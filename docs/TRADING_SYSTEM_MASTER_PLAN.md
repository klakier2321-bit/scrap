# Plan Systemu Tradingowego

## Cel dokumentu

Ten dokument opisuje docelowy model działania platformy `crypto-system` prostym, ale dokładnym językiem. Ma odpowiadać na pytania:

- po co ten system istnieje,
- jak ma zarabiać,
- jakie ma warstwy,
- jak płyną dane i decyzje,
- jaka jest rola Freqtrade,
- jaka jest rola control layer i agentów AI,
- co już jest zrobione,
- czego jeszcze brakuje do systemu skutecznego biznesowo.

To jest dokument zarządczo-architektoniczny. Ma być jedną wersją prawdy o tym, jak system ma działać i dokąd zmierza.

## Główny cel biznesowy

Celem projektu nie jest zbudowanie „chatbota do tradingu”, tylko zbudowanie skutecznego, kontrolowanego i rozwijanego warstwowo systemu tradingowego dla rynku crypto.

Docelowo system ma:

- generować dodatni wynik skorygowany o ryzyko,
- ograniczać drawdown i nadmierną ekspozycję,
- oddzielać logikę decyzji od silnika wykonawczego,
- uczyć się z danych historycznych, backtestów i wyników `dry_run`,
- rozwijać się iteracyjnie, bez przechodzenia zbyt wcześnie do live tradingu.

Najważniejsza zasada biznesowa jest taka:

**nie interesuje nas sam profit bez kontroli ryzyka.**

System ma zarabiać w sposób:

- powtarzalny,
- zrozumiały,
- weryfikowalny,
- możliwy do zatrzymania i audytu.

Dlatego projekt jest budowany w kolejności:

1. bezpieczna architektura,
2. dane i monitoring,
3. backtest i `dry_run`,
4. ocena jakości strategii i ryzyka,
5. dopiero później dalsza automatyzacja.

## Jak bot ma zarabiać

Docelowo źródłem zarabiania ma być nie pojedynczy „magiczny sygnał”, ale cały układ:

1. strategia znajduje okazje rynkowe,
2. warstwa ryzyka filtruje złe wejścia i zbyt duże ryzyko,
3. control layer pilnuje zasad systemowych,
4. Freqtrade wykonuje tylko te działania, które zostały dopuszczone,
5. monitoring i raporty pozwalają szybko ocenić, czy system rzeczywiście poprawia wynik.

Oznacza to, że przewaga ma pochodzić z połączenia:

- jakości sygnału strategii,
- zarządzania ryzykiem,
- ograniczenia drawdownu,
- kontroli ekspozycji,
- iteracyjnego uczenia się z `backtest` i `dry_run`.

To ważne: w tym systemie zakładamy, że edge może wynikać bardziej z dobrego zarządzania ryzykiem niż z samego pomysłu wejścia w trade. Dlatego strategia nie może być oceniana tylko po:

- win rate,
- liczbie trafień,
- pojedynczym dodatnim wyniku.

Musi przechodzić wspólną bramkę jakości:

- `backtest`,
- `risk`,
- `dry_run`.

## Najważniejsze założenia systemu

### 1. Control layer steruje, Freqtrade wykonuje

To jest podstawowe założenie architektury.

`Freqtrade` nie ma być mózgiem systemu. Jest execution engine i narzędziem do:

- uruchamiania strategii,
- backtestów,
- `dry_run`,
- pozyskiwania danych runtime.

Natomiast logika systemowa ma należeć do `core/`, czyli control layer.

To oznacza, że docelowe decyzje systemowe mają zapadać w warstwie:

- strategii,
- ryzyka,
- orchestracji,
- policy gate,
- review i nadzoru.

### 2. AI nie wykonuje bezpośrednio live tradingu

Agenci AI:

- planują,
- analizują,
- raportują,
- przygotowują zmiany,
- kodują w swoim zakresie,
- wspierają rozwój strategii i monitoringu.

Ale nie mają prawa do:

- bezpośredniej komunikacji z giełdą,
- uruchamiania live trade,
- czytania sekretów,
- obchodzenia warstwy ryzyka,
- obchodzenia review człowieka.

### 3. Wysokie ryzyko wymaga człowieka

Zmiany dotyczące:

- runtime tradingowego,
- sekretów,
- live tradingu,
- krytycznej konfiguracji,
- zmian cross-layer,
- kosztowo istotnych decyzji

nie mogą przechodzić bez kontroli człowieka.

### 4. System ma rozwijać się iteracyjnie

Nie budujemy wszystkiego naraz.

Przyjęty model rozwoju to:

- mały przyrost,
- review,
- test,
- pomiar wyniku,
- kolejny przyrost.

To dotyczy również agentów AI. Każdy większy cel jest rozbijany na małe taski.

## Główne warstwy systemu

## 1. Warstwa tradingowa: `trading/`

To miejsce, gdzie siedzi runtime Freqtrade, strategie i techniczne zasoby tradingowe.

Ta warstwa odpowiada za:

- backtesty,
- `dry_run`,
- wykonanie transakcji przez Freqtrade,
- lokalne artefakty strategii,
- wejście do execution engine.

Na obecnym etapie ta warstwa działa realnie w `dry_run`.

## 2. Control layer: `core/`

To najważniejsza warstwa docelowa.

Ma być centralnym mózgiem systemu, który:

- zbiera sygnały,
- ocenia ryzyko,
- podejmuje decyzję systemową,
- komunikuje się z runtime,
- wystawia stan systemu do operatora i agentów.

Najważniejsze moduły tej warstwy to:

- `orchestrator.py` – główna koordynacja modułów,
- `bot_manager.py` – stan i cykl życia bota,
- `strategy_manager.py` – raporty strategii, assessmenty i gotowość,
- `risk_manager.py` – zasady ryzyka i readiness gate,
- `dry_run_manager.py` – snapshoty i smoke test `dry_run`,
- `freqtrade_runtime.py` – read-only bridge do wewnętrznego API Freqtrade,
- `coding_service.py` – supervised coding workflow agentów,
- `executive_report.py` – raport dla prezesa,
- `api.py` – operatorskie API systemu.

## 3. Warstwa agentów AI: `ai_agents/`

Ta warstwa ma wspierać rozwój i operowanie systemem.

Agenci mają różne role:

- `system_lead_agent` – rozbija cele, pilnuje kolejki prac i raportowania,
- `strategy_agent` – pełni rolę strategy lead dla pionu futures strategy factory,
- `alpha_research_agent` – buduje hipotezy edge,
- `feature_engineering_agent` – buduje foundation danych i cech,
- `regime_model_agent` – klasyfikuje reżimy rynku,
- `risk_research_agent` – rozwija futures-aware risk architecture,
- `experiment_evaluation_agent` – porównuje kandydatów i buduje evidence do promotion gate,
- `monitoring_agent` – rozwija dashboardy, metryki i alerty,
- `control_layer_agent` – rozwija `core/`,
- `architecture_agent` – pilnuje spójności architektury,
- `review_agent` – ocenia zmiany i ryzyko,
- `api_agent` – rozwija operatorskie API,
- `gui_agent` – rozwija panel operatora.

Obecnie agenci nie działają jako swobodni użytkownicy internetu ani jako autonomiczny bot tradingowy. Działają w modelu:

- lead deleguje,
- agent modułowy koduje w swoim zakresie,
- review zatwierdza,
- commit trafia na branch worktree,
- `main` nie jest merge’owany automatycznie.

W pionie strategii działa dodatkowo model dwupoziomowy:

- `system_lead_agent` zarządza całą platformą,
- `strategy_agent` zarządza tylko pionem strategii futures,
- helperzy strategii dostarczają artefakty danych, ryzyka, reżimów i oceny kandydatów,
- tylko `strategy_agent` scala evidence i przenosi kandydata między stanami lifecycle.

## 4. Monitoring i raportowanie

Warstwa obserwowalności obejmuje:

- `Grafana`,
- `Prometheus`,
- `Loki`,
- `Tempo`,
- executive dashboard,
- panel operatorski AI.

Ta warstwa ma odpowiadać nie tylko na pytanie:

- „czy kontener działa?”

ale też:

- czy `dry_run` działa,
- czy strategia jest gotowa,
- co jest teraz budowane,
- co blokuje projekt,
- czego potrzeba od prezesa,
- jaki jest stan agentów i tasków.

## Jak wygląda przepływ danych

Docelowy przepływ danych jest następujący:

1. Rynek i dane giełdowe trafiają do Freqtrade.
2. Freqtrade wykonuje backtest lub `dry_run`.
3. W trybie `dry_run` control layer czyta read-only runtime przez wewnętrzne API Freqtrade.
4. `core/` buduje znormalizowane snapshoty `dry_run`.
5. `strategy_manager` łączy:
   - raport backtestu,
   - assessment strategii,
   - dane `dry_run`,
   - ocenę `RiskManager`.
6. Powstaje wspólny readiness gate:
   - `backtest`,
   - `risk`,
   - `dry_run`.
7. Wynik trafia do:
   - operatora,
   - dashboardu,
   - executive report,
   - agentów analitycznych.
8. Agenci i człowiek na tej podstawie podejmują decyzję o następnym kroku.

## Jak wygląda przepływ decyzji

Docelowy przepływ decyzyjny ma wyglądać tak:

1. Strategia generuje hipotezę lub sygnał.
2. `RiskManager` ocenia:
   - drawdown,
   - ekspozycję,
   - gotowość risk-adjusted,
   - jakość aktualnego wyniku.
3. Control layer zbiera wszystkie sygnały.
4. System ocenia, czy:
   - strategia przechodzi gate,
   - potrzebny jest kolejny eksperyment,
   - należy coś odrzucić,
   - należy zatrzymać promocję dalej.
5. Freqtrade wykonuje tylko to, co zostało dopuszczone.
6. Monitoring i raporty zwracają informację do kolejnej iteracji.

Najważniejsze:

**system ma działać jak pętla uczenia operacyjnego, a nie jak jednorazowy skrypt tradingowy.**

## Jak wygląda przepływ pracy agentów

Obecny model pracy agentów jest następujący:

1. `system_lead_agent` tworzy małe taski.
2. Każdy task ma:
   - ownera,
   - scope,
   - pliki docelowe,
   - definicję ukończenia,
   - testy.
3. Agent modułowy dostaje własny `git worktree`.
4. Agent koduje tylko w swoim zakresie.
5. `review_agent` ocenia diff.
6. Po akceptacji task dostaje commit na branchu worktree.
7. Executive dashboard pokazuje:
   - co jest budowane,
   - co czeka na review,
   - co już dowieziono.

To jest bardzo ważne, bo pozwala rozwijać system bez chaosu i bez wrzucania całego repo do każdego promptu.

## Jak system ma dojść do zarabiania

Docelowa droga do zarabiającego systemu jest taka:

1. zbudować zdrową architekturę,
2. zapewnić monitoring i kontrolę,
3. uruchomić prawdziwy `dry_run`,
4. zbierać dane runtime,
5. budować raporty strategii i risk gate,
6. iteracyjnie poprawiać strategię,
7. sprawdzać, czy poprawa jest realna w:
   - backtest,
   - `dry_run`,
   - risk-adjusted wynikach,
8. dopiero potem myśleć o dalszej promocji.

To oznacza, że system ma zarabiać nie przez szybkie „włączenie live”, tylko przez:

- dyscyplinę,
- pomiar,
- selekcję lepszych wariantów,
- odrzucanie słabych pomysłów.

## Jakie są obecne kryteria jakości strategii

Strategia nie może być uznana za gotową tylko dlatego, że:

- ma wysokie `win_rate`,
- wygląda dobrze w jednym raporcie,
- chwilowo ma dodatnią pozycję.

Obecna wspólna bramka strategii wymaga oceny:

- jakości backtestu,
- ryzyka,
- zachowania w `dry_run`.

Jeśli któryś z tych elementów zawodzi, system ma prawo zablokować dalszą promocję strategii.

To jest celowe. Lepiej zatrzymać złą strategię wcześniej niż przepchnąć ją do kolejnego etapu tylko dlatego, że „coś zarobiła chwilowo”.

## Aktualny stan wdrożenia

Na dziś system ma już działające fundamenty:

- `Freqtrade` działa realnie w `dry_run`,
- control layer ma read-only bridge do runtime,
- snapshoty `dry_run` są generowane,
- smoke test `dry_run` działa,
- executive dashboard działa,
- autopilot agentów działa,
- coding supervisor działa,
- agenci pracują w modelu `lead -> task -> worktree -> review -> commit`,
- strategia jest oceniana przez wspólny gate `backtest + risk + dry_run`.

Obecnie live status systemu jest taki:

- `autopilot` działa stabilnie,
- `dry_run` jest gotowy i daje świeże dane,
- raport strategii jest dostępny,
- system jest zdrowy operacyjnie.

## Co już jest zrobione

### Zrobione fundamenty techniczne

- warstwa `core/` jako miejsce przyszłej orkiestracji,
- pierwszy offline slice `control_layer`,
- operatorskie API,
- panel operatorski,
- dashboardy Grafany,
- Prometheus, Loki i Tempo,
- monitoring kosztów, tasków i agentów,
- `dry_run` runtime bridge,
- snapshoty runtime,
- smoke test `dry_run`,
- supervised coding workflow agentów,
- worktree per task,
- review przed commitem,
- executive dashboard dla prezesa.

### Zrobione fundamenty decyzyjne

- oddzielenie `control layer` od `Freqtrade`,
- zakaz bezpośredniego live tradingu przez AI,
- read-only model dostępu agentów do runtime,
- readiness gate strategii,
- kontrola kosztów i scope agentów,
- kontrola ryzykownych zmian przez człowieka.

## Co jeszcze nie jest gotowe

Najważniejsza uczciwa prawda jest taka:

**system działa, ale jeszcze nie jest skutecznym systemem zarabiającym.**

Na dziś największy niedomknięty element to nie infrastruktura, tylko jakość samej strategii.

Aktualny stan strategii jest słaby:

- backtest jest ujemny,
- drawdown jest za wysoki,
- stabilność jest zbyt niska,
- `dry_run` nadal pokazuje ujemny wynik,
- readiness gate blokuje promocję strategii dalej.

To znaczy:

- architektura działa,
- proces działa,
- monitoring działa,
- agenci pracują,
- ale edge strategii nadal nie został jeszcze dowieziony.

## Najważniejsze ryzyka projektu

### 1. Strategia bez przewagi

Największe ryzyko biznesowe jest takie, że obecny wariant strategii po prostu nie ma jeszcze wystarczającej jakości.

### 2. Zbyt szybkie przejście do dalszej automatyzacji

Jeśli system zacznie zwiększać automatyzację przed uzyskaniem dobrej jakości `backtest + risk + dry_run`, to może tylko szybciej skalować zły proces.

### 3. Mylenie postępu technicznego z postępem biznesowym

To, że:

- dashboard działa,
- agenci kodują,
- `dry_run` działa,

nie oznacza jeszcze, że system umie zarabiać.

### 4. Zbyt słaby nacisk na risk-adjusted wynik

Jeśli zespół będzie patrzył za mocno na sam profit lub win rate, może pominąć to, że drawdown i ekspozycja niszczą wartość strategii.

## Docelowy model operacyjny

W dojrzałej wersji system ma działać tak:

1. człowiek lub lead określa kierunek rozwoju,
2. agenci modułowi rozwijają swoje obszary w małych taskach,
3. control layer zbiera dane i pilnuje zasad,
4. strategia jest stale oceniana przez wspólny gate jakości,
5. tylko lepsze warianty przechodzą dalej,
6. monitoring i dashboardy raportują stan prostym językiem,
7. człowiek zachowuje kontrolę nad obszarami wysokiego ryzyka.

## Podsumowanie strategiczne

`crypto-system` nie jest zwykłym botem tradingowym. To platforma budowana warstwowo po to, żeby:

- oddzielić myślenie systemowe od execution engine,
- rozwijać strategię i ryzyko w sposób kontrolowany,
- używać AI jako siły rozwojowej, ale nie jako niekontrolowanego tradera,
- dojść do skutecznego, risk-adjusted systemu tradingowego.

Na dziś największy sukces projektu to:

- działająca architektura rozwoju,
- działający `dry_run`,
- działający control plane,
- działający model pracy agentów,
- gotowy fundament pod dalsze iteracje strategii.

Na dziś największe wyzwanie projektu to:

- zamienić sprawnie działającą maszynę operacyjną w system, który faktycznie ma przewagę tradingową.

To jest teraz główne pole walki projektu.
