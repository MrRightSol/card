from fastapi import APIRouter, Query
from ..services.logging_service import list_events

router = APIRouter()


@router.get("/logs")
def get_logs(limit: int = Query(100, ge=1, le=1000)):
    return list_events(limit=limit)
