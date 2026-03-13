# CrewAI Implementation Plan

Ostatni audyt: `2026-03-13`

## Cel planu

Ten plan opisuje bezpieczne wdrozenie warstwy `CrewAI` do projektu `crypto-system`.
Kolejnosc jest celowo ostrozna:

- najpierw kontrola kosztow i bezpieczenstwo
- potem obserwowalnosc i dashboardy
- potem mala warstwa operacyjna
- dopiero na koncu wlasciwi agenci i automatyzacja

Plan pasuje do obecnego repo:

- `Freqtrade` pozostaje execution engine
- system startuje od `dry_run`
- AI nie wykonuje bezposrednio live trade
- sekrety i runtime configi pozostaja lokalne
- `docker-compose.yml` pozostaje plikiem wrazliwym

## Zasady nadrzedne

- [x] Nie podpinamy agentow bezposrednio pod surowy klucz OpenAI.
- [x] Nie uruchamiamy wielu agentow rownolegle na starcie.
- [x] Nie budujemy najpierw duzego GUI ani duzego multi-agent loop.
- [x] Najpierw wdrazamy koszty, limity, review i monitoring.
- [x] Kazdy agent dziala tylko w swoim `owned scope`.
- [x] `system_lead_agent` ma pelna kontrole planistyczna, ale nie omija granic bezpieczenstwa.
- [x] Wszystkie zmiany wysokiego ryzyka dalej wymagaja czlowieka.

## Definicja gotowosci do startu CrewAI

Przed pierwszym prawdziwym uruchomieniem agentow powinny byc gotowe:

- [x] projektowe `.venv`
- [x] przypieta wersja `CrewAI`
- [x] czytelna konfiguracja modeli i sekretow dla warstwy agentowej
- [x] twardy gate kosztow przed modelem
- [x] monitoring kosztow, tokenow i statusow agentow
- [x] minimalny panel operatorski
- [x] pierwszy prosty workflow `plan -> review -> write`

## Etap 1: Domkniecie warstwy konfiguracji AI

Cel:
- rozdzielic konfiguracje agentow od runtime tradingowego

Do wykonania:
- [x] utworzyc lokalny plik `.env` lub `.env.ai.local` tylko dla warstwy agentowej
- [x] trzymac tam wylacznie sekrety AI i monitoringu agentow
- [x] przygotowac `.env.ai.example` z placeholderami
- [x] rozdzielic sekrety AI od sekretow Freqtrade i infrastruktury
- [x] przypiac modele do rol agentow, zamiast zostawiac dowolny wybor

Wazne pola do przewidzenia:
- [x] `OPENAI_API_KEY` lub docelowy klucz do gatewaya LLM
- [x] `OPENAI_PROJECT_ID` lub osobny projekt dla agentow
- [x] `DEFAULT_MODEL`
- [x] `CHEAP_MODEL`
- [x] `STRONG_MODEL`
- [x] `AGENT_MODE=plan_first`
- [x] `CREWAI_DISABLE_TELEMETRY=true`, jesli chcemy ograniczyc zewnetrzna telemetrie

Definition of done:
- [x] konfiguracja AI jest odseparowana od runtime tradingowego
- [x] zaden sekret AI nie trafia do Git
- [x] wiadomo, ktory model jest tani, a ktory mocny

## Etap 2: Bramka kosztow i dostepu do modeli

Cel:
- odciac agentow od bezposredniego dostepu do modeli

Rekomendowane rozwiazanie:
- [x] wdrozyc gateway LLM, najlepiej `LiteLLM Proxy`

Dlaczego to jest wazne:
- [x] budzety i rate limits nie moga zalezec wylacznie od samego OpenAI
- [x] OpenAI budget traktujemy jako dodatkowy alert, nie jako jedyny bezpiecznik
- [x] kazdy agent powinien miec osobny identyfikator, klucz wirtualny albo logiczny scope kosztowy

Do wykonania:
- [x] zaplanowac osobny kontener lub usluge dla gatewaya LLM
- [x] zdefiniowac allowliste modeli
- [x] zdefiniowac limity per agent
- [x] zdefiniowac limity per dzien
- [x] zdefiniowac limit tokenow na pojedynczy request
- [x] zdefiniowac limit iteracji na task
- [x] zdefiniowac blokade drogich modeli bez zgody

Minimalne limity startowe:
- [x] `system_lead_agent` z malym budzetem dziennym
- [x] `review_agent` tylko tani model
- [x] pozostali agenci uruchamiani pojedynczo
- [x] brak nieograniczonych retry

Definition of done:
- [x] zaden agent nie uzywa bezposrednio prawdziwego klucza modelu
- [x] mozna zobaczyc koszt per agent
- [x] mozna zablokowac request przed jego wykonaniem

## Etap 3: Observability pod agentow

Cel:
- miec pelny podglad pracy agentow, kosztow i bledow

Rekomendowany kierunek:
- [x] `Grafana` jako centralny dashboard
- [x] `Prometheus` dla metryk
- [x] `Loki` dla logow
- [x] `Tempo` lub inny tracing dla przeplywow agentowych

Do wykonania:
- [x] zdefiniowac metryki agentowe
- [x] zdefiniowac format logow z `run_id`, `task_id`, `agent_name`, `model`, `status`
- [x] zdefiniowac zrodla danych do Grafany
- [x] przygotowac podstawowe dashboardy
- [x] przygotowac alerty kosztowe i alerty bezpieczenstwa

Minimalne metryki:
- [x] `agent_runs_total`
- [x] `agent_run_duration_seconds`
- [x] `llm_calls_total`
- [x] `prompt_tokens_total`
- [x] `completion_tokens_total`
- [x] `estimated_cost_usd_total`
- [x] `blocked_calls_total`
- [x] `review_required_total`
- [x] `human_escalations_total`
- [x] `scope_violations_total`

Minimalne dashboardy:
- [x] `Agent Overview` wdrozone jako `Przeglad Agentow`
- [x] `Token & Cost Dashboard` wdrozone jako `Koszty i Tokeny`
- [x] `Safety Dashboard` wdrozone jako `Bezpieczenstwo`
- [x] `Trading + AI Overview` wdrozone jako `Trading i AI`

Minimalne alerty:
- [x] 50% budzetu dziennego
- [x] 80% budzetu dziennego
- [x] 95% budzetu dziennego
- [x] zbyt duzo retry jednego taska
- [x] proba wyjscia poza `owned scope`
- [x] uzycie modelu spoza allowlisty

Definition of done:
- [x] w Grafanie widac kto pracuje, ile trwa i ile kosztuje
- [x] mamy alert zanim agent przepali wiekszy budzet

## Etap 4: Minimalna aplikacja operatorska

Cel:
- miec prosta aplikacje do uruchamiania i kontroli agentow bez marnowania tokenow

Zasada:
- [x] to ma byc panel operatorski, nie rozbudowany chat z calym systemem

Minimalne funkcje GUI:
- [x] lista agentow
- [x] status agentow
- [x] aktualny task
- [x] koszt taska
- [x] uzyty model
- [x] liczba iteracji
- [x] przycisk `start`
- [x] przycisk `stop`
- [x] przycisk `approve expensive run`
- [x] link do logow i trace

Wazne decyzje:
- [x] GUI komunikuje sie z control/API layer, nie bezposrednio z gielda
- [x] GUI nie moze nadawac agentom szerszego scope niz w manifestach
- [x] GUI nie uruchamia live tradingu

Definition of done:
- [x] operator widzi co sie dzieje bez zagladania do terminala
- [x] operator moze zatrzymac drogi lub zly task

## Etap 5: Bazowy runtime CrewAI

Cel:
- uruchomic `CrewAI` w sposob przewidywalny i ograniczony

Preferowany model:
- [x] uzywac `Flow` jako nadrzednego orchestratora
- [x] uruchamiac male `Crew` tylko wtedy, gdy to potrzebne
- [x] nie zaczynac od duzej hierarchii agentow dzialajacej stale

Do wykonania:
- [x] utworzyc maly modul runtime dla agentow
- [x] podpiac `CrewAI` do gatewaya LLM, nie bezposrednio do OpenAI
- [x] wlaczyc `LLM hooks`
- [x] wlaczyc `Execution hooks`
- [x] rejestrowac metryki i logi w kazdym przebiegu
- [x] wprowadzic `run_id` i `task_id` jako standard

Wazne bezpieczniki:
- [x] twardy limit iteracji
- [x] brak samoczynnych petli bez konca
- [x] brak rownoleglych ekip na starcie
- [x] brak pamieci i vector DB, dopoki nie ma realnej potrzeby

Definition of done:
- [x] da sie uruchomic jeden maly workflow agentowy
- [x] kazdy krok jest widoczny w logach i metrykach
- [x] agent nie moze ominac `plan -> review -> write`

## Etap 6: Pierwsi agenci w produkcyjnej kolejnosci

Cel:
- wdrazac agentow od najbezpieczniejszych do najbardziej wplywowych

Status sekcji:
- [x] rollout produkcyjny jest wdrozony w bezpiecznym modelu smoke-testowym dla wszystkich agentow

Kolejnosc:
- [x] `review_agent`
- [x] `system_lead_agent`
- [x] `architecture_agent`
- [x] `monitoring_agent`
- [x] `control_layer_agent`
- [x] `strategy_agent`
- [x] `integration_agent`
- [x] `api_agent`
- [x] `gui_agent`

Dlaczego tak:
- [x] najpierw kontrola jakosci i koordynacja
- [x] potem warstwy organizujace system
- [x] dopiero pozniej strategie i warstwy uzytkowe

Definition of done:
- [x] kazdy agent ma wlasny prompt, task template i review path
- [x] kazdy agent ma przypisany model i limit kosztowy
- [x] kazdy agent ma jasno okreslony scope

## Etap 7: Control API dla agentow i GUI

Cel:
- zbudowac jedno wejscie do kontroli systemu

Zasada:
- [x] agenci i GUI rozmawiaja z systemem przez control layer
- [x] `Freqtrade` nie staje sie glownym mozgiem systemu

Minimalny zakres:
- [x] `GET /health`
- [x] `GET /bots`
- [x] `POST /bots/{bot_id}/start`
- [x] `POST /bots/{bot_id}/stop`
- [x] `GET /bots/{bot_id}/status`
- [x] `GET /bots/{bot_id}/logs`

Do wykonania:
- [x] zachowac zgodnosc z `docs/openapi.yaml`
- [x] najpierw aktualizowac kontrakt, potem implementacje
- [x] logowac kazde wywolanie control API

Definition of done:
- [x] GUI i agenci maja jedno kontrolowane wejscie do systemu
- [x] zadna warstwa AI nie rozmawia bezposrednio z gielda

## Etap 8: Integracja z backtestami i feedback loop

Cel:
- sprawic, by agenci pracowali na danych i wynikach, a nie na domyslach

Do wykonania:
- [x] zdefiniowac standard wejscia dla wynikow backtestu
- [x] zdefiniowac raport strategii jako artefakt
- [x] zdefiniowac minimalne metryki oceny strategii
- [x] zdefiniowac prog odrzucenia strategii
- [x] zdefiniowac prog przejscia do kolejnego etapu

Minimalne metryki strategii:
- [x] profit %
- [x] absolute profit
- [x] drawdown
- [x] liczba trade
- [x] win rate
- [x] stabilnosc wyniku miedzy okresami

Wazne zasady:
- [x] dobry profit nie moze przykrywac zlego drawdownu
- [x] AI nie promuje strategii do `paper` lub `live` bez review
- [x] ryzyko dalej jest wazniejsze niz agresja

Definition of done:
- [x] agent strategii generuje raport oparty na realnych wynikach
- [x] monitoring widzi historie wynikow strategii

## Etap 9: Zasady kosztowe i bezpieczenstwo operacyjne

Cel:
- domknac ochrone przed przepalaniem tokenow i zlym uzyciem agentow

Do wykonania:
- [x] osobny budzet dzienny dla warstwy agentowej
- [x] osobny budzet per agent
- [x] osobny budzet per task
- [x] blokada drozszych modeli bez approval
- [x] limit maksymalnego kontekstu dla taska
- [x] zakaz wrzucania calego repo do promptu
- [x] cache dla stabilnych odpowiedzi, jesli pojawi sie realna potrzeba

Rzeczy, o ktorych latwo zapomniec:
- [x] wersjonowanie promptow agentow
- [x] wersjonowanie kontraktow
- [x] logowanie decyzji `approve / revise / escalate`
- [x] jawny `kill switch` dla calej warstwy agentowej
- [x] fallback, gdy gateway LLM nie dziala
- [x] idempotencja taskow operatorskich
- [x] limit czasu na pojedynczy run

Definition of done:
- [x] mozna zatrzymac cala warstwe agentowa jednym przelacznikiem
- [x] koszt i ryzyko sa ograniczane zanim poleci request do modelu

## Etap 10: Czego nie robic na starcie

- [x] nie budowac od razu pelnej autonomii multi-agent
- [x] nie wdrazac live tradingu przez agentow
- [x] nie dawac agentom dostepu do sekretow
- [x] nie laczyc od razu GUI, API, strategii i monitoringu w jeden duzy sprint
- [x] nie uzywac najmocniejszego modelu do wszystkiego
- [x] nie pozwalac agentom samym decydowac o zwiekszaniu wlasnego budzetu
- [x] nie dokladac pamieci dlugoterminowej bez potrzeby i bez limitow

## Proponowana kolejnosc wdrazania w praktyce

Realna kolejnosc prac dla tego repo:

1. [x] dopracowac lokalna konfiguracje AI i pliki `.example`
2. [x] zaplanowac gateway LLM i limity kosztowe
3. [x] wdrozyc monitoring agentow do Grafany
4. [x] przygotowac minimalna aplikacje operatorska
5. [x] uruchomic bazowy runtime `CrewAI`
6. [x] wdrozyc `review_agent`
7. [x] wdrozyc `system_lead_agent`
8. [x] wdrozyc `architecture_agent`
9. [x] wdrozyc `monitoring_agent`
10. [x] wdrozyc `control_layer_agent`
11. [x] dopiero potem wejsc w `strategy_agent`
12. [x] po stabilizacji rozwijac API i GUI

## Kryterium zakonczenia wdrozenia podstawowego

Mozemy uznac podstawowe wdrozenie `CrewAI` za gotowe dopiero wtedy, gdy:

- [x] agenci dzialaja tylko przez kontrolowane modele i gateway
- [x] koszty sa mierzone i limitowane
- [x] Grafana pokazuje status agentow i koszty
- [x] operator ma prosty panel kontroli
- [x] `system_lead_agent` dziala, ale nie omija zasad bezpieczenstwa
- [x] `review_agent` dziala przed zmianami sredniego i wysokiego ryzyka
- [x] zadna warstwa AI nie ma bezposredniej sciezki do live tradingu
