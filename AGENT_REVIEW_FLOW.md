# Agent Review Flow

## When review is mandatory

Review jest obowiązkowe, gdy zmiana:
- dotyka więcej niż jednej warstwy systemu
- wpływa na bezpieczeństwo
- wpływa na runtime
- zmienia konfigurację Dockera
- może mieć wpływ na trading

## Low-risk changes

Zmiany niskiego ryzyka:
- dokumentacja
- porządki w strukturze katalogów
- szkielety modułów bez logiki runtime
- drobne pliki pomocnicze bez wpływu na bezpieczeństwo

Takie zmiany mogą przejść uproszczony review.

## Medium-risk changes

Zmiany średniego ryzyka:
- zmiany w control layer
- zmiany w workflow testowym
- zmiany w strategiach lub backtestach
- zmiany w monitoringu i integracjach

Takie zmiany powinny przejść normalny review przed commitem lub przed scaleniem.

## High-risk changes

Zmiany wysokiego ryzyka:
- zmiany dotykające runtime
- zmiany dotykające bezpieczeństwa
- zmiany w `docker-compose.yml`
- zmiany dotyczące live tradingu
- zmiany dotyczące sekretów
- zmiany dotyczące exchange API keys

Takie zmiany zawsze wymagają człowieka.

## Human review rule

Zmiany dotykające runtime, bezpieczeństwa, `docker-compose`, tradingu live i sekretów wymagają review człowieka.
`review_agent` może wspierać analizę zmian, ale nie zastępuje człowieka przy zmianach wysokiego ryzyka.
To ograniczenie obowiązuje również `system_lead_agent`.
