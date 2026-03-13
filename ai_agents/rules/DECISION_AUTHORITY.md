# Decision Authority

## Primary objective

Nadrzędny cel warstwy agentowej to rozwój systemu, który ma w przyszłości maksymalizować długoterminowy zysk skorygowany o ryzyko.
Warstwa agentowa nie może dążyć do maksymalizacji surowego zysku kosztem bezpieczeństwa, review i kontroli ryzyka.

## System lead authority

`system_lead_agent` może samodzielnie:
- ustalać kolejność prac
- rozbijać cele na taski
- delegować pracę do agentów
- zatrzymywać zmiany wychodzące poza scope
- wymagać review
- akceptować artefakty niskiego ryzyka

## Review authority

`review_agent` może:
- oceniać ryzyko zmian
- blokować zmianę do czasu poprawek
- eskalować zmianę do człowieka

## Human-only authority

Tylko człowiek może podjąć decyzję o:
- live tradingu
- użyciu exchange API keys
- zmianie sekretów
- zmianie lokalnych runtime configów
- akceptacji zmian wysokiego ryzyka
- zmianach wrażliwych w `docker-compose.yml`

## Hard rule

Żaden agent, w tym `system_lead_agent`, nie może samodzielnie obchodzić tych ograniczeń.
