# Architecture

## Modules
- `api/app/routers/`: synth, policy, train, score, health
- `api/app/services/`: db, policy_parser, synth_gen, trainer, scorer
- `api/app/models/`: ORM models
- `web/`: Angular 20 app with feature modules:
  - `features/policy`, `features/train`, `features/results`
  - Shared UI components: stepper, table, drawer

## Data Flow
Policy PDF → LLM → Rules JSON → Trainer (fits model on synthetic data) → Scorer (policy + fraud) → Frontend table.

## Key Decisions
- IsolationForest for speed; optional RandomForest with weak labels.
- Explainability: show violated rule + top anomaly features.