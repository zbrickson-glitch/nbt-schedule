"""
Tests for the unknown/MAAG PDF fallback pipeline in the ingest router.

The fallback pipeline (PHASE 2.5) handles PDFs that classify as UNKNOWN or MAAG:
  1. Try deterministic parser (parse_schedule_pdf_multi)
  2. If that fails or returns no events, store 0 events
  3. Always fire send_unknown_format_alert
  4. Record filename in unknown_pdfs

All DB, parser, and external calls are mocked so tests run without infrastructure.
"""
import base64
from contextlib import contextmanager
from datetime import date, time
from typing import Optional
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.parsers.classifier import PdfType
from app.parsers.schedule import ParsedSchedule, ScheduleEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_PDF_B64 = base64.b64encode(b"fake-pdf-bytes").decode()


def _make_payload(filename: str, email_id: str = "email-001", subject: str = "Test Email"):
    """Build a minimal ingest payload with one attachment."""
    return {
        "email_id": email_id,
        "subject": subject,
        "body": "",
        "attachments": [
            {"filename": filename, "data": FAKE_PDF_B64}
        ],
    }


def _mock_db_no_existing():
    """Return a mock get_db context manager that reports no existing events."""

    @contextmanager
    def _fake_get_db():
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = None  # no existing events / no idempotency hit
        conn.cursor.return_value = cur
        yield conn

    return _fake_get_db


def _mock_db_existing():
    """Return a mock get_db context manager that reports an existing event (idempotency)."""

    @contextmanager
    def _fake_get_db():
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {"id": 42}  # existing event found
        conn.cursor.return_value = cur
        yield conn

    return _fake_get_db


def _parsed_schedule_with_events(n: int = 2) -> ParsedSchedule:
    """Return a fake ParsedSchedule with n rehearsal events."""
    events = [
        ScheduleEvent(
            time_start=time(9 + i, 0),
            time_end=time(10 + i, 0),
            studio="Studio A",
            show="ZIGZAG",
            staff="Teacher",
            cast_type="Full Call",
            notes=None,
        )
        for i in range(n)
    ]
    return ParsedSchedule(
        date=date(2026, 3, 5),
        events=events,
        fittings=[],
    )


# ---------------------------------------------------------------------------
# Shared patch targets
# ---------------------------------------------------------------------------

PATCH_GET_DB = "app.routers.ingest.get_db"
PATCH_CLASSIFY = "app.routers.ingest.classify_pdf"
PATCH_PARSE_MULTI = "app.routers.ingest.parse_schedule_pdf"
PATCH_ALERT = "app.routers.ingest.send_unknown_format_alert"
PATCH_REGEN = "app.routers.ingest._regenerate_all_feeds"
PATCH_GCAL = "app.routers.ingest.get_gcal_calendar_id"


# ---------------------------------------------------------------------------
# Test 1: UNKNOWN PDF routes to fallback pipeline
# ---------------------------------------------------------------------------

def test_unknown_pdf_routes_to_fallback_parse_schedule_pdf_multi_called():
    """classify_pdf returning UNKNOWN means parse_schedule_pdf_multi is called."""
    with patch(PATCH_GET_DB, _mock_db_no_existing()), \
         patch(PATCH_CLASSIFY, return_value=PdfType.UNKNOWN), \
         patch(PATCH_PARSE_MULTI, return_value=_parsed_schedule_with_events(2)) as mock_multi, \
         patch(PATCH_ALERT), \
         patch(PATCH_REGEN), \
         patch(PATCH_GCAL, return_value=""):
        client = TestClient(app)
        response = client.post("/api/ingest", json=_make_payload("mystery-file.pdf"))

    assert response.status_code == 200
    mock_multi.assert_called_once()


# ---------------------------------------------------------------------------
# Test 2: Deterministic succeeds on unknown PDF
# ---------------------------------------------------------------------------

def test_deterministic_succeeds_on_unknown_pdf():
    """When parse_schedule_pdf_multi succeeds, events are stored and method is deterministic_on_unknown."""
    with patch(PATCH_GET_DB, _mock_db_no_existing()), \
         patch(PATCH_CLASSIFY, return_value=PdfType.UNKNOWN), \
         patch(PATCH_PARSE_MULTI, return_value=_parsed_schedule_with_events(2)), \
         patch(PATCH_ALERT) as mock_alert, \
         patch(PATCH_REGEN), \
         patch(PATCH_GCAL, return_value=""):
        client = TestClient(app)
        response = client.post("/api/ingest", json=_make_payload("mystery-file.pdf"))

    assert response.status_code == 200
    data = response.json()

    # Events were stored via deterministic path
    assert data["events_created"] == 2

    # unknown_pdfs must list the filename
    assert "mystery-file.pdf" in data["unknown_pdfs"]

    # Alert fires regardless
    mock_alert.assert_called_once()


# ---------------------------------------------------------------------------
# Test 3: Deterministic fails — 0 events stored, alert still fires
# ---------------------------------------------------------------------------

def test_deterministic_fails_zero_events_stored():
    """When parse_schedule_pdf_multi raises ValueError, 0 events are stored and alert fires."""
    with patch(PATCH_GET_DB, _mock_db_no_existing()), \
         patch(PATCH_CLASSIFY, return_value=PdfType.UNKNOWN), \
         patch(PATCH_PARSE_MULTI, side_effect=ValueError("Cannot parse date from PDF")), \
         patch(PATCH_ALERT) as mock_alert, \
         patch(PATCH_REGEN), \
         patch(PATCH_GCAL, return_value=""):
        client = TestClient(app)
        response = client.post("/api/ingest", json=_make_payload("multi-day-schedule.pdf"))

    assert response.status_code == 200
    data = response.json()

    # No events extracted
    assert data["events_created"] == 0

    # Alert fires regardless
    mock_alert.assert_called_once()


# ---------------------------------------------------------------------------
# Test 4: Deterministic returns no events — alert still fires
# ---------------------------------------------------------------------------

def test_deterministic_no_events_alert_fires():
    """When parse_schedule_pdf_multi returns no events, 0 events are stored but alert fires."""
    with patch(PATCH_GET_DB, _mock_db_no_existing()), \
         patch(PATCH_CLASSIFY, return_value=PdfType.UNKNOWN), \
         patch(PATCH_PARSE_MULTI, side_effect=ValueError("Cannot parse")), \
         patch(PATCH_ALERT) as mock_alert, \
         patch(PATCH_REGEN), \
         patch(PATCH_GCAL, return_value=""):
        client = TestClient(app)
        response = client.post("/api/ingest", json=_make_payload("mystery-file.pdf"))

    assert response.status_code == 200
    data = response.json()

    assert data["events_created"] == 0

    # Alert must still fire even when nothing was extracted
    mock_alert.assert_called_once()


# ---------------------------------------------------------------------------
# Test 5: MAAG type routes through the same fallback pipeline
# ---------------------------------------------------------------------------

def test_maag_pdf_routes_to_fallback_pipeline():
    """classify_pdf returning MAAG goes through the same unknown fallback pipeline."""
    with patch(PATCH_GET_DB, _mock_db_no_existing()), \
         patch(PATCH_CLASSIFY, return_value=PdfType.MAAG), \
         patch(PATCH_PARSE_MULTI, side_effect=ValueError("No daily events in MAAG")), \
         patch(PATCH_ALERT) as mock_alert, \
         patch(PATCH_REGEN), \
         patch(PATCH_GCAL, return_value=""):
        client = TestClient(app)
        response = client.post(
            "/api/ingest",
            json=_make_payload("February Month at a Glance.pdf", email_id="maag-001"),
        )

    assert response.status_code == 200
    data = response.json()

    # Filename appears in unknown_pdfs
    assert "February Month at a Glance.pdf" in data["unknown_pdfs"]

    # Alert fires
    mock_alert.assert_called_once()


# ---------------------------------------------------------------------------
# Test 6: Alert fires whether extraction succeeds or fails
# ---------------------------------------------------------------------------

def test_alert_fires_when_deterministic_succeeds():
    """Alert is sent even when deterministic parser succeeds on unknown PDF."""
    with patch(PATCH_GET_DB, _mock_db_no_existing()), \
         patch(PATCH_CLASSIFY, return_value=PdfType.UNKNOWN), \
         patch(PATCH_PARSE_MULTI, return_value=_parsed_schedule_with_events(1)), \
         patch(PATCH_ALERT) as mock_alert, \
         patch(PATCH_REGEN), \
         patch(PATCH_GCAL, return_value=""):
        client = TestClient(app)
        client.post("/api/ingest", json=_make_payload("weird-schedule.pdf"))

    mock_alert.assert_called_once()
    # Alert should mention the filename
    call_kwargs = mock_alert.call_args
    assert call_kwargs is not None
    args, kwargs = call_kwargs
    filename_arg = args[0] if args else kwargs.get("filename", "")
    assert "weird-schedule.pdf" in filename_arg


def test_alert_fires_when_parser_fails():
    """Alert is sent even when the deterministic parser fails to extract any events."""
    with patch(PATCH_GET_DB, _mock_db_no_existing()), \
         patch(PATCH_CLASSIFY, return_value=PdfType.UNKNOWN), \
         patch(PATCH_PARSE_MULTI, side_effect=ValueError("Cannot parse")), \
         patch(PATCH_ALERT) as mock_alert, \
         patch(PATCH_REGEN), \
         patch(PATCH_GCAL, return_value=""):
        client = TestClient(app)
        client.post("/api/ingest", json=_make_payload("garbage.pdf"))

    mock_alert.assert_called_once()


# ---------------------------------------------------------------------------
# Test 7: unknown_pdfs populated in IngestResult
# ---------------------------------------------------------------------------

def test_unknown_pdfs_populated_in_result():
    """IngestResult.unknown_pdfs lists every unknown/MAAG attachment filename."""
    # Only one attachment is classified as UNKNOWN — the other two return CASTING/SCHEDULE
    # and should NOT appear in unknown_pdfs.
    def _classify_side_effect(filename):
        if "maag" in filename.lower():
            return PdfType.UNKNOWN
        return PdfType.CASTING  # other files go to casting path, not unknown

    payload = {
        "email_id": "multi-001",
        "subject": "Test",
        "body": "",
        "attachments": [
            {"filename": "Company B RR.pdf", "data": FAKE_PDF_B64},
            {"filename": "maag-unknown.pdf", "data": FAKE_PDF_B64},
        ],
    }

    with patch(PATCH_GET_DB, _mock_db_no_existing()), \
         patch(PATCH_CLASSIFY, side_effect=_classify_side_effect), \
         patch("app.routers.ingest.parse_casting_pdf") as mock_casting, \
         patch("app.routers.ingest._upsert_casting"), \
         patch(PATCH_PARSE_MULTI, side_effect=ValueError("Cannot parse")), \
         patch(PATCH_ALERT), \
         patch(PATCH_REGEN), \
         patch(PATCH_GCAL, return_value=""):
        mock_casting.return_value = MagicMock(show="COMPANY B", sections=[])
        client = TestClient(app)
        response = client.post("/api/ingest", json=payload)

    assert response.status_code == 200
    data = response.json()

    assert data["unknown_pdfs"] == ["maag-unknown.pdf"]
    # Casting file should NOT appear in unknown_pdfs
    assert "Company B RR.pdf" not in data["unknown_pdfs"]


# ---------------------------------------------------------------------------
# Test 8: Idempotency still works for unknown PDFs
# ---------------------------------------------------------------------------

def test_idempotency_skips_already_processed_unknown_pdf():
    """If the email_id is already in the DB, ingest returns skipped=True for unknown PDFs too."""
    with patch(PATCH_GET_DB, _mock_db_existing()), \
         patch(PATCH_CLASSIFY, return_value=PdfType.UNKNOWN), \
         patch(PATCH_PARSE_MULTI) as mock_multi, \
         patch(PATCH_ALERT) as mock_alert, \
         patch(PATCH_REGEN), \
         patch(PATCH_GCAL, return_value=""):
        client = TestClient(app)
        response = client.post("/api/ingest", json=_make_payload("mystery-file.pdf"))

    assert response.status_code == 200
    data = response.json()

    # Should be skipped immediately — no parsing should occur
    assert data["skipped"] is True
    assert data["status"] == "skipped"

    mock_multi.assert_not_called()
    mock_alert.assert_not_called()


# ---------------------------------------------------------------------------
# Test 9: Multiple unknown PDFs — each gets its own entry in unknown_pdfs
# ---------------------------------------------------------------------------

def test_multiple_unknown_pdfs_each_in_unknown_pdfs():
    """When two unknown PDFs are in the email, each appears in unknown_pdfs."""
    payload = {
        "email_id": "multi-unknown-001",
        "subject": "Two weird PDFs",
        "body": "",
        "attachments": [
            {"filename": "weird-a.pdf", "data": FAKE_PDF_B64},
            {"filename": "weird-b.pdf", "data": FAKE_PDF_B64},
        ],
    }

    parse_responses = iter([
        _parsed_schedule_with_events(1),  # first PDF extracts 1 event
        ValueError("Cannot parse"),       # second PDF fails
    ])

    def _parse_side_effect(path):
        result = next(parse_responses)
        if isinstance(result, Exception):
            raise result
        return result

    with patch(PATCH_GET_DB, _mock_db_no_existing()), \
         patch(PATCH_CLASSIFY, return_value=PdfType.UNKNOWN), \
         patch(PATCH_PARSE_MULTI, side_effect=_parse_side_effect), \
         patch(PATCH_ALERT) as mock_alert, \
         patch(PATCH_REGEN), \
         patch(PATCH_GCAL, return_value=""):
        client = TestClient(app)
        response = client.post("/api/ingest", json=payload)

    assert response.status_code == 200
    data = response.json()

    # Both filenames in unknown_pdfs
    assert set(data["unknown_pdfs"]) == {"weird-a.pdf", "weird-b.pdf"}

    # Alert fires once per unknown PDF
    assert mock_alert.call_count == 2

    # First PDF extracted 1 event, second extracted 0
    assert data["events_created"] == 1


# ---------------------------------------------------------------------------
# Test 10: Known SCHEDULE type does NOT appear in unknown_pdfs
# ---------------------------------------------------------------------------

def test_known_schedule_pdf_not_in_unknown_pdfs():
    """A file classified as SCHEDULE goes through Phase 2, not the fallback pipeline."""
    with patch(PATCH_GET_DB, _mock_db_no_existing()), \
         patch(PATCH_CLASSIFY, return_value=PdfType.SCHEDULE), \
         patch("app.routers.ingest.parse_schedule_pdf",
               return_value=_parsed_schedule_with_events(1)), \
         patch("app.routers.ingest._store_schedule_events", return_value=1), \
         patch(PATCH_ALERT) as mock_alert, \
         patch(PATCH_REGEN), \
         patch(PATCH_GCAL, return_value=""):
        client = TestClient(app)
        response = client.post(
            "/api/ingest",
            json=_make_payload("Monday 3.2.26 Artist Daily Schedule.pdf"),
        )

    assert response.status_code == 200
    data = response.json()

    # Known schedule: unknown_pdfs must be empty
    assert data["unknown_pdfs"] == []

    # No alert for known schedule PDFs
    mock_alert.assert_not_called()
