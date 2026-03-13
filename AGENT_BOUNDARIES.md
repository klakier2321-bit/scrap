# Agent Boundaries

## Responsibility rule

Zasada podstawowa:

1 agent = 1 warstwa odpowiedzialności

Każdy agent ma jasno ograniczony zakres zmian i nie powinien samodzielnie wchodzić w obszary innych agentów bez wyraźnej potrzeby i review.
`system_lead_agent` może koordynować scope i delegację, ale nie ma prawa naruszać granic bezpieczeństwa ani przejmować zmian poza procesem review.
Pełna kontrola `system_lead_agent` oznacza pełną kontrolę planowania i delegacji, a nie pełną władzę nad runtime i bezpieczeństwem.

## Directory ownership

- koordynacja scope i delegacji - `system_lead_agent`
- `core/` - głównie `control_layer_agent`
- `trading/` - głównie `strategy_agent`
- `monitoring/` i przyszłe dashboardy - głównie `monitoring_agent`
- dokumentacja architektury i układu projektu - głównie `architecture_agent`
- przyszłe API - głównie `api_agent`
- przyszłe GUI - głównie `gui_agent`
- połączenia między warstwami - głównie `integration_agent`
- przegląd jakości i zgodności zmian - `review_agent`

Szczegółowa macierz `owned / read-only / forbidden` znajduje się w `ai_agents/rules/OWNERSHIP_MATRIX.md`.

## Forbidden scope for all agents

Agentom nie wolno samodzielnie zmieniać:

- lokalnych runtime configów
- sekretów
- live tradingu
- exchange API keys
- omijania review człowieka przy zmianach wysokiego ryzyka

## Sensitive files and runtime limits

- Runtime configi lokalne są poza zakresem agentów.
- Sekrety są poza zakresem agentów.
- `docker-compose.yml` może być zmieniany tylko świadomie i wyjątkowo.
- Live trading i exchange API keys są poza zakresem agentów.
- `system_lead_agent` nie może używać swojej roli koordynacyjnej do omijania tych ograniczeń.

## Review rule

Większe zmiany powinny przechodzić review przed wdrożeniem.
Dotyczy to szczególnie zmian w architekturze, integracjach, konfiguracji runtime i logice mogącej wpływać na bezpieczeństwo systemu.
`system_lead_agent` może wymagać review, ale nie może go znosić dla zmian wysokiego ryzyka.

Zmiany cross-layer powinny być prowadzone wyłącznie świadomie i zgodnie z zasadami z `ai_agents/rules/CROSS_LAYER_RULES.md`.
