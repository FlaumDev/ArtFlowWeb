from __future__ import annotations

from datetime import date, datetime, timezone

from app.config import Settings


def current_date(
    app_settings: Settings,
    *,
    now: datetime | None = None,
) -> date:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("Current time must include timezone information")
    return current_time.astimezone(app_settings.timezone).date()
