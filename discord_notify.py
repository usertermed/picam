"""Discord webhook notification helper."""
from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Optional

import requests

from config import Config

LOG = logging.getLogger("security_camera.discord")


class DiscordNotifier:
    def __init__(self, config: Config):
        self.config = config
        self._last_sent = 0.0

    def _webhook(self) -> Optional[str]:
        return self.config.as_dict().get("discord", {}).get("webhook_url")

    def test_webhook(self, jpg_bytes: Optional[bytes] = None) -> None:
        if not self.config.discord_enabled():
            raise RuntimeError("Discord disabled")
        return self.notify(datetime.utcnow(), jpg_bytes, test=True)

    def notify(self, timestamp: datetime, image_bytes: Optional[bytes], test: bool = False) -> None:
        url = self._webhook()
        if not url:
            raise RuntimeError("No webhook configured")
        now = timestamp
        payload = {
            "content": f"Motion detected\nDate: {now.date()}\nTime: {now.time()}\nCamera: Logitech C270"
        }
        files = None
        if image_bytes:
            files = {
                "file": ("snapshot.jpg", io.BytesIO(image_bytes), "image/jpeg")
            }
        try:
            # respect cooldown
            cooldown = int(self.config.as_dict().get("discord", {}).get("cooldown_seconds", 30))
            # not enforcing last-sent globally for now
            r = requests.post(url, data=payload, files=files, timeout=10)
            if not r.ok:
                LOG.warning("Discord webhook returned %s: %s", r.status_code, r.text)
            else:
                LOG.info("Discord webhook sent")
        except Exception:
            LOG.exception("Failed to send Discord webhook")
