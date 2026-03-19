# AI Agent Roles

## Leady

- `system_lead_agent`
  - globalny lead platformy
- `strategy_agent`
  - lead pionu strategii futures

## Helperzy strategii

- `alpha_research_agent`
  - hipotezy i weak point analysis
- `feature_engineering_agent`
  - datasety i cechy
- `regime_model_agent`
  - reżimy rynku
- `risk_research_agent`
  - futures risk architecture
- `experiment_evaluation_agent`
  - robustness, comparison, promotion evidence

## Zasada

Helperzy mają rozłączne role, a `strategy_agent` scala ich wynik w lifecycle kandydata.

`strategy_agent` działa według modelu:

- doctrine:
  - `ai_agents/prompts/futures_edge_factory_master_prompt.md`
- runtime checklist:
  - `ai_agents/prompts/strategy_agent_decision_checklist.md`
- operating playbook:
  - `docs/agent_playbooks/strategy_agent_playbook.md`
