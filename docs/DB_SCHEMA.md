# MSSQL Schema (logical)

## Tables
- Employees(employee_id PK, name, department, city)
- Transactions(txn_id PK, employee_id FK, merchant, city, category, amount DECIMAL(12,2), timestamp DATETIME2, channel, card_id)
- Models(model_id PK, algo, created_at, metrics_json)
- Scores(score_id PK, txn_id FK, model_id FK, fraud_score FLOAT, compliant BIT, reason NVARCHAR(4000))

## Indexing
- IX_Transactions_Employee_Timestamp (employee_id, timestamp)
- IX_Transactions_Merchant_Timestamp (merchant, timestamp)

## Notes
- Use UTC for timestamps.
- Keep raw data immutable; write Scores separately.