from __future__ import annotations

import logging
from datetime import timedelta

import pandas as pd
import requests

from ..config import load_yaml, settings
from ..db import scalar, upsert

log = logging.getLogger(__name__)
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"


def fetch_series(series_id: str, api_key: str, start: str) -> pd.DataFrame:
    r = requests.get(
        FRED_URL,
        params={"series_id": series_id, "api_key": api_key, "file_type": "json", "observation_start": start},
        timeout=30,
    )
    r.raise_for_status()
    df = pd.DataFrame(r.json().get("observations", []))
    if df.empty:
        return pd.DataFrame(columns=["date", "value"])
    df = df[["date", "value"]].copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # FRED memakai "." untuk data kosong
    return df.dropna()


def run(full: bool = False) -> dict:
    key = settings().fred_api_key
    if not key:
        raise RuntimeError("FRED_API_KEY belum diisi di .env")
    cfg = load_yaml("series.yaml")
    out: dict[str, object] = {}
    for sid in cfg["fred"]:
        try:
            last = scalar("SELECT MAX(obs_date) FROM macro_observations WHERE series_id=:s", s=sid)
            # ambil ulang 45 hari ke belakang: angka bulanan sering direvisi
            start = cfg["history_start"] if (full or last is None) else (last - timedelta(days=45)).isoformat()
            df = fetch_series(sid, key, start)
            rows = [{"series_id": sid, "obs_date": d, "value": float(v)} for d, v in zip(df["date"], df["value"])]
            out[sid] = upsert("macro_observations", rows, update_cols=["value"])
        except Exception as exc:  # satu seri gagal tidak boleh menghentikan yang lain
            log.exception("FRED %s gagal", sid)
            out[sid] = f"ERROR: {exc}"
    return out
