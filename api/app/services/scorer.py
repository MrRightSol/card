from __future__ import annotations

from typing import Any, Dict, List, Optional
import csv

from .trainer import get_model
from .logging_service import log_event
from .db import run_query_to_dicts


def _featurize_for_scoring(_: List[Dict[str, Any]], feature_names: List[str]):
    # No-op in lightweight implementation; feature alignment is not needed
    return feature_names


def _apply_policy_rules(row: Dict[str, Any], rules_json: Dict[str, Any] | None) -> Dict[str, Any]:
    # Use centralized safe evaluation for rules
    if not rules_json:
        return {"compliant": True, "violated_rules": [], "reason": "no rules"}
    try:
        from .policy_eval import evaluate_rules
        violated = evaluate_rules(row, rules_json)
    except Exception:
        violated = []
    compliant = len(violated) == 0
    reason = "; ".join(violated) if violated else "OK"
    return {"compliant": compliant, "violated_rules": violated, "reason": reason}


def _load_rows_from_csv(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows


def _rows_to_amounts(rows: List[Dict[str, Any]]) -> List[float]:
    amounts: List[float] = []
    for row in rows:
        try:
            row_amount = float(row.get("amount", 0.0))
        except Exception:
            row_amount = 0.0
        amounts.append(row_amount)
    return amounts


def score_dataset(dataset_path: str | None = None, db_query: Dict[str, Any] | None = None, rules_json: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    model, _ = get_model()
    rows: List[Dict[str, Any]] = []
    # Support three modes:
    # 1) dataset_path provided (CSV or mssql:// raw query)
    # 2) db_query provided — call query_transactions paging API
    # 3) neither -> error
    if dataset_path:
        if dataset_path.lower().startswith("mssql://"):
            query = dataset_path[len("mssql://") :]
            try:
                rows = run_query_to_dicts(query)
            except Exception as e:
                raise RuntimeError(f"MSSQL query failed: {e}")
        else:
            rows = _load_rows_from_csv(dataset_path)
    elif db_query:
        # Page through DB rows using the same helper used elsewhere
        try:
            from .db import query_transactions
            page = 0
            page_size = 1000
            collected: List[Dict[str, Any]] = []
            while True:
                qparams = dict(db_query)
                qparams['page'] = page
                qparams['page_size'] = page_size
                res = query_transactions(**qparams)
                items = res.get('items', [])
                for it in items:
                    collected.append(it)
                total = res.get('total', 0)
                if (page + 1) * page_size >= total:
                    break
                page += 1
            rows = collected
        except Exception as e:
            raise RuntimeError(f"DB query failed: {e}")
    else:
        raise RuntimeError('score requires either dataset_path or db_query')
    amounts = _rows_to_amounts(rows)
    if model is None:
        if amounts:
            mean = sum(amounts) / len(amounts)
            var = sum((x - mean) ** 2 for x in amounts) / max(1, (len(amounts) - 1))
            std = (var ** 0.5) or 1.0
        else:
            mean, std = 0.0, 1.0
    else:
        mean = float(model.get("mean", 0.0))
        std = float(model.get("std", 1.0)) or 1.0
    results: List[Dict[str, Any]] = []
    for row in rows:
        try:
            amount = float(row.get("amount", 0.0))
        except Exception:
            amount = 0.0
        z = abs(amount - mean) / (std or 1.0)
        score = max(0.0, min(1.0, z / 6.0))
        policy = _apply_policy_rules(row, rules_json)
        results.append(
            {
                "txn_id": row.get("txn_id"),
                "amount": amount,
                "category": row.get("category"),
                "fraud_score": float(score),
                "policy": policy,
            }
        )
    try:
        log_event(
            "score",
            {
                "rows": len(rows),
                "mean": mean,
                "std": std,
            },
        )
    except Exception:
        pass
    return results
