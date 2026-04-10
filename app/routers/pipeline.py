"""
Unified NBT email pipeline endpoint.
Called by n8n dispatcher (or the built-in poller) for all emails from
bwahlquist@nevadaballet.org.
Owns: classification, parsing, atomic DB write, Discord notification.

Two-layer architecture:
  1. Deterministic parser (app/parsers/) — fast, free, handles 90% of cases
  2. Qwen smart classifier (app/services/qwen.py) — adds call-status reasoning
     using the full casting database role list. Handles TYPE 1 vs TYPE 2
     disambiguation, ambiguous cast columns, and edge cases.
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
from app.services.qwen import interpret_schedule_smart, interpret_casting_smart
from app.services.knowledge import (
    get_all_production_roles,
    get_user_roles,
    get_casting_status_rules,
    update_casting_db,
)

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
    """Parse schedule PDF(s), store atomically, notify Discord.

    Two-layer approach:
      1. Deterministic parser extracts raw events (time, studio, show, cast_type).
      2. If Qwen is enabled, run the smart classifier to add call-status reasoning
         using the full casting database role list (TYPE 1 vs TYPE 2 logic).
    """
    all_events = []
    errors = []
    qwen_events = []  # events from Qwen's smart interpretation

    for att in payload.attachments:
        # Route casting PDFs in a mixed email to the casting handler
        pdf_type = classify_pdf(att.filename)
        if pdf_type == PdfType.CASTING:
            _handle_casting_attachment(att, payload, webhook)
            continue
        if pdf_type == PdfType.MAAG:
            continue  # ignore month-at-a-glance

        pdf_bytes = base64.b64decode(att.data)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            tmp_path = f.name

        try:
            # --- Layer 1: Deterministic parser ---
            try:
                parsed_days = parse_schedule_pdf(tmp_path)
            except Exception as exc:
                logger.exception("Deterministic parse failed for %s", att.filename)
                errors.append(f"{att.filename}: {exc}")
                parsed_days = None

            if parsed_days:
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

            # --- Layer 2: Qwen smart classifier ---
            if settings.qwen_enabled and settings.qwen_api_key:
                try:
                    import pdfplumber
                    pdf_text_parts = []
                    pdf_tables = []
                    with pdfplumber.open(tmp_path) as pdf:
                        for i, page in enumerate(pdf.pages):
                            text = page.extract_text()
                            if text:
                                pdf_text_parts.append(f"--- Page {i+1} ---\n{text}")
                            tables = page.extract_tables()
                            for table in tables:
                                pdf_tables.append({"page": i + 1, "rows": table})

                    pdf_text = "\n\n".join(pdf_text_parts)
                    user_roles = get_user_roles()
                    production_roles = get_all_production_roles()

                    qwen_result = interpret_schedule_smart(
                        pdf_text=pdf_text,
                        pdf_tables=pdf_tables,
                        email_subject=payload.subject,
                        user_roles=user_roles,
                        production_roles=production_roles,
                    )

                    if qwen_result["error"]:
                        logger.warning("Qwen schedule interpretation failed: %s", qwen_result["error"])
                    else:
                        qwen_events = qwen_result["events"]
                        logger.info(
                            "Qwen interpreted %d events (tokens: %s)",
                            len(qwen_events),
                            qwen_result.get("usage", {}).get("total_tokens", "?"),
                        )
                except Exception:
                    logger.exception("Qwen smart classifier failed, continuing with deterministic only")

        finally:
            os.unlink(tmp_path)

    if not all_events:
        msg = _discord_schedule_error(payload, errors or ["no events extracted"])
        post_to_discord(webhook, msg)
        status = "parse_error" if errors else "no_events"
        return {"status": status, "message_id": payload.message_id, "errors": errors}

    # --- Merge Qwen call-status into deterministic events ---
    if qwen_events:
        all_events = _merge_qwen_call_status(all_events, qwen_events)

    # Atomic store
    count = _store_events_atomically(all_events, payload.message_id)
    zach_calls = _get_zach_calls(payload.message_id)

    dates = sorted(set(e["date"] for e in all_events))
    date_range = f"{dates[0]} \u2013 {dates[-1]}" if dates else "unknown"

    msg = _discord_schedule_ok(payload, count, date_range, zach_calls)
    if qwen_events:
        called = sum(1 for e in qwen_events if e.get("call_status") == "CALLED")
        not_called = sum(1 for e in qwen_events if e.get("call_status") == "NOT_CALLED")
        msg += f"\n\U0001f9e0 Qwen: {called} CALLED, {not_called} NOT_CALLED"
    if errors:
        msg += f"\n\u26a0\ufe0f Partial errors: {'; '.join(errors)}"
    post_to_discord(webhook, msg)

    return {
        "status": "ok",
        "message_id": payload.message_id,
        "events_stored": count,
        "date_range": date_range,
        "qwen_enriched": bool(qwen_events),
    }


def _merge_qwen_call_status(det_events: list, qwen_events: list) -> list:
    """Merge Qwen's call-status reasoning into the deterministic event list.

    Matches events by show name + start time. Adds 'call_status' and
    'qwen_reasoning' fields to each deterministic event. Falls back to
    the deterministic event unchanged if no Qwen match is found.
    """
    # Build a lookup from Qwen events: (show_fragment, start_time) -> qwen_event
    qwen_lookup = {}
    for qe in qwen_events:
        title = qe.get("title", "")
        # Extract show name from "NBT: [CALLED] Piece Name" format
        show_part = title.split("]", 1)[-1].strip() if "]" in title else title
        start = qe.get("start_datetime", "")
        # Use HH:MM from the ISO datetime
        time_key = start[11:16] if len(start) >= 16 else ""
        key = (show_part.lower(), time_key)
        qwen_lookup[key] = qe

    for ev in det_events:
        show_lower = (ev.get("show") or "").lower()
        t_start = ev.get("time_start")
        if hasattr(t_start, "strftime"):
            time_key = t_start.strftime("%H:%M")
        else:
            time_key = str(t_start)[:5] if t_start else ""

        # Try exact match first, then fuzzy (show substring)
        matched = qwen_lookup.get((show_lower, time_key))
        if not matched:
            for (qs, qt), qe in qwen_lookup.items():
                if qt == time_key and (qs in show_lower or show_lower in qs):
                    matched = qe
                    break

        if matched:
            ev["call_status"] = matched.get("call_status")
            ev["qwen_reasoning"] = matched.get("reasoning")

    return det_events


# ---------------------------------------------------------------------------
# Casting handler
# ---------------------------------------------------------------------------

def _handle_casting(payload: EmailPayload, webhook: str) -> dict:
    """Process casting PDFs.

    If Qwen is enabled, use AI to interpret the casting and update the
    knowledge base automatically. Otherwise fall back to Discord notification
    for manual processing.
    """
    if not (settings.qwen_enabled and settings.qwen_api_key):
        # Fallback: manual processing via Discord
        filenames = ", ".join(a.filename for a in payload.attachments)
        post_to_discord(webhook,
            f"\U0001f4cb **Casting PDF received \u2014 needs manual processing**\n"
            f"   From: {payload.sender}\n"
            f"   Subject: {payload.subject}\n"
            f"   Files: {filenames}\n"
            f"   \u2192 Open a Claude session and parse into casting DB"
        )
        return {"status": "manual", "message_id": payload.message_id}

    # --- Qwen-powered casting interpretation ---
    results = []
    for att in payload.attachments:
        pdf_type = classify_pdf(att.filename)
        if pdf_type not in (PdfType.CASTING, PdfType.UNKNOWN):
            continue

        try:
            pdf_bytes = base64.b64decode(att.data)
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(pdf_bytes)
                tmp_path = f.name

            try:
                import pdfplumber
                pdf_text_parts = []
                pdf_tables = []
                with pdfplumber.open(tmp_path) as pdf:
                    for i, page in enumerate(pdf.pages):
                        text = page.extract_text()
                        if text:
                            pdf_text_parts.append(f"--- Page {i+1} ---\n{text}")
                        tables = page.extract_tables()
                        for table in tables:
                            pdf_tables.append({"page": i + 1, "rows": table})

                pdf_text = "\n\n".join(pdf_text_parts)
                casting_rules = get_casting_status_rules()

                casting_result = interpret_casting_smart(
                    pdf_text=pdf_text,
                    pdf_tables=pdf_tables,
                    email_subject=payload.subject,
                    email_body=payload.attachments[0].data[:500] if payload.attachments else "",
                    existing_production=None,
                    casting_status_rules=casting_rules,
                )

                if casting_result.get("error"):
                    logger.warning("Qwen casting interpretation failed: %s", casting_result["error"])
                    post_to_discord(webhook,
                        f"\u26a0\ufe0f **Qwen casting parse failed** for {att.filename}\n"
                        f"   Error: {casting_result['error'][:200]}"
                    )
                else:
                    prod_key = casting_result.get("production_key", "unknown")
                    roles_data = casting_result.get("roles", {})
                    zach_roles = casting_result.get("zach_roles", [])
                    status = casting_result.get("casting_status", "unknown")

                    if roles_data:
                        update_casting_db(prod_key, roles_data, source_email_id=payload.message_id)
                        logger.info("Updated casting DB: %s (%s)", prod_key, status)

                    post_to_discord(webhook,
                        f"\U0001f4cb **Casting processed by Qwen**\n"
                        f"   Production: {casting_result.get('production_title', prod_key)}\n"
                        f"   Status: {status}\n"
                        f"   Zach's roles: {', '.join(zach_roles) if zach_roles else 'none listed'}\n"
                        f"   File: {att.filename}"
                    )
                    results.append(prod_key)

            finally:
                os.unlink(tmp_path)

        except Exception:
            logger.exception("Failed to process casting attachment %s", att.filename)

    return {
        "status": "ok" if results else "no_casting",
        "message_id": payload.message_id,
        "productions_updated": results,
    }


def _handle_casting_attachment(att: AttachmentPayload, payload: EmailPayload,
                                webhook: str) -> None:
    """Post a single casting attachment to Discord in a mixed email."""
    post_to_discord(webhook,
        f"\U0001f4cb **Casting PDF in mixed email \u2014 needs manual processing**\n"
        f"   File: {att.filename}"
    )
