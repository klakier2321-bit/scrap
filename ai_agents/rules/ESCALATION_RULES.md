# Escalation Rules

## Escalate to review_agent

Agent przekazuje zmianę do `review_agent`, gdy:
- dotyka więcej niż jednej warstwy
- zmienia kontrakt
- wpływa na architekturę
- może wpływać na zachowanie tradingowe
- nie ma pewności co do scope

## Escalate to human

Agent musi oddać decyzję człowiekowi, gdy zmiana dotyczy:
- sekretów
- `.env`
- `config.json`
- `config.backtest.local.json`
- `docker-compose.yml`
- live tradingu
- exchange API keys
- limitów ryzyka
- przejścia z testów do środowiska realnego

## Escalate on uncertainty

Agent eskaluje również wtedy, gdy:
- wynik backtestu jest niejednoznaczny
- zysk rośnie kosztem wyraźnego wzrostu drawdownu
- zmiana wygląda na opłacalną, ale narusza zasady projektu
- pojawia się konflikt między architekturą a szybkim wdrożeniem
