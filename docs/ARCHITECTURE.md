# Spec Core: Architecture

## Cel systemu

`crypto-system` nie jest projektem "bota z jednym sygnalem", tylko platforma do budowy kontrolowanego systemu tradingowego crypto.

Architektura ma realizowac jeden nadrzedny model:

- `control layer` steruje,
- `Freqtrade` wykonuje,
- `research layer` buduje edge,
- `AI` wspiera rozwoj i raportowanie, ale nie handluje bezposrednio.

To rozdzielenie ma chronic projekt przed chaosem architektonicznym i przed zbyt szybkim przejsciem z eksperymentu do ryzykownego runtime.

## Główne warstwy repo

- `trading/` - execution engine, strategie, backtesty i `dry_run`
- `core/` - control layer, czyli warstwa sterujaca i operatorska
- `research/` - foundation pod futures strategy factory: artefakty danych, cech, ryzyka i kandydatow
- `ai_agents/` - role, prompty, ownership i runtime pracy agentow
- `monitoring/` - raportowanie operacyjne, artefakty statusu i obserwowalnosc
- `scripts/` - proste skrypty operatorskie
- `infrastructure/` - Grafana, Prometheus, Tempo i pomocnicza infrastruktura
- `data/` - snapshoty `dry_run`, raporty strategii i artefakty runtime/read-only

## Co już istnieje

- Docker dla uslug operatorskich i tradingowych
- lokalny runtime Freqtrade w trybie `dry_run`
- read-only bridge do runtime Freqtrade oraz snapshoty `dry_run`
- `core/` jako realna warstwa operatorska: raportowanie, API operatorskie, gating, dry-run smoke i supervised coding flow
- aktywny model agentowy z leadem systemowym, review i izolowanymi worktree
- foundation pionu strategii futures: `strategy_agent` jako lead oraz helperzy od danych, ryzyka, reżimow i ewaluacji
- dokumentacja kanoniczna i roadmapa executive
- branch-first workflow agentow kodujacych: commit najpierw trafia na branch worktree, a nie automatycznie do `main`

## Co jest planowane

- dalsze domykanie control layer jako mozgu systemu
- dalsze porzadkowanie executive reporting i monitoringu operatorskiego
- futures-aware strategy factory oparta na artefaktach, lifecycle i promotion gate
- dalsze rozszerzanie research layer bez naruszania bezpieczenstwa runtime
- dopiero pozniej: dalsza automatyzacja selekcji kandydatow strategii i gotowosc do kolejnych gate'ow

## Najwazniejsze decyzje architektoniczne

Na tym etapie obowiazuja nas ponizsze decyzje:

- `control layer` jest jedynym miejscem, gdzie ma dojrzewac logika sterowania systemem
- `Freqtrade` pozostaje execution engine, zrodlem backtestu i `dry_run`, ale nie staje sie mozgiem platformy
- `research/` sluzy do budowy edge futures, nie do wykonywania zlecen
- `strategy_agent` nie jest juz pojedynczym autorem strategii, tylko leadem pionu futures strategy factory
- helperzy strategii dostarczaja artefakty evidence-first, a nie "luzne pomysly"
- wszystko, co dotyczy runtime, sekretow, krytycznych kontraktow lub live tradingu, pozostaje pod review czlowieka

## Rola Freqtrade

Freqtrade jest execution engine i narzedziem do:

- backtestow,
- `dry_run`,
- pobierania stanu runtime,
- wykonywania tego, co zostalo dopuszczone przez warstwy wyzej.

Freqtrade nie jest glownym mozgiem systemu.
Nie powinno sie do niego przenosic odpowiedzialnosci za:

- governance,
- gating ryzyka,
- executive visibility,
- lifecycle kandydatow strategii,
- polityke pracy agentow.

## Rola core/

`core/` jest warstwa sterujaca i operatorska.
To tutaj maja byc spinane:

- sygnaly strategii,
- gating ryzyka,
- polityki systemowe,
- stan runtime,
- executive reporting,
- operatorskie API,
- bezpieczne workflow agentowe.

Na dzis:

- istnieje offline'owy slice `core/control_layer/`
- dziala read-only bridge do `dry_run`
- dziala smoke test i snapshot pipeline
- dziala supervised coding workflow agentow

To nie jest jeszcze finalny mozg systemu, ale to juz nie jest sam szkielet.

## Rola ai_agents/

`ai_agents/` opisuje i uruchamia kontrolowane srodowisko pracy agentow AI.

Agenci:

- planuja,
- raportuja,
- koduja w waskim ownership,
- rozwijaja dokumentacje, monitoring, API, GUI, control layer i pion strategii futures.

Agenci nie:

- wykonują live tradingu,
- nie omijaja `RiskManager`,
- nie czytaja sekretow,
- nie dostaja bezposredniego dostepu do REST API Freqtrade,
- nie podejmuja high-risk decyzji bez review.

W aktywowanym pionie strategii futures obowiązuje też dodatkowa hierarchia:

- `system_lead_agent` zarządza całym systemem,
- `strategy_agent` działa jako strategy lead,
- helperzy strategii (`alpha_research_agent`, `feature_engineering_agent`, `regime_model_agent`, `risk_research_agent`, `experiment_evaluation_agent`) produkują tylko własne artefakty badawcze,
- tylko `strategy_agent` scala evidence i pilnuje lifecycle kandydatów.

Docelowo obok `core/` i `trading/` istnieje też warstwa `research/`, w której powstają:

- datasety futures-aware,
- feature manifests,
- definicje reżimów,
- candidate manifests,
- eksperymenty,
- promotion evidence.

## Read-only most danych runtime

Docelowy przepływ danych runtime dla agentów jest następujący:

1. `Freqtrade` działa w prawdziwym `dry_run`
2. wewnętrzne API Freqtrade jest dostępne tylko dla control layer
3. `core/` pobiera read-only dane runtime przez dedykowany bridge
4. control layer zapisuje znormalizowany `dry_run snapshot`
5. operator i agenci analityczni czytają snapshoty, nie surowe API

Minimalny kontrakt snapshotu obejmuje:

- status `dry_run` i `runmode`
- aktywną strategię i podstawowe ustawienia runtime
- podsumowanie salda
- liczbę otwartych pozycji i ich skrót
- profit i performance summary
- status świeżości snapshotu
- ostrzeżenia runtime

Bridge ma zwracać czytelne stany błędów:

- `webserver_only`
- `auth_failed`
- `runtime_unavailable`
- `snapshot_stale`
- `dry_run_disabled`

To rozdzielenie jest ważne:

- control layer może czytać runtime Freqtrade
- agenci AI nie mogą czytać sekretów ani configów runtime
- agenci AI nie mogą wykonywać write akcji na trading runtime
- jedynym źródłem danych runtime dla agentów są snapshoty i raporty

## Podstawowy przeplyw sterowania

Docelowy przeplyw jest nastepujacy:

1. dane i artefakty research trafiaja do warstwy strategii
2. strategia lub kandydat strategii generuje hipoteze albo sygnal
3. warstwa ryzyka ocenia, czy kandydat lub sygnal moze przejsc dalej
4. control layer podejmuje decyzje systemowa
5. Freqtrade wykonuje tylko zatwierdzona akcje
6. monitoring, snapshoty i raporty wracaja do ludzi oraz agentow jako feedback

## Podstawowy przeplyw rozwoju edge

Rownolegle do przeplywu wykonawczego istnieje przeplyw budowy edge:

1. `research/` buduje datasety, cechy i artefakty hipotez futures
2. helperzy strategii produkuja evidence dla kandydata
3. `strategy_agent` scala evidence w candidate bundle
4. kandydat przechodzi gate `backtest + risk + dry_run`
5. dopiero wtedy moze stac sie `reviewed_candidate` lub `promoted_candidate`

To oznacza, ze strategia jest rozwijana jak produkt inwestycyjny, a nie jak jednorazowy eksperyment.

## Jak czytac postep implementacji

W tym projekcie nie wolno mieszac trzech roznych znaczen postepu:

- `committed_on_task_branch` - agent dowiozl zmiane na branchu worktree; to jest postep review/coding flow, ale jeszcze nie domkniecie platformy
- `merged_to_main` - zmiana jest juz w glownym repo i dopiero wtedy moze byc liczona jako domkniety przyrost architektury lub platformy
- `runtime_active` - dzialajaca usluga lub pipeline widoczny w biezacym runtime, np. `dry_run`, snapshot bridge, autopilot lub coding supervisor

Na etapie v1 agentowego workflow domyslna interpretacja jest taka:

- `committed` task kodujacy oznacza branch-first progress
- merge do `main` pozostaje poza agentami i wymaga osobnego kroku nadzoru
- executive reporting nie powinien sprzedawac branchowego commita jako rownoznacznego z domknieciem platformy

## Co znaczy, ze architektura jest "domknieta" na ten etap

Na obecnym etapie "domknieta architektura" nie znaczy "wszystko zrobione".
Znaczy:

- granice warstw sa jasne
- ownership agentow jest jasny
- runtime tradingowy jest odseparowany od AI
- `dry_run` jest bezpiecznym zrodlem danych
- pion strategii futures ma leada, helperow i evidence-first model pracy
- executive reporting umie pokazac postep i ryzyka prostym jezykiem

Nie znaczy jeszcze:

- gotowosci do live tradingu
- gotowej, zarabiajacej strategii
- pelnej automatyzacji strategy factory
- zamkniecia wszystkich prac operatorskich
- ze kazdy task `committed` przez agenta jest juz zmergowany do `main`

## Ograniczenie bezpieczenstwa

AI nie wykonuje bezposrednio live trade.
Zmiany dotyczace runtime, sekretow, live tradingu i konfiguracji krytycznej wymagaja kontroli czlowieka.
Read-only most `dry_run` nie zmienia tej zasady: daje wglad w dane runtime, ale nie daje agentom prawa do sterowania execution engine.
