# (Architecture Decision Record)
# ADR-0001: Choose MS SQL Server
- Context: enterprise alignment + existing licenses
- Decision: MS SQL via SQLAlchemy + pyodbc (ODBC Driver 18)
- Consequences: need driver install; strong T-SQL capabilities; good tooling