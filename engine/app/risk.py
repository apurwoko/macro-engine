"""Filter risiko event: apakah ada rilis/keputusan besar di sekitar waktu sekarang?"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .config import assets_cfg
from .db import read_df


def relevant(asset_cfg: dict, ev: dict) -> bool:
    if ev["currency"] not in (asset_cfg.get("currencies") or []):
        return False
    if ev["impact"] == "high":
        return True
    title = ev["title"].lower()
    return any(k.lower() in title for k in asset_cfg.get("event_keywords") or [])


def event_risk(
    asset_cfg: dict,
    now: datetime,
    events: list[dict],
    ahead_h: int = 24,
    before_min: int = 120,
    after_min: int = 60,
) -> dict[str, Any]:
    """Murni (tanpa I/O). `now` dan event_time: datetime naive UTC.

    blackout = ada event relevan dengan  event_time - before_min <= now <= event_time + after_min.
    """
    upcoming, blackout = [], []
    for ev in events:
        if not relevant(asset_cfg, ev):
            continue
        t = ev["event_time"]
        item = {"time": t.isoformat(), "currency": ev["currency"], "title": ev["title"], "impact": ev["impact"]}
        if t - timedelta(minutes=before_min) <= now <= t + timedelta(minutes=after_min):
            blackout.append(item)
        if now <= t <= now + timedelta(hours=ahead_h):
            upcoming.append(item)
    return {"blackout": bool(blackout), "blackout_events": blackout, "upcoming": upcoming}


def load_events(now: datetime, hours: int = 48, back_h: int = 3) -> list[dict]:
    df = read_df(
        "SELECT event_time, currency, title, impact FROM calendar_events "
        "WHERE event_time BETWEEN :a AND :b ORDER BY event_time",
        a=now - timedelta(hours=back_h), b=now + timedelta(hours=hours),
    )
    return [
        {"event_time": r.event_time.to_pydatetime(), "currency": r.currency, "title": r.title, "impact": r.impact}
        for r in df.itertuples()
    ]


def event_risk_all(now: datetime, ahead_h: int = 24) -> dict[str, dict]:
    events = load_events(now, hours=max(ahead_h, 24))
    return {code: event_risk(cfg, now, events, ahead_h=ahead_h) for code, cfg in assets_cfg().items()}
