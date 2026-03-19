"""Regime detection for futures-aware market state classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import median
from tempfile import NamedTemporaryFile
from typing import Any

import yaml


DEFAULT_REASONS_LIMIT = 6
PRIMARY_REGIMES = (
    "trend_up",
    "trend_down",
    "range",
    "low_vol",
    "high_vol",
    "stress_panic",
)


@dataclass(frozen=True)
class SymbolFeatureSnapshot:
    pair: str
    trend_spread_pct: float
    slope_pct: float
    adx: float
    volatility_ratio: float
    std_ratio: float
    candle_spread_ratio: float
    volume_spike: float
    recent_move_pct: float
    recent_move_abs_pct: float
    funding_bps: float | None
    ltf_trend_spread_pct: float
    ltf_slope_pct: float
    pullback_distance_pct: float


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def _normalize_pair_to_stem(pair: str) -> str:
    normalized = pair.replace("/", "_").replace(":", "_")
    return normalized.replace("-", "_")


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    ema_values = [values[0]]
    for value in values[1:]:
        ema_values.append(alpha * value + (1.0 - alpha) * ema_values[-1])
    return ema_values


def _pct_change(current: float, reference: float) -> float:
    if abs(reference) <= 1e-9:
        return 0.0
    return ((current - reference) / reference) * 100.0


def _average_true_range(highs: list[float], lows: list[float], closes: list[float], period: int) -> float:
    if len(highs) < 2 or len(lows) < 2 or len(closes) < 2:
        return 0.0
    true_ranges: list[float] = []
    for index in range(1, len(closes)):
        current_high = highs[index]
        current_low = lows[index]
        previous_close = closes[index - 1]
        true_ranges.append(
            max(
                current_high - current_low,
                abs(current_high - previous_close),
                abs(current_low - previous_close),
            )
        )
    if not true_ranges:
        return 0.0
    window = true_ranges[-period:] if len(true_ranges) >= period else true_ranges
    return sum(window) / len(window)


def _rolling_std(values: list[float], period: int) -> float:
    if len(values) < 2:
        return 0.0
    window = values[-period:] if len(values) >= period else values
    mean = sum(window) / len(window)
    variance = sum((value - mean) ** 2 for value in window) / len(window)
    return math.sqrt(max(variance, 0.0))


def _adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if min(len(highs), len(lows), len(closes)) < period + 2:
        return 0.0

    plus_dm: list[float] = []
    minus_dm: list[float] = []
    true_ranges: list[float] = []
    for index in range(1, len(closes)):
        up_move = highs[index] - highs[index - 1]
        down_move = lows[index - 1] - lows[index]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        true_ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )

    if len(true_ranges) < period:
        return 0.0

    dx_values: list[float] = []
    for index in range(period - 1, len(true_ranges)):
        tr_sum = sum(true_ranges[index - period + 1 : index + 1])
        if tr_sum <= 1e-9:
            continue
        plus_sum = sum(plus_dm[index - period + 1 : index + 1])
        minus_sum = sum(minus_dm[index - period + 1 : index + 1])
        plus_di = (plus_sum / tr_sum) * 100.0
        minus_di = (minus_sum / tr_sum) * 100.0
        denominator = plus_di + minus_di
        if denominator <= 1e-9:
            dx = 0.0
        else:
            dx = abs(plus_di - minus_di) / denominator * 100.0
        dx_values.append(dx)

    if not dx_values:
        return 0.0
    window = dx_values[-period:] if len(dx_values) >= period else dx_values
    return sum(window) / len(window)


def _read_feather_records(path: Path) -> list[dict[str, Any]]:
    import pandas as pd

    frame = pd.read_feather(path)
    if "date" in frame.columns:
        frame = frame.sort_values("date")
    return frame.to_dict("records")


class RegimeDetector:
    """Classifies current futures market state into operational regimes."""

    def __init__(
        self,
        *,
        user_data_dir: Path,
        output_dir: Path,
        research_dir: Path,
        definition_path: Path | None = None,
    ) -> None:
        self.user_data_dir = user_data_dir
        self.market_data_dir = user_data_dir / "data" / "binance" / "futures"
        self.output_dir = output_dir
        self.research_dir = research_dir
        self.definition_path = definition_path or (
            research_dir / "regimes" / "regime_definition_v1.yaml"
        )

    def latest_report(self) -> dict[str, Any] | None:
        path = self.output_dir / "latest.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.output_dir.exists():
            return []
        reports: list[dict[str, Any]] = []
        for path in sorted(self.output_dir.glob("regime-*.json"), reverse=True):
            reports.append(json.loads(path.read_text(encoding="utf-8")))
            if len(reports) >= limit:
                break
        return reports

    def generate_report(self) -> dict[str, Any]:
        definition = self._load_definition()
        previous_report = self.latest_report()
        candidate_manifests = self._load_candidate_manifests()
        symbol_features = self._build_symbol_features(definition)
        feature_snapshot = self._aggregate_features(symbol_features, definition)

        raw_classification = self._classify(feature_snapshot, definition)
        stabilized = self._apply_hysteresis(
            raw_classification=raw_classification,
            previous_report=previous_report,
            definition=definition,
        )

        htf_bias = self._derive_htf_bias(feature_snapshot, definition)
        market_state = self._derive_market_state(
            feature_snapshot=feature_snapshot,
            primary_regime=stabilized["primary_regime"],
            htf_bias=htf_bias,
            definition=definition,
        )
        ltf_execution_state = self._derive_ltf_execution_state(
            feature_snapshot=feature_snapshot,
            primary_regime=stabilized["primary_regime"],
            htf_bias=htf_bias,
            market_state=market_state,
            definition=definition,
        )
        volatility_phase = self._derive_volatility_phase(
            feature_snapshot=feature_snapshot,
            previous_report=previous_report,
            definition=definition,
        )
        market_phase = self._derive_market_phase(
            primary_regime=stabilized["primary_regime"],
            market_state=market_state,
            ltf_execution_state=ltf_execution_state,
            volatility_phase=volatility_phase,
            bars_in_regime=stabilized["regime_persistence"]["bars_in_regime"],
            definition=definition,
        )
        active_event_flags = self._derive_active_event_flags(
            feature_snapshot=feature_snapshot,
            primary_regime=stabilized["primary_regime"],
            htf_bias=htf_bias,
            definition=definition,
        )
        consensus = self._derive_symbol_states(symbol_features, definition)
        bias = self._derive_bias(
            primary_regime=stabilized["primary_regime"],
            htf_bias=htf_bias,
        )
        alignment_score = self._derive_alignment_score(
            confidence=stabilized["confidence"],
            htf_bias=htf_bias,
            market_state=market_state,
            ltf_execution_state=ltf_execution_state,
            consensus_strength=consensus["consensus_strength"],
        )
        signals = self._build_signals(
            feature_snapshot=feature_snapshot,
            primary_regime=stabilized["primary_regime"],
            htf_bias=htf_bias,
            market_state=market_state,
            ltf_execution_state=ltf_execution_state,
            market_phase=market_phase,
            volatility_phase=volatility_phase,
            consensus_strength=consensus["consensus_strength"],
            definition=definition,
        )
        execution_constraints = self._derive_execution_constraints(
            primary_regime=stabilized["primary_regime"],
            market_state=market_state,
            ltf_execution_state=ltf_execution_state,
            market_phase=market_phase,
            risk_level=stabilized["risk_level"],
            consensus_strength=consensus["consensus_strength"],
            active_event_flags=active_event_flags,
            cooldown_remaining_bars=stabilized["regime_persistence"]["cooldown_remaining_bars"],
        )
        position_size_multiplier = self._derive_position_size_multiplier(
            risk_level=stabilized["risk_level"],
            alignment_score=alignment_score,
            execution_constraints=execution_constraints,
        )
        entry_aggressiveness = self._derive_entry_aggressiveness(
            alignment_score=alignment_score,
            risk_level=stabilized["risk_level"],
            execution_constraints=execution_constraints,
            market_phase=market_phase,
        )
        eligible, blocked = self._candidate_eligibility(
            candidate_manifests,
            primary_regime=stabilized["primary_regime"],
            htf_bias=htf_bias,
            market_state=market_state,
            market_phase=market_phase,
            execution_constraints=execution_constraints,
        )
        strategy_priority_order = self._rank_candidates(
            manifests=candidate_manifests,
            eligible_candidate_ids=eligible,
            bias=bias,
            primary_regime=stabilized["primary_regime"],
            market_state=market_state,
            market_phase=market_phase,
        )

        report = {
            "generated_at": _now_iso(),
            "asof_timeframe": definition.get("asof_timeframe", "1h"),
            "universe": [item.get("pair") for item in symbol_features],
            "primary_regime": stabilized["primary_regime"],
            "confidence": round(stabilized["confidence"], 4),
            "risk_level": stabilized["risk_level"],
            "trend_strength": feature_snapshot["trend_strength"],
            "volatility_level": feature_snapshot["volatility_level"],
            "volume_state": feature_snapshot["volume_state"],
            "derivatives_state": feature_snapshot["derivatives_state"],
            "feature_snapshot": feature_snapshot,
            "reasons": stabilized["reasons"][:DEFAULT_REASONS_LIMIT],
            "eligible_candidate_ids": eligible,
            "blocked_candidate_ids": blocked,
            "candidate_freeze_mode": definition.get("freeze_build_mode", "freeze_build_keep_dry_run"),
            "htf_bias": htf_bias,
            "market_state": market_state,
            "ltf_execution_state": ltf_execution_state,
            "bias": bias,
            "alignment_score": alignment_score,
            "market_phase": market_phase,
            "volatility_phase": volatility_phase,
            "active_event_flags": active_event_flags,
            "signals": signals,
            "regime_persistence": stabilized["regime_persistence"],
            "position_size_multiplier": position_size_multiplier,
            "entry_aggressiveness": entry_aggressiveness,
            "strategy_priority_order": strategy_priority_order,
            "execution_constraints": execution_constraints,
            "btc_state": consensus["btc_state"],
            "eth_state": consensus["eth_state"],
            "market_consensus": consensus["market_consensus"],
            "consensus_strength": consensus["consensus_strength"],
            "smoothed_scores": stabilized["smoothed_scores"],
        }
        self._write_report(report)
        return report

    def _load_definition(self) -> dict[str, Any]:
        return yaml.safe_load(self.definition_path.read_text(encoding="utf-8")) or {}

    def _load_candidate_manifests(self) -> list[dict[str, Any]]:
        manifests: list[dict[str, Any]] = []
        for path in sorted((self.research_dir / "candidates").glob("*/strategy_manifest.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            manifests.append(payload)
        return manifests

    def _build_symbol_features(self, definition: dict[str, Any]) -> list[dict[str, Any]]:
        symbol_features: list[dict[str, Any]] = []
        universe = definition.get("universe") or [
            "BTC/USDT:USDT",
            "ETH/USDT:USDT",
        ]
        for pair in universe:
            symbol_features.append(self._compute_symbol_features(pair))
        return symbol_features

    def _compute_symbol_features(self, pair: str) -> dict[str, Any]:
        stem = _normalize_pair_to_stem(pair)
        frame_5m = _read_feather_records(self.market_data_dir / f"{stem}-5m-futures.feather")
        frame_1h = _read_feather_records(self.market_data_dir / f"{stem}-1h-futures.feather")
        funding_path = self.market_data_dir / f"{stem}-1h-funding_rate.feather"
        funding_frame = _read_feather_records(funding_path) if funding_path.exists() else []

        closes_5m = [_safe_float(row.get("close")) for row in frame_5m]
        highs_5m = [_safe_float(row.get("high")) for row in frame_5m]
        lows_5m = [_safe_float(row.get("low")) for row in frame_5m]
        volumes_5m = [_safe_float(row.get("volume")) for row in frame_5m]

        closes_1h = [_safe_float(row.get("close")) for row in frame_1h]
        highs_1h = [_safe_float(row.get("high")) for row in frame_1h]
        lows_1h = [_safe_float(row.get("low")) for row in frame_1h]

        atr_short = _average_true_range(highs_5m, lows_5m, closes_5m, period=14)
        atr_long = _average_true_range(highs_5m, lows_5m, closes_5m, period=48)
        volatility_ratio = atr_short / atr_long if atr_long > 1e-9 else 1.0

        returns_5m = [
            (closes_5m[index] - closes_5m[index - 1]) / closes_5m[index - 1]
            for index in range(1, len(closes_5m))
            if closes_5m[index - 1] > 1e-9
        ]
        std_short = _rolling_std(returns_5m, 24)
        std_long = _rolling_std(returns_5m, 96)
        std_ratio = std_short / std_long if std_long > 1e-9 else 1.0

        recent_volume_window = volumes_5m[-48:] if len(volumes_5m) >= 48 else volumes_5m
        volume_spike = (
            volumes_5m[-1] / max(median(recent_volume_window), 1e-9)
            if recent_volume_window
            else 1.0
        )

        candle_spreads = [
            (highs_5m[index] - lows_5m[index]) / max(closes_5m[index], 1e-9)
            for index in range(max(0, len(closes_5m) - 24), len(closes_5m))
        ]
        candle_spread_ratio = median(candle_spreads) if candle_spreads else 0.0
        recent_move_pct = _pct_change(closes_5m[-1], closes_5m[-7]) if len(closes_5m) >= 7 else 0.0
        recent_move_abs_pct = abs(recent_move_pct)

        ema_fast = _ema(closes_1h, 12)
        ema_slow = _ema(closes_1h, 36)
        trend_spread_pct = (
            ((ema_fast[-1] - ema_slow[-1]) / max(closes_1h[-1], 1e-9)) * 100.0
            if ema_fast and ema_slow and closes_1h
            else 0.0
        )
        slope_reference_index = -6 if len(ema_fast) >= 6 else 0
        slope_pct = _pct_change(ema_fast[-1], ema_fast[slope_reference_index]) if len(ema_fast) >= 2 else 0.0
        adx_value = _adx(highs_1h, lows_1h, closes_1h, period=14)

        ema_fast_5m = _ema(closes_5m, 8)
        ema_slow_5m = _ema(closes_5m, 21)
        ltf_trend_spread_pct = (
            ((ema_fast_5m[-1] - ema_slow_5m[-1]) / max(closes_5m[-1], 1e-9)) * 100.0
            if ema_fast_5m and ema_slow_5m and closes_5m
            else 0.0
        )
        ltf_slope_reference_index = -6 if len(ema_fast_5m) >= 6 else 0
        ltf_slope_pct = (
            _pct_change(ema_fast_5m[-1], ema_fast_5m[ltf_slope_reference_index])
            if len(ema_fast_5m) >= 2
            else 0.0
        )
        pullback_distance_pct = (
            _pct_change(closes_5m[-1], ema_fast_5m[-1])
            if ema_fast_5m and closes_5m
            else 0.0
        )

        funding_bps = None
        if funding_frame:
            latest_funding = funding_frame[-1]
            for field_name in ("fundingRate", "funding_rate", "value", "close", "open"):
                if field_name in latest_funding:
                    funding_bps = _safe_float(latest_funding.get(field_name)) * 10000.0
                    break

        snapshot = SymbolFeatureSnapshot(
            pair=pair,
            trend_spread_pct=round(trend_spread_pct, 4),
            slope_pct=round(slope_pct, 4),
            adx=round(adx_value, 4),
            volatility_ratio=round(volatility_ratio, 4),
            std_ratio=round(std_ratio, 4),
            candle_spread_ratio=round(candle_spread_ratio, 6),
            volume_spike=round(volume_spike, 4),
            recent_move_pct=round(recent_move_pct, 4),
            recent_move_abs_pct=round(recent_move_abs_pct, 4),
            funding_bps=round(funding_bps, 4) if funding_bps is not None else None,
            ltf_trend_spread_pct=round(ltf_trend_spread_pct, 4),
            ltf_slope_pct=round(ltf_slope_pct, 4),
            pullback_distance_pct=round(pullback_distance_pct, 4),
        )
        return snapshot.__dict__

    def _aggregate_features(
        self,
        symbol_features: list[dict[str, Any]],
        definition: dict[str, Any],
    ) -> dict[str, Any]:
        numeric_keys = (
            "trend_spread_pct",
            "slope_pct",
            "adx",
            "volatility_ratio",
            "std_ratio",
            "candle_spread_ratio",
            "volume_spike",
            "recent_move_pct",
            "recent_move_abs_pct",
            "ltf_trend_spread_pct",
            "ltf_slope_pct",
            "pullback_distance_pct",
        )
        aggregates: dict[str, float] = {}
        for key in numeric_keys:
            values = [_safe_float(item.get(key)) for item in symbol_features]
            aggregates[key] = round(sum(values) / max(len(values), 1), 6)

        funding_values = [
            _safe_float(item.get("funding_bps"))
            for item in symbol_features
            if item.get("funding_bps") is not None
        ]
        funding_abs_bps = (
            round(sum(abs(value) for value in funding_values) / len(funding_values), 6)
            if funding_values
            else None
        )
        funding_mean_bps = (
            round(sum(funding_values) / len(funding_values), 6)
            if funding_values
            else None
        )

        decorated = self._decorate_feature_snapshot(
            {
                **aggregates,
                "funding_abs_bps": funding_abs_bps,
                "funding_mean_bps": funding_mean_bps,
            },
            definition,
        )
        return {
            **decorated,
            "symbols": symbol_features,
        }

    def _decorate_feature_snapshot(
        self,
        metrics: dict[str, Any],
        definition: dict[str, Any],
    ) -> dict[str, Any]:
        thresholds = definition.get("thresholds", {})
        trend_strength = round(
            min(1.0, _safe_float(metrics.get("adx")) / max(_safe_float(thresholds.get("adx_trend_min"), 20.0), 1.0)),
            4,
        )
        volatility_ratio = _safe_float(metrics.get("volatility_ratio"), 1.0)
        volume_spike = _safe_float(metrics.get("volume_spike"), 1.0)
        funding_abs_bps = metrics.get("funding_abs_bps")

        if volatility_ratio >= _safe_float(thresholds.get("stress_volatility_ratio_min"), 1.8):
            volatility_level = "extreme"
        elif volatility_ratio >= _safe_float(thresholds.get("high_volatility_ratio_min"), 1.2):
            volatility_level = "high"
        elif volatility_ratio <= _safe_float(thresholds.get("low_volatility_ratio_max"), 0.85):
            volatility_level = "low"
        else:
            volatility_level = "normal"

        if volume_spike >= _safe_float(thresholds.get("stress_volume_spike_min"), 1.8):
            volume_state = "spike"
        elif volume_spike >= _safe_float(thresholds.get("volume_spike_high"), 1.25):
            volume_state = "elevated"
        elif volume_spike <= _safe_float(thresholds.get("low_volume_spike_max"), 0.9):
            volume_state = "thin"
        else:
            volume_state = "normal"

        if funding_abs_bps is None:
            derivatives_state = "unavailable"
        elif _safe_float(funding_abs_bps) >= _safe_float(thresholds.get("funding_extreme_bps"), 8.0):
            derivatives_state = "stretched"
        elif _safe_float(funding_abs_bps) >= _safe_float(thresholds.get("funding_elevated_bps"), 4.0):
            derivatives_state = "elevated"
        else:
            derivatives_state = "neutral"

        return {
            **metrics,
            "trend_strength": trend_strength,
            "volatility_level": volatility_level,
            "volume_state": volume_state,
            "derivatives_state": derivatives_state,
        }

    def _classify(self, feature_snapshot: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
        thresholds = definition.get("thresholds", {})
        scores = {regime: 0.0 for regime in PRIMARY_REGIMES}
        reasons: dict[str, list[str]] = {regime: [] for regime in PRIMARY_REGIMES}

        adx = _safe_float(feature_snapshot.get("adx"))
        spread = _safe_float(feature_snapshot.get("trend_spread_pct"))
        slope = _safe_float(feature_snapshot.get("slope_pct"))
        volatility_ratio = _safe_float(feature_snapshot.get("volatility_ratio"), 1.0)
        std_ratio = _safe_float(feature_snapshot.get("std_ratio"), 1.0)
        candle_spread_ratio = _safe_float(feature_snapshot.get("candle_spread_ratio"))
        volume_spike = _safe_float(feature_snapshot.get("volume_spike"), 1.0)
        recent_move_abs_pct = _safe_float(feature_snapshot.get("recent_move_abs_pct"))
        funding_abs_bps = _safe_float(feature_snapshot.get("funding_abs_bps"), 0.0)

        if spread >= _safe_float(thresholds.get("trend_spread_min_pct"), 0.12):
            scores["trend_up"] += 2.0
            reasons["trend_up"].append("EMA spread wskazuje trend wzrostowy.")
        if slope >= _safe_float(thresholds.get("slope_min_pct"), 0.08):
            scores["trend_up"] += 2.0
            reasons["trend_up"].append("Szybka srednia rośnie na 1h.")
        if spread <= -_safe_float(thresholds.get("trend_spread_min_pct"), 0.12):
            scores["trend_down"] += 2.0
            reasons["trend_down"].append("EMA spread wskazuje trend spadkowy.")
        if slope <= -_safe_float(thresholds.get("slope_min_pct"), 0.08):
            scores["trend_down"] += 2.0
            reasons["trend_down"].append("Szybka srednia spada na 1h.")

        if adx >= _safe_float(thresholds.get("adx_trend_min"), 22.0):
            scores["trend_up"] += 2.0
            scores["trend_down"] += 2.0
            reasons["trend_up"].append("ADX potwierdza trend.")
            reasons["trend_down"].append("ADX potwierdza trend.")
        if adx < _safe_float(thresholds.get("adx_range_max"), 18.0):
            scores["range"] += 2.0
            reasons["range"].append("ADX jest niski i nie potwierdza trendu.")

        if abs(spread) <= _safe_float(thresholds.get("range_spread_max_pct"), 0.08):
            scores["range"] += 2.0
            reasons["range"].append("Trend spread jest zbyt mały na czysty trend.")

        if volatility_ratio <= _safe_float(thresholds.get("low_volatility_ratio_max"), 0.85):
            scores["low_vol"] += 2.0
            reasons["low_vol"].append("ATR short/long wskazuje kompresję zmienności.")
        if candle_spread_ratio <= _safe_float(thresholds.get("low_candle_spread_max"), 0.0025):
            scores["low_vol"] += 1.5
            reasons["low_vol"].append("Średnie spready świec są małe.")
        if volume_spike <= _safe_float(thresholds.get("low_volume_spike_max"), 0.9):
            scores["low_vol"] += 1.0
            reasons["low_vol"].append("Wolumen jest cienki wobec mediany.")

        if volatility_ratio >= _safe_float(thresholds.get("high_volatility_ratio_min"), 1.2):
            scores["high_vol"] += 2.0
            reasons["high_vol"].append("ATR short/long wskazuje ekspansję zmienności.")
        if std_ratio >= _safe_float(thresholds.get("high_std_ratio_min"), 1.15):
            scores["high_vol"] += 1.5
            reasons["high_vol"].append("Odchylenie krótkie przyspiesza wobec długiego.")
        if volume_spike >= _safe_float(thresholds.get("volume_spike_high"), 1.25):
            scores["high_vol"] += 1.0
            reasons["high_vol"].append("Wolumen potwierdza ruch.")

        if recent_move_abs_pct >= _safe_float(thresholds.get("stress_move_abs_pct_min"), 1.6):
            scores["stress_panic"] += 2.0
            reasons["stress_panic"].append("Ruch cenowy jest gwałtowny.")
        if volatility_ratio >= _safe_float(thresholds.get("stress_volatility_ratio_min"), 1.8):
            scores["stress_panic"] += 2.0
            reasons["stress_panic"].append("Zmienność weszła w strefę stresu.")
        if volume_spike >= _safe_float(thresholds.get("stress_volume_spike_min"), 1.8):
            scores["stress_panic"] += 1.5
            reasons["stress_panic"].append("Wolumen wszedł w strefę wymuszonego ruchu.")
        if funding_abs_bps >= _safe_float(thresholds.get("funding_extreme_bps"), 8.0):
            scores["stress_panic"] += 1.0
            reasons["stress_panic"].append("Funding wskazuje mocno rozciągnięty rynek.")

        ordered = sorted(
            scores.items(),
            key=lambda item: (
                item[1],
                1 if item[0] == "stress_panic" else 0,
                1 if item[0] in {"trend_up", "trend_down"} else 0,
            ),
            reverse=True,
        )
        primary_regime, primary_score = ordered[0]
        second_score = ordered[1][1] if len(ordered) > 1 else 0.0
        confidence = max(0.2, min(0.99, 0.45 + (primary_score - second_score) * 0.08 + primary_score * 0.05))

        if primary_regime in {"stress_panic", "high_vol"}:
            risk_level = "high"
        elif primary_regime in {"trend_down", "range"}:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "primary_regime": primary_regime,
            "confidence": confidence,
            "risk_level": risk_level,
            "scores": {key: round(value, 4) for key, value in scores.items()},
            "reasons_by_regime": reasons,
            "reasons": reasons[primary_regime],
        }

    def _apply_hysteresis(
        self,
        *,
        raw_classification: dict[str, Any],
        previous_report: dict[str, Any] | None,
        definition: dict[str, Any],
    ) -> dict[str, Any]:
        thresholds = definition.get("thresholds", {})
        previous_regime = (previous_report or {}).get("primary_regime")
        raw_primary_regime = raw_classification.get("primary_regime")
        previous_scores = (previous_report or {}).get("smoothed_scores") or {}
        score_scale = max(_safe_float(thresholds.get("score_normalization_max"), 6.5), 1.0)
        smoothing_alpha = min(max(_safe_float(thresholds.get("smoothing_alpha"), 0.45), 0.05), 1.0)
        enter_threshold = _safe_float(thresholds.get("enter_score_threshold"), 0.75)
        exit_threshold = _safe_float(thresholds.get("exit_score_threshold"), 0.55)
        min_bars_in_regime = max(int(_safe_float(thresholds.get("min_bars_in_regime"), 3)), 1)
        switch_cooldown_bars = max(int(_safe_float(thresholds.get("switch_cooldown_bars"), 2)), 0)
        bar_minutes = max(int(_safe_float(thresholds.get("bar_minutes"), 5)), 1)

        normalized_scores = {
            key: round(min(1.0, _safe_float(value) / score_scale), 4)
            for key, value in (raw_classification.get("scores") or {}).items()
        }
        smoothed_scores = {
            key: round(
                smoothing_alpha * normalized_scores.get(key, 0.0)
                + (1.0 - smoothing_alpha) * _safe_float(previous_scores.get(key), normalized_scores.get(key, 0.0)),
                4,
            )
            for key in PRIMARY_REGIMES
        }
        ordered = sorted(smoothed_scores.items(), key=lambda item: item[1], reverse=True)
        candidate_regime = ordered[0][0]
        candidate_score = ordered[0][1]
        previous_score = _safe_float(previous_scores.get(previous_regime), 0.0) if previous_regime else 0.0

        delta_bars = 1
        if previous_report:
            previous_generated_at = self._parse_iso(previous_report.get("generated_at"))
            current_generated_at = self._parse_iso(_now_iso())
            if previous_generated_at and current_generated_at:
                delta_minutes = max((current_generated_at - previous_generated_at).total_seconds() / 60.0, 0.0)
                delta_bars = max(int(round(delta_minutes / bar_minutes)), 1)

        previous_persistence = (previous_report or {}).get("regime_persistence") or {}
        previous_bars_in_regime = max(int(_safe_float(previous_persistence.get("bars_in_regime"), 0)), 0)
        previous_minutes_in_regime = max(int(_safe_float(previous_persistence.get("minutes_in_regime"), 0)), 0)
        previous_cooldown = max(int(_safe_float(previous_persistence.get("cooldown_remaining_bars"), 0)), 0)

        stable_regime = candidate_regime
        kept_previous = False
        if previous_regime and previous_regime != candidate_regime:
            if previous_cooldown > 0 or previous_bars_in_regime < min_bars_in_regime:
                stable_regime = previous_regime
                kept_previous = True
            elif candidate_score < enter_threshold:
                stable_regime = previous_regime
                kept_previous = True
            elif previous_score >= exit_threshold:
                stable_regime = previous_regime
                kept_previous = True

        if previous_regime == stable_regime:
            bars_in_regime = previous_bars_in_regime + delta_bars
            minutes_in_regime = previous_minutes_in_regime + delta_bars * bar_minutes
            cooldown_remaining_bars = max(previous_cooldown - delta_bars, 0)
        else:
            bars_in_regime = 1
            minutes_in_regime = bar_minutes
            cooldown_remaining_bars = switch_cooldown_bars

        mature_regime_bars = max(int(_safe_float(thresholds.get("mature_regime_bars"), 6)), 2)
        if bars_in_regime <= 2:
            regime_age_state = "fresh"
        elif bars_in_regime >= mature_regime_bars:
            regime_age_state = "mature"
        else:
            regime_age_state = "developing"

        stable_reasons = list(raw_classification["reasons_by_regime"].get(stable_regime) or [])
        if kept_previous:
            stable_reasons.append("Hysteresis utrzymala poprzedni reżim do czasu mocniejszego potwierdzenia zmiany.")
        elif previous_regime == stable_regime and raw_primary_regime != stable_regime:
            stable_reasons.append("Hysteresis i smoothing utrzymaly poprzedni reżim mimo krótkoterminowego sygnału zmiany.")

        second_score = ordered[1][1] if len(ordered) > 1 else 0.0
        stable_confidence = max(
            0.2,
            min(
                0.99,
                0.45
                + (smoothed_scores.get(stable_regime, 0.0) - second_score) * 0.5
                + min(bars_in_regime, mature_regime_bars) / mature_regime_bars * 0.12,
            ),
        )
        stable_risk_level = raw_classification["risk_level"]
        if stable_regime in {"stress_panic", "high_vol"}:
            stable_risk_level = "high"
        elif stable_regime in {"trend_down", "range"}:
            stable_risk_level = "medium"
        else:
            stable_risk_level = "low"

        return {
            "primary_regime": stable_regime,
            "confidence": stable_confidence,
            "risk_level": stable_risk_level,
            "smoothed_scores": smoothed_scores,
            "reasons": stable_reasons,
            "regime_persistence": {
                "previous_primary_regime": previous_regime,
                "bars_in_regime": bars_in_regime,
                "minutes_in_regime": minutes_in_regime,
                "regime_age_state": regime_age_state,
                "cooldown_remaining_bars": cooldown_remaining_bars,
            },
        }

    def _derive_htf_bias(self, feature_snapshot: dict[str, Any], definition: dict[str, Any]) -> str:
        thresholds = definition.get("thresholds", {})
        spread = _safe_float(feature_snapshot.get("trend_spread_pct"))
        slope = _safe_float(feature_snapshot.get("slope_pct"))
        adx = _safe_float(feature_snapshot.get("adx"))
        if (
            spread >= _safe_float(thresholds.get("htf_bias_spread_min_pct"), 0.10)
            and slope >= _safe_float(thresholds.get("htf_bias_slope_min_pct"), 0.06)
            and adx >= _safe_float(thresholds.get("adx_trend_min"), 22.0)
        ):
            return "long"
        if (
            spread <= -_safe_float(thresholds.get("htf_bias_spread_min_pct"), 0.10)
            and slope <= -_safe_float(thresholds.get("htf_bias_slope_min_pct"), 0.06)
            and adx >= _safe_float(thresholds.get("adx_trend_min"), 22.0)
        ):
            return "short"
        return "neutral"

    def _derive_market_state(
        self,
        *,
        feature_snapshot: dict[str, Any],
        primary_regime: str,
        htf_bias: str,
        definition: dict[str, Any],
    ) -> str:
        thresholds = definition.get("thresholds", {})
        ltf_spread = _safe_float(feature_snapshot.get("ltf_trend_spread_pct"))
        ltf_slope = _safe_float(feature_snapshot.get("ltf_slope_pct"))
        pullback_distance = _safe_float(feature_snapshot.get("pullback_distance_pct"))
        pullback_threshold = _safe_float(thresholds.get("pullback_distance_min_pct"), 0.05)
        transition_spread_max = _safe_float(thresholds.get("ltf_transition_spread_max_pct"), 0.03)

        if primary_regime in {"range", "low_vol"}:
            return "range"
        if htf_bias == "short" and pullback_distance >= pullback_threshold:
            return "pullback"
        if htf_bias == "long" and pullback_distance <= -pullback_threshold:
            return "pullback"
        if abs(ltf_spread) <= transition_spread_max and abs(ltf_slope) <= transition_spread_max:
            return "transition"
        return "trend"

    def _derive_ltf_execution_state(
        self,
        *,
        feature_snapshot: dict[str, Any],
        primary_regime: str,
        htf_bias: str,
        market_state: str,
        definition: dict[str, Any],
    ) -> str:
        thresholds = definition.get("thresholds", {})
        ltf_spread = _safe_float(feature_snapshot.get("ltf_trend_spread_pct"))
        ltf_slope = _safe_float(feature_snapshot.get("ltf_slope_pct"))
        recent_move_abs_pct = _safe_float(feature_snapshot.get("recent_move_abs_pct"))
        adx = _safe_float(feature_snapshot.get("adx"))
        late_move_abs_pct = _safe_float(thresholds.get("late_move_abs_pct"), 0.9)
        noise_adx_max = _safe_float(thresholds.get("noise_adx_max"), 16.0)

        if market_state == "pullback":
            if htf_bias == "short" and ltf_spread < 0 and ltf_slope < 0:
                return "momentum_resuming"
            if htf_bias == "long" and ltf_spread > 0 and ltf_slope > 0:
                return "momentum_resuming"
        if recent_move_abs_pct >= late_move_abs_pct and primary_regime in {"trend_up", "trend_down", "high_vol"}:
            return "late_move"
        if adx <= noise_adx_max or market_state == "range":
            return "noisy"
        return "neutral"

    def _derive_volatility_phase(
        self,
        *,
        feature_snapshot: dict[str, Any],
        previous_report: dict[str, Any] | None,
        definition: dict[str, Any],
    ) -> str:
        thresholds = definition.get("thresholds", {})
        volatility_ratio = _safe_float(feature_snapshot.get("volatility_ratio"), 1.0)
        std_ratio = _safe_float(feature_snapshot.get("std_ratio"), 1.0)
        previous_level = (previous_report or {}).get("volatility_phase") or (previous_report or {}).get("volatility_level")

        if (
            volatility_ratio <= _safe_float(thresholds.get("compression_volatility_ratio_max"), 0.9)
            and std_ratio <= _safe_float(thresholds.get("compression_std_ratio_max"), 0.95)
        ):
            return "compression"
        if volatility_ratio >= _safe_float(thresholds.get("extreme_volatility_ratio_min"), 1.8):
            return "extreme"
        if (
            previous_level in {"expanding", "extreme", "high"}
            and volatility_ratio <= _safe_float(thresholds.get("cooling_volatility_ratio_max"), 1.05)
        ):
            return "cooling"
        if volatility_ratio >= _safe_float(thresholds.get("expansion_volatility_ratio_min"), 1.15):
            return "expanding"
        return "cooling" if previous_level in {"expanding", "extreme"} else "compression"

    def _derive_market_phase(
        self,
        *,
        primary_regime: str,
        market_state: str,
        ltf_execution_state: str,
        volatility_phase: str,
        bars_in_regime: int,
        definition: dict[str, Any],
    ) -> str:
        mature_regime_bars = max(int(_safe_float(definition.get("thresholds", {}).get("mature_regime_bars"), 6)), 2)
        if market_state == "pullback":
            return "pullback"
        if volatility_phase == "compression":
            return "compression"
        if volatility_phase in {"expanding", "extreme"} or ltf_execution_state == "momentum_resuming":
            return "expansion"
        if primary_regime in {"trend_up", "trend_down"} and bars_in_regime >= mature_regime_bars:
            return "mature_trend"
        return "transition"

    def _derive_active_event_flags(
        self,
        *,
        feature_snapshot: dict[str, Any],
        primary_regime: str,
        htf_bias: str,
        definition: dict[str, Any],
    ) -> dict[str, bool]:
        thresholds = definition.get("thresholds", {})
        recent_move_pct = _safe_float(feature_snapshot.get("recent_move_pct"))
        recent_move_abs_pct = _safe_float(feature_snapshot.get("recent_move_abs_pct"))
        volatility_ratio = _safe_float(feature_snapshot.get("volatility_ratio"))
        volume_spike = _safe_float(feature_snapshot.get("volume_spike"))
        funding_mean_bps = _safe_float(feature_snapshot.get("funding_mean_bps"), 0.0)

        stress_move = _safe_float(thresholds.get("stress_move_abs_pct_min"), 1.6)
        squeeze_move = _safe_float(thresholds.get("squeeze_move_abs_pct_min"), 1.2)
        event_confirmed = (
            recent_move_abs_pct >= squeeze_move
            and volatility_ratio >= _safe_float(thresholds.get("expansion_volatility_ratio_min"), 1.15)
            and volume_spike >= _safe_float(thresholds.get("volume_spike_high"), 1.25)
        )

        panic_flush = primary_regime == "stress_panic" and recent_move_pct <= -stress_move
        short_squeeze = event_confirmed and recent_move_pct >= squeeze_move and htf_bias == "short"
        long_squeeze = event_confirmed and recent_move_pct <= -squeeze_move and htf_bias == "long"
        capitulation = panic_flush and funding_mean_bps <= -_safe_float(thresholds.get("funding_elevated_bps"), 4.0)
        deleveraging = (
            primary_regime in {"stress_panic", "high_vol"}
            and event_confirmed
            and abs(funding_mean_bps) >= _safe_float(thresholds.get("funding_elevated_bps"), 4.0)
        )
        return {
            "panic_flush": panic_flush,
            "short_squeeze": short_squeeze,
            "long_squeeze": long_squeeze,
            "capitulation": capitulation,
            "deleveraging": deleveraging,
        }

    def _derive_symbol_states(
        self,
        symbol_features: list[dict[str, Any]],
        definition: dict[str, Any],
    ) -> dict[str, Any]:
        states: dict[str, dict[str, Any]] = {}
        biases: list[str] = []
        confidences: list[float] = []

        for symbol_feature in symbol_features:
            decorated = self._decorate_feature_snapshot(
                {
                    key: value
                    for key, value in symbol_feature.items()
                    if key != "pair"
                },
                definition,
            )
            classification = self._classify(decorated, definition)
            htf_bias = self._derive_htf_bias(decorated, definition)
            market_state = self._derive_market_state(
                feature_snapshot=decorated,
                primary_regime=classification["primary_regime"],
                htf_bias=htf_bias,
                definition=definition,
            )
            volatility_phase = self._derive_volatility_phase(
                feature_snapshot=decorated,
                previous_report=None,
                definition=definition,
            )
            market_phase = self._derive_market_phase(
                primary_regime=classification["primary_regime"],
                market_state=market_state,
                ltf_execution_state="neutral",
                volatility_phase=volatility_phase,
                bars_in_regime=1,
                definition=definition,
            )
            state = {
                "pair": symbol_feature["pair"],
                "primary_regime": classification["primary_regime"],
                "bias": self._derive_bias(primary_regime=classification["primary_regime"], htf_bias=htf_bias),
                "market_state": market_state,
                "market_phase": market_phase,
                "confidence": round(classification["confidence"], 4),
            }
            states[symbol_feature["pair"]] = state
            biases.append(state["bias"])
            confidences.append(state["confidence"])

        market_consensus = "mixed"
        consensus_strength = 0.25
        long_count = sum(1 for item in biases if item == "long")
        short_count = sum(1 for item in biases if item == "short")
        neutral_count = sum(1 for item in biases if item == "neutral")
        average_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        if long_count == len(biases) and long_count > 0:
            market_consensus = "strong_bullish"
            consensus_strength = min(1.0, 0.75 + average_confidence * 0.2)
        elif short_count == len(biases) and short_count > 0:
            market_consensus = "strong_bearish"
            consensus_strength = min(1.0, 0.75 + average_confidence * 0.2)
        elif long_count > 0 and short_count == 0:
            market_consensus = "weak_bullish"
            consensus_strength = min(0.75, 0.45 + average_confidence * 0.2)
        elif short_count > 0 and long_count == 0:
            market_consensus = "weak_bearish"
            consensus_strength = min(0.75, 0.45 + average_confidence * 0.2)
        elif neutral_count == len(biases):
            market_consensus = "neutral"
            consensus_strength = 0.35

        return {
            "btc_state": states.get("BTC/USDT:USDT"),
            "eth_state": states.get("ETH/USDT:USDT"),
            "market_consensus": market_consensus,
            "consensus_strength": round(consensus_strength, 4),
        }

    def _derive_bias(self, *, primary_regime: str, htf_bias: str) -> str:
        if htf_bias in {"long", "short"}:
            return htf_bias
        if primary_regime == "trend_up":
            return "long"
        if primary_regime == "trend_down":
            return "short"
        return "neutral"

    def _derive_alignment_score(
        self,
        *,
        confidence: float,
        htf_bias: str,
        market_state: str,
        ltf_execution_state: str,
        consensus_strength: float,
    ) -> float:
        base = confidence * 0.5 + consensus_strength * 0.25
        if htf_bias in {"long", "short"}:
            base += 0.15
        if market_state in {"trend", "pullback"}:
            base += 0.07
        if ltf_execution_state == "momentum_resuming":
            base += 0.08
        if ltf_execution_state == "noisy":
            base -= 0.12
        return round(max(0.0, min(1.0, base)), 4)

    def _build_signals(
        self,
        *,
        feature_snapshot: dict[str, Any],
        primary_regime: str,
        htf_bias: str,
        market_state: str,
        ltf_execution_state: str,
        market_phase: str,
        volatility_phase: str,
        consensus_strength: float,
        definition: dict[str, Any],
    ) -> dict[str, bool]:
        thresholds = definition.get("thresholds", {})
        return {
            "trend_strength_high": _safe_float(feature_snapshot.get("adx")) >= _safe_float(thresholds.get("adx_trend_min"), 22.0),
            "down_slope_confirmed": _safe_float(feature_snapshot.get("slope_pct")) <= -_safe_float(thresholds.get("slope_min_pct"), 0.08),
            "volatility_expanding": volatility_phase in {"expanding", "extreme"},
            "volume_spike": _safe_float(feature_snapshot.get("volume_spike")) >= _safe_float(thresholds.get("volume_spike_high"), 1.25),
            "funding_extreme": _safe_float(feature_snapshot.get("funding_abs_bps")) >= _safe_float(thresholds.get("funding_extreme_bps"), 8.0),
            "htf_ltf_aligned": htf_bias in {"long", "short"} and ltf_execution_state == "momentum_resuming",
            "phase_pullback": market_phase == "pullback",
            "phase_expansion": market_phase == "expansion",
            "noise_high": market_state == "range" or ltf_execution_state == "noisy" or consensus_strength < 0.45,
            "primary_regime_is_stress": primary_regime == "stress_panic",
        }

    def _derive_execution_constraints(
        self,
        *,
        primary_regime: str,
        market_state: str,
        ltf_execution_state: str,
        market_phase: str,
        risk_level: str,
        consensus_strength: float,
        active_event_flags: dict[str, bool],
        cooldown_remaining_bars: int,
    ) -> dict[str, bool]:
        no_trade_zone = primary_regime == "low_vol" or (market_state == "range" and consensus_strength < 0.5)
        high_noise_environment = market_state == "range" or ltf_execution_state == "noisy" or consensus_strength < 0.4
        post_shock_cooldown = cooldown_remaining_bars > 0 and any(active_event_flags.values())
        reduced_exposure_only = (
            risk_level in {"medium", "high"}
            or market_phase in {"transition", "compression"}
            or high_noise_environment
            or post_shock_cooldown
        )
        return {
            "no_trade_zone": no_trade_zone,
            "reduced_exposure_only": reduced_exposure_only and not no_trade_zone,
            "high_noise_environment": high_noise_environment,
            "post_shock_cooldown": post_shock_cooldown,
        }

    def _derive_position_size_multiplier(
        self,
        *,
        risk_level: str,
        alignment_score: float,
        execution_constraints: dict[str, bool],
    ) -> float:
        if execution_constraints["no_trade_zone"]:
            return 0.0
        base = {"low": 1.0, "medium": 0.8, "high": 0.6}.get(risk_level, 0.75)
        base *= 0.6 + alignment_score * 0.4
        if execution_constraints["reduced_exposure_only"]:
            base *= 0.8
        if execution_constraints["high_noise_environment"]:
            base *= 0.8
        if execution_constraints["post_shock_cooldown"]:
            base *= 0.7
        return round(max(0.0, min(1.25, base)), 4)

    def _derive_entry_aggressiveness(
        self,
        *,
        alignment_score: float,
        risk_level: str,
        execution_constraints: dict[str, bool],
        market_phase: str,
    ) -> str:
        if execution_constraints["no_trade_zone"]:
            return "blocked"
        if execution_constraints["post_shock_cooldown"] or execution_constraints["high_noise_environment"]:
            return "low"
        if risk_level == "high":
            return "low"
        if alignment_score >= 0.82 and market_phase in {"pullback", "expansion"}:
            return "high"
        if alignment_score >= 0.62:
            return "moderate"
        return "low"

    def _candidate_eligibility(
        self,
        manifests: list[dict[str, Any]],
        *,
        primary_regime: str,
        htf_bias: str,
        market_state: str,
        market_phase: str,
        execution_constraints: dict[str, bool],
    ) -> tuple[list[str], list[str]]:
        eligible: list[str] = []
        blocked: list[str] = []
        for manifest in manifests:
            candidate_id = str(manifest.get("strategy_id") or "")
            if not candidate_id:
                continue
            allowed_regimes = list(manifest.get("allowed_primary_regimes") or [])
            blocked_regimes = list(manifest.get("blocked_primary_regimes") or [])
            allowed_biases = list(manifest.get("allowed_htf_biases") or [])
            allowed_states = list(manifest.get("allowed_market_states") or [])
            blocked_states = list(manifest.get("blocked_market_states") or [])
            blocked_phases = list(manifest.get("blocked_market_phases") or [])
            policy = manifest.get("execution_constraints_policy") or {}

            if primary_regime in blocked_regimes:
                blocked.append(candidate_id)
                continue
            if allowed_regimes and primary_regime not in allowed_regimes:
                blocked.append(candidate_id)
                continue
            if allowed_biases and htf_bias not in allowed_biases:
                blocked.append(candidate_id)
                continue
            if market_state in blocked_states:
                blocked.append(candidate_id)
                continue
            if allowed_states and market_state not in allowed_states:
                blocked.append(candidate_id)
                continue
            if market_phase in blocked_phases:
                blocked.append(candidate_id)
                continue
            if execution_constraints["no_trade_zone"] and policy.get("no_trade_zone") == "block":
                blocked.append(candidate_id)
                continue
            if execution_constraints["post_shock_cooldown"] and policy.get("post_shock_cooldown") == "block":
                blocked.append(candidate_id)
                continue
            eligible.append(candidate_id)
        return eligible, blocked

    def _rank_candidates(
        self,
        *,
        manifests: list[dict[str, Any]],
        eligible_candidate_ids: list[str],
        bias: str,
        primary_regime: str,
        market_state: str,
        market_phase: str,
    ) -> list[str]:
        scored: list[tuple[float, str]] = []
        manifests_by_id = {
            str(manifest.get("strategy_id")): manifest
            for manifest in manifests
            if manifest.get("strategy_id")
        }
        for candidate_id in eligible_candidate_ids:
            manifest = manifests_by_id.get(candidate_id, {})
            score = 0.0
            if primary_regime in list(manifest.get("allowed_primary_regimes") or []):
                score += 3.0
            if bias in list(manifest.get("allowed_htf_biases") or []):
                score += 1.5
            if market_state in list(manifest.get("allowed_market_states") or []):
                score += 1.5
            if market_phase in list(manifest.get("preferred_market_phases") or []):
                score += 1.0
            if candidate_id.endswith("short_breakdown_v1") and bias == "short":
                score += 1.5
            if candidate_id.endswith("long_continuation_v1") and bias == "long":
                score += 1.5
            if candidate_id.endswith("baseline_v1"):
                score += 0.5
            scored.append((score, candidate_id))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [candidate_id for _, candidate_id in scored]

    def _parse_iso(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def _write_report(self, report: dict[str, Any]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = report["generated_at"].replace(":", "-")
        history_path = self.output_dir / f"regime-{stamp}.json"
        latest_path = self.output_dir / "latest.json"
        self._atomic_write_json(history_path, report)
        self._atomic_write_json(latest_path, report)

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as handle:
            temp_path = Path(handle.name)
            try:
                handle.write(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")
            except Exception:
                temp_path.unlink(missing_ok=True)
                raise
        temp_path.replace(path)
