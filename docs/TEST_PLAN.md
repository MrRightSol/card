# Test Plan

## Backend (pytest)
- `test_synth`: row count, schema, seed determinism
- `test_train`: completes < 10s with MAX_TRAIN_ROWS
- `test_score`: fraud_score in [0,1], policy field present
- `test_policy_parser`: offline fallback returns valid rules JSON

## Frontend (Jest/Vitest + Playwright)
- Render ResultsTable with color pills
- UploadPolicy -> preview JSON
- E2E: 5-step flow completes successfully

## Performance
- Score 10k rows in < 3s on M1 (target)