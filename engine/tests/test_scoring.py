import numpy as np
import pandas as pd
import pytest

from app.scoring.engine import score_asset, transform, z_to_score, zscore_last


def test_z_to_score_bands():
    assert z_to_score(0.4) == 0
    assert z_to_score(0.5) == 1
    assert z_to_score(1.2) == 1
    assert z_to_score(1.25) == 2
    assert z_to_score(-3) == -2
    assert z_to_score(float("nan")) is None
    assert z_to_score(None) is None


def test_transform_kinds():
    s = pd.Series([100.0, 110.0, 121.0], index=pd.date_range("2024-01-01", periods=3))
    assert transform(s, "level", 1).iloc[-1] == 121
    assert transform(s, "diff", 1).iloc[-1] == pytest.approx(11)
    assert transform(s, "pct", 1).iloc[-1] == pytest.approx(0.10)
    with pytest.raises(ValueError):
        transform(s, "bogus", 1)


def test_zscore_needs_enough_data():
    assert zscore_last(pd.Series(np.arange(10.0)), 750) == (None, None)


def _series(n=900, seed=0, step=0.02, start=2.0):
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(seed)
    return pd.Series(start + np.cumsum(rng.normal(0, step, n)), index=idx)


CFG = {
    "factors": [
        {"name": "real_yield", "source": "fred:DFII10", "transform": "diff", "window": 20, "direction": -1, "weight": 2.0},
        {"name": "usd", "source": "fred:DTWEXBGS", "transform": "pct", "window": 20, "direction": -1, "weight": 1.0},
    ]
}


def test_falling_real_yield_is_bullish_for_gold():
    ry = _series()
    ry.iloc[-20:] = ry.iloc[-21] - np.linspace(0.05, 0.8, 20)  # penurunan tajam 20 hari terakhir
    usd = _series(seed=5, step=0.002, start=100.0)
    data = {"fred:DFII10": ry, "fred:DTWEXBGS": usd}
    res = score_asset("XAUUSD", CFG, lambda k: data[k], asof=ry.index[-1])
    ry_f = next(f for f in res["factors"] if f["factor"] == "real_yield")
    assert ry_f["z"] < -1.25 and ry_f["score"] == 2.0      # z sangat negatif x arah -1 => +2
    assert res["bias"] == "bullish"
    assert res["total"] > 0.2
    assert res["coverage"] == 1.0
    assert 0 <= res["confidence"] <= 1


def test_stale_data_is_excluded_and_result_neutral():
    data = {"fred:DFII10": _series(), "fred:DTWEXBGS": _series(seed=2, start=100.0)}
    far = data["fred:DFII10"].index[-1] + pd.Timedelta(days=60)
    res = score_asset("XAUUSD", CFG, lambda k: data[k], asof=far)
    assert {f["status"] for f in res["factors"]} == {"stale"}
    assert res["bias"] == "neutral" and res["coverage"] == 0.0 and res["confidence"] == 0.0


def test_news_factor_direct_score_and_missing():
    cfg = {"factors": [{"name": "news", "source": "news", "direction": 1, "weight": 1.0}]}
    asof = pd.Timestamp("2025-06-02")
    bull = score_asset("XAUUSD", cfg, lambda k: None, lambda a, t: 1.5, asof)
    assert bull["factors"][0]["score"] == 1.5 and bull["bias"] == "bullish"
    none = score_asset("XAUUSD", cfg, lambda k: None, lambda a, t: None, asof)
    assert none["factors"][0]["status"] == "missing" and none["bias"] == "neutral"


def test_broken_loader_does_not_crash_asset():
    def loader(key):
        raise RuntimeError("db down")

    res = score_asset("XAUUSD", CFG, loader, asof=pd.Timestamp("2025-01-01"))
    assert {f["status"] for f in res["factors"]} == {"error"}
    assert res["bias"] == "neutral"


def test_no_lookahead_future_data_ignored():
    ry = _series()
    asof = ry.index[-100]
    data = {"fred:DFII10": ry, "fred:DTWEXBGS": _series(seed=3, start=100.0)}
    a = score_asset("XAUUSD", CFG, lambda k: data[k], asof=asof)
    mutated = {k: v.copy() for k, v in data.items()}
    mutated["fred:DFII10"].iloc[-99:] += 50  # ubah hanya data setelah asof
    b = score_asset("XAUUSD", CFG, lambda k: mutated[k], asof=asof)
    assert a["total"] == b["total"]
