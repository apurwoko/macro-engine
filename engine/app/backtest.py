"""Backtest skor bias: apakah skor historis punya nilai prediktif untuk arah harga ke depan?

Hanya faktor pasar/makro (tanpa `news`, karena riwayat berita tidak tersedia). Data point-in-time
lewat jeda publikasi di config/series.yaml. Keterbatasan yang harus dipahami:
- Nilai FRED yang direvisi (CPI, dsb.) tampil dalam versi akhir, bukan versi saat rilis.
- Langkah mingguan dengan horizon > 1 minggu menghasilkan sampel yang saling tumpang-tindih,
  sehingga jumlah observasi independen jauh lebih kecil dari n.
- Bobot di factors.yaml adalah tebakan awal; jangan di-tune berlebihan pada hasil ini (overfitting).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .config import assets_cfg, load_yaml
from .data.series import make_cached_loader
from .scoring.engine import score_asset


def run(asset: str, start: str = "2014-01-01", horizons_days: tuple[int, ...] = (7, 28)) -> dict:
    fcfg = load_yaml("factors.yaml")
    thr = float(fcfg.get("defaults", {}).get("threshold", 0.2))
    acfg = {"factors": [f for f in fcfg["assets"][asset]["factors"] if f["source"] != "news"]}
    loader = make_cached_loader(start=load_yaml("series.yaml")["history_start"], pit=True)
    px = loader(f"px:{assets_cfg()[asset]['px']}").dropna()
    if px.empty:
        raise RuntimeError("Harga aset belum ada. Jalankan: python -m app.cli ingest prices --full")

    rows = []
    for d in pd.date_range(start, px.index[-1], freq="W-FRI"):
        res = score_asset(asset, acfg, loader, None, d, thr)
        if res["coverage"] < 0.5:
            continue  # data terlalu sedikit pada tanggal itu
        p0 = px.asof(d)
        rec = {"date": d, "total": res["total"], "bias": res["bias"], "coverage": res["coverage"]}
        for h in horizons_days:
            end = d + pd.Timedelta(days=h)
            rec[f"fwd_{h}d"] = float(np.log(px.asof(end) / p0)) if end <= px.index[-1] else np.nan
        rows.append(rec)

    df = pd.DataFrame(rows)
    out: dict = {"asset": asset, "n_dates": len(df), "threshold": thr, "horizons": {}}
    for h in horizons_days:
        col = f"fwd_{h}d"
        d = df.dropna(subset=[col])
        if len(d) < 30:
            out["horizons"][f"{h}d"] = {"n": len(d), "note": "sampel < 30"}
            continue
        ic, p = spearmanr(d["total"], d[col])
        bull, bear = d[d["bias"] == "bullish"], d[d["bias"] == "bearish"]
        out["horizons"][f"{h}d"] = {
            "n": len(d),
            "spearman_ic": float(ic), "p_value": float(p),
            "base_rate_up": float((d[col] > 0).mean()),
            "bullish": {"n": len(bull), "hit_rate_up": float((bull[col] > 0).mean()) if len(bull) else None,
                        "mean_fwd_pct": float(bull[col].mean() * 100) if len(bull) else None},
            "bearish": {"n": len(bear), "hit_rate_down": float((bear[col] < 0).mean()) if len(bear) else None,
                        "mean_fwd_pct": float(bear[col].mean() * 100) if len(bear) else None},
        }
    out["frame"] = df
    return out
