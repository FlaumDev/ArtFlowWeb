from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from datetime import date, datetime

import pytest

from app.config import settings
from app.database import (
    DatabaseUnavailableError,
    check_database_connection,
    close_database_pool,
    get_connection,
    open_database_pool,
)
from app.repositories import competitions as competitions_repository
from app.repositories import faq as faq_repository


pytestmark = pytest.mark.integration


async def with_pool(database_url, callback):
    app_settings = replace(
        settings,
        database_url=database_url,
        db_host=None,
        db_name=None,
        db_user=None,
        db_password=None,
        app_env="test",
    )
    pool = await open_database_pool(app_settings)
    assert pool is not None
    try:
        return await callback(pool)
    finally:
        await close_database_pool(pool)


def test_pool_opens_and_answers_healthcheck(integration_database_url):
    async def check(pool):
        await check_database_connection(pool)
        assert not pool.closed

    asyncio.run(with_pool(integration_database_url, check))


def test_published_competitions_and_detail(integration_database_url):
    async def load(pool):
        rows = await competitions_repository.get_published_competitions(
            pool=pool
        )
        detail = await competitions_repository.get_published_competition_by_id(
            1,
            pool=pool,
        )
        hidden = await competitions_repository.get_published_competition_by_id(
            2,
            pool=pool,
        )
        return rows, detail, hidden

    rows, detail, hidden = asyncio.run(
        with_pool(integration_database_url, load)
    )
    assert [row["id"] for row in rows] == [1]
    assert detail is not None and detail["id"] == 1
    assert hidden is None
    assert isinstance(detail["event_date"], date)
    assert isinstance(detail["application_deadline"], date)
    assert isinstance(detail["updated_at"], datetime)


def test_faq_and_timestamp_conversion(integration_database_url):
    async def load(pool):
        return await faq_repository.get_all_faq(pool=pool)

    rows = asyncio.run(with_pool(integration_database_url, load))
    assert [row["id"] for row in rows] == [1]
    assert isinstance(rows[0]["create_at"], datetime)


def test_pool_enforces_read_only_and_statement_timeout(
    integration_database_url,
):
    async def inspect(pool):
        async with get_connection(pool) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SHOW default_transaction_read_only")
                read_only_row = await cursor.fetchone()
                await cursor.execute("SHOW statement_timeout")
                statement_timeout_row = await cursor.fetchone()
        read_only = next(iter(read_only_row.values()))
        statement_timeout = next(iter(statement_timeout_row.values()))
        return read_only, statement_timeout

    read_only, statement_timeout = asyncio.run(
        with_pool(integration_database_url, inspect)
    )
    assert read_only == "on"
    assert statement_timeout in {"5s", "5000ms"}


def test_unavailable_database_is_controlled():
    unavailable_url = (
        "postgresql://artflow_test:integration-only-password@"
        "127.0.0.1:1/artflow_test"
    )

    async def check():
        app_settings = replace(
            settings,
            database_url=unavailable_url,
            db_host=None,
            db_name=None,
            db_user=None,
            db_password=None,
            app_env="test",
        )
        pool = await open_database_pool(app_settings)
        try:
            with pytest.raises(DatabaseUnavailableError):
                await check_database_connection(pool)
        finally:
            await close_database_pool(pool)

    asyncio.run(check())


def test_repository_sql_contains_no_write_statements():
    queries = [
        value
        for module in (competitions_repository, faq_repository)
        for name, value in vars(module).items()
        if name.endswith("_SQL") and isinstance(value, str)
    ]
    forbidden = {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"}
    assert queries
    for query in queries:
        assert not forbidden.intersection(
            re.findall(r"[A-Z_]+", query.upper())
        )
