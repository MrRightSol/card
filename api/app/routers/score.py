from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any
from ..services.scorer import score_dataset

router = APIRouter()


class ScoreBody(BaseModel):
    dataset_path: str | None = None
    db_query: dict | None = None
    rules_json: dict | None = None


@router.post("/score")
def score_endpoint(body: ScoreBody) -> Any:
    # Support scoring from either a CSV dataset_path or from DB query params
    if body.dataset_path:
        return score_dataset(dataset_path=body.dataset_path, rules_json=body.rules_json)
    if body.db_query:
        # Import here to avoid circulars; scorer supports db_query param
        return score_dataset(db_query=body.db_query, rules_json=body.rules_json)
    raise RuntimeError('score requires either dataset_path or db_query')
