from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from app.clock import current_date
from app.config import Settings, settings
from app.services.competitions import _serialize_competition


def competition_row(deadline: date) -> dict:
    return {
        "id": 7,
        "name": "Timezone test",
        "application_deadline": deadline,
    }


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 8, 31, 12, tzinfo=timezone.utc), True),
        (datetime(2026, 9, 1, 12, tzinfo=timezone.utc), True),
        (datetime(2026, 9, 2, 12, tzinfo=timezone.utc), False),
    ],
)
def test_registration_status_uses_fixed_application_time(now, expected):
    app_settings = replace(settings, app_timezone="Asia/Almaty")
    result = _serialize_competition(
        competition_row(date(2026, 9, 1)),
        app_settings,
        now=now,
    )
    assert result["registration_is_open"] is expected


def test_almaty_date_can_differ_from_utc_near_midnight():
    now = datetime(2026, 1, 1, 20, 30, tzinfo=timezone.utc)
    utc_settings = replace(settings, app_timezone="UTC")
    almaty_settings = replace(settings, app_timezone="Asia/Almaty")

    assert current_date(utc_settings, now=now) == date(2026, 1, 1)
    assert current_date(almaty_settings, now=now) == date(2026, 1, 2)

    deadline = date(2026, 1, 1)
    assert _serialize_competition(
        competition_row(deadline),
        utc_settings,
        now=now,
    )["registration_is_open"] is True
    assert _serialize_competition(
        competition_row(deadline),
        almaty_settings,
        now=now,
    )["registration_is_open"] is False


def test_invalid_app_timezone_raises_clear_error(monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "Mars/Olympus_Mons")
    monkeypatch.setenv("DB_PASSWORD", "DO_NOT_EXPOSE")

    with pytest.raises(ValueError) as error:
        Settings.from_env()

    assert "APP_TIMEZONE" in str(error.value)
    assert "IANA" in str(error.value)
    assert "DO_NOT_EXPOSE" not in str(error.value)


def test_naive_current_time_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        current_date(settings, now=datetime(2026, 1, 1, 12, 0))
