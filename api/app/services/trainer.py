from __future__ import annotations

import csv
import math
import time
import threading
import uuid
import json
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from .logging_service import log_event
from .db import sqlalchemy_url_from_env, create_engine_lazy

import joblib
from sklearn.ensemble import IsolationForest, RandomForestClassifier, GradientBoostingClassifier, ExtraTreesClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.neighbors import LocalOutlierFactor
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from sklearn.exceptions import NotFittedError
from sklearn.svm import OneClassSVM
from sklearn.neighbors import LocalOutlierFactor
from .policy_eval import evaluate_rules
try:
    from xgboost import XGBClassifier
    _HAS_XGBOOST = True
except Exception:
    XGBClassifier = None
    _HAS_XGBOOST = False

# Simple in-memory job registry to track background training jobs
_TRAIN_JOBS: Dict[str, Dict[str, Any]] = {}

# Last generated dataset path (set by synth generator)
_LAST_DATASET_PATH: Optional[str] = None


def set_last_dataset_path(path: str) -> None:
    global _LAST_DATASET_PATH
    _LAST_DATASET_PATH = path


def _count_csv_rows(path: str) -> int:
    c = 0
    with open(path, newline='') as f:
        r = csv.reader(f)
        # count excluding header
        try:
            next(r)
        except StopIteration:
            return 0
        for _ in r:
            c += 1
    return c


def _load_amounts(path: str, max_rows: Optional[int] = None) -> List[float]:
    amounts: List[float] = []
    with open(path, newline='') as f:
        r = csv.DictReader(f)
        for i, row in enumerate(r):
            try:
                amounts.append(float(row.get('amount', 0.0)))
            except Exception:
                continue
            if max_rows is not None and i + 1 >= max_rows:
                break
    return amounts


def _persist_model(model: Any, job_id: str) -> str:
    out_dir = Path('data') / 'models'
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / f'model_{job_id}.pkl'
    joblib.dump(model, str(model_path))
    # write metadata
    meta = {'job_id': job_id, 'saved_at': time.time()}
    (out_dir / f'model_{job_id}.json').write_text(json.dumps(meta))
    return str(model_path)


def _has_label_column(path: str) -> bool:
    try:
        with open(path, newline='') as f:
            r = csv.reader(f)
            header = next(r)
            cols = [c.strip().lower() for c in header]
            for candidate in ('label', 'target', 'y', 'is_fraud', 'fraud', 'class'):
                if candidate in cols:
                    return True
    except Exception:
        return False
    return False


def _load_features_and_labels(path: str, max_rows: Optional[int] = None) -> Tuple[List[List[float]], List[int]]:
    X: List[List[float]] = []
    y: List[int] = []
    with open(path, newline='') as f:
        r = csv.DictReader(f)
        for i, row in enumerate(r):
            try:
                amt = float(row.get('amount', 0.0))
            except Exception:
                amt = 0.0
            X.append([amt])
            # try common label fields
            label = None
            for candidate in ('label', 'target', 'y', 'is_fraud', 'fraud', 'class'):
                if candidate in row and row[candidate] is not None:
                    try:
                        label = int(float(row[candidate]))
                    except Exception:
                        try:
                            label = 1 if str(row[candidate]).lower() in ('1','true','yes') else 0
                        except Exception:
                            label = 0
                    break
            y.append(label if label is not None else 0)
            if max_rows is not None and i + 1 >= max_rows:
                break
    return X, y


def start_training_job(
    algo: str,
    max_rows: Optional[int] = None,
    dataset_path: Optional[str] = None,
    db_query: Optional[dict] = None,
    include_policy_features: bool = False,
    rules_json: Optional[dict] = None,
) -> str:
    """Start a background training job. Returns job_id."""
    job_id = uuid.uuid4().hex
    _TRAIN_JOBS[job_id] = {'status': 'pending', 'progress': 0, 'result': None, 'error': None, 'model_path': None}

    def _run():
        try:
            _TRAIN_JOBS[job_id]['status'] = 'running'
            _TRAIN_JOBS[job_id]['progress'] = 1
            # determine dataset
            # If caller provided an explicit dataset_path, prefer it and record
            global _LAST_DATASET_PATH
            if dataset_path:
                _LAST_DATASET_PATH = dataset_path
            # If dataset_path provided -> load CSV
            path = _LAST_DATASET_PATH
            use_db = False
            db_rows = None
            if db_query and not dataset_path:
                use_db = True
            if not path and not use_db:
                from .synth_gen import generate_synth
                path, _ = generate_synth(rows=1000, seed=123)
            # count rows and validate (only if path is available)
            total_rows = 0
            if path and Path(path).exists():
                try:
                    total_rows = _count_csv_rows(path)
                except Exception:
                    total_rows = 0
            _TRAIN_JOBS[job_id]['progress'] = 5
            # Only validate max_rows against CSV total when we are not training from DB
            if not use_db and max_rows is not None and max_rows > total_rows:
                raise ValueError(f"max_rows {max_rows} exceeds available rows {total_rows}")
            # load data (features and labels if present)
            _TRAIN_JOBS[job_id]['progress'] = 10
            # If training from DB, page through query_transactions
            if use_db:
                from .db import query_transactions

                page = 0
                page_size = 1000
                collected: List[dict] = []
                while True:
                    qparams = dict(db_query)
                    qparams['page'] = page
                    qparams['page_size'] = page_size
                    res = query_transactions(**qparams)
                    items = res.get('items', [])
                    for it in items:
                        collected.append(it)
                        if max_rows is not None and len(collected) >= int(max_rows):
                            break
                    total = res.get('total', 0)
                    if max_rows is not None and len(collected) >= int(max_rows):
                        break
                    if (page + 1) * page_size >= total:
                        break
                    page += 1

                db_rows = collected
                # Build X,y from rows
                if not db_rows:
                    # If DB query returned nothing, fall back to CSV dataset if available
                    if path and Path(path).exists() and _count_csv_rows(path) > 0:
                        # switch to CSV path-based training
                        use_db = False
                    else:
                        raise ValueError('no rows returned from DB for training')
                # check for labels
                has_labels = any(('label' in r or 'is_fraud' in r or 'target' in r) for r in db_rows)
                if has_labels:
                    X = [[float(r.get('amount') or 0.0)] for r in db_rows]
                    y = [int(float(r.get('label') or r.get('is_fraud') or r.get('target') or 0)) for r in db_rows]
                else:
                    X = [[float(r.get('amount') or 0.0)] for r in db_rows]
                    y = None
            else:
                has_labels = _has_label_column(path)
                if has_labels:
                    X, y = _load_features_and_labels(path, max_rows=max_rows)
                else:
                    amounts = _load_amounts(path, max_rows=max_rows)
                    X = [[a] for a in amounts]
                    y = None
            _TRAIN_JOBS[job_id]['progress'] = 30
            if not X or len(X) == 0:
                raise ValueError('no data found in dataset')

            # Optionally incorporate policy-derived features (POC): add a rule_count feature
            if include_policy_features and rules_json:
                # If training from DB we have db_rows; otherwise try to load rows from CSV
                rows_for_policy = None
                if db_rows is not None:
                    rows_for_policy = db_rows
                elif path and Path(path).exists():
                    # load CSV rows
                    rows_for_policy = []
                    with open(path, newline='') as f:
                        r = csv.DictReader(f)
                        for row in r:
                            rows_for_policy.append(row)
                if rows_for_policy is not None:
                    # Compute rule_count per row and append as feature
                    rule_counts = []
                    for row in rows_for_policy[: len(X)]:
                        try:
                            violated = evaluate_rules(row, rules_json)
                            rule_counts.append(len(violated))
                        except Exception:
                            rule_counts.append(0)
                    # Append rule_count to each sample feature vector
                    for idx in range(len(X)):
                        cnt = rule_counts[idx] if idx < len(rule_counts) else 0
                        X[idx].append(cnt)

            # scale features for algorithms that benefit
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)

            start_ts = time.time()
            model = None
            algo_used = algo

            # Map algo id to estimator. For supervised algos require labels.
            if algo == 'isolation_forest':
                model = IsolationForest(n_estimators=100, contamination='auto', random_state=42)
                model.fit(X_scaled)
            elif algo == 'local_outlier_factor':
                # use LOF in novelty mode to allow scoring of new samples
                lof = LocalOutlierFactor(n_neighbors=20, novelty=True)
                lof.fit(X_scaled)
                model = lof
            elif algo == 'one_class_svm':
                ocsvm = OneClassSVM(gamma='auto')
                ocsvm.fit(X_scaled)
                model = ocsvm
            elif algo == 'knn':
                # use LocalOutlierFactor as a KNN-based detector
                knn_lof = LocalOutlierFactor(n_neighbors=5, novelty=True)
                knn_lof.fit(X_scaled)
                model = knn_lof
            elif algo in ('random_forest', 'gradient_boosting', 'logistic_regression', 'sgd_classifier', 'decision_tree', 'extra_trees', 'xgboost'):
                # supervised algorithms require labels in dataset
                if y is None:
                    raise ValueError(f"supervised algorithm '{algo}' requires labeled dataset")
                if algo == 'random_forest':
                    clf = RandomForestClassifier(n_estimators=100, random_state=42)
                elif algo == 'gradient_boosting':
                    clf = GradientBoostingClassifier(n_estimators=100, random_state=42)
                elif algo == 'logistic_regression':
                    clf = LogisticRegression(max_iter=1000)
                elif algo == 'sgd_classifier':
                    clf = SGDClassifier(max_iter=1000)
                elif algo == 'decision_tree':
                    clf = DecisionTreeClassifier()
                elif algo == 'extra_trees':
                    clf = ExtraTreesClassifier(n_estimators=100, random_state=42)
                elif algo == 'xgboost':
                    if not _HAS_XGBOOST:
                        raise ValueError('xgboost not available on server')
                    clf = XGBClassifier(use_label_encoder=False, eval_metric='logloss')
                else:
                    raise ValueError(f'unknown supervised algo: {algo}')
                clf.fit(X_scaled, y)
                model = clf
            else:
                # default to isolation forest if unknown id
                model = IsolationForest(n_estimators=100, contamination='auto', random_state=42)
                model.fit(X_scaled)

            fit_seconds = time.time() - start_ts

            _TRAIN_JOBS[job_id]['progress'] = 80
            # Save model + scaler and metadata
            model_path = _persist_model({'model': model, 'scaler': scaler, 'rules_json': rules_json if include_policy_features else None}, job_id)
            _TRAIN_JOBS[job_id]['progress'] = 95
            # Insert metadata into ht_Models if DB available
            model_id = None
            try:
                url = sqlalchemy_url_from_env()
                if url:
                    engine = create_engine_lazy(url)
                    with engine.begin() as conn:
                        metrics = {'rows': len(X), 'fit_seconds': fit_seconds, 'features': ['amount']}
                        conn.exec_driver_sql(
                            "INSERT INTO dbo.ht_Models (algo, created_at, metrics_json) VALUES (?, SYSUTCDATETIME(), ?)",
                            (algo_used, json.dumps(metrics)),
                        )
                        r = conn.exec_driver_sql("SELECT CAST(SCOPE_IDENTITY() AS INT)")
                        row = r.fetchone()
                        if row:
                            model_id = int(row[0])
            except Exception:
                # Non-fatal: if DB insert fails, just continue and return file-based model_path
                try:
                    log_event('model_metadata_insert_failed', {'job_id': job_id})
                except Exception:
                    pass

            res = {'algo': algo_used, 'fit_seconds': fit_seconds, 'features': ['amount'], 'rows': len(X), 'model_path': model_path, 'model_id': model_id}
            _TRAIN_JOBS[job_id]['status'] = 'done'
            _TRAIN_JOBS[job_id]['progress'] = 100
            _TRAIN_JOBS[job_id]['result'] = res
        except Exception as e:
            _TRAIN_JOBS[job_id]['status'] = 'failed'
            _TRAIN_JOBS[job_id]['error'] = str(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return job_id


def get_job_status(job_id: str) -> Dict[str, Any]:
    return _TRAIN_JOBS.get(job_id, {'status': 'not_found'})


def load_model_by_job(job_id: str):
    info = _TRAIN_JOBS.get(job_id)
    if not info or not info.get('model_path'):
        return None
    try:
        return joblib.load(info['model_path'])
    except Exception:
        return None


def predict_transaction_with_model(model: Any, txn: Dict[str, Any]) -> float:
    # simple featurization: amount only
    amt = float(txn.get('amount', 0.0))
    X = [[amt]]
    # IsolationForest.decision_function returns anomaly score: higher is less anomalous
    try:
        score = float(model.decision_function(X)[0])
    except Exception:
        score = 0.0
    return score


def get_model() -> tuple[Optional[Dict[str, float]], List[str]]:
    """Compatibility shim for older scorer code.

    Returns (model_dict_or_none, features_list). Old code expects a dict with
    'mean' and 'std' if available; return None so scorer computes mean/std from data.
    """
    return None, []

