from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from ..config import assets_cfg, load_yaml
from ..db import scalar, upsert

log = logging.getLogger(__name__)


def symbols() -> list[str]:
    syms = [a["px"] for a in assets_cfg().values()]
    syms += load_yaml("assets.yaml").get("extra_px", [])
    return sorted(set(syms))


def fetch(symbol: str, start: str) -> pd.DataFrame:
    """Harga harian dari Yahoo Finance (tidak resmi; jangan jadikan tulang punggung produksi)."""
    import yfinance as yf

    h = yf.Ticker(symbol).history(start=start, auto_adjust=False, actions=False)
    if h is None or h.empty:
        return pd.DataFrame()
    h = h.copy()
    h.index = pd.to_datetime(h.index).tz_localize(None).normalize()
    h = h.rename(columns=str.lower)
    return h[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])


def run(full: bool = False) -> dict:
    out: dict[str, object] = {}
    default_start = load_yaml("series.yaml")["history_start"]
    for sym in symbols():
        try:
            last = scalar("SELECT MAX(trade_date) FROM prices_daily WHERE symbol=:s", s=sym)
            start = default_start if (full or last is None) else (last - timedelta(days=10)).isoformat()
            df = fetch(sym, start)
            rows = [
                {
                    "symbol": sym,
                    "trade_date": idx.date(),
                    "open": r.open, "high": r.high, "low": r.low, "close": r.close,
                    "volume": r.volume,
                }
                for idx, r in df.iterrows()
            ]
            out[sym] = upsert("prices_daily", rows)
        except Exception as exc:
            log.exception("Harga %s gagal", sym)
            out[sym] = f"ERROR: {exc}"
    return out
