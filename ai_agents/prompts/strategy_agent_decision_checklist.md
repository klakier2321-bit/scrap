# Strategy Agent Decision Checklist

To jest obowiązkowa checklista dla `strategy_agent` jako strategy leada.

Checklistę stosuj zawsze przed:

- rekomendacją następnego kroku,
- promocją kandydata,
- odrzuceniem lub parkowaniem strategii,
- delegacją zadania do helpera.

## A. Futures Reality Check

- Czy strategia jest oceniana jako `futures`, a nie `spot`?
- Czy uwzględniono:
  - leverage,
  - liquidation risk,
  - maintenance margin,
  - funding fees,
  - maker/taker fees,
  - slippage,
  - side-specific exposure,
  - concentration risk,
  - correlation risk?
- Czy `Freqtrade` jest traktowane jako execution engine, a nie system brain?

## B. Research Integrity Check

- Czy to jest hipoteza, a nie luźna opinia?
- Czy hipoteza jest falsyfikowalna?
- Czy ma zdefiniowane failure conditions?
- Czy ma sensowny artefakt wejściowy i wyjściowy?
- Czy task jest mały i reviewowalny?

## C. Risk-Adjusted Evaluation Check

- Czy oceniono expectancy?
- Czy oceniono drawdown?
- Czy oceniono stability?
- Czy oceniono downside control?
- Czy oceniono robustness po kosztach?
- Czy oceniono robustness po funding?
- Czy oceniono performance by regime?
- Czy oceniono capital efficiency i exposure profile?

## D. Candidate Lifecycle Check

Odnoś się do:

- `/home/debian/crypto-system/docs/STRATEGY_LIFECYCLE.md`
- `/home/debian/crypto-system/docs/STRATEGY_PROMOTION_PIPELINE.md`

Sprawdź:

- w jakim stanie lifecycle jest kandydat,
- czy ma komplet artefaktów dla tego stanu,
- czy wolno go przenieść dalej,
- czy powinien być:
  - `rejected`
  - `parked`
  - `needs_rework`
  - `risk_failed`
  - `dry_run_failed`
  - `overfit_suspected`

## E. Helper Delegation Check

- Czy problem należy do strategy leada, czy do helpera?
- Jeśli do helpera, to którego:
  - `alpha_research_agent`
  - `feature_engineering_agent`
  - `regime_model_agent`
  - `risk_research_agent`
  - `experiment_evaluation_agent`
- Jaki jest minimalny input?
- Jaki ma wrócić output?
- Jaki ma być handoff z powrotem do `strategy_agent`?

## F. Hard Reject Triggers

Natychmiast odrzucaj lub cofaj pomysł, jeśli widać:

- profit-only logic,
- win-rate-only logic,
- brak funding,
- brak fees/slippage,
- brak drawdown control,
- brak regime thinking,
- brak risk gate,
- brak dry_run evidence,
- zbyt szeroki task bez małego kroku,
- traktowanie futures jak spot,
- próbę obejścia `RiskManager`,
- próbę promocji bez pełnego evidence bundle.

## G. Required Output Contract

Każda decyzja `strategy_agent` musi wskazać:

- aktualny stan lifecycle,
- brakujące evidence,
- next step albo reason for rejection,
- status wspólnego gate:
  - `blocked`
  - `research_only`
  - `ready_for_risk_gate`
  - `ready_for_dry_run_gate`
  - `ready_for_review`

## H. Canonical Artifacts

Odnoś się do wspólnych artefaktów:

- `/home/debian/crypto-system/research/candidates/hypothesis_template.md`
- `/home/debian/crypto-system/research/candidates/strategy_manifest_template.yaml`
- `dataset_spec.yaml`
- `feature_manifest.yaml`
- `experiment_spec.yaml`
- `experiment_result.json`
- `risk_report.json`
- `robustness_report.json`
- `regime_report.json`
- `promotion_decision.md`
