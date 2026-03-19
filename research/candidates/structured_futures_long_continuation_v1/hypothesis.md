# Structured Futures Long Continuation V1 Hypothesis

- hypothesis_id: structured_futures_long_continuation_v1
- strategy_name: StructuredFuturesLongContinuationStrategy
- thesis: Trade only higher-quality long continuation setups where the 1h trend is already constructive and the 5m market re-accelerates after a shallow reset. The goal is to test whether a cleaner long-only candidate outperforms the current baseline.
- expected_regimes:
  - trend_up_continuation
  - breakout_after_consolidation
- invalidation_rules:
  - broad backtest stays negative after fees
  - candidate only wins in one isolated window
  - drawdown breaches the current hard risk gate
- key_risks:
  - trend exhaustion can create late entries
  - low-volatility chop can fake continuation
  - small universe can hide regime concentration
- next_test: Build broad backtest evidence and compare this long-only candidate directly against the baseline.
