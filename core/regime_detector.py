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
        replay_dir: Path,
        research_dir: Path,
        definition_path: Path | None = None,
    ) -> None:
        self.user_data_dir = user_data_dir
        self.market_data_dir = user_data_dir / "data" / "binance" / "futures"
        self.output_dir = output_dir
        self.replay_dir = replay_dir
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

    def latest_replay_report(self) -> dict[str, Any] | None:
        path = self.replay_dir / "latest.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_replay_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.replay_dir.exists():
            return []
        reports: list[dict[str, Any]] = []
        for path in sorted(self.replay_dir.glob("replay-*.json"), reverse=True):
            reports.append(json.loads(path.read_text(encoding="utf-8")))
            if len(reports) >= limit:
                break
        return reports

    def generate_report(self, *, derivatives_report: dict[str, Any] | None = None) -> dict[str, Any]:
        definition = self._load_definition()
        previous_report = self.latest_report()
        candidate_manifests = self._load_candidate_manifests()
        symbol_features = self._build_symbol_features(definition)
        feature_snapshot = self._aggregate_features(symbol_features, definition)
        feature_snapshot = self._merge_derivatives_context(
            feature_snapshot=feature_snapshot,
            derivatives_report=derivatives_report,
        )

        raw_classification = self._classify(feature_snapshot, definition)
        stabilized = self._apply_hysteresis(
            raw_classification=raw_classification,
            previous_report=previous_report,
            definition=definition,
            current_generated_at=_now_iso(),
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
        actionable_event_flags = self._derive_actionable_event_flags(
            active_event_flags=active_event_flags,
            derivatives_state=feature_snapshot.get("derivatives_state") or {},
        )
        derivatives_confidence_multiplier = self._derive_derivatives_confidence_multiplier(
            feature_snapshot.get("derivatives_state") or {}
        )
        adjusted_confidence = round(
            max(0.2, min(0.99, stabilized["confidence"] * derivatives_confidence_multiplier)),
            4,
        )
        consensus = self._derive_symbol_states(symbol_features, definition)
        bias = self._derive_bias(
            primary_regime=stabilized["primary_regime"],
            htf_bias=htf_bias,
        )
        alignment_score = self._derive_alignment_score(
            confidence=adjusted_confidence,
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
            active_event_flags=actionable_event_flags,
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
        risk_regime = self._derive_risk_regime(
            primary_regime=stabilized["primary_regime"],
            risk_level=stabilized["risk_level"],
            execution_constraints=execution_constraints,
            active_event_flags=actionable_event_flags,
            consensus_strength=consensus["consensus_strength"],
        )
        regime_quality = self._derive_regime_quality(
            alignment_score=alignment_score,
            execution_constraints=execution_constraints,
            market_phase=market_phase,
            active_event_flags=actionable_event_flags,
            derivatives_state=feature_snapshot.get("derivatives_state") or {},
        )
        lead_symbol, lag_confirmation = self._derive_market_leadership(symbol_features, consensus)
        outcome_tracking_status = "replay_backfilled" if self.latest_replay_report() else "not_started"
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
            "confidence": adjusted_confidence,
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
            "actionable_event_flags": actionable_event_flags,
            "active_event_flags_reliability": (feature_snapshot.get("derivatives_state") or {}).get("event_reliability"),
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
            "risk_regime": risk_regime,
            "regime_quality": regime_quality,
            "lead_symbol": lead_symbol,
            "lag_confirmation": lag_confirmation,
            "outcome_tracking_status": outcome_tracking_status,
        }
        self._write_report(report)
        return report

    def generate_replay_report(self) -> dict[str, Any]:
        definition = self._load_definition()
        universe = definition.get("universe") or ["BTC/USDT:USDT", "ETH/USDT:USDT"]
        all_frames: dict[str, dict[str, list[dict[str, Any]]]] = {}
        replay_5m_lengths: dict[str, list[int]] = {}
        for pair in universe:
            stem = _normalize_pair_to_stem(pair)
            all_frames[pair] = {
                "1h": _read_feather_records(self.market_data_dir / f"{stem}-1h-futures.feather"),
                "5m": _read_feather_records(self.market_data_dir / f"{stem}-5m-futures.feather"),
                "mark": _read_feather_records(self.market_data_dir / f"{stem}-1h-mark.feather")
                if (self.market_data_dir / f"{stem}-1h-mark.feather").exists()
                else [],
                "funding": _read_feather_records(self.market_data_dir / f"{stem}-1h-funding_rate.feather")
                if (self.market_data_dir / f"{stem}-1h-funding_rate.feather").exists()
                else [],
            }
            replay_5m_lengths[pair] = self._build_replay_5m_lengths(
                frame_1h=all_frames[pair]["1h"],
                frame_5m=all_frames[pair]["5m"],
            )

        bar_minutes = max(int(_safe_float(definition.get("thresholds", {}).get("bar_minutes"), 5)), 1)
        warmup_1h_bars = max(int(_safe_float(definition.get("thresholds", {}).get("replay_warmup_bars"), 48)), 24)
        replay_max_bars = max(int(_safe_float(definition.get("thresholds", {}).get("replay_max_bars"), 0)), 0)
        first_pair = universe[0]
        total_1h_bars = len(all_frames[first_pair]["1h"])
        reports: list[dict[str, Any]] = []
        previous_report: dict[str, Any] | None = None
        start_idx = warmup_1h_bars
        if replay_max_bars > 0:
            start_idx = max(start_idx, total_1h_bars - replay_max_bars)

        for idx in range(start_idx, total_1h_bars):
            symbol_features: list[dict[str, Any]] = []
            asof_iso = str(all_frames[first_pair]["1h"][idx].get("date"))
            for pair in universe:
                frame_1h = all_frames[pair]["1h"][: idx + 1]
                frame_5m = all_frames[pair]["5m"][: replay_5m_lengths[pair][idx]]
                funding = all_frames[pair]["funding"][: idx + 1] if all_frames[pair]["funding"] else []
                symbol_features.append(
                    self._compute_symbol_features_from_frames(
                        pair=pair,
                        frame_5m=frame_5m,
                        frame_1h=frame_1h,
                        funding_frame=funding,
                    )
                )
            feature_snapshot = self._aggregate_features(symbol_features, definition)
            derivatives_report = self._build_replay_derivatives_report(
                pair_frames=all_frames,
                universe=universe,
                index=idx,
                generated_at=asof_iso,
            )
            feature_snapshot = self._merge_derivatives_context(
                feature_snapshot=feature_snapshot,
                derivatives_report=derivatives_report,
            )
            raw_classification = self._classify(feature_snapshot, definition)
            stabilized = self._apply_hysteresis(
                raw_classification=raw_classification,
                previous_report=previous_report,
                definition=definition,
                current_generated_at=asof_iso,
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
            consensus = self._derive_symbol_states(symbol_features, definition)
            execution_constraints = self._derive_execution_constraints(
                primary_regime=stabilized["primary_regime"],
                market_state=market_state,
                ltf_execution_state=ltf_execution_state,
                market_phase=market_phase,
                risk_level=stabilized["risk_level"],
                consensus_strength=consensus["consensus_strength"],
                active_event_flags=self._derive_actionable_event_flags(
                    self._derive_active_event_flags(
                        feature_snapshot=feature_snapshot,
                        primary_regime=stabilized["primary_regime"],
                        htf_bias=htf_bias,
                        definition=definition,
                    ),
                    feature_snapshot.get("derivatives_state") or {},
                ),
                cooldown_remaining_bars=stabilized["regime_persistence"]["cooldown_remaining_bars"],
            )
            active_event_flags = self._derive_active_event_flags(
                feature_snapshot=feature_snapshot,
                primary_regime=stabilized["primary_regime"],
                htf_bias=htf_bias,
                definition=definition,
            )
            actionable_event_flags = self._derive_actionable_event_flags(
                active_event_flags,
                feature_snapshot.get("derivatives_state") or {},
            )
            report = {
                "generated_at": asof_iso,
                "primary_regime": stabilized["primary_regime"],
                "bias": self._derive_bias(primary_regime=stabilized["primary_regime"], htf_bias=htf_bias),
                "market_phase": market_phase,
                "market_state": market_state,
                "active_event_flags": active_event_flags,
                "actionable_event_flags": actionable_event_flags,
                "active_event_flags_reliability": (feature_snapshot.get("derivatives_state") or {}).get("event_reliability"),
                "execution_constraints": execution_constraints,
                "regime_persistence": stabilized["regime_persistence"],
                "market_consensus": consensus["market_consensus"],
                "consensus_strength": consensus["consensus_strength"],
                "feature_snapshot": feature_snapshot,
                "derivatives_state": feature_snapshot.get("derivatives_state") or {},
            }
            reports.append(report)
            previous_report = report

        summary = self._summarize_replay_reports(reports=reports, bar_minutes=bar_minutes, definition=definition)
        self._write_replay_report(summary)
        return summary

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
        return self._compute_symbol_features_from_frames(
            pair=pair,
            frame_5m=frame_5m,
            frame_1h=frame_1h,
            funding_frame=funding_frame,
        )

    def _compute_symbol_features_from_frames(
        self,
        *,
        pair: str,
        frame_5m: list[dict[str, Any]],
        frame_1h: list[dict[str, Any]],
        funding_frame: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not frame_5m or not frame_1h:
            raise ValueError(f"Missing futures frames for {pair}.")

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

    @staticmethod
    def _slice_5m_until(frame_5m: list[dict[str, Any]], *, asof_time: str) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        asof = str(asof_time)
        for row in frame_5m:
            row_time = str(row.get("date"))
            if row_time <= asof:
                selected.append(row)
        return selected or frame_5m

    @staticmethod
    def _build_replay_5m_lengths(
        *,
        frame_1h: list[dict[str, Any]],
        frame_5m: list[dict[str, Any]],
    ) -> list[int]:
        if not frame_1h:
            return []
        if not frame_5m:
            return [0 for _ in frame_1h]

        lengths: list[int] = []
        ltf_dates = [str(row.get("date")) for row in frame_5m]
        cursor = 0
        for row in frame_1h:
            asof = str(row.get("date"))
            while cursor < len(ltf_dates) and ltf_dates[cursor] <= asof:
                cursor += 1
            lengths.append(max(cursor, 1))
        return lengths

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

    def _merge_derivatives_context(
        self,
        *,
        feature_snapshot: dict[str, Any],
        derivatives_report: dict[str, Any] | None,
    ) -> dict[str, Any]:
        symbols = list((derivatives_report or {}).get("symbols") or [])
        oi_changes = [
            _safe_float(item.get("open_interest_change_pct"), None)
            for item in symbols
            if _safe_float(item.get("open_interest_change_pct"), None) is not None
        ]
        oi_accelerations = [
            _safe_float(item.get("oi_acceleration"), None)
            for item in symbols
            if _safe_float(item.get("oi_acceleration"), None) is not None
        ]
        liquidation_pressures = [
            _safe_float(item.get("liquidation_pressure_proxy"), 0.0) or 0.0
            for item in symbols
        ]
        squeeze_risks = [str(item.get("squeeze_risk") or "unknown") for item in symbols]
        positioning_states = [str(item.get("positioning_state") or "unknown") for item in symbols]
        funding_extreme = any(bool(item.get("funding_extreme_flag")) for item in symbols)
        agreement_values = [str(item.get("oi_price_agreement") or "unknown") for item in symbols]
        liquidation_confidences = [str(item.get("liquidation_event_confidence") or "low") for item in symbols]
        liquidation_source_types = [str(item.get("liquidation_source_type") or "proxy_from_local_market_data") for item in symbols]

        if symbols:
            if all(state == positioning_states[0] for state in positioning_states):
                positioning_state = positioning_states[0]
            else:
                positioning_state = "mixed"
            if all(level == "high" for level in squeeze_risks):
                squeeze_risk = "high"
            elif any(level == "medium" for level in squeeze_risks) or any(level == "high" for level in squeeze_risks):
                squeeze_risk = "medium"
            else:
                squeeze_risk = "low" if all(level == "low" for level in squeeze_risks) else "unknown"
            if all(value == agreement_values[0] for value in agreement_values):
                oi_price_agreement = agreement_values[0]
            else:
                oi_price_agreement = "mixed"
        else:
            positioning_state = "unknown"
            squeeze_risk = "unknown"
            oi_price_agreement = "unknown"

        feed_status = (derivatives_report or {}).get("feed_status", "missing")
        source = (derivatives_report or {}).get("source", "unavailable")
        is_stale = bool((derivatives_report or {}).get("is_stale"))
        event_reliability = str(
            (derivatives_report or {}).get("event_reliability")
            or self._derive_derivatives_event_reliability(
                source=source,
                feed_status=feed_status,
                is_stale=is_stale,
            )
        )
        if liquidation_confidences:
            liquidation_event_confidence = (
                "medium" if "medium" in liquidation_confidences else liquidation_confidences[0]
            )
        else:
            liquidation_event_confidence = str(
                (derivatives_report or {}).get("liquidation_event_confidence") or "low"
            )
        if liquidation_source_types:
            liquidation_source_type = (
                liquidation_source_types[0]
                if all(value == liquidation_source_types[0] for value in liquidation_source_types)
                else "mixed"
            )
        else:
            liquidation_source_type = str(
                (derivatives_report or {}).get("liquidation_source_type") or "proxy_from_local_market_data"
            )

        return {
            **feature_snapshot,
            "oi_change_mean_pct": round(sum(oi_changes) / len(oi_changes), 4) if oi_changes else None,
            "oi_acceleration_mean": round(sum(oi_accelerations) / len(oi_accelerations), 4) if oi_accelerations else None,
            "liquidation_pressure_mean": round(sum(liquidation_pressures) / len(liquidation_pressures), 4)
            if liquidation_pressures
            else 0.0,
            "funding_extreme_flag": funding_extreme,
            "derivatives_state": {
                "feed_status": feed_status,
                "source": source,
                "vendor_available": bool((derivatives_report or {}).get("vendor_available")),
                "vendor_name": (derivatives_report or {}).get("vendor_name"),
                "fetch_errors": (derivatives_report or {}).get("fetch_errors") or [],
                "fetched_at": (derivatives_report or {}).get("fetched_at"),
                "source_timestamp": (derivatives_report or {}).get("source_timestamp"),
                "age_seconds": (derivatives_report or {}).get("age_seconds"),
                "is_stale": is_stale,
                "event_reliability": event_reliability,
                "positioning_state": positioning_state,
                "squeeze_risk": squeeze_risk,
                "oi_price_agreement": oi_price_agreement,
                "open_interest_change_pct": round(sum(oi_changes) / len(oi_changes), 4) if oi_changes else None,
                "oi_acceleration": round(sum(oi_accelerations) / len(oi_accelerations), 4) if oi_accelerations else None,
                "funding_extreme_flag": funding_extreme,
                "liquidation_pressure_proxy": round(sum(liquidation_pressures) / len(liquidation_pressures), 4)
                if liquidation_pressures
                else 0.0,
                "liquidation_source_type": liquidation_source_type,
                "liquidation_event_confidence": liquidation_event_confidence,
                "symbols": symbols,
            },
        }

    def _build_replay_derivatives_report(
        self,
        *,
        pair_frames: dict[str, dict[str, list[dict[str, Any]]]],
        universe: list[str],
        index: int,
        generated_at: str,
    ) -> dict[str, Any]:
        symbols: list[dict[str, Any]] = []
        for pair in universe:
            frames = pair_frames[pair]
            futures_1h = frames["1h"][: index + 1]
            mark_1h = frames.get("mark", [])[: index + 1]
            funding_1h = frames.get("funding", [])[: index + 1]
            if len(futures_1h) < 2:
                continue

            latest = futures_1h[-1]
            previous = futures_1h[-2]
            latest_close = _safe_float(latest.get("close"), 0.0)
            previous_close = _safe_float(previous.get("close"), latest_close)
            price_change_pct = _pct_change(latest_close, previous_close) if previous_close else 0.0

            latest_volume = _safe_float(latest.get("volume"), 0.0)
            volume_window = [
                _safe_float(row.get("volume"), 0.0)
                for row in futures_1h[-24:]
            ]
            volume_spike = latest_volume / max(median(volume_window), 1e-9) if volume_window else 1.0

            latest_mark = _safe_float((mark_1h[-1] if mark_1h else {}).get("close"), latest_close)
            mark_premium_pct = _pct_change(latest_mark, latest_close) if latest_close else 0.0

            funding_bps = None
            if funding_1h:
                latest_funding = funding_1h[-1]
                for field_name in ("fundingRate", "funding_rate", "value", "close", "open"):
                    if field_name in latest_funding:
                        raw_value = _safe_float(latest_funding.get(field_name), 0.0)
                        funding_bps = raw_value * 10000.0 if raw_value is not None else None
                        break

            # Proxy OI follows conviction and stress intensity until real vendor OI history is available.
            oi_change_pct = round(
                price_change_pct * 0.55 + max(0.0, volume_spike - 1.0) * 6.0 + mark_premium_pct * 1.8,
                4,
            )
            if abs(price_change_pct) < 0.15 and volume_spike < 1.05:
                oi_change_pct = round(oi_change_pct * 0.25, 4)

            previous_oi_change_pct = 0.0
            if len(futures_1h) >= 3:
                prev_latest = futures_1h[-2]
                prev_previous = futures_1h[-3]
                prev_latest_close = _safe_float(prev_latest.get("close"), 0.0)
                prev_previous_close = _safe_float(prev_previous.get("close"), prev_latest_close)
                prev_price_change = _pct_change(prev_latest_close, prev_previous_close) if prev_previous_close else 0.0
                prev_volume_window = [
                    _safe_float(row.get("volume"), 0.0)
                    for row in futures_1h[-25:-1]
                ]
                prev_volume_spike = (
                    _safe_float(prev_latest.get("volume"), 0.0) / max(median(prev_volume_window), 1e-9)
                    if prev_volume_window
                    else 1.0
                )
                prev_mark = _safe_float((mark_1h[-2] if len(mark_1h) >= 2 else {}).get("close"), prev_latest_close)
                prev_mark_premium = _pct_change(prev_mark, prev_latest_close) if prev_latest_close else 0.0
                previous_oi_change_pct = round(
                    prev_price_change * 0.55 + max(0.0, prev_volume_spike - 1.0) * 6.0 + prev_mark_premium * 1.8,
                    4,
                )

            oi_acceleration = round(oi_change_pct - previous_oi_change_pct, 4)
            open_interest = round(
                max(0.0, latest_close * max(latest_volume, 0.0) * 0.015 * (1.0 + max(oi_change_pct, -95.0) / 100.0)),
                4,
            )
            liquidation_pressure_proxy = round(
                min(
                    1.0,
                    abs(price_change_pct) * 0.14
                    + max(0.0, volume_spike - 1.0) * 0.35
                    + abs(mark_premium_pct) * 0.3
                    + max(0.0, abs(oi_acceleration) - 0.5) * 0.06,
                ),
                4,
            )
            symbols.append(
                {
                    "pair": pair,
                    "open_interest": open_interest,
                    "open_interest_change_pct": oi_change_pct,
                    "oi_acceleration": oi_acceleration,
                    "price_change_pct": round(price_change_pct, 4),
                    "oi_price_agreement": self._derive_replay_oi_price_agreement(
                        price_change_pct=price_change_pct,
                        oi_change_pct=oi_change_pct,
                    ),
                    "funding_bps": round(funding_bps, 4) if funding_bps is not None else None,
                    "funding_extreme_flag": bool(abs(funding_bps or 0.0) >= 8.0),
                    "liquidation_pressure_proxy": liquidation_pressure_proxy,
                    "positioning_state": self._derive_replay_positioning_state(
                        price_change_pct=price_change_pct,
                        oi_change_pct=oi_change_pct,
                    ),
                    "squeeze_risk": self._derive_replay_squeeze_risk(
                        price_change_pct=price_change_pct,
                        oi_change_pct=oi_change_pct,
                        funding_bps=funding_bps,
                        liquidation_pressure_proxy=liquidation_pressure_proxy,
                    ),
                }
            )

        return {
            "generated_at": generated_at,
            "fetched_at": generated_at,
            "source_timestamp": generated_at,
            "age_seconds": 0.0,
            "is_stale": False,
            "source": "replay_proxy",
            "feed_status": "replay_proxy",
            "vendor_available": False,
            "vendor_name": "replay_proxy",
            "fetch_errors": [],
            "event_reliability": "low",
            "liquidation_source_type": "proxy_from_replay_market_data",
            "liquidation_event_confidence": "low",
            "universe": [item["pair"] for item in symbols],
            "symbols": symbols,
        }

    @staticmethod
    def _derive_replay_oi_price_agreement(*, price_change_pct: float, oi_change_pct: float | None) -> str:
        if oi_change_pct is None:
            return "unknown"
        if price_change_pct > 0 and oi_change_pct > 0:
            return "trend_supported_up"
        if price_change_pct < 0 and oi_change_pct > 0:
            return "trend_supported_down"
        if price_change_pct > 0 and oi_change_pct < 0:
            return "short_covering"
        if price_change_pct < 0 and oi_change_pct < 0:
            return "long_unwind"
        return "mixed"

    def _derive_replay_positioning_state(self, *, price_change_pct: float, oi_change_pct: float | None) -> str:
        agreement = self._derive_replay_oi_price_agreement(
            price_change_pct=price_change_pct,
            oi_change_pct=oi_change_pct,
        )
        mapping = {
            "trend_supported_up": "long_build",
            "trend_supported_down": "short_build",
            "short_covering": "short_covering",
            "long_unwind": "long_unwind",
        }
        return mapping.get(agreement, "mixed")

    @staticmethod
    def _derive_replay_squeeze_risk(
        *,
        price_change_pct: float,
        oi_change_pct: float | None,
        funding_bps: float | None,
        liquidation_pressure_proxy: float,
    ) -> str:
        if oi_change_pct is None:
            return "unknown"
        if (
            price_change_pct > 0.8
            and oi_change_pct < -0.6
            and (abs(funding_bps or 0.0) >= 4.0 or liquidation_pressure_proxy >= 0.45)
        ):
            return "high"
        if (
            price_change_pct < -0.8
            and oi_change_pct < -0.6
            and liquidation_pressure_proxy >= 0.45
        ):
            return "high"
        if abs(price_change_pct) >= 0.5 or liquidation_pressure_proxy >= 0.3:
            return "medium"
        return "low"

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

        derivatives_state = metrics.get("derivatives_state")
        if not isinstance(derivatives_state, dict):
            if funding_abs_bps is None:
                derivatives_state = {
                    "feed_status": "unavailable",
                    "source": "funding_only",
                    "vendor_available": False,
                    "vendor_name": None,
                    "fetch_errors": [],
                    "fetched_at": None,
                    "source_timestamp": None,
                    "age_seconds": None,
                    "is_stale": False,
                    "event_reliability": "low",
                    "positioning_state": "unknown",
                    "squeeze_risk": "unknown",
                    "oi_price_agreement": "unknown",
                    "open_interest_change_pct": None,
                    "oi_acceleration": None,
                    "funding_extreme_flag": False,
                    "liquidation_pressure_proxy": 0.0,
                    "liquidation_source_type": "proxy_from_local_market_data",
                    "liquidation_event_confidence": "low",
                    "symbols": [],
                }
            else:
                derivatives_state = {
                    "feed_status": "funding_only",
                    "source": "funding_only",
                    "vendor_available": False,
                    "vendor_name": None,
                    "fetch_errors": [],
                    "fetched_at": None,
                    "source_timestamp": None,
                    "age_seconds": None,
                    "is_stale": False,
                    "event_reliability": "low",
                    "positioning_state": "mixed",
                    "squeeze_risk": "unknown",
                    "oi_price_agreement": "unknown",
                    "open_interest_change_pct": None,
                    "oi_acceleration": None,
                    "funding_extreme_flag": _safe_float(funding_abs_bps) >= _safe_float(thresholds.get("funding_extreme_bps"), 8.0),
                    "liquidation_pressure_proxy": 0.0,
                    "liquidation_source_type": "proxy_from_local_market_data",
                    "liquidation_event_confidence": "low",
                    "symbols": [],
                }

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

        compression_volatility_ratio_max = _safe_float(thresholds.get("compression_volatility_ratio_max"), 0.9)
        compression_std_ratio_max = _safe_float(thresholds.get("compression_std_ratio_max"), 0.95)
        compression_recent_move_abs_pct_max = _safe_float(
            thresholds.get("compression_recent_move_abs_pct_max"),
            0.45,
        )
        compression_volume_spike_max = _safe_float(
            thresholds.get("compression_volume_spike_max"),
            1.55,
        )
        if (
            volatility_ratio <= compression_volatility_ratio_max
            and std_ratio <= compression_std_ratio_max
            and recent_move_abs_pct <= compression_recent_move_abs_pct_max
            and volume_spike <= compression_volume_spike_max
        ):
            scores["low_vol"] += 1.75
            reasons["low_vol"].append("Kompresja zmienności tłumi handlowalność mimo istniejącego kierunku.")
            if abs(spread) <= _safe_float(thresholds.get("compression_range_spread_max_pct"), 0.18):
                scores["range"] += 1.0
                reasons["range"].append("Kompresja i ograniczony spread sugerują bardziej przejście lub range niż czysty trend.")
            scores["trend_up"] -= 0.85
            scores["trend_down"] -= 0.85
            reasons["trend_up"].append("Kompresja obniża jakość trendu wzrostowego jako aktywnego reżimu.")
            reasons["trend_down"].append("Kompresja obniża jakość trendu spadkowego jako aktywnego reżimu.")

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
        current_generated_at: str | None = None,
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
            current_generated_at_dt = self._parse_iso(current_generated_at or _now_iso())
            if previous_generated_at and current_generated_at_dt:
                delta_minutes = max((current_generated_at_dt - previous_generated_at).total_seconds() / 60.0, 0.0)
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

    @staticmethod
    def _derive_derivatives_event_reliability(
        *,
        source: str,
        feed_status: str,
        is_stale: bool,
    ) -> str:
        if source == "binance_futures_public_api":
            reliability = "medium"
        elif source == "external_vendor":
            reliability = "medium"
        else:
            reliability = "low"
        if feed_status == "partial":
            reliability = "low"
        if is_stale and reliability == "medium":
            reliability = "low"
        return reliability

    @staticmethod
    def _derive_derivatives_confidence_multiplier(derivatives_state: dict[str, Any]) -> float:
        reliability = str(derivatives_state.get("event_reliability") or "low")
        is_stale = bool(derivatives_state.get("is_stale"))
        feed_status = str(derivatives_state.get("feed_status") or "missing")
        multiplier = {"medium": 0.94, "low": 0.84}.get(reliability, 0.88)
        if reliability == "medium" and feed_status == "ok":
            multiplier = 0.97
        if feed_status in {"missing", "degraded_proxy"}:
            multiplier = min(multiplier, 0.84)
        if is_stale:
            multiplier *= 0.9
        return max(0.65, min(1.0, multiplier))

    @staticmethod
    def _derive_actionable_event_flags(
        active_event_flags: dict[str, bool],
        derivatives_state: dict[str, Any],
    ) -> dict[str, bool]:
        reliability = str(derivatives_state.get("event_reliability") or "low")
        if reliability != "low":
            return dict(active_event_flags)
        return {
            "panic_flush": bool(active_event_flags.get("panic_flush")),
            "short_squeeze": False,
            "long_squeeze": False,
            "capitulation": False,
            "deleveraging": False,
        }

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
        derivatives_state = feature_snapshot.get("derivatives_state") or {}
        oi_change_pct = _safe_float(derivatives_state.get("open_interest_change_pct"), None)
        liquidation_pressure = _safe_float(derivatives_state.get("liquidation_pressure_proxy"), 0.0) or 0.0
        squeeze_risk = str(derivatives_state.get("squeeze_risk") or "unknown")

        stress_move = _safe_float(thresholds.get("stress_move_abs_pct_min"), 1.6)
        squeeze_move = _safe_float(thresholds.get("squeeze_move_abs_pct_min"), 1.2)
        event_confirmed = (
            recent_move_abs_pct >= squeeze_move
            and volatility_ratio >= _safe_float(thresholds.get("expansion_volatility_ratio_min"), 1.15)
            and volume_spike >= _safe_float(thresholds.get("volume_spike_high"), 1.25)
        )

        panic_flush = primary_regime == "stress_panic" and recent_move_pct <= -stress_move
        short_squeeze = (
            event_confirmed
            and recent_move_pct >= squeeze_move
            and squeeze_risk in {"medium", "high"}
            and oi_change_pct is not None
            and oi_change_pct < 0
        )
        long_squeeze = (
            event_confirmed
            and recent_move_pct <= -squeeze_move
            and squeeze_risk in {"medium", "high"}
            and oi_change_pct is not None
            and oi_change_pct < 0
        )
        capitulation = (
            panic_flush
            and liquidation_pressure >= 0.6
            and (oi_change_pct is None or oi_change_pct < 0)
            and funding_mean_bps <= -_safe_float(thresholds.get("funding_elevated_bps"), 4.0)
        )
        deleveraging = (
            event_confirmed
            and oi_change_pct is not None
            and oi_change_pct <= -1.0
            and liquidation_pressure >= 0.5
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
            "funding_extreme": bool((feature_snapshot.get("derivatives_state") or {}).get("funding_extreme_flag"))
            or _safe_float(feature_snapshot.get("funding_abs_bps")) >= _safe_float(thresholds.get("funding_extreme_bps"), 8.0),
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

    def _derive_risk_regime(
        self,
        *,
        primary_regime: str,
        risk_level: str,
        execution_constraints: dict[str, bool],
        active_event_flags: dict[str, bool],
        consensus_strength: float,
    ) -> str:
        if active_event_flags.get("panic_flush") or active_event_flags.get("deleveraging"):
            return "high"
        if execution_constraints["no_trade_zone"]:
            return "high"
        if execution_constraints["post_shock_cooldown"] or execution_constraints["high_noise_environment"]:
            return "elevated"
        if risk_level == "high":
            return "high"
        if risk_level == "medium" or primary_regime in {"trend_down", "range"} or consensus_strength < 0.5:
            return "elevated"
        return "normal"

    def _derive_regime_quality(
        self,
        *,
        alignment_score: float,
        execution_constraints: dict[str, bool],
        market_phase: str,
        active_event_flags: dict[str, bool],
        derivatives_state: dict[str, Any],
    ) -> float:
        quality = alignment_score
        if execution_constraints["no_trade_zone"]:
            quality *= 0.25
        elif execution_constraints["reduced_exposure_only"]:
            quality *= 0.8
        if execution_constraints["high_noise_environment"]:
            quality *= 0.7
        if execution_constraints["post_shock_cooldown"]:
            quality *= 0.65
        if market_phase == "compression":
            quality *= 0.85
        if any(active_event_flags.values()):
            quality *= 0.75
        event_reliability = str(derivatives_state.get("event_reliability") or "low")
        if event_reliability == "medium":
            quality *= 0.95
        elif event_reliability == "low":
            quality *= 0.82
        if bool(derivatives_state.get("is_stale")):
            quality *= 0.85
        return round(max(0.0, min(1.0, quality)), 4)

    def _derive_market_leadership(
        self,
        symbol_features: list[dict[str, Any]],
        consensus: dict[str, Any],
    ) -> tuple[str | None, str]:
        if not symbol_features:
            return None, "unknown"
        by_pair = {item["pair"]: item for item in symbol_features}
        btc = by_pair.get("BTC/USDT:USDT")
        eth = by_pair.get("ETH/USDT:USDT")
        if not btc or not eth:
            return None, "unknown"
        btc_score = abs(_safe_float(btc.get("trend_spread_pct"))) + abs(_safe_float(btc.get("slope_pct"))) + _safe_float(btc.get("adx")) / 100.0
        eth_score = abs(_safe_float(eth.get("trend_spread_pct"))) + abs(_safe_float(eth.get("slope_pct"))) + _safe_float(eth.get("adx")) / 100.0
        lead_symbol = "BTC" if btc_score >= eth_score else "ETH"
        if consensus.get("market_consensus", "").startswith("strong_"):
            lag_confirmation = "strong"
        elif consensus.get("market_consensus", "").startswith("weak_"):
            lag_confirmation = "weak"
        else:
            lag_confirmation = "divergent"
        return lead_symbol, lag_confirmation

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

    def _summarize_replay_reports(
        self,
        *,
        reports: list[dict[str, Any]],
        bar_minutes: int,
        definition: dict[str, Any],
    ) -> dict[str, Any]:
        if not reports:
            return {
                "generated_at": _now_iso(),
                "asof_timeframe": definition.get("asof_timeframe", "1h"),
                "bar_count": 0,
                "replay_status": "empty",
                "warmup_bars": max(int(_safe_float(definition.get("thresholds", {}).get("replay_warmup_bars"), 48)), 24),
                "regime_switches_total": 0,
                "avg_minutes_in_regime": 0.0,
                "no_trade_zone_share": 0.0,
                "compression_to_expansion_count": 0,
                "bias_followthrough_15m_pct": None,
                "bias_followthrough_1h_pct": None,
                "market_consensus_breakdown": {},
                "regime_coverage": {},
                "event_counts": {},
                "derivatives_source_breakdown": {},
                "derivatives_event_reliability_breakdown": {},
                "derivatives_stale_share": 0.0,
                "notes": ["Replay nie wygenerowal jeszcze zadnych barow."],
            }

        regime_switches = 0
        compression_to_expansion_count = 0
        no_trade_count = 0
        regime_counts: dict[str, int] = {}
        consensus_counts: dict[str, int] = {}
        event_counts = {
            "panic_flush": 0,
            "short_squeeze": 0,
            "long_squeeze": 0,
            "capitulation": 0,
            "deleveraging": 0,
        }
        derivatives_source_counts: dict[str, int] = {}
        derivatives_event_reliability_counts: dict[str, int] = {}
        stale_reports = 0
        follow_15m_hits = 0
        follow_15m_total = 0
        follow_1h_hits = 0
        follow_1h_total = 0

        previous = None
        for report in reports:
            regime = str(report.get("primary_regime") or "unknown")
            regime_counts[regime] = regime_counts.get(regime, 0) + 1
            consensus = str(report.get("market_consensus") or "unknown")
            consensus_counts[consensus] = consensus_counts.get(consensus, 0) + 1
            if report.get("execution_constraints", {}).get("no_trade_zone"):
                no_trade_count += 1
            derivatives_state = report.get("derivatives_state") or {}
            derivatives_source = str(derivatives_state.get("source") or "unknown")
            derivatives_source_counts[derivatives_source] = derivatives_source_counts.get(derivatives_source, 0) + 1
            event_reliability = str(derivatives_state.get("event_reliability") or "unknown")
            derivatives_event_reliability_counts[event_reliability] = (
                derivatives_event_reliability_counts.get(event_reliability, 0) + 1
            )
            if bool(derivatives_state.get("is_stale")):
                stale_reports += 1
            if previous and previous.get("primary_regime") != regime:
                regime_switches += 1
            if previous and previous.get("market_phase") == "compression" and report.get("market_phase") == "expansion":
                compression_to_expansion_count += 1
            for flag_name in event_counts:
                if bool((report.get("actionable_event_flags") or {}).get(flag_name)):
                    event_counts[flag_name] += 1
                elif bool((report.get("feature_snapshot", {}) or {}).get("actionable_event_flags", {}).get(flag_name)):
                    event_counts[flag_name] += 1
                elif bool((report.get("active_event_flags") or {}).get(flag_name)):
                    event_counts[flag_name] += 1

            bias = str(report.get("bias") or "neutral")
            current_move = _safe_float(report.get("feature_snapshot", {}).get("recent_move_pct"), 0.0) or 0.0
            if bias in {"long", "short"}:
                follow_15m_total += 1
                follow_1h_total += 1
                if (bias == "long" and current_move >= 0) or (bias == "short" and current_move <= 0):
                    follow_15m_hits += 1
                    follow_1h_hits += 1
            previous = report

        avg_minutes_in_regime = sum(
            _safe_float(report.get("regime_persistence", {}).get("minutes_in_regime"), bar_minutes) or bar_minutes
            for report in reports
        ) / len(reports)
        return {
            "generated_at": _now_iso(),
            "asof_timeframe": definition.get("asof_timeframe", "1h"),
            "bar_count": len(reports),
            "replay_status": "ready",
            "warmup_bars": max(int(_safe_float(definition.get("thresholds", {}).get("replay_warmup_bars"), 48)), 24),
            "regime_switches_total": regime_switches,
            "avg_minutes_in_regime": round(avg_minutes_in_regime, 2),
            "no_trade_zone_share": round(no_trade_count / len(reports), 4),
            "compression_to_expansion_count": compression_to_expansion_count,
            "bias_followthrough_15m_pct": round(follow_15m_hits / follow_15m_total, 4) if follow_15m_total else None,
            "bias_followthrough_1h_pct": round(follow_1h_hits / follow_1h_total, 4) if follow_1h_total else None,
            "market_consensus_breakdown": consensus_counts,
            "regime_coverage": regime_counts,
            "event_counts": event_counts,
            "derivatives_source_breakdown": derivatives_source_counts,
            "derivatives_event_reliability_breakdown": derivatives_event_reliability_counts,
            "derivatives_stale_share": round(stale_reports / len(reports), 4),
            "notes": [
                "Replay summary sluzy do kalibracji progow i stabilnosci przejsc, nie do bezposredniego tradingu.",
            ],
        }

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

    def _write_replay_report(self, report: dict[str, Any]) -> None:
        self.replay_dir.mkdir(parents=True, exist_ok=True)
        stamp = str(report["generated_at"]).replace(":", "-")
        history_path = self.replay_dir / f"replay-{stamp}.json"
        latest_path = self.replay_dir / "latest.json"
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
