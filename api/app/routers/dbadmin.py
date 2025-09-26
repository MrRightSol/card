from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from ..services.db import (
    ensure_hackathon_schema,
    load_transactions_csv,
    load_transactions_excel,
    run_query_to_dicts,
    truncate_transactions,
    query_transactions,
    distinct_values,
)
from ..services.logging_service import log_event

router = APIRouter()


@router.post("/db/setup")
def db_setup():
    try:
        return ensure_hackathon_schema()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(e).__name__}: {e}. To enable MSSQL, ensure MSSQL_* environment variables are set for the running server (MSSQL_HOST, MSSQL_DB, MSSQL_USER, MSSQL_PASSWORD).\n"
                "You can add them to ~/.zshrc and 'source ~/.zshrc' or create a .env file in the repo root. Also ensure sqlalchemy and pyodbc are installed and ODBC Driver 18 is available."
            ),
        )


class LoadCsvBody(BaseModel):
    path: str
    truncate: bool = False
    limit: int | None = None


@router.post("/db/load-csv")
def db_load_csv(body: LoadCsvBody):
    try:
        return load_transactions_csv(body.path, truncate=body.truncate, limit=body.limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=(f"{type(e).__name__}: {e}. Ensure MSSQL env and DB connectivity. Use POST /db/ping to test connection."))


@router.get("/db/transactions")
def db_transactions(
    employee_id: list[str] | None = Query(default=None),
    merchant: list[str] | None = Query(default=None),
    city: list[str] | None = Query(default=None),
    category: list[str] | None = Query(default=None),
    channel: list[str] | None = Query(default=None),
    card_id: list[str] | None = Query(default=None),
    min_amount: float | None = Query(default=None, ge=0),
    max_amount: float | None = Query(default=None, ge=0),
    start_ts: str | None = None,
    end_ts: str | None = None,
    page: int = Query(default=0, ge=0),
    page_size: int = Query(default=50, ge=1, le=1000),
    sort_by: str | None = None,
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
):
    try:
        return query_transactions(
            employee_id=employee_id,
            merchant=merchant,
            city=city,
            category=category,
            channel=channel,
            card_id=card_id,
            min_amount=min_amount,
            max_amount=max_amount,
            start_ts=start_ts,
            end_ts=end_ts,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except Exception as e:
        try:
            log_event(
                "db_error",
                {
                    "endpoint": "/db/transactions",
                    "error": str(e),
                    "type": type(e).__name__,
                    "params": {
                        "employee_id": employee_id,
                        "merchant": merchant,
                        "city": city,
                        "category": category,
                        "channel": channel,
                        "card_id": card_id,
                        "min_amount": min_amount,
                        "max_amount": max_amount,
                        "start_ts": start_ts,
                        "end_ts": end_ts,
                        "page": page,
                        "page_size": page_size,
                        "sort_by": sort_by,
                        "sort_dir": sort_dir,
                    },
                },
            )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@router.post("/db/transactions/truncate")
def db_truncate_transactions():
    try:
        return truncate_transactions()
    except Exception as e:
        raise HTTPException(status_code=500, detail=(f"{type(e).__name__}: {e}. Ensure MSSQL env and DB connectivity. Use POST /db/ping to test connection."))


@router.get("/db/transactions/distinct")
def db_distinct(field: str = Query(..., pattern="^(employee_id|merchant|city|category|channel|card_id)$"), q: str | None = None, limit: int = Query(50, ge=1, le=500)):
    try:
        return distinct_values(field, q=q, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class LoadExcelBody(BaseModel):
    path: str
    sheet: str | None = None
    truncate: bool = False
    limit: int | None = None


@router.post("/db/load-excel")
def db_load_excel(body: LoadExcelBody):
    try:
        return load_transactions_excel(
            path=body.path, sheet=body.sheet, truncate=body.truncate, limit=body.limit
        )
    except ImportError as e:
        # Hint to install openpyxl when missing
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/db/ping')
def db_ping():
    try:
        # try a minimal connection and simple select
        from ..services.db import sqlalchemy_url_from_env, create_engine_lazy
        url = sqlalchemy_url_from_env()
        if not url:
            raise RuntimeError('MSSQL env vars not set')
        engine = create_engine_lazy(url)
        with engine.connect() as conn:
            conn.exec_driver_sql('SELECT 1')
        return {'ok': True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=(f"{type(e).__name__}: {e}. Check MSSQL env and connectivity."))
