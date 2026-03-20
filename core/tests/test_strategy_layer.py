from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.strategy_layer.service import StrategyLayerService
from core.strategy_manager import StrategyManager


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFESTS_DIR = REPO_ROOT / "research" / "strategies" / "manifests"


def _risk_decision(
    *,
    trading_mode: str = "normal",
    data_trust_level: str = "full_trust",
    allowed_directions: list[str] | None = None,
) -> dict:
    return {
        "generated_at": "2026-03-20T00:00:00+00:00",
        "allow_trading": trading_mode != "blocked",
        "trading_mode": trading_mode,
        "risk_state": "normal",
        "risk_score": 30,
        "data_validation_status": "valid",
        "data_trust_level": data_trust_level,
        "allowed_directions": allowed_directions or ["long", "short"],
        "blocked_directions": [],
        "max_position_size_pct": 1.0,
        "max_total_exposure_pct": 20.0,
        "max_positions_total": 3,
        "max_positions_per_symbol": 1,
        "max_correlated_positions": 2,
        "allowed_strategy_ids": [],
        "blocked_strategy_ids": [],
        "allowed_strategy_families": [],
        "blocked_strategy_families": [],
        "leverage_cap": 2.0,
        "force_reduce_only": False,
        "new_entries_allowed": trading_mode != "blocked",
        "cooldown_active": False,
        "execution_budget_multiplier": 1.0,
        "hard_enforcement_enabled": True,
        "enforced_by": ["control_layer_preselection", "freqtrade_strategy_hook"],
        "last_enforcement_status": "allowed",
        "last_blocked_order_reason_codes": [],
        "enforcement_counters": {},
        "protective_overrides": {
            "force_conservative_execution": trading_mode in {"blocked", "capital_protection"},
            "disable_aggressive_entries": trading_mode in {"blocked", "capital_protection", "reduced_risk"},
            "tighter_risk_budget": trading_mode in {"capital_protection", "reduced_risk"},
        },
        "risk_reason_codes": [],
        "risk_notes": [],
        "decision_trace": [],
        "degradation_flags": {},
        "context": {},
    }


def _trend_pullback_regime() -> dict:
    return {
        "primary_regime": "trend_down",
        "confidence": 0.84,
        "risk_level": "medium",
        "risk_regime": "normal",
        "regime_quality": 0.79,
        "htf_bias": "short",
        "market_state": "pullback",
        "ltf_execution_state": "momentum_resuming",
        "market_phase": "pullback",
        "volatility_phase": "cooling",
        "market_consensus": "strong_bearish",
        "consensus_strength": 0.77,
        "active_event_flags": {},
        "actionable_event_flags": {},
        "active_event_flags_reliability": "medium",
        "derivatives_state_global": {
            "feed_status": "ok",
            "source": "binance_futures_public_api",
            "vendor_available": True,
            "event_reliability": "medium",
            "liquidation_event_confidence": "medium",
            "age_seconds": 60,
            "is_stale": False,
            "squeeze_risk": "low",
            "oi_price_agreement": "short_build",
            "positioning_state": "short_build",
        },
        "execution_constraints": {
            "no_trade_zone": False,
            "reduced_exposure_only": False,
            "high_noise_environment": False,
            "post_shock_cooldown": False,
        },
        "position_size_multiplier": 1.0,
        "entry_aggressiveness": "moderate",
        "alignment_score": 0.81,
        "feature_snapshot": {"reference_price": 82000.0},
        "lead_symbol": "BTC",
    }


def _panic_regime() -> dict:
    payload = _trend_pullback_regime()
    payload.update(
        {
            "primary_regime": "stress_panic",
            "risk_regime": "high",
            "htf_bias": "neutral",
            "market_state": "transition",
            "market_phase": "transition",
            "volatility_phase": "extreme",
            "market_consensus": "weak_bearish",
            "consensus_strength": 0.52,
            "actionable_event_flags": {"panic_flush": True, "capitulation": True},
            "active_event_flags": {"panic_flush": True, "capitulation": True},
            "active_event_flags_reliability": "high",
            "execution_constraints": {
                "no_trade_zone": False,
                "reduced_exposure_only": True,
                "high_noise_environment": False,
                "post_shock_cooldown": False,
            },
            "derivatives_state_global": {
                "feed_status": "ok",
                "source": "binance_futures_public_api",
                "vendor_available": True,
                "event_reliability": "high",
                "liquidation_event_confidence": "high",
                "age_seconds": 40,
                "is_stale": False,
                "squeeze_risk": "low",
                "oi_price_agreement": "long_unwind",
                "positioning_state": "long_unwind",
            },
        }
    )
    return payload


class StrategyLayerServiceTests(unittest.TestCase):
    def test_generates_trend_pullback_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = StrategyLayerService(
                manifests_dir=MANIFESTS_DIR,
                output_dir=Path(tmpdir) / "signals",
                telemetry_dir=Path(tmpdir) / "telemetry",
            )
            report = service.generate_report(
                regime_report=_trend_pullback_regime(),
                risk_decision=_risk_decision(allowed_directions=["short"]),
                bot_id="candidate",
            )

            self.assertEqual(report["status"], "ok")
            self.assertIn("trend_pullback_continuation_v1", report["applicable_strategy_ids"])
            self.assertEqual(report["preferred_risk_admitted_strategy_id"], "trend_pullback_continuation_v1")
            self.assertEqual(report["preferred_strategy_id"], "trend_pullback_continuation_v1")
            self.assertIn("trend_pullback_continuation_v1", report["risk_admitted_strategy_ids"])
            self.assertTrue(report["built_signals"])
            self.assertEqual(report["built_signals"][0]["direction"], "short")
            self.assertTrue((Path(tmpdir) / "signals" / "latest-candidate.json").exists())

    def test_generates_panic_reversal_for_actionable_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = StrategyLayerService(
                manifests_dir=MANIFESTS_DIR,
                output_dir=Path(tmpdir) / "signals",
                telemetry_dir=Path(tmpdir) / "telemetry",
            )
            report = service.generate_report(
                regime_report=_panic_regime(),
                risk_decision=_risk_decision(trading_mode="capital_protection", allowed_directions=["long"]),
                bot_id="candidate",
            )

            panic_signal = next(
                signal for signal in report["built_signals"] if signal["strategy_id"] == "panic_reversal_v1"
            )
            self.assertEqual(report["preferred_risk_admitted_strategy_id"], "panic_reversal_v1")
            self.assertEqual(panic_signal["direction"], "long")
            self.assertTrue(panic_signal["risk_admissible"])

    def test_required_data_inputs_block_applicability(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = StrategyLayerService(
                manifests_dir=MANIFESTS_DIR,
                output_dir=Path(tmpdir) / "signals",
                telemetry_dir=Path(tmpdir) / "telemetry",
            )
            regime = _trend_pullback_regime()
            regime.pop("market_consensus", None)
            report = service.generate_report(
                regime_report=regime,
                risk_decision=_risk_decision(allowed_directions=["short"]),
                bot_id="candidate",
                strategy_filter_ids=["trend_pullback_continuation_v1"],
            )

            evaluation = report["strategy_evaluations"][0]
            self.assertFalse(evaluation["applicable"])
            self.assertIn(
                "required_input_missing:market_consensus",
                evaluation["applicability"]["reasons"],
            )
            self.assertEqual(report["risk_admitted_strategy_ids"], [])
            self.assertEqual(report["preferred_risk_admitted_strategy_id"], None)


class StrategyManagerStrategyLayerTests(unittest.TestCase):
    def test_lists_strategy_manifests_and_reads_latest_strategy_layer_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            user_data_dir = repo_root / "trading" / "freqtrade" / "user_data"
            reports_dir = repo_root / "data" / "ai_control" / "strategy_reports"
            signals_dir = repo_root / "data" / "ai_control" / "strategy_signals"
            manifests_dir = repo_root / "research" / "strategies" / "manifests"
            user_data_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            signals_dir.mkdir(parents=True)
            manifests_dir.mkdir(parents=True)

            (manifests_dir / "demo.yaml").write_text(
                "\n".join(
                    [
                        "strategy_id: demo_strategy_v1",
                        "display_name: Demo Strategy",
                        "version: '1.0.0'",
                        "strategy_family: breakout",
                        "risk_profile: balanced",
                        "execution_style: breakout",
                        "archetype: demo",
                        "status: experimental",
                    ]
                ),
                encoding="utf-8",
            )
            (signals_dir / "latest-ft_trend_pullback_continuation_v1.json").write_text(
                '{"generated_at":"2026-03-20T00:00:00+00:00","bot_id":"ft_trend_pullback_continuation_v1","status":"ok","manifests_total":1,"implemented_strategies_total":0,"applicable_strategy_ids":[],"blocked_strategy_ids":[],"risk_admitted_strategy_ids":[],"blocked_by_risk_strategy_ids":[],"advisory_strategy_ids":[],"strategy_evaluations":[],"built_signals":[],"preferred_strategy_id":null,"preferred_risk_admitted_strategy_id":null,"ranking":[]}',
                encoding="utf-8",
            )

            manager = StrategyManager(
                user_data_dir=user_data_dir,
                reports_dir=reports_dir,
                dry_run_snapshots_dir=repo_root / "data" / "ai_control" / "dry_run_snapshots",
                strategy_signals_dir=signals_dir,
            )
            manifests = manager.list_strategy_manifests()
            latest = manager.latest_strategy_layer_report()

            self.assertEqual(len(manifests), 1)
            self.assertEqual(manifests[0]["strategy_id"], "demo_strategy_v1")
            self.assertIn("manifest_path", manifests[0])
            self.assertEqual(latest["status"], "ok")
