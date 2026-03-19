# Spec Core: Decisions

## Freqtrade as Engine

Freqtrade jest silnikiem wykonawczym i narzędziem backtestowym.
Repo nie traktuje go jako głównego miejsca logiki całego systemu.

## Control Layer Owns System Decisions

`core/` i control layer maja dojrzewac jako jedyne miejsce systemowych decyzji operacyjnych.
To tam maja byc spinane:

- risk gating,
- executive reporting,
- operatorskie API,
- read-only bridge do runtime,
- bezpieczne workflow agentowe.

## Start in Dry Run

System startuje od `dry_run = true`.
To ogranicza ryzyko na etapie budowy, testów i pierwszych iteracji strategii.

## Profit Means Risk-Adjusted Profit

Projekt ma dążyć do wysokiej rentowności, ale nie do surowego zysku za wszelką cenę.
Priorytetem jest długoterminowy zysk skorygowany o ryzyko, a nie agresja kapitałowa lub omijanie zasad bezpieczeństwa.

## AI Does Not Trade Directly

AI może analizować i proponować zmiany, ale nie wykonuje bezpośrednio trade.
Decyzje wykonawcze mają przechodzić przez control layer i zasady bezpieczeństwa.

## Strategy Pillar Has Its Own Lead

`strategy_agent` jest strategyleadem pionu futures strategy factory.
To oznacza, ze:

- `system_lead_agent` nie powinien mikrozarzadzac helperami strategii,
- helperzy strategii dostarczaja artefakty evidence-first,
- tylko `strategy_agent` scala lifecycle i promotion gate kandydatow.

## Branch Commits Do Not Equal Mainline Completion

W supervised coding flow agent commituje najpierw na branchu worktree.
To oznacza:

- `committed` task agenta nie jest automatycznie rowny merge do `main`
- postep branchowy i postep platformy trzeba raportowac osobno
- executive reporting nie powinien traktowac branchowego commita jako domkniecia platformy bez dodatkowego kroku nadzoru

Domyslna interpretacja v1:

- `committed_on_task_branch` = postep coding flow
- `merged_to_main` = postep repo
- `runtime_active` = postep operacyjny

## Futures First, Not Spot Thinking

Rozwoj warstwy strategii ma byc futures-first.
Kazda rekomendacja strategii, ryzyka i oceny kandydata ma uwzgledniac:

- leverage,
- funding,
- slippage i fees,
- liquidation risk,
- exposure i concentration,
- performance by regime.

## Runtime Configs Stay Local

Lokalne runtime configi i sekrety są poza zakresem agentów i Git.
Dotyczy to w szczególności `.env`, `config.json` i innych plików lokalnych.

## Docker Compose Is Sensitive

`docker-compose.yml` jest plikiem wrażliwym, bo wpływa na runtime całego systemu.
Zmiany w nim powinny być rzadkie, świadome i reviewowane.

## Agent Ownership Matters

Każdy agent ma przypisaną warstwę odpowiedzialności.
To ogranicza chaos i zmniejsza ryzyko zmian „przy okazji”.

## Local Test Contract Must Be Explicit

Lokalne testy i compile maja byc uruchamiane z root repo i na jawnie zainstalowanych zaleznosciach control plane.
Nie zakladamy, ze "systemowe python3" ma komplet pakietow do `core/` i `ai_agents/`.

Kanoniczny model lokalny:

- zaleznosci z `requirements-ai-control.txt`
- uruchamianie z root repo
- testy odseparowane od aktywnego coding supervisora, gdy potrzebna jest czysta diagnostyka

## System Lead Orchestrates, Does Not Override Safety

`system_lead_agent` prowadzi projekt, planuje pracę i deleguje zadania.
Nie ma jednak prawa omijać review człowieka, dotykać sekretów ani przejmować decyzji wysokiego ryzyka.

## Risky Changes Require Review

Zmiany dotykające runtime, bezpieczeństwa, kontraktów, live tradingu lub sekretów wymagają review człowieka.
`review_agent` wspiera analizę, ale nie zastępuje człowieka.

## Most Hypotheses Should Be Rejected Early

Fabryka strategii ma odrzucac wiekszosc slabych pomyslow na wczesnym etapie.
Sukcesem nie jest duza liczba strategii, tylko mala liczba kandydatow, ktore przechodza:

- `backtest`,
- `risk`,
- `dry_run`,
- `review`.
