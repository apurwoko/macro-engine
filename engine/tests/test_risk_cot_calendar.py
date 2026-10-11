from datetime import datetime

import pandas as pd
import pytest

from app.ingest.calendar import parse_csv
from app.ingest.cot import find_col, parse_market
from app.llm.classify import build_tool, sanitize
from app.risk import event_risk

NOW = datetime(2026, 11, 6, 13, 0)
GOLD = {"currencies": ["USD"], "event_keywords": []}
OIL = {"currencies": ["USD"], "event_keywords": ["Crude Oil Inventories", "OPEC"]}
EURUSD = {"currencies": ["EUR", "USD"]}


def ev(minutes, cur="USD", title="Nonfarm Payrolls", impact="high"):
    return {"event_time": datetime(2026, 11, 6, 13, 0) + pd.Timedelta(minutes=minutes),
            "currency": cur, "title": title, "impact": impact}


def test_blackout_before_and_after_window():
    assert event_risk(GOLD, NOW, [ev(+30)])["blackout"] is True      # 30 menit lagi
    assert event_risk(GOLD, NOW, [ev(+120)])["blackout"] is True     # tepat batas 120 menit
    assert event_risk(GOLD, NOW, [ev(+121)])["blackout"] is False
    assert event_risk(GOLD, NOW, [ev(-60)])["blackout"] is True      # 60 menit setelah rilis
    assert event_risk(GOLD, NOW, [ev(-61)])["blackout"] is False


def test_upcoming_window_and_relevance():
    r = event_risk(GOLD, NOW, [ev(+600), ev(+60 * 30), ev(+60, cur="EUR", title="ECB Rate")])
    assert [e["title"] for e in r["upcoming"]] == ["Nonfarm Payrolls"]   # +30 jam di luar 24 jam; EUR tidak relevan utk emas
    assert event_risk(EURUSD, NOW, [ev(+60, cur="EUR", title="ECB Rate")])["blackout"] is True


def test_non_high_event_only_counts_with_keyword():
    stock = ev(+30, title="Crude Oil Inventories", impact="medium")
    assert event_risk(OIL, NOW, [stock])["blackout"] is True
    assert event_risk(GOLD, NOW, [stock])["blackout"] is False
    assert event_risk(OIL, NOW, [ev(+30, title="Retail Sales", impact="medium")])["blackout"] is False


# ---------------------------------------------------------------- COT

def test_find_col_tolerates_header_variants():
    df = pd.DataFrame(columns=["Market and Exchange Names", "CFTC Contract Market Code"])
    assert find_col(df, "Market_and_Exchange_Names") == "Market and Exchange Names"
    assert find_col(df, "CFTC_Contract_Market_Code") == "CFTC Contract Market Code"
    with pytest.raises(KeyError):
        find_col(df, "tidak_ada")
    assert find_col(df, "tidak_ada", required=False) is None


def test_parse_market_keeps_leading_zero_codes_and_computes_net():
    raw = pd.DataFrame(
        {
            "Market_and_Exchange_Names": ["GOLD - COMMODITY EXCHANGE INC.", "GOLD - COMMODITY EXCHANGE INC.", "SILVER - COMEX"],
            "Report_Date_as_YYYY-MM-DD": ["2026-10-27", "2026-11-03", "2026-11-03"],
            "CFTC_Contract_Market_Code": ["088691", "088691", "084691"],
            "M_Money_Positions_Long_All": ["150000", "160000", "40000"],
            "M_Money_Positions_Short_All": ["30000", "25000", "10000"],
            "Open_Interest_All": ["500000", "510000", "150000"],
        }
    )
    out = parse_market(raw, "GOLD", {"report": "disagg", "code": "088691",
                                     "long": "M_Money_Positions_Long_All", "short": "M_Money_Positions_Short_All"})
    assert list(out["net_pos"]) == [120000, 135000]
    assert out.attrs["market_name"].startswith("GOLD")
    assert set(out["market_key"]) == {"GOLD"}
    miss = parse_market(raw, "X", {"report": "fin", "code": "999999",
                                   "long": "M_Money_Positions_Long_All", "short": "M_Money_Positions_Short_All"})
    assert miss.empty


# ---------------------------------------------------------------- kalender & LLM

def test_parse_calendar_csv(tmp_path):
    p = tmp_path / "cal.csv"
    p.write_text(
        "event_time_utc,currency,country,title,impact,forecast,previous,actual\n"
        "2026-11-06 13:30,usd,us,Nonfarm Payrolls,HIGH,180K,175K,\n"
    )
    rows = parse_csv(str(p))
    assert rows[0]["currency"] == "USD" and rows[0]["impact"] == "high" and rows[0]["actual"] is None
    assert rows[0]["event_time"] == datetime(2026, 11, 6, 13, 30)
    bad = tmp_path / "bad.csv"
    bad.write_text("event_time_utc,currency,title,impact\n2026-11-06 13:30,USD,X,critical\n")
    with pytest.raises(ValueError):
        parse_csv(str(bad))


def test_llm_output_is_sanitized():
    raw = {"items": [
        {"id": 1, "event_type": "central_bank", "summary": "x" * 500, "confidence": 1.7,
         "signals": [{"asset": "XAUUSD", "tone": 5}, {"asset": "BTCUSD", "tone": 1}, {"asset": "EURUSD", "tone": 0}]},
        {"id": 999, "event_type": "other", "summary": "id asing", "confidence": 0.5, "signals": []},
        {"id": 2, "event_type": "ngawur", "summary": "", "confidence": -1, "signals": []},
    ]}
    items = sanitize(raw, {1, 2})
    assert [i["id"] for i in items] == [1, 2]                       # id di luar batch dibuang
    assert items[0]["signals"] == [{"asset": "XAUUSD", "tone": 2}]  # tone dibatasi; aset asing & tone 0 dibuang
    assert items[0]["confidence"] == 1.0 and len(items[0]["summary"]) == 300
    assert items[1]["event_type"] == "other" and items[1]["confidence"] == 0.0


def test_tool_schema_lists_scored_assets():
    enum = build_tool()["input_schema"]["properties"]["items"]["items"]["properties"]["signals"]["items"]["properties"]["asset"]["enum"]
    assert "XAUUSD" in enum and "XLE" not in enum
