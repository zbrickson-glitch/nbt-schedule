"""
Unified NBT email pipeline endpoint.
Called by n8n dispatcher for all emails from bwahlquist@nevadaballet.org.
Owns: classification, parsing, atomic DB write, Discord notification.
"""
import base64
import json
import logging
import tempfile
import os
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.db import get_db
from app.parsers.classifier import classify_pdf, classify_email, PdfType, EmailType
from app.parsers.schedule import parse_schedule_pdf
from app.services.discord import post_to_discord

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class AttachmentPayload(BaseModel):
    filename: str
    data: str  # base64-encoded bytes


class EmailPayload(BaseModel):
    message_id: str
    sender: str
    subject: str = ""
    body: str = ""
    attachments: List[AttachmentPayload] = []


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _already_processed(message_id: str) -> bool:
    """Check whether this message_id has already been ingested."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM schedule_events WHERE source_email_id = %s LIMIT 1",
            (message_id,),
        )
        return cur.fetchone() is not None


def _archive_existing_events(message_id: str) -> None:
    """Snapshot any existing events for this email into history, then delete them."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT json_agg(row_to_json(e)) FROM schedule_events e WHERE source_email_id = %s",
            (message_id,),
        )
        row = cur.fetchone()
        old_events = row["json_agg"] if row else None
        if old_events:
            cur.execute(
                """INSERT INTO schedule_history (date, old_events, new_email_id, reason)
                   VALUES (CURRENT_DATE, %s, %s, 'pipeline_reingestion')""",
                (json.dumps(old_events), message_id),
            )
            cur.execute(
                "DELETE FROM schedule_events WHERE source_email_id = %s",
                (message_id,),
            )


def _store_events_atomically(events: list, message_id: str) -> int:
    """Insert parsed events in a single transaction. Returns count stored."""
    with get_db() as conn:
        cur = conn.cursor()
        count = 0
        for ev in events:
            cur.execute(
                """INSERT INTO schedule_events
                   (date, time_start, time_end, studio, show, staff, cast_type,
                    notes, event_type, fitting_dancer, source_email_id, is_revised)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    ev["date"], ev["time_start"], ev["time_end"],
                    ev["studio"], ev["show"], ev["staff"],
                    ev["cast_type"], ev["notes"],
                    ev.get("event_type", "rehearsal"),
                    ev.get("fitting_dancer"),
                    message_id,
                    ev.get("is_revised", False),
                ),
            )
            count += 1
    return count


def _get_zach_calls(message_id: str) -> list:
    """Return events from this email that match Zach's call patterns."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT date, time_start, show, cast_type
               FROM schedule_events
               WHERE source_email_id = %s
                 AND (cast_type ILIKE '%%brickson%%'
                      OR cast_type ILIKE '%%full cast%%'
                      OR cast_type ILIKE '%%full call%%'
                      OR cast_type ILIKE '%%company call%%'
                      OR cast_type ILIKE '%%all cast%%'
                      OR cast_type ILIKE '%%all dancers%%')
               ORDER BY date, time_start""",
            (message_id,),
        )
        return list(cur.fetchall())


# ---------------------------------------------------------------------------
# Discord message formatters
# ---------------------------------------------------------------------------

def _discord_received(payload: EmailPayload, email_type: str) -> str:
    return (
        f"\U0001f4ec **Email from** {payload.sender}\n"
        f"   Subject: {payload.subject}\n"
        f"   Classified: {email_type}"
    )


def _discord_schedule_ok(payload: EmailPayload, count: int,
                          date_range: str, zach_calls: list) -> str:
    lines = [
        f"\u2705 **Schedule parsed** \u2014 {count} events stored",
        f"   Date range: {date_range}",
    ]
    if zach_calls:
        lines.append("   **Your calls:**")
        for c in zach_calls:
            t = str(c["time_start"])[:5] if c["time_start"] else ""
            ct = f" ({c['cast_type']})" if c.get("cast_type") else ""
            lines.append(f"   \u2022 {c['date']} {t} \u2014 {c['show']}{ct}")
    else:
        lines.append("   No personal calls in this schedule.")
    return "\n".join(lines)


def _discord_schedule_error(payload: EmailPayload, errors: list) -> str:
    return (
        f"\u26a0\ufe0f **Schedule parse failed**\n"
        f"   From: {payload.sender}\n"
        f"   Subject: {payload.subject}\n"
        f"   Error: {'; '.join(errors)}"
    )


# ---------------------------------------------------------------------------
# Main route
# ---------------------------------------------------------------------------

@router.post("/nbt")
def pipeline_nbt(payload: EmailPayload):
    """
    Single entry point for all NBT emails from bwahlquist@nevadaballet.org.
    n8n calls this with raw email data. We classify, parse, store, notify.
    """
    webhook = settings.discord_webhook_url

    # 1. Idempotency check
    if _already_processed(payload.message_id):
        logger.info("Skipping already-processed email %s", payload.message_id)
        return {"status": "skipped", "message_id": payload.message_id}

    # 2. Classify email
    attachment_filenames = [a.filename for a in payload.attachments]
    email_type = classify_email(payload.subject, payload.body, attachment_filenames)

    # 3. Post "received" to Discord
    post_to_discord(webhook, _discord_received(payload, email_type.value))

    # 4. No attachments — nothing to parse
    if not payload.attachments:
        post_to_discord(webhook,
            f"\u2139\ufe0f No PDF attachments \u2014 nothing to parse\n"
            f"   From: {payload.sender} | Subject: {payload.subject}"
        )
        return {"status": "no_pdf", "message_id": payload.message_id}

    # 5. Route by email type
    if email_type in (EmailType.SCHEDULE, EmailType.MIXED):
        return _handle_schedule(payload, webhook)
    elif email_type == EmailType.CASTING:
        return _handle_casting(payload, webhook)
    else:
        # Try content-based classification on first attachment
        first = payload.attachments[0]
        pdf_bytes = base64.b64decode(first.data)
        pdf_type = classify_pdf(first.filename, pdf_bytes=pdf_bytes)
        if pdf_type == PdfType.SCHEDULE:
            return _handle_schedule(payload, webhook)
        elif pdf_type == PdfType.CASTING:
            return _handle_casting(payload, webhook)
        else:
            post_to_discord(webhook,
                f"\u26a0\ufe0f **Unknown email format** \u2014 could not classify\n"
                f"   From: {payload.sender}\n"
                f"   Subject: {payload.subject}\n"
                f"   Attachment: {first.filename}"
            )
            return {"status": "unknown_format", "message_id": payload.message_id}


# ---------------------------------------------------------------------------
# Schedule handler
# ---------------------------------------------------------------------------

def _handle_schedule(payload: EmailPayload, webhook: str) -> dict:
    """Parse schedule PDF(s), store atomically, notify Discord."""
    all_events = []
    errors = []

    for att in payload.attachments:
        # Route casting PDFs in a mixed email to the casting handler
        pdf_type = classify_pdf(att.filename)
        if pdf_type == PdfType.CASTING:
            _handle_casting_attachment(att, payload, webhook)
            continue
        if pdf_type == PdfType.MAAG:
            continue  # ignore month-at-a-glance

        try:
            pdf_bytes = base64.b64decode(att.data)
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(pdf_bytes)
                tmp_path = f.name
            try:
                parsed_days = parse_schedule_pdf(tmp_path)
            finally:
                os.unlink(tmp_path)

            # parse_schedule_pdf returns a single ParsedSchedule, not a list
            parsed_days = [parsed_days] if parsed_days else []
            for day in parsed_days:
                for ev in day.events:
                    all_events.append({
                        "date": str(day.date),
                        "time_start": ev.time_start,
                        "time_end": ev.time_end,
                        "studio": ev.studio,
                        "show": ev.show,
                        "staff": ev.staff,
                        "cast_type": ev.cast_type,
                        "notes": ev.notes,
                        "event_type": "rehearsal",
                        "fitting_dancer": None,
                        "is_revised": False,
                    })
                for fv in day.fittings:
                    all_events.append({
                        "date": str(day.date),
                        "time_start": fv.time_start,
                        "time_end": fv.time_end,
                        "studio": fv.where,
                        "show": fv.show,
                        "staff": fv.staff,
                        "cast_type": None,
                        "notes": fv.notes,
                        "event_type": "fitting",
                        "fitting_dancer": fv.dancer,
                        "is_revised": False,
                    })
        except Exception as exc:
            logger.exception("Failed to parse attachment %s", att.filename)
            errors.append(f"{att.filename}: {exc}")

    if not all_events:
        msg = _discord_schedule_error(payload, errors or ["no events extracted"])
        post_to_discord(webhook, msg)
        status = "parse_error" if errors else "no_events"
        return {"status": status, "message_id": payload.message_id, "errors": errors}

    # Atomic store
    count = _store_events_atomically(all_events, payload.message_id)
    zach_calls = _get_zach_calls(payload.message_id)

    dates = sorted(set(e["date"] for e in all_events))
    date_range = f"{dates[0]} \u2013 {dates[-1]}" if dates else "unknown"

    msg = _discord_schedule_ok(payload, count, date_range, zach_calls)
    if errors:
        msg += f"\n\u26a0\ufe0f Partial errors: {'; '.join(errors)}"
    post_to_discord(webhook, msg)

    return {
        "status": "ok",
        "message_id": payload.message_id,
        "events_stored": count,
        "date_range": date_range,
    }


# ---------------------------------------------------------------------------
# Casting handler
# ---------------------------------------------------------------------------

def _handle_casting(payload: EmailPayload, webhook: str) -> dict:
    """Casting PDFs: notify Discord for manual processing. No DB writes."""
    filenames = ", ".join(a.filename for a in payload.attachments)
    post_to_discord(webhook,
        f"\U0001f4cb **Casting PDF received \u2014 needs manual processing**\n"
        f"   From: {payload.sender}\n"
        f"   Subject: {payload.subject}\n"
        f"   Files: {filenames}\n"
        f"   \u2192 Open a Claude session and parse into casting DB"
    )
    return {"status": "manual", "message_id": payload.message_id}


def _handle_casting_attachment(att: AttachmentPayload, payload: EmailPayload,
                                webhook: str) -> None:
    """Post a single casting attachment to Discord in a mixed email."""
    post_to_discord(webhook,
        f"\U0001f4cb **Casting PDF in mixed email \u2014 needs manual processing**\n"
        f"   File: {att.filename}"
    )
