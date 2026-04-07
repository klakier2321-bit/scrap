# Agents v2

## Cel

`agents.yaml v2` porzadkuje agentow do modelu:

- maly aktywny rdzen
- jawne drzewo odpowiedzialnosci
- `ops_observability_agent` jako jeden owner Grafany, kosztow i stanu runtime
- 5 stewardow strategii zdefiniowanych, ale domyslnie wylaczonych
- `artifact-first context packs`, zeby nie pompowac szerokiego kontekstu do modeli

## Aktywny rdzen

- `system_lead_agent`
- `review_agent`
- `control_layer_agent`
- `strategy_agent`
- `regime_model_agent`
- `feature_engineering_agent`
- `risk_research_agent`
- `ops_observability_agent`

Aktywacja:
- `always_on_guarded`

## On-demand

- `architecture_agent`
- `experiment_evaluation_agent`
- `integration_agent`

Aktywacja:
- `manual_only`

## Disabled by default

- `alpha_research_agent`
- `api_agent`
- `gui_agent`
- `trend_pullback_steward`
- `breakout_from_compression_steward`
- `range_mean_reversion_steward`
- `panic_reversal_steward`
- `defense_only_steward`

Aktywacja:
- `disabled_by_default`
- wymagaja jawnego enable przez operatora

## Drzewo ownership

- `system_lead_agent`
  - `review_agent`
  - `architecture_agent`
  - `control_layer_agent`
    - `integration_agent`
    - `api_agent`
    - `gui_agent`
  - `ops_observability_agent`
  - `strategy_agent`
    - `regime_model_agent`
    - `feature_engineering_agent`
    - `risk_research_agent`
    - `experiment_evaluation_agent`
    - `alpha_research_agent`
    - `trend_pullback_steward`
    - `breakout_from_compression_steward`
    - `range_mean_reversion_steward`
    - `panic_reversal_steward`
    - `defense_only_steward`

## Guarded cost control

- budzety sa trzymane w `ai_agents/config/budgets.yaml`
- operator moze nadpisac `enabled`, `daily_budget_usd`, `per_run_budget_usd`
- overridy sa zapisywane w `data/ai_control/agent_runtime_overrides.json`
- `manual_only` nie wchodzi do autopilota
- `disabled_by_default` wymaga jawnego enable
- agent bez prawa `can_touch_runtime` nie moze dotykac runtime
- `max_parallel_runs` ogranicza rownolegly spam jednego agenta

## Grafana i operator visibility

Owner:
- `ops_observability_agent`

Glowne zrodla:
- `/metrics`
- `/ops/agents`
- `/ops/executive/report`
- `data/ai_control/agent_context/packets/`

Dashboardy:
- `infrastructure/grafana/dashboards/agent-overview.json`
- `infrastructure/grafana/dashboards/token-cost-dashboard.json`

## Context packs

Pakiety sa lekkim, tanim kontekstem dla agentow:

- `runtime_state_packet`
- `executive_packet`
- `cost_packet`
- `agent_tree_packet`
- `strategy_packet`
- `module_packet`

Sciezka:
- `data/ai_control/agent_context/packets/`

Zasada:
- najpierw pakiety i artefakty
- dopiero potem glebszy odczyt repo
- bez plugin-first runtime na tym etapie

## Zasady stewardow

Kazdy steward:
- czyta replay, telemetry, manifesty i research swojej strategii
- moze pisac tylko w swoim obszarze stewardingu i researchu
- nie moze zmieniac `risk`, `execution`, kontraktow runtime ani budzetow globalnych

## Migracja ze starego ukladu

- stare podejscie `candidate-first` jest archive-only
- autopilot zostaje zawężony do rdzenia
- observability zostaje skupione pod jednym ownerem
- stewardzi sa gotowi do aktywacji, ale nie startuja automatycznie
