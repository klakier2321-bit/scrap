# Agent System Plan

## Purpose of the AI agent layer

Warstwa agentów AI ma wspierać rozwój projektu, porządkować pracę między warstwami systemu i przyspieszać iteracje architektury, strategii oraz integracji.
Agenci mają pomagać w rozwoju systemu, ale nie wykonują bezpośrednio transakcji i nie sterują giełdą bez warstwy kontrolnej.

## Core rule

Agenci rozwijają warstwy systemu, a nie zastępują zasad bezpieczeństwa, review i decyzji operatora.

## Planned agents

### architecture_agent

Odpowiada za porządek architektury projektu, strukturę katalogów, zależności między warstwami i spójność dokumentacji technicznej.

### control_layer_agent

Odpowiada za rozwój warstwy `core/`, w tym orchestracji, zarządzania botami, strategiami i ryzykiem.

### strategy_agent

Odpowiada za przygotowanie, analizę i rozwój strategii tradingowych oraz workflow testowego dla Freqtrade.

### api_agent

Odpowiada za przyszłe API systemu i bezpieczne punkty komunikacji między warstwami.

### gui_agent

Odpowiada za przyszły interfejs użytkownika i warstwę prezentacji.

### monitoring_agent

Odpowiada za monitoring, metryki, dashboardy i spójność warstwy obserwowalności.

### integration_agent

Odpowiada za integracje między modułami systemu i pilnowanie zgodności połączeń między warstwami.

### review_agent

Odpowiada za przegląd zmian, kontrolę jakości, wykrywanie ryzyk i pilnowanie zgodności z zasadami projektu.

## Deployment order

Kolejność wdrażania agentów od najbezpieczniejszych do najbardziej wpływających na system:

1. `review_agent`
2. `architecture_agent`
3. `monitoring_agent`
4. `control_layer_agent`
5. `strategy_agent`
6. `integration_agent`
7. `api_agent`
8. `gui_agent`

Najpierw wdrażamy agentów, którzy analizują i porządkują system, a dopiero później tych, którzy wpływają na logikę integracji i warstwy użytkowe.
