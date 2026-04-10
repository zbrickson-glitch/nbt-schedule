import logging
import requests

logger = logging.getLogger(__name__)


def post_to_discord(webhook_url: str, content: str) -> None:
    """Post a message to a Discord webhook. Silently no-ops on failure."""
    if not webhook_url:
        return
    try:
        requests.post(
            webhook_url,
            json={"content": content},
            timeout=5,
        )
    except Exception as exc:
        logger.warning("Discord notification failed: %s", exc)
