"""Lapisan DB untuk engine repricing: estimasi beta (job mingguan) dan eksekusi skenario."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pandas as pd

from ..config import assets_cfg, load_yaml
from ..data import series
from ..db import execute, get_state, parse_json, read_df, set_state, to_py, upsert
from . import betas as B
from .scenario import run_scenario
from .variables import DRIVERS, kind_of, variables

WINDOW_WEEKS = 156
MIN_REGIME_OBS = 40


def _frame(names: list[str], asof=None) -> pd.DataFrame:
    spec = {n: variables()[n] for n in names}
    loader = series.make_cached_loader(start=load_yaml("series.yaml")["history_start"], pit=False)
    asof = asof or pd.Timestamp(datetime.now(timezone.utc).date())
    return B.build_frame(loader, spec, asof=asof)


def run_betas(window_weeks: int = WINDOW_WEEKS, asof=None) -> dict:
    """Hitung ulang beta semua driver x target x rezim, simpan ke asset_betas."""
    asset_codes = list(assets_cfg().keys())
    need = set(asset_codes) | {"spx"}
    for d in DRIVERS.values():
        need |= {d["var"], *d["channels"]}
    df = _frame(sorted(need), asof)

    rows, state_stats, state_regime = [], {}, {}
    for name, d in DRIVERS.items():
        drv = d["var"]
        if drv not in df.columns:
            continue
        pair = d.get("regime_pair")
        state_stats[name] = {"max_abs_weekly": float(df[drv].abs().max()), "as_of": str(df.index[-1].date())}

        regimes: dict[str, pd.Series | None] = {"all": None}
        if pair and pair in df.columns:
            lab = B.regime_labels(df, drv, pair)
            for r in ("supply", "demand"):
                m = (lab == r)
                if int(m.tail(window_weeks).sum()) >= MIN_REGIME_OBS:
                    regimes[r] = m
            state_regime[name] = B.current_regime(df, drv, pair)

        targets = [a for a in asset_codes if a not in d.get("exclude", [])]
        for reg, mask in regimes.items():
            for r in B.fit_driver(df, drv, targets, d["channels"], window_weeks, mask):
                r["driver"] = name          # simpan nama driver (kunci API), bukan nama variabel
                r["regime"] = reg
                rows.append(r)

    n = upsert("asset_betas", [{**r, "decomposition": r["decomposition"], "flags": r["flags"]} for r in rows])
    set_state("driver_stats", state_stats)
    set_state("regime_current", state_regime)
    return {"rows": n, "regimes": state_regime, "as_of": str(df.index[-1].date())}


def _load_rows(driver: str, window_weeks: int = WINDOW_WEEKS) -> list[dict]:
    df = read_df("SELECT * FROM asset_betas WHERE driver=:d AND window_weeks=:w", d=driver, w=window_weeks)
    rows = df.to_dict("records")
    for r in rows:
        r["decomposition"] = parse_json(r.get("decomposition"))
        r["flags"] = parse_json(r.get("flags")) or []
    return rows


def baseline_for(driver: str) -> tuple[float, str, str]:
    """Level terkini driver. Mengembalikan (nilai, kunci_sumber, tanggal)."""
    start = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    for key in DRIVERS[driver]["baseline_keys"]:
        s = series.load(key, start=start, pit=False)
        if len(s):
            return float(s.iloc[-1]), key, str(s.index[-1].date())
    raise RuntimeError(f"Tidak ada data baseline untuk driver '{driver}'. Jalankan ingest dulu.")


def scenario(driver: str, target: float | None = None, shock_pct: float | None = None,
             baseline: float | None = None, regime: str = "auto", log: bool = True) -> dict:
    if driver not in DRIVERS:
        raise ValueError(f"driver tidak dikenal: {driver}")
    rows = _load_rows(driver)
    if not rows:
        raise RuntimeError("Beta belum dihitung. Jalankan: python -m app.cli betas")
    src = None
    if baseline is None:
        baseline, key, day = baseline_for(driver)
        src = {"key": key, "date": day}
    d = DRIVERS[driver]
    names = {c: a["name"] for c, a in assets_cfg().items()}
    names.update({"us2y": "Yield UST 2Y (kanal)", "bei5y": "Breakeven 5Y (kanal)", "dxy": "Indeks dolar (kanal)",
                  "vix": "VIX (kanal)", "us10y": "Yield UST 10Y (kanal)", "real10y": "Yield riil 10Y (kanal)"})
    kinds = {n: kind_of(n) for n in names}
    channel_names = set(d["channels"])
    order = [c for c in assets_cfg() if c not in d.get("exclude", [])] + list(d["channels"])
    res = run_scenario(
        rows, driver, kind_of(d["var"]), baseline, kinds, order, names, channel_names,
        target=target, shock_pct=shock_pct, regime=regime,
        regime_current=(get_state("regime_current", {}) or {}).get(driver),
        driver_stats=get_state("driver_stats", {}),
    )
    res["driver_label"], res["unit"], res["baseline_source"] = d["label"], d["unit"], src
    res = to_py(res)
    if log:
        execute(
            "INSERT INTO scenario_runs (driver, baseline, target, shock, regime, result) "
            "VALUES (:d, :b, :t, :x, :r, :res)",
            d=driver, b=baseline, t=target, x=res["shock_x"], r=res["regime_applied"], res=json.dumps(res),
        )
    return res


def compare(driver: str, targets: list[float], regime: str = "auto") -> dict:
    runs = [scenario(driver, target=t, regime=regime, log=False) for t in targets]
    matrix: dict[str, dict] = {}
    for run in runs:
        for r in run["results"]:
            m = matrix.setdefault(r["code"], {"name": r["name"], "unit": r["unit"], "role": r["role"], "est": [], "conf": []})
            m["est"].append(r["est"])
            m["conf"].append(r["confidence"])
    return {"driver": driver, "targets": targets, "baseline": runs[0]["baseline"] if runs else None,
            "regime_applied": runs[0]["regime_applied"] if runs else None, "matrix": matrix,
            "warnings": sorted({w for r in runs for w in r["warnings"]})}


def reverse(driver: str, asset: str, move_pct: float, window_weeks: int = WINDOW_WEEKS) -> dict:
    """'Jika <asset> bergerak X%, berapa gerak driver yang konsisten secara historis?'"""
    d = DRIVERS[driver]
    if asset not in variables():
        raise ValueError(f"aset tidak dikenal: {asset}")
    if kind_of(asset) != "log":
        raise ValueError("reverse hanya untuk aset berbasis harga")
    df = _frame([d["var"], asset])
    fit = B.reverse_fit(df, d["var"], asset, window_weeks)
    if fit is None:
        raise RuntimeError("Data tidak cukup untuk regresi balik.")
    y = math.log1p(move_pct / 100.0)
    implied = fit["beta"] * y
    dk = kind_of(d["var"])
    est = math.expm1(implied) * 100.0 if dk == "log" else implied
    warn = []
    if fit["r2"] < 0.10:
        warn.append(f"R2={fit['r2']:.2f}: hubungan lemah, implikasi ini sangat tidak pasti.")
    return to_py({"driver": driver, "asset": asset, "asset_move_pct": move_pct,
                  "implied": est, "unit": "%" if dk == "log" else "pp",
                  "r2": fit["r2"], "n": fit["n_obs"], "noise_1w": fit["noise_sigma"] * (100.0 if dk == "log" else 1.0),
                  "warnings": warn})
