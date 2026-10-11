"""Estimasi sensitivitas (beta) antar variabel. Murni: DataFrame masuk, hasil keluar.

Model dasar (mingguan):   target_t = a + beta * driver_t + e_t          (beta "total")
Dekomposisi kanal:        target_t = a + b0 * driver_t + sum_c b_c * kanal_c,t + e_t
                          kanal_c,t = a_c + delta_c * driver_t + u_t
Identitas OVB (exact in-sample, OLS):   beta = b0 + sum_c b_c * delta_c
=> total = efek langsung + sum(efek lewat tiap kanal). Dipakai untuk menjelaskan "kenapa".

Galat standar memakai HAC (Newey-West, 2 lag). Rezim ditentukan dari korelasi bergulir yang di-shift
satu minggu, sehingga label minggu t hanya memakai data sampai t-1 (tidak memilih sampel berdasarkan
hasil yang sedang diregresi).
"""
from __future__ import annotations

import math
from typing import Callable

import numpy as np
import pandas as pd
import statsmodels.api as sm

MIN_OBS = 30


def build_frame(
    loader: Callable[[str], pd.Series],
    spec: dict[str, tuple[str, str]],
    asof: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Frame perubahan mingguan (W-FRI). spec: nama -> (kunci_data, kind)."""
    cols = {}
    for name, (key, kind) in spec.items():
        s = loader(key)
        if s is None or s.empty:
            continue
        w = s.resample("W-FRI").last().ffill(limit=1)
        if kind == "log":
            w = w.where(w > 0)
            cols[name] = np.log(w).diff()
        elif kind == "diff":
            cols[name] = w.diff()
        else:
            raise ValueError(kind)
    df = pd.DataFrame(cols)
    if asof is not None:
        df = df[df.index <= pd.Timestamp(asof)]  # buang minggu yang belum selesai
    return df


def _ols(y: pd.Series, X: pd.DataFrame, hac_lags: int = 2):
    d = pd.concat([y.rename("__y__"), X], axis=1).dropna()
    if len(d) < MIN_OBS:
        return None
    Xc = sm.add_constant(d.drop(columns="__y__"), has_constant="add")
    mod = sm.OLS(d["__y__"], Xc).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lags})
    return mod, len(d)


def regime_labels(df: pd.DataFrame, driver: str, market: str = "spx", window: int = 26) -> pd.Series:
    """'supply' bila korelasi (driver, market) minggu-minggu sebelumnya negatif, 'demand' bila >= 0."""
    c = df[driver].rolling(window, min_periods=window // 2).corr(df[market])
    prev = c.shift(1)
    lab = pd.Series(np.where(prev < 0, "supply", "demand"), index=df.index, dtype=object)
    lab[prev.isna()] = None
    return lab


def current_regime(df: pd.DataFrame, driver: str, market: str = "spx", window: int = 26) -> str | None:
    c = df[driver].rolling(window, min_periods=window // 2).corr(df[market]).dropna()
    if c.empty:
        return None
    return "supply" if c.iloc[-1] < 0 else "demand"


def _flags(beta: float, se: float, r2: float, n: int,
           beta_recent: float | None, se_recent: float | None = None) -> list[str]:
    flags = []
    if n < 60:
        flags.append(f"sampel kecil (n={n})")
    t = beta / se if se > 0 else 0.0
    if abs(t) < 2:
        flags.append("tidak signifikan (|t|<2)")
    if r2 < 0.05:
        flags.append("R2 rendah: hubungan lemah")
    if beta_recent is not None and se_recent is not None:
        # Selisih diuji terhadap ketidakpastian KEDUA estimasi (estimasi 52 minggu jauh lebih berisik).
        # Sampel saling tumpang-tindih, jadi memakai sqrt(se^2 + se_recent^2) bersifat konservatif.
        if abs(beta_recent - beta) > 2 * math.sqrt(se ** 2 + se_recent ** 2):
            flags.append("beta tidak stabil (52 minggu vs seluruh sampel)")
    return flags


def fit_driver(
    df: pd.DataFrame,
    driver: str,
    targets: list[str],
    channels: list[str],
    window_weeks: int = 156,
    mask: pd.Series | None = None,
) -> list[dict]:
    """Beta total tiap target terhadap driver (+ beta kanal dan dekomposisi untuk target non-kanal)."""
    d = df.tail(window_weeks)
    if mask is not None:
        d = d[mask.reindex(d.index).fillna(False).astype(bool)]
    channels = [c for c in channels if c in d.columns and c != driver]

    delta: dict[str, float] = {}
    for c in channels:
        r = _ols(d[c], d[[driver]])
        if r:
            delta[c] = float(r[0].params[driver])

    rows = []
    for t in [x for x in targets if x != driver] + channels:
        if t not in d.columns:
            continue
        r = _ols(d[t], d[[driver]])
        if r is None:
            continue
        mod, n = r
        beta, se = float(mod.params[driver]), float(mod.bse[driver])
        rec = _ols(d[t].tail(52), d[[driver]].tail(52))
        beta_recent = float(rec[0].params[driver]) if rec else None
        se_recent = float(rec[0].bse[driver]) if rec else None
        decomposition = None
        if t not in channels and channels and all(c in delta for c in channels):
            full = _ols(d[t], d[[driver] + channels])
            if full:
                fm = full[0]
                decomposition = {"direct": float(fm.params[driver])}
                for c in channels:
                    decomposition[c] = float(fm.params[c]) * delta[c]
                decomposition["unexplained"] = beta - sum(decomposition.values())
        rows.append(
            {
                "driver": driver, "target": t, "window_weeks": window_weeks,
                "beta": beta, "se": se, "r2": float(mod.rsquared),
                "t_stat": beta / se if se > 0 else 0.0, "n_obs": n,
                "beta_recent": beta_recent, "noise_sigma": float(math.sqrt(mod.scale)),
                "decomposition": decomposition,
                "flags": _flags(beta, se, float(mod.rsquared), n, beta_recent, se_recent),
            }
        )
    return rows


def reverse_fit(df: pd.DataFrame, driver: str, asset: str, window_weeks: int = 156) -> dict | None:
    """E[driver | asset]: regresi driver pada aset (BUKAN 1/beta; itu salah bila R2 rendah)."""
    d = df.tail(window_weeks)
    r = _ols(d[driver], d[[asset]])
    if r is None:
        return None
    mod, n = r
    return {"beta": float(mod.params[asset]), "se": float(mod.bse[asset]), "r2": float(mod.rsquared), "n_obs": n,
            "noise_sigma": float(math.sqrt(mod.scale))}
