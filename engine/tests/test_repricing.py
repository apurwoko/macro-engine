import math

import numpy as np
import pandas as pd
import pytest

from app.repricing import betas as B
from app.repricing.scenario import NOTES, confidence_label, project, run_scenario, shock_x


def make_frame(n=300, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-03", periods=n, freq="W-FRI")
    oil = rng.normal(0, 0.04, n)
    us2y = 0.5 * oil + rng.normal(0, 0.02, n)
    bei5y = 0.3 * oil + rng.normal(0, 0.02, n)
    dxy = -0.02 * oil + rng.normal(0, 0.004, n)
    xau = 0.2 * oil + 0.8 * bei5y - 0.5 * us2y + rng.normal(0, 0.01, n)
    spx = rng.normal(0, 0.02, n)
    return pd.DataFrame({"oil_wti": oil, "us2y": us2y, "bei5y": bei5y, "dxy": dxy, "XAUUSD": xau, "spx": spx}, index=idx)


def test_decomposition_identity_is_exact_in_sample():
    """beta total = efek langsung + sum(efek lewat kanal): identitas aljabar OLS, berlaku untuk n berapa pun."""
    df = make_frame(n=300)
    rows = B.fit_driver(df, "oil_wti", ["XAUUSD"], ["us2y", "bei5y", "dxy"], window_weeks=300)
    r = next(x for x in rows if x["target"] == "XAUUSD")
    d = r["decomposition"]
    assert sum(d.values()) == pytest.approx(r["beta"], abs=1e-9)
    assert abs(d["unexplained"]) < 1e-9
    # kanal sendiri ikut dilaporkan sebagai target tanpa dekomposisi
    ch = next(x for x in rows if x["target"] == "us2y")
    assert ch["decomposition"] is None


def test_true_parameters_recovered_with_large_sample():
    """Struktur sebenarnya: total = 0.2 + 0.8*0.3 - 0.5*0.5 = 0.19; langsung 0.2; via bei5y 0.24; via us2y -0.25.
    Dengan n=4000 galat sampling ~0.01, jadi toleransi 0.03 (~3 sigma) bermakna."""
    df = make_frame(n=4000, seed=7)
    rows = B.fit_driver(df, "oil_wti", ["XAUUSD"], ["us2y", "bei5y", "dxy"], window_weeks=4000)
    r = next(x for x in rows if x["target"] == "XAUUSD")
    assert r["beta"] == pytest.approx(0.19, abs=0.03)
    d = r["decomposition"]
    assert d["direct"] == pytest.approx(0.20, abs=0.03)
    assert d["bei5y"] == pytest.approx(0.24, abs=0.03)
    assert d["us2y"] == pytest.approx(-0.25, abs=0.03)
    assert abs(d["dxy"]) < 0.03
    ch = next(x for x in rows if x["target"] == "us2y")
    assert ch["beta"] == pytest.approx(0.5, abs=0.03)


def test_driver_not_regressed_on_itself():
    df = make_frame()
    rows = B.fit_driver(df, "oil_wti", ["oil_wti", "XAUUSD"], ["us2y"], window_weeks=300)
    assert "oil_wti" not in {r["target"] for r in rows}


def test_too_few_obs_returns_nothing():
    df = make_frame(n=300).tail(20)
    assert B.fit_driver(df, "oil_wti", ["XAUUSD"], ["us2y"], window_weeks=300) == []


def _pair_frame(beta_path, seed, n=300):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-03", periods=n, freq="W-FRI")
    x = rng.normal(0, 0.04, n)
    return pd.DataFrame({"d": x, "t": beta_path * x + rng.normal(0, 0.01, n)}, index=idx)


def test_instability_flag_detects_structural_break():
    path = np.r_[np.full(300 - 52, 0.5), np.full(52, -0.5)]     # beta berbalik tanda 52 minggu terakhir
    row = B.fit_driver(_pair_frame(path, seed=11), "d", ["t"], [], window_weeks=300)[0]
    assert any("tidak stabil" in f for f in row["flags"])


def test_instability_flag_rarely_fires_on_stable_relationship():
    flagged = 0
    for seed in range(40):
        row = B.fit_driver(_pair_frame(np.full(300, 0.5), seed), "d", ["t"], [], window_weeks=300)[0]
        flagged += any("tidak stabil" in f for f in row["flags"])
    assert flagged <= 5      # ~ tingkat alarm palsu nominal (<= ~12%); aturan lama menandai jauh lebih sering


def test_regime_label_uses_only_past_data():
    df = make_frame()
    lab1 = B.regime_labels(df, "oil_wti", "spx")
    df2 = df.copy()
    df2.iloc[-1] = df2.iloc[-1] * -25          # ubah hanya minggu terakhir
    lab2 = B.regime_labels(df2, "oil_wti", "spx")
    assert lab1.equals(lab2)                   # label minggu t memakai data sampai t-1


def test_regime_detection_signs():
    rng = np.random.default_rng(3)
    idx = pd.date_range("2021-01-01", periods=120, freq="W-FRI")
    oil = rng.normal(0, 0.04, 120)
    sup = pd.DataFrame({"oil_wti": oil, "spx": -oil + rng.normal(0, 0.005, 120)}, index=idx)
    dem = pd.DataFrame({"oil_wti": oil, "spx": oil + rng.normal(0, 0.005, 120)}, index=idx)
    assert B.current_regime(sup, "oil_wti", "spx") == "supply"
    assert B.current_regime(dem, "oil_wti", "spx") == "demand"


def test_reverse_fit_is_regression_of_driver_on_asset():
    df = make_frame()
    fit = B.reverse_fit(df, "oil_wti", "XAUUSD", 300)
    direct = B._ols(df["oil_wti"], df[["XAUUSD"]])[0].params["XAUUSD"]
    assert fit["beta"] == pytest.approx(direct)
    assert 0 <= fit["r2"] <= 1


# ---------------------------------------------------------------- skenario

def test_shock_x_log_and_diff():
    assert shock_x("log", 75, target=93) == pytest.approx(math.log(93 / 75))
    assert shock_x("log", 75, shock_pct=10) == pytest.approx(math.log(1.1))
    assert shock_x("diff", 4.2, target=5.0) == pytest.approx(0.8)
    with pytest.raises(ValueError):
        shock_x("log", 75)
    with pytest.raises(ValueError):
        shock_x("log", 0, target=10)
    with pytest.raises(ValueError):
        shock_x("diff", 4.2, shock_pct=5)


def test_project_log_and_interval_ordering():
    x = math.log(93 / 75)
    est, lo, hi = project(0.5, 0.1, x, "log")
    assert est == pytest.approx((1.24 ** 0.5 - 1) * 100, rel=1e-6)   # ~ +11.36%
    assert lo < est < hi
    # shock negatif: batas tetap terurut
    est2, lo2, hi2 = project(0.5, 0.1, -0.2, "log")
    assert lo2 < est2 < hi2
    est3, lo3, hi3 = project(0.4, 0.05, 0.8, "diff")
    assert est3 == pytest.approx(0.32) and lo3 < hi3


def test_confidence_labels():
    assert confidence_label(4.0, 0.3, []) == "tinggi"
    assert confidence_label(2.5, 0.3, []) == "sedang"
    assert confidence_label(1.0, 0.3, []) == "rendah"
    assert confidence_label(4.0, 0.3, ["beta tidak stabil (52 minggu vs seluruh sampel)"]) == "sedang"


def _rows():
    base = dict(driver="oil_wti", window_weeks=156, n_obs=150, noise_sigma=0.02, beta_recent=0.1, flags=[])
    return [
        {**base, "target": "XAUUSD", "regime": "all", "beta": 0.10, "se": 0.04, "r2": 0.10, "t_stat": 2.5,
         "decomposition": {"direct": 0.02, "us2y": -0.05, "bei5y": 0.13, "unexplained": 0.0}},
        {**base, "target": "XAUUSD", "regime": "supply", "beta": 0.25, "se": 0.05, "r2": 0.2, "t_stat": 5.0, "decomposition": None},
        {**base, "target": "us2y", "regime": "all", "beta": 0.5, "se": 0.1, "r2": 0.2, "t_stat": 5.0, "decomposition": None},
    ]


def test_run_scenario_regime_selection_and_fallback():
    kw = dict(driver="oil_wti", driver_kind="log", baseline=75.0, kinds={"XAUUSD": "log", "us2y": "diff"},
              order=["XAUUSD", "us2y"], names={"XAUUSD": "Emas", "us2y": "UST 2Y"}, channel_names={"us2y"}, target=93)
    sup = run_scenario(_rows(), regime="auto", regime_current="supply", **kw)
    xau = next(r for r in sup["results"] if r["code"] == "XAUUSD")
    assert xau["regime_used"] == "supply" and xau["unit"] == "%"
    ch = next(r for r in sup["results"] if r["code"] == "us2y")
    assert ch["role"] == "channel" and ch["unit"] == "pp" and ch["regime_used"] == "all"   # fallback ke 'all'

    allr = run_scenario(_rows(), regime="all", regime_current="supply", **kw)
    assert next(r for r in allr["results"] if r["code"] == "XAUUSD")["regime_used"] == "all"
    assert allr["notes"] == NOTES
    # kanal diskalakan ke satuan target (% untuk aset log)
    x = math.log(93 / 75)
    assert allr["results"][0]["channels"]["bei5y"] == pytest.approx(0.13 * x * 100)


def test_parse_json_handles_all_null_shapes():
    from app.db import parse_json
    assert parse_json(None) is None and parse_json(float("nan")) is None and parse_json("null") is None
    assert parse_json('{"a": 1}') == {"a": 1} and parse_json(b"[1, 2]") == [1, 2]
    assert parse_json({"x": 1}) == {"x": 1}


def test_run_scenario_extrapolation_and_missing_regime_warnings():
    kw = dict(driver="oil_wti", driver_kind="log", baseline=75.0, kinds={"XAUUSD": "log", "us2y": "diff"},
              order=["XAUUSD"], names={}, channel_names=set(), target=93)
    res = run_scenario(_rows(), regime="auto", regime_current=None,
                       driver_stats={"oil_wti": {"max_abs_weekly": 0.10}}, **kw)
    text = " ".join(res["warnings"])
    assert "ekstrapolasi" in text and "Rezim tidak terdeteksi" in text
    assert res["regime_applied"] == "all"
