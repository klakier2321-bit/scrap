# System Architecture

## Infrastructure Layer

Docker

Services:

- Postgres
- Redis
- Grafana
- Freqtrade

## Trading Engine

Silnik tradingowy:

Freqtrade

Tryb:

dry_run

Strategie znajdują się w:

trading/freqtrade/user_data/strategies

## Control Layer (planned)

Docelowo powstanie warstwa sterująca:

core/

Planowane moduły:

orchestrator.py
bot_manager.py
strategy_manager.py
risk_manager.py

Ta warstwa będzie sterować Freqtrade.

## AI Layer (future)

Planowane użycie:

CrewAI / LangGraph

Agenci AI będą odpowiedzialni za:

- research strategii
- analizę danych
- optymalizację strategii

AI nie będzie wykonywać trade bezpośrednio.

## Monitoring

Grafana

Docelowo dashboard ma pokazywać:

- profit
- drawdown
- trade history
- status botów
