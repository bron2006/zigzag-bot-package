from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import SESSION_FLAGS, SESSION_WINDOWS_UTC

DEFAULT_TIMEZONE = "Europe/Kyiv"


def normalize_timezone(value: str | None) -> str:
    tz = (value or "").strip()
    if not tz:
        return DEFAULT_TIMEZONE

    try:
        ZoneInfo(tz)
        return tz
    except ZoneInfoNotFoundError:
        return DEFAULT_TIMEZONE


def timezone_short_name(value: str | None) -> str:
    tz = normalize_timezone(value)
    parts = tz.split("/")
    return (parts[-1] if parts else tz).replace("_", " ")


def session_time_label(session: str, user_timezone: str | None = None, now: datetime | None = None) -> str:
    window = SESSION_WINDOWS_UTC.get(session)
    if not window:
        return ""

    tz_name = normalize_timezone(user_timezone)
    tz = ZoneInfo(tz_name)
    start_hour, end_hour = window

    base_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start_utc = base_utc.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    end_utc = base_utc.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    if end_hour <= start_hour:
        end_utc += timedelta(days=1)

    start_local = start_utc.astimezone(tz)
    end_local = end_utc.astimezone(tz)
    flag = SESSION_FLAGS.get(session, "")

    return f"{flag} ({start_local:%H:%M} - {end_local:%H:%M}, {timezone_short_name(tz_name)})".strip()
