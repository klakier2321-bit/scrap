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
