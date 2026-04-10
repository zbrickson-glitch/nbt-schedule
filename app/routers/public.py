from fastapi import APIRouter
from app.db import get_db
from app.config import settings

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/schedule/date/{event_date}")
def public_schedule_for_date(event_date: str):
    """Read-only schedule events for a specific date.
    Returns events from the most recently ingested email only (deduplicates
    original vs. revised schedule emails for the same date)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, date, time_start, time_end, studio, show, staff,
                      cast_type, notes, event_type, fitting_dancer, is_revised
               FROM schedule_events
               WHERE date = %s
                 AND source_email_id = (
                   SELECT source_email_id
                   FROM schedule_events
                   WHERE date = %s
                   GROUP BY source_email_id
                   ORDER BY max(created_at) DESC
                   LIMIT 1
                 )
               ORDER BY time_start""",
            (event_date, event_date),
        )
        rows = cur.fetchall()
        for r in rows:
            if r["date"]:
                r["date"] = str(r["date"])
            if r["time_start"]:
                r["time_start"] = str(r["time_start"])
            if r["time_end"]:
                r["time_end"] = str(r["time_end"])
        return rows


@router.get("/casting")
def public_casting():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT dancer_name, show, section, role, cover_for
               FROM casting ORDER BY show, section, role, dancer_name"""
        )
        return list(cur.fetchall())


@router.get("/casting/shows")
def public_casting_shows():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT show FROM casting ORDER BY show")
        return [r["show"] for r in cur.fetchall()]


@router.get("/season")
def public_season():
    import json
    from pathlib import Path

    config_path = Path("/app/season/season.json")
    if not config_path.exists():
        return {"season": "", "weeks": []}
    return json.loads(config_path.read_text())


@router.post("/subscribe")
def public_subscribe(body: dict):
    """Create a subscriber and return their iCal URL."""
    import secrets
    dancer_name = body.get("dancer_name", "").strip()
    if not dancer_name:
        from fastapi import HTTPException
        raise HTTPException(400, "dancer_name is required")
    shows = body.get("shows", [])
    token = secrets.token_urlsafe(32)
    with get_db() as conn:
        cur = conn.cursor()
        # Check if already subscribed
        cur.execute("SELECT token FROM subscribers WHERE dancer_name = %s AND active = TRUE", (dancer_name,))
        existing = cur.fetchone()
        if existing:
            return {"token": existing["token"], "ical_url": f"/cal/{existing['token']}.ics"}
        cur.execute(
            "INSERT INTO roster (full_name) VALUES (%s) ON CONFLICT (full_name) DO NOTHING",
            (dancer_name,)
        )
        cur.execute(
            """INSERT INTO subscribers (dancer_name, token, shows)
               VALUES (%s, %s, %s) RETURNING token""",
            (dancer_name, token, shows)
        )
        row = cur.fetchone()
    return {"token": row["token"], "ical_url": f"/cal/{row['token']}.ics"}


@router.get("/subscribe/shows")
def public_subscribe_shows():
    """Get list of shows available for calendar subscription."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT show FROM casting ORDER BY show")
        return [r["show"] for r in cur.fetchall()]


@router.post("/feedback")
def public_feedback(body: dict):
    """Store user feedback/suggestions and forward to Discord #capture."""
    import urllib.request
    import json as json_mod

    message = (body.get("message") or "").strip()
    if not message or len(message) > 500:
        from fastapi import HTTPException
        raise HTTPException(400, "message is required (max 500 chars)")

    # Store in DB
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """CREATE TABLE IF NOT EXISTS feedback (
                id SERIAL PRIMARY KEY,
                message TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )"""
        )
        cur.execute("INSERT INTO feedback (message) VALUES (%s)", (message,))

    # Forward to Discord #capture via webhook
    try:
        webhook_url = settings.discord_webhook_url
        if not webhook_url:
            raise ValueError("NBT_DISCORD_WEBHOOK_URL not configured")
        payload = json_mod.dumps({
            "content": f"**Schedule Suggestion** (from schedule.naenaewhipwhip.com):\n> {message}"
        }).encode()
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "NBT-Schedule-Service/1.0",
            },
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # Don't fail the user request if Discord forwarding fails

    return {"status": "ok"}


@router.get("/calendar.ics")
def public_full_calendar():
    """Full schedule as iCal feed (no filtering)."""
    from fastapi.responses import PlainTextResponse
    from icalendar import Calendar, Event
    from datetime import datetime, time as time_type
    from zoneinfo import ZoneInfo

    PACIFIC = ZoneInfo("America/Los_Angeles")

    with get_db() as conn:
        cur = conn.cursor()
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

    cal = Calendar()
    cal.add('prodid', '-//NBT Schedule Service//nbt.schedule//EN')
    cal.add('version', '2.0')
    cal.add('method', 'PUBLISH')
    cal.add('x-wr-calname', 'NBT Full Schedule')

    for ev in events:
        event = Event()
        ev_date = ev["date"]
        start_dt = datetime.combine(ev_date, ev["time_start"], tzinfo=PACIFIC)
        end_time = ev["time_end"] if ev["time_end"] is not None else (
            time_type((ev["time_start"].hour + 1) % 24, ev["time_start"].minute)
        )
        end_dt = datetime.combine(ev_date, end_time, tzinfo=PACIFIC)
        show = ev["show"]
        uid = (
            f"nbt-{ev_date.isoformat()}"
            f"-{ev['time_start'].strftime('%H%M')}"
            f"-{show.upper().replace(' ', '-').replace('/', '-')}"
            f"@nbt.schedule"
        )
        event.add('uid', uid)
        event.add('dtstart', start_dt)
        event.add('dtend', end_dt)
        event.add('summary', show)
        studio = ev.get("studio", "")
        event.add('location', f'Studio {studio}' if studio else 'NBT')
        desc_parts = []
        cast_type = (ev.get("cast_type") or "").strip()
        if cast_type:
            desc_parts.append(f"Cast: {cast_type}")
        notes = ev.get("notes", "")
        if notes:
            desc_parts.append(f"Notes: {notes}")
        if desc_parts:
            event.add('description', '\n'.join(desc_parts))
        event.add('sequence', 1)
        cal.add_component(event)

    feed = cal.to_ical().decode('utf-8')
    return PlainTextResponse(content=feed, media_type="text/calendar; charset=utf-8")
