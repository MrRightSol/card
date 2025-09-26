# Expense Fraud & Policy Compliance – FastAPI + Angular 20 + MS SQL Server

## Stack
- Backend: FastAPI (Python 3.11+), SQLAlchemy 2.x, pyodbc + ODBC Driver 18 for SQL Server
- Frontend: Angular 20

Note on upgrading Angular / Material
- When upgrading the frontend, ensure all Angular packages (@angular/*), @angular/material, @angular/cdk and zone.js are compatible. Always run migrations (ng update) in a clean git working tree and verify Node.js meets the minimum required version (>=20.19 or Node 22+).
- DB: Microsoft SQL Server
- AI: OpenAI API for policy parsing (JSON rules)

## Quickstart
1. Create `.env` from `.env.example`.
2. Backend:
   ```bash
   uvicorn app.main:app --reload --port 8080
3.	Frontend:   
   cd web && npm ci && ng serve --port 5173
4.	Swagger: http://localhost:8080/docs  |  Web: http://localhost:5173
   Demo Flow
	1.	Generate synthetic data → 2) Upload policy → 3) Train model → 4) Score → 5) Dashboard.   
   ---

## Git workflow helpers

This repository includes small helper scripts to initialise a git repo and
perform common tasks safely. See docs/GIT_WORKFLOW.md for usage examples and
details. The scripts live in the `scripts/` directory (e.g. scripts/git-setup.sh,
scripts/git-commit.sh, scripts/git-rollback.sh).


## 2) `ENVIRONMENT.md`
```md
# Environment Variables

## Required (Backend)
- `MSSQL_HOST` (e.g., 127.0.0.1)
- `MSSQL_PORT` (default 1433)
- `MSSQL_DB`
- `MSSQL_USER`
- `MSSQL_PASSWORD`
- `MSSQL_ENCRYPT` (true|false; default true)
- `OPENAI_API_KEY` (optional for offline demos)
- `OPENAI_MODEL` (e.g., gpt-4o-mini)
- `MAX_TRAIN_ROWS` (e.g., 20000)

### SQLAlchemy URL
`mssql+pyodbc://{MSSQL_USER}:{MSSQL_PASSWORD}@{MSSQL_HOST},{MSSQL_PORT}/{MSSQL_DB}?driver=ODBC+Driver+18+for+SQL+Server&Encrypt={MSSQL_ENCRYPT}`

## Required (Frontend)
- `VITE_API_URL` (e.g., http://localhost:8080)