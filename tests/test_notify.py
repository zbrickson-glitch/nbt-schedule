"""
Tests for app.services.notify — send_unknown_format_alert
"""
import json
import unittest
from unittest.mock import MagicMock, call, patch

import pytest

from app.services.notify import send_unknown_format_alert, PDF_TYPE_EMOJI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DISCORD_URL = "https://discord.com/api/webhooks/test/discord"
MM_URL = "https://mattermost.example.com/hooks/test-mm"

BASE_KWARGS = dict(
    filename="mystery-file.pdf",
    subject="NBT Schedule for 3/2",
    email_id="email-abc-123",
    pdf_type="unknown",
    extraction_method="pdfplumber",
    events_extracted=0,
)


def _call_kwargs(mock_request):
    """Return keyword args from the first Request() call."""
    return mock_request.call_args


def _posted_payload(mock_urlopen):
    """Decode the JSON body passed to urlopen from the Request object."""
    req_obj = mock_urlopen.call_args[0][0]
    return json.loads(req_obj.data.decode("utf-8"))


# ---------------------------------------------------------------------------
# 1. Discord webhook called correctly
# ---------------------------------------------------------------------------

class TestDiscordWebhookPayload:
    def test_discord_request_is_posted(self):
        """urlopen is called once when only discord_webhook_url is set."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen") as mock_open, \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = ""
            mock_req.return_value = MagicMock()

            send_unknown_format_alert(**BASE_KWARGS)

            mock_open.assert_called_once()

    def test_discord_request_uses_correct_url(self):
        """Request is constructed with the discord_webhook_url."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = ""
            mock_req.return_value = MagicMock()

            send_unknown_format_alert(**BASE_KWARGS)

            first_arg = mock_req.call_args[0][0]
            assert first_arg == DISCORD_URL

    def test_discord_payload_contains_filename(self):
        """Discord payload embeds fields include filename."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen") as mock_open, \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = ""
            req_obj = MagicMock()
            mock_req.return_value = req_obj
            # Capture body written into Request
            captured = {}

            def capture_request(url, data=None, headers=None, method=None):
                captured["data"] = data
                captured["url"] = url
                return MagicMock()

            mock_req.side_effect = capture_request
            mock_open.return_value = MagicMock()

            send_unknown_format_alert(**BASE_KWARGS)

            payload = json.loads(captured["data"].decode("utf-8"))
            fields = payload["embeds"][0]["fields"]
            field_values = {f["name"]: f["value"] for f in fields}

            assert field_values["Filename"] == BASE_KWARGS["filename"]
            assert field_values["Subject"] == BASE_KWARGS["subject"]
            assert field_values["Email ID"] == BASE_KWARGS["email_id"]
            assert field_values["PDF Type"] == BASE_KWARGS["pdf_type"]
            assert field_values["Extraction Method"] == BASE_KWARGS["extraction_method"]

    def test_discord_payload_content_type_header(self):
        """Request is sent with Content-Type: application/json."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = ""
            captured = {}

            def capture_request(url, data=None, headers=None, method=None):
                captured["headers"] = headers
                return MagicMock()

            mock_req.side_effect = capture_request
            send_unknown_format_alert(**BASE_KWARGS)

            assert captured["headers"]["Content-Type"] == "application/json"

    def test_discord_payload_http_method_is_post(self):
        """Request uses POST method."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = ""
            captured = {}

            def capture_request(url, data=None, headers=None, method=None):
                captured["method"] = method
                return MagicMock()

            mock_req.side_effect = capture_request
            send_unknown_format_alert(**BASE_KWARGS)

            assert captured["method"] == "POST"


# ---------------------------------------------------------------------------
# 2. Mattermost webhook called correctly
# ---------------------------------------------------------------------------

class TestMattermostWebhookPayload:
    def test_mm_request_is_posted(self):
        """urlopen is called once when only mm_webhook_url is set."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen") as mock_open, \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = ""
            mock_settings.mm_webhook_url = MM_URL
            mock_req.return_value = MagicMock()

            send_unknown_format_alert(**BASE_KWARGS)

            mock_open.assert_called_once()

    def test_mm_request_uses_correct_url(self):
        """Request is constructed with the mm_webhook_url."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = ""
            mock_settings.mm_webhook_url = MM_URL
            captured = {}

            def capture_request(url, data=None, headers=None, method=None):
                captured["url"] = url
                return MagicMock()

            mock_req.side_effect = capture_request
            send_unknown_format_alert(**BASE_KWARGS)

            assert captured["url"] == MM_URL

    def test_mm_payload_is_text_dict(self):
        """Mattermost payload is exactly {"text": <message>}."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = ""
            mock_settings.mm_webhook_url = MM_URL
            captured = {}

            def capture_request(url, data=None, headers=None, method=None):
                captured["data"] = data
                return MagicMock()

            mock_req.side_effect = capture_request
            send_unknown_format_alert(**BASE_KWARGS)

            payload = json.loads(captured["data"].decode("utf-8"))
            assert "text" in payload
            assert len(payload) == 1, "MM payload should only have a 'text' key"

    def test_mm_payload_text_contains_all_fields(self):
        """Mattermost text message contains filename, subject, email_id, pdf_type, extraction_method, status."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = ""
            mock_settings.mm_webhook_url = MM_URL
            captured = {}

            def capture_request(url, data=None, headers=None, method=None):
                captured["data"] = data
                return MagicMock()

            mock_req.side_effect = capture_request
            send_unknown_format_alert(**BASE_KWARGS)

            payload = json.loads(captured["data"].decode("utf-8"))
            text = payload["text"]

            assert BASE_KWARGS["filename"] in text
            assert BASE_KWARGS["subject"] in text
            assert BASE_KWARGS["email_id"] in text
            assert BASE_KWARGS["pdf_type"] in text
            assert BASE_KWARGS["extraction_method"] in text


# ---------------------------------------------------------------------------
# 3. Both webhooks fire when both are configured
# ---------------------------------------------------------------------------

class TestBothWebhooks:
    def test_both_webhooks_called_when_both_configured(self):
        """urlopen is called twice when both discord and mm URLs are set."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen") as mock_open, \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = MM_URL
            mock_req.return_value = MagicMock()

            send_unknown_format_alert(**BASE_KWARGS)

            assert mock_open.call_count == 2

    def test_both_webhooks_distinct_urls(self):
        """Discord and Mattermost get distinct URLs in separate Request() calls."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = MM_URL
            urls_seen = []

            def capture_request(url, data=None, headers=None, method=None):
                urls_seen.append(url)
                return MagicMock()

            mock_req.side_effect = capture_request
            send_unknown_format_alert(**BASE_KWARGS)

            assert DISCORD_URL in urls_seen
            assert MM_URL in urls_seen


# ---------------------------------------------------------------------------
# 4. Graceful failure when webhooks not configured (empty string URLs)
# ---------------------------------------------------------------------------

class TestNoWebhooksConfigured:
    def test_no_request_when_discord_url_empty(self):
        """No Request or urlopen call when discord_webhook_url is empty."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen") as mock_open, \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = ""
            mock_settings.mm_webhook_url = ""

            send_unknown_format_alert(**BASE_KWARGS)

            mock_req.assert_not_called()
            mock_open.assert_not_called()

    def test_no_exception_when_both_urls_empty(self):
        """No exception raised when both webhook URLs are empty strings."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request"):
            mock_settings.discord_webhook_url = ""
            mock_settings.mm_webhook_url = ""

            # Must not raise
            send_unknown_format_alert(**BASE_KWARGS)

    def test_only_discord_fires_when_mm_empty(self):
        """Only one request is made when mm_webhook_url is empty."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen") as mock_open, \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = ""
            mock_req.return_value = MagicMock()

            send_unknown_format_alert(**BASE_KWARGS)

            assert mock_open.call_count == 1

    def test_only_mm_fires_when_discord_empty(self):
        """Only one request is made when discord_webhook_url is empty."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen") as mock_open, \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = ""
            mock_settings.mm_webhook_url = MM_URL
            mock_req.return_value = MagicMock()

            send_unknown_format_alert(**BASE_KWARGS)

            assert mock_open.call_count == 1


# ---------------------------------------------------------------------------
# 5. Graceful failure when urlopen raises
# ---------------------------------------------------------------------------

class TestWebhookFailureHandling:
    def test_discord_urlopen_exception_does_not_propagate(self):
        """If urlopen raises for Discord, no exception escapes the function."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen") as mock_open, \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = ""
            mock_req.return_value = MagicMock()
            mock_open.side_effect = Exception("connection refused")

            # Must not raise
            send_unknown_format_alert(**BASE_KWARGS)

    def test_mm_urlopen_exception_does_not_propagate(self):
        """If urlopen raises for Mattermost, no exception escapes the function."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen") as mock_open, \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = ""
            mock_settings.mm_webhook_url = MM_URL
            mock_req.return_value = MagicMock()
            mock_open.side_effect = Exception("timeout")

            # Must not raise
            send_unknown_format_alert(**BASE_KWARGS)

    def test_discord_failure_logged_as_warning(self):
        """A warning is logged when the Discord webhook request fails."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen") as mock_open, \
             patch("app.services.notify.urllib.request.Request") as mock_req, \
             patch("app.services.notify.logger") as mock_logger:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = ""
            mock_req.return_value = MagicMock()
            mock_open.side_effect = Exception("503 Service Unavailable")

            send_unknown_format_alert(**BASE_KWARGS)

            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "Discord" in warning_msg

    def test_mm_failure_logged_as_warning(self):
        """A warning is logged when the Mattermost webhook request fails."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen") as mock_open, \
             patch("app.services.notify.urllib.request.Request") as mock_req, \
             patch("app.services.notify.logger") as mock_logger:
            mock_settings.discord_webhook_url = ""
            mock_settings.mm_webhook_url = MM_URL
            mock_req.return_value = MagicMock()
            mock_open.side_effect = Exception("network error")

            send_unknown_format_alert(**BASE_KWARGS)

            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "Mattermost" in warning_msg

    def test_second_webhook_fires_even_if_first_fails(self):
        """If Discord fails, Mattermost still receives its request."""
        call_urls = []
        call_count = [0]

        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen") as mock_open, \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = MM_URL

            def capture_request(url, data=None, headers=None, method=None):
                call_urls.append(url)
                return MagicMock()

            mock_req.side_effect = capture_request
            call_count_open = [0]

            def open_side_effect(req):
                call_count_open[0] += 1
                if call_count_open[0] == 1:
                    raise Exception("Discord is down")
                return MagicMock()

            mock_open.side_effect = open_side_effect

            # Must not raise
            send_unknown_format_alert(**BASE_KWARGS)

            # Both URLs should have been constructed
            assert DISCORD_URL in call_urls
            assert MM_URL in call_urls


# ---------------------------------------------------------------------------
# 6. All pdf_type emoji mappings produce a message
# ---------------------------------------------------------------------------

class TestPdfTypeEmojiMappings:
    PDF_TYPES = [
        "unknown",
        "maag",
        "cancellation",
        "emergency",
        "additional_detail",
        "body_text_logged",
    ]

    @pytest.mark.parametrize("pdf_type", PDF_TYPES)
    def test_each_pdf_type_produces_message(self, pdf_type):
        """Every supported pdf_type triggers a webhook call without error."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen") as mock_open, \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = ""
            mock_req.return_value = MagicMock()

            send_unknown_format_alert(
                filename="test.pdf",
                subject="Test Subject",
                email_id="email-001",
                pdf_type=pdf_type,
                extraction_method="pdfplumber",
                events_extracted=0,
            )

            mock_open.assert_called_once()

    @pytest.mark.parametrize("pdf_type", PDF_TYPES)
    def test_each_pdf_type_in_message_text(self, pdf_type):
        """The pdf_type string appears in the outgoing Mattermost message text."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = ""
            mock_settings.mm_webhook_url = MM_URL
            captured = {}

            def capture_request(url, data=None, headers=None, method=None):
                captured["data"] = data
                return MagicMock()

            mock_req.side_effect = capture_request

            send_unknown_format_alert(
                filename="test.pdf",
                subject="Test Subject",
                email_id="email-001",
                pdf_type=pdf_type,
                extraction_method="pdfplumber",
                events_extracted=0,
            )

            payload = json.loads(captured["data"].decode("utf-8"))
            assert pdf_type in payload["text"]

    @pytest.mark.parametrize("pdf_type,expected_emoji", list(PDF_TYPE_EMOJI.items()))
    def test_each_pdf_type_emoji_in_message(self, pdf_type, expected_emoji):
        """The correct emoji for each pdf_type appears in the message text."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = ""
            mock_settings.mm_webhook_url = MM_URL
            captured = {}

            def capture_request(url, data=None, headers=None, method=None):
                captured["data"] = data
                return MagicMock()

            mock_req.side_effect = capture_request

            send_unknown_format_alert(
                filename="test.pdf",
                subject="Test",
                email_id="eid",
                pdf_type=pdf_type,
                extraction_method="pdfplumber",
                events_extracted=0,
            )

            payload = json.loads(captured["data"].decode("utf-8"))
            assert expected_emoji in payload["text"]

    def test_unknown_pdf_type_still_produces_message(self):
        """A completely unrecognized pdf_type uses a default emoji and does not crash."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen") as mock_open, \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = ""
            mock_req.return_value = MagicMock()

            send_unknown_format_alert(
                filename="weird.pdf",
                subject="Weird",
                email_id="eid-999",
                pdf_type="some_future_type_not_in_map",
                extraction_method="llm",
                events_extracted=0,
            )

            mock_open.assert_called_once()


# ---------------------------------------------------------------------------
# 7. events_extracted > 0 vs 0 status messages
# ---------------------------------------------------------------------------

class TestEventsExtractedStatus:
    def _get_mm_text(self, events_extracted: int) -> str:
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = ""
            mock_settings.mm_webhook_url = MM_URL
            captured = {}

            def capture_request(url, data=None, headers=None, method=None):
                captured["data"] = data
                return MagicMock()

            mock_req.side_effect = capture_request

            send_unknown_format_alert(
                filename="schedule.pdf",
                subject="Schedule",
                email_id="eid-001",
                pdf_type="unknown",
                extraction_method="pdfplumber",
                events_extracted=events_extracted,
            )

            return json.loads(captured["data"].decode("utf-8"))["text"]

    def test_zero_events_includes_manual_review_message(self):
        """When events_extracted=0, status says manual review needed."""
        text = self._get_mm_text(events_extracted=0)
        assert "0 events extracted" in text
        assert "manual review" in text

    def test_positive_events_includes_count_in_status(self):
        """When events_extracted > 0, the count appears in the status."""
        text = self._get_mm_text(events_extracted=5)
        assert "5 event(s) extracted" in text

    def test_positive_events_does_not_include_manual_review(self):
        """When events were successfully extracted, no manual-review warning shown."""
        text = self._get_mm_text(events_extracted=3)
        assert "manual review" not in text

    def test_single_event_extracted(self):
        """Edge case: exactly 1 event extracted."""
        text = self._get_mm_text(events_extracted=1)
        assert "1 event(s) extracted" in text

    def test_discord_field_status_zero_events(self):
        """Discord embed Status field reflects 0 events message."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = ""
            captured = {}

            def capture_request(url, data=None, headers=None, method=None):
                captured["data"] = data
                return MagicMock()

            mock_req.side_effect = capture_request

            send_unknown_format_alert(
                filename="schedule.pdf",
                subject="Schedule",
                email_id="eid-001",
                pdf_type="unknown",
                extraction_method="pdfplumber",
                events_extracted=0,
            )

            payload = json.loads(captured["data"].decode("utf-8"))
            fields = {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}
            assert "0 events extracted" in fields["Status"]
            assert "manual review" in fields["Status"]

    def test_discord_field_status_positive_events(self):
        """Discord embed Status field shows count when events > 0."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = ""
            captured = {}

            def capture_request(url, data=None, headers=None, method=None):
                captured["data"] = data
                return MagicMock()

            mock_req.side_effect = capture_request

            send_unknown_format_alert(
                filename="schedule.pdf",
                subject="Schedule",
                email_id="eid-001",
                pdf_type="unknown",
                extraction_method="pdfplumber",
                events_extracted=7,
            )

            payload = json.loads(captured["data"].decode("utf-8"))
            fields = {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}
            assert "7 event(s) extracted" in fields["Status"]


# ---------------------------------------------------------------------------
# 8. Message formatting — verify all key fields present
# ---------------------------------------------------------------------------

class TestMessageFormatting:
    def test_mm_message_contains_all_key_fields(self):
        """Mattermost message text includes all six required data fields."""
        kwargs = dict(
            filename="monday-3-2-26.pdf",
            subject="Monday 3/2 Artist Daily Schedule",
            email_id="msg-id-555",
            pdf_type="maag",
            extraction_method="llm",
            events_extracted=12,
        )
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = ""
            mock_settings.mm_webhook_url = MM_URL
            captured = {}

            def capture_request(url, data=None, headers=None, method=None):
                captured["data"] = data
                return MagicMock()

            mock_req.side_effect = capture_request

            send_unknown_format_alert(**kwargs)

            payload = json.loads(captured["data"].decode("utf-8"))
            text = payload["text"]

            assert kwargs["filename"] in text
            assert kwargs["subject"] in text
            assert kwargs["email_id"] in text
            assert kwargs["pdf_type"] in text
            assert kwargs["extraction_method"] in text
            assert "12 event(s) extracted" in text

    def test_discord_embed_contains_all_required_field_names(self):
        """Discord embed fields include Filename, Subject, Email ID, PDF Type, Extraction Method, Status."""
        required_field_names = {
            "Filename", "Subject", "Email ID", "PDF Type", "Extraction Method", "Status"
        }
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = ""
            captured = {}

            def capture_request(url, data=None, headers=None, method=None):
                captured["data"] = data
                return MagicMock()

            mock_req.side_effect = capture_request

            send_unknown_format_alert(**BASE_KWARGS)

            payload = json.loads(captured["data"].decode("utf-8"))
            field_names = {f["name"] for f in payload["embeds"][0]["fields"]}
            assert required_field_names.issubset(field_names)

    def test_discord_embed_has_title(self):
        """Discord embed has a non-empty title."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = DISCORD_URL
            mock_settings.mm_webhook_url = ""
            captured = {}

            def capture_request(url, data=None, headers=None, method=None):
                captured["data"] = data
                return MagicMock()

            mock_req.side_effect = capture_request

            send_unknown_format_alert(**BASE_KWARGS)

            payload = json.loads(captured["data"].decode("utf-8"))
            title = payload["embeds"][0].get("title", "")
            assert title  # non-empty

    def test_alert_message_header_present(self):
        """The message contains the NBT Unknown Format Alert header text."""
        with patch("app.services.notify.settings") as mock_settings, \
             patch("app.services.notify.urllib.request.urlopen"), \
             patch("app.services.notify.urllib.request.Request") as mock_req:
            mock_settings.discord_webhook_url = ""
            mock_settings.mm_webhook_url = MM_URL
            captured = {}

            def capture_request(url, data=None, headers=None, method=None):
                captured["data"] = data
                return MagicMock()

            mock_req.side_effect = capture_request

            send_unknown_format_alert(**BASE_KWARGS)

            payload = json.loads(captured["data"].decode("utf-8"))
            assert "NBT Unknown Format Alert" in payload["text"]

    def test_different_filenames_produce_different_messages(self):
        """Two calls with different filenames produce distinct message texts."""
        texts = []
        for fn in ["file-a.pdf", "file-b.pdf"]:
            with patch("app.services.notify.settings") as mock_settings, \
                 patch("app.services.notify.urllib.request.urlopen"), \
                 patch("app.services.notify.urllib.request.Request") as mock_req:
                mock_settings.discord_webhook_url = ""
                mock_settings.mm_webhook_url = MM_URL
                captured = {}

                def capture_request(url, data=None, headers=None, method=None):
                    captured["data"] = data
                    return MagicMock()

                mock_req.side_effect = capture_request

                send_unknown_format_alert(
                    filename=fn,
                    subject="Same Subject",
                    email_id="same-id",
                    pdf_type="unknown",
                    extraction_method="pdfplumber",
                    events_extracted=0,
                )

                payload = json.loads(captured["data"].decode("utf-8"))
                texts.append(payload["text"])

        assert texts[0] != texts[1]
