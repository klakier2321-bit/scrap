# Crypto System

Minimalny szkielet projektu pod platformę tradingową crypto opartą w przyszłości o Freqtrade oraz dodatkowe moduły AI.

## Co zawiera projekt

- katalogi pod logikę aplikacji, trading, monitoring i przyszłe agenty AI
- podstawową infrastrukturę Docker dla PostgreSQL, Redis i Grafana
- pliki startowe do dalszej rozbudowy

## Jak uruchomić usługi

```bash
docker compose up -d
docker compose ps
docker compose logs -f
```

## Pierwsze uruchomienie

```bash
cd /home/debian/crypto-system
docker compose up -d
docker compose ps
```

## Canonical Docs

Start od dokumentów kanonicznych w `docs/`:

- `docs/ARCHITECTURE.md`
- `docs/PROJECT_MAP.md`
- `docs/DECISIONS.md`
- `docs/openapi.yaml`
- `docs/AI_CHANGE_RULES.md`

## Dostęp operatorski

- Grafana jest dostępna publicznie na porcie `3000`
- panel operatorski AI jest dostępny publicznie na porcie `8000`
- Prometheus jest dostępny publicznie na porcie `9090`

Uwaga:
panel operatorski AI i Prometheus są obecnie wystawione publicznie bez dodatkowej warstwy autoryzacji.
