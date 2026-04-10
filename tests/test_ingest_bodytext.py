"""
Tests for body-text email routing in the ingest router.

Covers classification and routing for body-text-only emails (no attachments):
  - CANCELLATION  → _store_body_text_event(payload, "cancellation")  → status="cancellation_logged"
  - EMERGENCY     → _store_body_text_event(payload, "emergency")      → status="emergency_logged"
  - ADDITIONAL_DETAIL → _store_body_text_event(payload, "additional_detail") → status="additional_detail_logged"
  - CAST_CHANGE   → _store_cast_change(payload)                       → status="cast_change_queued"
  - UNKNOWN       → falls through to normal result processing (no early return)
"""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi.testclient import TestClient

from app.routers.ingest import IngestPayload, router

# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------

from fastapi import FastAPI

_app = FastAPI()
_app.include_router(router)
client = TestClient(_app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_mock(fetchone_return=None):
    """
    Return a (mock_conn, mock_cursor) pair whose context-manager behaviour
    matches psycopg2's connection:  `with get_db() as conn: cur = conn.cursor()`.
    """
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = fetchone_return

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    return mock_conn, mock_cursor


@contextmanager
def _db_ctx(mock_conn):
    """A context manager that yields mock_conn, matching get_db()'s protocol."""
    yield mock_conn


def _patch_db(mock_conn):
    """
    Patch app.routers.ingest.get_db to return a fresh context manager over
    mock_conn on every call.  get_db() is called multiple times per request
    (idempotency check + DB writes), so side_effect is used instead of
    return_value to avoid consuming a single-use generator.
    """
    return patch(
        "app.routers.ingest.get_db",
        side_effect=lambda: _db_ctx(mock_conn),
    )


# ---------------------------------------------------------------------------
# Test 1 — Cancellation email is stored and alert fires
# ---------------------------------------------------------------------------

def test_cancellation_email_stored():
    """
    A body-text email with 'cancel' in subject → status='cancellation_logged',
    DB INSERT with reason='cancellation', and send_unknown_format_alert is called.
    """
    mock_conn, mock_cursor = _make_db_mock(fetchone_return=None)

    with _patch_db(mock_conn), \
         patch("app.routers.ingest.send_unknown_format_alert") as mock_alert:

        response = client.post("/api/ingest", json={
            "email_id": "cancel-001",
            "subject": "rehearsal cancelled",
            "body": "The 3pm rehearsal has been cancelled.",
        })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "cancellation_logged"
    assert data["email_id"] == "cancel-001"
    assert data["skipped"] is False

    # Alert must fire
    mock_alert.assert_called_once()
    call_kwargs = mock_alert.call_args
    assert call_kwargs.kwargs["email_id"] == "cancel-001"

    # DB INSERT must include reason='cancellation'
    insert_calls = [
        c for c in mock_cursor.execute.call_args_list
        if "schedule_history" in str(c)
    ]
    assert len(insert_calls) >= 1
    # Verify the reason argument in the INSERT parameters
    found_reason = False
    for c in insert_calls:
        args = c.args  # positional args to execute(sql, params)
        if len(args) >= 2:
            params = args[1]
            if "cancellation" in params:
                found_reason = True
    assert found_reason, "DB INSERT did not include reason='cancellation'"


# ---------------------------------------------------------------------------
# Test 2 — Emergency email stored and alert fires
# ---------------------------------------------------------------------------

def test_emergency_email_stored():
    """
    A body-text email with 'emergency' + 'rehearsal' → status='emergency_logged',
    alert fires.
    """
    mock_conn, mock_cursor = _make_db_mock(fetchone_return=None)

    with _patch_db(mock_conn), \
         patch("app.routers.ingest.send_unknown_format_alert") as mock_alert:

        response = client.post("/api/ingest", json={
            "email_id": "emrg-002",
            "subject": "EMERGENCY Rehearsal at 6:30pm tonight",
            "body": "All Pirates, Lost Boys and James Hook are needed for an EMERGENCY REHEARSAL today at 6:30pm on stage.",
        })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "emergency_logged"
    assert data["email_id"] == "emrg-002"

    mock_alert.assert_called_once()
    assert mock_alert.call_args.kwargs["email_id"] == "emrg-002"

    # DB INSERT must include reason='emergency'
    insert_calls = [
        c for c in mock_cursor.execute.call_args_list
        if "schedule_history" in str(c)
    ]
    found_reason = any(
        "emergency" in str(c.args[1])
        for c in insert_calls
        if len(c.args) >= 2
    )
    assert found_reason, "DB INSERT did not include reason='emergency'"


# ---------------------------------------------------------------------------
# Test 3 — Additional detail email stored and alert fires
# ---------------------------------------------------------------------------

def test_additional_detail_stored():
    """
    A body-text email with 'Additional Detail' in subject →
    status='additional_detail_logged', alert fires.
    """
    mock_conn, mock_cursor = _make_db_mock(fetchone_return=None)

    with _patch_db(mock_conn), \
         patch("app.routers.ingest.send_unknown_format_alert") as mock_alert:

        response = client.post("/api/ingest", json={
            "email_id": "addl-003",
            "subject": "Additional Detail for Friday",
            "body": "Please see additional details for Friday's schedule.",
        })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "additional_detail_logged"
    assert data["email_id"] == "addl-003"

    mock_alert.assert_called_once()
    assert mock_alert.call_args.kwargs["email_id"] == "addl-003"

    insert_calls = [
        c for c in mock_cursor.execute.call_args_list
        if "schedule_history" in str(c)
    ]
    found_reason = any(
        "additional_detail" in str(c.args[1])
        for c in insert_calls
        if len(c.args) >= 2
    )
    assert found_reason, "DB INSERT did not include reason='additional_detail'"


# ---------------------------------------------------------------------------
# Test 4 — Cast change stored with reason='cast_change'
# ---------------------------------------------------------------------------

def test_cast_change_stored():
    """
    A body-text email with 'cast change' in subject/body →
    status='cast_change_queued', stored with reason='cast_change'.
    """
    mock_conn, mock_cursor = _make_db_mock(fetchone_return=None)

    with _patch_db(mock_conn):

        response = client.post("/api/ingest", json={
            "email_id": "cast-004",
            "subject": "Cast Change",
            "body": "Isaac Aguirre will perform Zachary Brickson's role in ZigZag tonight.",
        })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "cast_change_queued"
    assert data["email_id"] == "cast-004"

    insert_calls = [
        c for c in mock_cursor.execute.call_args_list
        if "schedule_history" in str(c)
    ]
    assert len(insert_calls) >= 1
    # _store_cast_change embeds 'cast_change' as a SQL literal in the query
    # string (not as a parameter), so check the SQL string itself.
    found_reason = any(
        "cast_change" in str(c.args[0])
        for c in insert_calls
        if len(c.args) >= 1
    )
    assert found_reason, "DB INSERT did not include reason='cast_change'"


# ---------------------------------------------------------------------------
# Test 5 — Unknown body-text falls through (no early return)
# ---------------------------------------------------------------------------

def test_unknown_body_text_falls_through():
    """
    A body-text email that doesn't match any known pattern (UNKNOWN) must NOT
    return an early status — it falls through to the normal result path and
    returns status='ok' with no attachments processed.
    """
    mock_conn, mock_cursor = _make_db_mock(fetchone_return=None)

    with _patch_db(mock_conn), \
         patch("app.routers.ingest.send_unknown_format_alert") as mock_alert:

        response = client.post("/api/ingest", json={
            "email_id": "unk-005",
            "subject": "Reminder about parking",
            "body": "Please remember to park in the correct spots.",
        })

    assert response.status_code == 200
    data = response.json()
    # Should fall through to the normal processing path
    assert data["status"] == "ok"
    assert data["email_id"] == "unk-005"
    assert data["skipped"] is False
    # No schedule or casting work was done
    assert data["schedules_processed"] == []
    assert data["casting_processed"] == []
    # Alert should NOT fire for unknown body-text (no early routing happened)
    mock_alert.assert_not_called()


# ---------------------------------------------------------------------------
# Test 6 — Body text stored in schedule_history with subject and body
# ---------------------------------------------------------------------------

def test_body_text_stored_with_subject_and_body():
    """
    The JSON payload inserted into schedule_history must include both
    the email subject and body text.
    """
    mock_conn, mock_cursor = _make_db_mock(fetchone_return=None)

    with _patch_db(mock_conn), \
         patch("app.routers.ingest.send_unknown_format_alert"):

        response = client.post("/api/ingest", json={
            "email_id": "store-006",
            "subject": "rehearsal cancelled for today",
            "body": "The afternoon rehearsal has been cancelled due to weather.",
        })

    assert response.status_code == 200
    assert response.json()["status"] == "cancellation_logged"

    # Find the INSERT call into schedule_history and verify JSON payload
    insert_calls = [
        c for c in mock_cursor.execute.call_args_list
        if "schedule_history" in str(c)
    ]
    assert len(insert_calls) >= 1

    found_subject = False
    found_body = False
    for c in insert_calls:
        args = c.args
        if len(args) >= 2:
            params = args[1]
            # params[0] is the JSON string with subject+body
            json_str = params[0]
            try:
                payload_dict = json.loads(json_str)
                if "subject" in payload_dict:
                    found_subject = True
                if "body" in payload_dict:
                    found_body = True
            except (json.JSONDecodeError, TypeError):
                pass

    assert found_subject, "schedule_history INSERT JSON did not include 'subject'"
    assert found_body, "schedule_history INSERT JSON did not include 'body'"


# ---------------------------------------------------------------------------
# Test 7 — Idempotency: already-processed email_id returns skipped=True
#           before body-text classification
# ---------------------------------------------------------------------------

def test_idempotency_skips_before_classification():
    """
    If email_id already exists in schedule_events, the handler returns
    status='skipped'/skipped=True immediately — body-text classification
    is never reached.
    """
    # fetchone returns a row, simulating an existing event
    existing_row = {"id": 42}
    mock_conn, mock_cursor = _make_db_mock(fetchone_return=existing_row)

    with _patch_db(mock_conn), \
         patch("app.routers.ingest.classify_email") as mock_classify, \
         patch("app.routers.ingest.send_unknown_format_alert") as mock_alert:

        response = client.post("/api/ingest", json={
            "email_id": "idem-007",
            "subject": "rehearsal cancelled",
            "body": "The rehearsal is cancelled.",
        })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "skipped"
    assert data["skipped"] is True
    assert data["email_id"] == "idem-007"

    # classify_email must NOT be called — we returned early
    mock_classify.assert_not_called()
    # Alert must NOT fire
    mock_alert.assert_not_called()


# ---------------------------------------------------------------------------
# Test 8 — Alert message includes the email subject
# ---------------------------------------------------------------------------

def test_alert_message_includes_subject():
    """
    send_unknown_format_alert is called with a `method` argument that
    includes the email subject string, so the alert is traceable.
    """
    mock_conn, mock_cursor = _make_db_mock(fetchone_return=None)

    subject = "EMERGENCY Rehearsal at 6:30pm tonight"

    with _patch_db(mock_conn), \
         patch("app.routers.ingest.send_unknown_format_alert") as mock_alert:

        response = client.post("/api/ingest", json={
            "email_id": "alert-008",
            "subject": subject,
            "body": "All Pirates, Lost Boys needed for emergency rehearsal at 6:30pm on stage.",
        })

    assert response.status_code == 200
    assert response.json()["status"] == "emergency_logged"

    mock_alert.assert_called_once()
    call_kwargs = mock_alert.call_args.kwargs
    # The subject must appear somewhere in the alert call arguments
    assert subject in call_kwargs.get("method", ""), (
        f"Expected subject '{subject}' in alert method arg, got: {call_kwargs}"
    )
