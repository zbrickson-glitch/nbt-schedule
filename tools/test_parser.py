#!/usr/bin/env python3
"""
NBT parser test harness.

Modes:
  --fast    Run parse_schedule_pdf() directly on corpus, report pass/fail (default)
  --report  Generate HTML side-by-side comparison report (pdftotext vs parsed)
  --visual  POST to test server, view results in admin UI

Usage:
    python3 tools/test_parser.py              # fast mode, all corpus PDFs
    python3 tools/test_parser.py --fast       # explicit fast mode
    python3 tools/test_parser.py --report     # generate HTML report
    python3 tools/test_parser.py --visual     # POST to test server
    python3 tools/test_parser.py --pdf path/to/specific.pdf  # single file
    python3 tools/test_parser.py --verbose    # show full tracebacks
"""
import argparse
import subprocess
import sys
import traceback
from pathlib import Path

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
                    results["warn"].append((pdf, "0 events (likely not a schedule PDF)"))
            else:
                results["pass"].append((pdf, parsed.date, len(parsed.events), len(parsed.fittings)))

        except ValueError as e:
            msg = str(e)
            if "Could not parse date" in msg:
                # Non-schedule PDF (role responsibilities, casting, etc.) - expected skip
                results["warn"].append((pdf, "Not a schedule PDF (no date found) — OK to ignore"))
            else:
                tb = traceback.format_exc()
                results["fail"].append((pdf, msg, tb))
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

    if results["warn"]:
        print(f"{YELLOW}{BOLD}WARNINGS:{RESET}")
        for item in results["warn"]:
            pdf, msg = item[0], item[1]
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
            "raw_text": raw_text[:3000],
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
.warn .pdf-header {{ border-left: 4px solid #ff9800; }}
.pdf-body {{ display: none; padding: 0 16px 16px; }}
.pdf-body.open {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
pre {{ font-size: 11px; white-space: pre-wrap; word-break: break-word; background: #f5f5f5; padding: 8px; border-radius: 4px; max-height: 400px; overflow-y: auto; }}
table {{ border-collapse: collapse; font-size: 12px; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 4px 8px; text-align: left; }}
th {{ background: #FFF5F7; }}
.badge-ok {{ background: #e8f5e9; color: #388e3c; padding: 2px 8px; border-radius: 12px; font-size: 12px; }}
.badge-fail {{ background: #fce4ec; color: #c62828; padding: 2px 8px; border-radius: 12px; font-size: 12px; }}
.badge-warn {{ background: #fff3e0; color: #e65100; padding: 2px 8px; border-radius: 12px; font-size: 12px; }}
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
    for r in sorted(rows, key=lambda x: (x["status"] != "fail", x["status"] != "warn")):
        if r["status"] == "ok":
            badge = '<span class="badge-ok">✓ OK</span>'
        elif r["status"] == "warn":
            badge = '<span class="badge-warn">⚠ WARN</span>'
        else:
            badge = '<span class="badge-fail">✗ FAIL</span>'
        html += f"""<div class="pdf-card {r['status']}" onclick="var b=this.querySelector('.pdf-body');b.classList.toggle('open')">
  <div class="pdf-header"><span><strong>{r['name']}</strong> &nbsp; {r['summary']}</span>{badge}</div>
  <div class="pdf-body">
    <div><h4>PDF Text (pdftotext)</h4><pre>{r['raw_text']}</pre></div>
    <div><h4>Parsed Events</h4>{r['events_html']}</div>
  </div>
</div>
"""
    html += "<script>document.querySelectorAll('.fail .pdf-body, .warn .pdf-body').forEach(b=>b.classList.add('open'))</script></body></html>"

    REPORT_PATH.write_text(html)
    print(f"\n✓ Report written to: {REPORT_PATH}")
    print(f"  Open with: open {REPORT_PATH}")
    subprocess.run(["open", str(REPORT_PATH)], check=False)


# ---------------------------------------------------------------------------
# Visual mode (POST to test server)
# ---------------------------------------------------------------------------

def run_visual(pdfs: list[Path], server_url: str = "http://schedule-test.k3s.local") -> int:
    """POST each PDF to the test server pipeline. Returns failure count."""
    import base64
    import urllib.request
    import json

    failures = 0
    print(f"Posting {len(pdfs)} PDFs to {server_url}/api/pipeline/nbt ...")

    for i, pdf in enumerate(pdfs):
        with open(pdf, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        msg_id = f"test-{pdf.stem}"
        payload = json.dumps({
            "message_id": msg_id,
            "sender": "bwahlquist@nevadaballet.org",
            "subject": f"Test: {pdf.name}",
            "body": "",
            "attachments": [{"filename": pdf.name, "data": b64}],
        }).encode()

        try:
            req = urllib.request.Request(
                f"{server_url}/api/pipeline/nbt",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            status = result.get("status", "?")
            if status in ("ok", "skipped"):
                events = result.get("events_stored", "?")
                print(f"  [{i+1}/{len(pdfs)}] ✓ {pdf.name}: {events} events")
            elif status == "manual":
                # Casting PDFs routed to manual processing — expected, not a failure
                print(f"  [{i+1}/{len(pdfs)}] ℹ {pdf.name}: casting (manual)")
            else:
                print(f"  [{i+1}/{len(pdfs)}] ✗ {pdf.name}: {status}")
                failures += 1
        except Exception as e:
            print(f"  [{i+1}/{len(pdfs)}] ✗ {pdf.name}: {e}")
            failures += 1

    if failures == 0:
        print(f"\n✓ All PDFs accepted by test server.")
        print(f"  View results: open {server_url}/admin")
        subprocess.run(["open", f"{server_url}/admin"], check=False)
    else:
        print(f"\n✗ {failures} PDFs rejected. Check logs on test server.")

    return failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="NBT parser test harness")
    parser.add_argument("--fast", action="store_true", default=True,
                        help="Run parser directly (default)")
    parser.add_argument("--report", action="store_true",
                        help="Generate HTML comparison report")
    parser.add_argument("--visual", action="store_true",
                        help="POST to test server, view in admin UI")
    parser.add_argument("--pdf", help="Test a single PDF file instead of corpus")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show full tracebacks and passed list")
    parser.add_argument("--server", default="http://schedule-test.k3s.local",
                        help="Test server URL for --visual mode")
    args = parser.parse_args()

    if args.pdf:
        pdfs = [Path(args.pdf)]
    else:
        # Load corpus + existing fixtures
        pdfs = sorted(CORPUS_DIR.glob("*.pdf"))
        for p in FIXTURE_DIR.glob("*.pdf"):
            pdfs.append(p)
        pdfs_subdir = FIXTURE_DIR / "pdfs"
        if pdfs_subdir.exists():
            for p in pdfs_subdir.glob("*.pdf"):
                pdfs.append(p)
        pdfs = sorted(set(pdfs))

    if not pdfs:
        print("No PDFs found. Run tools/fetch_corpus.py first.")
        sys.exit(1)

    print(f"Testing {len(pdfs)} PDFs...")

    if args.visual:
        failures = run_visual(pdfs, server_url=args.server)
        sys.exit(1 if failures > 0 else 0)
    elif args.report:
        run_report(pdfs)
    else:
        failures = run_fast(pdfs, verbose=args.verbose)
        sys.exit(1 if failures > 0 else 0)


if __name__ == "__main__":
    main()
