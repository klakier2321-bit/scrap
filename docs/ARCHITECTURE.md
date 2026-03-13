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
- dokumentacja zasad projektu, ryzyka, konfiguracji i agentów
- workflow do pobierania danych i backtestu przez Freqtrade

## Co jest planowane

- implementacja control layer w `core/`
- docelowe Control API
- monitoring wyników i dashboardy
- warstwa AI wspierająca rozwój systemu

## Rola Freqtrade

Freqtrade jest execution engine i narzędziem do backtestów.
Nie jest głównym mózgiem systemu.

## Rola core/

`core/` ma stać się warstwą sterującą, która łączy sygnały strategii, kontrolę ryzyka i decyzje operacyjne.
To ta warstwa ma w przyszłości sterować Freqtrade.

## Rola ai_agents/

`ai_agents/` opisuje przyszłe środowisko agentów AI.
Agenci mają wspierać rozwój architektury, strategii, monitoringu i integracji, ale nie wykonują bezpośrednio live trade.

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
