# Structured Futures Baseline V1 Hypothesis

- hypothesis_id: structured_futures_baseline_v1
- strategy_name: StructuredFuturesBaselineStrategy
- thesis: Trade 5m pullbacks only in the direction of the 1h trend and only when short-term momentum confirms continuation. This should reduce random entries and create a simple futures-ready baseline for `backtest + dry_run`.
- expected_regimes:
  - trend_up_pullback
  - trend_down_pullback
- invalidation_rules:
  - backtest remains negative after fees on the small BTC/ETH universe
  - drawdown exceeds the current hard risk gate
  - one side is consistently harmful and needs isolation or rework
- key_risks:
  - no dedicated funding time series in v1
  - no explicit regime engine yet
  - only a 2-pair universe, so the sample can be too narrow
- next_test: Start a limited dry_run for the long-biased baseline and treat short-side logic as parked until a separate short module is validated.

## First Backtest Snapshot

- status: needs_rework
- timerange: 2026-02-17 -> 2026-03-19
- total_trades: 63
- total_profit_pct: -1.72
- drawdown_pct: 2.14
- long_profit_pct: -0.23
- short_profit_pct: -1.49
- main finding: short entries are materially weaker than longs and dominate the loss profile

## Second Backtest Snapshot

- status: ready_for_dry_run_gate
- timerange: 2026-02-17 -> 2026-03-19
- total_trades: 8
- total_profit_pct: 0.33
- drawdown_pct: 0.19
- long_profit_pct: 0.33
- short_profit_pct: 0.0
- main finding: tighter momentum and trend filters removed the damaging short churn and produced a small but positive baseline with low drawdown

## Broader Backtest Check

- status: ready_for_dry_run_gate
- full_window: 2025-11-19 -> 2026-03-19
- full_window_total_trades: 70
- full_window_total_trades_after_short_rebuild: 23
- full_window_total_profit_pct: 0.10
- full_window_drawdown_pct: 0.27
- full_window_long_profit_pct: 0.10
- full_window_short_profit_pct: 0.0
- split_window_summary:
  - 2025-11-19 -> 2026-03-19: +0.10%
  - 2026-02-15 -> 2026-03-19: +0.19%
- main finding: the rebuilt short logic effectively parked weak short participation and left a cleaner long-biased futures baseline that stays slightly positive on the broad window with lower drawdown
