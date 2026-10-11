"""CFTC Commitments of Traders (futures-only), diunduh langsung dari arsip tahunan CFTC."""
from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import date

import pandas as pd
import requests

from ..config import load_yaml
from ..db import upsert

log = logging.getLogger(__name__)

URLS = {
    "disagg": "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip",
    "fin": "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip",
}
CODE_COLS = ("CFTC_Contract_Market_Code", "CFTC Contract Market Code")
DATE_COLS = ("Report_Date_as_YYYY-MM-DD", "As_of_Date_In_Form_YYYY-MM-DD", "Report_Date_as_YYYY_MM_DD")
NAME_COLS = ("Market_and_Exchange_Names", "Market and Exchange Names")
OI_COLS = ("Open_Interest_All",)


def _norm(c: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_")


def find_col(df: pd.DataFrame, *candidates: str, required: bool = True) -> str | None:
    """Cari kolom tanpa peduli beda spasi/underscore/huruf besar-kecil (header CFTC tidak konsisten)."""
    m = {_norm(c): c for c in df.columns}
    for cand in candidates:
        if _norm(cand) in m:
            return m[_norm(cand)]
    if required:
        raise KeyError(f"Kolom {candidates} tidak ditemukan. Kolom tersedia: {list(df.columns)[:12]}...")
    return None


def parse_market(df: pd.DataFrame, key: str, mcfg: dict) -> pd.DataFrame:
    """Saring satu pasar dari tabel mentah CFTC dan hitung net posisi. Murni (tanpa I/O)."""
    code_col = find_col(df, *CODE_COLS)
    date_col = find_col(df, *DATE_COLS)
    long_col = find_col(df, mcfg["long"])
    short_col = find_col(df, mcfg["short"])
    name_col = find_col(df, *NAME_COLS, required=False)
    oi_col = find_col(df, *OI_COLS, required=False)

    codes = df[code_col].astype(str).str.strip().str.lstrip("0")
    sub = df[codes == str(mcfg["code"]).lstrip("0")].copy()
    if sub.empty:
        return pd.DataFrame()
    out = pd.DataFrame(
        {
            "market_key": key,
            "report_date": pd.to_datetime(sub[date_col]).dt.date,
            "report_type": mcfg["report"],
            "contract_code": str(mcfg["code"]),
            "long_pos": pd.to_numeric(sub[long_col], errors="coerce"),
            "short_pos": pd.to_numeric(sub[short_col], errors="coerce"),
            "open_interest": pd.to_numeric(sub[oi_col], errors="coerce") if oi_col else None,
        }
    )
    out = out.dropna(subset=["long_pos", "short_pos"])
    out["net_pos"] = out["long_pos"] - out["short_pos"]
    if name_col is not None and len(sub):
        out.attrs["market_name"] = str(sub[name_col].iloc[0])
    return out.drop_duplicates(subset=["market_key", "report_date"], keep="last")


def download_year(report: str, year: int) -> pd.DataFrame | None:
    url = URLS[report].format(year=year)
    r = requests.get(url, timeout=120)
    if r.status_code == 404:
        log.warning("COT %s %s belum tersedia (404)", report, year)
        return None
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        member = zf.namelist()[0]
        with zf.open(member) as fh:
            return pd.read_csv(fh, dtype=str, low_memory=False)  # dtype=str: pertahankan nol di depan kode kontrak


def run(full: bool = False) -> dict:
    cfg = load_yaml("cot.yaml")
    this_year = date.today().year
    years = range(int(cfg["backfill_from_year"]), this_year + 1) if full else (this_year - 1, this_year)
    out: dict[str, object] = {}
    for report in {m["report"] for m in cfg["markets"].values()}:
        frames: dict[int, pd.DataFrame] = {}
        for y in years:
            try:
                df = download_year(report, y)
                if df is not None:
                    frames[y] = df
            except Exception as exc:
                log.exception("COT %s %s gagal", report, y)
                out[f"{report}:{y}"] = f"ERROR: {exc}"
        for key, mcfg in cfg["markets"].items():
            if mcfg["report"] != report:
                continue
            parts = [parse_market(df, key, mcfg) for df in frames.values()]
            parts = [p for p in parts if not p.empty]
            if not parts:
                out[key] = "tidak ada baris cocok (cek kode kontrak)"
                continue
            data = pd.concat(parts)
            name = parts[-1].attrs.get("market_name", "?")
            log.info("COT %s -> %s (%d baris)", key, name, len(data))
            out[key] = {"rows": upsert("cot_positions", data.to_dict("records")), "market": name}
    return out
