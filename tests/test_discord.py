from unittest.mock import patch, MagicMock
from app.services.discord import post_to_discord


def test_post_to_discord_sends_content():
    with patch("app.services.discord.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=204)
        post_to_discord("https://discord.com/api/webhooks/test", "hello world")
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["content"] == "hello world"


def test_post_to_discord_no_webhook_does_not_raise():
    # Should silently do nothing if webhook URL is empty
    post_to_discord("", "hello world")  # no exception


def test_post_to_discord_request_failure_does_not_raise():
    with patch("app.services.discord.requests.post") as mock_post:
        mock_post.side_effect = Exception("network error")
        post_to_discord("https://discord.com/api/webhooks/test", "hello world")
        # Should not raise — Discord failures are non-fatal
