# Project Rules

## Goal of the system

System ma być platformą do budowy bota tradingowego crypto.

Silnik tradingowy:
Freqtrade

System ma być rozwijany warstwowo i docelowo obsługiwać agentów AI.

AI nie wykonuje bezpośrednio transakcji.

AI może:
- analizować dane
- proponować strategie
- optymalizować strategie
- analizować wyniki

AI nie może:
- zmieniać konfiguracji giełdy
- wykonywać live tradingu bez kontroli systemu

## Security rules

Nigdy nie commitujemy:

.env
config.json
API keys

Sekrety przechowujemy tylko lokalnie.

## Git rules

Każda zmiana musi być:

1 commit = 1 logiczna zmiana

Commit message musi być krótki i opisowy.

## Runtime safety rules

System zawsze zaczyna w trybie:

dry_run = true

Live trading jest możliwy dopiero po:

- testach
- backtestach
- kontroli ryzyka

## AI integration rules

AI agents nie mogą:

- wykonywać transakcji
- zmieniać docker-compose
- zmieniać konfiguracji giełdy

AI może jedynie generować propozycje zmian.
