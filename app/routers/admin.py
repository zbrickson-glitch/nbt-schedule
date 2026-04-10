from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Optional
from app.db import get_db

router = APIRouter(prefix="/admin", tags=["admin"])

static_dir = Path(__file__).parent.parent / "static"


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
def admin_page():
    """Serve the admin HTML page."""
    return FileResponse(str(static_dir / "admin.html"))


@router.get("/events")
def list_events(date_from: Optional[str] = None, date_to: Optional[str] = None):
    """List all schedule events for a date range."""
    with get_db() as conn:
        cur = conn.cursor()
        if date_from and date_to:
            cur.execute(
                """SELECT id, date, time_start, time_end, studio, show, staff,
                          cast_type, notes, event_type, fitting_dancer, is_revised,
                          source_email_id, created_at
                   FROM schedule_events
                   WHERE date >= %s AND date <= %s
                   ORDER BY date, time_start""",
                (date_from, date_to),
            )
        elif date_from:
            cur.execute(
                """SELECT id, date, time_start, time_end, studio, show, staff,
                          cast_type, notes, event_type, fitting_dancer, is_revised,
                          source_email_id, created_at
                   FROM schedule_events
                   WHERE date >= %s
                   ORDER BY date, time_start""",
                (date_from,),
            )
        else:
            cur.execute(
                """SELECT id, date, time_start, time_end, studio, show, staff,
                          cast_type, notes, event_type, fitting_dancer, is_revised,
                          source_email_id, created_at
                   FROM schedule_events
                   ORDER BY date DESC, time_start
                   LIMIT 200"""
            )
        rows = cur.fetchall()
        result = []
        for r in rows:
            row = dict(r)
            if row["date"]:
                row["date"] = str(row["date"])
            if row["time_start"]:
                row["time_start"] = str(row["time_start"])[:5]  # HH:MM
            if row["time_end"]:
                row["time_end"] = str(row["time_end"])[:5]  # HH:MM
            if row["created_at"]:
                row["created_at"] = str(row["created_at"])
            result.append(row)
        return result


@router.get("/events/date/{date}")
def get_events_for_date(date: str):
    """Get all events for a specific date."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, date, time_start, time_end, studio, show, staff,
                      cast_type, notes, event_type, fitting_dancer, is_revised,
                      source_email_id, created_at
               FROM schedule_events
               WHERE date = %s
               ORDER BY time_start""",
            (date,),
        )
        rows = cur.fetchall()
        result = []
        for r in rows:
            row = dict(r)
            if row["date"]:
                row["date"] = str(row["date"])
            if row["time_start"]:
                row["time_start"] = str(row["time_start"])[:5]
            if row["time_end"]:
                row["time_end"] = str(row["time_end"])[:5]
            if row["created_at"]:
                row["created_at"] = str(row["created_at"])
            result.append(row)
        return result


@router.post("/events")
def create_event(body: dict):
    """Create a new manual schedule event."""
    date = body.get("date")
    if not date:
        raise HTTPException(400, "date is required")

    time_start = body.get("time_start") or None
    time_end = body.get("time_end") or None
    studio = body.get("studio") or "1"
    show = body.get("show") or None
    staff = body.get("staff") or None
    cast_type = body.get("cast_type") or None
    notes = body.get("notes") or None
    event_type = body.get("event_type") or "rehearsal"
    fitting_dancer = body.get("fitting_dancer") or None
    is_revised = bool(body.get("is_revised", False))

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO schedule_events
               (date, time_start, time_end, studio, show, staff, cast_type,
                notes, event_type, fitting_dancer, is_revised, source_email_id, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'manual', NOW())
               RETURNING id""",
            (date, time_start, time_end, studio, show, staff, cast_type,
             notes, event_type, fitting_dancer, is_revised),
        )
        row = cur.fetchone()
    return {"id": row["id"], "status": "created"}


@router.put("/events/{event_id}")
def update_event(event_id: int, body: dict):
    """Update an existing schedule event."""
    with get_db() as conn:
        cur = conn.cursor()
        # Check it exists
        cur.execute("SELECT id FROM schedule_events WHERE id = %s", (event_id,))
        if not cur.fetchone():
            raise HTTPException(404, f"Event {event_id} not found")

        time_start = body.get("time_start") or None
        time_end = body.get("time_end") or None
        studio = body.get("studio") or "1"
        show = body.get("show") or None
        staff = body.get("staff") or None
        cast_type = body.get("cast_type") or None
        notes = body.get("notes") or None
        event_type = body.get("event_type") or "rehearsal"
        fitting_dancer = body.get("fitting_dancer") or None
        is_revised = bool(body.get("is_revised", False))
        date = body.get("date")

        if not date:
            raise HTTPException(400, "date is required")

        cur.execute(
            """UPDATE schedule_events
               SET date = %s,
                   time_start = %s,
                   time_end = %s,
                   studio = %s,
                   show = %s,
                   staff = %s,
                   cast_type = %s,
                   notes = %s,
                   event_type = %s,
                   fitting_dancer = %s,
                   is_revised = %s,
                   source_email_id = 'manual',
                   created_at = NOW()
               WHERE id = %s""",
            (date, time_start, time_end, studio, show, staff, cast_type,
             notes, event_type, fitting_dancer, is_revised, event_id),
        )
    return {"id": event_id, "status": "updated"}


@router.delete("/events/{event_id}")
def delete_event(event_id: int):
    """Delete a schedule event."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM schedule_events WHERE id = %s", (event_id,))
        if not cur.fetchone():
            raise HTTPException(404, f"Event {event_id} not found")
        cur.execute("DELETE FROM schedule_events WHERE id = %s", (event_id,))
    return {"id": event_id, "status": "deleted"}
