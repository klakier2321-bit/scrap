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

## V2.1 kierunek

Po `v1.5` priorytet przeszedł na:

- pełną warstwę `derivatives`
- replay i kalibrację progów
- twarde spięcie z selector + risk layer w control plane

Strategie nadal nie są właścicielem logiki reżimu. Najpierw control layer ma
umieć powiedzieć:

- czy kandydat w ogóle może otwierać nowe wejścia
- jaki ma być `position_size_multiplier`
- jaka ma być agresywność wejścia
- czy rynek jest handlowalny czy tylko poprawnie sklasyfikowany

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

## Dane wejściowe v2.1

- struktura ceny i kierunek
- ATR / rolling volatility
- ADX / trend spread / slope
- volume spike i relatywny wolumen
- funding i mark price, jeśli dostępne
- kanoniczny feed `derivatives`, jeśli jest dostępny
- time/session bucket w formie pochodnej przez strukturę ruchu

Kanoniczny feed derivatives ma osobny artefakt:

- `data/ai_control/derivatives/latest.json`
- `data/ai_control/derivatives/derivatives-<timestamp>.json`

Domyślny vendor v2.1 to publiczny feed **Binance USD-M Futures**:

- `openInterest`
- `openInterestHist`
- `fundingRate`
- `takerlongshortRatio`
- `globalLongShortAccountRatio`

Jeśli Binance nie odpowiada albo zwraca niepełny zestaw danych, system próbuje:

- lokalnego pliku `data/ai_control/derivatives_vendor/latest.json`
- a dopiero na końcu schodzi do `degraded_proxy`

W trybie `degraded_proxy` event flags są tylko ostrzeżeniem, nie twardą
podstawą wejścia.

## Artefakt runtime

Kanoniczny raport reżimu:

- `data/ai_control/regime/latest.json`

Historia:

- `data/ai_control/regime/regime-<timestamp>.json`

Replay i kalibracja:

- `data/ai_control/regime_replay/latest.json`
- `data/ai_control/regime_replay/replay-<timestamp>.json`

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
- `risk_regime`
- `regime_quality`
- `lead_symbol`
- `lag_confirmation`
- `outcome_tracking_status`

`derivatives_state` jest teraz obiektem, a nie prostym stringiem. Ma opisywać:

- status feedu
- dostępność vendora
- świeżość danych:
  - `fetched_at`
  - `source_timestamp`
  - `age_seconds`
  - `is_stale`
- jakość eventów:
  - `event_reliability`
- `positioning_state`
- `squeeze_risk`
- `oi_price_agreement`
- `open_interest_change_pct`
- `oi_acceleration`
- `funding_extreme_flag`
- `liquidation_pressure_proxy`
- `liquidation_source_type`
- `liquidation_event_confidence`

W v2.1 trzeba czytać te pola ostrożnie:

- `binance_futures_public_api` daje sensowną warstwę OI i funding, ale likwidacje dalej są proxy
- `external_vendor` może być średniej jakości snapshotem
- `degraded_proxy` jest tylko miękkim ostrzeżeniem

Dlatego detector rozróżnia:

- `active_event_flags`
- `actionable_event_flags`
- `active_event_flags_reliability`

czyli event może zostać wykryty, ale nie musi być jeszcze na tyle wiarygodny,
żeby control layer użył go jako twardego sygnału ryzyka.

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
- budowania runtime policy w control layer
- porównywania wyników kandydatów między środowiskami rynku
- wskazywania, które kandydaty byłyby dziś dopuszczone albo zablokowane
- replay i kalibracji progów historycznych
