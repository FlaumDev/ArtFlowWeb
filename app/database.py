from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import (
    AsyncConnectionPool,
    PoolClosed,
    PoolTimeout,
    TooManyRequests,
)

from app.config import Settings


logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 5
STATEMENT_TIMEOUT_MILLISECONDS = 5000
POOL_ACQUIRE_TIMEOUT_SECONDS = 1.5
POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 5

DatabasePool = AsyncConnectionPool


class DatabaseUnavailableError(RuntimeError):
    """Raised when the public database cannot be queried safely."""


async def open_database_pool(app_settings: Settings) -> DatabasePool | None:
    try:
        database_dsn = app_settings.database_dsn
    except (psycopg.Error, ValueError):
        logger.warning("PostgreSQL pool configuration is invalid")
        return None

    if database_dsn is None:
        logger.warning("PostgreSQL pool is disabled because configuration is missing")
        return None

    try:
        pool = AsyncConnectionPool(
            conninfo=database_dsn,
            min_size=POOL_MIN_SIZE,
            max_size=POOL_MAX_SIZE,
            timeout=POOL_ACQUIRE_TIMEOUT_SECONDS,
            reconnect_timeout=30,
            open=False,
            name="artflow-web",
            kwargs={
                "autocommit": True,
                "connect_timeout": CONNECT_TIMEOUT_SECONDS,
                "options": (
                    "-c default_transaction_read_only=on "
                    f"-c statement_timeout={STATEMENT_TIMEOUT_MILLISECONDS}"
                ),
                "row_factory": dict_row,
            },
        )
    except (psycopg.Error, TypeError, ValueError):
        logger.warning("PostgreSQL pool configuration is invalid")
        return None

    try:
        await pool.open(wait=False)
    except (psycopg.Error, OSError, TimeoutError, ValueError):
        logger.warning("PostgreSQL pool could not be started")
        await pool.close()
        return None

    return pool


async def close_database_pool(pool: DatabasePool | None) -> None:
    if pool is None or pool.closed:
        return

    try:
        await pool.close(timeout=5)
    except Exception:
        logger.warning("PostgreSQL pool could not be closed cleanly")


@asynccontextmanager
async def get_connection(
    pool: DatabasePool | None,
) -> AsyncIterator[AsyncConnection[DictRow]]:
    if pool is None or pool.closed:
        raise DatabaseUnavailableError("Database pool is unavailable")

    try:
        async with pool.connection(
            timeout=POOL_ACQUIRE_TIMEOUT_SECONDS
        ) as connection:
            yield connection
    except DatabaseUnavailableError:
        raise
    except (PoolTimeout, PoolClosed, TooManyRequests):
        logger.warning("PostgreSQL pool could not provide a connection in time")
        raise DatabaseUnavailableError("Database is unavailable") from None
    except (psycopg.Error, OSError, TimeoutError, ValueError):
        logger.warning("PostgreSQL read operation failed")
        raise DatabaseUnavailableError("Database is unavailable") from None


async def check_database_connection(pool: DatabasePool | None) -> None:
    async with get_connection(pool) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT 1")
            await cursor.fetchone()
