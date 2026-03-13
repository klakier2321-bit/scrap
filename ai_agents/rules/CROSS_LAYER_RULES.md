# Cross-Layer Rules

## Default rule

Agent nie zmienia plików poza swoim `owned scope`.
Samo techniczne uzasadnienie nie wystarcza, żeby wejść w cudzy obszar.

## When cross-layer change is allowed

Zmiana cross-layer jest dopuszczalna tylko wtedy, gdy:

- zadanie zostało jawnie oznaczone jako cross-layer
- `system_lead_agent` zdekomponował i zatwierdził taki scope
- zmiana przechodzi przez review
- albo zmianę prowadzi `integration_agent`
- albo decyzję podejmuje człowiek

## What counts as cross-layer

Za zmianę cross-layer uznajemy sytuację, gdy agent:

- dotyka plików należących do innego agenta
- zmienia kontrakt między warstwami
- zmienia architekturę lub przepływ danych między modułami
- łączy zmiany w `core/`, `trading/`, `docs/`, `ai_agents/` lub `scripts/` w jednym kroku

## Required controls

Każda zmiana cross-layer musi mieć:

- ownera zadania
- listę dotykanych plików
- oznaczenie `cross-layer: yes`
- review obowiązkowe

## Forbidden cross-layer behavior

Niedozwolone jest:

- poprawianie cudzych plików "przy okazji"
- rozszerzanie scope bez zgody
- omijanie review, bo zmiana wydaje się mała
- używanie roli `system_lead_agent` do bezpośredniego przepisywania całego repo

## Human escalation

Jeśli zmiana cross-layer dotyka runtime, bezpieczeństwa, sekretów, live tradingu lub `docker-compose.yml`, decyzję musi podjąć człowiek.
