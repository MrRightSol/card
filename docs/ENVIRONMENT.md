---

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
## (Also include a .env.example file—non-MD—but you already asked for envs.)