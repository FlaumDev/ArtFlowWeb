from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from dotenv import load_dotenv
from psycopg.conninfo import make_conninfo


load_dotenv()

_TELEGRAM_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_DEVELOPMENT_HOSTS = ("127.0.0.1", "localhost", "testserver")
_ALLOWED_APP_ENVS = ("development", "test", "production")


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


def _boolean_env(name: str, *, default: bool) -> bool:
    value = _optional_env(name)
    if value is None:
        return default

    normalized = value.casefold()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


def _allowed_hosts(value: str | None, *, is_production: bool) -> tuple[str, ...]:
    hosts: list[str] = []
    for item in (value or "").split(","):
        host = item.strip().lower()
        if not host or host in hosts:
            continue
        if is_production and host == "*":
            continue
        hosts.append(host)

    if not is_production:
        for host in _DEVELOPMENT_HOSTS:
            if host not in hosts:
                hosts.append(host)
    return tuple(hosts)


def _app_env(value: str | None) -> str:
    app_env = (value or "development").strip().casefold()
    if app_env not in _ALLOWED_APP_ENVS:
        allowed = ", ".join(_ALLOWED_APP_ENVS)
        raise ValueError(f"APP_ENV must be one of: {allowed}")
    return app_env


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str | None = field(repr=False)
    db_host: str | None
    db_name: str | None
    db_user: str | None
    db_password: str | None = field(repr=False)
    db_port: str
    bot_username: str | None
    app_env: str
    base_url: str
    allowed_hosts: tuple[str, ...]
    enable_docs: bool
    enable_security_headers: bool

    def __post_init__(self) -> None:
        if self.app_env not in _ALLOWED_APP_ENVS:
            allowed = ", ".join(_ALLOWED_APP_ENVS)
            raise ValueError(f"APP_ENV must be one of: {allowed}")

    @classmethod
    def from_env(cls) -> "Settings":
        app_env = _app_env(_optional_env("APP_ENV"))
        is_production = app_env == "production"
        return cls(
            database_url=_optional_env("DATABASE_URL"),
            db_host=_optional_env("DB_HOST"),
            db_name=_optional_env("DB_NAME"),
            db_user=_optional_env("DB_USER"),
            db_password=os.getenv("DB_PASSWORD") or None,
            db_port=_optional_env("DB_PORT") or "5432",
            bot_username=_bot_username(),
            app_env=app_env,
            base_url=_optional_env("BASE_URL") or "http://127.0.0.1:8000",
            allowed_hosts=_allowed_hosts(
                _optional_env("ALLOWED_HOSTS"),
                is_production=is_production,
            ),
            enable_docs=_boolean_env("ENABLE_DOCS", default=not is_production),
            enable_security_headers=_boolean_env(
                "ENABLE_SECURITY_HEADERS",
                default=True,
            ),
        )

    @property
    def is_production(self) -> bool:
        return self.app_env.casefold() == "production"

    @property
    def trusted_hosts(self) -> tuple[str, ...]:
        if self.allowed_hosts:
            return self.allowed_hosts
        # An empty production allow-list must fail closed instead of allowing all hosts.
        return ("invalid.local",)

    @property
    def public_https_base_url(self) -> str | None:
        if not self.is_production:
            return None

        try:
            parsed = urlsplit(self.base_url)
            parsed.port
        except ValueError:
            return None

        if (
            parsed.scheme.casefold() != "https"
            or not parsed.hostname
            or parsed.hostname.casefold() in {"localhost", "127.0.0.1", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            return None

        return self.base_url.rstrip("/")

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
