from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from ..config import load_yaml, scored_assets
from ..data.series import make_cached_loader
from ..db import read_df, to_py, upsert
from .engine import score_asset


def make_news_loader(window_days: int = 3, min_signals: int = 2):
    """Rata-rata tone (dibobot confidence) dari headline_signals dalam N hari terakhir."""

    def _news(asset: str, asof: pd.Timestamp):
        df = read_df(
            "SELECT SUM(s.tone * s.confidence) / NULLIF(SUM(s.confidence), 0) AS tone, COUNT(*) AS n "
            "FROM headline_signals s JOIN headlines h ON h.id = s.headline_id "
            "WHERE s.asset_code=:a AND h.published_at > :f AND h.published_at <= :t",
            a=asset, f=asof - pd.Timedelta(days=window_days), t=asof + pd.Timedelta(days=1),
        )
        if df.empty or int(df["n"].iloc[0]) < min_signals or pd.isna(df["tone"].iloc[0]):
            return None
        return float(df["tone"].iloc[0])

    return _news


def run_scores(asof=None, assets: list[str] | None = None) -> dict:
    cfg = load_yaml("factors.yaml")
    threshold = float(cfg.get("defaults", {}).get("threshold", 0.2))
    loader = make_cached_loader(start=load_yaml("series.yaml")["history_start"], pit=True)
    news = make_news_loader()
    out = {}
    for code in assets or scored_assets():
        if code not in cfg["assets"]:
            continue
        res = score_asset(code, cfg["assets"][code], loader, news, asof, threshold)
        upsert(
            "factor_scores",
            [
                {"asset_code": code, "as_of": res["as_of"], "factor": r["factor"], "raw_value": r["raw"],
                 "zscore": r["z"], "score": r["score"], "weight": r["weight"], "status": r["status"]}
                for r in res["factors"]
            ],
        )
        upsert(
            "bias_scores",
            [{"asset_code": code, "as_of": res["as_of"], "total": res["total"], "bias": res["bias"],
              "confidence": res["confidence"], "coverage": res["coverage"], "details": to_py(res["factors"])}],
        )
        out[code] = {"bias": res["bias"], "total": round(res["total"], 3), "confidence": round(res["confidence"], 2)}
    return out
