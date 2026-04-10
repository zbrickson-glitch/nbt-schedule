from datetime import date, time, datetime, timezone
from zoneinfo import ZoneInfo
from icalendar import Calendar, Event

PACIFIC = ZoneInfo("America/Los_Angeles")

def generate_ical_feed(dancer_name: str, dancer_shows: list, events: list) -> str:
    """
    Generate a personalized .ics feed for a dancer.

    dancer_name: Full name e.g. "Zachary Brickson"
    dancer_shows: Shows they're in e.g. ["ZIGZAG"] — compared case-insensitively
    events: List of dicts with keys: date, time_start, time_end, show, cast_type, studio, notes

    Includes event if:
    - show is "Company Class" (everyone attends)
    - show matches dancer_shows AND cast_type contains "Full Call"
    - dancer's name appears in cast_type (individually called)
    """
    cal = Calendar()
    cal.add('prodid', '-//NBT Schedule Service//nbt.schedule//EN')
    cal.add('version', '2.0')
    cal.add('method', 'PUBLISH')
    cal.add('x-wr-calname', f'NBT - {dancer_name}')

    shows_upper = {s.upper() for s in dancer_shows}
    # Last name for matching against "Brickson, Fulton"-style cast lists
    last_name = dancer_name.split()[-1].upper() if dancer_name else ""

    for ev in events:
        show = ev["show"]
        show_upper = show.upper()
        cast_type = (ev.get("cast_type") or "").strip()
        cast_upper = cast_type.upper()
        cast_lower = cast_type.lower()

        is_company_class = "company class" in show.lower()
        # "Full Call", "Full Cast", "Full Cast and Covers" all mean everyone in the show
        is_full_call_for_show = (show_upper in shows_upper) and (
            "full call" in cast_lower or "full cast" in cast_lower
            or "full company" in cast_lower or "entire cast" in cast_lower
            or "all cast" in cast_lower or "ensemble cast" in cast_lower
        )
        # Cast lists use last names: "Brickson, Fulton" — check last name in cast
        is_named_individually = bool(last_name) and last_name in cast_upper

        if not (is_company_class or is_full_call_for_show or is_named_individually):
            continue

        event = Event()
        ev_date = ev["date"]
        start_dt = datetime.combine(ev_date, ev["time_start"], tzinfo=PACIFIC)
        end_time = ev["time_end"] if ev["time_end"] is not None else (
            time((ev["time_start"].hour + 1) % 24, ev["time_start"].minute)
        )
        end_dt = datetime.combine(ev_date, end_time, tzinfo=PACIFIC)

        uid = (
            f"nbt-{ev_date.isoformat()}"
            f"-{ev['time_start'].strftime('%H%M')}"
            f"-{show_upper.replace(' ', '-').replace('/', '-')}"
            f"@nbt.schedule"
        )

        event.add('uid', uid)
        event.add('dtstart', start_dt)
        event.add('dtend', end_dt)
        event.add('summary', show)

        studio = ev.get("studio", "")
        event.add('location', f'Studio {studio}' if studio else 'NBT')

        desc_parts = []
        if cast_type:
            desc_parts.append(f"Cast: {cast_type}")
        notes = ev.get("notes", "")
        if notes:
            desc_parts.append(f"Notes: {notes}")
        if desc_parts:
            event.add('description', '\n'.join(desc_parts))

        event.add('sequence', 1)
        cal.add_component(event)

    return cal.to_ical().decode('utf-8')
