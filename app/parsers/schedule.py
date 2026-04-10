"""
Parser for NBT daily schedule PDFs.

PDF table structure (from pdfplumber):
  Rehearsal table headers: Time | Studio | What | Staff | Cast | Notes
  Fitting table headers:   TIME | Where  | What | Staff | Cast | Notes

Time format examples:
  "9:30 - 11:00am"   -> 9:30 AM to 11:00 AM
  "11:15 - 12:10pm"  -> 11:15 AM to 12:10 PM
  "12:15 - 1:10pm"   -> 12:15 PM to 1:10 PM
  "1:15 - 2:10pm"    -> 1:15 PM to 2:10 PM
  "5:15 - 6:10pm"    -> 5:15 PM to 6:10 PM
  "11:15 - 11:35am"  -> 11:15 AM to 11:35 AM

Rules:
  - Only the end time carries an am/pm suffix.
  - If end is "am": both are AM (hours 1-11).
  - If end is "pm": end hour < 12 becomes +12. Start is inferred:
      - If start hour == end hour (mod 12): same period as end.
      - If start > end numerically but end is PM: start is also PM (e.g. 12:15 - 1:10pm -> both PM).
      - 9:30 with pm suffix on end 11:00 -> but end is "am" so both AM.
      - General rule: if end is PM and start_h < end_h_raw, start is also PM (add 12 if < 12).
        Exception: 11:15 - 12:10pm -> start=11:15 AM, end=12:10 PM.
        Exception: 12:55 - 1:15pm -> start=12:55 PM, end=1:15 PM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Optional

import pdfplumber


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ScheduleEvent:
    time_start: time
    time_end: Optional[time]
    studio: Optional[str]
    show: str
    staff: Optional[str]
    cast_type: Optional[str]
    notes: Optional[str]
    event_type: str = "rehearsal"


@dataclass
class FittingEvent:
    time_start: time
    time_end: Optional[time]
    where: str
    show: str
    staff: Optional[str]
    dancer: str
    notes: Optional[str]
    event_type: str = "fitting"


@dataclass
class ParsedSchedule:
    date: date
    events: list[ScheduleEvent] = field(default_factory=list)
    fittings: list[FittingEvent] = field(default_factory=list)
    raw_text: str = ""


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*([ap](?:\.?m)?\.?)",
    re.IGNORECASE,
)

# Time range with no am/pm suffix — common in older fitting rows e.g. "3:15 - 3:30"
_TIME_RE_NO_SUFFIX = re.compile(
    r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$",
)

# Single-time entries like "2:00pm" or "7:30 PM" (no end time)
_SINGLE_TIME_RE = re.compile(
    r"^(\d{1,2}):(\d{2})\s*([ap](?:\.?m)?\.?)$",
    re.IGNORECASE,
)


def _parse_single_time(raw: str) -> Optional[time]:
    """Parse a single time string like '2:00pm' or '7:30 PM'. Returns None if no match."""
    m = _SINGLE_TIME_RE.match(raw.strip())
    if not m:
        return None
    h, m_min = int(m.group(1)), int(m.group(2))
    period = "pm" if m.group(3).lower().startswith("p") else "am"
    if period == "pm":
        h_24 = h if h == 12 else h + 12
    else:
        h_24 = 0 if h == 12 else h
    return time(h_24, m_min)


def _parse_time_range(raw: str, assume_pm: bool = False) -> tuple[time, time]:
    """Parse a time range string like '9:30 - 11:00am' into (start, end) times.

    If assume_pm is True, times with no am/pm suffix are treated as PM.
    """
    m = _TIME_RE.search(raw)
    if not m:
        # Try no-suffix format e.g. "3:15 - 3:30" (common in older fitting rows)
        m2 = _TIME_RE_NO_SUFFIX.match(raw.strip())
        if m2 and assume_pm:
            sh, sm, eh, em = int(m2.group(1)), int(m2.group(2)), int(m2.group(3)), int(m2.group(4))
            sh_24 = sh if sh == 12 else sh + 12
            eh_24 = eh if eh == 12 else eh + 12
            return time(sh_24, sm), time(eh_24, em)
        raise ValueError(f"Cannot parse time range: {raw!r}")

    sh, sm, eh, em_min = (
        int(m.group(1)),
        int(m.group(2)),
        int(m.group(3)),
        int(m.group(4)),
    )
    period = "pm" if m.group(5).lower().startswith("p") else "am"

    # Resolve end time first
    if period == "pm":
        if eh != 12:
            eh_24 = eh + 12
        else:
            eh_24 = 12  # noon exactly
    else:  # am
        eh_24 = eh if eh != 12 else 0

    # Resolve start time
    # Strategy: figure out whether start is AM or PM
    if period == "am":
        # Both are AM (e.g. "11:15 - 11:35am")
        sh_24 = sh if sh != 12 else 0
    else:
        # End is PM. Cases:
        #   "12:15 - 1:10pm" -> start=12:15 PM (sh=12, already PM), end=13:10
        #   "12:55 - 1:15pm" -> start=12:55 PM, end=13:15
        #   "1:15 - 2:10pm"  -> start=13:15, end=14:10
        #   "11:15 - 12:10pm"-> start=11:15 AM (sh=11, end hour raw=12 -> noon)
        if sh == 12:
            # e.g. "12:15 - 1:10pm" — start is noon (already >= 12)
            sh_24 = 12
        elif sh < 12 and eh_24 == 12:
            # e.g. "11:15 - 12:10pm" — end is noon, start is morning
            sh_24 = sh
        else:
            # e.g. "1:15 - 2:10pm", "3:15 - 4:10pm", "5:15 - 6:10pm"
            # Normally start is afternoon (add 12), but if that would put start
            # AFTER end (e.g. "11:30 - 1:00pm" → 23:30 > 13:00), start is AM.
            sh_24 = sh + 12
            if sh_24 > eh_24:
                sh_24 = sh  # start is AM (e.g. 11:30am - 1:00pm)

    return time(sh_24, sm), time(eh_24, em_min)


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

_DATE_RE = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})",
    re.IGNORECASE,
)

# NOTE: this regex also matches strings that contain a year; always try _DATE_RE first.
_DATE_RE_NO_YEAR = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?\s*[-–,]",
    re.IGNORECASE,
)


def _parse_date(text: str) -> Optional[date]:
    # Try with explicit year first (e.g. "Monday, March 2, 2026")
    m = _DATE_RE.search(text)
    if m:
        month_str, day_str, year_str = m.group(1), m.group(2), m.group(3)
        month = _MONTHS.get(month_str.lower())
        if month:
            return date(int(year_str), month, int(day_str))

    # Try without year (e.g. "Wednesday, December 10 -")
    m = _DATE_RE_NO_YEAR.search(text)
    if m:
        month_str, day_str = m.group(1), m.group(2)
        month = _MONTHS.get(month_str.lower())
        if not month:
            return None
        day = int(day_str)
        # Infer year: return the most recent past occurrence of this month/day.
        # NOTE: Will be wrong if a no-year schedule is parsed before the performance
        # date (e.g. a December schedule received in November). Schedules with
        # explicit years (see _DATE_RE above) are always preferred.
        today = datetime.today().date()
        for year_offset in [0, -1, -2]:
            candidate_year = today.year + year_offset
            try:
                candidate = date(candidate_year, month, day)
                if candidate <= today:
                    return candidate
            except ValueError:
                continue
        return None

    return None


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------

def _clean(val: Optional[str]) -> Optional[str]:
    """Normalize whitespace; return None for blank/None values."""
    if val is None:
        return None
    cleaned = " ".join(val.split())
    return cleaned if cleaned else None


def _is_break_row(row: list) -> bool:
    """Return True if the row is a BREAK filler row."""
    what = _clean(row[2]) if len(row) > 2 else None
    return what == "BREAK"


def _is_header_row(row: list) -> bool:
    """Return True if this is a column header row."""
    if not row:
        return False
    first = _clean(row[0])
    return first in ("Time", "TIME")


def _is_empty_row(row: list) -> bool:
    """Return True if all cells are blank/None."""
    return all(_clean(c) is None for c in row)


def _is_dancers_call_row(row: list) -> bool:
    """Return True for 'Dancers Call' rows that span multiple columns."""
    if len(row) < 2:
        return False
    col1 = _clean(row[1])
    if col1 and "dancers call" in col1.lower():
        return True
    # Also skip rows where only col0 has content and rest are None
    if len(row) > 2 and _clean(row[0]) and all(_clean(row[i]) is None for i in range(2, len(row))):
        return True
    return False


def _has_time(row: list) -> bool:
    """Return True if the row has a parseable time (range or single) in column 0."""
    time_cell = _clean(row[0]) if row else None
    if not time_cell:
        return False
    return (
        bool(_TIME_RE.search(time_cell))
        or bool(_SINGLE_TIME_RE.match(time_cell))
        or bool(_TIME_RE_NO_SUFFIX.match(time_cell))
    )


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_schedule_pdf(pdf_path: str) -> ParsedSchedule:
    """Parse a daily schedule PDF and return a ParsedSchedule."""
    with pdfplumber.open(pdf_path) as pdf:
        raw_text_parts = []
        all_tables: list[list[list]] = []

        for page in pdf.pages:
            text = page.extract_text() or ""
            raw_text_parts.append(text)
            tables = page.extract_tables()
            all_tables.extend(tables)

    raw_text = "\n".join(raw_text_parts)

    # Parse date from raw text
    schedule_date = _parse_date(raw_text)
    if schedule_date is None:
        raise ValueError(f"Could not parse date from PDF: {pdf_path}")

    result = ParsedSchedule(date=schedule_date, raw_text=raw_text)

    for table in all_tables:
        if not table:
            continue

        # Identify table type by its header row
        header = table[0]
        if not header:
            continue

        col0 = _clean(header[0])
        col1 = _clean(header[1]) if len(header) > 1 else None

        # Detect headerless continuation tables: first row has time data, not a label.
        # Some PDFs split rehearsals across multiple tables without repeating the header.
        headerless_rehearsal = col0 not in ("Time", "TIME") and _has_time(header)

        if col0 in ("Time", "TIME") or headerless_rehearsal:
            # Fittings tables use "TIME" (all caps); rehearsal tables use "Time" (mixed case).
            # Both can have "Where" or "Studio" in col1 — don't use col1 to distinguish.
            is_fitting_table = col0 == "TIME"

            # For headerless tables include the first row (it's data, not a header)
            rows = table if headerless_rehearsal else table[1:]
            for row in rows:  # skip header only if we have one
                if _is_empty_row(row):
                    continue
                if _is_break_row(row):
                    continue
                if _is_dancers_call_row(row):
                    continue
                if not _has_time(row):
                    continue

                # Skip announcement rows where the show/what column (col2) is blank
                # e.g. "1:30pm | Dancers Call - Please remember... | None | ..."
                if len(row) < 3 or not _clean(row[2]):
                    continue

                time_cell = _clean(row[0])
                t_end: Optional[time] = None
                try:
                    # For fitting tables, assume PM when no am/pm suffix is present
                    t_start, t_end = _parse_time_range(time_cell, assume_pm=is_fitting_table)
                except ValueError:
                    # Try single-time format (e.g. "2:00pm" for performances)
                    t_start = _parse_single_time(time_cell)
                    if t_start is None:
                        continue

                if is_fitting_table:
                    # Columns: TIME | Where | What | Staff | Cast (dancer) | Notes
                    # Minimum 5 columns required (TIME, Where, What, Staff, Cast).
                    MIN_FITTING_COLS = 5
                    if len(row) < MIN_FITTING_COLS:
                        continue
                    where = _clean(row[1]) or ""
                    show = _clean(row[2]) or ""
                    staff = _clean(row[3])
                    dancer = _clean(row[4]) or ""
                    notes = _clean(row[5]) if len(row) > 5 else None

                    result.fittings.append(FittingEvent(
                        time_start=t_start,
                        time_end=t_end,
                        where=where,
                        show=show,
                        staff=staff,
                        dancer=dancer,
                        notes=notes,
                    ))
                else:
                    # Columns: Time | Studio | What | Staff | Cast | Notes
                    # Minimum 4 columns required because row[3] (staff) is accessed
                    # unconditionally below. The earlier len(row) < 3 check guards
                    # row[2] (show), but not row[3], so we need 4 here.
                    MIN_REHEARSAL_COLS = 4
                    if len(row) < MIN_REHEARSAL_COLS:
                        continue
                    studio = _clean(row[1])
                    show = _clean(row[2]) or ""
                    staff = _clean(row[3])
                    cast_type = _clean(row[4]) if len(row) > 4 else None
                    notes = _clean(row[5]) if len(row) > 5 else None
                    # Strip redundant fitting cross-reference notes (BUG-001, BUG-002).
                    # These are already parsed as separate fitting events.
                    if notes and re.match(r"\*\*\s*(Check Fitting|.*fitting\s+\d)", notes, re.IGNORECASE):
                        notes = None

                    result.events.append(ScheduleEvent(
                        time_start=t_start,
                        time_end=t_end,
                        studio=studio,
                        show=show,
                        staff=staff,
                        cast_type=cast_type or None,
                        notes=notes,
                    ))

    return result
