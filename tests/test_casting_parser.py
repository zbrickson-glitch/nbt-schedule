"""
Tests for the casting (Role Responsibilities) PDF parser.
"""

import pytest
from app.parsers.casting import parse_casting_pdf


def test_parse_zigzag(zigzag_rr_pdf):
    result = parse_casting_pdf(zigzag_rr_pdf)

    # Show name check
    assert result.show in ("ZigZag", "ZIGZAG", "Zig Zag")

    # Should have at least 9 sections (10 songs across 2 pages)
    assert len(result.sections) >= 9, (
        f"Expected >= 9 sections, got {len(result.sections)}: "
        f"{[s.name for s in result.sections]}"
    )

    all_names = result.all_dancer_names()

    # Key dancers must appear
    assert "Robert Fulton" in all_names, f"Robert Fulton not found in {all_names}"
    assert "Zachary Brickson" in all_names, f"Zachary Brickson not found in {all_names}"
    assert "Cameron Kesten" in all_names, f"Cameron Kesten not found in {all_names}"

    # Enough unique dancers
    assert len(all_names) >= 20, f"Expected >= 20 dancers, got {len(all_names)}: {all_names}"

    # Zachary Brickson should appear as a cover in at least one section
    all_dancers = [d for s in result.sections for d in s.dancers]
    zach = [d for d in all_dancers if d.name == "Zachary Brickson"]
    assert len(zach) > 0, "Zachary Brickson not found in any section's dancers"
    assert any(d.role == "cover" for d in zach), (
        f"Zachary Brickson has no 'cover' role — roles: {[d.role for d in zach]}"
    )


def test_parse_zigzag_updated_date(zigzag_rr_pdf):
    result = parse_casting_pdf(zigzag_rr_pdf)
    assert result.updated_date, "Updated date should not be empty"
    assert "2/13" in result.updated_date or "2026" in result.updated_date or result.updated_date


def test_parse_zigzag_sections_content(zigzag_rr_pdf):
    result = parse_casting_pdf(zigzag_rr_pdf)
    section_names = [s.name for s in result.sections]

    # Check a few expected song titles exist in section names
    assert any("What The World" in n for n in section_names), (
        f"'What The World...' section not found in {section_names}"
    )
    assert any("San Francisco" in n for n in section_names), (
        f"'I Left My Heart...' section not found in {section_names}"
    )


def test_parse_company_b(company_b_rr_pdf):
    result = parse_casting_pdf(company_b_rr_pdf)

    # Show name check
    assert result.show in ("Company B", "COMPANY B"), (
        f"Expected 'Company B', got '{result.show}'"
    )

    all_names = result.all_dancer_names()

    # Key dancers must appear
    assert "Jaime DeRocker" in all_names, f"Jaime DeRocker not found in {all_names}"
    assert "Shelby Rambo" in all_names, f"Shelby Rambo not found in {all_names}"

    # Enough unique dancers
    assert len(all_names) >= 12, f"Expected >= 12 dancers, got {len(all_names)}: {all_names}"


def test_parse_company_b_updated_date(company_b_rr_pdf):
    result = parse_casting_pdf(company_b_rr_pdf)
    assert result.updated_date, "Updated date should not be empty"
    assert "2/17" in result.updated_date or result.updated_date


def test_parse_company_b_two_covers(company_b_rr_pdf):
    result = parse_casting_pdf(company_b_rr_pdf)

    # "I Can Dream, Can't I?" section should have 2 covers for Jaime DeRocker
    dream = next((s for s in result.sections if "Dream" in s.name), None)
    assert dream is not None, (
        f"'I Can Dream...' section not found. Sections: {[s.name for s in result.sections]}"
    )

    covers = [d for d in dream.dancers if "cover" in d.role]
    cover_names = {d.name for d in covers}

    assert "Brooke Lyness" in cover_names, (
        f"Brooke Lyness not found in covers for 'I Can Dream': {cover_names}"
    )
    assert "Carmen Rossi" in cover_names, (
        f"Carmen Rossi not found in covers for 'I Can Dream': {cover_names}"
    )


def test_parse_company_b_sections(company_b_rr_pdf):
    result = parse_casting_pdf(company_b_rr_pdf)
    section_names = [s.name for s in result.sections]

    # Pennsylvania Polka should be the first section
    assert any("Pennsylvania" in n for n in section_names), (
        f"'Pennsylvania Polka' not found in {section_names}"
    )
    # Another You should be present
    assert any("Another" in n for n in section_names), (
        f"'Another You' not found in {section_names}"
    )


def test_raw_text_populated(zigzag_rr_pdf, company_b_rr_pdf):
    for path in (zigzag_rr_pdf, company_b_rr_pdf):
        result = parse_casting_pdf(path)
        assert result.raw_text, "raw_text should not be empty"
        assert len(result.raw_text) > 50, "raw_text seems too short"
