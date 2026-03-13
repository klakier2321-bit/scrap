# Spec Core: Decisions

## Freqtrade as Engine

Freqtrade jest silnikiem wykonawczym i narzędziem backtestowym.
Repo nie traktuje go jako głównego miejsca logiki całego systemu.

## Start in Dry Run

System startuje od `dry_run = true`.
To ogranicza ryzyko na etapie budowy, testów i pierwszych iteracji strategii.

## Profit Means Risk-Adjusted Profit

Projekt ma dążyć do wysokiej rentowności, ale nie do surowego zysku za wszelką cenę.
Priorytetem jest długoterminowy zysk skorygowany o ryzyko, a nie agresja kapitałowa lub omijanie zasad bezpieczeństwa.

## AI Does Not Trade Directly

AI może analizować i proponować zmiany, ale nie wykonuje bezpośrednio trade.
Decyzje wykonawcze mają przechodzić przez control layer i zasady bezpieczeństwa.

## Runtime Configs Stay Local

Lokalne runtime configi i sekrety są poza zakresem agentów i Git.
Dotyczy to w szczególności `.env`, `config.json` i innych plików lokalnych.

## Docker Compose Is Sensitive

`docker-compose.yml` jest plikiem wrażliwym, bo wpływa na runtime całego systemu.
Zmiany w nim powinny być rzadkie, świadome i reviewowane.

## Agent Ownership Matters

Każdy agent ma przypisaną warstwę odpowiedzialności.
To ogranicza chaos i zmniejsza ryzyko zmian „przy okazji”.

## System Lead Orchestrates, Does Not Override Safety

`system_lead_agent` prowadzi projekt, planuje pracę i deleguje zadania.
Nie ma jednak prawa omijać review człowieka, dotykać sekretów ani przejmować decyzji wysokiego ryzyka.

## Risky Changes Require Review

Zmiany dotykające runtime, bezpieczeństwa, kontraktów, live tradingu lub sekretów wymagają review człowieka.
`review_agent` wspiera analizę, ale nie zastępuje człowieka.
