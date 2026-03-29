# Spec Core: Architecture

## Cel systemu

`crypto-system` nie jest jednym botem z pojedyncza strategia. To kontrolowany system futures, w ktorym:

- `regime` opisuje rynek
- `risk` decyduje, co wolno
- `strategy layer` proponuje edge
- `execution` tylko egzekwuje
- `system replay` jest kanonicznym testem calego runtime
- agenci AI wspieraja rozwoj, ale nie steruja krytyczna sciezka execution

Kanoniczny tor futures jest jeden:

- `market data -> regime -> risk -> strategy layer -> execution guard -> dry-run/paper runtime -> telemetry -> system replay`

## Glówne warstwy repo

- `core/` - control plane: regime, risk, strategy layer, executive, replay, operator API
- `trading/` - execution runtime Freqtrade, wrappery futures i lokalne artifacts `user_data`
- `research/` - manifests strategii, dane, eksperymenty i archive-only research assets
- `ai_agents/` - role, prompty, workflow agentow i supervised coding
- `monitoring/` - raporty operatorskie i obserwowalnosc
- `backtests/` - wyniki replay i inne artefakty testowe
- `telemetry/` - telemetry strategii i replay

## Stan kanoniczny

Obecny stan docelowy dla futures jest nastepujacy:

- `canonical strategy layer` jest jedynym source of truth dla futures runtime
- `research/candidates/*` jest archive-only i nie steruje juz execution futures
- 5 kanonicznych botow futures wspoldzieli jeden logiczny portfel `futures_canonical`
- `risk_decision` jest jedynym zrodlem caps i uprawnien runtime
- `execution guard` dziala w modelu `user_data only`
- `system replay` w `core/system_backtest/` jest prawda systemowa dla backtestu calego runtime

## Rola Freqtrade

Freqtrade pozostaje execution engine. Odpowiada za:

- dry-run / paper runtime
- stan runtime i snapshoty
- wykonanie wejsc i wyjsc dopuszczonych przez warstwy wyzej

Freqtrade nie odpowiada za:

- governance systemu
- portfolio risk policy
- leverage policy
- selekcje strategii
- executive control

Wrapper futures ma czytac tylko lokalne artefakty z `trading/freqtrade/user_data/runtime_artifacts/...`.
Nie importuje `core` przez repo root.

## Rola core/

`core/` jest mozgiem systemu futures. Tu spinane sa:

- `RegimeDetector`
- `RiskManager` / `RiskEngine`
- `StrategyLayerService`
- `runtime_artifacts`
- executive report i operator API
- `system replay`

To w `core/` obowiazuje kanoniczny przeplyw:

1. `RegimeDetector` buduje `regime_report`
2. `RiskEngine` buduje `risk_decision`
3. `StrategyLayerService` ocenia strategie i buduje `strategy signals`
4. execution dostaje tylko to, co przeszlo przez risk
5. runtime albo replay wykonuje dopuszczone akcje

## Rola research/

`research/` jest warstwa budowy edge i kontraktow strategii.

Tu znajduja sie:

- manifests kanonicznych strategii
- eksperymenty i dane replay/backtest
- archive-only `candidates`
- roadmapy i evidence dla stewardow

Wazna zasada:

- `research/candidates/*` moze sluzyc do porownan historycznych i archiwum
- nie wolno juz z niego czytac runtime policy dla kanonicznego futures execution

## Rola strategy layer

`strategy layer` wykrywa edge, ale nie zarzadza portfelowym ryzykiem.

Odpowiada za:

- sprawdzenie, czy strategia jest aplikowalna w danym regime
- ocene setupu
- budowe `strategy signal contract`
- invalidation i exit template
- telemetry setup-to-signal

Nie odpowiada za:

- `allow_trading`
- `allowed_directions`
- `allowed_strategy_ids`
- size / exposure / leverage caps
- cooldown i reduce-only

Zasada:

- `strategy proposes, risk permits, execution enforces`

## Rola risk

`risk_decision` jest jedynym kanonicznym kontraktem dopuszczenia runtime.

Musi pozostac zrodlem prawdy dla:

- `allow_trading`
- `new_entries_allowed`
- `allowed_directions`
- `allowed_strategy_ids`
- `max_position_size_pct`
- `max_total_exposure_pct`
- `max_positions_total`
- `max_positions_per_symbol`
- `max_correlated_positions`
- `leverage_cap`
- `force_reduce_only`
- `cooldown_active`
- `protective_overrides`

`risk` nie projektuje edge. `strategy` nie omija risk.

## Rola execution

Execution jest tylko warstwa egzekwujaca.

Odpowiada za:

- admission check
- stake clamp
- leverage clamp
- safe-block przy braku lub starych artefaktach
- wykonanie zlecenia tylko w granicach `risk_decision`

Execution nie interpretuje rynku i nie zmienia polityki risk.

## Runtime artifacts

Kanoniczne artefakty runtime futures:

- `.../<bot_id>/risk/latest.json`
- `.../<bot_id>/signals/latest.json`
- `.../global/portfolio/latest.json`

Jesli artefakt nie istnieje albo jest nieaktualny:

- wrapper przechodzi w `safe-block`
- nie probuje zgadywac stanu runtime

## Globalny futures cluster

5 botow futures to jeden logiczny portfel:

- wspolne `starting_equity`
- wspolne caps portfelowe
- wspolne `max_positions_total`
- wspolne `max_positions_per_symbol`
- wspolne `max_correlated_positions`
- wspolne `max_total_exposure_pct`

Per-bot runtime nie ma prawa luzowac globalnych limitow.

## System replay

`core/system_backtest/` jest kanonicznym backtestem calego systemu.

Replay:

- dziala bar-by-bar
- odpala `regime -> risk -> strategy -> execution`
- pracuje na jednym wspolnym futures portfelu
- zapisuje artefakty do `backtests/system/...`
- nie nadpisuje live `runtime_artifacts`

Dwa tryby replay:

- `fast` - summary, equity, trades, bar log, execution events
- `full-diagnostic` - dodatkowo per-bar `regime_reports`, `risk_decisions`, `strategy_reports`

Freqtrade backtester pozostaje narzedziem pomocniczym do pojedynczych strategii, a nie prawda systemowa.

## Rola agentow

Agenci AI nie sa elementem krytycznej sciezki execution.

Po fazie domkniecia runtime moga wspierac:

- replay review
- telemetry review
- tuning parametrow
- backtesty strategii
- changelog i stewarding strategii

Nie wolno im:

- zmieniac centralnego risk desk bez decyzji architektonicznej
- obchodzic execution guard
- wykonywac write actions na live/paper runtime
- czytac sekretow

Status operatorski agentow jest jawny:

- `agents_disabled`
- `agents_guarded`
- `agents_active_limited`

To jest kontrola operatorska, a nie ukryty stan.

## Co znaczy paper-ready

Na tym etapie `paper-ready` znaczy:

- futures runtime dziala tylko na torze kanonicznym
- risk, strategy i execution maja twarde kontrakty
- `system replay` przechodzi w sensownym czasie bez OOM
- executive futures view nie miesza spot i futures
- agenci moga pozostac wylaczeni bez psucia runtime

Nie znaczy to jeszcze:

- gotowosci do live tradingu
- gotowej, stabilnie zarabiajacej strategii
- pelnej automatyzacji przez agentow
