from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

WIB = ZoneInfo("Asia/Jakarta")


@pytest.fixture()
def sched(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Jakarta")
    from app.config import settings
    settings.cache_clear()
    from app.scheduler import build
    yield build()
    settings.cache_clear()


def _trigger(sched, job_id):
    # Scheduler yang belum start menyimpan job di _pending_jobs sebagai tuple (job, jobstore, replace_existing)
    return next(p[0].trigger for p in sched._pending_jobs if p[0].id == job_id)


def test_expected_jobs_registered(sched):
    ids = {p[0].id for p in sched._pending_jobs}
    assert ids == {"daily_pipeline", "ingest_cot", "ingest_eia", "news_cycle", "betas"}


def test_daily_pipeline_skips_sunday_and_monday_morning(sched):
    t = _trigger(sched, "daily_pipeline")
    # Minggu 2026-10-11 05:35 WIB -> eksekusi berikutnya Selasa 06:30 (data Senin AS baru lengkap Selasa pagi WIB)
    now = datetime(2026, 10, 11, 5, 35, tzinfo=WIB)
    assert t.get_next_fire_time(None, now) == datetime(2026, 10, 13, 6, 30, tzinfo=WIB)
    # Jumat malam -> Sabtu 06:30 (mencakup penutupan Jumat AS)
    assert t.get_next_fire_time(None, datetime(2026, 10, 16, 23, 0, tzinfo=WIB)) == datetime(2026, 10, 17, 6, 30, tzinfo=WIB)


def test_cot_and_eia_and_betas_times(sched):
    now = datetime(2026, 10, 11, 5, 35, tzinfo=WIB)       # Minggu
    assert _trigger(sched, "ingest_cot").get_next_fire_time(None, now) == datetime(2026, 10, 17, 8, 0, tzinfo=WIB)   # Sabtu
    assert _trigger(sched, "ingest_eia").get_next_fire_time(None, now) == datetime(2026, 10, 14, 23, 30, tzinfo=WIB)  # Rabu
    assert _trigger(sched, "betas").get_next_fire_time(None, now) == datetime(2026, 10, 11, 7, 0, tzinfo=WIB)        # Minggu itu juga
