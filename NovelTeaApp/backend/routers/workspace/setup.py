"""First-run setup: where the corpus folder lives."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import set_corpus_path

router = APIRouter()


class CorpusPathRequest(BaseModel):
    path: str


@router.post("/corpus-path")
def update_corpus_path(req: CorpusPathRequest):
    """Update the path to the NovelTea Engine corpus directory."""
    p = Path(req.path)
    if not str(req.path).strip():
        raise HTTPException(400, "Enter a folder path.")
    try:
        set_corpus_path(str(p))          # creates the folder (and raw/ novels/ projects/ generated/ + the pipeline scripts) if needed
    except OSError as e:
        raise HTTPException(400, f"Cannot use that folder: {e}")
    return {"success": True, "path": str(p), "restart_required": True}
