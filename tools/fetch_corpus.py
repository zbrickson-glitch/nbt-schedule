#!/usr/bin/env python3
"""
Download real NBT schedule PDFs from Gmail for parser testing.
Saves PDFs to tests/fixtures/corpus/ with a manifest.json.

Usage:
    python3 tools/fetch_corpus.py             # download missing PDFs only
    python3 tools/fetch_corpus.py --refresh   # re-download everything
    python3 tools/fetch_corpus.py --limit 50  # cap at 50 PDFs

NOTE: Requires gog CLI on macmini with valid credentials.
If gog token has expired, use the Gmail MCP in Claude to re-download.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CORPUS_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "corpus"
MANIFEST_PATH = CORPUS_DIR / "manifest.json"

GOG_ACCOUNT = "zbrickson@gmail.com"
BROOKE_EMAIL = "bwahlquist@nevadaballet.org"

# Filenames/subjects that are NOT daily schedule PDFs
_SKIP_KEYWORDS = [
    "casting", "roster", "maag", "month", "contract", "handbook",
    "role responsibilities", "shoes", "tights", "candy cane",
    "non-reengagement", "shoe drop"
]


def _gog_password() -> str:
    password = os.environ.get("GOG_KEYRING_PASSWORD", "").strip()
    if not password:
        raise RuntimeError("GOG_KEYRING_PASSWORD environment variable is required")
    return password


def _ssh_gog(cmd: str, timeout: int = 60) -> str:
    full = f"GOG_KEYRING_PASSWORD={_gog_password()} gog {cmd} --account {GOG_ACCOUNT} --json"
    result = subprocess.run(["ssh", "macmini", full], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"gog failed: {result.stderr.strip()}")
    return result.stdout


def _is_schedule_pdf(filename: str) -> bool:
    """Return True if filename looks like a daily schedule (not casting/MAAG/etc.)."""
    name = filename.lower()
    if not name.endswith(".pdf"):
        return False
    for kw in _SKIP_KEYWORDS:
        if kw in name:
            return False
    return True


def fetch_threads(limit: int) -> list[dict]:
    """Search Gmail for all Brooke emails with attachments."""
    data = json.loads(_ssh_gog(
        f"gmail search 'from:{BROOKE_EMAIL} has:attachment' --max {limit}"
    ))
    threads = data.get("threads") or []
    return list(reversed(threads))  # oldest first


def get_pdf_attachments(thread_id: str) -> list[dict]:
    data = json.loads(_ssh_gog(f"gmail get {thread_id}"))
    return [
        a for a in data.get("attachments", [])
        if a.get("mimeType") == "application/pdf"
           and _is_schedule_pdf(a.get("filename", ""))
    ]


def download_pdf(thread_id: str, att_id: str, dest: Path) -> bool:
    """Download one attachment to dest. Returns True on success."""
    try:
        att_json = json.loads(_ssh_gog(f"gmail attachment {thread_id} '{att_id}'", timeout=30))
        remote_path = att_json["path"]
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            tmp = Path(f.name)
        subprocess.run(["scp", f"macmini:{remote_path}", str(tmp)],
                       check=True, capture_output=True)
        tmp.rename(dest)
        return True
    except Exception as e:
        print(f"    ERROR: {e}")
        return False


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Download NBT schedule PDF corpus")
    parser.add_argument("--refresh", action="store_true", help="Re-download already-fetched PDFs")
    parser.add_argument("--limit", type=int, default=200, help="Max Gmail threads to search")
    args = parser.parse_args()

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {} if args.refresh else load_manifest()

    print(f"Searching Gmail (limit {args.limit})...")
    threads = fetch_threads(args.limit)
    print(f"Found {len(threads)} threads")

    downloaded = 0
    skipped = 0
    errors = 0

    for i, thread in enumerate(threads):
        thread_id = thread["id"]
        subject = thread.get("subject", "?")[:55]
        date_str = thread.get("date", "?")

        try:
            pdfs = get_pdf_attachments(thread_id)
        except Exception as e:
            print(f"  [{i+1}] SKIP (get_attachments failed): {e}")
            errors += 1
            continue

        for att in pdfs:
            att_id = att.get("attachmentId") or att.get("id", "")
            filename = att.get("filename", "attachment.pdf")
            key = f"{thread_id}_{filename}"
            dest = CORPUS_DIR / f"{thread_id[:8]}_{filename}"

            if key in manifest and dest.exists() and not args.refresh:
                skipped += 1
                continue

            print(f"  [{i+1}/{len(threads)}] {date_str} | {filename}")
            ok = download_pdf(thread_id, att_id, dest)
            if ok:
                manifest[key] = {
                    "thread_id": thread_id,
                    "filename": filename,
                    "dest": dest.name,
                    "date": date_str,
                    "subject": subject,
                }
                downloaded += 1
            else:
                errors += 1

    save_manifest(manifest)
    total = len([p for p in CORPUS_DIR.glob("*.pdf")])
    print(f"\nDone. Downloaded: {downloaded}, Skipped: {skipped}, Errors: {errors}")
    print(f"Total PDFs in corpus: {total}")
    if total < 100:
        print(f"WARNING: Only {total} PDFs — need 100. Try --limit 300.")


if __name__ == "__main__":
    main()
