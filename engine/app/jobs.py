"""Registri job: dipakai bersama oleh scheduler, CLI, dan endpoint API (trigger manual)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from .alerts import digest, telegram
from .db import execute, to_py
from .ingest import cot, eia, fred, news, prices
from .llm import classify
from .repricing import service as repricing
from .scoring import run as scoring_run

log = logging.getLogger(__name__)


def _errors(result: dict) -> list[str]:
    return [k for k, v in result.items() if isinstance(v, str) and v.startswith("ERROR")]


def daily_pipeline() -> dict:
    """Ingest harga & makro -> skor bias -> ringkasan Telegram. Berurutan agar skor memakai data terbaru."""
    out: dict[str, Any] = {}
    for name, fn in (("fred", fred.run), ("prices", prices.run)):
        try:
            out[name] = {"errors": _errors(fn())}
        except Exception as exc:
            log.exception("daily_pipeline: %s gagal", name)
            out[name] = f"ERROR: {exc}"
    out["score"] = scoring_run.run_scores()
    out["digest"] = digest.send_daily()
    return out


def news_cycle() -> dict:
    return {"ingest": news.run(), "classify": classify.run()}


JOBS: dict[str, Callable[[], Any]] = {
    "ingest_fred": fred.run,
    "ingest_prices": prices.run,
    "ingest_cot": cot.run,
    "ingest_eia": eia.run,
    "ingest_news": news.run,
    "classify_news": classify.run,
    "score": scoring_run.run_scores,
    "betas": repricing.run_betas,
    "digest": digest.send_daily,
    "daily_pipeline": daily_pipeline,
    "news_cycle": news_cycle,
}


def run_job(name: str) -> dict:
    if name not in JOBS:
        raise KeyError(f"job tidak dikenal: {name}")
    started = datetime.now(timezone.utc).replace(tzinfo=None)
    jid = execute("INSERT INTO job_runs (job, started_at) VALUES (:j, :s)", j=name, s=started).lastrowid
    try:
        out = JOBS[name]()
        status, msg = "ok", json.dumps(to_py(out), ensure_ascii=False)[:2000]
    except Exception as exc:
        log.exception("Job %s gagal", name)
        status, msg = "error", str(exc)[:2000]
        telegram.send(f"JOB GAGAL: {name}\n{msg[:500]}", kind="job_error")
    execute(
        "UPDATE job_runs SET finished_at=:f, status=:s, message=:m WHERE id=:id",
        f=datetime.now(timezone.utc).replace(tzinfo=None), s=status, m=msg, id=jid,
    )
    return {"job": name, "status": status}
