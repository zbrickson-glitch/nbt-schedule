import json
import logging
import os
import tempfile
import base64
from datetime import date
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

import requests

from app.parsers.classifier import classify_pdf, classify_email, PdfType, EmailType
from app.parsers.schedule import parse_schedule_pdf
from app.parsers.casting import parse_casting_pdf
from app.services.ical import generate_ical_feed
from app.db import get_db
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


def get_gcal_calendar_id() -> str:
    """Return the Google Calendar ID for schedule events, if configured."""
    return os.environ.get("NBT_GCAL_CALENDAR_ID", "")


def send_unknown_format_alert(filename: str, email_id: str, method: Optional[str] = None) -> None:
    """Send an alert when a PDF has an unknown/unsupported format."""
    message = (
        f"[NBT Schedule] Unknown PDF format: `{filename}` "
        f"(email_id={email_id})"
    )
    if method:
        message += f" — extracted via {method}"
    else:
        message += " — no events extracted"

    if settings.mm_webhook_url:
        try:
            requests.post(
                settings.mm_webhook_url,
                json={"text": message},
                timeout=5,
            )
        except Exception as exc:
            logger.warning("Failed to send Mattermost alert: %s", exc)

    logger.warning("Unknown format alert: %s", message)


class AttachmentPayload(BaseModel):
    filename: str
    data: str  # base64-encoded PDF bytes


class IngestPayload(BaseModel):
    email_id: str
    subject: str
    body: str = ""
    attachments: list[AttachmentPayload] = []
    is_revised: bool = False  # can be set explicitly, also detected from subject


class IngestResult(BaseModel):
    status: str
    email_id: str
    skipped: bool = False
    casting_processed: list[str] = []
    schedules_processed: list[str] = []
    events_created: int = 0
    unknown_pdfs: list[str] = []


@router.post("/api/ingest", response_model=IngestResult)
def ingest_email(payload: IngestPayload):
    # 1. Idempotency check — skip if already processed
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM schedule_events WHERE source_email_id = %s LIMIT 1",
            (payload.email_id,)
        )
        if cur.fetchone():
            return IngestResult(status="skipped", email_id=payload.email_id, skipped=True)

    # Detect revision from subject
    is_revised = payload.is_revised or "revised" in payload.subject.lower()

    # 2. Classify attachments
    casting_attachments = []
    schedule_attachments = []
    unknown_attachments = []
    for att in payload.attachments:
        pdf_type = classify_pdf(att.filename)
        if pdf_type == PdfType.CASTING:
            casting_attachments.append(att)
        elif pdf_type == PdfType.SCHEDULE:
            schedule_attachments.append(att)
        elif pdf_type in (PdfType.UNKNOWN, PdfType.MAAG):
            unknown_attachments.append(att)

    # Handle body-text-only emails (no attachments)
    if not payload.attachments:
        email_type = classify_email(payload.subject, payload.body, [])
        if email_type == EmailType.CANCELLATION:
            _store_body_text_event(payload, "cancellation")
            send_unknown_format_alert(
                filename="(body text)",
                email_id=payload.email_id,
                method=f"body-text:{payload.subject}",
            )
            return IngestResult(status="cancellation_logged", email_id=payload.email_id)
        if email_type == EmailType.EMERGENCY:
            _store_body_text_event(payload, "emergency")
            send_unknown_format_alert(
                filename="(body text)",
                email_id=payload.email_id,
                method=f"body-text:{payload.subject}",
            )
            return IngestResult(status="emergency_logged", email_id=payload.email_id)
        if email_type == EmailType.ADDITIONAL_DETAIL:
            _store_body_text_event(payload, "additional_detail")
            send_unknown_format_alert(
                filename="(body text)",
                email_id=payload.email_id,
                method=f"body-text:{payload.subject}",
            )
            return IngestResult(status="additional_detail_logged", email_id=payload.email_id)
        if email_type == EmailType.CAST_CHANGE:
            # Store for Madge to process
            _store_cast_change(payload)
            return IngestResult(status="cast_change_queued", email_id=payload.email_id)

    result = IngestResult(status="ok", email_id=payload.email_id)

    # PHASE 1: Process casting PDFs FIRST
    for att in casting_attachments:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(base64.b64decode(att.data))
            tmp_path = f.name
        try:
            parsed = parse_casting_pdf(tmp_path)
            _upsert_casting(parsed, payload.email_id)
            result.casting_processed.append(parsed.show)
        finally:
            os.unlink(tmp_path)

    # PHASE 2: Process schedule PDFs
    for att in schedule_attachments:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(base64.b64decode(att.data))
            tmp_path = f.name
        try:
            # Deterministic parser (Pipeline A)
            try:
                parsed_a = parse_schedule_pdf(tmp_path)
            except ValueError as ve:
                # PDF could not be parsed (e.g., MAAG, multi-date, or unsupported format)
                # Log and skip gracefully rather than returning 500
                logger.warning(
                    "Skipping unparseable schedule PDF '%s': %s", att.filename, ve
                )
                continue

            # Check for existing events on this date (revision handling)
            event_date = parsed_a.date
            if is_revised or _has_events_for_date(event_date):
                _archive_and_delete_events(event_date, payload.email_id)

            # Store events from pdfplumber parser
            count = _store_schedule_events(parsed_a, payload.email_id, att.filename, is_revised)

            result.schedules_processed.append(event_date.isoformat())
            result.events_created += count
        finally:
            os.unlink(tmp_path)

    # PHASE 2.5: Unknown/MAAG PDF fallback pipeline
    # For PDFs that couldn't be classified, try the deterministic parser.
    # Always fire an alert regardless of extraction outcome.
    for att in unknown_attachments:
        result.unknown_pdfs.append(att.filename)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(base64.b64decode(att.data))
            tmp_path = f.name

        method_used: Optional[str] = None

        try:
            try:
                parsed_a = parse_schedule_pdf(tmp_path)
                if parsed_a and parsed_a.events:
                    event_date = parsed_a.date
                    if is_revised or _has_events_for_date(event_date):
                        _archive_and_delete_events(event_date, payload.email_id)
                    events_stored = _store_schedule_events(
                        parsed_a, payload.email_id, att.filename, is_revised
                    )
                    result.schedules_processed.append(event_date.isoformat())
                    result.events_created += events_stored
                    method_used = "deterministic_on_unknown"
            except Exception as det_err:
                logger.warning(
                    "Deterministic parser failed on unknown PDF '%s': %s",
                    att.filename, det_err,
                )
        finally:
            os.unlink(tmp_path)

        # Always alert about unknown format (success or failure)
        send_unknown_format_alert(att.filename, payload.email_id, method=method_used)

    # PHASE 3: Regenerate .ics feeds if any schedules processed
    if result.schedules_processed:
        _regenerate_all_feeds()

    return result


def _has_events_for_date(event_date: date) -> bool:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM schedule_events WHERE date = %s LIMIT 1", (event_date,))
        return cur.fetchone() is not None


def _archive_and_delete_events(event_date: date, new_email_id: str):
    """Snapshot existing events to history then delete them (for revision handling)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT json_agg(row_to_json(e)) FROM schedule_events e WHERE date = %s",
            (event_date,)
        )
        row = cur.fetchone()
        old_events = row["json_agg"] if row else None

        cur.execute(
            """INSERT INTO schedule_history (date, old_events, new_email_id, reason)
               VALUES (%s, %s, %s, 'revised')""",
            (event_date, json.dumps(old_events), new_email_id)
        )
        cur.execute("DELETE FROM schedule_events WHERE date = %s", (event_date,))


def _upsert_casting(parsed, email_id: str):
    """Upsert casting data from a parsed Role Responsibilities PDF."""
    with get_db() as conn:
        cur = conn.cursor()
        show = parsed.show.upper().replace("ZIGZAG", "ZIGZAG").strip()

        for section in parsed.sections:
            for dancer in section.dancers:
                # Ensure dancer is in roster
                cur.execute(
                    "INSERT INTO roster (full_name) VALUES (%s) ON CONFLICT (full_name) DO NOTHING",
                    (dancer.name,)
                )
                cur.execute(
                    """INSERT INTO casting (dancer_name, show, section, role, cover_for, source_email_id)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (dancer_name, show, section, role)
                       DO UPDATE SET cover_for = EXCLUDED.cover_for,
                                     source_email_id = EXCLUDED.source_email_id,
                                     updated_at = NOW()""",
                    (dancer.name, show, section.name, dancer.role, dancer.cover_for, email_id)
                )


def _store_schedule_events(parsed, email_id: str, filename: str, is_revised: bool) -> int:
    count = 0
    with get_db() as conn:
        cur = conn.cursor()
        for ev in parsed.events:
            cur.execute(
                """INSERT INTO schedule_events
                   (date, time_start, time_end, studio, show, staff, cast_type, notes,
                    event_type, source_email_id, source_filename, is_revised,
                    parser_a_json)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (parsed.date, ev.time_start, ev.time_end, ev.studio, ev.show,
                 ev.staff, ev.cast_type, ev.notes, ev.event_type,
                 email_id, filename, is_revised,
                 json.dumps({
                     "time_start": str(ev.time_start),
                     "time_end": ev.time_end.strftime("%H:%M") if ev.time_end else None,
                     "show": ev.show,
                 }))
            )
            count += 1
        for fit in parsed.fittings:
            cur.execute(
                """INSERT INTO schedule_events
                   (date, time_start, time_end, studio, show, staff, cast_type, notes,
                    event_type, fitting_dancer, source_email_id, source_filename, is_revised)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (parsed.date, fit.time_start, fit.time_end, fit.where, fit.show,
                 fit.staff, fit.dancer, fit.notes, 'fitting',
                 fit.dancer, email_id, filename, is_revised)
            )
            count += 1
    return count



def _store_body_text_event(payload, reason: str):
    """Store a body-text-only email in schedule_history for manual review."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO schedule_history (date, old_events, new_email_id, reason)
               VALUES (CURRENT_DATE, %s, %s, %s)""",
            (json.dumps({"subject": payload.subject, "body": payload.body}), payload.email_id, reason)
        )


def _store_cast_change(payload):
    """Store free-text cast change for Madge to process."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO schedule_history (date, old_events, new_email_id, reason)
               VALUES (CURRENT_DATE, %s, %s, 'cast_change')""",
            (json.dumps({"subject": payload.subject, "body": payload.body}), payload.email_id)
        )


def _regenerate_all_feeds():
    """Regenerate .ics files for all active subscribers."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM subscribers WHERE active = TRUE")
        subscribers = cur.fetchall()

        cur.execute(
            """SELECT date, time_start, time_end, studio, show, cast_type, notes
               FROM schedule_events
               WHERE event_type = 'rehearsal'
               ORDER BY date, time_start"""
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

    feed_dir = "/tmp/nbt_feeds"
    os.makedirs(feed_dir, exist_ok=True)

    for sub in subscribers:
        feed = generate_ical_feed(sub["dancer_name"], sub["shows"] or [], events)
        with open(f"{feed_dir}/{sub['token']}.ics", "w") as f:
            f.write(feed)
