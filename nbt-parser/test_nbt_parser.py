"""
Tests for nbt-parser service.

Run: pytest test_nbt_parser.py -v
"""

import base64
import json
import os
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

# Set test env vars before importing modules
os.environ["SKIP_GCAL"] = "1"
os.environ["DASHSCOPE_API_KEY"] = "test-key"

from schedule_parser import (
    parse_filename_date,
    parse_header_date,
    parse_time_range,
    is_schedule_pdf,
    parse_schedule_pdf,
)
from casting_parser import extract_pdf_text, parse_casting_pdf
from discord_preview import (
    format_schedule_preview,
    format_casting_preview,
    format_datetime,
    format_time_only,
)
from calendar_writer import _add_tz_if_missing


# ============================================================
# Schedule Parser Tests
# ============================================================

class TestParseFilenameDate:
    def test_standard_format(self):
        result = parse_filename_date("Tuesday 2.10.26 Artist Daily Schedule.pdf")
        assert result == datetime(2026, 2, 10)

    def test_two_digit_month(self):
        result = parse_filename_date("Thursday 12.11.25 Schedule.pdf")
        assert result == datetime(2025, 12, 11)

    def test_four_digit_year(self):
        result = parse_filename_date("Monday 3.5.2026 Schedule.pdf")
        assert result == datetime(2026, 3, 5)

    def test_no_date(self):
        result = parse_filename_date("Nutcracker Casting.pdf")
        assert result is None

    def test_path_with_directory(self):
        result = parse_filename_date("/uploads/Tuesday 2.10.26 Schedule.pdf")
        assert result == datetime(2026, 2, 10)


class TestParseHeaderDate:
    def test_standard_format(self):
        text = "Thursday, December 11 - NBT Dancer Schedule at The Smith Center"
        result = parse_header_date(text)
        assert result is not None
        assert result.month == 12
        assert result.day == 11

    def test_no_match(self):
        result = parse_header_date("No date here")
        assert result is None


class TestParseTimeRange:
    def test_pm_range(self):
        base = datetime(2026, 2, 10)
        start, end = parse_time_range("1:00 - 2:20pm", base)
        assert start.hour == 13
        assert start.minute == 0
        assert end.hour == 14
        assert end.minute == 20

    def test_with_annotation(self):
        base = datetime(2026, 2, 10)
        start, end = parse_time_range("1:00 - 2:20pm (80/10)", base)
        assert start.hour == 13
        assert end.hour == 14

    def test_morning_range(self):
        base = datetime(2026, 2, 10)
        start, end = parse_time_range("9:00 - 10:15am", base)
        assert start.hour == 9
        assert end.hour == 10

    def test_invalid_time(self):
        base = datetime(2026, 2, 10)
        with pytest.raises(ValueError):
            parse_time_range("invalid", base)

    def test_evening_range(self):
        base = datetime(2026, 2, 10)
        start, end = parse_time_range("5:30 - 6:50pm", base)
        assert start.hour == 17
        assert start.minute == 30
        assert end.hour == 18
        assert end.minute == 50


class TestAddTzIfMissing:
    def test_adds_offset(self):
        result = _add_tz_if_missing("2026-02-10T09:00:00")
        assert result == "2026-02-10T09:00:00-07:00"

    def test_preserves_existing(self):
        result = _add_tz_if_missing("2026-02-10T09:00:00-05:00")
        assert result == "2026-02-10T09:00:00-05:00"

    def test_preserves_utc(self):
        result = _add_tz_if_missing("2026-02-10T09:00:00Z")
        assert result == "2026-02-10T09:00:00Z"


# ============================================================
# Schedule PDF Parsing (with mock PDF)
# ============================================================

class TestIsSchedulePdf:
    @patch("schedule_parser.pdfplumber")
    def test_schedule_detected(self, mock_pdfplumber):
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [["Time", "Where", "What", "Staff", "Cast", "Notes"]]
        ]
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber.open.return_value = mock_pdf

        assert is_schedule_pdf(b"fake pdf bytes") is True

    @patch("schedule_parser.pdfplumber")
    def test_casting_not_detected(self, mock_pdfplumber):
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [["Role", "Cast A", "Cast B"]]
        ]
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber.open.return_value = mock_pdf

        assert is_schedule_pdf(b"fake pdf bytes") is False


class TestParseSchedulePdf:
    @patch("schedule_parser.pdfplumber")
    def test_basic_parsing(self, mock_pdfplumber):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Thursday, February 10 - NBT Dancer Schedule"
        mock_page.extract_tables.return_value = [[
            ["Time", "Where", "What", "Staff", "Cast", "Notes"],
            ["9:00 - 10:15am", "Troesh Studio", "Company Class", "Smith", "All Dancers", ""],
            ["10:30 - 12:00pm", "Stage", "Act II Run", "Jones", "Brickson, Lee", "Full run"],
            ["1:00 - 2:30pm", "Stage", "Snow Scene", "Brown", "Johnson, Davis", ""],
        ]]
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber.open.return_value = mock_pdf

        result = parse_schedule_pdf(b"fake", "Tuesday 2.10.26 Schedule.pdf")

        assert result["event_count"] == 3
        assert result["filtered_count"] == 2  # Company Class (all dancers) + Act II (Brickson)
        assert result["schedule_date"] == "2026-02-10"

        # Check that filtered events match correctly
        filtered_titles = [e['title'] for e in result["filtered_events"]]
        assert any("Company Class" in t for t in filtered_titles)
        assert any("Act II" in t for t in filtered_titles)

    @patch("schedule_parser.pdfplumber")
    def test_skip_break_rows(self, mock_pdfplumber):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""
        mock_page.extract_tables.return_value = [[
            ["Time", "Where", "What", "Staff", "Cast", "Notes"],
            ["BREAK", "", "", "", "", ""],
            ["9:00 - 10:00am", "Studio", "Warm Up", "", "All Dancers", ""],
        ]]
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber.open.return_value = mock_pdf

        result = parse_schedule_pdf(b"fake", "Tuesday 2.10.26 Schedule.pdf")
        assert result["event_count"] == 1


# ============================================================
# Casting Parser Tests
# ============================================================

class TestCastingParser:
    @patch("casting_parser.call_llm")
    @patch("casting_parser.extract_pdf_text")
    def test_llm_success(self, mock_extract, mock_llm):
        mock_extract.return_value = "Nutcracker casting: Sugar Plum - Smith, Cavalier - Brickson"
        mock_llm.return_value = {
            "show": "Nutcracker",
            "roster": [
                {"role": "Sugar Plum", "dancers": ["Smith, Jane"]},
                {"role": "Cavalier", "dancers": ["Brickson, Zach", "Lee, Mike"]},
            ],
            "notes": "",
        }

        result = parse_casting_pdf(b"fake pdf", "Nutcracker Casting.pdf")
        assert result["show"] == "Nutcracker"
        assert result["llm_used"] is True
        assert "Cavalier" in result["your_roles"]
        assert len(result["roster"]) == 2

    @patch("casting_parser.call_llm")
    @patch("casting_parser.extract_pdf_text")
    def test_llm_failure_fallback(self, mock_extract, mock_llm):
        mock_extract.return_value = "Some raw casting text that LLM can't parse"
        mock_llm.return_value = None

        result = parse_casting_pdf(b"fake pdf", "Casting.pdf")
        assert result["llm_used"] is False
        assert result["error"] is not None
        assert "raw text" in result["preview"].lower() or "raw text" in (result.get("error") or "").lower()

    @patch("casting_parser.extract_pdf_text")
    def test_empty_pdf(self, mock_extract):
        mock_extract.return_value = ""
        result = parse_casting_pdf(b"fake pdf", "Empty.pdf")
        assert result["error"] is not None
        assert result["roster"] == []


# ============================================================
# Discord Preview Tests
# ============================================================

class TestDiscordPreview:
    def test_format_datetime_basic(self):
        result = format_datetime("2026-02-10T09:00:00")
        assert "Feb" in result
        assert "10" in result
        assert "9:00" in result

    def test_format_time_only(self):
        result = format_time_only("2026-02-10T14:30:00")
        assert "2:30" in result
        assert "PM" in result

    def test_schedule_preview(self):
        events = [
            {
                "start": "2026-02-10T09:00:00",
                "end": "2026-02-10T10:15:00",
                "title": "9a-10:15a Company Class",
                "location": "Troesh Studio",
                "dancer_match": True,
            },
            {
                "start": "2026-02-10T10:30:00",
                "end": "2026-02-10T12:00:00",
                "title": "10:30a-12p Act II Run",
                "location": "Stage",
                "dancer_match": False,
            },
        ]
        filtered = [events[0]]

        preview = format_schedule_preview(
            events=events,
            filtered_events=filtered,
            schedule_date="2026-02-10",
            subject="Artistic Schedules for 2/10",
        )
        assert "Artistic Schedules" in preview
        assert "Company Class" in preview
        assert "2 events" in preview
        assert "1 yours" in preview

    def test_schedule_preview_empty(self):
        preview = format_schedule_preview([], [], "2026-02-10")
        assert "No schedule events" in preview

    def test_casting_preview_with_roles(self):
        roster = [
            {"role": "Sugar Plum", "dancers": ["Smith, Jane"]},
            {"role": "Cavalier", "dancers": ["Brickson, Zach", "Lee, Mike"]},
        ]
        preview = format_casting_preview(
            roster=roster,
            your_roles=["Cavalier"],
            show="Nutcracker",
        )
        assert "Nutcracker" in preview
        assert "Cavalier" in preview
        assert "You: Cavalier" in preview

    def test_casting_preview_not_listed(self):
        roster = [{"role": "Sugar Plum", "dancers": ["Smith, Jane"]}]
        preview = format_casting_preview(roster=roster, your_roles=[], show="Swan Lake")
        assert "not listed" in preview

    def test_casting_preview_raw_fallback(self):
        preview = format_casting_preview(
            roster=[],
            your_roles=[],
            show="Unknown",
            raw_preview="Some raw PDF text here",
        )
        assert "raw text" in preview.lower()
        assert "Some raw PDF text" in preview


# ============================================================
# FastAPI Endpoint Tests
# ============================================================

class TestAPI:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)

    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "nbt-parser"

    def test_process_no_pdfs(self, client):
        response = client.post("/process", json={"pdfs": []})
        assert response.status_code == 400

    @patch("main.is_schedule_pdf")
    @patch("main.parse_schedule_pdf")
    def test_process_schedule(self, mock_parse, mock_classify, client):
        mock_classify.return_value = True
        mock_parse.return_value = {
            "events": [
                {
                    "start": "2026-02-10T09:00:00",
                    "end": "2026-02-10T10:15:00",
                    "title": "Company Class",
                    "location": "Studio",
                    "description": "",
                    "dancer_match": True,
                }
            ],
            "filtered_events": [
                {
                    "start": "2026-02-10T09:00:00",
                    "end": "2026-02-10T10:15:00",
                    "title": "Company Class",
                    "location": "Studio",
                    "description": "",
                    "dancer_match": True,
                }
            ],
            "schedule_date": "2026-02-10",
            "event_count": 1,
            "filtered_count": 1,
        }

        # Create a minimal valid PDF-like base64
        fake_pdf_b64 = base64.b64encode(b"fake pdf content").decode()

        response = client.post("/process", json={
            "pdfs": [{"filename": "Tuesday 2.10.26 Schedule.pdf", "base64": fake_pdf_b64}],
            "sender": "bwahlquist@nevadaballet.org",
            "subject": "Artistic Schedules for 2/10",
        })

        assert response.status_code == 200
        data = response.json()
        assert "schedule" in data["pdf_types"]
        assert data["schedules"] is not None
        assert "Company Class" in data["schedules"]["preview"]

    @patch("main.is_schedule_pdf")
    @patch("main.parse_casting_pdf")
    def test_process_casting(self, mock_parse, mock_classify, client):
        mock_classify.return_value = False
        mock_parse.return_value = {
            "roster": [{"role": "Cavalier", "dancers": ["Brickson, Zach"]}],
            "your_roles": ["Cavalier"],
            "show": "Nutcracker",
            "notes": "",
            "llm_used": True,
            "error": None,
        }

        fake_pdf_b64 = base64.b64encode(b"fake pdf content").decode()

        response = client.post("/process", json={
            "pdfs": [{"filename": "Nutcracker Casting.pdf", "base64": fake_pdf_b64}],
            "sender": "bwahlquist@nevadaballet.org",
            "subject": "Nutcracker Casting",
        })

        assert response.status_code == 200
        data = response.json()
        assert "casting" in data["pdf_types"]
        assert data["castings"] is not None
        assert "Cavalier" in data["castings"]["your_roles"]


# ============================================================
# Calendar Writer Tests
# ============================================================

class TestCalendarWriter:
    @patch("calendar_writer._run_gog")
    def test_create_events_gog_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("gog not found")

        from calendar_writer import create_events
        result = create_events(
            [{"start": "2026-02-10T09:00:00", "end": "2026-02-10T10:00:00", "title": "Test"}],
            [],
            "2026-02-10",
        )
        assert result["gcal_skipped"] is True
        assert result["events_created"] == 0

    @patch("calendar_writer._run_gog")
    def test_create_events_success(self, mock_run):
        # First call = version check, second = delete query, third+ = create
        version_result = MagicMock(returncode=0, stdout="0.9.0", stderr="")
        delete_query_result = MagicMock(returncode=0, stdout='{"events": []}', stderr="")
        create_result = MagicMock(returncode=0, stdout="Created", stderr="")
        mock_run.side_effect = [version_result, delete_query_result, create_result]

        from calendar_writer import create_events
        events = [{"start": "2026-02-10T09:00:00", "end": "2026-02-10T10:00:00", "title": "Test"}]
        result = create_events(events, events, "2026-02-10")

        assert result["events_created"] == 1
        assert result["your_events"] == 1
