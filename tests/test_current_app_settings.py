import asyncio
from dataclasses import replace
from datetime import date

import pytest
from fastapi import Request

from app import database, main
from app.cache import ApplicationCaches
from app.config import Settings, settings
from app.repositories import competitions as competitions_repository
from app.routers import competitions as competition_routes
from app.services import competitions as competitions_service


def custom_settings(*, production: bool) -> Settings:
    return replace(
        settings,
        database_url="postgresql://web:password@database.test:5432/artflow",
        db_host=None,
        db_name=None,
        db_user=None,
        db_password=None,
        bot_username="CustomArtFlowBot",
        app_env="production" if production else "development",
        base_url=(
            "https://artflow.example.test"
            if production
            else "http://127.0.0.1:8000"
        ),
        allowed_hosts=("testserver",),
        enable_docs=not production,
    )


def request_for(application, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"host", b"testserver")],
            "client": ("test", 50000),
            "server": ("testserver", 80),
            "root_path": "",
            "app": application,
        }
    )


def competition_row(**overrides):
    row = {
        "id": 7,
        "name": "Settings test",
        "description": "Description",
        "event_date": date(2026, 9, 5),
        "application_deadline": date(2026, 9, 1),
        "city": "Almaty",
        "place": "Stage",
        "short_description": "Short description",
        "directions": "Vocal",
        "poster_url": "http://cdn.example.test/poster",
        "rules_url": "http://cdn.example.test/rules",
        "price": "100",
    }
    row.update(overrides)
    return row


def test_create_app_lifespan_passes_custom_settings_to_database(monkeypatch):
    selected_settings = custom_settings(production=True)
    received = []
    selected_pool = object()

    async def open_pool(app_settings):
        received.append(app_settings)
        return selected_pool

    async def close_pool(pool):
        received.append(pool)

    monkeypatch.setattr(main, "open_database_pool", open_pool)
    monkeypatch.setattr(main, "close_database_pool", close_pool)
    application = main.create_app(selected_settings)

    async def run_lifespan():
        async with application.router.lifespan_context(application):
            assert application.state.database_pool is selected_pool
        assert application.state.database_pool is None

    asyncio.run(run_lifespan())
    assert received == [selected_settings, selected_pool]


def test_app_instances_keep_database_pools_and_caches_isolated(monkeypatch):
    first_settings = custom_settings(production=False)
    second_settings = replace(
        custom_settings(production=True),
        database_url="postgresql://web:password@second.test:5432/artflow",
    )
    pools = {}
    closed = []

    async def open_pool(app_settings):
        pool = object()
        pools[app_settings.database_dsn] = pool
        return pool

    async def close_pool(pool):
        closed.append(pool)

    monkeypatch.setattr(main, "open_database_pool", open_pool)
    monkeypatch.setattr(main, "close_database_pool", close_pool)
    first_app = main.create_app(first_settings)
    second_app = main.create_app(second_settings)

    async def run_lifespans():
        async with first_app.router.lifespan_context(first_app):
            async with second_app.router.lifespan_context(second_app):
                assert first_app.state.database_pool is pools[
                    first_settings.database_dsn
                ]
                assert second_app.state.database_pool is pools[
                    second_settings.database_dsn
                ]
                assert (
                    first_app.state.database_pool
                    is not second_app.state.database_pool
                )
                assert first_app.state.caches is not second_app.state.caches

    asyncio.run(run_lifespans())
    assert set(closed) == set(pools.values())
    assert not hasattr(database, "_pool")


def test_health_db_cache_is_scoped_to_application(monkeypatch):
    first_app = main.create_app(custom_settings(production=False))
    second_app = main.create_app(custom_settings(production=False))
    first_pool = object()
    second_pool = object()
    first_app.state.database_pool = first_pool
    second_app.state.database_pool = second_pool
    checked_pools = []

    async def check_connection(pool):
        checked_pools.append(pool)

    monkeypatch.setattr(main, "check_database_connection", check_connection)

    async def check_both_apps():
        await main.health_db(request_for(first_app, "/health/db"))
        await main.health_db(request_for(first_app, "/health/db"))
        await main.health_db(request_for(second_app, "/health/db"))

    asyncio.run(check_both_apps())
    assert checked_pools == [first_pool, second_pool]


def test_database_pool_uses_explicit_application_settings(monkeypatch):
    selected_settings = custom_settings(production=True)
    captured = {}

    class FakePool:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.closed = False

        async def open(self, *, wait):
            captured["wait"] = wait

        async def close(self, timeout=5):
            self.closed = True

    monkeypatch.setattr(database, "AsyncConnectionPool", FakePool)
    pool = asyncio.run(database.open_database_pool(selected_settings))

    assert captured["conninfo"] == selected_settings.database_dsn
    assert "default_transaction_read_only=on" in captured["kwargs"]["options"]
    assert "statement_timeout=5000" in captured["kwargs"]["options"]
    asyncio.run(database.close_database_pool(pool))


def test_route_uses_custom_production_settings_for_urls(monkeypatch):
    selected_settings = custom_settings(production=True)
    application = main.create_app(selected_settings)
    received = []

    async def get_competition(
        competition_id,
        app_settings=None,
        database_pool=None,
        cache=None,
    ):
        received.append(app_settings)
        return competitions_service._serialize_competition(
            competition_row(id=competition_id),
            app_settings,
        )

    monkeypatch.setattr(
        competition_routes,
        "get_competition_by_id",
        get_competition,
    )
    response = asyncio.run(
        competition_routes.competition_detail(
            request_for(application, "/competitions/7"),
            7,
        )
    )
    body = response.body.decode()

    assert received == [selected_settings]
    assert "http://cdn.example.test/poster" not in body
    assert "http://cdn.example.test/rules" not in body
    assert "https://t.me/CustomArtFlowBot?start=competition_7" in body


def test_cache_does_not_mix_development_and_production_settings(monkeypatch):
    calls = 0

    async def published_competitions(limit=None, *, pool=None):
        nonlocal calls
        calls += 1
        return [competition_row()]

    monkeypatch.setattr(
        competitions_repository,
        "get_published_competitions",
        published_competitions,
    )
    development = custom_settings(production=False)
    production = custom_settings(production=True)

    async def load_both():
        development_items = await competitions_service.get_competitions(
            development,
            cache=ApplicationCaches().competitions,
        )
        production_items = await competitions_service.get_competitions(
            production,
            cache=ApplicationCaches().competitions,
        )
        return development_items, production_items

    development_items, production_items = asyncio.run(load_both())
    assert development_items[0]["poster_url"].startswith("http://")
    assert production_items[0]["poster_url"] is None
    assert calls == 2


@pytest.mark.parametrize("invalid_value", ["prodution", "prod", "staging"])
def test_unknown_app_env_raises_clear_error(monkeypatch, invalid_value):
    monkeypatch.setenv("APP_ENV", invalid_value)
    monkeypatch.setenv("DB_PASSWORD", "DO_NOT_EXPOSE")

    with pytest.raises(ValueError) as error:
        Settings.from_env()

    message = str(error.value)
    assert "APP_ENV" in message
    assert "development, test, production" in message
    assert "DO_NOT_EXPOSE" not in message


@pytest.mark.parametrize("valid_value", ["development", "test", "production"])
def test_known_app_env_is_accepted(monkeypatch, valid_value):
    monkeypatch.setenv("APP_ENV", valid_value)
    assert Settings.from_env().app_env == valid_value


def test_url_with_credentials_is_rejected():
    url = "https://user:password@example.com/file"
    assert competitions_service._http_url(url) is None


def test_url_with_malformed_port_is_rejected():
    assert (
        competitions_service._http_url(
            "https://cdn.example.test:not-a-port/file"
        )
        is None
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://cdn.example.test/file\n",
        "https://cdn.example.test/fi\x7fle",
    ],
)
def test_url_with_control_character_is_rejected(url):
    assert competitions_service._http_url(url) is None


def test_url_without_hostname_is_rejected():
    assert competitions_service._http_url("https:///file") is None


def test_https_cdn_url_without_image_extension_is_preserved():
    url = "https://cdn.example.test/assets/poster?id=7"
    assert competitions_service._http_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/poster",
        "https://[::1]/poster",
        "https://10.0.0.5/poster",
        "https://[fd00::1]/poster",
        "https://0.0.0.0/poster",
        "https://[::]/poster",
        "https://localhost/poster",
        "https://assets/poster",
        "https://127.1/poster",
    ],
)
def test_production_rejects_non_public_url_hosts(url):
    assert (
        competitions_service._http_url(
            url,
            custom_settings(production=True),
        )
        is None
    )


def test_production_preserves_public_https_cdn_url():
    url = "https://media.cdn-example.com/assets/poster?id=7"
    assert (
        competitions_service._http_url(
            url,
            custom_settings(production=True),
        )
        == url
    )


@pytest.mark.parametrize("app_env", ["development", "test"])
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/poster",
        "http://localhost:8080/poster",
        "http://assets/poster",
    ],
)
def test_non_production_preserves_local_test_urls(app_env, url):
    app_settings = replace(
        custom_settings(production=False),
        app_env=app_env,
    )
    assert competitions_service._http_url(url, app_settings) == url
