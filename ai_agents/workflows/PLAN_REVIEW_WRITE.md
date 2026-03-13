# Plan Review Write

## Default mode

Domyślny tryb pracy agentów to:

1. plan
2. review
3. write

Agent nie powinien zaczynać od edycji plików.

## Step 1: Plan

Agent najpierw:
- czyta dokumenty kanoniczne
- sprawdza swój scope w `ai_agents/rules/AGENT_SCOPE_MANIFEST.yaml`
- przygotowuje mały plan zmiany
- wskazuje pliki, które chce ruszyć
- oznacza, czy zmiana jest cross-layer

Jeśli plik nie należy do `owned scope`, agent nie przechodzi sam do zapisu.

## Step 2: Review

Review jest obowiązkowe, gdy:
- zmiana jest cross-layer
- zmiana dotyka kontraktu
- zmiana dotyka architektury
- zmiana jest średniego lub wysokiego ryzyka
- agent nie jest pewny scope

Review kończy się jedną z decyzji:
- approve
- revise
- human_review_required

## Step 3: Write

Zapis jest dozwolony tylko wtedy, gdy:
- plan ma jasno określony scope
- pliki mieszczą się w `owned scope`
- review nie zablokował zmiany
- zmiana nie dotyka obszaru zastrzeżonego dla człowieka

## Hard write gate

Agent nie zapisuje zmian, jeśli dotyka:
- sekretów
- `.env`
- `docker-compose.yml`
- lokalnych runtime configów
- live tradingu
- exchange API keys

Takie zmiany zawsze wracają do człowieka.

## Practical rule

Najpierw plan i lista plików.
Potem review, jeśli jest wymagane.
Dopiero na końcu write we własnym zakresie odpowiedzialności.
