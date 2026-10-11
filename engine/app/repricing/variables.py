"""Definisi variabel & driver untuk engine repricing.

kind:
  log  -> perubahan = log-return (harga/indeks)
  diff -> perubahan = selisih level (yield dalam poin persen, VIX dalam poin)
"""
from __future__ import annotations

from ..config import assets_cfg

# Variabel non-aset: driver, kanal transmisi, dan pembanding rezim.
BASE_VARIABLES: dict[str, tuple[str, str]] = {
    "oil_wti": ("fred:DCOILWTICO", "log"),
    "us10y": ("fred:DGS10", "diff"),
    "dxy": ("fred:DTWEXBGS", "log"),
    "vix": ("fred:VIXCLS", "diff"),
    "us2y": ("fred:DGS2", "diff"),
    "bei5y": ("fred:T5YIE", "diff"),
    "real10y": ("fred:DFII10", "diff"),
    "spx": ("px:^GSPC", "log"),
}

# Driver yang bisa di-shock. `channels` = jalur transmisi antara yang diuraikan di output.
# `baseline_keys` = sumber harga/level terkini (dicoba berurutan).
DRIVERS: dict[str, dict] = {
    "oil_wti": {
        "label": "Minyak WTI", "unit": "USD/bbl", "var": "oil_wti",
        "channels": ["us2y", "bei5y", "dxy"],
        "baseline_keys": ["px:CL=F", "fred:DCOILWTICO"],
        "regime_pair": "spx",   # korelasi minyak-saham: negatif = supply shock, positif = demand shock
        "exclude": ["USOIL"],   # WTI futures = driver itu sendiri; hasilnya trivial
    },
    "us10y": {
        "label": "Yield UST 10Y", "unit": "%", "var": "us10y",
        "channels": ["dxy", "bei5y", "vix"],
        "baseline_keys": ["fred:DGS10"], "regime_pair": None,
    },
    "dxy": {
        "label": "Indeks dolar luas", "unit": "indeks", "var": "dxy",
        "channels": ["us2y", "vix"],
        "baseline_keys": ["fred:DTWEXBGS"], "regime_pair": None,
    },
    "vix": {
        "label": "VIX", "unit": "poin", "var": "vix",
        "channels": ["us2y", "dxy"],
        "baseline_keys": ["fred:VIXCLS"], "regime_pair": None,
    },
}


def variables() -> dict[str, tuple[str, str]]:
    """Gabungan variabel dasar + semua aset (kunci = kode aset, kind=log)."""
    v = dict(BASE_VARIABLES)
    for code, a in assets_cfg().items():
        v[code] = (f"px:{a['px']}", "log")
    return v


def kind_of(name: str) -> str:
    return variables()[name][1]
