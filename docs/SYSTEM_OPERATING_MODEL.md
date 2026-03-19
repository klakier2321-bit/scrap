# System Operating Model

## Cel

System działa jako platforma budowy i selekcji strategii futures, a nie jako pojedynczy bot z jedną strategią.

## Model operacyjny

- `system_lead_agent` zarządza całą platformą
- `strategy_agent` zarządza tylko pionem strategii futures
- helperzy strategii produkują małe artefakty badawcze
- `core/` pozostaje warstwą sterującą
- `Freqtrade` pozostaje execution engine

## Zasady

- futures-first
- risk-adjusted profitability ponad raw profit
- większość hipotez ma odpadać wcześnie
- brak AI -> live trading
- review człowieka dla zmian medium/high risk

## Przepływ

`hypothesis -> feature/data foundation -> risk evidence -> experiment evidence -> candidate -> backtest gate -> risk gate -> dry_run gate -> review -> promotion`

