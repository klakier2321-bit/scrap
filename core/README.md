# Core Control Layer

Ta warstwa istnieje po to, aby oddzielić sterowanie systemem od silnika tradingowego.
W przyszłości ma być głównym miejscem koordynacji pracy bota i zasad bezpieczeństwa.

## Moduły

- `orchestrator.py` - główny punkt koordynacji modułów
- `bot_manager.py` - zarządzanie cyklem życia botów
- `strategy_manager.py` - obsługa strategii
- `risk_manager.py` - kontrola zasad ryzyka

## Rola w systemie

Ta warstwa ma w przyszłości sterować Freqtrade, zamiast mieszać logikę sterującą z konfiguracją infrastruktury.
AI będzie komunikować się z systemem przez tę warstwę, a nie bezpośrednio z giełdą.
