"""
Discord preview formatting for schedule and casting data.

Produces Discord-friendly text previews for posting to webhooks.
"""

from datetime import datetime


def format_datetime(iso_string: str) -> str:
    """Convert ISO 8601 datetime to readable format."""
    try:
        dt = datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
        return dt.strftime('%a %b %d, %I:%M %p').replace(' 0', ' ').strip()
    except Exception:
        return iso_string


def format_time_only(iso_string: str) -> str:
    """Extract just the time from an ISO datetime."""
    try:
        dt = datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
        return dt.strftime('%I:%M %p').replace(' 0', ' ').strip()
    except Exception:
        return iso_string


def format_schedule_preview(
    events: list[dict],
    filtered_events: list[dict],
    schedule_date: str,
    subject: str = "",
    max_events: int = 15,
) -> str:
    """
    Format a Discord-friendly schedule preview.

    Args:
        events: All parsed events
        filtered_events: Events matching the dancer filter
        schedule_date: Date string (YYYY-MM-DD)
        subject: Email subject line
        max_events: Maximum events to show in preview

    Returns:
        Discord-formatted string
    """
    if not events:
        return "No schedule events found in PDF."

    # Build set of filtered event keys
    filtered_keys = set()
    for e in filtered_events:
        filtered_keys.add((e['start'], e['end']))

    # Format date header
    try:
        date_obj = datetime.strptime(schedule_date, '%Y-%m-%d')
        date_display = date_obj.strftime('%a %b %d')
    except ValueError:
        date_display = schedule_date

    lines = []

    # Header
    if subject:
        lines.append(f"Subject: {subject}")

    # Event list
    for i, event in enumerate(events[:max_events]):
        key = (event['start'], event['end'])
        is_yours = key in filtered_keys

        title = event.get('title', 'Unknown')
        location = event.get('location', '')
        start_time = format_time_only(event['start'])
        end_time = format_time_only(event['end'])

        # Clean up title -- remove the time block prefix since we show time separately
        clean_title = title
        # Title format is "9a-10:15a Company Class -- Cast"
        # Just use the original what/cast info
        parts = clean_title.split(' ', 1)
        if len(parts) > 1 and ('-' in parts[0] and any(c in parts[0] for c in 'ap')):
            clean_title = parts[1]

        marker = "* " if is_yours else "  "
        line = f"{marker}{clean_title}"
        if location:
            line += f" [{location}]"
        line += f", {start_time} - {end_time}"

        lines.append(line)

    # Summary
    if len(events) > max_events:
        lines.append(f"...and {len(events) - max_events} more events")

    lines.append(f"Created {len(events)} events ({len(filtered_events)} yours) for {date_display}")

    return '\n'.join(lines)


def format_casting_preview(
    roster: list[dict],
    your_roles: list[str],
    show: str,
    notes: str = "",
    raw_preview: str = "",
) -> str:
    """
    Format a Discord-friendly casting preview.

    Args:
        roster: List of {"role": str, "dancers": [str]}
        your_roles: Roles assigned to the filtered dancer
        show: Production/show name
        notes: Optional casting notes
        raw_preview: Fallback raw text if LLM extraction failed

    Returns:
        Discord-formatted string
    """
    lines = []
    lines.append(f"{show}")

    if your_roles:
        lines.append(f"You: {', '.join(your_roles)}")
    else:
        lines.append("You: not listed")

    if roster:
        lines.append("")
        for entry in roster:
            role = entry.get('role', 'Unknown')
            dancers = entry.get('dancers', [])
            dancer_str = ', '.join(dancers) if dancers else 'TBD'

            # Highlight roles that are yours
            if role in your_roles:
                lines.append(f">> {role}: {dancer_str}")
            else:
                lines.append(f"   {role}: {dancer_str}")
    elif raw_preview:
        lines.append("")
        lines.append("(LLM extraction failed -- raw text below)")
        # Limit raw preview for Discord
        if len(raw_preview) > 1500:
            raw_preview = raw_preview[:1500] + "\n[... truncated ...]"
        lines.append(raw_preview)

    if notes:
        lines.append("")
        lines.append(f"Notes: {notes}")

    return '\n'.join(lines)
