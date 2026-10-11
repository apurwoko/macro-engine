"""Tes alat kalibrasi pada dunia sintetis dengan jawaban yang diketahui."""
import numpy as np
import pandas as pd
import pytest

from app import calibrate as C
from app.scoring.engine import score_asset

CFG = {"factors": [
    # A: prediktor sebenarnya, arah benar
    {"name": "fA", "source": "fred:A", "transform": "diff", "window": 20, "direction": 1, "weight": 1.0},
    # B: noise murni
    {"name": "fB", "source": "fred:B", "transform": "diff", "window": 20, "direction": 1, "weight": 1.0},
    # A_salah: sumber sama dengan A, arah SALAH (logika ekonomi keliru) -> tidak boleh membuat prior bagus
    {"name": "fA_salah", "source": "fred:A", "transform": "diff", "window": 20, "direction": -1, "weight": 1.0},
]}


def make_world(seed: int, signal: float, years: int = 16):
    """Harga bergerak mengikuti z-score kausal dari A (r[t+1] = signal*zA[t] + eps) bila signal > 0."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2008-01-01", periods=years * 261)
    n = len(idx)
    A = pd.Series(2 + np.cumsum(rng.normal(0, 0.03, n)), index=idx)
    B = pd.Series(5 + np.cumsum(rng.normal(0, 0.03, n)), index=idx)
    dA = A.diff(20)
    zA = ((dA - dA.expanding(60).mean()) / dA.expanding(60).std()).clip(-3, 3).fillna(0.0).to_numpy()
    eps = rng.normal(0, 0.008, n)
    ret = eps.copy()
    ret[1:] += signal * zA[:-1]
    px = pd.Series(100 * np.exp(np.cumsum(ret)), index=idx)
    data = {"fred:A": A, "fred:B": B}
    return (lambda k: data[k]), px


def run_world(seed, signal, **kw):
    loader, px = make_world(seed, signal)
    r = C.calibrate_asset("TEST", CFG, loader, px, start="2009-01-01", horizon=28, **kw)
    C.finalize_status([r])
    return r


def test_signal_world_is_detected_and_fit_beats_prior():
    r = run_world(seed=3, signal=0.0010)
    ev = r["eval"]
    # prior = fA + fB - fA = (hampir) noise -> tidak ada bukti; fit harus mematikan fA_salah dan mempertahankan fA
    assert abs(ev.loc["prior", "ic"]) < 0.10
    assert ev.loc["fit", "ic"] > 0.15 and ev.loc["fit", "p"] < 0.05
    assert ev.loc["fit", "ic"] - ev.loc["prior", "ic"] > C.MIN_IC_GAIN
    assert r["adopt_fit"] is True and r["recommendation"] == "PAKAI BOBOT FIT"
    w = r["final_weights"]
    assert w["fA"] > 3 * w["fA_salah"]            # faktor berarah salah dimatikan/diturunkan
    assert w["fA"] > 3 * w["fB"]                  # noise tidak diberi bobot besar
    assert (w >= 0).all()                         # data tidak boleh membalik arah ekonomi
    assert w.sum() == pytest.approx(3.0)          # skala bobot tetap = jumlah bobot awal


def test_noise_world_rarely_adopts_fit():
    adopted, ics = 0, []
    for seed in range(12):
        r = run_world(seed=100 + seed, signal=0.0)
        adopted += r["adopt_fit"]
        ics.append(r["ic_fit"])
    assert adopted <= 2, f"terlalu sering menerapkan bobot pada noise: {adopted}/12"
    assert abs(np.nanmean(ics)) < 0.08           # tanpa sinyal, IC OOS berpusat di sekitar 0


def test_training_never_touches_test_period_embargo():
    loader, px = make_world(1, 0.0008)
    p = C.build_panel("TEST", CFG, loader, px, "2009-01-01")
    y = p["y"][28]
    seen = {}
    orig = C.fit_weights

    def spy(S, yy, w0, lam=1.0):
        seen["last_train_date"] = S.index.max()
        return orig(S, yy, w0, lam)

    C.fit_weights = spy
    try:
        C.walk_forward(p["S"], y, p["w0"], horizon_days=28, train_min_years=3)
    finally:
        C.fit_weights = orig
    # fit terakhir untuk tahun uji Y: tanggal latih + 28 hari harus < 1 Jan Y
    last_year = p["S"].index.year.max()
    assert seen["last_train_date"] + pd.Timedelta(days=28) < pd.Timestamp(year=last_year, month=1, day=1)


def test_panel_future_data_does_not_change_past_scores():
    """Mengubah data setelah tanggal t tidak boleh mengubah skor pada t (tidak ada look-ahead)."""
    loader, px = make_world(5, 0.001)
    p1 = C.build_panel("TEST", CFG, loader, px, "2010-01-01")
    cut = pd.Timestamp("2018-06-29")
    data = {"fred:A": loader("fred:A").copy(), "fred:B": loader("fred:B").copy()}
    for s in data.values():
        s[s.index > cut] += 99.0
    p2 = C.build_panel("TEST", CFG, lambda k: data[k], px, "2010-01-01")
    before = p1["S"].index[p1["S"].index <= cut]
    pd.testing.assert_frame_equal(p1["S"].loc[before], p2["S"].loc[before])


def test_composite_matches_production_total():
    loader, px = make_world(2, 0.001)
    p = C.build_panel("TEST", CFG, loader, px, "2012-01-01")
    comp = C.composite(p["S"], p["w0"])
    pd.testing.assert_series_equal(comp, p["total"], check_names=False, atol=1e-12)
    # titik tunggal terhadap score_asset langsung
    d = p["S"].index[200]
    res = score_asset("TEST", CFG, loader, None, d, 0.2)
    assert comp.loc[d] == pytest.approx(res["total"])


def test_fit_weights_respects_sign_and_shrinks_with_lam():
    rng = np.random.default_rng(0)
    n = 600
    idx = pd.date_range("2010-01-01", periods=n, freq="W-FRI")
    S = pd.DataFrame({"good": rng.choice([-2, -1, 0, 1, 2], n), "bad": rng.choice([-2, -1, 0, 1, 2], n)}, index=idx).astype(float)
    y = pd.Series(0.3 * S["good"] - 0.3 * S["bad"] + rng.normal(0, 1, n), index=idx)   # 'bad' berhubungan negatif
    w0 = pd.Series({"good": 1.0, "bad": 1.0})
    free = C.fit_weights(S, y, w0, lam=0.01)
    tight = C.fit_weights(S, y, w0, lam=1000.0)
    assert free["bad"] < 0.05 and free["good"] > 1.8          # faktor berarah salah dimatikan, bukan dibalik
    assert tight["bad"] == pytest.approx(1.0, abs=0.1)        # shrinkage kuat -> kembali ke prior
    assert (free >= 0).all() and free.sum() == pytest.approx(2.0)


def test_fit_weights_returns_prior_on_too_little_data():
    S = pd.DataFrame({"a": [1.0, 0.0]}, index=pd.date_range("2020-01-03", periods=2, freq="W-FRI"))
    w0 = pd.Series({"a": 2.0})
    assert C.fit_weights(S, pd.Series([0.1, -0.1], index=S.index), w0).equals(w0)


def test_bh_qvalues_known_values():
    q = C.bh_qvalues([0.01, 0.04, 0.03, 0.20, float("nan")])
    # p terurut: .01 .03 .04 .20 -> q mentah: .04 .06 .0533 .20 -> monoton: .04 .0533 .0533 .20
    assert q[0] == pytest.approx(0.04) and q[2] == pytest.approx(0.05333, abs=1e-4)
    assert q[1] == pytest.approx(0.05333, abs=1e-4) and q[3] == pytest.approx(0.20)
    assert np.isnan(q[4])


def test_spearman_ic_effective_n_inflates_pvalue_for_overlap():
    rng = np.random.default_rng(1)
    x = pd.Series(rng.normal(size=400))
    y = 0.15 * x + pd.Series(rng.normal(size=400))
    _, p1, _ = C.spearman_ic(x, y, step_weeks=1)
    _, p4, _ = C.spearman_ic(x, y, step_weeks=4)
    assert p4 > p1                                   # sampel tumpang-tindih -> lebih konservatif
    assert np.isnan(C.spearman_ic(pd.Series([1.0] * 100), pd.Series(rng.normal(size=100)), 1)[0])


def test_suggested_yaml_breaks_aliases_and_only_changes_adopted():
    import yaml
    fake_w = pd.Series({"real_yield_10y_20d": 3.9, "usd_broad_20d": 0.5, "breakeven_5y_20d": 0.1, "us2y_20d": 0.1,
                        "vix_level": 0.0, "cot_gold_mm_net": 0.0})
    res = [{"asset": "XAUUSD", "adopt_fit": True, "final_weights": fake_w},
           {"asset": "US100", "adopt_fit": False, "final_weights": pd.Series(dtype=float)}]
    text = C.suggested_yaml(res)
    assert "&" not in text.split("\n", 2)[2] and "*us_equity" not in text      # tanpa anchor/alias
    cfg = yaml.safe_load(text)
    xau = {f["name"]: f["weight"] for f in cfg["assets"]["XAUUSD"]["factors"]}
    assert xau["real_yield_10y_20d"] == 3.9 and xau["vix_level"] == 0.0 and xau["news_tone"] == 0.75   # news tak disentuh
    orig = {f["name"]: f["weight"] for f in C.load_yaml("factors.yaml")["assets"]["US100"]["factors"]}
    assert {f["name"]: f["weight"] for f in cfg["assets"]["US100"]["factors"]} == orig               # tidak diadopsi -> tetap
    # US30 (berbagi daftar dengan US100 lewat alias YAML) tidak ikut berubah
    assert {f["name"]: f["weight"] for f in cfg["assets"]["US30"]["factors"]} == orig


def test_report_renders_without_error(tmp_path):
    r = run_world(seed=3, signal=0.001)
    md = C.render_markdown(r)
    assert "PAKAI BOBOT FIT" in md and "Out-of-sample" in md and "fA_salah" in md
    out = C.write_reports([r], tmp_path)
    assert (out / "TEST.md").exists() and (out / "summary.csv").exists() and (out / "suggested_factors.yaml").exists()
    assert (out / "panel_TEST.csv").exists()
