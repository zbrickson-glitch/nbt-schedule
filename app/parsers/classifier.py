import re
from enum import Enum
from typing import Optional

class PdfType(Enum):
    SCHEDULE = "schedule"
    CASTING = "casting"
    MAAG = "maag"  # Month at a Glance
    UNKNOWN = "unknown"

class EmailType(Enum):
    SCHEDULE = "schedule"
    CASTING = "casting"
    CAST_CHANGE = "cast_change"
    CANCELLATION = "cancellation"
    EMERGENCY = "emergency"
    ADDITIONAL_DETAIL = "additional_detail"
    MIXED = "mixed"
    UNKNOWN = "unknown"

CASTING_PATTERNS = [
    r"(?i)\bRR\b",
    r"(?i)role\s+responsibilit",
]

SCHEDULE_PATTERNS = [
    r"(?i)artist\s+daily\s+schedule",
    r"(?i)artistic\s+daily\s+schedule",
    r"(?i)artistic\s+schedule",
    r"(?i)nbt\s+dancer\s+schedule",
    r"(?i)artist[_\s]+daily",  # catches Artist_Daily.pdf (early Nov format, no "Schedule" suffix)
    r"(?i)schedule",  # catches dec10_schedule.pdf, schedule-monday-3-2.pdf, etc.
]

MAAG_PATTERNS = [
    r"(?i)month\s+at\s+a\s+glance",
    r"(?i)\bMAAG\b",
    r"(?i)monthly\s+calendar",
    r"(?i)monthly\s+overview",
]

def classify_pdf(filename: str, pdf_bytes: Optional[bytes] = None) -> PdfType:
    """Classify a PDF by filename patterns, with content fallback."""
    # First try filename
    for pattern in CASTING_PATTERNS:
        if re.search(pattern, filename):
            return PdfType.CASTING
    for pattern in MAAG_PATTERNS:
        if re.search(pattern, filename):
            return PdfType.MAAG
    for pattern in SCHEDULE_PATTERNS:
        if re.search(pattern, filename):
            return PdfType.SCHEDULE

    # Filename didn't match — try content if bytes provided
    if pdf_bytes:
        return _classify_pdf_by_content(pdf_bytes)

    return PdfType.UNKNOWN


def _classify_pdf_by_content(pdf_bytes: bytes) -> PdfType:
    """Detect PDF type by looking at text and table headers in content."""
    import io
    import pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages[:2]:  # check first 2 pages only
                text = (page.extract_text() or "").lower()
                # Check for schedule title text
                if any(p in text for p in (
                    "artist daily schedule", "artistic daily schedule",
                    "artist daily",  # early format without "schedule" suffix
                    "nbt dancer schedule", "dancer schedule",
                )):
                    return PdfType.SCHEDULE
                if "role responsibilit" in text or " rr " in text:
                    return PdfType.CASTING
                # Check table headers
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue
                    header = " ".join(str(c or "") for c in (table[0] or [])).lower()
                    # "where" is used instead of "studio" in some PDFs
                    location_col = "studio" in header or "where" in header
                    if location_col and ("what" in header or "show" in header):
                        return PdfType.SCHEDULE
                    if "role" in header and ("dancer" in header or "cast" in header):
                        return PdfType.CASTING
    except Exception:
        pass
    return PdfType.UNKNOWN

def classify_email(subject: str, body: str, attachments: list) -> EmailType:
    """Classify an email by its subject, body, and attachment filenames."""
    text = f"{subject} {body}".lower()

    if not attachments:
        # Body-text-only emails — classify by content
        if "emergency" in text and "rehearsal" in text:
            return EmailType.EMERGENCY
        if "cancel" in text:
            return EmailType.CANCELLATION
        if "additional detail" in subject.lower():
            return EmailType.ADDITIONAL_DETAIL
        if "cast change" in text or "casting change" in text:
            return EmailType.CAST_CHANGE
        return EmailType.UNKNOWN

    types = {classify_pdf(a) for a in attachments}
    has_casting = PdfType.CASTING in types
    has_schedule = PdfType.SCHEDULE in types

    if has_casting and has_schedule:
        return EmailType.MIXED
    if has_casting:
        return EmailType.CASTING
    if has_schedule:
        return EmailType.SCHEDULE
    return EmailType.UNKNOWN
