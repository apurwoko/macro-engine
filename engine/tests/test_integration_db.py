"""Tes integrasi end-to-end terhadap MySQL sungguhan dengan data SINTETIS.

Aktifkan:  MACRO_INTEGRATION_DB=1 python -m pytest tests/test_integration_db.py -q
PAKAI DATABASE KOSONG/SEKALI PAKAI. Tes ini menulis data palsu ke tabel produksi (macro_observations,
prices_daily, ...) dan akan SKIP bila tabel-tabel itu sudah berisi data. Jangan arahkan ke DB berjalanmu.
"""
import os

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("MACRO_INTEGRATION_DB") != "1", reason="set MACRO_INTEGRATION_DB=1")

N_DAYS = 2200


@pytest.fixture(scope="module")
def seeded():
    from app import db
    from app.config import assets_cfg, load_yaml

    for t in ("macro_observations", "prices_daily", "cot_positions", "bias_scores", "asset_betas"):
        if db.scalar(f"SELECT COUNT(*) FROM {t}"):
            pytest.skip(f"tabel {t} tidak kosong; tes integrasi hanya untuk DB sekali pakai")

    rng = np.random.default_rng(42)
    idx = pd.bdate_range(end=pd.Timestamp.now("UTC").tz_localize(None).normalize(), periods=N_DAYS)
    n = len(idx)

    def rw(start, step, drift=0.0):
        return start + np.cumsum(rng.normal(drift, step, n))

    # dunia sintetis: minyak & saham berkorelasi negatif (rezim supply) + emas bergantung yield riil
    oil_r = rng.normal(0, 0.018, n)
    spx_r = -0.5 * oil_r + rng.normal(0, 0.008, n)
    real = rw(1.0, 0.03)
    px_oil = 75 * np.exp(np.cumsum(oil_r))
    px_spx = 4000 * np.exp(np.cumsum(spx_r))
    px_gold = 1800 * np.exp(np.cumsum(-0.04 * np.diff(real, prepend=real[0]) + 0.1 * oil_r + rng.normal(0, 0.006, n)))

    fred = {
        "DGS2": rw(4, 0.03), "DGS10": rw(4, 0.03), "DFII10": real, "T5YIE": rw(2.2, 0.015) + 0.002 * np.cumsum(oil_r * 50),
        "T10YIE": rw(2.3, 0.01), "T10Y2Y": rw(0.2, 0.02), "DTWEXBGS": 120 * np.exp(np.cumsum(rng.normal(0, 0.002, n))),
        "VIXCLS": np.abs(rw(18, 0.6)) + 8, "BAMLH0A0HYM2": np.abs(rw(4, 0.05)) + 2, "DCOILWTICO": px_oil,
        "DCOILBRENTEU": px_oil * 1.05, "DFEDTARU": np.full(n, 4.5), "SP500": px_spx,
    }
    rows = [{"series_id": sid, "obs_date": d.date(), "value": float(v)} for sid, arr in fred.items() for d, v in zip(idx, arr)]
    # WALCL mingguan, EIA mingguan
    wk = idx[idx.dayofweek == 2]
    rows += [{"series_id": "WALCL", "obs_date": d.date(), "value": float(v)} for d, v in zip(wk, 8e6 + np.cumsum(rng.normal(0, 2e4, len(wk))))]
    for sid in load_yaml("series.yaml")["eia"]:
        rows += [{"series_id": f"EIA_{sid}", "obs_date": d.date(), "value": float(v)} for d, v in zip(wk, 4e5 + np.cumsum(rng.normal(0, 3e3, len(wk))))]
    # bulanan (tak dipakai faktor v1, hanya memastikan ingest bentuk umum)
    db.upsert("macro_observations", rows, update_cols=["value"])

    series_px = {a["px"]: None for a in assets_cfg().values()}
    series_px.update({s: None for s in load_yaml("assets.yaml")["extra_px"]})
    prow = []
    for sym in series_px:
        base = {"CL=F": px_oil, "^GSPC": px_spx, "GC=F": px_gold}.get(sym)
        if base is None:
            base = 100 * np.exp(np.cumsum(rng.normal(0, 0.006, n)) + 0.3 * np.cumsum(spx_r))
        for d, v in zip(idx, base):
            prow.append({"symbol": sym, "trade_date": d.date(), "open": float(v), "high": float(v), "low": float(v), "close": float(v), "volume": 1.0})
    db.upsert("prices_daily", prow)

    cot_idx = idx[idx.dayofweek == 1]
    crow = []
    for key, m in load_yaml("cot.yaml")["markets"].items():
        net = np.cumsum(rng.normal(0, 3000, len(cot_idx)))
        crow += [{"market_key": key, "report_date": d.date(), "report_type": m["report"], "contract_code": m["code"],
                  "long_pos": int(100000 + v), "short_pos": 100000, "net_pos": int(v), "open_interest": 500000}
                 for d, v in zip(cot_idx, net)]
    db.upsert("cot_positions", crow)
    yield
    # data sintetis dibiarkan; DB ini sekali pakai


def test_session_time_zone_is_utc():
    """connect_args.init_command (app/db.py) harus memaksa UTC terlepas dari time_zone server/klien."""
    from app import db

    assert db.scalar("SELECT @@session.time_zone") == "+00:00"


def test_upsert_is_idempotent_and_updates(seeded):
    from app import db
    q = "SELECT value FROM macro_observations WHERE series_id='TEST_UPSERT' AND obs_date='2020-01-02'"
    cnt = "SELECT COUNT(*) FROM macro_observations WHERE series_id='TEST_UPSERT'"
    try:
        db.upsert("macro_observations", [{"series_id": "TEST_UPSERT", "obs_date": "2020-01-02", "value": 1.0}], update_cols=["value"])
        db.upsert("macro_observations", [{"series_id": "TEST_UPSERT", "obs_date": "2020-01-02", "value": 1.23}], update_cols=["value"])
        assert db.scalar(cnt) == 1                       # duplikat tidak menambah baris
        assert db.scalar(q) == pytest.approx(1.23)       # tetapi nilainya diperbarui
        db.upsert("macro_observations", [{"series_id": "TEST_UPSERT", "obs_date": "2020-01-02", "value": 9.99}], update_cols=[])
        assert db.scalar(q) == pytest.approx(1.23)       # INSERT IGNORE tidak menimpa
        # NaN -> NULL ditolak kolom NOT NULL (value) alih-alih tertulis diam-diam sebagai nilai aneh
        with pytest.raises(Exception):
            db.upsert("macro_observations", [{"series_id": "TEST_UPSERT", "obs_date": "2020-01-03", "value": float("nan")}])
    finally:
        db.execute("DELETE FROM macro_observations WHERE series_id='TEST_UPSERT'")


def test_scores_all_assets(seeded):
    from app.config import scored_assets
    from app.scoring.run import run_scores

    out = run_scores()
    assert set(out) == set(scored_assets())
    from app import db
    n = db.scalar("SELECT COUNT(*) FROM bias_scores")
    assert n == len(scored_assets())
    details = db.parse_json(db.scalar("SELECT details FROM bias_scores WHERE asset_code='XAUUSD'"))
    assert isinstance(details, list) and details[0]["factor"]
    ok = db.scalar("SELECT COUNT(*) FROM factor_scores WHERE asset_code='XAUUSD' AND status='ok'")
    assert ok >= 5     # news & mungkin faktor lain missing; makro/cot/px harus ok


def test_betas_and_scenarios(seeded):
    from app import db
    from app.repricing import service

    res = service.run_betas()
    assert res["rows"] > 20
    assert db.scalar("SELECT COUNT(*) FROM asset_betas WHERE driver='oil_wti' AND regime='all'") > 10
    assert db.get_state("regime_current")["oil_wti"] in ("supply", "demand")

    r = service.scenario("oil_wti", target=93, log=True)
    codes = {x["code"] for x in r["results"]}
    assert {"XAUUSD", "US100", "USDCAD", "us2y"} <= codes
    assert "USOIL" not in codes and "UKOIL" in codes      # WTI = driver itu sendiri (trivial), Brent tetap tampil
    assert r["shock_x"] == pytest.approx(__import__("math").log(93 / r["baseline"]))
    assert db.scalar("SELECT COUNT(*) FROM scenario_runs") == 1

    c = service.compare("oil_wti", [85, 93, 110])
    xau = c["matrix"]["XAUUSD"]["est"]
    assert len(xau) == 3 and xau == sorted(xau) or xau == sorted(xau, reverse=True)   # monoton terhadap shock

    rev = service.reverse("oil_wti", "US100", -5)
    assert "implied" in rev and 0 <= rev["r2"] <= 1

    # driver level (yield): shock 4.2 -> 5.0 harus jalan dan mengembalikan satuan yang benar
    y = service.scenario("us10y", target=5.0, log=False)
    assert y["results"] and y["shock_x"] == pytest.approx(5.0 - y["baseline"])


def test_api_end_to_end(seeded, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("API_KEY", "kunci-tes")
    from app.config import settings
    settings.cache_clear()
    from app.api.main import app

    c = TestClient(app)
    assert c.get("/health").status_code == 200
    assert c.get("/bias").status_code == 401
    assert c.get("/bias", headers={"X-API-Key": "salah"}).status_code == 401
    h = {"X-API-Key": "kunci-tes"}
    b = c.get("/bias", headers=h)
    assert b.status_code == 200 and len(b.json()["items"]) == 12
    assert {"bias", "total", "risk", "name"} <= set(b.json()["items"][0])
    assert c.get("/bias/xauusd", headers=h).json()["details"]
    assert c.get("/bias/NOPE", headers=h).status_code == 404
    assert c.get("/bias/XAUUSD/history?days=30", headers=h).status_code == 200
    s = c.post("/scenario", json={"driver": "oil_wti", "target": 93}, headers=h)
    assert s.status_code == 200 and s.json()["results"]
    assert c.post("/scenario", json={"driver": "oil_wti"}, headers=h).status_code == 422
    assert c.post("/scenario", json={"driver": "oil_wti", "target": -5}, headers=h).status_code == 422
    assert c.post("/scenario/compare", json={"driver": "oil_wti", "targets": [85, 93, 110]}, headers=h).status_code == 200
    assert c.post("/scenario/reverse", json={"driver": "oil_wti", "asset": "us100", "move_pct": -5}, headers=h).status_code == 200
    assert c.get("/meta", headers=h).json()["drivers"]["oil_wti"]["unit"] == "USD/bbl"
    assert c.get("/calendar/upcoming", headers=h).status_code == 200
    assert c.post("/jobs/tidak_ada", headers=h).status_code == 404


def test_api_fails_closed_without_key(seeded, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("API_KEY", "")
    from app.config import settings
    settings.cache_clear()
    from app.api.main import app

    assert TestClient(app).get("/bias", headers={"X-API-Key": ""}).status_code == 401
    settings.cache_clear()


def test_calendar_risk_and_digest(seeded, tmp_path):
    from datetime import datetime, timedelta, timezone
    from app.alerts.digest import build_digest
    from app.ingest.calendar import import_csv

    soon = (datetime.now(timezone.utc) + timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M")
    p = tmp_path / "c.csv"
    p.write_text(f"event_time_utc,currency,country,title,impact,forecast,previous,actual\n{soon},USD,US,FOMC Rate Decision,high,,,\n")
    assert import_csv(str(p)) == 1
    assert import_csv(str(p)) == 1          # impor ulang idempoten (unique key)
    text = build_digest()
    assert "XAUUSD" in text and "JANGAN ENTRY: FOMC Rate Decision" in text


def test_calibrate_run_end_to_end(seeded, tmp_path):
    """calibrate.run membaca DB sungguhan, menghasilkan laporan, dan tidak menyentuh factors.yaml."""
    from app import calibrate
    from app.config import CONFIG_DIR

    before = (CONFIG_DIR / "factors.yaml").read_bytes()
    res = calibrate.run(["XAUUSD", "US100"], start="2018-01-01", horizon=28, out=str(tmp_path))
    assert not res["skipped"], res["skipped"]
    assert set(res["summary"]["asset"]) == {"XAUUSD", "US100"}
    out = tmp_path / sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("calibration_"))[-1]
    for f in ("summary.csv", "suggested_factors.yaml", "XAUUSD.md", "US100.md", "panel_XAUUSD.csv"):
        assert (out / f).exists(), f
    assert (CONFIG_DIR / "factors.yaml").read_bytes() == before
