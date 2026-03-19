# Structured Futures Short Breakdown V1 Hypothesis

- hypothesis_id: structured_futures_short_breakdown_v1
- strategy_name: StructuredFuturesShortBreakdownStrategy
- thesis: Trade only strong 5m breakdowns that align with a real 1h downtrend. The goal is to validate whether short edge exists as a standalone futures candidate instead of contaminating the long-biased baseline.
- expected_regimes:
  - trend_down_breakdown
  - stress_downside_expansion
- invalidation_rules:
  - broad backtest stays negative after fees
  - short candidate only works in one very narrow window
  - drawdown breaches the current hard risk gate
- key_risks:
  - downside squeezes can invalidate shorts quickly
  - funding drag can erase a small short edge
  - breakdowns in noisy regimes can produce false continuation
- next_test: Run the standard broad backtest bundle and decide whether the short side deserves to stay active or should remain parked.
