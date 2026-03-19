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
    recent_move_abs_pct: float
    funding_bps: float | None


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
        candidate_manifests = self._load_candidate_manifests()
        symbol_features = self._build_symbol_features(definition)
        feature_snapshot = self._aggregate_features(symbol_features, definition)
        classification = self._classify(feature_snapshot, definition)
        eligible, blocked = self._candidate_eligibility(
            candidate_manifests,
            primary_regime=classification["primary_regime"],
        )
        report = {
            "generated_at": _now_iso(),
            "asof_timeframe": definition.get("asof_timeframe", "1h"),
            "universe": [item.get("pair") for item in symbol_features],
            "primary_regime": classification["primary_regime"],
            "confidence": round(classification["confidence"], 4),
            "risk_level": classification["risk_level"],
            "trend_strength": feature_snapshot["trend_strength"],
            "volatility_level": feature_snapshot["volatility_level"],
            "volume_state": feature_snapshot["volume_state"],
            "derivatives_state": feature_snapshot["derivatives_state"],
            "feature_snapshot": feature_snapshot,
            "reasons": classification["reasons"][:DEFAULT_REASONS_LIMIT],
            "eligible_candidate_ids": eligible,
            "blocked_candidate_ids": blocked,
            "candidate_freeze_mode": "freeze_build_keep_dry_run",
        }
        self._write_report(report)
        return report

    def _load_definition(self) -> dict[str, Any]:
        payload = yaml.safe_load(self.definition_path.read_text(encoding="utf-8")) or {}
        return payload

    def _load_candidate_manifests(self) -> list[dict[str, Any]]:
        manifests: list[dict[str, Any]] = []
        for path in sorted((self.research_dir / "candidates").glob("*/strategy_manifest.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            manifests.append(payload)
        return manifests

    def _build_symbol_features(
        self,
        definition: dict[str, Any],
    ) -> list[dict[str, Any]]:
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
        recent_move_abs_pct = abs(_pct_change(closes_5m[-1], closes_5m[-7])) if len(closes_5m) >= 7 else 0.0

        ema_fast = _ema(closes_1h, 12)
        ema_slow = _ema(closes_1h, 36)
        trend_spread_pct = (
            ((ema_fast[-1] - ema_slow[-1]) / max(closes_1h[-1], 1e-9)) * 100.0
            if ema_fast and ema_slow and closes_1h
            else 0.0
        )
        slope_reference_index = -6 if len(ema_fast) >= 6 else 0
        slope_pct = (
            _pct_change(ema_fast[-1], ema_fast[slope_reference_index])
            if len(ema_fast) >= 2
            else 0.0
        )
        adx_value = _adx(highs_1h, lows_1h, closes_1h, period=14)

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
            recent_move_abs_pct=round(recent_move_abs_pct, 4),
            funding_bps=round(funding_bps, 4) if funding_bps is not None else None,
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
            "recent_move_abs_pct",
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
        funding_abs_bps = round(
            sum(abs(value) for value in funding_values) / len(funding_values),
            6,
        ) if funding_values else None

        thresholds = definition.get("thresholds", {})
        trend_strength = round(
            min(1.0, aggregates["adx"] / max(_safe_float(thresholds.get("adx_trend_min"), 20.0), 1.0)),
            4,
        )

        if aggregates["volatility_ratio"] >= _safe_float(thresholds.get("stress_volatility_ratio_min"), 1.8):
            volatility_level = "extreme"
        elif aggregates["volatility_ratio"] >= _safe_float(thresholds.get("high_volatility_ratio_min"), 1.2):
            volatility_level = "high"
        elif aggregates["volatility_ratio"] <= _safe_float(thresholds.get("low_volatility_ratio_max"), 0.85):
            volatility_level = "low"
        else:
            volatility_level = "normal"

        if aggregates["volume_spike"] >= _safe_float(thresholds.get("stress_volume_spike_min"), 1.8):
            volume_state = "spike"
        elif aggregates["volume_spike"] >= _safe_float(thresholds.get("volume_spike_high"), 1.25):
            volume_state = "elevated"
        elif aggregates["volume_spike"] <= _safe_float(thresholds.get("low_volume_spike_max"), 0.9):
            volume_state = "thin"
        else:
            volume_state = "normal"

        if funding_abs_bps is None:
            derivatives_state = "unavailable"
        elif funding_abs_bps >= _safe_float(thresholds.get("funding_extreme_bps"), 8.0):
            derivatives_state = "stretched"
        elif funding_abs_bps >= _safe_float(thresholds.get("funding_elevated_bps"), 4.0):
            derivatives_state = "elevated"
        else:
            derivatives_state = "neutral"

        return {
            **aggregates,
            "funding_abs_bps": funding_abs_bps,
            "trend_strength": trend_strength,
            "volatility_level": volatility_level,
            "volume_state": volume_state,
            "derivatives_state": derivatives_state,
            "symbols": symbol_features,
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

        if primary_regime == "stress_panic":
            risk_level = "high"
        elif primary_regime == "high_vol":
            risk_level = "high"
        elif primary_regime == "trend_down":
            risk_level = "medium"
        elif primary_regime == "range":
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "primary_regime": primary_regime,
            "confidence": confidence,
            "risk_level": risk_level,
            "scores": {key: round(value, 4) for key, value in scores.items()},
            "reasons": reasons[primary_regime],
        }

    def _candidate_eligibility(
        self,
        manifests: list[dict[str, Any]],
        *,
        primary_regime: str,
    ) -> tuple[list[str], list[str]]:
        eligible: list[str] = []
        blocked: list[str] = []
        for manifest in manifests:
            candidate_id = str(manifest.get("strategy_id") or "")
            if not candidate_id:
                continue
            allowed = list(manifest.get("allowed_primary_regimes") or [])
            blocked_regimes = list(manifest.get("blocked_primary_regimes") or [])
            if not allowed:
                allowed = list(manifest.get("required_regimes") or [])
            if primary_regime in blocked_regimes:
                blocked.append(candidate_id)
            elif allowed and primary_regime not in allowed:
                blocked.append(candidate_id)
            else:
                eligible.append(candidate_id)
        return eligible, blocked

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
