from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def to_utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def parse_reset_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def local_day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[str, str]:
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return to_utc_iso(start), to_utc_iso(end)


def _reset_boundary(local_now: datetime, reset: time) -> datetime:
    return local_now.replace(hour=reset.hour, minute=reset.minute, second=0, microsecond=0)


def occupancy_day_start_utc(now_utc: datetime, tz: ZoneInfo, reset: time) -> str:
    local_now = now_utc.astimezone(tz)
    boundary = _reset_boundary(local_now, reset)
    if local_now < boundary:
        boundary -= timedelta(days=1)
    return to_utc_iso(boundary)


def seconds_until_next_reset(now_utc: datetime, tz: ZoneInfo, reset: time) -> float:
    local_now = now_utc.astimezone(tz)
    boundary = _reset_boundary(local_now, reset)
    if boundary <= local_now:
        boundary += timedelta(days=1)
    return (boundary - local_now).total_seconds()
