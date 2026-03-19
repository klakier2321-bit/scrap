# Documentation Quality Gate

## Cel

Ten dokument definiuje minimalny, lekki quality gate dla dokumentacji kanonicznej.
Ma zapobiegac sytuacji, w ktorej architektura jest "prawie domknieta", ale dokumenty znowu zaczynaja sie rozjezdzac.

To nie jest ciezki proces.
To jest minimalny standard, ktory pozwala utrzymac jedna wersje prawdy.

## Zestaw dokumentow kanonicznych

Za zestaw kanoniczny uznajemy:

- `docs/ARCHITECTURE.md`
- `docs/PROJECT_MAP.md`
- `docs/DECISIONS.md`
- `docs/TRADING_SYSTEM_MASTER_PLAN.md`
- `docs/FUTURES_TRADING_MODEL.md`
- `docs/AI_AGENT_ROLES.md`
- `docs/openapi.yaml`
- `docs/AI_CHANGE_RULES.md`

## Minimalne reguly jakosci

Kazda zmiana w dokumentach kanonicznych powinna spelniac ponizsze warunki:

1. Nie moze przeczyc innemu dokumentowi kanonicznemu.
2. Musi jasno rozroznic:
   - control layer,
   - execution engine,
   - research layer,
   - role agentow.
3. Nie moze sugerowac, ze AI wykonuje bezposrednio live trading.
4. Nie moze traktowac futures jak spot.
5. Nie moze promowac samego profitu bez ryzyka jako celu systemu.
6. Powinna byc napisana prostym, zarzadczym jezykiem tam, gdzie dokument jest czytany przez prezesa lub operatora.

## Minimalny check przed merge

Przed merge zmiany w dokumentacji kanonicznej sprawdzamy:

1. Czy linki i referencje do plikow nadal istnieja.
2. Czy `ARCHITECTURE.md`, `PROJECT_MAP.md`, `DECISIONS.md` i `TRADING_SYSTEM_MASTER_PLAN.md` mowia tym samym jezykiem o:
   - roli control layer,
   - roli Freqtrade,
   - granicach AI,
   - pionie strategii futures.
3. Czy nie pojawily sie ukryte zmiany kontraktu lub bezpieczenstwa bez aktualizacji `docs/`.
4. Czy zakres zmiany nadal jest maly i nie laczy przypadkowo wielu warstw.

## Kiedy wymagany jest manualny review

Manualny review dokumentacji jest obowiazkowy, gdy zmiana:

- zmienia granice warstw,
- zmienia ownership agentow,
- zmienia model pracy strategii futures,
- dotyka zasad bezpieczenstwa,
- opisuje nowe kontrakty cross-layer,
- moze byc interpretowana jako zgoda na live trading lub obejscie review.

## Czego nie robimy

Nie robimy:

- szerokich sweepow po wszystkich docs bez jasnego celu,
- dekoracyjnych zmian w nazwach bez poprawy tresci,
- ukrywania brakow pod ogolnikami,
- nadpisywania kanonicznych dokumentow starszym kontekstem z root.

## Jak zamykamy etap architektoniczny

Mozna uczciwie powiedziec, ze etap architektoniczny jest domkniety na ten moment, gdy:

- kanoniczne docs sa wzajemnie spojne,
- control layer i Freqtrade maja jasno rozdzielone role,
- runtime tradingowy jest odseparowany od AI,
- pion strategii futures ma opisany ownership i model pracy,
- executive reporting umie pokazac postep i ryzyka prostym jezykiem.
