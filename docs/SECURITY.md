# Security Notes
- Never log PII; mask `MSSQL_PASSWORD`, `OPENAI_API_KEY`.
- Use `Encrypt=True` in ODBC parameters; validate certs where applicable.
- CORS limited to local dev by default.
- Rate-limit `/parse-policy` to prevent abuse.