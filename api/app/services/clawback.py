from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .db import sqlalchemy_url_from_env, create_engine_lazy


def _now():
    return datetime.utcnow().isoformat() + 'Z'


def ensure_clawback_schema() -> None:
    url = sqlalchemy_url_from_env()
    if not url:
        raise RuntimeError('MSSQL environment not configured')
    engine = create_engine_lazy(url)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            IF OBJECT_ID('dbo.ht_ClawBackJobs', 'U') IS NULL
            CREATE TABLE dbo.ht_ClawBackJobs (
                job_id NVARCHAR(50) NOT NULL PRIMARY KEY,
                name NVARCHAR(200) NULL,
                created_by NVARCHAR(200) NULL,
                created_at DATETIME2 NOT NULL,
                filters_json NVARCHAR(MAX) NULL,
                template_text NVARCHAR(MAX) NULL,
                job_status NVARCHAR(50) NULL,
                metadata_json NVARCHAR(MAX) NULL
            )
            """
        )
        conn.exec_driver_sql(
            """
            IF OBJECT_ID('dbo.ht_ClawBackItems', 'U') IS NULL
            CREATE TABLE dbo.ht_ClawBackItems (
                item_id NVARCHAR(50) NOT NULL PRIMARY KEY,
                job_id NVARCHAR(50) NULL,
                txn_id NVARCHAR(50) NULL,
                employee_id NVARCHAR(50) NULL,
                rendered_email NVARCHAR(MAX) NULL,
                status NVARCHAR(50) NULL,
                simulate_result NVARCHAR(200) NULL,
                created_at DATETIME2 NULL,
                updated_at DATETIME2 NULL,
                note NVARCHAR(4000) NULL
            )
            """
        )


def _render_email(template_text: Optional[str], employee_id: str, transactions: List[Dict[str, Any]], job_name: str | None = None) -> str:
    # Very small templating: support {employee_id}, {job_name}, and {transactions}
    lines = []
    for t in transactions:
        amt = t.get('amount')
        try:
            amt = float(amt) if amt is not None else 0.0
            amt = f"${amt:.2f}"
        except Exception:
            amt = str(amt)
        lines.append(f"- {t.get('txn_id')} | {t.get('timestamp')} | {t.get('merchant')} | {t.get('city')} | {t.get('category')} | {amt}")
    tx_block = "\n".join(lines)
    tpl = template_text or (
        "Hello {employee_id},\n\n"
        "This is a notification that our expense review has identified the following transactions which may be subject to a claw back for job '{job_name}':\n\n"
        "{transactions}\n\n"
        "Please reply if you believe any of these are incorrect.\n\n"
        "Regards,\nExpense Team"
    )
    rendered = tpl.format(employee_id=employee_id, transactions=tx_block, job_name=job_name or '')
    return rendered


def create_clawback_job(
    name: Optional[str],
    created_by: Optional[str],
    selected_txn_ids: Optional[List[str]] = None,
    selected_transactions: Optional[List[Dict[str, Any]]] = None,
    template_text: Optional[str] = None,
    filters_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a claw back job from either txn ids (DB) or provided transactions.

    Returns job metadata including items created.
    """
    job_id = str(uuid.uuid4())
    created_at = _now()
    # Determine whether DB is required (if caller provided txn ids, we must
    # fetch authoritative transaction details from the DB). If selected_txn_ids
    # is supplied we consider the DB required; if only selected_transactions is
    # supplied we operate in file-backed mode and DB is optional.
    require_db = bool(selected_txn_ids)

    # Fetch transactions
    txns: List[Dict[str, Any]] = []
    if selected_transactions:
        txns = selected_transactions
    elif selected_txn_ids:
        url = sqlalchemy_url_from_env()
        if not url:
            raise RuntimeError('DB not configured and no transaction objects provided')
        engine = create_engine_lazy(url)
        qmarks = ",".join(["?" for _ in selected_txn_ids])
        sql = (
            "SELECT txn_id, employee_id, merchant, city, category, amount, [timestamp], channel, card_id, is_fraud, label, policy_flags "
            f"FROM dbo.ht_Transactions WHERE txn_id IN ({qmarks})"
        )
        with engine.connect() as conn:
            res = conn.exec_driver_sql(sql, tuple(selected_txn_ids))
            cols = res.keys()
            for r in res:
                txns.append({k: r[idx] for idx, k in enumerate(cols)})
    else:
        raise RuntimeError('No transactions provided')

    # Group by employee
    by_emp: Dict[str, List[Dict[str, Any]]] = {}
    for t in txns:
        emp = t.get('employee_id') or 'unknown'
        by_emp.setdefault(emp, []).append(t)

    items: List[Dict[str, Any]] = []

    url = sqlalchemy_url_from_env()
    if url:
        try:
            engine = create_engine_lazy(url)
            with engine.begin() as conn:
                # insert job
                conn.exec_driver_sql(
                    "INSERT INTO dbo.ht_ClawBackJobs (job_id, name, created_by, created_at, filters_json, template_text, job_status, metadata_json) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        job_id,
                        name,
                        created_by,
                        created_at,
                        json.dumps(filters_json or {}),
                        template_text,
                        'created',
                        json.dumps({}),
                    ),
                )
                for emp, txs in by_emp.items():
                    rendered = _render_email(template_text, emp, txs, job_name=name)
                    item_id = str(uuid.uuid4())
                    conn.exec_driver_sql(
                        "INSERT INTO dbo.ht_ClawBackItems (item_id, job_id, txn_id, employee_id, rendered_email, status, simulate_result, created_at, updated_at, note) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (
                            item_id,
                            job_id,
                            ','.join([t.get('txn_id') or '' for t in txs]),
                            emp,
                            rendered,
                            'pending',
                            None,
                            created_at,
                            created_at,
                            None,
                        ),
                    )
                    items.append({'item_id': item_id, 'employee_id': emp, 'txn_count': len(txs), 'rendered_email': rendered})
            return {'job_id': job_id, 'items': items, 'employees_count': len(items), 'transactions_count': len(txns)}
        except Exception:
            # If DB was required (txn ids provided), do not silently fall back;
            # surface the error so the caller can retry/configure DB.
            if require_db:
                raise
            # otherwise fall through to file-backed fallback
            pass

    # file-backed fallback
    from pathlib import Path

    base = Path('data') / 'clawback'
    base.mkdir(parents=True, exist_ok=True)
    job_file = base / f"job_{job_id}.json"
    job_obj = {
        'job_id': job_id,
        'name': name,
        'created_by': created_by,
        'created_at': created_at,
        'filters_json': filters_json or {},
        'template_text': template_text,
        'job_status': 'created',
        'metadata_json': {},
        'items': [],
    }
    for emp, txs in by_emp.items():
        rendered = _render_email(template_text, emp, txs, job_name=name)
        item_id = str(uuid.uuid4())
        it = {
            'item_id': item_id,
            'job_id': job_id,
            'txn_ids': [t.get('txn_id') for t in txs],
            'employee_id': emp,
            'rendered_email': rendered,
            'status': 'pending',
            'simulate_result': None,
            'created_at': created_at,
            'updated_at': created_at,
            'note': None,
        }
        job_obj['items'].append(it)
        items.append({'item_id': item_id, 'employee_id': emp, 'txn_count': len(txs), 'rendered_email': rendered})
    job_file.write_text(json.dumps(job_obj, indent=2), encoding='utf-8')

    return {'job_id': job_id, 'items': items, 'employees_count': len(items), 'transactions_count': len(txns)}


def get_clawback_job(job_id: str) -> Dict[str, Any]:
    url = sqlalchemy_url_from_env()
    # Try DB first, but if DB connection fails, fall back to file-backed storage
    if url:
        try:
            engine = create_engine_lazy(url)
            with engine.connect() as conn:
                res = conn.exec_driver_sql("SELECT job_id, name, created_by, created_at, filters_json, template_text, job_status, metadata_json FROM dbo.ht_ClawBackJobs WHERE job_id = ?", (job_id,))
                row = res.fetchone()
                if not row:
                    # Not found in DB; try file fallback
                    raise RuntimeError('not_found_db')
                job = {k: row[idx] for idx, k in enumerate(res.keys())}
                items = []
                res2 = conn.exec_driver_sql("SELECT item_id, txn_id, employee_id, rendered_email, status, simulate_result, created_at, updated_at, note FROM dbo.ht_ClawBackItems WHERE job_id = ?", (job_id,))
                for r in res2:
                    items.append({k: r[idx] for idx, k in enumerate(res2.keys())})
                job['items'] = items
                return job
        except Exception:
            # Fall through to file-backed fallback
            pass

    from pathlib import Path
    p = Path('data') / 'clawback' / f"job_{job_id}.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}


def list_clawback_jobs() -> List[Dict[str, Any]]:
    url = sqlalchemy_url_from_env()
    out: List[Dict[str, Any]] = []
    if url:
        try:
            engine = create_engine_lazy(url)
            with engine.connect() as conn:
                res = conn.exec_driver_sql("SELECT job_id, name, created_by, created_at, job_status FROM dbo.ht_ClawBackJobs ORDER BY created_at DESC")
                for r in res:
                    row = {k: r[idx] for idx, k in enumerate(res.keys())}
                    # count items
                    try:
                        c = conn.exec_driver_sql("SELECT item_id, txn_id FROM dbo.ht_ClawBackItems WHERE job_id = ?", (row.get('job_id'),))
                        items = [dict(zip(c.keys(), r2)) for r2 in c]
                        row['employees_count'] = len(items)
                        # compute transactions_count by summing txn_id comma lists
                        tx_count = 0
                        for it in items:
                            t = it.get('txn_id') or ''
                            if isinstance(t, str) and t.strip():
                                tx_count += len([x for x in t.split(',') if x.strip()])
                        row['transactions_count'] = tx_count
                    except Exception:
                        row['employees_count'] = 0
                        row['transactions_count'] = 0
                    out.append(row)
            return out
        except Exception:
            # Fall back to file-based listing
            pass

    from pathlib import Path
    base = Path('data') / 'clawback'
    if not base.exists():
        return []
    for p in sorted(base.glob('job_*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            j = json.loads(p.read_text(encoding='utf-8'))
            out.append({
                'job_id': j.get('job_id'),
                'name': j.get('name'),
                'created_by': j.get('created_by'),
                'created_at': j.get('created_at'),
                'job_status': j.get('job_status'),
                'employees_count': len(j.get('items', [])),
            })
        except Exception:
            continue
    return out


def validate_txn_selection(selected_txn_ids: List[str]) -> Dict[str, Any]:
    """Validate that txn ids exist and compute employee count.

    Returns dict with keys: missing_txn_ids, employees_count, transactions_count.
    """
    from pathlib import Path

    if not selected_txn_ids:
        return {"missing_txn_ids": [], "employees_count": 0, "transactions_count": 0}

    url = sqlalchemy_url_from_env()
    if url:
        engine = create_engine_lazy(url)
        # Query DB for the provided txn ids
        qmarks = ",".join(["?" for _ in selected_txn_ids])
        sql = f"SELECT txn_id, employee_id FROM dbo.ht_Transactions WHERE txn_id IN ({qmarks})"
        found = {}
        with engine.connect() as conn:
            res = conn.exec_driver_sql(sql, tuple(selected_txn_ids))
            for r in res:
                row = {k: r[idx] for idx, k in enumerate(res.keys())}
                found[row.get('txn_id')] = row.get('employee_id')
        missing = [t for t in selected_txn_ids if t not in found]
        emp_set = set(v for v in found.values() if v is not None)
        result = {"missing_txn_ids": missing, "employees_count": len(emp_set), "transactions_count": len(found)}
        # Check for any selected txns that are already part of an open/non-resolved clawback item
        already = []
        try:
            for tid in selected_txn_ids:
                # search in ht_ClawBackItems.txn_id comma-joined field for this tid
                likep = f'%,{tid},%'
                q = "SELECT item_id, job_id, txn_id, status FROM dbo.ht_ClawBackItems WHERE (',' + txn_id + ',') LIKE ? AND (status IS NULL OR status NOT IN ('resolved','closed'))"
                res2 = conn.exec_driver_sql(q, (likep,))
                for r2 in res2:
                    row2 = {k: r2[idx] for idx, k in enumerate(res2.keys())}
                    already.append({"txn_id": tid, "item_id": row2.get('item_id'), "job_id": row2.get('job_id'), "status": row2.get('status')})
        except Exception:
            # if anything goes wrong, ignore already check (non-fatal)
            already = []
        result['already_in_open_jobs'] = already
        return result
    else:
        # file-based fallback: try to locate jobs that may contain txns (best-effort)
        base = Path('data') / 'clawback'
        # cannot validate against canonical transactions without DB; report all missing
        return {"missing_txn_ids": selected_txn_ids, "employees_count": 0, "transactions_count": 0, 'already_in_open_jobs': []}


def update_clawback_item(job_id: str, item_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    url = sqlalchemy_url_from_env()
    now = _now()
    if url:
        engine = create_engine_lazy(url)
        with engine.begin() as conn:
            # allowed updates: rendered_email, status, note
            params = []
            sets = []
            if 'rendered_email' in updates:
                sets.append('rendered_email = ?')
                params.append(updates['rendered_email'])
            if 'status' in updates:
                sets.append('status = ?')
                params.append(updates['status'])
            if 'note' in updates:
                sets.append('note = ?')
                params.append(updates['note'])
            if not sets:
                return {}
            sets.append('updated_at = ?')
            params.append(now)
            params.extend([item_id])
            sql = f"UPDATE dbo.ht_ClawBackItems SET {', '.join(sets)} WHERE item_id = ?"
            conn.exec_driver_sql(sql, tuple(params))
            res = conn.exec_driver_sql("SELECT item_id, job_id, txn_id, employee_id, rendered_email, status, simulate_result, created_at, updated_at, note FROM dbo.ht_ClawBackItems WHERE item_id = ?", (item_id,))
            row = res.fetchone()
            return {k: row[idx] for idx, k in enumerate(res.keys())} if row else {}
    else:
        from pathlib import Path
        p = Path('data') / 'clawback' / f"job_{job_id}.json"
        if not p.exists():
            return {}
        job = json.loads(p.read_text(encoding='utf-8'))
        for it in job.get('items', []):
            if it.get('item_id') == item_id:
                for k, v in updates.items():
                    it[k] = v
                it['updated_at'] = now
                p.write_text(json.dumps(job, indent=2), encoding='utf-8')
                return it
        return {}


def simulate_send(job_id: str, item_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Simulate sending notifications. Returns per-item results."""
    now = _now()
    url = sqlalchemy_url_from_env()
    results = []
    if url:
        engine = create_engine_lazy(url)
        with engine.begin() as conn:
            q = "SELECT item_id FROM dbo.ht_ClawBackItems WHERE job_id = ?"
            params = [job_id]
            if item_ids:
                # filter
                q = f"SELECT item_id FROM dbo.ht_ClawBackItems WHERE job_id = ? AND item_id IN ({','.join(['?']*len(item_ids))})"
                params = [job_id] + item_ids
            res = conn.exec_driver_sql(q, tuple(params))
            ids = [r[0] for r in res]
            for iid in ids:
                # mark as notified
                conn.exec_driver_sql("UPDATE dbo.ht_ClawBackItems SET status = ?, simulate_result = ?, updated_at = ? WHERE item_id = ?", ('notified', 'simulated_ok', now, iid))
                results.append({'item_id': iid, 'result': 'simulated_ok'})
    else:
        from pathlib import Path
        p = Path('data') / 'clawback' / f"job_{job_id}.json"
        if not p.exists():
            return []
        job = json.loads(p.read_text(encoding='utf-8'))
        for it in job.get('items', []):
            if item_ids and it.get('item_id') not in item_ids:
                continue
            it['status'] = 'notified'
            it['simulate_result'] = 'simulated_ok'
            it['updated_at'] = now
            results.append({'item_id': it.get('item_id'), 'result': 'simulated_ok'})
        p.write_text(json.dumps(job, indent=2), encoding='utf-8')
    return results
