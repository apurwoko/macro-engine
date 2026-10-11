from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from ..config import load_yaml
from ..db import upsert

log = logging.getLogger(__name__)


def _published(entry) -> datetime:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if t:
        return datetime(*t[:6])  # feedparser memberi struct_time UTC
    return datetime.now(timezone.utc).replace(tzinfo=None)


def run(full: bool = False) -> dict:
    import feedparser

    out: dict[str, object] = {}
    for feed in load_yaml("feeds.yaml")["feeds"]:
        try:
            parsed = feedparser.parse(feed["url"])
            rows = []
            for e in parsed.entries:
                link = e.get("link") or ""
                title = (e.get("title") or "").strip()
                if not title:
                    continue
                rows.append(
                    {
                        "url_hash": hashlib.sha1((link or title).encode("utf-8")).hexdigest(),
                        "published_at": _published(e),
                        "source": feed["name"][:64],
                        "title": title[:400],
                        "url": link[:600] or None,
                        "summary": (e.get("summary") or "")[:2000] or None,
                    }
                )
            # update_cols=[] -> INSERT IGNORE: headline yang sudah ada (dan sudah diproses LLM) tidak ditimpa
            out[feed["name"]] = upsert("headlines", rows, update_cols=[])
        except Exception as exc:
            log.exception("Feed %s gagal", feed.get("name"))
            out[feed.get("name", "?")] = f"ERROR: {exc}"
    return out
