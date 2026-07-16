from __future__ import annotations

import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv
from psycopg.conninfo import make_conninfo


load_dotenv()

_TELEGRAM_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None

    value = value.strip()
    return value or None


def normalize_bot_username(value: str | None) -> str | None:
    if value is None:
        return None

    username = value.strip().lstrip("@").strip()
    if not username or not _TELEGRAM_USERNAME_PATTERN.fullmatch(username):
        return None

    return username


def _bot_username() -> str | None:
    return normalize_bot_username(_optional_env("BOT_USERNAME"))


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str | None
    db_host: str | None
    db_name: str | None
    db_user: str | None
    db_password: str | None
    db_port: str
    bot_username: str | None
    app_env: str
    base_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=_optional_env("DATABASE_URL"),
            db_host=_optional_env("DB_HOST"),
            db_name=_optional_env("DB_NAME"),
            db_user=_optional_env("DB_USER"),
            db_password=os.getenv("DB_PASSWORD") or None,
            db_port=_optional_env("DB_PORT") or "5432",
            bot_username=_bot_username(),
            app_env=_optional_env("APP_ENV") or "development",
            base_url=_optional_env("BASE_URL") or "http://127.0.0.1:8000",
        )

    @property
    def database_dsn(self) -> str | None:
        if self.database_url:
            return self.database_url

        if not all((self.db_host, self.db_name, self.db_user, self.db_password)):
            return None

        return make_conninfo(
            host=self.db_host,
            dbname=self.db_name,
            user=self.db_user,
            password=self.db_password,
            port=self.db_port,
        )

    @property
    def telegram_url(self) -> str | None:
        username = normalize_bot_username(self.bot_username)
        if username is None:
            return None

        return f"https://t.me/{username}"


settings = Settings.from_env()
