# Runbook
- Start DB (container or remote) → confirm ODBC driver 18 installed.
- Backend:
  - `pip install -r requirements.txt`
  - `alembic upgrade head` (if you add Alembic)
- Frontend:
  - `npm ci && ng serve --port 5173`
- Common issues:
  - ODBC driver not found → install `msodbcsql18` and `unixodbc-dev`.