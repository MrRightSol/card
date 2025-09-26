from fastapi import APIRouter
from pydantic import BaseModel, Field
from ..services.synth_gen import generate_synth

router = APIRouter()


class GenerateSynthBody(BaseModel):
    rows: int = Field(..., ge=1)
    seed: int | None = None


@router.post("/generate-synth")
def generate_synth_endpoint(body: GenerateSynthBody):
    path, preview = generate_synth(rows=body.rows, seed=body.seed)
    return {"path": path, "preview": preview}
