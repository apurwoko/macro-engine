"""Mesin skor faktor fundamental. Fungsi murni: data masuk lewat `loader`, tanpa akses DB.

Alur per faktor:  deret -> transform (diff/pct/level) -> z-score terhadap riwayatnya
                  -> skor diskret -2..+2 -> dikali arah (direction).
Agregasi: total = sum(skor * bobot) / (2 * sum(bobot yang datanya ada))  -> -1..+1
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Callable

import numpy as np
import pandas as pd

Loader = Callable[[str], pd.Series]
NewsLoader = Callable[[str, pd.Timestamp], "float | None"]


def z_to_score(z: float | None) -> float | None:
    if z is None or not np.isfinite(z):
        return None
    a = abs(z)
    s = 0 if a < 0.5 else (1 if a < 1.25 else 2)
    return float(np.sign(z) * s)


def transform(s: pd.Series, kind: str, window: int) -> pd.Series:
    s = s.dropna()
    if kind == "level":
        return s
    if kind == "diff":
        return s - s.shift(window)
    if kind == "pct":
        return s.pct_change(window, fill_method=None)
    raise ValueError(f"transform tidak dikenal: {kind}")


def zscore_last(m: pd.Series, lookback: int, min_obs: int = 30) -> tuple[float | None, float | None]:
    m = m.dropna()
    if len(m) < min_obs:
        return None, None
    hist = m.iloc[-lookback:]
    sd = hist.std(ddof=1)
    if not np.isfinite(sd) or sd == 0:
        return None, None
    return float((m.iloc[-1] - hist.mean()) / sd), float(m.iloc[-1])


def _score_factor(f: dict, code: str, loader: Loader, news_loader: NewsLoader | None, asof: pd.Timestamp) -> dict:
    rec = {
        "factor": f["name"], "source": f["source"], "weight": float(f.get("weight", 1.0)),
        "direction": float(f.get("direction", 1)), "raw": None, "z": None, "score": None, "status": "ok",
    }
    try:
        if f["source"] == "news":
            tone = news_loader(code, asof) if news_loader else None
            if tone is None:
                rec["status"] = "missing"
            else:
                rec["raw"] = float(tone)
                rec["score"] = float(np.clip(tone, -2, 2)) * rec["direction"]
            return rec

        s = loader(f["source"])
        s = s[s.index <= asof]
        if s.empty:
            rec["status"] = "missing"
            return rec
        if (asof - s.index[-1]).days > int(f.get("max_age_days", 7)):
            rec["status"] = "stale"
            return rec
        m = transform(s, f.get("transform", "level"), int(f.get("window", 20)))
        z, raw = zscore_last(m, int(f.get("lookback", 750)))
        if z is None:
            rec["status"] = "missing"
            return rec
        rec["z"], rec["raw"] = z, raw
        rec["score"] = z_to_score(z) * rec["direction"]
    except Exception as exc:  # satu faktor rusak tidak boleh menjatuhkan seluruh aset
        rec["status"] = "error"
        rec["error"] = str(exc)
    return rec


def score_asset(
    code: str,
    cfg: dict,
    loader: Loader,
    news_loader: NewsLoader | None = None,
    asof: date | datetime | pd.Timestamp | None = None,
    threshold: float = 0.2,
) -> dict:
    asof_ts = pd.Timestamp(asof or datetime.now(timezone.utc).date()).normalize()
    factors = [_score_factor(f, code, loader, news_loader, asof_ts) for f in cfg["factors"]]

    total_w = sum(r["weight"] for r in factors)
    usable = [r for r in factors if r["score"] is not None]
    used_w = sum(r["weight"] for r in usable)
    if used_w == 0:
        return {"asset": code, "as_of": asof_ts.date(), "total": 0.0, "bias": "neutral",
                "confidence": 0.0, "coverage": 0.0, "factors": factors}

    total = sum(r["score"] * r["weight"] for r in usable) / (2.0 * used_w)
    coverage = used_w / total_w
    signed = [r for r in usable if r["score"] != 0]
    sw = sum(r["weight"] for r in signed)
    agree_w = sum(r["weight"] for r in signed if np.sign(r["score"]) == np.sign(total))
    agreement = (agree_w / sw) if (sw > 0 and total != 0) else 0.0
    # Heuristik, BELUM terkalibrasi: besar skor x kesepakatan faktor x kelengkapan data
    confidence = float(min(1.0, abs(total) / 0.5) * agreement * coverage)
    bias = "bullish" if total >= threshold else ("bearish" if total <= -threshold else "neutral")
    return {"asset": code, "as_of": asof_ts.date(), "total": float(total), "bias": bias,
            "confidence": confidence, "coverage": float(coverage), "factors": factors}
