"""Impor kalender ekonomi dari CSV.

Format (lihat data/calendar_template.csv):
  event_time_utc,currency,country,title,impact,forecast,previous,actual
  2026-11-06 13:30,USD,US,Nonfarm Payrolls,high,180K,175K,

Kalender dengan konsensus yang andal biasanya berbayar (Trading Economics, dsb.). Untuk fase awal,
isi event berdampak tinggi secara manual (FOMC, CPI, NFP, rapat bank sentral, OPEC+) dari kalender
resmi bank sentral/BLS, lalu ganti dengan penyedia API bila sudah berlangganan.
"""
from __future__ import annotations

import pandas as pd

from ..db import upsert

VALID_IMPACT = {"low", "medium", "high"}


def parse_csv(path: str) -> list[dict]:
    df = pd.read_csv(path, dtype=str).fillna("")
    required = {"event_time_utc", "currency", "title"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Kolom wajib hilang: {sorted(missing)}")
    rows = []
    for _, r in df.iterrows():
        impact = (r.get("impact") or "medium").strip().lower()
        if impact not in VALID_IMPACT:
            raise ValueError(f"impact tidak valid '{impact}' pada baris: {r.to_dict()}")
        rows.append(
            {
                "event_time": pd.to_datetime(r["event_time_utc"]).to_pydatetime().replace(tzinfo=None),
                "country": (r.get("country") or "").strip().upper()[:8],
                "currency": r["currency"].strip().upper()[:3],
                "title": r["title"].strip()[:160],
                "impact": impact,
                "forecast": (r.get("forecast") or None),
                "previous": (r.get("previous") or None),
                "actual": (r.get("actual") or None),
            }
        )
    return rows


def import_csv(path: str) -> int:
    return upsert("calendar_events", parse_csv(path))
