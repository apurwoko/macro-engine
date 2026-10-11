"""Kalibrasi bobot faktor secara walk-forward, dengan perlindungan terhadap overfitting.

Pertanyaan yang dijawab per aset:
  1. Apakah skor bias (bobot awal) punya nilai prediktif OUT-OF-SAMPLE untuk arah harga ke depan?
  2. Apakah bobot hasil fit mengalahkan bobot awal di luar sampel? Jika tidak, bobot awal dipertahankan.

Desain (tiap poin ada karena satu alasan statistik):
- Target = return maju dinormalisasi volatilitas (bukan return mentah) -> tidak didominasi periode volatil.
- Skor faktor memakai jalur yang SAMA dengan produksi (scoring.engine.score_asset, point-in-time).
- Fit bobot: NNLS (bobot >= 0) dengan penalti ridge ke bobot awal. Skor sudah memuat arah ekonomi
  (direction), jadi bobot >= 0 berarti data hanya boleh MEMATIKAN/menurunkan faktor, tidak membalik logikanya.
- Walk-forward: fit memakai data sebelum tahun uji, dengan embargo selama horizon agar jendela return maju data
  latih tidak menyentuh periode uji. Bobot dipakai pada tahun uji, lalu bergeser.
- Sampel mingguan dengan horizon 4 minggu saling tumpang-tindih 4x; p-value memakai n efektif = n / langkah.
- Banyak aset diuji sekaligus -> koreksi Benjamini-Hochberg (q-value) agar temuan kebetulan tidak lolos.
- Faktor `news` tidak dapat dibackteskan (riwayat berita tidak ada) dan dikecualikan; bobotnya tetap dari prior.
"""
from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy import stats
from scipy.optimize import nnls

from .config import assets_cfg, load_yaml, scored_assets
from .data.series import make_cached_loader
from .scoring.engine import score_asset

HORIZONS = (7, 28)

# Aturan keputusan (eksplisit agar bisa dikritik/diubah):
MIN_IC_GAIN = 0.02      # bobot fit harus menambah IC OOS minimal ini dibanding bobot awal
ALPHA = 0.10            # ambang p/q
PRIOR_IC = 0.05         # korelasi yang diasumsikan untuk komposit prior saat menetapkan skala target shrinkage


# ----------------------------------------------------------------------------- panel

def _weekly_vol(px: pd.Series) -> pd.Series:
    w = px.resample("W-FRI").last().dropna()
    return np.log(w).diff().rolling(52, min_periods=26).std()


def build_panel(asset: str, acfg: dict, loader, px: pd.Series, start: str,
                horizons: tuple[int, ...] = HORIZONS, threshold: float = 0.2) -> dict:
    """Panel mingguan: skor tiap faktor per tanggal + return maju (mentah & dinormalisasi vol)."""
    factors = [f for f in acfg["factors"] if f["source"] != "news"]
    names = [f["name"] for f in factors]
    cfg = {"factors": factors}
    px = px.dropna()
    px = px[px > 0]
    vol = _weekly_vol(px)
    last = px.index[-1]

    scores, totals, fwd, vols, mom = {}, {}, {}, {}, {}
    for d in pd.date_range(start, last, freq="W-FRI"):
        res = score_asset(asset, cfg, loader, None, d, threshold)
        scores[d] = {f["factor"]: f["score"] for f in res["factors"]}
        totals[d] = res["total"]
        p0 = px.asof(d)
        fwd[d] = {
            h: (math.log(px.asof(d + pd.Timedelta(days=h)) / p0) if d + pd.Timedelta(days=h) <= last else np.nan)
            for h in horizons
        }
        vols[d] = vol.asof(d)
        pm = px.asof(d - pd.Timedelta(days=28))
        mom[d] = math.log(p0 / pm) if (pm == pm and pm > 0) else np.nan   # pm == pm -> bukan NaN

    S = pd.DataFrame.from_dict(scores, orient="index")[names].astype(float)
    F = pd.DataFrame.from_dict(fwd, orient="index")
    v = pd.Series(vols)
    Y = pd.DataFrame({h: (F[h] / (v * math.sqrt(h / 7.0))).clip(-4, 4) for h in horizons})
    w0 = pd.Series({f["name"]: float(f.get("weight", 1.0)) for f in factors})
    return {"S": S, "fwd": F, "y": Y, "vol": v, "mom": pd.Series(mom), "total": pd.Series(totals),
            "w0": w0, "threshold": threshold, "horizons": horizons}


# ----------------------------------------------------------------------------- statistik

def composite(S: pd.DataFrame, w: pd.Series) -> pd.Series:
    """Rumus yang sama dengan produksi: sum(skor*bobot) / (2 * sum(bobot yang datanya ada))."""
    w = w.reindex(S.columns).fillna(0.0)
    num = (S.fillna(0.0) * w).sum(axis=1)
    den = (S.notna() * w).sum(axis=1) * 2.0
    return (num / den.where(den > 0)).fillna(0.0)


def spearman_ic(x: pd.Series, y: pd.Series, step_weeks: int) -> tuple[float, float, int]:
    """IC Spearman + p-value dua sisi dengan n efektif = n / langkah (koreksi sampel tumpang-tindih)."""
    d = pd.concat([x, y], axis=1).dropna()
    n = len(d)
    if n < 30 or d.iloc[:, 0].nunique() < 3:
        return float("nan"), float("nan"), n
    ic = float(stats.spearmanr(d.iloc[:, 0], d.iloc[:, 1])[0])
    if not np.isfinite(ic):
        return float("nan"), float("nan"), n
    n_eff = max(n / max(step_weeks, 1), 4.0)
    t = ic * math.sqrt((n_eff - 2) / max(1 - ic * ic, 1e-12))
    return ic, float(2 * stats.t.sf(abs(t), n_eff - 2)), n


def bh_qvalues(p: list[float]) -> list[float]:
    """Benjamini-Hochberg. NaN dipertahankan sebagai NaN."""
    arr = np.array(p, dtype=float)
    ok = np.isfinite(arr)
    q = np.full(len(arr), np.nan)
    if ok.sum() == 0:
        return q.tolist()
    pv = arr[ok]
    order = np.argsort(pv)
    ranked = pv[order] * len(pv) / (np.arange(len(pv)) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(len(pv))
    out[order] = np.clip(ranked, 0, 1)
    q[ok] = out
    return q.tolist()


def fit_weights(S: pd.DataFrame, y: pd.Series, w0: pd.Series, lam: float = 1.0) -> pd.Series:
    """NNLS dengan penalti ridge ke bobot awal.

    minimize ||y - X w||^2 + lam_eff * ||w - s*w0||^2,  w >= 0
    X = skor/2 (rentang -1..1, NaN -> 0).

    Skala target s ditetapkan SEBELUM melihat performa prior: s*w0 adalah komposit dengan korelasi
    PRIOR_IC (lemah, positif) terhadap y. Skala TIDAK boleh diturunkan dari seberapa baik prior memprediksi:
    bila prior tak berdaya prediksi, target akan menyusut ke nol dan penalti berhenti menarik ke prior
    (bobot lalu ditentukan data saja, persis yang ingin dicegah).

    lam_eff = lam * n * rata-rata varians kolom X. Untuk kolom ortogonal, hasil = rata-rata berbobot
    (data : prior = 1 : lam) dari bobot yang diimplikasikan data dan prior. lam=1 -> separuh jalan; lam besar -> prior.
    Hasil dinormalisasi agar jumlah bobot sama dengan bobot awal (skala tidak berubah).
    """
    cols = list(S.columns)
    d = pd.concat([S.fillna(0.0) / 2.0, y.rename("__y__")], axis=1).dropna(subset=["__y__"])
    if len(d) < 50:
        return w0.copy()
    A, b = d[cols].to_numpy(float), d["__y__"].to_numpy(float)
    p0 = w0.reindex(cols).to_numpy(float)
    comp0 = A @ p0
    sd0, sdy = float(np.std(comp0)), float(np.std(b))
    mv = float(np.mean(np.var(A, axis=0)))
    if mv <= 0 or sd0 <= 0 or sdy <= 0:
        return w0.copy()
    s = PRIOR_IC * sdy / sd0
    lam_eff = lam * len(b) * mv
    A2 = np.vstack([A, math.sqrt(lam_eff) * np.eye(len(cols))])
    b2 = np.concatenate([b, math.sqrt(lam_eff) * s * p0])
    w, _ = nnls(A2, b2)
    if w.sum() <= 0:
        return w0.copy()
    w = w * (p0.sum() / w.sum())
    return pd.Series(w, index=cols)


# ----------------------------------------------------------------------------- walk-forward

def walk_forward(S: pd.DataFrame, y: pd.Series, w0: pd.Series, horizon_days: int,
                 train_min_years: int = 3, lam: float = 1.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Kembalikan (oos, fits). oos: kolom prior/fit/equal/y per minggu uji; fits: bobot per tahun uji."""
    rows, fits = [], {}
    first = S.index[0].year + train_min_years
    for year in sorted(set(S.index.year)):
        if year < first:
            continue
        test = S.index[S.index.year == year]
        # embargo: baris latih harus selesai (tanggal + horizon) sebelum 1 Januari tahun uji
        cutoff = pd.Timestamp(year=year, month=1, day=1) - pd.Timedelta(days=horizon_days)
        tr = S.index < cutoff
        if int((tr & y.notna().to_numpy()).sum()) < 100:
            continue
        w = fit_weights(S[tr], y[tr], w0, lam)
        fits[year] = w
        St = S.loc[test]
        rows.append(pd.DataFrame({
            "prior": composite(St, w0), "fit": composite(St, w),
            "equal": composite(St, pd.Series(1.0, index=S.columns)), "y": y.loc[test],
        }))
    oos = pd.concat(rows) if rows else pd.DataFrame(columns=["prior", "fit", "equal", "y"])
    return oos, pd.DataFrame(fits)


def evaluate(oos: pd.DataFrame, step_weeks: int, thr: float) -> pd.DataFrame:
    out = []
    base = float((oos["y"] > 0).mean()) if len(oos) else float("nan")
    for c in ("prior", "fit", "equal"):
        ic, p, n = spearman_ic(oos[c], oos["y"], step_weeks)
        bull, bear = oos[oos[c] >= thr], oos[oos[c] <= -thr]
        out.append({
            "model": c, "n": n, "ic": ic, "p": p, "base_rate_up": base,
            "n_bull": len(bull), "hit_bull": float((bull["y"] > 0).mean()) if len(bull) else float("nan"),
            "n_bear": len(bear), "hit_bear": float((bear["y"] < 0).mean()) if len(bear) else float("nan"),
        })
    return pd.DataFrame(out).set_index("model")


def factor_table(S: pd.DataFrame, y: pd.Series, w0: pd.Series, fits: pd.DataFrame, final_w: pd.Series,
                 step_weeks: int) -> pd.DataFrame:
    """Diagnostik per faktor (IC penuh-sampel bersifat DESKRIPTIF, bukan bukti out-of-sample)."""
    rows = []
    valid = y.dropna().index
    thirds = np.array_split(np.arange(len(valid)), 3)
    for f in S.columns:
        ic, p, _ = spearman_ic(S.loc[valid, f], y.loc[valid], step_weeks)
        sub = [spearman_ic(S.loc[valid[ix], f], y.loc[valid[ix]], step_weeks)[0] for ix in thirds if len(ix) >= 30]
        sign_ok = sum(1 for v in sub if np.isfinite(v) and np.sign(v) == np.sign(ic)) if np.isfinite(ic) else 0
        zeroed = float((fits.loc[f] < 0.05 * w0[f]).mean()) if (len(fits.columns) and f in fits.index) else float("nan")
        rows.append({
            "faktor": f, "cakupan": float(S[f].notna().mean()), "ic_penuh": ic, "p": p,
            "ic_per_sepertiga": " / ".join(f"{v:+.2f}" if np.isfinite(v) else "n/a" for v in sub),
            "konsisten": f"{sign_ok}/{len(sub)}",
            "bobot_awal": float(w0[f]),
            "bobot_fit_rata2": float(fits.loc[f].mean()) if len(fits.columns) else float("nan"),
            "dimatikan_di_fit": zeroed,
            "bobot_fit_akhir": float(final_w[f]),
        })
    return pd.DataFrame(rows).set_index("faktor")


def calibrate_asset(asset: str, acfg: dict, loader, px: pd.Series, start: str = "2014-01-01",
                    horizon: int = 28, lam: float = 1.0, train_min_years: int = 3, threshold: float = 0.2) -> dict:
    horizons = tuple(sorted(set(HORIZONS) | {horizon}))
    panel = build_panel(asset, acfg, loader, px, start, horizons, threshold)
    S, y = panel["S"], panel["y"][horizon]
    step = max(1, math.ceil(horizon / 7))
    oos, fits = walk_forward(S, y, panel["w0"], horizon, train_min_years, lam)
    ev = evaluate(oos, step, threshold) if len(oos) else pd.DataFrame()
    final_w = fit_weights(S, y, panel["w0"], lam)
    ftab = factor_table(S, y, panel["w0"], fits, final_w, step)
    mom_ic, mom_p, _ = spearman_ic(panel["mom"].loc[oos.index] if len(oos) else panel["mom"], oos["y"] if len(oos) else y, step)
    per_year = {}
    if len(oos):
        for yr, g in oos.groupby(oos.index.year):
            per_year[int(yr)] = spearman_ic(g["prior"], g["y"], step)[0]
    res = {"asset": asset, "horizon": horizon, "lam": lam, "n_weeks": len(S), "panel": panel, "oos": oos, "fits": fits,
           "eval": ev, "factors": ftab, "final_weights": final_w, "momentum_ic": mom_ic, "per_year_ic_prior": per_year,
           "n_oos": len(oos)}
    res.update(decide(res))
    return res


def decide(res: dict) -> dict:
    """Aturan keputusan eksplisit (lihat konstanta di atas)."""
    ev = res["eval"]
    if ev.empty or not np.isfinite(ev.loc["prior", "ic"]):
        return {"status": "DATA TIDAK CUKUP", "adopt_fit": False, "p_prior": float("nan"), "p_fit": float("nan"),
                "ic_prior": float("nan"), "ic_fit": float("nan"), "ic_equal": float("nan")}
    ic_p, p_p = float(ev.loc["prior", "ic"]), float(ev.loc["prior", "p"])
    ic_f, p_f = float(ev.loc["fit", "ic"]), float(ev.loc["fit", "p"])
    adopt = bool(np.isfinite(ic_f) and ic_f - ic_p >= MIN_IC_GAIN and ic_f > 0 and p_f < ALPHA)
    return {"adopt_fit": adopt, "ic_prior": ic_p, "p_prior": p_p, "ic_fit": ic_f, "p_fit": p_f,
            "ic_equal": float(ev.loc["equal", "ic"]),
            "status": "KANDIDAT" if (ic_p > 0 and p_p < ALPHA) else "TIDAK ADA BUKTI"}


def finalize_status(results: list[dict]) -> None:
    """Tambahkan q-value lintas aset dan label status akhir."""
    qp = bh_qvalues([r["p_prior"] for r in results])
    qf = bh_qvalues([r["p_fit"] for r in results])
    for r, a, b in zip(results, qp, qf):
        r["q_prior"], r["q_fit"] = a, b
        if r["status"] == "KANDIDAT" and np.isfinite(a) and a < ALPHA:
            r["status"] = "TERKONFIRMASI"
        if r["adopt_fit"] and not (np.isfinite(b) and b < ALPHA):
            r["adopt_note"] = "p lolos tetapi q-value belum (kemungkinan kebetulan setelah koreksi multi-aset)"
        r["recommendation"] = (
            "PAKAI BOBOT FIT" if r["adopt_fit"] else
            "PERTAHANKAN BOBOT AWAL" if r["status"] in ("TERKONFIRMASI", "KANDIDAT") else
            "JANGAN ANDALKAN BIAS ASET INI" if r["status"] == "TIDAK ADA BUKTI" else "DATA TIDAK CUKUP")


# ----------------------------------------------------------------------------- laporan

def _f(v, fmt="{:+.3f}") -> str:
    return "—" if v is None or (isinstance(v, float) and not np.isfinite(v)) else fmt.format(v)


def md_table(df: pd.DataFrame, fmts: dict | None = None) -> str:
    fmts = fmts or {}
    cols = [df.index.name or ""] + list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for idx, row in df.iterrows():
        cells = [str(idx)]
        for c in df.columns:
            v = row[c]
            cells.append(_f(v, fmts.get(c, "{:+.3f}")) if isinstance(v, (float, np.floating)) else str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_markdown(r: dict) -> str:
    ev = r["eval"]
    out = [f"# Kalibrasi {r['asset']}  (horizon {r['horizon']} hari, {r['n_weeks']} minggu, OOS {r['n_oos']} minggu)", ""]
    out.append(f"**Keputusan: {r['recommendation']}**  (status sinyal: {r['status']})")
    if r.get("adopt_note"):
        out.append(f"\n> {r['adopt_note']}")
    out += ["", "## Out-of-sample (walk-forward)", ""]
    if ev.empty:
        out.append("Data tidak cukup untuk walk-forward.")
    else:
        out.append(md_table(ev[["n", "ic", "p", "base_rate_up", "n_bull", "hit_bull", "n_bear", "hit_bear"]],
                            {"n": "{:.0f}", "n_bull": "{:.0f}", "n_bear": "{:.0f}", "p": "{:.3f}",
                             "base_rate_up": "{:.2f}", "hit_bull": "{:.2f}", "hit_bear": "{:.2f}"}))
        out.append(f"\nq-value lintas aset: prior {_f(r.get('q_prior'), '{:.3f}')}, fit {_f(r.get('q_fit'), '{:.3f}')}. "
                   f"Pembanding momentum 4 minggu (tanpa fitur fundamental): IC {_f(r['momentum_ic'])}.")
        out.append("\nIC prior per tahun uji: " + ", ".join(f"{y}: {_f(v, '{:+.2f}')}" for y, v in r["per_year_ic_prior"].items()))
    out += ["", "## Faktor (IC penuh-sampel = deskriptif, bukan bukti OOS)", "",
            md_table(r["factors"], {"cakupan": "{:.2f}", "p": "{:.3f}", "bobot_awal": "{:.2f}",
                                    "bobot_fit_rata2": "{:.2f}", "dimatikan_di_fit": "{:.0%}", "bobot_fit_akhir": "{:.2f}"}),
            "", "Catatan: `bobot_fit_akhir` dihitung dari seluruh sampel (in-sample); keandalannya diukur oleh blok OOS di atas, "
                "bukan oleh tabel ini. Faktor `news` tidak ikut (tidak ada riwayat) dan tetap memakai bobot awal."]
    return "\n".join(out)


def suggested_yaml(results: list[dict]) -> str:
    base = json.loads(json.dumps(load_yaml("factors.yaml")))   # salinan dalam: putus alias YAML antar aset
    for r in results:
        if not r["adopt_fit"] or r["asset"] not in base["assets"]:
            continue
        for f in base["assets"][r["asset"]]["factors"]:
            if f["source"] != "news" and f["name"] in r["final_weights"].index:
                f["weight"] = round(float(r["final_weights"][f["name"]]), 2)

    class _D(yaml.SafeDumper):
        def ignore_aliases(self, data):  # jangan keluarkan &anchor/*alias
            return True

    header = ("# DIHASILKAN oleh `app.cli calibrate`. Bobot hanya berubah untuk aset dengan keputusan PAKAI BOBOT FIT.\n"
              "# Tinjau dulu, lalu salin manual ke config/factors.yaml. Tidak pernah menimpa file asli.\n")
    return header + yaml.dump(base, Dumper=_D, sort_keys=False, allow_unicode=True, width=140)


def write_reports(results: list[dict], outdir: str | Path) -> Path:
    out = Path(outdir) / f"calibration_{datetime.now(timezone.utc):%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in results:
        (out / f"{r['asset']}.md").write_text(render_markdown(r), encoding="utf-8")
        panel = r["panel"]
        pd.concat([panel["S"].add_prefix("s_"), panel["y"].add_prefix("y_"), panel["total"].rename("total")], axis=1
                  ).to_csv(out / f"panel_{r['asset']}.csv")
        rows.append({k: r.get(k) for k in ("asset", "n_weeks", "n_oos", "ic_prior", "p_prior", "q_prior", "ic_fit", "p_fit",
                                           "q_fit", "ic_equal", "momentum_ic", "status", "recommendation")})
    pd.DataFrame(rows).to_csv(out / "summary.csv", index=False)
    (out / "suggested_factors.yaml").write_text(suggested_yaml(results), encoding="utf-8")
    return out


def run(assets: list[str] | None = None, start: str = "2014-01-01", horizon: int = 28, lam: float = 1.0,
        out: str = "reports", train_min_years: int = 3) -> dict:
    fcfg = load_yaml("factors.yaml")
    thr = float(fcfg.get("defaults", {}).get("threshold", 0.2))
    loader = make_cached_loader(start=load_yaml("series.yaml")["history_start"], pit=True)
    results, skipped = [], {}
    for code in assets or scored_assets():
        px = loader(f"px:{assets_cfg()[code]['px']}")
        if px.empty:
            skipped[code] = "harga belum di-ingest"
            continue
        try:
            results.append(calibrate_asset(code, fcfg["assets"][code], loader, px, start, horizon, lam, train_min_years, thr))
        except Exception as exc:
            skipped[code] = f"{type(exc).__name__}: {exc}"
    finalize_status(results)
    path = write_reports(results, out) if results else None
    table = pd.DataFrame([{k: r.get(k) for k in ("asset", "n_oos", "ic_prior", "q_prior", "ic_fit", "q_fit", "momentum_ic", "recommendation")}
                          for r in results])
    return {"dir": str(path) if path else None, "summary": table, "skipped": skipped, "results": results}
