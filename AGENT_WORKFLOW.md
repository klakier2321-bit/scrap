# Agent Workflow

## Standard flow

Agent dostaje zadanie z jasno określonym celem, zakresem i ograniczeniami.
Najpierw analizuje scope i identyfikuje, której warstwy projektu dotyczy zmiana.
Wejściem do pracy powinien być ustandaryzowany task, a wyjściem ustandaryzowany artefakt lub diff.

## Scope analysis

Agent powinien ustalić:
- jaki katalog i jaka warstwa są objęte zmianą
- czy zadanie mieści się w jego odpowiedzialności
- czy zmiana dotyka runtime, bezpieczeństwa lub sekretów

Jeśli zmiana wychodzi poza jego warstwę, agent powinien ograniczyć zakres albo przekazać sprawę do review.

## Change boundaries

Agent ogranicza zmiany do swojej warstwy odpowiedzialności.
Nie powinien samodzielnie rozszerzać scope na inne moduły tylko dlatego, że jest to wygodne technicznie.

## Diff and output

Przed zamknięciem zadania agent powinien pokazać czytelny diff lub listę zmienionych plików.
Zmiany mają być małe, konkretne i możliwe do prostego review.

## Review handoff

Agent przekazuje zmianę do review, gdy:
- zmiana dotyka więcej niż jednej warstwy
- zmiana wpływa na bezpieczeństwo
- zmiana dotyka konfiguracji runtime
- zmiana może wpływać na zachowanie tradingowe

## Commit rule

Commit można wykonać dopiero po domknięciu scope i upewnieniu się, że zmiana mieści się w odpowiedzialności agenta.
Preferowana zasada:

1 commit = 1 logiczna zmiana

Zmiany średniego i wysokiego ryzyka powinny przejść przez review przed commitem lub przed scaleniem.

## Hard boundaries

Agent nie wdraża live tradingu.
Agent nie dotyka sekretów.
Agent nie zmienia lokalnych runtime configów bez wyraźnej decyzji człowieka.
