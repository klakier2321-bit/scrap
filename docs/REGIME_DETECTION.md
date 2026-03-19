# Regime Detection

## Cel

Strategia futures nie ma działać wszędzie tak samo. System musi wiedzieć, w jakim
reżimie działa rynek i czy dany kandydat w ogóle powinien teraz otwierać nowe
pozycje.

## Priorytet

Najpierw budujemy regime detector, dopiero później kolejne strategie.

Aktualny tryb systemu:

- `freeze_build_keep_dry_run`
- kandydaty strategii są zamrożone do czasu gotowego regime engine
- candidate dry-run zostaje jako pasywny telemetry lane

## V1 reżimów

- `trend_up`
- `trend_down`
- `range`
- `low_vol`
- `high_vol`
- `stress_panic`

## Dane wejściowe v1

- struktura ceny i kierunek
- ATR / rolling volatility
- ADX / trend spread / slope
- volume spike i relatywny wolumen
- jeśli dostępne: funding, open interest, OI change, liquidation proxy
- time/session bucket

## Artefakt runtime

Kanoniczny raport reżimu:

- `data/ai_control/regime/latest.json`

Historia:

- `data/ai_control/regime/regime-<timestamp>.json`

## Zastosowanie

Reżimy są używane do:

- aktywacji strategii
- blokowania strategii
- de-riskingu
- porównywania wyników kandydatów między środowiskami rynku
- wskazywania, które kandydaty byłyby dziś dopuszczone albo zablokowane
