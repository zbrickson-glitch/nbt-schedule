import subprocess
import base64
import json
import os
from fastapi import APIRouter
from pydantic import BaseModel
from app.routers.pipeline import pipeline_nbt, EmailPayload, AttachmentPayload, _archive_existing_events

router = APIRouter()

BROOKE_EMAIL = "bwahlquist@nevadaballet.org"


class BackfillRequest(BaseModel):
    limit: int = 100
    force: bool = False  # if True, delete existing events before re-ingesting


class BackfillResult(BaseModel):
    emails_found: int
    emails_ingested: int
    emails_skipped: int
    emails_forced: int = 0
    errors: list[str] = []


@router.post("/api/backfill", response_model=BackfillResult)
def backfill_from_gmail(req: BackfillRequest = None):
    """
    Scan Gmail history for all Brooke schedule emails and ingest them via
    the unified pipeline endpoint. Uses gog gmail CLI on Mac mini via SSH.

    Set force=True to delete existing sparse events and re-ingest fresh.
    This is useful when old events were stored by the legacy ingest pipeline
    (1 Company Class per email) and you want full multi-event schedules.
    """
    if req is None:
        req = BackfillRequest()

    result = BackfillResult(emails_found=0, emails_ingested=0, emails_skipped=0)

    try:
        # Fetch Brooke emails with attachments
        cmd = [
            "ssh", "macmini",
            f"gog gmail search 'from:{BROOKE_EMAIL} has:attachment' --limit {req.limit} --json"
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            result.errors.append(f"gog gmail search failed: {proc.stderr}")
            return result

        emails = json.loads(proc.stdout)
        result.emails_found = len(emails)

        for email in emails:
            try:
                email_id = email["id"]
                subject = email.get("subject", "")
                body = email.get("body", "")
                sender = email.get("sender") or email.get("from") or BROOKE_EMAIL
                attachments = []

                for att in email.get("attachments", []):
                    if att.get("mimeType") == "application/pdf":
                        dl_cmd = [
                            "ssh", "macmini",
                            f"gog gmail attachment {email_id} {att['id']} --base64"
                        ]
                        dl_proc = subprocess.run(dl_cmd, capture_output=True, text=True, timeout=30)
                        if dl_proc.returncode == 0:
                            attachments.append(AttachmentPayload(
                                filename=att.get("filename", "attachment.pdf"),
                                data=dl_proc.stdout.strip()
                            ))

                if not attachments:
                    continue

                # Force mode: wipe existing events for this email so idempotency passes
                if req.force:
                    _archive_existing_events(email_id)
                    result.emails_forced += 1

                pipeline_result = pipeline_nbt(EmailPayload(
                    message_id=email_id,
                    sender=sender,
                    subject=subject,
                    body=body,
                    attachments=attachments
                ))

                if pipeline_result.get("status") == "skipped":
                    result.emails_skipped += 1
                else:
                    result.emails_ingested += 1

            except Exception as e:
                result.errors.append(f"Error processing {email.get('id', '?')}: {str(e)}")

    except Exception as e:
        result.errors.append(str(e))

    return result
