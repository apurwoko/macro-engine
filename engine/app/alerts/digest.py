from __future__ import annotations

from datetime import datetime, timezone

from ..config import assets_cfg
from ..db import read_df
from ..risk import event_risk_all
from . import telegram

ARROW = {"bullish": "NAIK ", "bearish": "TURUN", "neutral": "NETRAL"}


def latest_bias() -> list[dict]:
    df = read_df(
        "SELECT b.asset_code, b.as_of, b.total, b.bias, b.confidence, b.coverage FROM bias_scores b "
        "JOIN (SELECT asset_code, MAX(as_of) AS m FROM bias_scores GROUP BY asset_code) x "
        "ON x.asset_code=b.asset_code AND x.m=b.as_of ORDER BY b.asset_code"
    )
    return df.to_dict("records")


def build_digest() -> str:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    risks = event_risk_all(now, ahead_h=24)
    names = assets_cfg()
    lines = [f"BIAS FUNDAMENTAL — {now:%Y-%m-%d %H:%M} UTC", ""]
    rows = latest_bias()
    if not rows:
        lines.append("Belum ada skor. Jalankan: python -m app.cli score")
    for r in rows:
        code = r["asset_code"]
        lines.append(
            f"{code:<7} {ARROW[r['bias']]}  skor {r['total']:+.2f}  yakin {r['confidence']:.0%}  data {r['coverage']:.0%}"
        )
        rk = risks.get(code, {})
        if rk.get("blackout"):
            lines.append(f"        !! JANGAN ENTRY: {', '.join(e['title'] for e in rk['blackout_events'])}")
        elif rk.get("upcoming"):
            nxt = rk["upcoming"][0]
            lines.append(f"        event 24j: {nxt['title']} ({nxt['time'][11:16]} UTC)")
    lines += ["", "Bias = filter arah, bukan sinyal entry. Yakin = heuristik, belum terkalibrasi."]
    return "\n".join(lines)


def send_daily() -> dict:
    text = build_digest()
    return {"sent": telegram.send(text, kind="digest"), "chars": len(text)}
