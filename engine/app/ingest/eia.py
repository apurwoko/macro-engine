from __future__ import annotations

import logging

import requests

from ..config import load_yaml, settings
from ..db import upsert

log = logging.getLogger(__name__)
EIA_URL = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"


def fetch_series(series: str, api_key: str, length: int = 5000) -> list[dict]:
    params = [
        ("api_key", api_key),
        ("frequency", "weekly"),
        ("data[0]", "value"),
        ("facets[series][]", series),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "desc"),
        ("offset", "0"),
        ("length", str(length)),
    ]
    r = requests.get(EIA_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("response", {}).get("data", [])


def run(full: bool = False) -> dict:
    key = settings().eia_api_key
    if not key:
        raise RuntimeError("EIA_API_KEY belum diisi di .env")
    out: dict[str, object] = {}
    for sid in load_yaml("series.yaml")["eia"]:
        try:
            data = fetch_series(sid, key, length=5000 if full else 60)
            rows = []
            for d in data:
                if d.get("value") in (None, ""):
                    continue
                rows.append({"series_id": f"EIA_{sid}", "obs_date": d["period"], "value": float(d["value"])})
            out[sid] = upsert("macro_observations", rows, update_cols=["value"])
        except Exception as exc:
            log.exception("EIA %s gagal", sid)
            out[sid] = f"ERROR: {exc}"
    return out
