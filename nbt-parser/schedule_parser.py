"""
Schedule PDF parser — ported from workspace-v4 ballet-parser/parser.py.

Parses NBT schedule PDFs (pdfplumber table extraction) into structured events.
Supports filtering by dancer name (BRICKSON).
"""

import io
import os
import re
from datetime import datetime
from typing import Optional

import pdfplumber


def parse_filename_date(filename: str) -> Optional[datetime]:
    """
    Parse date from filename like:
    'Tuesday 2.10.26 Artist Daily Schedule.pdf' -> Feb 10, 2026
    'Thursday 12.11.25 Schedule.pdf' -> Dec 11, 2025
    """
    basename = os.path.basename(filename)
    match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})', basename)
    if match:
        month, day, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        year = 2000 + year if year < 100 else year
        try:
            return datetime(year, month, day)
        except ValueError:
            pass
    return None


def parse_header_date(text: str) -> Optional[datetime]:
    """
    Parse date from header like:
    'Thursday, December 11 - NBT Dancer Schedule at The Smith Center'
    """
    patterns = [
        r"(\w+),\s+(\w+)\s+(\d{1,2})\s+-\s+NBT",
        r"(\w+)\s+(\d{1,2})\.(\d{1,2})\.(\d{2,4})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            if len(groups) == 3:
                month_str, day = groups[1], int(groups[2])
                months = {
                    'january': 1, 'february': 2, 'march': 3, 'april': 4,
                    'may': 5, 'june': 6, 'july': 7, 'august': 8,
                    'september': 9, 'october': 10, 'november': 11, 'december': 12
                }
                month = months.get(month_str.lower())
                if month:
                    # Use current year context
                    now = datetime.now()
                    year = now.year if month >= now.month - 1 else now.year + 1
                    return datetime(year, month, day)
            elif len(groups) == 4:
                month, day, year = int(groups[1]), int(groups[2]), int(groups[3])
                year = 2000 + year if year < 100 else year
                return datetime(year, month, day)
    return None


def parse_time_range(time_str: str, base_date: datetime) -> tuple[datetime, datetime]:
    """
    Parse time ranges like:
    - '11:00 - 12:30pm'
    - '1:00 - 2:20pm (80/10)'
    - '5:30 - 6:50pm'

    Returns (start_datetime, end_datetime)
    """
    # Remove annotations like (80/10)
    time_str = re.sub(r'\s*\([^)]+\)\s*', '', time_str)

    match = re.match(r'(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*(am|pm)?', time_str, re.IGNORECASE)
    if not match:
        raise ValueError(f"Cannot parse time: {time_str}")

    start_str, end_str, period = match.groups()

    def parse_time(t: str) -> tuple[int, int]:
        h, m = map(int, t.split(':'))
        return h, m

    is_pm = period and period.lower() == 'pm'

    start_h, start_m = parse_time(start_str)
    end_h, end_m = parse_time(end_str)

    # If end time has pm, adjust both if needed
    if is_pm:
        if end_h < 12:
            end_h += 12
        if start_h < 12 and start_h < end_h - 12:
            start_h += 12

    start_dt = base_date.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    end_dt = base_date.replace(hour=end_h, minute=end_m, second=0, microsecond=0)

    return start_dt, end_dt


def is_schedule_pdf(pdf_bytes: bytes) -> bool:
    """
    Classify whether a PDF is a schedule by checking table headers
    for schedule-specific columns (Time, Where, What).
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue
                    for row in table[:3]:  # Check first 3 rows for headers
                        if not row:
                            continue
                        cells_lower = [str(c).lower() for c in row if c]
                        has_time = any('time' in c for c in cells_lower)
                        has_where = any(w in c for c in cells_lower for w in ['where', 'studio', 'location'])
                        has_what = any(w in c for c in cells_lower for w in ['what', 'activity'])
                        if has_time and (has_where or has_what):
                            return True
    except Exception:
        pass
    return False


def parse_schedule_pdf(pdf_bytes: bytes, filename: str, filter_dancer: str = "BRICKSON") -> dict:
    """
    Parse a schedule PDF and return structured events.

    Args:
        pdf_bytes: Raw PDF file content
        filename: Original filename (used for date extraction)
        filter_dancer: Dancer name to filter for (default: BRICKSON)

    Returns:
        {
            "events": [...],           # All events
            "filtered_events": [...],   # Events matching filter_dancer
            "schedule_date": "YYYY-MM-DD",
            "event_count": int,
            "filtered_count": int
        }
    """
    all_events = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        all_text = ""
        tables = []

        for page in pdf.pages:
            all_text += page.extract_text() or ""
            page_tables = page.extract_tables()
            tables.extend(page_tables)

        # Parse date - try filename first, then header
        base_date = parse_filename_date(filename)
        if not base_date:
            base_date = parse_header_date(all_text)
        if not base_date:
            base_date = datetime.now()

        schedule_date = base_date.strftime('%Y-%m-%d')

        # Process tables
        for table in tables:
            if not table:
                continue

            # Find header row
            header_idx = None
            for i, row in enumerate(table):
                if row and any('time' in str(cell).lower() for cell in row if cell):
                    header_idx = i
                    break

            if header_idx is None:
                continue

            headers = [str(h).lower().strip() if h else '' for h in table[header_idx]]

            # Map columns
            col_map = {}
            for i, h in enumerate(headers):
                if 'time' in h:
                    col_map['time'] = i
                elif 'where' in h:
                    col_map['where'] = i
                elif 'what' in h:
                    col_map['what'] = i
                elif 'staff' in h:
                    col_map['staff'] = i
                elif 'cast' in h:
                    col_map['cast'] = i
                elif 'note' in h:
                    col_map['notes'] = i

            # Process data rows
            for row in table[header_idx + 1:]:
                if not row or not any(row):
                    continue

                def get_cell(key: str) -> str:
                    idx = col_map.get(key)
                    if idx is not None and idx < len(row) and row[idx]:
                        return str(row[idx]).strip()
                    return ""

                time_str = get_cell('time')
                what = get_cell('what')
                where = get_cell('where')
                staff = get_cell('staff')
                cast = get_cell('cast')
                notes = get_cell('notes')

                # Skip non-event rows
                if not time_str or 'break' in time_str.lower() or not what:
                    continue
                if 'subject to change' in what.lower():
                    continue

                try:
                    start_dt, end_dt = parse_time_range(time_str, base_date)
                except ValueError:
                    continue

                # Build description
                desc_parts = []
                if staff:
                    desc_parts.append(f"Staff: {staff}")
                if cast:
                    desc_parts.append(f"Cast: {cast}")
                if notes:
                    desc_parts.append(f"Notes: {notes}")

                # Build title with time block
                def fmt_time(dt):
                    h = dt.hour % 12 or 12
                    m = f":{dt.minute:02d}" if dt.minute else ""
                    p = "a" if dt.hour < 12 else "p"
                    return f"{h}{m}{p}"

                time_block = f"{fmt_time(start_dt)}-{fmt_time(end_dt)}"
                clean_what = what.replace('\n', ' ').strip()
                if cast:
                    clean_cast = cast.replace('\n', ' ').strip()
                    title = f"{time_block} {clean_what} -- {clean_cast}"
                else:
                    title = f"{time_block} {clean_what}"

                # Check if this dancer is involved
                dancer_match = False
                if filter_dancer:
                    dancer_lower = filter_dancer.lower()
                    combined = f"{cast} {notes}".lower()
                    what_lower = what.lower()
                    is_everyone = any(phrase in combined for phrase in [
                        'all dancers', 'full cast', 'full company', 'all company',
                        'entire cast', 'everyone', 'full call',
                        'principals and covers', 'principal cast and covers',
                    ])
                    is_company_class = 'company class' in what_lower
                    if dancer_lower in combined or is_everyone or is_company_class:
                        dancer_match = True

                event = {
                    'start': start_dt.isoformat(),
                    'end': end_dt.isoformat(),
                    'title': title,
                    'location': where,
                    'description': '\n'.join(desc_parts),
                    'dancer_match': dancer_match,
                }
                all_events.append(event)

    filtered_events = [e for e in all_events if e.get('dancer_match')]

    return {
        "events": all_events,
        "filtered_events": filtered_events,
        "schedule_date": schedule_date,
        "event_count": len(all_events),
        "filtered_count": len(filtered_events),
    }
