# CrewAI Implementation Plan

## Cel planu

Ten plan opisuje bezpieczne wdrożenie warstwy `CrewAI` do projektu `crypto-system`.
Kolejność jest celowo ostrożna:

- najpierw kontrola kosztów i bezpieczeństwo
- potem obserwowalność i dashboardy
- potem mała warstwa operacyjna
- dopiero na końcu właściwi agenci i automatyzacja

Plan ma pasować do obecnego repo:

- `Freqtrade` pozostaje execution engine
- system startuje od `dry_run`
- AI nie wykonuje bezpośrednio live trade
- sekrety i runtime configi pozostają lokalne
- `docker-compose.yml` pozostaje plikiem wrażliwym

## Zasady nadrzędne

- [ ] Nie podpinamy agentów bezpośrednio pod surowy klucz OpenAI.
- [ ] Nie uruchamiamy wielu agentów równolegle na starcie.
- [ ] Nie budujemy najpierw dużego GUI ani dużego multi-agent loop.
- [ ] Najpierw wdrażamy koszty, limity, review i monitoring.
- [ ] Każdy agent działa tylko w swoim `owned scope`.
- [ ] `system_lead_agent` ma pełną kontrolę planistyczną, ale nie omija granic bezpieczeństwa.
- [ ] Wszystkie zmiany wysokiego ryzyka dalej wymagają człowieka.

## Definicja gotowości do startu CrewAI

Przed pierwszym prawdziwym uruchomieniem agentów powinny być gotowe:

- [ ] projektowe `.venv`
- [ ] przypięta wersja `CrewAI`
- [ ] czytelna konfiguracja modeli i sekretów dla warstwy agentowej
- [ ] twardy gate kosztów przed modelem
- [ ] monitoring kosztów, tokenów i statusów agentów
- [ ] minimalny panel operatorski
- [ ] pierwszy prosty workflow `plan -> review -> write`

## Etap 1: Domknięcie warstwy konfiguracji AI

Cel:
- rozdzielić konfigurację agentów od runtime tradingowego

Do wykonania:
- [ ] utworzyć lokalny plik `.env` lub `.env.ai.local` tylko dla warstwy agentowej
- [ ] trzymać tam wyłącznie sekrety AI i monitoringu agentów
- [ ] przygotować `.env.ai.example` z placeholderami
- [ ] rozdzielić sekrety AI od sekretów Freqtrade i infrastruktury
- [ ] przypiąć modele do ról agentów, zamiast zostawiać dowolny wybór

Ważne pola do przewidzenia:
- [ ] `OPENAI_API_KEY` lub docelowy klucz do gatewaya LLM
- [ ] `OPENAI_PROJECT_ID` lub osobny projekt dla agentów
- [ ] `DEFAULT_MODEL`
- [ ] `CHEAP_MODEL`
- [ ] `STRONG_MODEL`
- [ ] `AGENT_MODE=plan_first`
- [ ] `CREWAI_DISABLE_TELEMETRY=true`, jeśli chcemy ograniczyć zewnętrzną telemetrię

Definition of done:
- [ ] konfiguracja AI jest odseparowana od runtime tradingowego
- [ ] żaden sekret AI nie trafia do Git
- [ ] wiadomo, który model jest tani, a który mocny

## Etap 2: Bramka kosztów i dostępu do modeli

Cel:
- odciąć agentów od bezpośredniego dostępu do modeli

Rekomendowane rozwiązanie:
- [ ] wdrożyć gateway LLM, najlepiej `LiteLLM Proxy`

Dlaczego to jest ważne:
- [ ] budżety i rate limits nie mogą zależeć wyłącznie od samego OpenAI
- [ ] OpenAI budget traktujemy jako dodatkowy alert, nie jako jedyny bezpiecznik
- [ ] każdy agent powinien mieć osobny identyfikator, klucz wirtualny albo logiczny scope kosztowy

Do wykonania:
- [ ] zaplanować osobny kontener lub usługę dla gatewaya LLM
- [ ] zdefiniować allowlistę modeli
- [ ] zdefiniować limity per agent
- [ ] zdefiniować limity per dzień
- [ ] zdefiniować limit tokenów na pojedynczy request
- [ ] zdefiniować limit iteracji na task
- [ ] zdefiniować blokadę drogich modeli bez zgody

Minimalne limity startowe:
- [ ] `system_lead_agent` z małym budżetem dziennym
- [ ] `review_agent` tylko tani model
- [ ] pozostali agenci uruchamiani pojedynczo
- [ ] brak nieograniczonych retry

Definition of done:
- [ ] żaden agent nie używa bezpośrednio prawdziwego klucza modelu
- [ ] można zobaczyć koszt per agent
- [ ] można zablokować request przed jego wykonaniem

## Etap 3: Observability pod agentów

Cel:
- mieć pełny podgląd pracy agentów, kosztów i błędów

Rekomendowany kierunek:
- [ ] `Grafana` jako centralny dashboard
- [ ] `Prometheus` dla metryk
- [ ] `Loki` dla logów
- [ ] opcjonalnie `Tempo` lub inny tracing dla przepływów agentowych

Do wykonania:
- [ ] zdefiniować metryki agentowe
- [ ] zdefiniować format logów z `run_id`, `task_id`, `agent_name`, `model`, `status`
- [ ] zdefiniować źródła danych do Grafany
- [ ] przygotować podstawowe dashboardy
- [ ] przygotować alerty kosztowe i alerty bezpieczeństwa

Minimalne metryki:
- [ ] `agent_runs_total`
- [ ] `agent_run_duration_seconds`
- [ ] `llm_calls_total`
- [ ] `prompt_tokens_total`
- [ ] `completion_tokens_total`
- [ ] `estimated_cost_usd_total`
- [ ] `blocked_calls_total`
- [ ] `review_required_total`
- [ ] `human_escalations_total`
- [ ] `scope_violations_total`

Minimalne dashboardy:
- [ ] `Agent Overview`
- [ ] `Token & Cost Dashboard`
- [ ] `Safety Dashboard`
- [ ] `Trading + AI Overview`

Minimalne alerty:
- [ ] 50% budżetu dziennego
- [ ] 80% budżetu dziennego
- [ ] 95% budżetu dziennego
- [ ] zbyt dużo retry jednego taska
- [ ] próba wyjścia poza `owned scope`
- [ ] użycie modelu spoza allowlisty

Definition of done:
- [ ] w Grafanie widać kto pracuje, ile trwa i ile kosztuje
- [ ] mamy alert zanim agent przepali większy budżet

## Etap 4: Minimalna aplikacja operatorska

Cel:
- mieć prostą aplikację do uruchamiania i kontroli agentów bez marnowania tokenów

Zasada:
- [ ] to ma być panel operatorski, nie rozbudowany chat z całym systemem

Minimalne funkcje GUI:
- [ ] lista agentów
- [ ] status agentów
- [ ] aktualny task
- [ ] koszt taska
- [ ] użyty model
- [ ] liczba iteracji
- [ ] przycisk `start`
- [ ] przycisk `stop`
- [ ] przycisk `approve expensive run`
- [ ] link do logów i trace

Ważne decyzje:
- [ ] GUI komunikuje się z control/API layer, nie bezpośrednio z giełdą
- [ ] GUI nie może nadawać agentom szerszego scope niż w manifestach
- [ ] GUI nie uruchamia live tradingu

Definition of done:
- [ ] operator widzi co się dzieje bez zaglądania do terminala
- [ ] operator może zatrzymać drogi lub zły task

## Etap 5: Bazowy runtime CrewAI

Cel:
- uruchomić `CrewAI` w sposób przewidywalny i ograniczony

Preferowany model:
- [ ] używać `Flow` jako nadrzędnego orchestratora
- [ ] uruchamiać małe `Crew` tylko wtedy, gdy to potrzebne
- [ ] nie zaczynać od dużej hierarchii agentów działającej stale

Do wykonania:
- [ ] utworzyć mały moduł runtime dla agentów
- [ ] podpiąć `CrewAI` do gatewaya LLM, nie bezpośrednio do OpenAI
- [ ] włączyć `LLM hooks`
- [ ] włączyć `Execution hooks`
- [ ] rejestrować metryki i logi w każdym przebiegu
- [ ] wprowadzić `run_id` i `task_id` jako standard

Ważne bezpieczniki:
- [ ] twardy limit iteracji
- [ ] brak samoczynnych pętli bez końca
- [ ] brak równoległych ekip na starcie
- [ ] brak pamięci i vector DB, dopóki nie ma realnej potrzeby

Definition of done:
- [ ] da się uruchomić jeden mały workflow agentowy
- [ ] każdy krok jest widoczny w logach i metrykach
- [ ] agent nie może ominąć `plan -> review -> write`

## Etap 6: Pierwsi agenci w produkcyjnej kolejności

Cel:
- wdrażać agentów od najbezpieczniejszych do najbardziej wpływowych

Kolejność:
- [ ] `review_agent`
- [ ] `system_lead_agent`
- [ ] `architecture_agent`
- [ ] `monitoring_agent`
- [ ] `control_layer_agent`
- [ ] `strategy_agent`
- [ ] `integration_agent`
- [ ] `api_agent`
- [ ] `gui_agent`

Dlaczego tak:
- [ ] najpierw kontrola jakości i koordynacja
- [ ] potem warstwy organizujące system
- [ ] dopiero później strategie i warstwy użytkowe

Definition of done:
- [ ] każdy agent ma własny prompt, task template i review path
- [ ] każdy agent ma przypisany model i limit kosztowy
- [ ] każdy agent ma jasno określony scope

## Etap 7: Control API dla agentów i GUI

Cel:
- zbudować jedno wejście do kontroli systemu

Zasada:
- [ ] agenci i GUI rozmawiają z systemem przez control layer
- [ ] `Freqtrade` nie staje się głównym mózgiem systemu

Minimalny zakres:
- [ ] `GET /health`
- [ ] `GET /bots`
- [ ] `POST /bots/{bot_id}/start`
- [ ] `POST /bots/{bot_id}/stop`
- [ ] `GET /bots/{bot_id}/status`
- [ ] `GET /bots/{bot_id}/logs`

Do wykonania:
- [ ] zachować zgodność z `docs/openapi.yaml`
- [ ] najpierw aktualizować kontrakt, potem implementację
- [ ] logować każde wywołanie control API

Definition of done:
- [ ] GUI i agenci mają jedno kontrolowane wejście do systemu
- [ ] żadna warstwa AI nie rozmawia bezpośrednio z giełdą

## Etap 8: Integracja z backtestami i feedback loop

Cel:
- sprawić, by agenci pracowali na danych i wynikach, a nie na domysłach

Do wykonania:
- [ ] zdefiniować standard wejścia dla wyników backtestu
- [ ] zdefiniować raport strategii jako artefakt
- [ ] zdefiniować minimalne metryki oceny strategii
- [ ] zdefiniować próg odrzucenia strategii
- [ ] zdefiniować próg przejścia do kolejnego etapu

Minimalne metryki strategii:
- [ ] profit %
- [ ] absolute profit
- [ ] drawdown
- [ ] liczba trade
- [ ] win rate
- [ ] stabilność wyniku między okresami

Ważne zasady:
- [ ] dobry profit nie może przykrywać złego drawdownu
- [ ] AI nie promuje strategii do `paper` lub `live` bez review
- [ ] ryzyko dalej jest ważniejsze niż agresja

Definition of done:
- [ ] agent strategii generuje raport oparty na realnych wynikach
- [ ] monitoring widzi historię wyników strategii

## Etap 9: Zasady kosztowe i bezpieczeństwo operacyjne

Cel:
- domknąć ochronę przed przepalaniem tokenów i złym użyciem agentów

Do wykonania:
- [ ] osobny budżet dzienny dla warstwy agentowej
- [ ] osobny budżet per agent
- [ ] osobny budżet per task
- [ ] blokada droższych modeli bez approval
- [ ] limit maksymalnego kontekstu dla taska
- [ ] zakaz wrzucania całego repo do promptu
- [ ] cache dla stabilnych odpowiedzi, jeśli pojawi się realna potrzeba

Rzeczy, o których łatwo zapomnieć:
- [ ] wersjonowanie promptów agentów
- [ ] wersjonowanie kontraktów
- [ ] logowanie decyzji `approve / revise / escalate`
- [ ] jawny `kill switch` dla całej warstwy agentowej
- [ ] fallback, gdy gateway LLM nie działa
- [ ] idempotencja tasków operatorskich
- [ ] limit czasu na pojedynczy run

Definition of done:
- [ ] można zatrzymać całą warstwę agentową jednym przełącznikiem
- [ ] koszt i ryzyko są ograniczane zanim poleci request do modelu

## Etap 10: Czego nie robić na starcie

- [ ] nie budować od razu pełnej autonomii multi-agent
- [ ] nie wdrażać live tradingu przez agentów
- [ ] nie dawać agentom dostępu do sekretów
- [ ] nie łączyć od razu GUI, API, strategii i monitoringu w jeden duży sprint
- [ ] nie używać najmocniejszego modelu do wszystkiego
- [ ] nie pozwalać agentom samym decydować o zwiększaniu własnego budżetu
- [ ] nie dokładać pamięci długoterminowej bez potrzeby i bez limitów

## Proponowana kolejność wdrażania w praktyce

Realna kolejność prac dla tego repo:

1. [ ] dopracować lokalną konfigurację AI i pliki `.example`
2. [ ] zaplanować gateway LLM i limity kosztowe
3. [ ] wdrożyć monitoring agentów do Grafany
4. [ ] przygotować minimalną aplikację operatorską
5. [ ] uruchomić bazowy runtime `CrewAI`
6. [ ] wdrożyć `review_agent`
7. [ ] wdrożyć `system_lead_agent`
8. [ ] wdrożyć `architecture_agent`
9. [ ] wdrożyć `monitoring_agent`
10. [ ] wdrożyć `control_layer_agent`
11. [ ] dopiero potem wejść w `strategy_agent`
12. [ ] po stabilizacji rozwijać API i GUI

## Kryterium zakończenia wdrożenia podstawowego

Możemy uznać podstawowe wdrożenie `CrewAI` za gotowe dopiero wtedy, gdy:

- [ ] agenci działają tylko przez kontrolowane modele i gateway
- [ ] koszty są mierzone i limitowane
- [ ] Grafana pokazuje status agentów i koszty
- [ ] operator ma prosty panel kontroli
- [ ] `system_lead_agent` działa, ale nie omija zasad bezpieczeństwa
- [ ] `review_agent` działa przed zmianami średniego i wysokiego ryzyka
- [ ] żadna warstwa AI nie ma bezpośredniej ścieżki do live tradingu
