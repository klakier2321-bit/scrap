# Regimes

Tutaj trafia kanoniczna definicja reżimów rynku futures oraz raporty, na których
mają później opierać się strategie.

W trybie `regime-first` najpierw budujemy:

- definicję głównych reżimów,
- feature snapshot rynku,
- klasyfikację `latest.json`,
- mapowanie `regime -> eligible / blocked candidates`.

Strategie wracają do aktywnego rozwoju dopiero wtedy, gdy ten kontrakt jest
stabilny i użyteczny dla risk gate oraz operator view.
