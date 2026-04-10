#!/usr/bin/env python3
"""
Backfill tool — fetch historical Brooke emails via gog on Mac mini and push
through the unified pipeline at http://schedule.k3s.local/api/pipeline/nbt.

Run from macbook (has SSH to macmini). Does NOT need SSH keys in the k8s pod.

Usage:
    python3 tools/backfill.py                         # dry run
    python3 tools/backfill.py --run                   # ingest new emails
    python3 tools/backfill.py --run --force           # wipe old events, re-ingest all
    python3 tools/backfill.py --run --period 2025-12  # one month only
    python3 tools/backfill.py --run --period 2025-11  # another month
"""
import argparse
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

PIPELINE_URL = "http://schedule.k3s.local/api/pipeline/nbt"
BROOKE_EMAIL = "bwahlquist@nevadaballet.org"
GOG_ACCOUNT = "zbrickson@gmail.com"
GOG_PASSWORD = "REDACTED"


# ---------------------------------------------------------------------------
# gog helpers (identical pattern to tools/review.py)
# ---------------------------------------------------------------------------

def _ssh_gog(cmd: str, timeout: int = 60) -> str:
    full = f"GOG_KEYRING_PASSWORD={GOG_PASSWORD} gog {cmd} --account {GOG_ACCOUNT} --json"
    result = subprocess.run(["ssh", "macmini", full], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"gog command failed: {result.stderr.strip()}")
    return result.stdout


def search_threads(period: str = None, limit: int = 100) -> list[dict]:
    """Return threads from Brooke with attachments."""
    if period:
        year, month = period.split("-")
        nm = int(month) % 12 + 1
        ny = int(year) + (1 if int(month) == 12 else 0)
        after = f"{year}/{int(month):02d}/01"
        before = f"{ny}/{nm:02d}/01"
        query = (
            f"gmail search 'from:{BROOKE_EMAIL} has:attachment "
            f"after:{after} before:{before}' --max {limit}"
        )
    else:
        query = f"gmail search 'from:{BROOKE_EMAIL} has:attachment' --max {limit}"
    data = json.loads(_ssh_gog(query))
    return data.get("threads") or []


def get_pdf_attachments(thread_id: str) -> list[dict]:
    data = json.loads(_ssh_gog(f"gmail get {thread_id}"))
    return [a for a in data.get("attachments", []) if a.get("mimeType") == "application/pdf"]


def download_attachment_b64(thread_id: str, att_id: str, filename: str) -> str:
    """Download attachment via gog→scp, return base64 string."""
    att_json = json.loads(_ssh_gog(f"gmail attachment {thread_id} '{att_id}'", timeout=30))
    remote_path = att_json["path"]
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        tmp_path = f.name
    try:
        subprocess.run(
            ["scp", f"macmini:{remote_path}", tmp_path],
            check=True, capture_output=True
        )
        with open(tmp_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# DB helpers (run via kubectl exec)
# ---------------------------------------------------------------------------

def delete_events_for_email(email_id: str) -> int:
    """Delete existing schedule_events for this email_id. Returns rows deleted."""
    cmd = (
        f"kubectl exec -n zachdb deployment/postgres -- "
        f"psql -U zachdb -t -c \"DELETE FROM nbt.schedule_events "
        f"WHERE source_email_id = '{email_id}'; SELECT ROW_COUNT();\""
    )
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return 0  # just fire and forget


# ---------------------------------------------------------------------------
# Pipeline call
# ---------------------------------------------------------------------------

def call_pipeline(message_id: str, sender: str, subject: str, body: str,
                  attachments: list) -> dict:
    payload = {
        "message_id": message_id,
        "sender": sender,
        "subject": subject,
        "body": body,
        "attachments": attachments,
    }
    resp = requests.post(PIPELINE_URL, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="NBT email backfill tool")
    parser.add_argument("--run", action="store_true",
                        help="Actually ingest (default is dry run)")
    parser.add_argument("--force", action="store_true",
                        help="Delete existing events and re-ingest (requires --run)")
    parser.add_argument("--period", help="Month to process YYYY-MM (default: all)")
    parser.add_argument("--limit", type=int, default=100,
                        help="Max threads to fetch (default: 100)")
    args = parser.parse_args()

    print(f"==> Searching Gmail for Brooke emails...")
    if args.period:
        print(f"    Period: {args.period}")
    threads = search_threads(period=args.period, limit=args.limit)
    print(f"    Found {len(threads)} threads")

    # Process oldest-first so that revised emails (sent later) have higher
    # created_at in the DB and the dedup query picks the most recent version.
    threads = list(reversed(threads))

    stats = {"found": len(threads), "ingested": 0, "skipped": 0,
             "forced": 0, "no_pdf": 0, "errors": []}

    for i, thread in enumerate(threads):
        thread_id = thread["id"]
        subject = thread.get("subject", "")
        date_str = thread.get("date", "?")

        print(f"\n  [{i+1}/{len(threads)}] {date_str}  {subject[:55]}")

        # Get PDF attachments for this thread
        try:
            pdfs = get_pdf_attachments(thread_id)
        except Exception as e:
            msg = f"{thread_id}: get_pdf_attachments failed: {e}"
            stats["errors"].append(msg)
            print(f"    ERROR: {e}")
            continue

        if not pdfs:
            stats["no_pdf"] += 1
            print(f"    SKIP (no PDFs)")
            continue

        print(f"    PDFs: {', '.join(a.get('filename', '?') for a in pdfs)}")

        if not args.run:
            print(f"    [dry run]")
            continue

        # Force: wipe old events for this thread_id before re-ingesting
        if args.force:
            delete_events_for_email(thread_id)
            stats["forced"] += 1

        # Download PDFs and build attachments payload
        attachments = []
        for att in pdfs:
            att_id = att.get("attachmentId") or att.get("id", "")
            filename = att.get("filename", "attachment.pdf")
            try:
                b64 = download_attachment_b64(thread_id, att_id, filename)
                attachments.append({"filename": filename, "data": b64})
                print(f"    Downloaded {filename} ({len(b64)//1024}KB)")
            except Exception as e:
                msg = f"{thread_id}/{filename}: download failed: {e}"
                stats["errors"].append(msg)
                print(f"    ERROR downloading {filename}: {e}")

        if not attachments:
            stats["errors"].append(f"{thread_id}: no attachments downloaded")
            continue

        # Call pipeline
        try:
            result = call_pipeline(
                message_id=thread_id,
                sender=BROOKE_EMAIL,
                subject=subject,
                body="",
                attachments=attachments,
            )
            status = result.get("status", "?")
            if status == "skipped":
                stats["skipped"] += 1
                print(f"    SKIPPED (already processed)")
            else:
                stats["ingested"] += 1
                events = result.get("events_stored", "?")
                date_range = result.get("date_range", "")
                print(f"    OK — {events} events  {date_range}")
        except Exception as e:
            stats["errors"].append(f"{thread_id}: pipeline call failed: {e}")
            print(f"    ERROR calling pipeline: {e}")

    print()
    print("=" * 50)
    print("SUMMARY")
    print(f"  Threads found:    {stats['found']}")
    print(f"  No PDF (skipped): {stats['no_pdf']}")
    if args.force and args.run:
        print(f"  Force-cleared:    {stats['forced']}")
    if args.run:
        print(f"  Ingested:         {stats['ingested']}")
        print(f"  Already skipped:  {stats['skipped']}")
    else:
        print(f"  (dry run — pass --run to ingest)")
    if stats["errors"]:
        print(f"  Errors ({len(stats['errors'])}):")
        for e in stats["errors"]:
            print(f"    - {e}")


if __name__ == "__main__":
    main()
