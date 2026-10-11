"""Proyeksi skenario dari beta yang sudah diestimasi. Murni (tanpa I/O)."""
from __future__ import annotations

import math
from typing import Any

Z80 = 1.2815515655446004  # kuantil 90% -> interval 80%

NOTES = [
    "Estimasi linier dari hubungan historis mingguan; bukan prediksi. Rentang hanya mencerminkan "
    "ketidakpastian estimasi beta, bukan noise harga (lihat noise_1w).",
    "Bila level skenario sudah tercermin di kurva futures/ekspektasi pasar, sisa repricing lebih kecil "
    "dari estimasi ini.",
]


def shock_x(kind: str, baseline: float, target: float | None = None, shock_pct: float | None = None) -> float:
    """Ukuran shock pada skala regresi: log-return (kind=log) atau selisih level (kind=diff)."""
    if kind == "log":
        if shock_pct is not None:
            if shock_pct <= -100:
                raise ValueError("shock_pct harus > -100")
            return math.log1p(shock_pct / 100.0)
        if target is None:
            raise ValueError("isi target atau shock_pct")
        if baseline <= 0 or target <= 0:
            raise ValueError("baseline dan target harus > 0")
        return math.log(target / baseline)
    if target is None:
        raise ValueError("driver ini memakai level: isi target")
    return float(target) - float(baseline)


def project(beta: float, se: float, x: float, target_kind: str) -> tuple[float, float, float]:
    def f(b: float) -> float:
        return math.expm1(b * x) * 100.0 if target_kind == "log" else b * x

    a, b = f(beta - Z80 * se), f(beta + Z80 * se)
    return f(beta), min(a, b), max(a, b)


def confidence_label(t: float, r2: float, flags: list[str]) -> str:
    unstable = any("tidak stabil" in f for f in flags)
    level = 2 if (abs(t) >= 3 and r2 >= 0.15) else (1 if abs(t) >= 2 else 0)
    if unstable:
        level = max(0, level - 1)
    return ["rendah", "sedang", "tinggi"][level]


def run_scenario(
    rows: list[dict],
    driver: str,
    driver_kind: str,
    baseline: float,
    kinds: dict[str, str],
    order: list[str],
    names: dict[str, str],
    channel_names: set[str],
    target: float | None = None,
    shock_pct: float | None = None,
    regime: str = "auto",
    regime_current: str | None = None,
    driver_stats: dict | None = None,
) -> dict[str, Any]:
    x = shock_x(driver_kind, baseline, target, shock_pct)
    desired = regime_current if regime == "auto" else regime
    desired = desired or "all"
    warnings: list[str] = []
    if regime == "auto" and regime_current is None:
        warnings.append("Rezim tidak terdeteksi; memakai beta seluruh sampel ('all').")

    by_target: dict[str, dict[str, dict]] = {}
    for r in rows:
        by_target.setdefault(r["target"], {})[r["regime"]] = r

    results = []
    for code in order:
        variants = by_target.get(code)
        if not variants:
            continue
        row = variants.get(desired)
        used = desired
        if row is None:
            row, used = variants.get("all"), "all"
            if row is None:
                continue
        tk = kinds[code]
        est, lo, hi = project(row["beta"], row["se"], x, tk)
        scale = 100.0 if tk == "log" else 1.0
        channels = None
        if row.get("decomposition"):
            channels = {k: v * x * scale for k, v in row["decomposition"].items()}
        flags = list(row.get("flags") or [])
        if row["regime"] != "all" and row["n_obs"] < 60:
            flags.append(f"sampel rezim '{row['regime']}' kecil (n={row['n_obs']})")
        results.append(
            {
                "code": code, "name": names.get(code, code),
                "role": "channel" if code in channel_names else "asset",
                "unit": "%" if tk == "log" else "pp",
                "est": est, "lo": lo, "hi": hi,
                "confidence": confidence_label(row["t_stat"], row["r2"], flags),
                "t": row["t_stat"], "r2": row["r2"], "n": row["n_obs"],
                "regime_used": used,
                "noise_1w": (row["noise_sigma"] or 0.0) * scale,
                "channels": channels, "flags": flags,
            }
        )

    stats = (driver_stats or {}).get(driver) or {}
    mx = stats.get("max_abs_weekly")
    if mx and abs(x) > mx:
        warnings.append(
            f"Shock ({x:+.3f}) lebih besar dari pergerakan mingguan terbesar dalam sampel ({mx:.3f}): "
            "ekstrapolasi, beta linier kurang andal."
        )
    return {
        "driver": driver, "baseline": baseline, "target": target, "shock_pct": shock_pct,
        "shock_x": x, "regime_requested": regime, "regime_current": regime_current, "regime_applied": desired,
        "results": results, "warnings": warnings, "notes": NOTES,
    }
