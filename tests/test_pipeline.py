import base64
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


def _make_client():
    from app.main import app
    return TestClient(app)


SENDER = "bwahlquist@nevadaballet.org"


def test_pipeline_nbt_requires_message_id():
    client = _make_client()
    resp = client.post("/api/pipeline/nbt", json={"sender": SENDER})
    assert resp.status_code == 422  # missing required field message_id


def test_pipeline_nbt_skips_duplicate():
    """If message_id already in DB, return skipped without reprocessing."""
    client = _make_client()
    with patch("app.routers.pipeline._already_processed", return_value=True):
        resp = client.post("/api/pipeline/nbt", json={
            "message_id": "test-dupe-123",
            "sender": SENDER,
            "subject": "Schedule",
            "body": "",
            "attachments": []
        })
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"


def test_pipeline_nbt_no_attachments_returns_no_pdf():
    """Email with no attachments returns no_pdf status."""
    client = _make_client()
    with patch("app.routers.pipeline._already_processed", return_value=False), \
         patch("app.routers.pipeline.post_to_discord"):
        resp = client.post("/api/pipeline/nbt", json={
            "message_id": "test-nopdf-456",
            "sender": SENDER,
            "subject": "Hi",
            "body": "Just checking in",
            "attachments": []
        })
    assert resp.status_code == 200
    assert resp.json()["status"] == "no_pdf"


def test_pipeline_nbt_discord_notified_on_receive():
    """Discord is notified when email arrives (even if no PDF)."""
    client = _make_client()
    with patch("app.routers.pipeline._already_processed", return_value=False), \
         patch("app.routers.pipeline.post_to_discord") as mock_discord:
        client.post("/api/pipeline/nbt", json={
            "message_id": "test-discord-789",
            "sender": SENDER,
            "subject": "Test Subject",
            "body": "",
            "attachments": []
        })
    # Discord should have been called at least once
    assert mock_discord.called


def test_pipeline_nbt_casting_returns_manual():
    """Casting email returns manual status (no DB write)."""
    client = _make_client()
    fake_pdf = base64.b64encode(b"%PDF-1.4 fake").decode()
    with patch("app.routers.pipeline._already_processed", return_value=False), \
         patch("app.routers.pipeline.post_to_discord"):
        resp = client.post("/api/pipeline/nbt", json={
            "message_id": "test-cast-001",
            "sender": SENDER,
            "subject": "ZigZag RR Casting",
            "body": "",
            "attachments": [{"filename": "zigzag-rr.pdf", "data": fake_pdf}]
        })
    assert resp.status_code == 200
    assert resp.json()["status"] == "manual"


def test_pipeline_stores_multiple_events_from_one_email(schedule_monday_pdf):
    """A single email with multiple events should store ALL of them with source_email_id set."""
    import pathlib
    from app.routers.pipeline import _handle_schedule, _store_events_atomically, _already_processed
    from app.routers.pipeline import EmailPayload, AttachmentPayload

    # Build payload with the real schedule PDF
    pdf_bytes = pathlib.Path(schedule_monday_pdf).read_bytes()
    payload = EmailPayload(
        message_id="test-multi-event-001",
        sender="bwahlquist@nevadaballet.org",
        subject="Test Schedule",
        body="",
        attachments=[AttachmentPayload(
            filename="schedule.pdf",
            data=base64.b64encode(pdf_bytes).decode()
        )]
    )

    # Call the handler with mocked DB and Discord
    stored_events = []
    def fake_store(events, msg_id):
        stored_events.extend(events)
        return len(events)

    with patch("app.routers.pipeline._already_processed", return_value=False), \
         patch("app.routers.pipeline._store_events_atomically", side_effect=fake_store), \
         patch("app.routers.pipeline._get_zach_calls", return_value=[]), \
         patch("app.routers.pipeline.post_to_discord"):
        resp = _make_client().post("/api/pipeline/nbt", json=payload.dict())

    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "ok"
    # A real schedule PDF should have more than 1 event
    assert result["events_stored"] > 1, \
        f"Expected multiple events from schedule PDF, got {result['events_stored']}"
