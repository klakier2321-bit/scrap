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

## V1.5 reżimów

- `trend_up`
- `trend_down`
- `range`
- `low_vol`
- `high_vol`
- `stress_panic`

Detektor pozostaje regułowy, ale ma już dodatkowe warstwy:

- `htf_bias`
- `market_state`
- `ltf_execution_state`
- `market_phase`
- `volatility_phase`
- `active_event_flags`
- `execution_constraints`

## Dane wejściowe v1.5

- struktura ceny i kierunek
- ATR / rolling volatility
- ADX / trend spread / slope
- volume spike i relatywny wolumen
- funding i mark price, jeśli dostępne
- time/session bucket w formie pochodnej przez strukturę ruchu

Na tym etapie nie ma jeszcze lokalnego feedu:

- open interest
- OI change
- liquidation data

To jest zaplanowane jako kolejna faza.

## Artefakt runtime

Kanoniczny raport reżimu:

- `data/ai_control/regime/latest.json`

Historia:

- `data/ai_control/regime/regime-<timestamp>.json`

## Co raport zwraca

Backward compatible pola podstawowe:

- `primary_regime`
- `confidence`
- `risk_level`
- `trend_strength`
- `volatility_level`
- `volume_state`
- `derivatives_state`

Nowe pola V1.5:

- `htf_bias`
- `market_state`
- `ltf_execution_state`
- `bias`
- `alignment_score`
- `market_phase`
- `volatility_phase`
- `active_event_flags`
- `signals`
- `regime_persistence`
- `position_size_multiplier`
- `entry_aggressiveness`
- `strategy_priority_order`
- `execution_constraints`
- `btc_state`
- `eth_state`
- `market_consensus`
- `consensus_strength`

## Stabilizacja

Detektor nie ma skakać co kilka świec. Dlatego używa:

- smoothing score
- pamięci poprzedniego reżimu
- progów wejścia i wyjścia
- `min_bars_in_regime`
- `switch_cooldown_bars`

To daje stabilniejszy runtime gating i mniej fałszywych przełączeń.

## Zastosowanie

Reżimy są używane do:

- aktywacji strategii
- blokowania strategii
- de-riskingu
- sterowania sizingiem i agresywnością wejścia
- porównywania wyników kandydatów między środowiskami rynku
- wskazywania, które kandydaty byłyby dziś dopuszczone albo zablokowane
