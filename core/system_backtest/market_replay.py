"""Historical market provider and replay-safe regime report builder."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

import pyarrow.feather as feather

from ..regime_detector import RegimeDetector, _normalize_pair_to_stem
from .models import SystemBacktestConfig


def _read_feather_records(path: Path) -> list[dict[str, Any]]:
    table = feather.read_table(path)
    records = table.to_pylist()
    records.sort(key=lambda item: item.get("date"))
    return records


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass(slots=True)
class ReplayBarWindow:
    index: int
    timestamp: datetime
    base_frames: dict[str, list[dict[str, Any]]]
    htf_frames: dict[str, list[dict[str, Any]]]
    funding_frames: dict[str, list[dict[str, Any]]]
    current_bars: dict[str, dict[str, Any]]
    next_bars: dict[str, dict[str, Any] | None]
    htf_index: int

    @property
    def asof_iso(self) -> str:
        return self.timestamp.isoformat()


class HistoricalMarketReplayProvider:
    """Loads futures candles and serves bar-by-bar windows without future leak."""

    def __init__(self, *, config: SystemBacktestConfig) -> None:
        self.config = config
        self.market_data_dir = config.user_data_dir / "data" / "binance" / "futures"
        self.frames: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for pair in config.universe:
            stem = _normalize_pair_to_stem(pair)
            self.frames[pair] = {
                "5m": _read_feather_records(self.market_data_dir / f"{stem}-5m-futures.feather"),
                "1h": _read_feather_records(self.market_data_dir / f"{stem}-1h-futures.feather"),
                "mark": _read_feather_records(self.market_data_dir / f"{stem}-1h-mark.feather"),
                "funding": _read_feather_records(self.market_data_dir / f"{stem}-1h-funding_rate.feather"),
            }
        first_pair = config.universe[0]
        self.base_schedule = [_to_datetime(row["date"]) for row in self.frames[first_pair]["5m"]]

    def iter_windows(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> Iterator[ReplayBarWindow]:
        emitted = 0
        for index, timestamp in enumerate(self.base_schedule):
            if timestamp < start or timestamp >= end:
                continue
            if index < self.config.replay_warmup_bars:
                continue
            current_hour_start = timestamp.replace(minute=0, second=0, microsecond=0)
            htf_index = self._latest_completed_1h_index(current_hour_start=current_hour_start)
            if htf_index < self.config.replay_warmup_1h_bars - 1:
                continue

            base_frames: dict[str, list[dict[str, Any]]] = {}
            htf_frames: dict[str, list[dict[str, Any]]] = {}
            funding_frames: dict[str, list[dict[str, Any]]] = {}
            current_bars: dict[str, dict[str, Any]] = {}
            next_bars: dict[str, dict[str, Any] | None] = {}

            for pair in self.config.universe:
                pair_5m = self.frames[pair]["5m"]
                pair_1h = self.frames[pair]["1h"]
                pair_funding = self.frames[pair]["funding"]
                base_window_start = max(0, index + 1 - self.config.replay_warmup_bars)
                htf_window_start = max(0, htf_index + 1 - self.config.replay_warmup_1h_bars)
                base_frames[pair] = pair_5m[base_window_start : index + 1]
                htf_frames[pair] = pair_1h[htf_window_start : htf_index + 1]
                eligible_funding = [
                    row for row in pair_funding if _to_datetime(row["date"]) < current_hour_start
                ]
                funding_frames[pair] = eligible_funding[-self.config.replay_warmup_1h_bars :]
                current_bars[pair] = dict(pair_5m[index])
                next_bars[pair] = dict(pair_5m[index + 1]) if index + 1 < len(pair_5m) else None

            if any(bar is None for bar in next_bars.values()):
                continue

            yield ReplayBarWindow(
                index=index,
                timestamp=timestamp,
                base_frames=base_frames,
                htf_frames=htf_frames,
                funding_frames=funding_frames,
                current_bars=current_bars,
                next_bars=next_bars,
                htf_index=htf_index,
            )
            emitted += 1
            if self.config.max_bars is not None and emitted >= self.config.max_bars:
                break

    def build_regime_report(
        self,
        *,
        detector: RegimeDetector,
        window: ReplayBarWindow,
        previous_report: dict[str, Any] | None,
    ) -> dict[str, Any]:
        definition = detector._load_definition()
        symbol_features: list[dict[str, Any]] = []
        for pair in self.config.universe:
            symbol_features.append(
                detector._compute_symbol_features_from_frames(
                    pair=pair,
                    frame_5m=window.base_frames[pair],
                    frame_1h=window.htf_frames[pair],
                    funding_frame=window.funding_frames[pair],
                )
            )

        feature_snapshot = detector._aggregate_features(symbol_features, definition)
        derivatives_report = detector._build_replay_derivatives_report(
            pair_frames=self.frames,
            universe=self.config.universe,
            index=window.htf_index,
            generated_at=window.asof_iso,
        )
        feature_snapshot = detector._merge_derivatives_context(
            feature_snapshot=feature_snapshot,
            derivatives_report=derivatives_report,
        )
        lead_pair = self._lead_pair(symbol_features)
        current_bar = window.current_bars.get(lead_pair) or window.current_bars[self.config.universe[0]]
        feature_snapshot["reference_price"] = float(current_bar.get("close") or 0.0)
        feature_snapshot["reference_pair"] = lead_pair

        raw_classification = detector._classify(feature_snapshot, definition)
        stabilized = detector._apply_hysteresis(
            raw_classification=raw_classification,
            previous_report=previous_report,
            definition=definition,
            current_generated_at=window.asof_iso,
        )
        htf_bias = detector._derive_htf_bias(feature_snapshot, definition)
        market_state = detector._derive_market_state(
            feature_snapshot=feature_snapshot,
            primary_regime=stabilized["primary_regime"],
            htf_bias=htf_bias,
            definition=definition,
        )
        ltf_execution_state = detector._derive_ltf_execution_state(
            feature_snapshot=feature_snapshot,
            primary_regime=stabilized["primary_regime"],
            htf_bias=htf_bias,
            market_state=market_state,
            definition=definition,
        )
        volatility_phase = detector._derive_volatility_phase(
            feature_snapshot=feature_snapshot,
            previous_report=previous_report,
            definition=definition,
        )
        market_phase = detector._derive_market_phase(
            primary_regime=stabilized["primary_regime"],
            market_state=market_state,
            ltf_execution_state=ltf_execution_state,
            volatility_phase=volatility_phase,
            bars_in_regime=stabilized["regime_persistence"]["bars_in_regime"],
            definition=definition,
        )
        active_event_flags = detector._derive_active_event_flags(
            feature_snapshot=feature_snapshot,
            primary_regime=stabilized["primary_regime"],
            htf_bias=htf_bias,
            definition=definition,
        )
        actionable_event_flags = detector._derive_actionable_event_flags(
            active_event_flags=active_event_flags,
            derivatives_state=feature_snapshot.get("derivatives_state") or {},
        )
        derivatives_confidence_multiplier = detector._derive_derivatives_confidence_multiplier(
            feature_snapshot.get("derivatives_state") or {}
        )
        adjusted_confidence = round(
            max(0.2, min(0.99, stabilized["confidence"] * derivatives_confidence_multiplier)),
            4,
        )
        consensus = detector._derive_symbol_states(symbol_features, definition)
        bias = detector._derive_bias(
            primary_regime=stabilized["primary_regime"],
            htf_bias=htf_bias,
        )
        alignment_score = detector._derive_alignment_score(
            confidence=adjusted_confidence,
            htf_bias=htf_bias,
            market_state=market_state,
            ltf_execution_state=ltf_execution_state,
            consensus_strength=consensus["consensus_strength"],
        )
        signals = detector._build_signals(
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
        execution_constraints = detector._derive_execution_constraints(
            primary_regime=stabilized["primary_regime"],
            market_state=market_state,
            ltf_execution_state=ltf_execution_state,
            market_phase=market_phase,
            risk_level=stabilized["risk_level"],
            consensus_strength=consensus["consensus_strength"],
            active_event_flags=actionable_event_flags,
            cooldown_remaining_bars=stabilized["regime_persistence"]["cooldown_remaining_bars"],
        )
        position_size_multiplier = detector._derive_position_size_multiplier(
            risk_level=stabilized["risk_level"],
            alignment_score=alignment_score,
            execution_constraints=execution_constraints,
        )
        entry_aggressiveness = detector._derive_entry_aggressiveness(
            alignment_score=alignment_score,
            risk_level=stabilized["risk_level"],
            execution_constraints=execution_constraints,
            market_phase=market_phase,
        )
        risk_regime = detector._derive_risk_regime(
            primary_regime=stabilized["primary_regime"],
            risk_level=stabilized["risk_level"],
            execution_constraints=execution_constraints,
            active_event_flags=actionable_event_flags,
            consensus_strength=consensus["consensus_strength"],
        )
        regime_quality = detector._derive_regime_quality(
            alignment_score=alignment_score,
            execution_constraints=execution_constraints,
            market_phase=market_phase,
            active_event_flags=actionable_event_flags,
            derivatives_state=feature_snapshot.get("derivatives_state") or {},
        )
        lead_symbol, lag_confirmation = detector._derive_market_leadership(symbol_features, consensus)

        return {
            "generated_at": window.asof_iso,
            "asof_timeframe": self.config.base_timeframe,
            "universe": [item.get("pair") for item in symbol_features],
            "primary_regime": stabilized["primary_regime"],
            "confidence": adjusted_confidence,
            "risk_level": stabilized["risk_level"],
            "trend_strength": feature_snapshot["trend_strength"],
            "volatility_level": feature_snapshot["volatility_level"],
            "volume_state": feature_snapshot["volume_state"],
            "derivatives_state": feature_snapshot["derivatives_state"],
            "feature_snapshot": feature_snapshot,
            "reasons": stabilized["reasons"],
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
            "outcome_tracking_status": "system_replay",
        }

    def _latest_completed_1h_index(self, *, current_hour_start: datetime) -> int:
        first_pair = self.config.universe[0]
        htf_dates = [_to_datetime(row["date"]) for row in self.frames[first_pair]["1h"]]
        index = -1
        for cursor, row_time in enumerate(htf_dates):
            if row_time < current_hour_start:
                index = cursor
            else:
                break
        return index

    @staticmethod
    def _lead_pair(symbol_features: list[dict[str, Any]]) -> str:
        if not symbol_features:
            return "BTC/USDT:USDT"
        leader = max(
            symbol_features,
            key=lambda item: abs(float(item.get("recent_move_abs_pct") or 0.0)),
        )
        return str(leader.get("pair") or "BTC/USDT:USDT")
