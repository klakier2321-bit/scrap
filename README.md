# Crypto System

Platforma tradingowa crypto budowana warstwowo:

- `control layer` steruje,
- `Freqtrade` wykonuje,
- `research layer` buduje edge,
- `AI` wspiera rozwój, review i raportowanie, ale nie handluje bezpośrednio.

To nie jest już minimalny szkielet. Repo zawiera działający runtime `dry_run`, control plane agentów, executive reporting oraz foundation pionu strategii futures.

## Co działa dziś

- `Freqtrade` działa w prawdziwym `dry_run`
- `core/` wystawia operatorskie API, executive report, dry-run bridge i snapshoty
- `ai_control` uruchamia autopilot, review i supervised coding workflow
- `Grafana`, `Prometheus`, `Tempo`, `Loki` i panel operatorski działają jako warstwa obserwowalności
- pion strategii futures ma aktywnego leada i helperów foundation

## Jak uruchomić usługi

```bash
cd /home/debian/crypto-system
docker compose up -d
docker compose ps
docker compose logs -f
```

## Canonical Docs

Start od dokumentów kanonicznych w `docs/`:

- `docs/ARCHITECTURE.md`
- `docs/PROJECT_MAP.md`
- `docs/DECISIONS.md`
- `docs/TRADING_SYSTEM_MASTER_PLAN.md`
- `docs/FUTURES_TRADING_MODEL.md`
- `docs/AI_AGENT_ROLES.md`
- `docs/DOCUMENTATION_QUALITY_GATE.md`
- `docs/openapi.yaml`
- `docs/AI_CHANGE_RULES.md`

## Semantyka postępu agentów

W projekcie obowiązuje rozróżnienie:

- `committed on task branch` - agent dowiózł zmianę na własnym branchu worktree; to nie oznacza jeszcze merge do `main`
- `merged to main` - zmiana jest już w głównym repo i może być traktowana jako postęp platformy
- `runtime active` - działająca usługa albo pipeline widoczny w bieżącym runtime (`dry_run`, bridge, autopilot, coding supervisor)

Executive reporting i porządek architektoniczny powinny używać właśnie tego rozróżnienia.

## Local Dev i Testy

Kanoniczny lokalny workflow developerski:

```bash
cd /home/debian/crypto-system
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-ai-control.txt
python3 -m compileall core ai_agents/runtime monitoring trading
python3 -m unittest discover -s core/tests -t . -p 'test_*.py'
```

Ważne:

- testy uruchamiaj z root repo i z `-t .`, inaczej importy `core` i `ai_agents` mogą nie działać poprawnie
- pełna suite wymaga zależności z `requirements-ai-control.txt`
- najlepiej uruchamiać testy przy zatrzymanym `coding supervisor`, żeby background worker nie mieszał logów i timeoutów z wynikiem testów
- jeśli chcesz odtwarzać dokładne środowisko operatorskie, użyj kontenera `ai_control`

## Dostęp operatorski

- Grafana jest dostępna publicznie na porcie `3000`
- panel operatorski AI jest dostępny publicznie na porcie `8000`
- Prometheus jest dostępny publicznie na porcie `9090`

Uwaga bezpieczeństwa:

- panel operatorski AI i Prometheus są obecnie wystawione publicznie bez dodatkowej warstwy autoryzacji
- to jest stan przejściowy, a nie docelowy model bezpieczeństwa
- przed szerszym użyciem należy dodać co najmniej warstwę ograniczenia dostępu lub reverse proxy z autoryzacją
