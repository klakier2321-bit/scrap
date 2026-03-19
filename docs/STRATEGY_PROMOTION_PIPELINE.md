# Strategy Promotion Pipeline

## Kolejność bramek

1. sanity check
2. backtest po kosztach
3. robustness
4. risk gate
5. dry_run validation
6. review gate

## Zasada

Strategia nie przechodzi dalej dlatego, że ma ładny profit.
Przechodzi dalej tylko wtedy, gdy przechodzi wszystkie bramki jakości i ryzyka.

## Promotion evidence

Każdy kandydat musi mieć:

- `strategy_manifest.yaml`
- `risk_report.json`
- `experiment_result.json`
- `robustness_report.json`
- `promotion_decision.md`

