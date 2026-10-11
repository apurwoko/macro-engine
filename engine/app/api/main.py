"""API internal (dipanggil dashboard Laravel). Semua endpoint kecuali /health butuh header X-API-Key."""
from __future__ import annotations

import hmac
import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from ..alerts.digest import latest_bias
from ..config import assets_cfg, settings
from ..db import get_state, parse_json, read_df, to_py
from ..jobs import JOBS, run_job
from ..repricing import service as repricing
from ..repricing.variables import DRIVERS
from ..risk import event_risk_all

log = logging.getLogger(__name__)
Driver = Literal["oil_wti", "us10y", "dxy", "vix"]
Regime = Literal["auto", "all", "supply", "demand"]


def require_key(x_api_key: str = Header(default="")) -> None:
    expected = settings().api_key
    # fail-closed: tanpa API_KEY terkonfigurasi, semua permintaan ditolak
    if not expected or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="API key tidak valid")


app = FastAPI(title="Macro Engine", version="0.1.0")
auth = [Depends(require_key)]


@app.get("/health")
def health() -> dict:
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


@app.get("/meta", dependencies=auth)
def meta() -> dict:
    return to_py({
        "assets": [{"code": c, "name": a["name"], "class": a["class"]} for c, a in assets_cfg().items() if a.get("scored")],
        "drivers": {k: {"label": d["label"], "unit": d["unit"]} for k, d in DRIVERS.items()},
        "regime_current": get_state("regime_current", {}),
        "jobs": sorted(JOBS),
    })


@app.get("/bias", dependencies=auth)
def bias() -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    risks = event_risk_all(now)
    names = assets_cfg()
    items = []
    for r in latest_bias():
        code = r["asset_code"]
        items.append({**r, "name": names.get(code, {}).get("name", code), "risk": risks.get(code)})
    return to_py({"items": items})


@app.get("/bias/{asset}", dependencies=auth)
def bias_detail(asset: str) -> dict:
    df = read_df(
        "SELECT as_of, total, bias, confidence, coverage, details FROM bias_scores "
        "WHERE asset_code=:a ORDER BY as_of DESC LIMIT 1", a=asset.upper(),
    )
    if df.empty:
        raise HTTPException(404, "Belum ada skor untuk aset ini")
    r = df.iloc[0].to_dict()
    r["details"] = parse_json(r["details"])
    return to_py({"asset": asset.upper(), **r})


@app.get("/bias/{asset}/history", dependencies=auth)
def bias_history(asset: str, days: int = Query(180, ge=7, le=3650)) -> dict:
    df = read_df(
        "SELECT as_of, total, bias, confidence FROM bias_scores WHERE asset_code=:a "
        "AND as_of >= DATE_SUB(CURDATE(), INTERVAL :d DAY) ORDER BY as_of", a=asset.upper(), d=days,
    )
    return to_py({"asset": asset.upper(), "items": df.to_dict("records")})


class ScenarioIn(BaseModel):
    driver: Driver = "oil_wti"
    target: float | None = Field(None, description="Level target (mis. 93 untuk minyak USD/bbl)")
    shock_pct: float | None = Field(None, description="Alternatif: perubahan % (hanya driver berbasis harga)")
    baseline: float | None = Field(None, description="Override level awal; default = level terkini")
    regime: Regime = "auto"

    @model_validator(mode="after")
    def _need_one(self):
        if self.target is None and self.shock_pct is None:
            raise ValueError("isi target atau shock_pct")
        return self


class CompareIn(BaseModel):
    driver: Driver = "oil_wti"
    targets: list[float] = Field(..., min_length=1, max_length=6)
    regime: Regime = "auto"


class ReverseIn(BaseModel):
    driver: Driver = "oil_wti"
    asset: str
    move_pct: float


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@app.post("/scenario", dependencies=auth)
def scenario(body: ScenarioIn) -> dict:
    return _guard(repricing.scenario, body.driver, body.target, body.shock_pct, body.baseline, body.regime)


@app.post("/scenario/compare", dependencies=auth)
def scenario_compare(body: CompareIn) -> dict:
    return _guard(repricing.compare, body.driver, body.targets, body.regime)


@app.post("/scenario/reverse", dependencies=auth)
def scenario_reverse(body: ReverseIn) -> dict:
    return _guard(repricing.reverse, body.driver, body.asset.upper(), body.move_pct)


@app.get("/calendar/upcoming", dependencies=auth)
def calendar_upcoming(hours: int = Query(48, ge=1, le=336)) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    df = read_df(
        "SELECT event_time, currency, title, impact, forecast, previous, actual FROM calendar_events "
        "WHERE event_time BETWEEN :a AND DATE_ADD(:a, INTERVAL :h HOUR) ORDER BY event_time", a=now, h=hours,
    )
    return to_py({"items": df.to_dict("records")})


@app.post("/jobs/{name}", status_code=202, dependencies=auth)
def trigger_job(name: str, bg: BackgroundTasks) -> dict:
    if name not in JOBS:
        raise HTTPException(404, f"job tidak dikenal: {name}")
    bg.add_task(run_job, name)
    return {"started": name}


@app.get("/jobs", dependencies=auth)
def job_history(limit: int = Query(30, ge=1, le=200)) -> dict:
    df = read_df("SELECT id, job, started_at, finished_at, status, message FROM job_runs ORDER BY id DESC LIMIT :n", n=limit)
    return to_py({"items": df.to_dict("records")})
