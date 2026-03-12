# Bot Decision Flow

## Overview

Docelowo bot nie podejmuje decyzji w jednym miejscu.
Decyzja przechodzi przez kilka warstw, z których każda ma własną odpowiedzialność.

## Decision layers

### data layer

Ta warstwa zbiera i przygotowuje dane wejściowe do analizy.

### strategy layer

Ta warstwa generuje sygnały strategii na podstawie danych.

### risk layer

Ta warstwa sprawdza limity ryzyka, ekspozycję i warunki bezpieczeństwa.
`risk_manager` ma prawo zablokować wykonanie.

### control layer

Ta warstwa podejmuje systemową decyzję, czy sygnał może przejść dalej.
To tutaj system łączy sygnał strategii z kontrolą ryzyka i zasadami operacyjnymi.

### execution layer

Ta warstwa wykonuje zatwierdzone akcje.
Freqtrade jest execution engine, a nie głównym mózgiem systemu.

### monitoring / feedback layer

Ta warstwa zbiera wyniki, błędy, metryki i zachowanie systemu.
Feedback wraca do dalszego rozwoju strategii, warstwy kontrolnej i dokumentacji.

## AI position in the flow

AI nie wykonuje bezpośrednio trade.
AI może analizować dane, strategie i wyniki, ale decyzja systemowa przechodzi przez control layer, a wykonanie przez execution layer.
