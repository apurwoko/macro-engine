from __future__ import annotations

import logging

import requests

from ..config import settings
from ..db import execute

log = logging.getLogger(__name__)
MAX_LEN = 4000  # batas Telegram 4096


def send(text: str, kind: str = "digest") -> bool:
    s = settings()
    if not (s.telegram_token and s.telegram_chat_id):
        log.info("Telegram tidak dikonfigurasi; pesan dilewati")
        return False
    ok = True
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{s.telegram_token}/sendMessage",
            json={"chat_id": s.telegram_chat_id, "text": text[:MAX_LEN], "disable_web_page_preview": True},
            timeout=15,
        )
        ok = r.ok
        if not ok:
            log.error("Telegram HTTP %s: %s", r.status_code, r.text[:200])
    except Exception:
        log.exception("Telegram gagal")
        ok = False
    try:
        execute("INSERT INTO alerts_log (channel, kind, body, ok) VALUES ('telegram', :k, :b, :ok)",
                k=kind, b=text[:MAX_LEN], ok=int(ok))
    except Exception:
        log.exception("Gagal mencatat alerts_log")
    return ok
