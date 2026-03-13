# System Lead Workflow

## Step 1: Read context

`system_lead_agent` zaczyna od dokumentów kanonicznych i celu biznesowego.

## Step 2: Define objective

Agent zamienia cel wysokiego poziomu na cel operacyjny, który nadal mieści się w zasadach bezpieczeństwa i scope projektu.

## Step 3: Break into tasks

Agent dzieli pracę na małe taski i przypisuje je do agentów warstwowych.
Każdy task powinien wskazywać scope, pliki i tryb pracy `plan_only` albo `review_required`.

## Step 4: Collect artefacts

Agent zbiera wyniki pracy agentów i ocenia, czy zadanie jest gotowe do review lub kolejnego kroku.

## Step 5: Request review

Jeśli zmiana jest średniego lub wysokiego ryzyka, `system_lead_agent` przekazuje ją do `review_agent` albo do człowieka.
Zmiany cross-layer nie powinny przechodzić bez review.

## Step 6: Decide next step

Agent podejmuje decyzję:
- kontynuować
- poprawić
- zatrzymać
- eskalować

## Hard limit

`system_lead_agent` nie wdraża live tradingu, nie dotyka sekretów i nie obchodzi decyzji człowieka.
Nie pomija też modelu `plan -> review -> write`.
