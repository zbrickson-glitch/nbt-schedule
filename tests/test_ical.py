from app.services.ical import generate_ical_feed
from datetime import date, time
import re

SAMPLE_EVENTS = [
    {"date": date(2026, 3, 2), "time_start": time(9, 30), "time_end": time(11, 0),
     "show": "Company Class", "cast_type": "", "studio": "1", "notes": ""},
    {"date": date(2026, 3, 2), "time_start": time(11, 15), "time_end": time(12, 10),
     "show": "ZIGZAG", "cast_type": "Full Call", "studio": "1", "notes": ""},
    {"date": date(2026, 3, 2), "time_start": time(12, 15), "time_end": time(13, 10),
     "show": "ZIGZAG", "cast_type": "Full Call", "studio": "1", "notes": ""},
    {"date": date(2026, 3, 2), "time_start": time(15, 15), "time_end": time(16, 10),
     "show": "COMPANY B", "cast_type": "Full Call", "studio": "1", "notes": ""},
]

def test_includes_company_class_always():
    feed = generate_ical_feed("Zachary Brickson", ["ZIGZAG"], SAMPLE_EVENTS)
    assert "Company Class" in feed

def test_includes_dancers_show_with_full_call():
    feed = generate_ical_feed("Zachary Brickson", ["ZIGZAG"], SAMPLE_EVENTS)
    assert feed.count("BEGIN:VEVENT") == 3  # Company Class + 2x ZIGZAG

def test_excludes_show_not_in():
    feed = generate_ical_feed("Zachary Brickson", ["ZIGZAG"], SAMPLE_EVENTS)
    # COMPANY B should not appear (Zach isn't in it)
    assert "COMPANY B" not in feed

def test_stable_uids():
    feed1 = generate_ical_feed("Zachary Brickson", ["ZIGZAG"], SAMPLE_EVENTS)
    feed2 = generate_ical_feed("Zachary Brickson", ["ZIGZAG"], SAMPLE_EVENTS)
    uids1 = sorted(re.findall(r'UID:(.*)', feed1))
    uids2 = sorted(re.findall(r'UID:(.*)', feed2))
    assert uids1 == uids2

def test_valid_ical_structure():
    feed = generate_ical_feed("Zachary Brickson", ["ZIGZAG"], SAMPLE_EVENTS)
    assert "BEGIN:VCALENDAR" in feed
    assert "END:VCALENDAR" in feed
    assert "NBT - Zachary Brickson" in feed
    assert "METHOD:PUBLISH" in feed

def test_named_dancer_included_regardless_of_show():
    events = [{"date": date(2026, 3, 2), "time_start": time(11, 15), "time_end": time(11, 35),
               "show": "Wardrobe fitting", "cast_type": "ZACHARY BRICKSON", "studio": "Wardrobe", "notes": ""}]
    feed = generate_ical_feed("Zachary Brickson", [], events)
    assert "BEGIN:VEVENT" in feed


# --- New tests for full-call variant logic ---

def test_full_call_variants():
    """Each of the 6 full-call phrases should include the event for a show the dancer is in."""
    phrases = [
        "Full Call",
        "Full Cast",
        "Full Company",
        "Entire Cast",
        "All Cast",
        "Ensemble Cast",
    ]
    for phrase in phrases:
        events = [
            {"date": date(2026, 3, 5), "time_start": time(10, 0), "time_end": time(11, 30),
             "show": "ZIGZAG", "cast_type": phrase, "studio": "1", "notes": ""},
        ]
        feed = generate_ical_feed("Zachary Brickson", ["ZIGZAG"], events)
        assert feed.count("BEGIN:VEVENT") == 1, (
            f"Expected 1 event for cast_type '{phrase}', got {feed.count('BEGIN:VEVENT')}"
        )


def test_full_call_case_insensitive():
    """All case variations of 'full call' should include the event."""
    variants = ["FULL CALL", "full call", "Full Call", "fUlL cAlL"]
    for variant in variants:
        events = [
            {"date": date(2026, 3, 5), "time_start": time(10, 0), "time_end": time(11, 30),
             "show": "ZIGZAG", "cast_type": variant, "studio": "1", "notes": ""},
        ]
        feed = generate_ical_feed("Zachary Brickson", ["ZIGZAG"], events)
        assert feed.count("BEGIN:VEVENT") == 1, (
            f"Expected 1 event for cast_type '{variant}', got {feed.count('BEGIN:VEVENT')}"
        )


def test_full_call_with_extra_text():
    """cast_type values that contain a full-call phrase should still match (substring check)."""
    extended_phrases = [
        "Full Cast and Covers",
        "Ensemble Cast - Stage Left",
    ]
    for phrase in extended_phrases:
        events = [
            {"date": date(2026, 3, 5), "time_start": time(10, 0), "time_end": time(11, 30),
             "show": "ZIGZAG", "cast_type": phrase, "studio": "1", "notes": ""},
        ]
        feed = generate_ical_feed("Zachary Brickson", ["ZIGZAG"], events)
        assert feed.count("BEGIN:VEVENT") == 1, (
            f"Expected 1 event for cast_type '{phrase}', got {feed.count('BEGIN:VEVENT')}"
        )


def test_full_call_wrong_show_excluded():
    """'Full Call' for a show the dancer is NOT in should NOT appear."""
    events = [
        {"date": date(2026, 3, 5), "time_start": time(10, 0), "time_end": time(11, 30),
         "show": "COMPANY B", "cast_type": "Full Call", "studio": "2", "notes": ""},
    ]
    # Dancer is in ZIGZAG only, not COMPANY B
    feed = generate_ical_feed("Zachary Brickson", ["ZIGZAG"], events)
    assert feed.count("BEGIN:VEVENT") == 0
    assert "COMPANY B" not in feed


def test_named_dancer_case_insensitive():
    """cast_type 'BRICKSON, Fulton' should match dancer 'Zachary Brickson' via last-name check."""
    events = [
        {"date": date(2026, 3, 5), "time_start": time(14, 0), "time_end": time(15, 0),
         "show": "ZIGZAG", "cast_type": "BRICKSON, Fulton", "studio": "1", "notes": ""},
    ]
    feed = generate_ical_feed("Zachary Brickson", [], events)
    assert feed.count("BEGIN:VEVENT") == 1


def test_company_class_always_included():
    """Company Class is included regardless of dancer_shows (even an empty list)."""
    events = [
        {"date": date(2026, 3, 5), "time_start": time(9, 0), "time_end": time(10, 30),
         "show": "Company Class", "cast_type": "", "studio": "1", "notes": ""},
    ]
    feed = generate_ical_feed("Zachary Brickson", [], events)
    assert feed.count("BEGIN:VEVENT") == 1
    assert "Company Class" in feed


def test_empty_cast_type_excluded():
    """An event with an empty cast_type for a non-Company-Class show is excluded."""
    events = [
        {"date": date(2026, 3, 5), "time_start": time(11, 0), "time_end": time(12, 0),
         "show": "ZIGZAG", "cast_type": "", "studio": "1", "notes": ""},
    ]
    # Even though dancer is in ZIGZAG, empty cast_type means no full-call and no name match
    feed = generate_ical_feed("Zachary Brickson", ["ZIGZAG"], events)
    assert feed.count("BEGIN:VEVENT") == 0
