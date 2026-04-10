from fastapi import APIRouter
from app.db import get_db

router = APIRouter()


@router.get("/api/schedule")
def list_schedule():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM schedule_events ORDER BY date, time_start LIMIT 500")
        return list(cur.fetchall())


@router.get("/api/schedule/date/{event_date}")
def get_schedule_for_date(event_date: str):
    with get_db() as conn:
        cur = conn.cursor()
        # Only return events from the most recently ingested email for this date.
        # This ensures revised schedules (which come in later) replace earlier ones.
        cur.execute(
            """SELECT * FROM schedule_events
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
            (event_date, event_date)
        )
        return list(cur.fetchall())


@router.get("/api/compare")
def get_comparison_history():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT date, source_filename, parser_match,
                      parser_a_json, parser_b_json, created_at
               FROM schedule_events
               WHERE parser_match IS NOT NULL
               ORDER BY created_at DESC LIMIT 100"""
        )
        return list(cur.fetchall())
