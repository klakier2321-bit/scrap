# Pierwszy Przyrost Control Layer

## Cel

Ten przyrost uruchamia pierwszy prawdziwy kawałek `control layer` bez dotykania runtime tradingowego.
Powstaje mały, lokalny kontrakt do obsługi offline'owych zadań kontrolnych i walidacyjnych.

## Co już powstało

- `core/control_layer/models.py` - wewnętrzne modele `ControlRequest`, `ControlDecision`, `ControlResult`
- `core/control_layer/registry.py` - local-only registry jawnie zarejestrowanych handlerów
- `core/control_layer/service.py` - cienki serwis wykonujący request przez registry
- `core/control_layer/handlers/dry_control_check.py` - referencyjny, deterministyczny workflow offline
- `core/tests/test_control_layer.py` - testy funkcjonalne i test bezpieczeństwa importów

## Jak działa pierwszy workflow

1. system buduje `ControlRequest`
2. `ControlLayerService` wybiera handler z registry
3. `dry_control_check` waliduje prosty payload
4. wynik wraca jako `ControlResult`
5. nie ma żadnych skutków ubocznych poza zwróceniem ustrukturyzowanej odpowiedzi

## Zakres tego przyrostu

To jest wyłącznie pionowy slice offline.
Ma dać punkt rozszerzeń pod przyszłą orkiestrację w `core/`, ale jeszcze nie steruje tradingiem.

## Jawne non-goals

- brak integracji z `Freqtrade`
- brak połączeń z giełdą
- brak dostępu do `.env`, sekretów i kluczy API
- brak zmian `docker-compose.yml`
- brak zmian lokalnych runtime configów
- brak live tradingu
- brak publicznego API do tego modułu

## Przykład użycia

```python
from core.control_layer import ControlLayerService, ControlRequest

service = ControlLayerService()
request = ControlRequest(
    task_type="dry_control_check",
    payload={
        "subject": "bootstrap-control-layer",
        "checks": ["offline_only", "no_runtime", "no_secrets"],
    },
    source="manual",
)
result = service.execute(request)
print(result.as_dict())
```

## Zasady bezpieczeństwa

Ten moduł nie może stać się skrótem do runtime tradingowego.
Każdy kolejny krok integrujący `control_layer` z istniejącym runtime musi przejść oddzielne review architektoniczne i decyzję właścicielską.
