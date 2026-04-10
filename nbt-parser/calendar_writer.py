"""
Google Calendar event writer using gog CLI.

Creates events with dual-color scheme:
  - Purple (3) = events you're in
  - Yellow (5) = context events (all rehearsals)

Deduplicates by deleting existing pipeline events for the same date
before creating new ones.
"""

import json
import logging
import os
import subprocess
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

GOG_CMD = os.environ.get("GOG_CMD", "/usr/local/bin/gog")
ACCOUNT = os.environ.get("GOG_ACCOUNT", "zbrickson@gmail.com")
TIMEZONE_OFFSET = "-07:00"  # America/Denver


def _add_tz_if_missing(ts: str) -> str:
    """Add timezone offset if missing from ISO timestamp."""
    if 'T' in ts and '+' not in ts and 'Z' not in ts and '-' not in ts.split('T')[1]:
        return ts + TIMEZONE_OFFSET
    return ts


def _run_gog(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a gog CLI command with standard options."""
    cmd = [GOG_CMD] + args
    logger.debug("Running: %s", ' '.join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def delete_existing_events(schedule_date: str) -> int:
    """Delete all pipeline-created events for a given date (YYYY-MM-DD)."""
    next_day = (datetime.strptime(schedule_date, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')

    try:
        result = _run_gog([
            'calendar', 'events', 'primary',
            '--from', schedule_date,
            '--to', next_day,
            '--private-prop-filter', 'source=nbt-pipeline',
            '--json',
            '--max', '50',
            '--account', ACCOUNT,
        ])

        if result.returncode != 0:
            logger.warning("Could not query existing events for %s: %s", schedule_date, result.stderr.strip())
            return 0

        data = json.loads(result.stdout) if result.stdout.strip() else {}
        events = data.get('events', []) if isinstance(data, dict) else data
        if not events:
            return 0

        deleted = 0
        for event in events:
            event_id = event.get('id')
            if not event_id:
                continue
            del_result = _run_gog([
                'calendar', 'delete', 'primary', event_id,
                '--force',
                '--account', ACCOUNT,
            ])
            if del_result.returncode == 0:
                deleted += 1
            else:
                logger.warning("Failed to delete event %s: %s", event_id, del_result.stderr.strip())

        if deleted:
            logger.info("Dedup: deleted %d existing pipeline event(s) for %s", deleted, schedule_date)
        return deleted

    except Exception as e:
        logger.warning("Dedup query failed for %s: %s", schedule_date, e)
        return 0


def create_single_event(event: dict, color_id: int, prefix: str = "") -> bool:
    """Create a single calendar event using gog CLI."""
    title = event.get('title', 'NBT Rehearsal')
    if prefix:
        title = f"{prefix} {title}"

    start = event.get('start')
    end = event.get('end')

    if not start or not end:
        logger.warning("Skipping event without start/end times: %s", title)
        return False

    start = _add_tz_if_missing(start)
    end = _add_tz_if_missing(end)

    schedule_date = start.split('T')[0] if 'T' in start else start[:10]

    cmd_args = [
        'calendar', 'create', 'primary',
        '--summary', title,
        '--from', start,
        '--to', end,
        '--event-color', str(color_id),
        '--account', ACCOUNT,
        '--private-prop', 'source=nbt-pipeline',
        '--private-prop', f'schedule-date={schedule_date}',
    ]

    if event.get('description'):
        cmd_args.extend(['--description', event['description']])
    if event.get('location'):
        cmd_args.extend(['--location', event['location']])

    try:
        result = _run_gog(cmd_args)
        if result.returncode == 0:
            color_label = "purple" if str(color_id) == "3" else "yellow"
            logger.info("[%s] %s", color_label, title)
            return True
        else:
            logger.error("FAILED: %s -- %s", title, result.stderr.strip())
            return False
    except subprocess.TimeoutExpired:
        logger.error("TIMEOUT: %s", title)
        return False
    except Exception as e:
        logger.error("ERROR: %s -- %s", title, e)
        return False


def create_events(all_events: list[dict], filtered_events: list[dict], schedule_date: str) -> dict:
    """
    Create GCal events from parsed schedule data.

    - Purple (color 3) for filtered (your) events
    - Yellow (color 5) for context events
    - Deduplicates by deleting existing pipeline events for the date

    Returns:
        {
            "events_created": int,
            "your_events": int,
            "context_events": int,
            "deleted_existing": int,
            "errors": [str]
        }
    """
    # Check gog is available
    try:
        _run_gog(['--version'], timeout=5)
    except FileNotFoundError:
        return {
            "events_created": 0,
            "your_events": 0,
            "context_events": 0,
            "deleted_existing": 0,
            "errors": [f"gog CLI not found at {GOG_CMD}"],
            "gcal_skipped": True,
        }

    errors = []

    # Dedup: delete existing pipeline events for this date
    deleted = delete_existing_events(schedule_date)

    # Build set of filtered event keys for matching
    filtered_keys = set()
    for e in filtered_events:
        filtered_keys.add((e['start'], e['end']))

    purple_count = 0
    yellow_count = 0
    success_count = 0

    for event in all_events:
        key = (event['start'], event['end'])
        if key in filtered_keys:
            color_id = 3   # Purple -- attending
            prefix = ""
            purple_count += 1
        else:
            color_id = 5   # Yellow -- not attending
            prefix = ""
            yellow_count += 1

        if create_single_event(event, color_id, prefix):
            success_count += 1
        else:
            errors.append(f"Failed to create: {event.get('title', 'unknown')}")

    return {
        "events_created": success_count,
        "your_events": purple_count,
        "context_events": yellow_count,
        "deleted_existing": deleted,
        "errors": errors,
    }
