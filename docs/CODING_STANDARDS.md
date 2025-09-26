# Coding Standards
- Python: Ruff + Black, type hints everywhere, SQLAlchemy 2.0 style.
- Angular: Standalone components, strict mode, signals where suitable.
- HTTP: 201 for created, 422 for validation; pydantic models for requests/responses.
- Logging: structured JSON logs; request-id middleware.
- Errors: never expose stack traces; consistent error envelope `{error:{code,msg}}`.