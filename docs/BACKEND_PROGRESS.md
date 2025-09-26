# Expense Fraud & Policy Compliance – Backend Progress and Usage

This document summarizes what has been implemented so far on the backend, how to run it, environment variables, endpoints, database integration, and sample commands.

## Stack
- FastAPI (Python 3.11+)
- Optional: SQLAlchemy + pyodbc + Microsoft ODBC Driver 18 for SQL Server
- Optional: OpenAI (policy parsing)
- Test runner: pytest

## Run locally
1) Create and activate a virtualenv
- python3 -m venv venv
- source venv/bin/activate

2) Install dependencies (baseline)
- python -m pip install -U pip setuptools wheel
- python -m pip install "uvicorn[standard]" fastapi pytest

3) Optional: MSSQL support
- python -m pip install "SQLAlchemy>=2.0" pyodbc
- Install Microsoft ODBC Driver 18 for SQL Server (via Homebrew on macOS)

4) Optional: Excel import
- python -m pip install openpyxl

5) Optional: OpenAI policy parsing
- python -m pip install openai

6) Start the API
- python -m uvicorn api.app.main:app --host 0.0.0.0 --port 8080 --reload

## Environment variables
- LOG_SINK: file (default) | db (to store logs in MSSQL)
- DATA_DIR: directory to store synthetic CSVs (default: ./data/synth)

MSSQL (when using DB features):
- MSSQL_HOST, MSSQL_PORT=1433, MSSQL_DB, MSSQL_USER, MSSQL_PASSWORD
- MSSQL_ENCRYPT=yes|no (default yes)
- MSSQL_TRUST_CERT=yes|no (default yes if ENCRYPT=yes)
- ODBC_DRIVER="ODBC Driver 18 for SQL Server"

OpenAI (optional):
- USE_OPENAI=1|0 (default 1)
- OPENAI_API_KEY
- OPENAI_MODEL (default gpt-4o-mini)

## Endpoints (current)
- GET /healthz
- POST /generate-synth
  - Body: { rows: int, seed?: int }
  - Response: { path: string, preview: [ up to 10 rows ] }
- POST /parse-policy
  - Accepts either JSON body { text: string } or multipart form-data with a file field "policy"
  - Response: { rules: [...], version: "1.0", source: "openai|fallback|upload|none" }
- POST /train
  - Body: { algo: "isoforest", max_rows?: int }
  - Response: { algo: "isoforest", fit_seconds: number, features: [string] }
- POST /score
  - Body: { dataset_path: string, rules_json?: object }
  - dataset_path may be a CSV path or an MSSQL query prefixed with "mssql://"
  - Response: [ { txn_id, amount, category, fraud_score (0..1), policy: {compliant, violated_rules, reason} } ]
- GET /logs?limit=100
  - Returns recent logs from file or MSSQL (if LOG_SINK=db)

DB Admin:
- POST /db/setup
  - Creates tables: dbo.ht_Employees, dbo.ht_Transactions, dbo.ht_Models, dbo.ht_Scores, dbo.ht_AppsLogs
  - Creates indexes: IX_ht_Transactions_Employee_Timestamp, IX_ht_Transactions_Merchant_Timestamp
- POST /db/load-csv
  - Body: { path: string, truncate?: bool, limit?: int }
  - Loads a CSV into dbo.ht_Transactions
- POST /db/load-excel
  - Body: { path: string, sheet?: string, truncate?: bool, limit?: int }
  - Loads an Excel file into dbo.ht_Transactions (openpyxl required)
- GET /db/transactions?top=10
  - Peeks recent rows from dbo.ht_Transactions

## Postman collection
- File: postman/FraudCompliance.postman_collection.json
- Variables: {{base_url}} (default http://localhost:8080), {{csv_path}}, {{xlsx_path}}
- Includes examples for all endpoints listed above.

## Sample usage (curl)
- Initialize DB (creates ht_* tables)
  - curl -X POST http://localhost:8080/db/setup

- Generate synthetic CSV
  - curl -s -X POST http://localhost:8080/generate-synth -H 'Content-Type: application/json' -d '{"rows": 5000, "seed": 42}'

- Train
  - curl -s -X POST http://localhost:8080/train -H 'Content-Type: application/json' -d '{"algo":"isoforest","max_rows":2000}'

- Score from CSV
  - curl -s -X POST http://localhost:8080/score -H 'Content-Type: application/json' -d '{"dataset_path":"/path/to.csv"}' | head -c 400

- Score from MSSQL
  - curl -s -X POST http://localhost:8080/score -H 'Content-Type: application/json' -d '{"dataset_path":"mssql://SELECT TOP 1000 txn_id, employee_id, merchant, city, category, amount, timestamp, channel, card_id FROM dbo.ht_Transactions"}' | head -c 400

- Load CSV into MSSQL
  - curl -s -X POST http://localhost:8080/db/load-csv -H 'Content-Type: application/json' -d '{"path":"./data/synth/your.csv","truncate":true,"limit":50000}'

- Load Excel into MSSQL
  - curl -s -X POST http://localhost:8080/db/load-excel -H 'Content-Type: application/json' -d '{"path":"./data/import/transactions.xlsx","sheet":"Sheet1","truncate":true,"limit":50000}'

- View logs
  - curl -s "http://localhost:8080/logs?limit=20"  # reads from dbo.ht_AppsLogs

## Implementation notes
- For tests and portability, the current trainer/scorer uses a lightweight approach (mean/std Z-score) to avoid heavy ML dependencies. It returns the API contract fields required by tests. We can swap to IsolationForest (sklearn) for better anomaly detection once dependencies are agreed.
- /parse-policy supports both LLM and deterministic fallback; multipart upload is handled without python-multipart by parsing the request body.
- Synthetic CSV generator writes into ./data/synth by default (or DATA_DIR if set) and returns a 10-row preview.
- Logging: train and score steps emit logs to file by default, or to MSSQL when LOG_SINK=db is set.

## Known limitations / next steps
- Replace eval-based policy rule checks with a safe expression parser.
- Persist trained models (ht_Models) and scoring outputs (ht_Scores) with linkage to models.
- Add pagination/streaming for /score responses with very large datasets.
- Frontend (Angular 20) scaffold for end-to-end demo.
- Extend Excel loader mapping rules and add a preview endpoint.
