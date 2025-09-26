from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _file_log_path() -> Path:
    base = Path(os.environ.get("DATA_DIR") or (Path.cwd() / "data" / "logs"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "app_logs.jsonl"


def log_event(event_type: str, payload: Dict[str, Any]) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "payload": payload,
    }
    sink = os.environ.get("LOG_SINK", "file").lower()
    if sink == "db":
        try:
            # Lazy DB logging: create table if needed and insert JSON
            from .db import sqlalchemy_url_from_env, create_engine_lazy

            url = sqlalchemy_url_from_env()
            if not url:
                raise RuntimeError("MSSQL env not set")
            engine = create_engine_lazy(url)
            with engine.begin() as conn:
                # Ensure preferred log table exists and insert
                conn.exec_driver_sql(
                    """
                    IF OBJECT_ID('dbo.ht_AppsLogs', 'U') IS NULL
                    CREATE TABLE dbo.ht_AppsLogs (
                        id INT IDENTITY(1,1) PRIMARY KEY,
                        ts DATETIME2 NOT NULL,
                        event_type NVARCHAR(100) NOT NULL,
                        payload NVARCHAR(MAX) NOT NULL
                    )
                    """
                )
                conn.exec_driver_sql(
                    "INSERT INTO dbo.ht_AppsLogs(ts, event_type, payload) VALUES (?, ?, ?)",
                    (entry["ts"], event_type, json.dumps(payload)),
                )
            return
        except Exception:
            # Fallback to file sink on any error
            pass
    # file sink
    path = _file_log_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def list_events(limit: int = 100) -> List[Dict[str, Any]]:
    sink = os.environ.get("LOG_SINK", "file").lower()
    if sink == "db":
        try:
            from .db import sqlalchemy_url_from_env, create_engine_lazy

            url = sqlalchemy_url_from_env()
            if not url:
                raise RuntimeError("MSSQL env not set")
            engine = create_engine_lazy(url)
            with engine.connect() as conn:
                res = conn.exec_driver_sql(
                    f"SELECT TOP {int(limit)} ts, event_type, payload FROM dbo.ht_AppsLogs ORDER BY id DESC"
                )
                out: List[Dict[str, Any]] = []
                for row in res:
                    out.append(
                        {
                            "ts": str(row[0]),
                            "type": row[1],
                            "payload": json.loads(row[2]) if row[2] else {},
                        }
                    )
                return out
        except Exception:
            pass
    # file sink
    path = _file_log_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out[::-1]
