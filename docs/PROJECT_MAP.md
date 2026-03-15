# Spec Core: Project Map

## Główne katalogi

- `core/` - szkielet warstwy sterującej oraz pierwszy offline'owy slice `core/control_layer/`
- `trading/` - Freqtrade, strategie i dane historyczne
- `ai_agents/` - role, workflowy i zasady przyszłych agentów
- `scripts/` - proste skrypty operacyjne
- `monitoring/` - przyszły monitoring systemu
- `infrastructure/` - katalogi pomocnicze usług
- `data/` - miejsce na przyszłe zasoby danych projektu

## Najważniejsze istniejące dokumenty

- `README.md` - szybki start projektu
- `ARCHITECTURE.md` - wcześniejszy opis architektury
- `PROJECT_RULES.md` - zasady projektu
- `CONFIGURATION_POLICY.md` - polityka konfiguracji i sekretów
- `RISK_RULES.md` - startowe zasady ryzyka
- `docs/control_layer/first_increment.md` - opis pierwszego bezpiecznego przyrostu control layer
- dokumenty `AGENT_*.md` - zasady pracy warstwy agentowej

## Dokumenty kanoniczne

Za kanoniczny start od tego momentu uznajemy:

- `docs/ARCHITECTURE.md`
- `docs/PROJECT_MAP.md`
- `docs/DECISIONS.md`
- `docs/openapi.yaml`
- `docs/AI_CHANGE_RULES.md`

Starsze dokumenty w root pozostają ważnym kontekstem pomocniczym i rozwinięciem zasad.

## Gdzie wprowadzać zmiany

- `core` - zmiany sterowania, orchestracji, bot managera, risk managera oraz offline'owych modułów `control_layer`
- `trading runtime` - zmiany Freqtrade, strategii, workflow backtestów, danych
- `ai agents` - zmiany planów agentów, ról, workflowów i zasad AI
- `scripts` - proste operacyjne skrypty projektu

## Jak uruchomić obecny projekt

Zgodnie z `README.md`:

```bash
cd /home/debian/crypto-system
docker compose up -d
docker compose ps
docker compose logs -f
```

## Jak agent AI ma czytać repo

1. najpierw czytaj `docs/`
2. potem czytaj dokumenty z root związane z zadaniem
3. dopiero na końcu wchodź w katalog modułu, który masz zmienić
4. nie rozszerzaj scope poza warstwę, której dotyczy zadanie
