"""
Tests for the NBT daily schedule PDF parser.

Expected counts (from real PDFs):
  Monday 3/2/26:   6 events, 0 fittings
  Thursday 2/26/26: 7 events, 9 fittings
  Friday 2/27/26:  7 events, 4 fittings
"""
from datetime import date, time

import pytest

from app.parsers.schedule import (
    FittingEvent,
    ParsedSchedule,
    ScheduleEvent,
    parse_schedule_pdf,
)


# ---------------------------------------------------------------------------
# _parse_date unit tests
# ---------------------------------------------------------------------------

class TestDateParsing:
    def test_date_with_year(self):
        from app.parsers.schedule import _parse_date
        result = _parse_date("Monday, March 2, 2026 - NBT Artist Daily Schedule")
        assert result == date(2026, 3, 2)

    def test_date_no_year_december(self):
        from app.parsers.schedule import _parse_date
        result = _parse_date("Wednesday, December 10 - NBT Dancer Schedule at The Smith Center")
        assert result is not None
        assert result.month == 12
        assert result.day == 10
        assert result.year == 2025  # most recent past December 10

    def test_date_no_year_with_dash_no_space(self):
        from app.parsers.schedule import _parse_date
        result = _parse_date("Friday, December 26- NBT Dancer Schedule at The Smith Center")
        assert result is not None
        assert result.month == 12
        assert result.day == 26
        assert result.year == 2025  # most recent past December 26

    def test_date_no_match_returns_none(self):
        from app.parsers.schedule import _parse_date
        result = _parse_date("No date here whatsoever")
        assert result is None


# ---------------------------------------------------------------------------
# Monday 3/2/26
# ---------------------------------------------------------------------------

class TestMondaySchedule:
    @pytest.fixture(autouse=True)
    def parsed(self, schedule_monday_pdf):
        self._s = parse_schedule_pdf(schedule_monday_pdf)
        return self._s

    def test_date(self):
        assert self._s.date == date(2026, 3, 2)

    def test_event_count(self):
        assert len(self._s.events) == 6

    def test_fitting_count(self):
        assert len(self._s.fittings) == 0

    def test_first_event_time_start(self):
        assert self._s.events[0].time_start == time(9, 30)

    def test_first_event_show(self):
        assert self._s.events[0].show == "Company Class"

    def test_first_event_type(self):
        assert self._s.events[0].event_type == "rehearsal"

    def test_second_event_show(self):
        assert self._s.events[1].show == "ZIGZAG"

    def test_second_event_cast_type(self):
        assert self._s.events[1].cast_type == "Full Call"

    def test_second_event_time_start(self):
        assert self._s.events[1].time_start == time(11, 15)

    def test_second_event_time_end(self):
        assert self._s.events[1].time_end == time(12, 10)

    def test_third_event_time_start(self):
        """12:15pm event should parse to 12:15 (noon, not midnight)."""
        assert self._s.events[2].time_start == time(12, 15)

    def test_fourth_event_time_start(self):
        """1:15pm event should parse to 13:15."""
        assert self._s.events[3].time_start == time(13, 15)

    def test_fifth_event_show(self):
        assert self._s.events[4].show == "COMPANY B"

    def test_fifth_event_time_start(self):
        assert self._s.events[4].time_start == time(15, 15)

    def test_sixth_event_time_start(self):
        assert self._s.events[5].time_start == time(16, 15)

    def test_no_break_events(self):
        """BREAK rows must not appear in events."""
        shows = [e.show for e in self._s.events]
        assert "BREAK" not in shows

    def test_raw_text_not_empty(self):
        assert len(self._s.raw_text) > 0


# ---------------------------------------------------------------------------
# Thursday 2/26/26
# ---------------------------------------------------------------------------

class TestThursdaySchedule:
    @pytest.fixture(autouse=True)
    def parsed(self, schedule_thursday_pdf):
        self._s = parse_schedule_pdf(schedule_thursday_pdf)
        return self._s

    def test_date(self):
        assert self._s.date == date(2026, 2, 26)

    def test_event_count(self):
        assert len(self._s.events) == 7

    def test_fitting_count(self):
        assert len(self._s.fittings) == 9

    # --- rehearsal events ---

    def test_first_event_show(self):
        assert self._s.events[0].show == "Company Class"

    def test_first_event_time_start(self):
        assert self._s.events[0].time_start == time(9, 30)

    def test_last_event_show(self):
        assert self._s.events[-1].show == "Red Angels"

    def test_last_event_time_start(self):
        assert self._s.events[-1].time_start == time(17, 15)

    def test_last_event_time_end(self):
        assert self._s.events[-1].time_end == time(18, 10)

    def test_event_types_all_rehearsal(self):
        assert all(e.event_type == "rehearsal" for e in self._s.events)

    # --- fittings ---

    def test_first_fitting_dancer(self):
        assert self._s.fittings[0].dancer == "DEROCKER"

    def test_first_fitting_time_start(self):
        assert self._s.fittings[0].time_start == time(11, 15)

    def test_first_fitting_time_end(self):
        assert self._s.fittings[0].time_end == time(11, 35)

    def test_first_fitting_where(self):
        assert self._s.fittings[0].where == "Wardrobe"

    def test_first_fitting_event_type(self):
        assert self._s.fittings[0].event_type == "fitting"

    def test_second_fitting_dancer(self):
        assert self._s.fittings[1].dancer == "KELLEMS"

    def test_third_fitting_dancer(self):
        assert self._s.fittings[2].dancer == "LAUZON"

    def test_fourth_fitting_dancer(self):
        assert self._s.fittings[3].dancer == "DIEHL"

    def test_fifth_fitting_dancer(self):
        assert self._s.fittings[4].dancer == "KNOWLTON"

    def test_sixth_fitting_dancer(self):
        assert self._s.fittings[5].dancer == "ALVAREZ"

    def test_seventh_fitting_dancer(self):
        assert self._s.fittings[6].dancer == "KESTEN"

    def test_seventh_fitting_time_start(self):
        """5:15pm fitting should parse to 17:15."""
        assert self._s.fittings[6].time_start == time(17, 15)

    def test_eighth_fitting_dancer(self):
        assert self._s.fittings[7].dancer == "RAMBO"

    def test_last_fitting_dancer(self):
        assert self._s.fittings[-1].dancer == "MCGRATH"

    def test_last_fitting_time_start(self):
        assert self._s.fittings[-1].time_start == time(17, 55)

    def test_last_fitting_time_end(self):
        assert self._s.fittings[-1].time_end == time(18, 15)

    def test_fitting_show_values(self):
        """All fittings should have a show value."""
        assert all(f.show for f in self._s.fittings)

    def test_fitting_staff_williams(self):
        assert all(f.staff == "Williams" for f in self._s.fittings)

    def test_alvarez_fitting_time_start(self):
        """12:55 - 1:15pm -> 12:55 PM."""
        alvarez = self._s.fittings[5]
        assert alvarez.dancer == "ALVAREZ"
        assert alvarez.time_start == time(12, 55)
        assert alvarez.time_end == time(13, 15)


# ---------------------------------------------------------------------------
# Friday 2/27/26
# ---------------------------------------------------------------------------

class TestFridaySchedule:
    @pytest.fixture(autouse=True)
    def parsed(self, schedule_friday_pdf):
        self._s = parse_schedule_pdf(schedule_friday_pdf)
        return self._s

    def test_date(self):
        assert self._s.date == date(2026, 2, 27)

    def test_event_count(self):
        assert len(self._s.events) == 7

    def test_fitting_count(self):
        assert len(self._s.fittings) == 4

    # --- rehearsal events ---

    def test_first_event_show(self):
        assert self._s.events[0].show == "Company Class"

    def test_first_event_time_start(self):
        assert self._s.events[0].time_start == time(9, 30)

    def test_last_event_show(self):
        assert self._s.events[-1].show == "Red Angels"

    def test_last_event_time_start(self):
        assert self._s.events[-1].time_start == time(17, 15)

    def test_event_types_all_rehearsal(self):
        assert all(e.event_type == "rehearsal" for e in self._s.events)

    # --- fittings ---

    def test_first_fitting_dancer(self):
        assert self._s.fittings[0].dancer == "FULTON"

    def test_first_fitting_time_start(self):
        assert self._s.fittings[0].time_start == time(12, 15)

    def test_second_fitting_dancer(self):
        assert self._s.fittings[1].dancer == "ROBERTS"

    def test_third_fitting_dancer(self):
        assert self._s.fittings[2].dancer == "LYNESS"

    def test_third_fitting_time_start(self):
        """12:55 - 1:10pm -> 12:55 PM."""
        assert self._s.fittings[2].time_start == time(12, 55)

    def test_third_fitting_time_end(self):
        assert self._s.fittings[2].time_end == time(13, 10)

    def test_last_fitting_dancer(self):
        assert self._s.fittings[-1].dancer == "CASTRO"

    def test_last_fitting_time_start(self):
        """1:15 - 1:45pm -> 13:15."""
        assert self._s.fittings[-1].time_start == time(13, 15)

    def test_last_fitting_time_end(self):
        assert self._s.fittings[-1].time_end == time(13, 45)

    def test_fitting_event_types(self):
        assert all(f.event_type == "fitting" for f in self._s.fittings)

    def test_fitting_staff(self):
        assert all(f.staff == "Williams" for f in self._s.fittings)


# ---------------------------------------------------------------------------
# December Nutcracker PDFs
# ---------------------------------------------------------------------------

class TestDecemberNutcrackerPDFs:
    """Tests against real December Nutcracker-season PDFs."""

    def test_dec10_has_events_not_fittings(self, dec10_pdf):
        """Dec 10 table uses 'Where' header — must NOT be classified as fittings."""
        result = parse_schedule_pdf(dec10_pdf)
        assert len(result.events) > 0, (
            f"December rehearsal events should be parsed as events, not fittings. "
            f"Got {len(result.events)} events and {len(result.fittings)} fittings."
        )
        assert result.date is not None

    def test_dec10_company_class_present(self, dec10_pdf):
        result = parse_schedule_pdf(dec10_pdf)
        shows = [e.show for e in result.events]
        assert any("company class" in s.lower() for s in shows), \
            f"Expected Company Class in events, got: {shows}"

    def test_dec26_has_performance_events(self, dec26_pdf):
        result = parse_schedule_pdf(dec26_pdf)
        assert len(result.events) > 0
        shows = [e.show for e in result.events]
        assert any("performance" in s.lower() or "act" in s.lower() for s in shows), \
            f"Expected performance/act events, got: {shows}"


class TestDancersCallRows:
    def test_dancers_call_rows_not_parsed_as_events(self, dec26_pdf):
        """Dec 26 has 'Dancers Call' span rows — must be skipped, not throw errors."""
        result = parse_schedule_pdf(dec26_pdf)
        shows = [e.show.lower() for e in result.events]
        assert not any("dancers call" in s for s in shows), \
            f"Dancers Call rows should be skipped, not parsed as events: {shows}"


# ---------------------------------------------------------------------------
# Defensive bounds checking — short rows
# ---------------------------------------------------------------------------

class TestShortRowDefense:
    def test_parse_schedule_ignores_short_rows(self, schedule_monday_pdf):
        """Rows with fewer than expected columns should be skipped gracefully."""
        # This is an integration test — if the parser encounters a row with
        # fewer columns it should not raise IndexError; it should skip the row.
        # We verify by checking parse_schedule_pdf returns a list (doesn't crash).
        result = parse_schedule_pdf(schedule_monday_pdf)
        # Should return a ParsedSchedule object — any crash = test failure
        assert isinstance(result, ParsedSchedule)
        assert len(result.events) > 0

    def test_parser_does_not_crash_on_real_pdfs(self, schedule_monday_pdf, schedule_thursday_pdf, schedule_friday_pdf):
        """All fixture PDFs parse without any exception."""
        from app.parsers.schedule import parse_schedule_pdf
        for pdf_path in [schedule_monday_pdf, schedule_thursday_pdf, schedule_friday_pdf]:
            result = parse_schedule_pdf(pdf_path)
            assert isinstance(result, ParsedSchedule), f"Expected ParsedSchedule from {pdf_path}"
            assert len(result.events) > 0, f"Expected events from {pdf_path}"
            # Verify each event has the expected fields
            for ev in result.events:
                assert ev.show is not None or ev.cast_type is not None, \
                    f"Event with no show and no cast_type in {pdf_path}"
