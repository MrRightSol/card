from __future__ import annotations

import ast
from typing import Any, Dict, List


def _safe_eval_condition(expr: str, env: Dict[str, Any]) -> bool:
    node = ast.parse(expr, mode='eval')

    def _eval(n):
        if isinstance(n, ast.Expression):
            return _eval(n.body)
        if isinstance(n, ast.Compare):
            left = _eval(n.left)
            for op, right in zip(n.ops, n.comparators):
                rval = _eval(right)
                if isinstance(op, ast.Eq):
                    if not (left == rval):
                        return False
                elif isinstance(op, ast.NotEq):
                    if not (left != rval):
                        return False
                elif isinstance(op, ast.Gt):
                    if not (left > rval):
                        return False
                elif isinstance(op, ast.Lt):
                    if not (left < rval):
                        return False
                elif isinstance(op, ast.GtE):
                    if not (left >= rval):
                        return False
                elif isinstance(op, ast.LtE):
                    if not (left <= rval):
                        return False
                else:
                    raise ValueError('unsupported comparator')
            return True
        if isinstance(n, ast.BoolOp):
            if isinstance(n.op, ast.And):
                return all(_eval(v) for v in n.values)
            if isinstance(n.op, ast.Or):
                return any(_eval(v) for v in n.values)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
            return not _eval(n.operand)
        if isinstance(n, ast.Name):
            return env.get(n.id)
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Str):
            return n.s
        # allow simple literals only
        raise ValueError('unsupported AST node')

    return bool(_eval(node))


def evaluate_rules(txn: Dict[str, Any], rules_json: Dict[str, Any]) -> List[str]:
    violated: List[str] = []
    if not rules_json or 'rules' not in rules_json:
        return violated
    for r in rules_json.get('rules', []):
        cond = r.get('condition')
        name = r.get('name') or r.get('description') or 'unnamed'
        if not cond:
            continue
        try:
            # Build environment mapping with both original keys and lower-cased keys
            env = dict(txn)
            for k, v in list(txn.items()):
                if isinstance(k, str):
                    lk = k.lower()
                    if lk not in env:
                        env[lk] = v
            # normalize numeric types
            # Normalize common numeric fields so comparisons work (amount is required,
            # but policies may reference other numeric columns such as day_total,
            # merchant_txn_7d or city_distance_km).
            # Only normalize numeric fields that exist in the canonical schema.
            numeric_fields = ['amount', 'merchant_txn_7d', 'city_distance_km', 'label']
            for nf in numeric_fields:
                if nf in env:
                    try:
                        env[nf] = float(env[nf])
                    except Exception:
                        # leave as-is if conversion fails
                        pass
            # Normalize boolean-like fields
            if 'is_fraud' in env:
                v = env.get('is_fraud')
                if isinstance(v, str):
                    lv = v.strip().lower()
                    if lv in ('1', 'true', 't', 'yes'):
                        env['is_fraud'] = True
                    elif lv in ('0', 'false', 'f', 'no'):
                        env['is_fraud'] = False
                else:
                    try:
                        env['is_fraud'] = bool(v)
                    except Exception:
                        pass
            ok = _safe_eval_condition(cond, env)
            if ok:
                violated.append(name)
        except Exception:
            # on error, skip this rule
            continue
    return violated
