# Structured Futures Long Continuation V1 Promotion Decision

- strategy_id: structured_futures_long_continuation_v1
- current_state: frozen_pending_regime_engine
- backtest_gate: frozen
- risk_gate: frozen
- dry_run_gate: frozen
- promotion_decision: wait_for_regime_engine
- reason: Long continuation candidate is frozen until the regime detector can clearly separate trend-up conditions from range and low-vol periods.
- next_step: Hold this candidate as reference material and resume only after regime detection and regime-aware contracts are stable.
