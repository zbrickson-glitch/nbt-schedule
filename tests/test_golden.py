"""
Golden file regression tests for the NBT schedule parser.

Each JSON in tests/fixtures/golden/ was manually approved via tools/review.py.
This test re-runs the parser against the source PDF and asserts exact match.

To add a new golden file:
    python tools/review.py --pdf tests/fixtures/pdfs/<file>.pdf

To re-run all golden tests:
    venv/bin/pytest tests/test_golden.py -v
"""
import json
from datetime import date
from pathlib import Path

import pytest

from app.parsers.schedule import parse_schedule_pdf

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"
PDF_DIR = Path(__file__).parent / "fixtures" / "pdfs"


def _load_golden_files():
    if not GOLDEN_DIR.exists():
        return []
    return sorted(GOLDEN_DIR.glob("*.json"))


def _event_to_dict(e) -> dict:
    return {
        "time_start": str(e.time_start),
        "time_end": str(e.time_end),
        "studio": e.studio,
        "show": e.show,
        "cast_type": e.cast_type,
        "staff": e.staff,
        "notes": e.notes,
        "event_type": e.event_type,
    }


def _fitting_to_dict(f) -> dict:
    return {
        "time_start": str(f.time_start),
        "time_end": str(f.time_end),
        "where": f.where,
        "show": f.show,
        "dancer": f.dancer,
        "staff": f.staff,
        "notes": f.notes,
        "event_type": f.event_type,
    }


@pytest.mark.parametrize(
    "golden_path",
    _load_golden_files(),
    ids=lambda p: p.stem,
)
def test_golden(golden_path):
    with open(golden_path) as f:
        golden = json.load(f)

    pdf_path = PDF_DIR / golden["source_pdf"]
    if not pdf_path.exists():
        pytest.skip(f"PDF not in fixtures: {pdf_path.name} — run tools/review.py to download")

    result = parse_schedule_pdf(str(pdf_path))

    # Date
    assert result.date == date.fromisoformat(golden["date"]), (
        f"Date mismatch: got {result.date}, expected {golden['date']}"
    )

    # Events
    actual_events = [_event_to_dict(e) for e in result.events]
    assert actual_events == golden["events"], (
        f"Events mismatch for {golden['date']}:\n"
        f"Expected {len(golden['events'])} events, got {len(actual_events)}\n"
        f"Diff — unexpected: {[e for e in actual_events if e not in golden['events']]}\n"
        f"Diff — missing:    {[e for e in golden['events'] if e not in actual_events]}"
    )

    # Fittings
    actual_fittings = [_fitting_to_dict(f) for f in result.fittings]
    assert actual_fittings == golden["fittings"], (
        f"Fittings mismatch for {golden['date']}: "
        f"expected {len(golden['fittings'])}, got {len(actual_fittings)}"
    )
