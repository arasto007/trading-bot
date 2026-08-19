"""اعلان‌ها — فایل + Telegram اختیاری."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, base_dir: str | Path = ".") -> None:
        self._log_path = Path(base_dir) / "logs" / "alerts.log"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self._telegram_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    def alert(self, level: str, message: str, **extra: Any) -> None:
        line = f"{level.upper()} | {message}"
        if extra:
            line += f" | {extra}"
        try:
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            logger.debug("alert log failed: %s", e)
        if level in ("critical", "error", "warn"):
            logger.log(
                logging.CRITICAL if level == "critical" else logging.WARNING,
                message,
            )
        self._send_telegram(line)

    def _send_telegram(self, text: str) -> None:
        if not self._telegram_token or not self._telegram_chat:
            return
        try:
            import urllib.parse
            import urllib.request

            url = (
                f"https://api.telegram.org/bot{self._telegram_token}/sendMessage?"
                f"{urllib.parse.urlencode({'chat_id': self._telegram_chat, 'text': text[:4000]})}"
            )
            urllib.request.urlopen(url, timeout=5)  # noqa: S310
        except Exception as e:
            logger.debug("telegram send failed: %s", e)
