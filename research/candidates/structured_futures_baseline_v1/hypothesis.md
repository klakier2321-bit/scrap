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
- next_test: Rework the short-side logic first, then rerun the same futures backtest before any dry_run promotion.

## First Backtest Snapshot

- status: needs_rework
- timerange: 2026-02-17 -> 2026-03-19
- total_trades: 63
- total_profit_pct: -1.72
- drawdown_pct: 2.14
- long_profit_pct: -0.23
- short_profit_pct: -1.49
- main finding: short entries are materially weaker than longs and dominate the loss profile
