# Strategy Lifecycle

## Główne stany

- `idea`
- `hypothesis`
- `research_experiment`
- `candidate`
- `validated_candidate`
- `risk_approved_candidate`
- `dry_run_candidate`
- `reviewed_candidate`
- `promoted_candidate`
- `future_live_candidate`

## Stany negatywne

- `rejected`
- `parked`
- `needs_rework`
- `overfit_suspected`
- `risk_failed`
- `dry_run_failed`

## Zasada odpowiedzialności

Tylko `strategy_agent` może przenosić strategię między głównymi stanami lifecycle.
Helperzy dostarczają evidence, nie decyzję końcową.

