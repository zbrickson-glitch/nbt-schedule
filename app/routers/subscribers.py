from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import secrets
from app.db import get_db

router = APIRouter()


class SubscriberCreate(BaseModel):
    dancer_name: str
    email: Optional[str] = None
    shows: list[str] = []


@router.get("/api/subscribers")
def list_subscribers():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, dancer_name, email, token, shows, active, created_at FROM subscribers")
        return list(cur.fetchall())


@router.post("/api/subscribers")
def create_subscriber(body: SubscriberCreate):
    token = secrets.token_urlsafe(32)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO roster (full_name) VALUES (%s) ON CONFLICT (full_name) DO NOTHING""",
            (body.dancer_name,)
        )
        cur.execute(
            """INSERT INTO subscribers (dancer_name, email, token, shows)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT DO NOTHING
               RETURNING *""",
            (body.dancer_name, body.email, token, body.shows)
        )
        row = cur.fetchone()
    return {"token": token, "ical_url": f"/cal/{token}.ics", **dict(row or {})}


@router.delete("/api/subscribers/{token}")
def delete_subscriber(token: str):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE subscribers SET active = FALSE WHERE token = %s", (token,))
    return {"status": "deactivated"}
