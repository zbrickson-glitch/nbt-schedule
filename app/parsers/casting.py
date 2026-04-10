"""
Parser for NBT Role Responsibilities (casting) PDFs.

These PDFs follow a consistent format:
  - Title row: "<Show Name> Role Responsibilities  Updated: <date>"
  - Column header row: "Cast | Cover" or "Cast | Cover | Cover"
  - Section header rows (song titles): bold font
  - Dancer rows (regular font): cast_name [cover1_name] [cover2_name]
    aligned to column x-positions

Font-based detection is used as the primary method:
  - Bold font (contains "Bold" in fontname) = section header or document header
  - Regular font = dancer name

Word x-positions determine which column a name belongs to:
  - Words at left margin (x < threshold) = Cast column
  - Words past first cover threshold = Cover column
  - Words past second cover threshold = Cover2 column
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import pdfplumber


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class CastingDancer:
    name: str
    role: str  # 'cast', 'cover', 'cover2'
    cover_for: str | None = None


@dataclass
class CastingSection:
    name: str
    dancers: list[CastingDancer] = field(default_factory=list)


@dataclass
class ParsedCasting:
    show: str
    updated_date: str
    sections: list[CastingSection] = field(default_factory=list)
    raw_text: str = ""

    def all_dancer_names(self) -> set:
        names = set()
        for section in self.sections:
            for d in section.dancers:
                names.add(d.name)
        return names


# ── Internal helpers ──────────────────────────────────────────────────────────

# Lines that are document boilerplate and should be skipped
_SKIP_LINE_PATTERNS = [
    re.compile(r"(?i)role\s+responsibilit"),   # title line
    re.compile(r"(?i)subject\s+to\s+change"),  # footer
    re.compile(r"(?i)^updated:"),
    re.compile(r"(?i)^cast\s+cover"),          # column headers
]

_ROLE_RESPONSIBILITIES_RE = re.compile(
    r"^(?P<show>.+?)\s+Role\s+Responsibilit",
    re.IGNORECASE,
)
_UPDATED_RE = re.compile(r"Updated:\s*(\S+)", re.IGNORECASE)


def _is_bold(fontname: str) -> bool:
    """Return True if the fontname indicates a bold variant."""
    return "Bold" in fontname or "bold" in fontname


def _is_header_line(fontname: str) -> bool:
    """A line is a document/section header if its words are in bold font."""
    return _is_bold(fontname)


def _is_skip_text(text: str) -> bool:
    """Return True if this line is boilerplate that should be ignored."""
    for pat in _SKIP_LINE_PATTERNS:
        if pat.search(text):
            return True
    return False


def _group_words_into_lines(words: list[dict]) -> list[list[dict]]:
    """
    Group extracted word dicts into logical lines based on their vertical (top) position.
    Words whose tops are within 2 points of each other are on the same line.
    """
    if not words:
        return []

    lines: list[list[dict]] = []
    current_line: list[dict] = [words[0]]
    current_top = words[0]["top"]

    for word in words[1:]:
        if abs(word["top"] - current_top) <= 2:
            current_line.append(word)
        else:
            lines.append(sorted(current_line, key=lambda w: w["x0"]))
            current_line = [word]
            current_top = word["top"]

    if current_line:
        lines.append(sorted(current_line, key=lambda w: w["x0"]))

    return lines


def _line_text(line: list[dict]) -> str:
    return " ".join(w["text"] for w in line)


def _line_is_bold(line: list[dict]) -> bool:
    """Return True if the majority (or first word) of line words are bold."""
    if not line:
        return False
    bold_count = sum(1 for w in line if _is_bold(w.get("fontname", "")))
    return bold_count > len(line) // 2


def _detect_column_boundaries(all_page_words: list[list[dict]]) -> tuple[float, Optional[float]]:
    """
    Detect the x-positions of the Cover and optional Cover2 columns by
    looking for the column header line ("Cast  Cover  Cover" or "CAST  COVER").

    Returns (cover1_x, cover2_x_or_None).
    """
    for line in all_page_words:
        texts = [w["text"].lower() for w in line]
        if "cast" in texts and "cover" in texts:
            cover_words = [w for w in line if w["text"].lower() == "cover"]
            if len(cover_words) >= 2:
                return cover_words[0]["x0"], cover_words[1]["x0"]
            elif len(cover_words) == 1:
                return cover_words[0]["x0"], None
    # Fallback: use a rough midpoint heuristic
    return 160.0, None


def _assign_column(x0: float, cover1_x: float, cover2_x: Optional[float]) -> str:
    """Assign a word's column role based on its left x-position."""
    # Give some tolerance (words can start a few points before column header)
    tolerance = 30.0
    if cover2_x is not None and x0 >= cover2_x - tolerance:
        return "cover2"
    if x0 >= cover1_x - tolerance:
        return "cover"
    return "cast"


def _extract_page_casting(
    page_words_lines: list[list[dict]],
    cover1_x: float,
    cover2_x: Optional[float],
    existing_sections: list[CastingSection],
) -> tuple[list[CastingSection], list[list[dict]]]:
    """
    Parse one page worth of line-grouped words into sections/dancers.

    Returns the updated sections list and any remaining word-lines for debugging.
    """
    sections = existing_sections

    for line in page_words_lines:
        if not line:
            continue

        line_text = _line_text(line)

        # Skip pure boilerplate
        if _is_skip_text(line_text):
            continue

        is_bold = _line_is_bold(line)

        if is_bold:
            # Could be title, column header, or section header
            # Column headers: the line contains "cast" and "cover"
            lower = line_text.lower()
            if "cast" in lower and "cover" in lower:
                continue  # column header row
            if _ROLE_RESPONSIBILITIES_RE.search(line_text):
                continue  # document title
            if _is_skip_text(line_text):
                continue

            # It's a song section header
            section_name = line_text.strip()
            # Guard: don't create duplicate back-to-back sections
            if not sections or sections[-1].name != section_name:
                sections.append(CastingSection(name=section_name))

        else:
            # Dancer row — assign words to columns
            if not sections:
                # Shouldn't happen but be safe
                continue

            # Group words in this line by column
            cast_words: list[str] = []
            cover1_words: list[str] = []
            cover2_words: list[str] = []

            for w in line:
                col = _assign_column(w["x0"], cover1_x, cover2_x)
                if col == "cast":
                    cast_words.append(w["text"])
                elif col == "cover":
                    cover1_words.append(w["text"])
                else:
                    cover2_words.append(w["text"])

            cast_name = " ".join(cast_words).strip() if cast_words else None
            cover1_name = " ".join(cover1_words).strip() if cover1_words else None
            cover2_name = " ".join(cover2_words).strip() if cover2_words else None

            section = sections[-1]

            if cast_name:
                section.dancers.append(
                    CastingDancer(name=cast_name, role="cast")
                )

            if cover1_name:
                section.dancers.append(
                    CastingDancer(
                        name=cover1_name,
                        role="cover",
                        cover_for=cast_name,
                    )
                )

            if cover2_name:
                section.dancers.append(
                    CastingDancer(
                        name=cover2_name,
                        role="cover2",
                        cover_for=cast_name,
                    )
                )

    return sections


# ── Public API ────────────────────────────────────────────────────────────────

def parse_casting_pdf(pdf_path: str) -> ParsedCasting:
    """
    Parse a Role Responsibilities PDF and return a ParsedCasting object.

    Args:
        pdf_path: Absolute path to the PDF file.

    Returns:
        ParsedCasting with show name, updated date, sections (songs), and
        per-section dancer assignments.
    """
    show = ""
    updated_date = ""
    sections: list[CastingSection] = []
    raw_text_pages: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        # Collect all words from page 0 first to detect column layout
        # We'll re-use this per-page below
        for page_idx, page in enumerate(pdf.pages):
            words = page.extract_words(extra_attrs=["fontname", "size"])
            page_text = page.extract_text() or ""
            raw_text_pages.append(page_text)

            # Group into lines
            lines = _group_words_into_lines(words)

            # Detect column boundaries from this page
            # (they repeat on each page, so just re-detect each time)
            cover1_x, cover2_x = _detect_column_boundaries(lines)

            # Extract show name and date from first page title
            if page_idx == 0:
                title_line_text = " ".join(page_text.split("\n")[:2])
                m_show = _ROLE_RESPONSIBILITIES_RE.search(title_line_text)
                if m_show:
                    show = m_show.group("show").strip()
                m_date = _UPDATED_RE.search(title_line_text)
                if m_date:
                    updated_date = m_date.group(1).strip()

            sections = _extract_page_casting(
                lines, cover1_x, cover2_x, sections
            )

    return ParsedCasting(
        show=show,
        updated_date=updated_date,
        sections=sections,
        raw_text="\n\n".join(raw_text_pages),
    )
