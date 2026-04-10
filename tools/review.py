#!/usr/bin/env python3
"""
Interactive review tool for NBT schedule parser.
Downloads PDFs from Gmail via gog on Mac mini, runs parser, lets you approve events.
Saves approved output as golden fixture JSON files.

Usage:
    python tools/review.py --period 2025-12        # all Dec PDFs via Gmail
    python tools/review.py --pdf /path/to/file.pdf  # single local PDF
    python tools/review.py --recheck               # re-run parser on all existing golden files

Requirements:
    - SSH alias 'macmini' configured
    - gog CLI on Mac mini at /opt/homebrew/bin/gog
    - GOG account: zbrickson@gmail.com
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

# Add project root to sys.path so we can import app.*
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.parsers.schedule import parse_schedule_pdf
from app.parsers.classifier import classify_pdf, PdfType

GOLDEN_DIR = PROJECT_ROOT / "tests" / "fixtures" / "golden"
PDF_CACHE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "pdfs"
GOG_ACCOUNT = "zbrickson@gmail.com"


def _gog_password() -> str:
    password = os.environ.get("GOG_KEYRING_PASSWORD", "").strip()
    if not password:
        raise RuntimeError("GOG_KEYRING_PASSWORD environment variable is required")
    return password


# ---------------------------------------------------------------------------
# Gmail helpers via gog on Mac mini
# ---------------------------------------------------------------------------

def _ssh_gog(cmd: str, timeout: int = 60) -> str:
    """Run a gog command on Mac mini, return stdout. Raises on failure."""
    full = f"GOG_KEYRING_PASSWORD={_gog_password()} gog {cmd} --account {GOG_ACCOUNT} --json"
    result = subprocess.run(["ssh", "macmini", full], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"gog command failed: {result.stderr.strip()}")
    return result.stdout


def search_period(period: str) -> list[dict]:
    """Return list of threads from Brooke with attachments in YYYY-MM period."""
    year, month = period.split("-")
    nm = int(month) % 12 + 1
    ny = int(year) + (1 if int(month) == 12 else 0)
    after = f"{year}/{int(month):02d}/01"
    before = f"{ny}/{nm:02d}/01"
    query = f"gmail search 'from:bwahlquist@nevadaballet.org has:attachment after:{after} before:{before}' --max 50"
    data = json.loads(_ssh_gog(query))
    return data.get("threads", [])


def get_pdf_attachments(thread_id: str) -> list[dict]:
    """Return list of PDF attachment dicts for a thread."""
    data = json.loads(_ssh_gog(f"gmail get {thread_id}"))
    return [a for a in data.get("attachments", []) if a.get("mimeType") == "application/pdf"]


def download_attachment(msg_id: str, att_id: str, filename: str) -> Path:
    """Download PDF from Mac mini, cache locally. Returns local path."""
    PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = PDF_CACHE_DIR / filename
    if cache_path.exists():
        print(f"    (cached: {filename})")
        return cache_path

    print(f"    Downloading {filename}...", end=" ", flush=True)
    att_json = json.loads(_ssh_gog(f"gmail attachment {msg_id} '{att_id}'", timeout=30))
    remote_path = att_json["path"]
    subprocess.run(["scp", f"macmini:{remote_path}", str(cache_path)], check=True, capture_output=True)
    print("done")
    return cache_path


# ---------------------------------------------------------------------------
# Review logic
# ---------------------------------------------------------------------------

def _prompt(msg: str, valid: set) -> str:
    while True:
        val = input(msg).strip().lower()
        if val in valid:
            return val
        print(f"  (enter one of: {', '.join(sorted(valid))})")


def review_pdf(pdf_path: Path, subject: str = "") -> dict | None:
    """
    Interactively review one PDF. Returns golden dict on save, None on skip.
    """
    print(f"\n{'='*60}")
    print(f"PDF:     {pdf_path.name}")
    if subject:
        print(f"Subject: {subject}")

    try:
        result = parse_schedule_pdf(str(pdf_path))
    except Exception as e:
        print(f"  PARSE ERROR: {e}")
        _prompt("  Skip this PDF? [y/n]: ", {"y", "n"})
        return None

    print(f"Date:    {result.date}")
    print(f"Events:  {len(result.events)}   Fittings: {len(result.fittings)}")

    if not result.events and not result.fittings:
        print("  WARNING: No events or fittings parsed!")

    approved_events = []
    approved_fittings = []

    # --- Review events ---
    for i, ev in enumerate(result.events):
        print(f"\n  [{i+1}/{len(result.events)}] {ev.time_start} - {ev.time_end}")
        print(f"    studio:  {ev.studio or '—'}")
        print(f"    show:    {ev.show}")
        print(f"    cast:    {ev.cast_type or '—'}")
        print(f"    staff:   {ev.staff or '—'}")
        if ev.notes:
            print(f"    notes:   {ev.notes}")

        choice = _prompt("  -> [y]es / [n]o / [e]dit: ", {"y", "n", "e"})

        if choice == "n":
            print("    Skipped.")
            continue
        elif choice == "e":
            show = input(f"    show [{ev.show}]: ").strip() or ev.show
            cast = input(f"    cast [{ev.cast_type or ''}]: ").strip() or ev.cast_type
            ev_dict = {
                "time_start": str(ev.time_start),
                "time_end": str(ev.time_end),
                "studio": ev.studio,
                "show": show,
                "cast_type": cast or None,
                "staff": ev.staff,
                "notes": ev.notes,
                "event_type": ev.event_type,
            }
        else:
            ev_dict = {
                "time_start": str(ev.time_start),
                "time_end": str(ev.time_end),
                "studio": ev.studio,
                "show": ev.show,
                "cast_type": ev.cast_type,
                "staff": ev.staff,
                "notes": ev.notes,
                "event_type": ev.event_type,
            }
        approved_events.append(ev_dict)

    # --- Review fittings (bulk) ---
    if result.fittings:
        print(f"\n  Fittings ({len(result.fittings)}):")
        for f in result.fittings[:5]:
            print(f"    {f.time_start}-{f.time_end}  {f.dancer}  [{f.show}]")
        if len(result.fittings) > 5:
            print(f"    ... and {len(result.fittings) - 5} more")
        choice = _prompt("  -> Approve all fittings? [y/n]: ", {"y", "n"})
        if choice == "y":
            for f in result.fittings:
                approved_fittings.append({
                    "time_start": str(f.time_start),
                    "time_end": str(f.time_end),
                    "where": f.where,
                    "show": f.show,
                    "dancer": f.dancer,
                    "staff": f.staff,
                    "notes": f.notes,
                    "event_type": f.event_type,
                })

    print(f"\n  Summary: {len(approved_events)} events, {len(approved_fittings)} fittings approved")
    choice = _prompt("  -> [s]ave / [q]uit / [r]edo: ", {"s", "q", "r"})

    if choice == "r":
        return review_pdf(pdf_path, subject)
    if choice != "s":
        return None

    golden = {
        "source_pdf": pdf_path.name,
        "date": result.date.isoformat(),
        "approved_at": datetime.now().isoformat(),
        "events": approved_events,
        "fittings": approved_fittings,
    }
    return golden


def save_golden(golden: dict) -> Path:
    """Save golden dict to tests/fixtures/golden/YYYY-MM-DD.json."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    out_path = GOLDEN_DIR / f"{golden['date']}.json"
    with open(out_path, "w") as f:
        json.dump(golden, f, indent=2)
    print(f"  Saved: {out_path.relative_to(PROJECT_ROOT)}")
    return out_path


def recheck_golden():
    """Re-run parser on all golden files and show diffs."""
    golden_files = sorted(GOLDEN_DIR.glob("*.json"))
    if not golden_files:
        print("No golden files found.")
        return

    for gf in golden_files:
        with open(gf) as f:
            golden = json.load(f)
        pdf_path = PDF_CACHE_DIR / golden["source_pdf"]
        if not pdf_path.exists():
            print(f"  SKIP {gf.stem} -- PDF not cached")
            continue

        try:
            result = parse_schedule_pdf(str(pdf_path))
        except Exception as e:
            print(f"  ERROR {gf.stem}: {e}")
            continue

        actual_events = [
            {
                "time_start": str(e.time_start), "time_end": str(e.time_end),
                "studio": e.studio, "show": e.show, "cast_type": e.cast_type,
                "staff": e.staff, "notes": e.notes, "event_type": e.event_type,
            }
            for e in result.events
        ]

        if actual_events == golden["events"]:
            print(f"  OK  {gf.stem} ({len(actual_events)} events)")
        else:
            print(f"  DIFF {gf.stem}: expected {len(golden['events'])} events, got {len(actual_events)}")
            added = [e for e in actual_events if e not in golden["events"]]
            removed = [e for e in golden["events"] if e not in actual_events]
            for e in removed:
                print(f"    - {e['time_start']} {e['show']}")
            for e in added:
                print(f"    + {e['time_start']} {e['show']}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="NBT schedule parser review tool")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--period", help="Gmail period to review (YYYY-MM), e.g. 2025-12")
    group.add_argument("--pdf", help="Path to a local PDF to review")
    group.add_argument("--recheck", action="store_true", help="Re-run parser on all golden files")
    parser.add_argument("--force", action="store_true", help="Re-review already-approved dates")
    args = parser.parse_args()

    if args.recheck:
        recheck_golden()
        return

    if args.pdf:
        pdf_path = Path(args.pdf)
        golden = review_pdf(pdf_path)
        if golden:
            save_golden(golden)
        return

    # --period: download and review all PDFs for the month
    print(f"Searching Gmail for {args.period}...")
    threads = search_period(args.period)
    print(f"Found {len(threads)} emails")

    saved = 0
    for thread in threads:
        print(f"\n--- {thread.get('date', '?')}  {thread.get('subject', '?')}")
        try:
            attachments = get_pdf_attachments(thread["id"])
        except Exception as e:
            print(f"  Error fetching attachments: {e}")
            continue

        if not attachments:
            print("  No PDF attachments, skipping")
            continue

        for att in attachments:
            filename = att.get("filename", f"{thread['id']}.pdf")
            if classify_pdf(filename) != PdfType.SCHEDULE:
                print(f"  Skipping non-schedule PDF: {filename}")
                continue

            try:
                pdf_path = download_attachment(thread["id"], att["attachmentId"], filename)
            except Exception as e:
                print(f"  Download error: {e}")
                continue

            # Check if already approved (by looking at golden files for this date)
            if not args.force:
                try:
                    result = parse_schedule_pdf(str(pdf_path))
                    golden_file = GOLDEN_DIR / f"{result.date.isoformat()}.json"
                    if golden_file.exists():
                        print(f"  Already approved: {result.date} -- skip (use --force to re-review)")
                        continue
                except Exception:
                    pass  # Can't parse date yet, proceed to review

            golden = review_pdf(pdf_path, subject=thread.get("subject", ""))
            if golden:
                save_golden(golden)
                saved += 1

    print(f"\nDone. {saved} golden files saved.")


if __name__ == "__main__":
    main()
