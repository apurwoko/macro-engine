"""Loader deret waktu dari MySQL.

Kunci:  fred:DGS10 | eia:WCESTUS1 | px:GC=F | cot:GOLD
pit=True menggeser indeks sebesar jeda publikasi (config/series.yaml) sehingga setiap nilai
hanya "terlihat" pada tanggal data itu benar-benar tersedia (point-in-time, anti look-ahead).
Untuk regresi beta mingguan antar harga pasar gunakan pit=False.
"""
from __future__ import annotations

import pandas as pd

from ..config import load_yaml
from ..db import read_df


def lag_days(key: str) -> int:
    cfg = load_yaml("series.yaml")
    lags = cfg.get("lags") or {}
    if key in lags:
        return int(lags[key])
    return int((cfg.get("default_lags") or {}).get(key.split(":", 1)[0], 0))


def _to_series(df: pd.DataFrame, date_col: str, val_col: str, name: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float, name=name, index=pd.DatetimeIndex([]))
    s = pd.Series(df[val_col].astype(float).to_numpy(), index=pd.to_datetime(df[date_col]), name=name)
    return s[~s.index.duplicated(keep="last")].sort_index()


def load(key: str, start: str | None = None, pit: bool = True) -> pd.Series:
    src, _, ident = key.partition(":")
    start = start or "1990-01-01"
    if src in ("fred", "eia"):
        sid = ident if src == "fred" else f"EIA_{ident}"
        df = read_df(
            "SELECT obs_date, value FROM macro_observations WHERE series_id=:s AND obs_date>=:d ORDER BY obs_date",
            s=sid, d=start,
        )
        s = _to_series(df, "obs_date", "value", key)
    elif src == "px":
        df = read_df(
            "SELECT trade_date, close FROM prices_daily WHERE symbol=:s AND trade_date>=:d ORDER BY trade_date",
            s=ident, d=start,
        )
        s = _to_series(df, "trade_date", "close", key)
    elif src == "cot":
        df = read_df(
            "SELECT report_date, net_pos FROM cot_positions WHERE market_key=:s AND report_date>=:d ORDER BY report_date",
            s=ident, d=start,
        )
        s = _to_series(df, "report_date", "net_pos", key)
    else:
        raise ValueError(f"Sumber data tidak dikenal: {key}")

    if pit and len(s):
        lag = lag_days(key)
        if lag:
            s.index = s.index + pd.Timedelta(days=lag)
    return s


def make_cached_loader(start: str | None = None, pit: bool = True):
    """Loader dengan memo di memori, agar satu kunci hanya dibaca sekali per proses/run."""
    cache: dict[str, pd.Series] = {}

    def _loader(key: str) -> pd.Series:
        if key not in cache:
            cache[key] = load(key, start=start, pit=pit)
        return cache[key]

    return _loader
