"""CLI:  python -m app.cli <perintah>

  ingest {fred,prices,cot,eia,news} [--full]
  classify | score | betas | digest
  calendar <file.csv>
  backfill                       # ingest penuh + betas + skor (jalankan sekali saat setup)
  backtest <ASET> [--start 2014-01-01]
  calibrate [ASET ...] [--horizon 28] [--lam 1.0]   # walk-forward + laporan di reports/
  scenario --driver oil_wti --target 93
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .db import to_py


def _p(obj) -> None:
    print(json.dumps(to_py(obj), indent=2, ensure_ascii=False, default=str))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ing = sub.add_parser("ingest")
    ing.add_argument("what", choices=["fred", "prices", "cot", "eia", "news"])
    ing.add_argument("--full", action="store_true")
    for c in ("classify", "score", "betas", "digest", "backfill"):
        sub.add_parser(c)
    cal = sub.add_parser("calendar")
    cal.add_argument("csv")
    bt = sub.add_parser("backtest")
    bt.add_argument("asset")
    bt.add_argument("--start", default="2014-01-01")
    cb = sub.add_parser("calibrate")
    cb.add_argument("assets", nargs="*", help="kode aset (default: semua yang dinilai)")
    cb.add_argument("--start", default="2014-01-01")
    cb.add_argument("--horizon", type=int, default=28, help="hari ke depan yang diprediksi")
    cb.add_argument("--lam", type=float, default=1.0, help="kekuatan shrinkage ke bobot awal (besar = patuh prior)")
    cb.add_argument("--train-years", type=int, default=3)
    cb.add_argument("--out", default="reports")
    sc = sub.add_parser("scenario")
    sc.add_argument("--driver", default="oil_wti")
    sc.add_argument("--target", type=float)
    sc.add_argument("--shock-pct", type=float)
    sc.add_argument("--regime", default="auto")
    a = ap.parse_args(argv)

    if a.cmd == "ingest":
        from .ingest import cot, eia, fred, news, prices
        mod = {"fred": fred, "prices": prices, "cot": cot, "eia": eia, "news": news}[a.what]
        _p(mod.run(full=a.full))
    elif a.cmd == "classify":
        from .llm import classify
        _p(classify.run())
    elif a.cmd == "score":
        from .scoring import run as scoring_run
        _p(scoring_run.run_scores())
    elif a.cmd == "betas":
        from .repricing import service
        _p(service.run_betas())
    elif a.cmd == "digest":
        from .alerts import digest
        print(digest.build_digest())
    elif a.cmd == "calendar":
        from .ingest import calendar
        print(f"{calendar.import_csv(a.csv)} event diimpor")
    elif a.cmd == "backfill":
        from .ingest import cot, eia, fred, prices
        from .repricing import service
        from .scoring import run as scoring_run
        for name, mod in (("fred", fred), ("prices", prices), ("cot", cot), ("eia", eia)):
            print(f"== ingest {name} (penuh)")
            try:
                _p(mod.run(full=True))
            except Exception as exc:  # mis. API key belum diisi: lanjut ke langkah berikutnya
                print(f"   dilewati: {exc}")
        print("== betas")
        _p(service.run_betas())
        print("== score")
        _p(scoring_run.run_scores())
    elif a.cmd == "backtest":
        from . import backtest
        res = backtest.run(a.asset.upper(), start=a.start)
        res.pop("frame")
        _p(res)
    elif a.cmd == "calibrate":
        from . import calibrate
        res = calibrate.run([x.upper() for x in a.assets] or None, a.start, a.horizon, a.lam, a.out, a.train_years)
        if len(res["summary"]):
            import pandas as pd
            with pd.option_context("display.width", 200, "display.float_format", "{:+.3f}".format):
                print(res["summary"].to_string(index=False))
        for k, v in res["skipped"].items():
            print(f"DILEWATI {k}: {v}")
        print(f"\nLaporan: {res['dir']}" if res["dir"] else "\nTidak ada aset yang bisa dikalibrasi.")
    elif a.cmd == "scenario":
        from .repricing import service
        _p(service.scenario(a.driver, target=a.target, shock_pct=a.shock_pct, regime=a.regime, log=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
