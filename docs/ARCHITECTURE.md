# Spec Core: Architecture

## Cel systemu

`crypto-system` jest szkieletem platformy do budowy bota tradingowego crypto.
Silnikiem wykonawczym jest Freqtrade, a system ma być rozwijany warstwowo, z późniejszym wsparciem agentów AI.

## Główne warstwy repo

- `trading/` - runtime tradingowy i zasoby Freqtrade
- `core/` - planowana warstwa sterująca systemem
- `ai_agents/` - fundament pod przyszłe workflow agentów AI
- `monitoring/` - miejsce pod obserwowalność i dashboardy
- `scripts/` - proste operacyjne skrypty projektu
- `infrastructure/` - katalogi pomocnicze dla usług Dockera

## Co już istnieje

- Docker dla `postgres`, `redis`, `grafana`, `freqtrade`
- lokalny runtime Freqtrade w trybie `dry_run`
- szkielet `core/` bez logiki biznesowej
- pierwszy, offline'owy slice `core/control_layer/` z lokalnym registry i workflow `dry_control_check`
- dokumentacja zasad projektu, ryzyka, konfiguracji i agentów
- workflow do pobierania danych i backtestu przez Freqtrade

## Co jest planowane

- implementacja control layer w `core/`
- kolejne, świadome rozszerzanie `core/control_layer/` dopiero po osobnych review
- docelowe Control API
- monitoring wyników i dashboardy
- warstwa AI wspierająca rozwój systemu

## Rola Freqtrade

Freqtrade jest execution engine i narzędziem do backtestów.
Nie jest głównym mózgiem systemu.
W aktualnym etapie działa też jako źródło read-only danych runtime w trybie `dry_run`.

## Rola core/

`core/` ma stać się warstwą sterującą, która łączy sygnały strategii, kontrolę ryzyka i decyzje operacyjne.
To ta warstwa ma w przyszłości sterować Freqtrade.
Pierwszy istniejący przyrost w `core/control_layer/` pozostaje jednak całkowicie offline i nie komunikuje się jeszcze z runtime tradingowym.
Nowy most `dry_run` w `core/` ma charakter wyłącznie odczytowy: control layer pobiera dane z wewnętrznego API Freqtrade i buduje znormalizowane snapshoty dla operatora oraz agentów analitycznych.

## Rola ai_agents/

`ai_agents/` opisuje przyszłe środowisko agentów AI.
Agenci mają wspierać rozwój architektury, strategii, monitoringu i integracji, ale nie wykonują bezpośrednio live trade.
Agenci nie dostają bezpośredniego dostępu do REST API Freqtrade. Pracują wyłącznie na snapshotach i raportach przygotowanych przez control layer.

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

## Podstawowy przepływ sterowania

Docelowy przepływ jest następujący:

1. dane wejściowe trafiają do warstwy strategii
2. strategia generuje sygnał
3. warstwa ryzyka ocenia, czy sygnał może przejść dalej
4. control layer podejmuje decyzję systemową
5. Freqtrade wykonuje zatwierdzoną akcję
6. monitoring zwraca feedback do dalszego rozwoju systemu

## Ograniczenie bezpieczeństwa

AI nie wykonuje bezpośrednio live trade.
Zmiany dotyczące runtime, sekretów, live tradingu i konfiguracji krytycznej wymagają kontroli człowieka.
Read-only most `dry_run` nie zmienia tej zasady: daje wgląd w dane runtime, ale nie daje agentom prawa do sterowania execution engine.
