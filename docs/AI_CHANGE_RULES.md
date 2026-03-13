# Spec Core: AI Change Rules

## Kolejność czytania

1. `docs/ARCHITECTURE.md`
2. `docs/PROJECT_MAP.md`
3. `docs/DECISIONS.md`
4. `docs/openapi.yaml`
5. dopiero potem starsze dokumenty z root

## Reading rule

Najpierw czytaj Spec Core, potem pliki modułu, którego dotyczy zadanie.

## Ownership

- agent core tylko `core/`
- agent strategies/runtime tylko `trading/`
- agent AI tylko `ai_agents/`
- agent scripts tylko `scripts/`
- tylko architekt lub `system_lead_agent` może zmieniać dokumenty kanoniczne i kontrakty

## Lead rule

`system_lead_agent` może planować i delegować zmiany w całym projekcie, ale nie może obchodzić ograniczeń bezpieczeństwa, zasad review ani zakazów dotyczących runtime i sekretów.

## Ownership model

Każdy agent działa w modelu:

- `owned scope`
- `read-only scope`
- `forbidden scope`

Dokładna macierz ownership znajduje się w `ai_agents/rules/OWNERSHIP_MATRIX.md`.
Maszynowo czytelny manifest scope znajduje się w `ai_agents/rules/AGENT_SCOPE_MANIFEST.yaml`.
Agent nie może zmieniać plików poza swoim `owned scope` bez jawnej eskalacji.

## Cross-layer rule

Jeśli zmiana dotyka plików innego agenta albo więcej niż jednej warstwy, traktujemy ją jako zmianę cross-layer.
Takie zmiany wymagają co najmniej review, a czasem decyzji człowieka.
Szczegóły znajdują się w `ai_agents/rules/CROSS_LAYER_RULES.md`.

## Execution mode

Domyślny tryb pracy agentów to `plan -> review -> write`.
Szczegóły znajdują się w `ai_agents/workflows/PLAN_REVIEW_WRITE.md`.
Agent nie powinien przechodzić bezpośrednio do zapisu plików bez wcześniejszego planu scope.

## Small change rule

- rób małe zmiany
- bez refaktoru całego repo
- bez zmian „przy okazji”
- nie poprawiaj cudzych plików bez powodu i bez scope

## Contract first rule

Jeśli zmiana dotyka kontraktu lub architektury, najpierw aktualizujesz `docs/`, a dopiero potem implementację.

## Minimalny template zmiany

- Co zmieniam
- Pliki które ruszam
- Czy dotykam kontraktu: tak/nie
- Jak testuję

## Definition of Done

- zmiana ma jasny zakres
- dokumentacja jest zgodna z implementacją
- jeśli dotyczy API, kontrakt jest zaktualizowany
- jeśli dotyczy ryzykownego obszaru, wymaga review
