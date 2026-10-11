from __future__ import annotations

import json
import math
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sqlalchemy import JSON, MetaData, Table, create_engine, text
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.engine import Engine

from .config import settings


@lru_cache(maxsize=1)
def engine() -> Engine:
    # Semua sesi dipaksa UTC: data (obs_date, trade_date, dst.) disimpan & dibaca sebagai UTC,
    # terlepas dari time_zone default server/klien.
    return create_engine(
        settings().db_url(),
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"init_command": "SET time_zone='+00:00'"},
    )


_meta = MetaData()


@lru_cache(maxsize=None)
def _table(name: str) -> Table:
    return Table(name, _meta, autoload_with=engine())


# ----------------------------------------------------------------- konversi nilai

def to_py(x: Any) -> Any:
    """Ubah ke tipe aman-JSON: numpy -> python, NaN/inf -> None, tanggal -> ISO string."""
    if x is None:
        return None
    if isinstance(x, dict):
        return {str(k): to_py(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [to_py(v) for v in x]
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return f if math.isfinite(f) else None
    if isinstance(x, (pd.Timestamp, datetime, date)):
        return None if x is pd.NaT else x.isoformat()
    if isinstance(x, Decimal):
        return float(x)
    return x


def _db_val(v: Any) -> Any:
    """Nilai untuk kolom DB: pertahankan date/datetime, bersihkan NaN & tipe numpy."""
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dict, list)):
        return to_py(v)
    return v


def parse_json(v: Any) -> Any:
    """Kolom JSON dari PyMySQL datang sebagai str; kembalikan objek Python.

    NULL bisa tiba sebagai None, NaN (pandas >= 3 memakai NaN untuk teks kosong) atau string 'null':
    semuanya menjadi None.
    """
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, (bytes, bytearray)):
        v = v.decode("utf-8")
    if isinstance(v, str):
        return json.loads(v)
    return v


# ----------------------------------------------------------------- operasi

def upsert(table: str, rows: Iterable[dict], update_cols: list[str] | None = None, chunk: int = 1000) -> int:
    """INSERT ... ON DUPLICATE KEY UPDATE.

    update_cols=None  -> perbarui semua kolom non-PK
    update_cols=[]    -> INSERT IGNORE (abaikan duplikat)
    """
    data = [{k: _db_val(v) for k, v in r.items()} for r in rows]
    if not data:
        return 0
    t = _table(table)
    # Kolom bertipe JSON (MySQL) menerima dict/list langsung; bila ter-reflect sebagai teks
    # (mis. MariaDB) nilainya harus berupa string JSON.
    json_cols = {c.name for c in t.columns if isinstance(c.type, JSON)}
    for r in data:
        for k, v in r.items():
            if isinstance(v, (dict, list)) and k not in json_cols:
                r[k] = json.dumps(v, ensure_ascii=False)
    pk = set(t.primary_key.columns.keys())
    cols = list(data[0].keys())
    upd = [c for c in cols if c not in pk] if update_cols is None else update_cols
    total = 0
    with engine().begin() as conn:
        for i in range(0, len(data), chunk):
            part = data[i : i + chunk]
            stmt = mysql_insert(t).values(part)
            if upd:
                stmt = stmt.on_duplicate_key_update({c: stmt.inserted[c] for c in upd})
            else:
                stmt = stmt.prefix_with("IGNORE")
            conn.execute(stmt)
            total += len(part)
    return total


def read_df(sql: str, **params: Any) -> pd.DataFrame:
    with engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


def execute(sql: str, **params: Any):
    with engine().begin() as conn:
        return conn.execute(text(sql), params)


def scalar(sql: str, **params: Any) -> Any:
    with engine().connect() as conn:
        return conn.execute(text(sql), params).scalar()


def get_state(key: str, default: Any = None) -> Any:
    v = scalar("SELECT v FROM engine_state WHERE k=:k", k=key)
    return default if v is None else parse_json(v)


def set_state(key: str, value: Any) -> None:
    execute(
        "INSERT INTO engine_state (k, v) VALUES (:k, :v) ON DUPLICATE KEY UPDATE v=VALUES(v)",
        k=key,
        v=json.dumps(to_py(value)),
    )
