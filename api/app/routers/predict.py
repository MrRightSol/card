from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from ..services import trainer
import ast

router = APIRouter()


class PredictBody(BaseModel):
    transaction: Dict[str, Any]
    model_job_id: Optional[str] = None
    rules_json: Optional[Dict[str, Any]] = None


def _safe_eval_condition(expr: str, env: Dict[str, Any]) -> bool:
    # Parse to AST and allow a very small subset for safety
    node = ast.parse(expr, mode='eval')

    def _eval(n):
        if isinstance(n, ast.Expression):
            return _eval(n.body)
        if isinstance(n, ast.Compare):
            left = _eval(n.left)
            for op, right in zip(n.ops, n.comparators):
                rval = _eval(right)
                if isinstance(op, ast.Eq):
                    if not (left == rval): return False
                elif isinstance(op, ast.NotEq):
                    if not (left != rval): return False
                elif isinstance(op, ast.Gt):
                    if not (left > rval): return False
                elif isinstance(op, ast.Lt):
                    if not (left < rval): return False
                elif isinstance(op, ast.GtE):
                    if not (left >= rval): return False
                elif isinstance(op, ast.LtE):
                    if not (left <= rval): return False
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
        # support simple attribute access like txn.amount -> Name('amount') used above
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
            # map variable names to transaction fields for evaluation
            env = dict(txn)
            # allow simple names like amount, category to map to txn values
            ok = _safe_eval_condition(cond, env)
            if ok:
                violated.append(name)
        except Exception:
            continue
    return violated


@router.post('/predict')
def predict_endpoint(body: PredictBody):
    # Load model
    model = None
    if body.model_job_id:
        info = trainer.get_job_status(body.model_job_id)
        if not info or info.get('status') != 'done':
            raise HTTPException(status_code=400, detail='model not ready')
        model_path = None
        res = info.get('result')
        if res and isinstance(res, dict):
            model_path = res.get('model_path')
        if not model_path:
            raise HTTPException(status_code=500, detail='trained model path not found')
        try:
            model = trainer.load_model_by_job(body.model_job_id)
            if model is None:
                raise RuntimeError('failed to load model')
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        raise HTTPException(status_code=400, detail='model_job_id required')

    # compute score
    score = trainer.predict_transaction_with_model(model, body.transaction)
    # evaluate policy rules if provided
    violated = evaluate_rules(body.transaction, body.rules_json) if body.rules_json else []
    out = {
        'fraud_score': score,
        'out_of_policy': len(violated) > 0,
        'violated_rules': violated,
    }
    return out
