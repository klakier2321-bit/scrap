# Risk Rules

## Goal of risk rules

Celem tych zasad jest ograniczenie ryzyka na etapie budowy i testowania systemu.
Na starcie priorytetem jest bezpieczeństwo, powtarzalność wyników i kontrola drawdownu, a nie agresywny wzrost kapitału.

## Max open trades

- Startowo maksymalnie 3 otwarte pozycje jednocześnie.
- Nie zwiększamy tej wartości, dopóki strategia nie przejdzie stabilnych backtestów i paper tradingu.

## Max capital exposure

- Łączna ekspozycja kapitału nie powinna przekraczać 30% dostępnego kapitału testowego.
- Pojedyncza strategia nie powinna zużywać całego kapitału.
- Na początku zwiększamy ekspozycję tylko bardzo małymi krokami.

## Max risk per trade

- Maksymalne ryzyko na pojedynczy trade: 1% kapitału testowego.
- Jeśli strategia wymaga większego ryzyka, nie przechodzi do kolejnego etapu bez dodatkowej analizy.

## Daily stop conditions

- Wstrzymujemy testy dzienne po 3 kolejnych stratach z rzędu.
- Wstrzymujemy testy, jeśli dzienny drawdown przekroczy 3%.
- Wstrzymujemy testy, jeśli pojawi się nietypowe zachowanie strategii lub błędy wykonania.

## Conditions for enabling live trading

- Live trading nie może być uruchomiony bez wcześniejszych testów.
- Wymagane są co najmniej:
  - poprawny dry_run
  - sensowne backtesty
  - stabilny paper trading
  - przegląd ryzyka i akceptacja człowieka
- Na starcie live trading nie zwiększamy agresji kapitałowej względem paper tradingu.

## Notes for future automation

- Drawdown ma być stale monitorowany i raportowany.
- AI nie decyduje samodzielnie o ryzyku.
- AI może proponować zmiany, ale limity ryzyka zatwierdza system lub operator.
- W przyszłości warto zautomatyzować blokadę strategii po przekroczeniu limitów strat i drawdownu.
