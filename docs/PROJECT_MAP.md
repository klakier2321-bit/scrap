# Spec Core: Project Map

## Po co istnieje ten dokument

`PROJECT_MAP.md` ma byc szybka mapa projektu dla ludzi i agentow.
Ma odpowiedziec na 3 pytania:

- gdzie lezy odpowiedzialnosc za dana warstwe,
- gdzie wolno szukac prawdy o module,
- od czego zaczac czytanie repo bez rozszerzania scope.

## Glowne katalogi

- `core/` - control layer, operatorskie API, raportowanie, risk gating i workflow agentowe
- `trading/` - Freqtrade, strategie, backtesty i `dry_run`
- `research/` - artefakty futures strategy factory: dane, cechy, reżimy, kandydaci, ewaluacja
- `ai_agents/` - role, prompty, ownership, autopilot i zasady pracy agentow
- `monitoring/` - artefakty statusu, skrypty operatorskie i warstwa observability
- `infrastructure/` - Grafana, Prometheus, Tempo i pomocnicza infrastruktura
- `scripts/` - proste skrypty operacyjne
- `data/` - snapshoty `dry_run`, raporty strategii i artefakty read-only

## Najwazniejsze istniejace dokumenty

- `README.md` - szybki start i wejscie operatorskie
- `docs/ARCHITECTURE.md` - kanoniczny opis warstw i granic systemu
- `docs/TRADING_SYSTEM_MASTER_PLAN.md` - biznesowy model tego, jak system ma zarabiac i jak plyna dane
- `docs/FUTURES_TRADING_MODEL.md` - zasady futures-first
- `docs/PROJECT_MAP.md` - mapa ownership i czytania repo
- `docs/DECISIONS.md` - decyzje architektoniczne i bezpieczenstwa
- `docs/AI_AGENT_ROLES.md` - role agentow i ich odpowiedzialnosc

## Dokumenty kanoniczne

Za kanoniczny start od tego momentu uznajemy:

- `docs/ARCHITECTURE.md`
- `docs/PROJECT_MAP.md`
- `docs/DECISIONS.md`
- `docs/TRADING_SYSTEM_MASTER_PLAN.md`
- `docs/FUTURES_TRADING_MODEL.md`
- `docs/AI_AGENT_ROLES.md`
- `docs/openapi.yaml`
- `docs/AI_CHANGE_RULES.md`

Starsze dokumenty w root pozostaja waznym kontekstem pomocniczym, ale nie powinny nadpisywac dokumentow kanonicznych z `docs/`.

## Ownership warstw

- `architecture_agent` - dokumentacja, granice warstw, spojnosc modelu architektonicznego
- `system_lead_agent` - kolejnosc prac, executive roadmap, priorytety platformy
- `control_layer_agent` - `core/`
- `monitoring_agent` - `monitoring/`, `infrastructure/grafana/`, `infrastructure/prometheus/`, wybrane artefakty widocznosci
- `strategy_agent` - lead pionu strategii futures
- helperzy strategii - `research/` i odpowiadajace im docs foundation
- `review_agent` - gate ryzyka i jakosci

## Gdzie wprowadzac zmiany

- `core/` - sterowanie, orchestracja, risk manager, executive reporting, API i control layer
- `trading/` - Freqtrade, strategie, workflow backtestow i runtime tradingowy
- `research/` - datasety, cechy, reżimy, kandydaci i promotion evidence
- `ai_agents/` - role, ownership, prompty, autopilot i zasady delegacji
- `monitoring/` i `infrastructure/` - monitoring, alerty, dashboardy, status platformy
- `docs/` - dokumentacja kanoniczna

## Jak uruchomic obecny projekt

Zgodnie z `README.md`:

```bash
cd /home/debian/crypto-system
docker compose up -d
docker compose ps
docker compose logs -f
```

## Jak agent AI ma czytac repo

1. najpierw czytaj `docs/`
2. potem czytaj dokumenty z root związane z zadaniem
3. dopiero na końcu wchodź w katalog modułu, który masz zmienić
4. nie rozszerzaj scope poza warstwę, której dotyczy zadanie

## Szybki porzadek czytania dla kluczowych tematow

- jesli temat dotyczy architektury:
  - `docs/ARCHITECTURE.md`
  - `docs/PROJECT_MAP.md`
  - `docs/DECISIONS.md`
- jesli temat dotyczy modelu tradingowego:
  - `docs/TRADING_SYSTEM_MASTER_PLAN.md`
  - `docs/FUTURES_TRADING_MODEL.md`
  - `docs/RISK_MODEL_FUTURES.md`
- jesli temat dotyczy agentow:
  - `docs/AI_AGENT_ROLES.md`
  - `ai_agents/config/`
  - `ai_agents/prompts/`
- jesli temat dotyczy runtime:
  - `core/`
  - `trading/`
  - `data/ai_control/dry_run_snapshots/`
