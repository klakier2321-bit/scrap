# Agent Build Flow

## Build approach

System ma być budowany warstwami przez agentów, a nie chaotycznie przez przypadkowe zmiany w całym repo.

## Coordination

`system_lead_agent` rozbija cele na mniejsze zadania, ustala kolejność prac i deleguje zadania do agentów warstwowych.

## Typical order of work

Najczęściej jako pierwsi wchodzą:
- `review_agent`
- `system_lead_agent`
- `architecture_agent`
- `control_layer_agent`

Potem dołączają agenci bardziej wyspecjalizowani, tacy jak:
- `strategy_agent`
- `monitoring_agent`
- `integration_agent`
- `api_agent`
- `gui_agent`

## Agent outputs

Agenci produkują artefakty takie jak:
- dokumentacja
- szkielety modułów
- propozycje zmian architektury
- workflow testowe
- moduły w swojej warstwie odpowiedzialności
- taski wejściowe
- review reports
- decyzje delegacyjne i statusy realizacji

## Mandatory review

`review_agent` wchodzi obowiązkowo przed większymi zmianami, zmianami wielowarstwowymi i zmianami dotykającymi bezpieczeństwa.

## Human decision points

Decyzja człowieka jest potrzebna przy zmianach wysokiego ryzyka, zmianach runtime, zmianach bezpieczeństwa, zmianach związanych z tradingiem live i sekretami.

## Scope rule

CrewAI ma w przyszłości rozwijać system nad control layer, a nie bezpośrednio nad giełdą.
`strategy_agent`, `api_agent`, `gui_agent`, `monitoring_agent` i `control_layer_agent` rozwijają tylko swoje warstwy.
`system_lead_agent` steruje kolejnością pracy tych agentów, ale nie zastępuje ich specjalizacji.
