from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import Optional
import tempfile
import os
from app.db import get_db
from app.parsers.casting import parse_casting_pdf

router = APIRouter()


@router.get("/api/casting")
def list_casting():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM casting ORDER BY show, dancer_name")
        return list(cur.fetchall())


@router.get("/api/casting/show/{show}")
def get_show_dancers(show: str):
    """Get all unique dancer names for a show (for Full Call resolution)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT dancer_name FROM casting WHERE UPPER(show) = UPPER(%s) ORDER BY dancer_name",
            (show,)
        )
        return [r["dancer_name"] for r in cur.fetchall()]


@router.post("/api/casting/import")
async def import_casting_pdf(file: UploadFile = File(...)):
    """Upload a Role Responsibilities PDF to update casting DB."""
    if not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Must be a PDF file")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(await file.read())
        tmp_path = f.name
    try:
        parsed = parse_casting_pdf(tmp_path)
        from app.routers.ingest import _upsert_casting
        _upsert_casting(parsed, f"manual-upload-{file.filename}")
        return {"show": parsed.show, "sections": len(parsed.sections), "dancers": len(parsed.all_dancer_names())}
    finally:
        os.unlink(tmp_path)
