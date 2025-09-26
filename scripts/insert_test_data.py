#!/usr/bin/env python3
"""Insert small amount of test data into the hackathon MSSQL schema.

Usage: set MSSQL_HOST, MSSQL_DB, MSSQL_USER, MSSQL_PASSWORD in env and run:
  ./venv/bin/python scripts/insert_test_data.py

This will:
- ensure the hackathon schema/tables exist
- insert 5 sample rows into each of: ht_AppsLogs, ht_Employees, ht_Transactions, ht_Models, ht_Scores
"""
from __future__ import annotations

import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

# Ensure the repository root is on sys.path so this script can be run directly
# (e.g. `py scripts/insert_test_data.py`) without requiring PYTHONPATH or venv activation.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.app.services.db import sqlalchemy_url_from_env, create_engine_lazy, ensure_hackathon_schema


def _insert_samples(engine):
    # Use an aware UTC timestamp
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        # AppsLogs
        for i in range(1, 6):
            conn.exec_driver_sql(
                "INSERT INTO dbo.ht_AppsLogs (ts, event_type, payload) VALUES (?, ?, ?)",
                (now, f"test_event_{i}", json.dumps({"i": i, "note": "sample log"})),
            )

        # Employees
        for i in range(1, 6):
            conn.exec_driver_sql(
                "INSERT INTO dbo.ht_Employees (employee_id, name, department, city) VALUES (?, ?, ?, ?)",
                (f"emp_{i}", f"Employee {i}", "Engineering" if i % 2 == 0 else "Sales", "CityX"),
            )

        # Transactions
        for i in range(1, 6):
            conn.exec_driver_sql(
                "INSERT INTO dbo.ht_Transactions (txn_id, employee_id, merchant, city, category, amount, [timestamp], channel, card_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    f"txn_{i}",
                    f"emp_{i}",
                    f"Merchant {i}",
                    "CityX",
                    "Office Supplies",
                    12.5 * i,
                    now,
                    "card",
                    f"card_{i}",
                ),
            )

        # Models
        for i in range(1, 6):
            conn.exec_driver_sql(
                "INSERT INTO dbo.ht_Models (algo, metrics_json) VALUES (?, ?)",
                (f"algo_{i}", json.dumps({"accuracy": 0.9 - i * 0.01})),
            )

        # Scores
        for i in range(1, 6):
            conn.exec_driver_sql(
                "INSERT INTO dbo.ht_Scores (txn_id, model_id, fraud_score, compliant, reason) VALUES (?, ?, ?, ?, ?)",
                (f"txn_{i}", i, 0.1 * i, 1 if i % 2 == 0 else 0, "test"),
            )


def main():
    url = sqlalchemy_url_from_env()
    if not url:
        print("MSSQL environment variables not set. Please set MSSQL_HOST, MSSQL_DB, MSSQL_USER, MSSQL_PASSWORD.")
        return

    engine = create_engine_lazy(url)
    print("Ensuring schema...")
    try:
        res = ensure_hackathon_schema()
        print("Schema ensured:", res)
    except Exception as e:
        print("Failed to ensure schema:", e)
        return

    print("Inserting sample rows...")
    try:
        _insert_samples(engine)
        print("Inserted sample rows into ht_AppsLogs, ht_Employees, ht_Transactions, ht_Models, ht_Scores")
    except Exception as e:
        print("Insert failed:", type(e).__name__, e)


if __name__ == '__main__':
    main()
