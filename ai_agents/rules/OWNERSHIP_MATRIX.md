# Ownership Matrix

## Rule

Każdy agent pracuje wyłącznie we własnym zakresie odpowiedzialności.
Każdy agent ma trzy strefy:

- `owned scope` - może czytać i zmieniać
- `read-only scope` - może czytać, ale nie zmienia
- `forbidden scope` - nie zmienia bez eskalacji do review albo człowieka

## system_lead_agent

- owned scope:
  - dokumenty planistyczne agentów
  - taski, workflowy, reguły i koordynacja pracy
  - kanoniczne dokumenty tylko w zakresie planowania i po świadomej decyzji
- read-only scope:
  - całe repo
- forbidden scope:
  - sekrety
  - runtime configi lokalne
  - live trading
  - exchange API keys
  - bezpośrednie poprawianie modułów innych agentów jako zwykły wykonawca

## architecture_agent

- owned scope:
  - dokumentacja architektury
  - struktura repo
  - dokumenty kanoniczne po zatwierdzonym scope
- read-only scope:
  - `core/`
  - `trading/`
  - `ai_agents/`
  - `scripts/`
- forbidden scope:
  - sekrety
  - runtime configi
  - live trading

## control_layer_agent

- owned scope:
  - `core/`
  - dokumentacja control layer
- read-only scope:
  - `docs/`
  - `trading/`
  - `ai_agents/`
  - `scripts/`
- forbidden scope:
  - sekrety
  - runtime configi
  - `docker-compose.yml`
  - live trading

## strategy_agent

- owned scope:
  - `trading/`
  - dokumentacja strategii i backtestów
- read-only scope:
  - `core/`
  - `docs/`
  - `ai_agents/`
  - `scripts/`
- forbidden scope:
  - sekrety
  - runtime krytyczny
  - `docker-compose.yml`
  - live trading bez decyzji człowieka

## api_agent

- owned scope:
  - kontrakty API
  - dokumentacja API
  - przyszła warstwa API
- read-only scope:
  - `core/`
  - `trading/`
  - `docs/`
- forbidden scope:
  - sekrety
  - runtime configi
  - logika strategii
  - live trading

## gui_agent

- owned scope:
  - przyszła warstwa GUI
  - dokumentacja interfejsów
- read-only scope:
  - `docs/`
  - `core/`
  - `trading/`
- forbidden scope:
  - sekrety
  - konfiguracja giełdy
  - live trading

## monitoring_agent

- owned scope:
  - monitoring
  - dashboardy
  - metryki i feedback
- read-only scope:
  - `core/`
  - `trading/`
  - `docs/`
- forbidden scope:
  - sekrety
  - runtime configi
  - bezpośrednie wykonywanie trade

## integration_agent

- owned scope:
  - integracje między warstwami
  - glue code i zgodność połączeń
- read-only scope:
  - całe repo
- forbidden scope:
  - sekrety
  - live trading
  - samodzielne zmiany runtime configów bez review

## review_agent

- owned scope:
  - review zmian
  - raporty ryzyka
  - decyzje approve / revise / escalate
- read-only scope:
  - całe repo
- forbidden scope:
  - samodzielne wdrażanie zmian wysokiego ryzyka
  - sekrety
  - live trading
