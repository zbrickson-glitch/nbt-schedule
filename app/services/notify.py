"""
Notification service — posts alerts to Discord and Mattermost webhooks
when unrecognized or unusual email formats are encountered.
"""
import json
import logging
import urllib.request
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Emoji mapping for each pdf_type / email classification
PDF_TYPE_EMOJI = {
    "unknown": "❓",
    "maag": "📅",
    "cancellation": "🚫",
    "emergency": "🚨",
    "additional_detail": "📋",
    "body_text_logged": "📝",
}

DEFAULT_EMOJI = "⚠️"


def _make_alert_message(
    filename: str,
    subject: str,
    email_id: str,
    pdf_type: str,
    extraction_method: str,
    events_extracted: int,
) -> str:
    """Build the human-readable alert message string."""
    emoji = PDF_TYPE_EMOJI.get(pdf_type, DEFAULT_EMOJI)

    if events_extracted > 0:
        status = f"{events_extracted} event(s) extracted"
    else:
        status = "0 events extracted — manual review needed"

    lines = [
        f"{emoji} **NBT Unknown Format Alert**",
        f"**File:** {filename}",
        f"**Subject:** {subject}",
        f"**Email ID:** {email_id}",
        f"**PDF Type:** {pdf_type}",
        f"**Extraction Method:** {extraction_method}",
        f"**Status:** {status}",
    ]
    return "\n".join(lines)


def _post_webhook(url: str, payload: dict, label: str) -> None:
    """POST a JSON payload to a webhook URL. Logs a warning on failure."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req)
    except Exception as exc:
        logger.warning(f"Failed to post {label} webhook: {exc}")


def send_unknown_format_alert(
    filename: str,
    subject: str,
    email_id: str,
    pdf_type: str,
    extraction_method: str,
    events_extracted: int = 0,
) -> None:
    """
    Send an alert to Discord and/or Mattermost when an unrecognized email
    format is encountered.

    Args:
        filename: The PDF filename that could not be classified.
        subject: The email subject line.
        email_id: Unique identifier for the source email.
        pdf_type: Classification string (e.g. "unknown", "maag", "cancellation").
        extraction_method: How extraction was attempted (e.g. "pdfplumber", "llm").
        events_extracted: Number of events successfully extracted (0 = none).
    """
    message = _make_alert_message(
        filename=filename,
        subject=subject,
        email_id=email_id,
        pdf_type=pdf_type,
        extraction_method=extraction_method,
        events_extracted=events_extracted,
    )

    discord_url = settings.discord_webhook_url
    mm_url = settings.mm_webhook_url

    if discord_url:
        discord_payload = {
            "content": message,
            "username": "NBT Schedule Bot",
            "embeds": [
                {
                    "title": "Unknown Format Alert",
                    "description": message,
                    "fields": [
                        {"name": "Filename", "value": filename, "inline": True},
                        {"name": "Subject", "value": subject, "inline": True},
                        {"name": "Email ID", "value": email_id, "inline": False},
                        {"name": "PDF Type", "value": pdf_type, "inline": True},
                        {"name": "Extraction Method", "value": extraction_method, "inline": True},
                        {"name": "Status", "value": (
                            f"{events_extracted} event(s) extracted"
                            if events_extracted > 0
                            else "0 events extracted — manual review needed"
                        ), "inline": False},
                    ],
                }
            ],
        }
        _post_webhook(discord_url, discord_payload, "Discord")

    if mm_url:
        mm_payload = {"text": message}
        _post_webhook(mm_url, mm_payload, "Mattermost")
