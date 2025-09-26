from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from ..services.trainer import start_training_job, get_job_status

router = APIRouter()


class TrainBody(BaseModel):
    algo: str
    max_rows: Optional[int] = None
    dataset_path: Optional[str] = None
    # If training from DB, pass a db_query object matching query_transactions params
    db_query: Optional[dict] = None
    # include parsed policy features into training (POC)
    include_policy_features: Optional[bool] = False
    # optional parsed rules JSON to be used as features
    rules_json: Optional[dict] = None


@router.post('/train')
def train_endpoint(body: TrainBody):
    try:
        job_id = start_training_job(
            body.algo,
            max_rows=body.max_rows,
            dataset_path=body.dataset_path,
            db_query=body.db_query,
            include_policy_features=bool(body.include_policy_features),
            rules_json=body.rules_json,
        )
        return {"job_id": job_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/train/status')
def train_status(job_id: str = Query(...)):
    info = get_job_status(job_id)
    if not info:
        raise HTTPException(status_code=404, detail='job not found')
    return info


@router.get("/train/algos")
def list_algos():
    """
    Return curated sklearn algorithms useful for fraud detection
    and policy compliance classification.
    """
    algos = [
        # Anomaly / outlier detection
        {"id": "isolation_forest", "label": "Isolation Forest"},
        {"id": "local_outlier_factor", "label": "Local Outlier Factor"},
        {"id": "one_class_svm", "label": "One-Class SVM"},

        # Ensemble classifiers
        {"id": "random_forest", "label": "Random Forest Classifier"},
        {"id": "gradient_boosting", "label": "Gradient Boosting Classifier"},
        {"id": "xgboost", "label": "XGBoost (if installed)"},

        # Linear / Logistic models
        {"id": "logistic_regression", "label": "Logistic Regression"},
        {"id": "sgd_classifier", "label": "Stochastic Gradient Descent Classifier"},

        # Tree-based models
        {"id": "decision_tree", "label": "Decision Tree Classifier"},
        {"id": "extra_trees", "label": "Extra Trees Classifier"},

        # Neighbors
        {"id": "knn", "label": "K-Nearest Neighbors"},
    ]

    return algos


@router.get('/train/dataset/info')
def dataset_info(path: str):
    from ..services.trainer import _count_csv_rows
    try:
        rows = _count_csv_rows(path)
        return {'rows': rows}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get('/train/dataset/distinct')
def dataset_distinct(path: str, field: str = 'category', limit: int = 200):
    """Return distinct values for a CSV column at the given path.

    This helps the UI map parsed policy categories to actual dataset categories.
    """
    import csv
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        raise HTTPException(status_code=400, detail='path not found')
    vals = []
    seen = set()
    try:
        with p.open(newline='') as f:
            r = csv.DictReader(f)
            for row in r:
                v = row.get(field)
                if v is None:
                    continue
                s = str(v)
                if s not in seen:
                    seen.add(s)
                    vals.append(s)
                    if len(vals) >= int(limit):
                        break
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return vals
