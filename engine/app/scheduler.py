"""Penjadwal (satu proses). Jam dalam zona waktu TZ (default Asia/Jakarta).

Jadwal mengikuti rilis data AS (dalam WIB):
- Tutup pasar AS Jumat 17:00 ET = Sabtu ~04:00 WIB  -> pipeline harian Selasa-Sabtu 06:30
- COT dirilis Jumat 15:30 ET = Sabtu ~02:30 WIB      -> ambil Sabtu 08:00
- Stok minyak EIA Rabu 10:30 ET = Rabu ~21:30 WIB    -> ambil Rabu 23:30
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import settings
from .jobs import run_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("scheduler")


def build() -> BlockingScheduler:
    tz = settings().tz
    sched = BlockingScheduler(timezone=tz)

    def add(name: str, **cron) -> None:
        sched.add_job(
            run_job, CronTrigger(timezone=tz, **cron), args=[name], id=name,
            max_instances=1, coalesce=True, misfire_grace_time=3600, replace_existing=True,
        )

    add("daily_pipeline", day_of_week="tue-sat", hour=6, minute=30)
    add("ingest_cot", day_of_week="sat", hour=8, minute=0)
    add("ingest_eia", day_of_week="wed", hour=23, minute=30)
    add("news_cycle", minute="*/30")
    add("betas", day_of_week="sun", hour=7, minute=0)
    return sched


def main() -> None:
    sched = build()
    for j in sched.get_jobs():
        log.info("terjadwal: %s", j.id)
    sched.start()


if __name__ == "__main__":
    main()
