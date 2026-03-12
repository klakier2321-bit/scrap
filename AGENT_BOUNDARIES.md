# Agent Boundaries

## Responsibility rule

Zasada podstawowa:

1 agent = 1 warstwa odpowiedzialności

Każdy agent ma jasno ograniczony zakres zmian i nie powinien samodzielnie wchodzić w obszary innych agentów bez wyraźnej potrzeby i review.

## Directory ownership

- `core/` - głównie `control_layer_agent`
- `trading/` - głównie `strategy_agent`
- `monitoring/` i przyszłe dashboardy - głównie `monitoring_agent`
- dokumentacja architektury i układu projektu - głównie `architecture_agent`
- przyszłe API - głównie `api_agent`
- przyszłe GUI - głównie `gui_agent`
- połączenia między warstwami - głównie `integration_agent`
- przegląd jakości i zgodności zmian - `review_agent`

## Forbidden scope for all agents

Agentom nie wolno samodzielnie zmieniać:

- lokalnych runtime configów
- sekretów
- live tradingu
- exchange API keys

## Sensitive files and runtime limits

- Runtime configi lokalne są poza zakresem agentów.
- Sekrety są poza zakresem agentów.
- `docker-compose.yml` może być zmieniany tylko świadomie i wyjątkowo.
- Live trading i exchange API keys są poza zakresem agentów.

## Review rule

Większe zmiany powinny przechodzić review przed wdrożeniem.
Dotyczy to szczególnie zmian w architekturze, integracjach, konfiguracji runtime i logice mogącej wpływać na bezpieczeństwo systemu.
