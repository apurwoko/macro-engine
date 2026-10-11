from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"


@dataclass(frozen=True)
class Settings:
    mysql_host: str
    mysql_port: int
    mysql_db: str
    mysql_user: str
    mysql_password: str
    fred_api_key: str
    eia_api_key: str
    anthropic_api_key: str
    anthropic_model: str
    telegram_token: str
    telegram_chat_id: str
    api_key: str
    tz: str
    llm_max_per_run: int

    def db_url(self) -> URL:
        # URL.create menangani karakter spesial pada password (tanpa perlu URL-encode manual).
        return URL.create(
            "mysql+pymysql",
            username=self.mysql_user,
            password=self.mysql_password,
            host=self.mysql_host,
            port=self.mysql_port,
            database=self.mysql_db,
            query={"charset": "utf8mb4"},
        )


@lru_cache(maxsize=1)
def settings() -> Settings:
    e = os.environ.get
    return Settings(
        mysql_host=e("MYSQL_HOST", "mysql"),
        mysql_port=int(e("MYSQL_PORT", "3306")),
        mysql_db=e("MYSQL_DATABASE", "macro"),
        mysql_user=e("MYSQL_USER", "macro"),
        mysql_password=e("MYSQL_PASSWORD", ""),
        fred_api_key=e("FRED_API_KEY", ""),
        eia_api_key=e("EIA_API_KEY", ""),
        anthropic_api_key=e("ANTHROPIC_API_KEY", ""),
        anthropic_model=e("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        telegram_token=e("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=e("TELEGRAM_CHAT_ID", ""),
        api_key=e("API_KEY", ""),
        tz=e("TZ", "Asia/Jakarta"),
        llm_max_per_run=int(e("LLM_MAX_PER_RUN", "40")),
    )


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def assets_cfg() -> dict:
    return load_yaml("assets.yaml")["assets"]


def scored_assets() -> list[str]:
    return [code for code, a in assets_cfg().items() if a.get("scored")]
