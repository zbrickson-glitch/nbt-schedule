# NBT Parser Test Harness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a system that downloads 100+ real schedule PDFs from Gmail, runs them all through the parser, reports failures with full detail, and iterates until every PDF parses without error.

**Architecture:** Three-phase hybrid approach. Phase A: `tools/fetch_corpus.py` downloads a corpus of real schedule PDFs from Gmail via gog+scp to `tests/fixtures/corpus/`. Phase B: `tools/test_parser.py --fast` runs `parse_schedule_pdf()` directly on every PDF and produces a pass/fail/warn report with full tracebacks. Phase C: `tools/test_parser.py --report` generates a local HTML comparison report (pdftotext vs parsed events, side-by-side) for visual inspection without a separate server. Parser fixes iterate in the fast loop (seconds per round), visual confirmation happens before promoting to production.

**Tech Stack:** Python 3.11, pdfplumber, pdftotext (poppler), gog CLI on macmini, pssh over SSH, pytest (existing), FastAPI (existing). No new dependencies required.

---

## Task 1: Fetch PDF corpus

**Files:**
- Create: `tools/fetch_corpus.py`
- Create: `tests/fixtures/corpus/.gitkeep`

**Goal:** Download 100+ real schedule PDFs from Gmail to `tests/fixtures/corpus/`. Saves a `manifest.json` so you can re-run without re-downloading.

**Step 1: Create the corpus directory**

```bash
mkdir -p tests/fixtures/corpus
touch tests/fixtures/corpus/.gitkeep
echo "tests/fixtures/corpus/*.pdf" >> .gitignore
echo "tests/fixtures/corpus/manifest.json" >> .gitignore
```

**Step 2: Write `tools/fetch_corpus.py`**

```python
#!/usr/bin/env python3
"""
Download real NBT schedule PDFs from Gmail for parser testing.
Saves PDFs to tests/fixtures/corpus/ with a manifest.json.

Usage:
    python3 tools/fetch_corpus.py             # download missing PDFs only
    python3 tools/fetch_corpus.py --refresh   # re-download everything
    python3 tools/fetch_corpus.py --limit 50  # cap at 50 PDFs
"""
import argparse
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

CORPUS_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "corpus"
MANIFEST_PATH = CORPUS_DIR / "manifest.json"

GOG_ACCOUNT = "zbrickson@gmail.com"
GOG_PASSWORD = "REDACTED"
BROOKE_EMAIL = "bwahlquist@nevadaballet.org"

# Filenames that are NOT daily schedule PDFs
_SKIP_KEYWORDS = ["casting", "roster", "maag", "month", "contract", "handbook"]


def _ssh_gog(cmd: str, timeout: int = 60) -> str:
    full = f"GOG_KEYRING_PASSWORD={GOG_PASSWORD} gog {cmd} --account {GOG_ACCOUNT} --json"
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
            # Unique key: thread_id + filename
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
```

**Step 3: Run it**

```bash
python3 tools/fetch_corpus.py
```

Expected: `Total PDFs in corpus: 100+`

**Step 4: Commit**

```bash
git -C /Users/brickson/workspace-v5 add Projects/nbt-schedule-service/tools/fetch_corpus.py \
    Projects/nbt-schedule-service/tests/fixtures/corpus/.gitkeep \
    Projects/nbt-schedule-service/.gitignore
git -C /Users/brickson/workspace-v5 commit -m "feat(nbt): add corpus fetcher script"
```

---

## Task 2: Fast test harness

**Files:**
- Create: `tools/test_parser.py`

**Goal:** Run every corpus PDF through `parse_schedule_pdf()`, report exactly which fail and why.

**Step 1: Write `tools/test_parser.py`**

```python
#!/usr/bin/env python3
"""
NBT parser test harness.

Modes:
  --fast    Run parse_schedule_pdf() directly on corpus, report pass/fail (default)
  --report  Generate HTML side-by-side comparison report (pdftotext vs parsed)

Usage:
    python3 tools/test_parser.py              # fast mode, all corpus PDFs
    python3 tools/test_parser.py --fast       # explicit fast mode
    python3 tools/test_parser.py --report     # generate HTML report
    python3 tools/test_parser.py --pdf path/to/specific.pdf  # single file
"""
import argparse
import subprocess
import sys
import traceback
from pathlib import Path
from datetime import date

# Ensure app is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.parsers.schedule import parse_schedule_pdf, ParsedSchedule

CORPUS_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "corpus"
FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
REPORT_PATH = Path("/tmp/nbt_parser_report.html")


# ---------------------------------------------------------------------------
# ANSI colors
# ---------------------------------------------------------------------------

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pdftotext(pdf_path: Path) -> str:
    """Extract raw text from PDF using pdftotext (poppler)."""
    try:
        result = subprocess.run(
            ["pdftotext", str(pdf_path), "-"],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout
    except Exception:
        return ""


def _count_time_rows(text: str) -> int:
    """Rough count of rows with time ranges in PDF text (ground truth estimate)."""
    import re
    pattern = re.compile(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\s*(am|pm)", re.IGNORECASE)
    lines = text.splitlines()
    return sum(1 for line in lines if pattern.search(line))


# ---------------------------------------------------------------------------
# Fast mode
# ---------------------------------------------------------------------------

def run_fast(pdfs: list[Path], verbose: bool = False) -> int:
    """Run all PDFs through the parser. Returns number of failures."""
    results = {"pass": [], "warn": [], "fail": []}

    for pdf in pdfs:
        try:
            parsed = parse_schedule_pdf(str(pdf))

            if not isinstance(parsed, ParsedSchedule):
                results["fail"].append((pdf, "Returned non-ParsedSchedule", ""))
                continue

            if parsed.date is None:
                results["warn"].append((pdf, "date is None — could not parse date"))
                continue

            total = len(parsed.events) + len(parsed.fittings)
            if total == 0:
                # Check if it's actually a schedule (pdftotext has time rows)
                text = _pdftotext(pdf)
                time_rows = _count_time_rows(text)
                if time_rows > 0:
                    results["warn"].append((
                        pdf,
                        f"0 events extracted but pdftotext found ~{time_rows} time rows"
                    ))
                else:
                    # Probably a casting or MAAG PDF that slipped through
                    results["warn"].append((pdf, "0 events (likely not a schedule PDF)"))
            else:
                results["pass"].append((pdf, parsed.date, len(parsed.events), len(parsed.fittings)))

        except Exception as e:
            tb = traceback.format_exc()
            results["fail"].append((pdf, str(e), tb))

    # Print report
    total = len(pdfs)
    n_pass = len(results["pass"])
    n_warn = len(results["warn"])
    n_fail = len(results["fail"])

    print(f"\n{'='*60}")
    print(f"{BOLD}NBT Parser Test Results{RESET}")
    print(f"{'='*60}")
    print(f"  Total PDFs:  {total}")
    print(f"  {GREEN}✓ PASS:    {n_pass}{RESET}")
    print(f"  {YELLOW}⚠ WARN:    {n_warn}{RESET}")
    print(f"  {RED}✗ FAIL:    {n_fail}{RESET}")
    print()

    if results["fail"]:
        print(f"{RED}{BOLD}FAILURES:{RESET}")
        for pdf, err, tb in results["fail"]:
            print(f"\n  {RED}✗ {pdf.name}{RESET}")
            print(f"    Error: {err}")
            if verbose and tb:
                for line in tb.strip().splitlines():
                    print(f"      {line}")
        print()

    if results["warn"] and verbose:
        print(f"{YELLOW}{BOLD}WARNINGS:{RESET}")
        for pdf, msg in results["warn"]:
            print(f"  ⚠ {pdf.name}: {msg}")
        print()

    if results["pass"] and verbose:
        print(f"{GREEN}{BOLD}PASSED:{RESET}")
        for pdf, dt, n_ev, n_fit in results["pass"]:
            print(f"  ✓ {pdf.name}: {dt}, {n_ev} events, {n_fit} fittings")
        print()

    # Progress bar
    bar_width = 40
    filled = int(bar_width * n_pass / total) if total else 0
    bar = "█" * filled + "░" * (bar_width - filled)
    pct = 100 * n_pass / total if total else 0
    print(f"  [{bar}] {n_pass}/{total} ({pct:.0f}%)")
    print()

    if n_fail == 0 and n_warn == 0:
        print(f"{GREEN}{BOLD}🎉 ALL {total} PDFs PARSED SUCCESSFULLY!{RESET}")
    elif n_fail == 0:
        print(f"{YELLOW}All PDFs parsed (no crashes), but {n_warn} warnings to review.{RESET}")
    else:
        print(f"{RED}Fix {n_fail} failure(s) then re-run.{RESET}")
        print(f"Tip: use --verbose for full tracebacks, --pdf <name> to isolate one file")

    return n_fail


# ---------------------------------------------------------------------------
# HTML report mode
# ---------------------------------------------------------------------------

def run_report(pdfs: list[Path]) -> None:
    """Generate HTML side-by-side comparison (pdftotext vs parsed events)."""
    rows = []
    for pdf in pdfs:
        raw_text = _pdftotext(pdf)
        try:
            parsed = parse_schedule_pdf(str(pdf))
            status = "ok"
            error = ""
            events_html = "<table><tr><th>Time</th><th>Show</th><th>Cast</th><th>Staff</th></tr>"
            for ev in parsed.events:
                ts = str(ev.time_start)[:5] if ev.time_start else "?"
                te = str(ev.time_end)[:5] if ev.time_end else "?"
                events_html += f"<tr><td>{ts}–{te}</td><td>{ev.show}</td><td>{ev.cast_type or ''}</td><td>{ev.staff or ''}</td></tr>"
            for fv in parsed.fittings:
                ts = str(fv.time_start)[:5] if fv.time_start else "?"
                events_html += f"<tr style='color:#888'><td>{ts}</td><td>FITTING: {fv.show}</td><td>{fv.dancer}</td><td>{fv.staff or ''}</td></tr>"
            events_html += "</table>"
            date_str = str(parsed.date) if parsed.date else "?"
            summary = f"{date_str} — {len(parsed.events)} events, {len(parsed.fittings)} fittings"
        except Exception as e:
            status = "fail"
            error = str(e) + "\n" + traceback.format_exc()
            events_html = f"<pre style='color:red'>{error}</pre>"
            summary = "FAILED"

        rows.append({
            "name": pdf.name,
            "status": status,
            "summary": summary,
            "raw_text": raw_text[:3000],  # truncate for display
            "events_html": events_html,
        })

    n_ok = sum(1 for r in rows if r["status"] == "ok")
    n_fail = sum(1 for r in rows if r["status"] == "fail")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>NBT Parser Report — {n_ok}/{len(rows)} passed</title>
<style>
body {{ font-family: 'Nunito', sans-serif; background: #FFF5F7; color: #4A1942; margin: 0; padding: 16px; }}
h1 {{ color: #E91E8C; }}
.summary {{ background: #fff; padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; border: 1px solid #eee; }}
.pdf-card {{ background: #fff; border-radius: 8px; margin-bottom: 16px; border: 1px solid #eee; overflow: hidden; }}
.pdf-header {{ padding: 10px 16px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; }}
.ok .pdf-header {{ border-left: 4px solid #4caf50; }}
.fail .pdf-header {{ border-left: 4px solid #E91E8C; background: #fff5f7; }}
.pdf-body {{ display: none; padding: 0 16px 16px; }}
.pdf-body.open {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
pre {{ font-size: 11px; white-space: pre-wrap; word-break: break-word; background: #f5f5f5; padding: 8px; border-radius: 4px; max-height: 400px; overflow-y: auto; }}
table {{ border-collapse: collapse; font-size: 12px; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 4px 8px; text-align: left; }}
th {{ background: #FFF5F7; }}
.badge-ok {{ background: #e8f5e9; color: #388e3c; padding: 2px 8px; border-radius: 12px; font-size: 12px; }}
.badge-fail {{ background: #fce4ec; color: #c62828; padding: 2px 8px; border-radius: 12px; font-size: 12px; }}
</style>
</head>
<body>
<h1>NBT Parser Report</h1>
<div class="summary">
  <strong>{n_ok}/{len(rows)}</strong> PDFs parsed successfully &nbsp;|&nbsp;
  <strong style="color:#E91E8C">{n_fail}</strong> failures
</div>
"""
    # Failures first
    for r in sorted(rows, key=lambda x: x["status"] != "fail"):
        badge = '<span class="badge-ok">✓ OK</span>' if r["status"] == "ok" else '<span class="badge-fail">✗ FAIL</span>'
        html += f"""<div class="pdf-card {r['status']}" onclick="var b=this.querySelector('.pdf-body');b.classList.toggle('open')">
  <div class="pdf-header"><span><strong>{r['name']}</strong> &nbsp; {r['summary']}</span>{badge}</div>
  <div class="pdf-body">
    <div><h4>PDF Text (pdftotext)</h4><pre>{r['raw_text']}</pre></div>
    <div><h4>Parsed Events</h4>{r['events_html']}</div>
  </div>
</div>
"""
    html += "<script>document.querySelectorAll('.fail .pdf-body').forEach(b=>b.classList.add('open'))</script></body></html>"

    REPORT_PATH.write_text(html)
    print(f"\n✓ Report written to: {REPORT_PATH}")
    print(f"  Open with: open {REPORT_PATH}")
    # Auto-open
    subprocess.run(["open", str(REPORT_PATH)], check=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="NBT parser test harness")
    parser.add_argument("--fast", action="store_true", default=True,
                        help="Run parser directly (default)")
    parser.add_argument("--report", action="store_true",
                        help="Generate HTML comparison report")
    parser.add_argument("--pdf", help="Test a single PDF file instead of corpus")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show full tracebacks and passed list")
    args = parser.parse_args()

    if args.pdf:
        pdfs = [Path(args.pdf)]
    else:
        # Load corpus + existing fixtures
        pdfs = sorted(CORPUS_DIR.glob("*.pdf"))
        # Also include existing test fixtures
        for p in FIXTURE_DIR.glob("*.pdf"):
            pdfs.append(p)
        for p in (FIXTURE_DIR / "pdfs").glob("*.pdf"):
            pdfs.append(p)
        pdfs = sorted(set(pdfs))

    if not pdfs:
        print("No PDFs found. Run tools/fetch_corpus.py first.")
        sys.exit(1)

    print(f"Testing {len(pdfs)} PDFs...")

    if args.report:
        run_report(pdfs)
    else:
        failures = run_fast(pdfs, verbose=args.verbose)
        sys.exit(1 if failures > 0 else 0)


if __name__ == "__main__":
    main()
```

**Step 2: Run it against existing fixtures first (smoke test)**

```bash
cd /Users/brickson/workspace-v5/Projects/nbt-schedule-service
python3 tools/test_parser.py --verbose
```

Expected: All 5 existing fixture PDFs pass, clear report printed.

**Step 3: After corpus is downloaded, run against all 100+**

```bash
python3 tools/test_parser.py --verbose 2>&1 | tee /tmp/parser-run-1.txt
```

Expected first run: Some failures on edge-case PDFs.

**Step 4: Commit**

```bash
git -C /Users/brickson/workspace-v5 add Projects/nbt-schedule-service/tools/test_parser.py
git -C /Users/brickson/workspace-v5 commit -m "feat(nbt): add parser test harness"
```

---

## Task 3: Run harness → fix parser → repeat until 100/100

This is the iteration loop. For each run:

**Step 1: Run the harness**

```bash
python3 tools/test_parser.py --verbose 2>&1 | tee /tmp/parser-run-N.txt
```

**Step 2: Identify failure patterns**

Look at the errors. Common patterns to watch for:
- `ValueError: Cannot parse time range: ...` → time format edge case
- `IndexError: list index out of range` → short row not caught
- `ValueError: Could not parse date` → date format variation
- `AttributeError` → unexpected None in a cell

**Step 3: Fix `app/parsers/schedule.py`**

For each failure, add a case to the appropriate function:
- Time parsing edge cases → `_parse_time_range()`
- Row too short → column count guards in the row processing loop
- Date edge cases → `_parse_date()` regex
- Unexpected None → `_clean()` + None guards

**Step 4: Re-run**

```bash
python3 tools/test_parser.py 2>&1 | tee /tmp/parser-run-N+1.txt
```

**Step 5: Check improvement**

Compare counts. Keep iterating until:
```
🎉 ALL 100 PDFs PARSED SUCCESSFULLY!
```

**Step 6: Generate visual report to review accuracy**

```bash
python3 tools/test_parser.py --report
# Browser opens automatically
```

Review side-by-side: pdftotext shows the PDF content, parsed events show what the parser extracted. Check for:
- Missing events (parser skipped a row)
- Wrong times (AM/PM logic off)
- Wrong show names (text merge/split)
- Fitting vs rehearsal misclassification

**Step 7: Commit each fix increment**

```bash
git -C /Users/brickson/workspace-v5 add Projects/nbt-schedule-service/app/parsers/schedule.py
git -C /Users/brickson/workspace-v5 commit -m "fix(nbt-parser): handle [specific edge case]"
```

Repeat until 100/100 with no warnings.

---

## Task 4: Make DB schema configurable (for test server isolation)

**Files:**
- Modify: `app/config.py`
- Modify: `app/db.py`

**Goal:** Add `NBT_SCHEMA` env var so the app can point to `nbt_test` schema in postgres without code changes.

**Step 1: Add `nbt_schema` to Settings**

In `app/config.py`, add:
```python
nbt_schema: str = "nbt"
```

Full file after change:
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql://zachdb:zachdb@zachdb-postgres.zachdb.svc.cluster.local:5432/zachdb"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    llm_api_key: str = "sk-madge-litellm-2026"
    llm_model: str = "madge-brain"
    llm_api_base: str = "http://100.89.229.85:4000/v1"
    mm_webhook_url: str = ""
    discord_webhook_url: str = ""
    gog_host: str = "macmini"
    base_url: str = "http://schedule.k3s.local"
    nbt_schema: str = "nbt"

    class Config:
        env_prefix = "NBT_"

settings = Settings()
```

**Step 2: Set search_path in `app/db.py`**

Use PostgreSQL's `search_path` so all unqualified table references route to the configured schema:

```python
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from app.config import settings

@contextmanager
def get_db():
    conn = psycopg2.connect(
        settings.database_url,
        cursor_factory=RealDictCursor,
        options=f"-c search_path={settings.nbt_schema}",
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

**Step 3: Strip `nbt.` prefix from all SQL queries**

Run this to find all occurrences:
```bash
grep -rn "nbt\." app/routers/ app/parsers/ | grep -v ".pyc"
```

For EVERY occurrence of `nbt.schedule_events`, `nbt.casting`, `nbt.subscribers`, etc. — remove the `nbt.` prefix (just use `schedule_events`, `casting`, etc.). The `search_path` handles routing.

Files to update:
- `app/routers/public.py` — all `nbt.` → bare table name
- `app/routers/schedule.py` — same
- `app/routers/admin.py` — same
- `app/routers/pipeline.py` — same
- `app/routers/casting.py` (if exists) — same
- Any other routers

**Step 4: Verify existing tests still pass**

```bash
cd /Users/brickson/workspace-v5/Projects/nbt-schedule-service
python3 -m pytest tests/ -x -q 2>&1 | tail -20
```

Expected: All existing tests pass (they don't test DB, only parser).

**Step 5: Commit**

```bash
git -C /Users/brickson/workspace-v5 add Projects/nbt-schedule-service/app/config.py \
    Projects/nbt-schedule-service/app/db.py \
    Projects/nbt-schedule-service/app/routers/
git -C /Users/brickson/workspace-v5 commit -m "feat(nbt): make DB schema configurable via NBT_SCHEMA"
```

---

## Task 5: Create nbt_test schema

**Goal:** A parallel `nbt_test` schema in zachdb postgres that the test server writes to.

**Step 1: Create schema via SQL**

```bash
kubectl exec -n zachdb deployment/postgres -- psql -U zachdb << 'EOF'
-- Create test schema mirroring nbt
CREATE SCHEMA IF NOT EXISTS nbt_test;

-- Copy all table definitions from nbt schema
CREATE TABLE IF NOT EXISTS nbt_test.schedule_events (LIKE nbt.schedule_events INCLUDING ALL);
CREATE TABLE IF NOT EXISTS nbt_test.schedule_history (LIKE nbt.schedule_history INCLUDING ALL);
CREATE TABLE IF NOT EXISTS nbt_test.casting (LIKE nbt.casting INCLUDING ALL);
CREATE TABLE IF NOT EXISTS nbt_test.subscribers (LIKE nbt.subscribers INCLUDING ALL);
CREATE TABLE IF NOT EXISTS nbt_test.roster (LIKE nbt.roster INCLUDING ALL);
CREATE TABLE IF NOT EXISTS nbt_test.feedback (LIKE nbt.feedback INCLUDING ALL);

GRANT ALL ON SCHEMA nbt_test TO zachdb;
GRANT ALL ON ALL TABLES IN SCHEMA nbt_test TO zachdb;
GRANT ALL ON ALL SEQUENCES IN SCHEMA nbt_test TO zachdb;
EOF
```

**Step 2: Verify schema created**

```bash
kubectl exec -n zachdb deployment/postgres -- psql -U zachdb -c "\dn"
```

Expected: Both `nbt` and `nbt_test` listed.

**Step 3: Commit** (no code to commit here, just note it in docs)

---

## Task 6: Deploy test server to k3s

**Files:**
- Create: `infra/manifests/nbt/deployment-test.yaml`
- Modify: `/etc/hosts` on macbook + macmini (add `schedule-test.k3s.local`)

**Goal:** A second instance of the schedule service at `http://schedule-test.k3s.local` pointing to `nbt_test` schema.

**Step 1: Write the test deployment manifest**

Create `infra/manifests/nbt/deployment-test.yaml`:

```yaml
# NBT Schedule Service — TEST instance (nbt_test schema)
# Access at: http://schedule-test.k3s.local
# Points to nbt_test schema — safe for testing, isolated from production

apiVersion: v1
kind: ConfigMap
metadata:
  name: nbt-schedule-test-config
  namespace: nbt
data:
  NBT_SCHEMA: "nbt_test"
  NBT_BASE_URL: "http://schedule-test.k3s.local"
  # Discord webhook left blank — don't spam Discord during testing
  NBT_DISCORD_WEBHOOK_URL: ""
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nbt-schedule-test
  namespace: nbt
  labels:
    app: nbt-schedule-test
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nbt-schedule-test
  template:
    metadata:
      labels:
        app: nbt-schedule-test
    spec:
      imagePullPolicy: Never
      containers:
        - name: nbt-schedule-test
          image: nbt-schedule-service:latest
          imagePullPolicy: Never
          ports:
            - containerPort: 8080
          envFrom:
            - configMapRef:
                name: nbt-schedule-test-config
            - configMapRef:
                name: nbt-schedule-config   # inherit DB creds + other settings
---
apiVersion: v1
kind: Service
metadata:
  name: nbt-schedule-test-svc
  namespace: nbt
spec:
  selector:
    app: nbt-schedule-test
  ports:
    - port: 80
      targetPort: 8080
```

**Step 2: Add DNS entry**

```bash
# On macbook
sudo sh -c 'echo "100.85.199.14  schedule-test.k3s.local" >> /etc/hosts'
# On macmini
ssh macmini "sudo sh -c 'echo \"100.85.199.14  schedule-test.k3s.local\" >> /etc/hosts'"
```

**Step 3: Apply manifest**

```bash
kubectl apply -f /Users/brickson/workspace-v5/infra/manifests/nbt/deployment-test.yaml
kubectl rollout status deployment/nbt-schedule-test -n nbt --timeout=60s
```

**Step 4: Smoke test**

```bash
curl -s http://schedule-test.k3s.local/public/season | python3 -m json.tool
```

Expected: JSON response (even if empty `{"season": "", "weeks": []}`)

**Step 5: Commit manifest**

```bash
git -C /Users/brickson/workspace-v5 add infra/manifests/nbt/deployment-test.yaml
git -C /Users/brickson/workspace-v5 commit -m "feat(nbt): add test server deployment (nbt_test schema)"
```

---

## Task 7: Visual validation — POST corpus through test server

**Goal:** POST all 100 corpus PDFs through the test server pipeline, view results in the admin UI.

**Step 1: Update `tools/test_parser.py` to support `--visual` mode**

Add to the `main()` function and add a `run_visual()` function:

```python
# Add to imports at top:
import base64
import requests  # already in requirements

# Add --visual flag to argparse:
parser.add_argument("--visual", action="store_true",
                    help="POST to test server, view results in admin UI")

# Add run_visual() function:
def run_visual(pdfs: list[Path], server_url: str = "http://schedule-test.k3s.local") -> int:
    """POST each PDF to the test server pipeline. Returns failure count."""
    failures = 0
    print(f"Posting {len(pdfs)} PDFs to {server_url}/api/pipeline/nbt ...")

    for i, pdf in enumerate(pdfs):
        with open(pdf, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        # Use filename-based unique ID to allow idempotent re-runs
        msg_id = f"test-{pdf.stem}"

        # Clear previous test run for this ID
        try:
            requests.delete(f"{server_url}/api/test/events/{msg_id}", timeout=5)
        except Exception:
            pass  # endpoint may not exist yet

        payload = {
            "message_id": msg_id,
            "sender": "bwahlquist@nevadaballet.org",
            "subject": f"Test: {pdf.name}",
            "body": "",
            "attachments": [{"filename": pdf.name, "data": b64}],
        }
        try:
            resp = requests.post(f"{server_url}/api/pipeline/nbt", json=payload, timeout=30)
            result = resp.json()
            status = result.get("status", "?")
            if status in ("ok", "skipped"):
                events = result.get("events_stored", "?")
                print(f"  [{i+1}/{len(pdfs)}] ✓ {pdf.name}: {events} events")
            else:
                print(f"  [{i+1}/{len(pdfs)}] ✗ {pdf.name}: {status} — {result}")
                failures += 1
        except Exception as e:
            print(f"  [{i+1}/{len(pdfs)}] ✗ {pdf.name}: request failed: {e}")
            failures += 1

    if failures == 0:
        print(f"\n✓ All PDFs accepted by test server.")
        print(f"  View results: open http://schedule-test.k3s.local/admin")
        import subprocess
        subprocess.run(["open", "http://schedule-test.k3s.local/admin"], check=False)
    else:
        print(f"\n✗ {failures} PDFs rejected. Check logs on test server.")

    return failures

# In main(), add branch:
# if args.visual:
#     failures = run_visual(pdfs)
#     sys.exit(1 if failures > 0 else 0)
```

**Step 2: Run visual mode**

```bash
python3 tools/test_parser.py --visual
```

Expected: Browser opens to `http://schedule-test.k3s.local/admin`, week view showing parsed events.

**Step 3: Manually browse through weeks in the admin UI**

Navigate through each week. Verify events look correct (right shows, right times). Any that look wrong, note the PDF name, fix the parser, re-run `--fast` until 100/100, then `--visual` again.

**Step 4: Final commit**

```bash
git -C /Users/brickson/workspace-v5 add Projects/nbt-schedule-service/tools/test_parser.py
git -C /Users/brickson/workspace-v5 commit -m "feat(nbt): add --visual mode to test harness"
```

---

## Completion Checklist

- [ ] `tools/fetch_corpus.py` downloads 100+ schedule PDFs
- [ ] `tools/test_parser.py --fast` reports 100/100 pass with 0 failures
- [ ] `tools/test_parser.py --report` generates clean HTML showing sensible events
- [ ] `pytest tests/` still passes (no regressions to parser)
- [ ] `NBT_SCHEMA` env var works — `nbt_test` schema isolated from production
- [ ] Test server running at `http://schedule-test.k3s.local`
- [ ] `tools/test_parser.py --visual` posts all PDFs and admin UI looks correct
