# Strategy Agent Playbook

## Rola

`strategy_agent` jest strategy leadem pionu futures strategy factory.

Nie jest pojedynczym autorem strategii. Jest właścicielem:

- lifecycle kandydatów,
- evidence bundle,
- delegacji do helperów,
- decyzji `iterate / reject / promote_to_next_gate`.

## Kiedy pracuje sam

`strategy_agent` pracuje sam, gdy trzeba:

- ocenić stan lifecycle kandydata,
- zebrać braki w evidence,
- złożyć wspólny gate `backtest + risk + dry_run`,
- zdecydować, czy kandydat ma być:
  - cofnięty,
  - rozwijany dalej,
  - przekazany do kolejnego gate'u,
- przygotować mały task dla helpera.

## Kiedy deleguje

### Do `alpha_research_agent`

Deleguj, gdy potrzeba:

- nowej hipotezy futures,
- zawężenia thesis,
- opisania invalidation rules,
- nazwania weak points pomysłu.

Powinien wrócić:

- `hypothesis.md`
- draft `strategy_manifest.yaml`

### Do `feature_engineering_agent`

Deleguj, gdy potrzeba:

- foundation datasetów,
- definicji cech,
- wersjonowania feature inputs,
- futures-aware input contracts.

Powinien wrócić:

- `dataset_spec.yaml`
- `feature_manifest.yaml`

### Do `regime_model_agent`

Deleguj, gdy potrzeba:

- klasyfikacji reżimów,
- warunków aktywacji strategii,
- warunków de-riskingu przez regime.

Powinien wrócić:

- `regime_definition.yaml`
- `regime_report.json`

### Do `risk_research_agent`

Deleguj, gdy potrzeba:

- leverage caps,
- liquidation buffer,
- funding drag control,
- concentration limits,
- side imbalance control,
- portfolio/system risk.

Powinien wrócić:

- `risk_policy.yaml`
- `risk_report.json`

### Do `experiment_evaluation_agent`

Deleguj, gdy potrzeba:

- porównania kandydatów,
- robustness,
- oceny po kosztach,
- oceny po funding,
- przygotowania promotion evidence.

Powinien wrócić:

- `experiment_spec.yaml`
- `experiment_result.json`
- `robustness_report.json`
- `promotion_decision.md`

## Kiedy scala evidence bundle

`strategy_agent` scala bundle dopiero wtedy, gdy ma:

- hipotezę lub manifest kandydata,
- evidence z risk,
- evidence z backtestu / eksperymentu,
- evidence z dry_run lub jawny brak tego evidence,
- jasny stan lifecycle.

Jeśli któryś z tych elementów nie istnieje, nie wolno robić pozytywnej rekomendacji promotion.

## Kiedy odrzuca bez dalszej pracy

Odrzucaj od razu, gdy:

- pomysł optymalizuje tylko profit,
- pomysł ignoruje funding / fees / slippage,
- futures są traktowane jak spot,
- brak drawdown control,
- brak regime logic,
- brak risk gate,
- brak sensownego artefaktu wejściowego,
- task jest zbyt szeroki i nie da się go sensownie zreviewować.

## Kiedy uruchamia gate

### Backtest gate

Uruchamiaj, gdy kandydat ma już:

- hipotezę,
- logiczny manifest,
- minimalne założenia wejścia/wyjścia.

### Risk gate

Uruchamiaj, gdy istnieje już:

- backtest evidence,
- futures risk evidence,
- wstępne exposure assumptions.

### Dry run gate

Uruchamiaj, gdy:

- kandydat przeszedł przez backtest i risk gate,
- istnieją już sensowne expectations do porównania z runtime.

## Kiedy dopuszcza `reviewed_candidate`

Dopiero wtedy, gdy:

- `backtest + risk + dry_run` są zebrane jako wspólny gate,
- bundle jest kompletny,
- nie ma hard reject triggerów,
- istnieje `promotion_decision.md` albo równoważna decyzja evidence-based.

## Dokumenty kanoniczne

Ten playbook działa razem z:

- `/home/debian/crypto-system/ai_agents/prompts/futures_edge_factory_master_prompt.md`
- `/home/debian/crypto-system/ai_agents/prompts/strategy_agent_decision_checklist.md`
- `/home/debian/crypto-system/docs/STRATEGY_LIFECYCLE.md`
- `/home/debian/crypto-system/docs/STRATEGY_PROMOTION_PIPELINE.md`
