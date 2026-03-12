# Configuration Policy

## Purpose

Ten dokument opisuje prosty podział konfiguracji i sekretów w projekcie `crypto-system`.
Celem jest bezpieczne przechowywanie danych wrażliwych i czytelne odtwarzanie środowiska na nowym serwerze.

## Local secrets

W `.env` przechowujemy lokalne sekrety infrastruktury, na przykład:
- hasło PostgreSQL
- dane logowania Grafany

W `trading/freqtrade/user_data/config.json` przechowujemy lokalną konfigurację Freqtrade, w tym:
- ustawienia `dry_run`
- konfigurację giełdy
- tokeny i hasła wewnętrzne Freqtrade

Pliki `.env` i `config.json` pozostają tylko lokalnie i nie mogą trafiać do Git.

## Git tracked configuration

Do Git commitujemy wyłącznie bezpieczne pliki konfiguracyjne i dokumentację, które nie zawierają sekretów.
Można commitować między innymi:
- `docker-compose.yml`
- `README.md`
- `PROJECT_RULES.md`
- `ARCHITECTURE.md`
- `CONFIGURATION_POLICY.md`
- pliki `.example`

Nie wolno commitować:
- `.env`
- `config.json`
- API keys
- haseł, tokenów i sekretów

## Example files

Pliki z konfiguracją lokalną powinny mieć wersję `.example`, jeśli mają być łatwo odtwarzane na nowym serwerze.
W tym projekcie dotyczy to przede wszystkim:
- `.env.example`

Pliki `.example` zawierają tylko placeholdery, nigdy prawdziwe sekrety.

## Recovery on new server

Na nowym serwerze:
1. sklonuj repozytorium
2. skopiuj `.env.example` do `.env`
3. uzupełnij lokalne hasła i dane dostępowe
4. wygeneruj lokalny `config.json` dla Freqtrade
5. uruchom usługi przez `docker compose`

Repozytorium odtwarza strukturę i bezpieczne szablony, a wszystkie sekrety uzupełnia się lokalnie.
