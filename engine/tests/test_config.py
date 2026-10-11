"""Validasi konsistensi file konfigurasi (salah ketik di YAML = bug diam-diam)."""
from app.config import assets_cfg, load_yaml, scored_assets
from app.repricing.variables import DRIVERS, variables

VALID_TRANSFORMS = {"level", "diff", "pct"}


def test_every_scored_asset_has_factors_and_vice_versa():
    f = load_yaml("factors.yaml")["assets"]
    assert set(scored_assets()) == set(f), set(scored_assets()) ^ set(f)


def test_factor_fields_valid():
    cot_keys = set(load_yaml("cot.yaml")["markets"])
    series = load_yaml("series.yaml")
    fred, eia = set(series["fred"]), set(series["eia"])
    px = {a["px"] for a in assets_cfg().values()} | set(load_yaml("assets.yaml")["extra_px"])
    for code, cfg in load_yaml("factors.yaml")["assets"].items():
        names = [f["name"] for f in cfg["factors"]]
        assert len(names) == len(set(names)), f"nama faktor ganda di {code}"
        for f in cfg["factors"]:
            assert f["direction"] in (1, -1), (code, f["name"])
            assert f.get("weight", 1) > 0
            src = f["source"]
            if src == "news":
                continue
            assert f.get("transform") in VALID_TRANSFORMS, (code, f["name"])
            kind, _, ident = src.partition(":")
            assert {"fred": ident in fred, "eia": ident in eia, "px": ident in px,
                    "cot": ident in cot_keys}.get(kind, False), f"sumber tidak terdaftar: {src} ({code})"


def test_drivers_and_variables_resolve():
    v = variables()
    for name, d in DRIVERS.items():
        assert d["var"] in v, name
        for c in d["channels"]:
            assert c in v and c != d["var"], (name, c)
        if d["regime_pair"]:
            assert d["regime_pair"] in v
