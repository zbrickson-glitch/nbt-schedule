from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from app.db import get_db
from app.services.ical import generate_ical_feed

router = APIRouter()


@router.get("/cal/{token}.ics")
def get_ical_feed(token: str):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM subscribers WHERE token = %s AND active = TRUE", (token,))
        sub = cur.fetchone()
        if not sub:
            raise HTTPException(404, "Feed not found")

        cur.execute(
            """SELECT date, time_start, time_end, studio, show, cast_type, notes
               FROM schedule_events
               WHERE event_type = 'rehearsal'
               ORDER BY date, time_start""",
        )
        events_raw = cur.fetchall()

    events = [
        {
            "date": e["date"],
            "time_start": e["time_start"],
            "time_end": e["time_end"],
            "studio": e["studio"],
            "show": e["show"],
            "cast_type": e["cast_type"] or "",
            "notes": e["notes"] or "",
        }
        for e in events_raw
    ]

    feed = generate_ical_feed(sub["dancer_name"], sub["shows"] or [], events)
    return PlainTextResponse(content=feed, media_type="text/calendar; charset=utf-8")
