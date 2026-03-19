# Research Layer

## Cel

Warstwa research ma systemowo budować edge, a nie tylko opisywać strategie.

## Podwarstwy

- `dataset_builder`
- `feature_store`
- `alpha_lab`
- `regime_detection`
- `strategy_candidates`
- `evaluation`
- `promotion`

## Role agentów

- `strategy_agent` scala i zarządza lifecycle
- `feature_engineering_agent` buduje foundation danych i cech
- `risk_research_agent` buduje foundation ryzyka
- `alpha_research_agent` generuje hipotezy
- `regime_model_agent` klasyfikuje środowisko rynku
- `experiment_evaluation_agent` porównuje kandydatów

## Zasada

Research layer ma odrzucać słabe pomysły wcześnie i promować tylko kandydatów z mocnym evidence bundle.

