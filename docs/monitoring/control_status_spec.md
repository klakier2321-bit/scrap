# Control Status Spec

## Cel

`control_status` daje bezpieczny, zwięzły obraz gotowości platformy bez ujawniania surowych payloadów runtime.

## Dozwolone wejścia

Moduł czyta wyłącznie JSON z:

- `data/ai_control/dry_run_snapshots/`
- `data/ai_control/strategy_reports/`
- `data/ai_control/dry_run_smoke/`

Każdy odczyt jest ograniczony do plików znajdujących się realnie wewnątrz tych katalogów.

## Dozwolone wyjścia

Moduł zapisuje wyłącznie do:

- `monitoring/reports/control_status_SUMMARY.md`
- `monitoring/reports/control_status.json`

## Sanitizacja

Sanitizowane są:

- ścieżki systemowe,
- URL-e,
- adresy e-mail,
- długie tokeny heksadecymalne,
- pola o nazwach sugerujących sekrety lub dane wrażliwe.

Podsumowanie tekstowe i lista uwag są zawsze oczyszczane przed zapisem.

## Minimalny kontrakt

### Dry run snapshots

Wymagane pola:

- `generated_at`
- `dry_run`
- `snapshot_status`
- `runmode`

### Strategy reports

Wymagane pola:

- `generated_at`
- `strategy_name`
- `evaluation_status`

### Dry run smoke

Wymagane pola:

- `checked_at`
- `status`

## Znane ograniczenia

- Moduł przetwarza tylko pliki JSON.
- To jest defensywny raport operatorski, a nie pełny silnik walidacji schematów.
