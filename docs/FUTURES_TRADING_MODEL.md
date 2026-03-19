# Futures Trading Model

## Założenie

Cały model budujemy pod futures, nie pod spot.

## Każda warstwa musi uwzględniać

- long i short
- leverage
- margin usage
- maintenance margin
- liquidation risk
- maker/taker fees
- funding fees
- slippage
- side concentration
- symbol concentration
- cross-symbol correlation

## Co to zmienia

Strategia nie jest oceniana tylko po wejściu i wyjściu. Jest oceniana też po:

- jakości po kosztach
- jakości po funding
- bezpieczeństwie przy leverage
- odporności na drawdown
- sensowności ekspozycji

