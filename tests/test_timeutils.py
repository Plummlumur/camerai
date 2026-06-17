from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from timeutils import (
    local_day_bounds_utc,
    occupancy_day_start_utc,
    parse_reset_time,
    period_bounds,
    seconds_until_next_reset,
    utc_now_iso,
)

VIENNA = ZoneInfo("Europe/Vienna")


def test_utc_now_iso_format():
    value = utc_now_iso()
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    assert value.endswith("+00:00")


def test_parse_reset_time():
    assert parse_reset_time("04:00") == time(4, 0)
    assert parse_reset_time("23:30") == time(23, 30)


def test_local_day_bounds_utc_summer():
    # Vienna is UTC+2 in June: local 2026-06-12 runs 2026-06-11T22:00Z .. 2026-06-12T22:00Z
    start, end = local_day_bounds_utc(date(2026, 6, 12), VIENNA)
    assert start == "2026-06-11T22:00:00+00:00"
    assert end == "2026-06-12T22:00:00+00:00"


def test_occupancy_day_start_before_and_after_reset():
    reset = time(4, 0)
    # 10:00 local (08:00 UTC) -> boundary is today 04:00 local = 02:00 UTC
    after = datetime(2026, 6, 12, 8, 0, tzinfo=UTC)
    assert occupancy_day_start_utc(after, VIENNA, reset) == "2026-06-12T02:00:00+00:00"
    # 03:00 local (01:00 UTC) -> boundary is YESTERDAY 04:00 local
    before = datetime(2026, 6, 12, 1, 0, tzinfo=UTC)
    assert occupancy_day_start_utc(before, VIENNA, reset) == "2026-06-11T02:00:00+00:00"


def test_period_bounds():
    # 2026-06-17 is a Wednesday (ISO weekday 2), June has 30 days, May 31.
    today = date(2026, 6, 17)
    assert period_bounds("yesterday", today) == (date(2026, 6, 16), date(2026, 6, 16))
    assert period_bounds("current_week", today) == (date(2026, 6, 15), date(2026, 6, 17))
    assert period_bounds("last_week", today) == (date(2026, 6, 8), date(2026, 6, 14))
    assert period_bounds("current_month", today) == (date(2026, 6, 1), date(2026, 6, 17))
    assert period_bounds("last_month", today) == (date(2026, 5, 1), date(2026, 5, 31))


def test_period_bounds_rejects_unknown():
    import pytest

    with pytest.raises(ValueError):
        period_bounds("nonsense", date(2026, 6, 17))


def test_seconds_until_next_reset():
    reset = time(4, 0)
    # 03:00 local -> one hour until reset
    now = datetime(2026, 6, 12, 1, 0, tzinfo=UTC)
    assert seconds_until_next_reset(now, VIENNA, reset) == 3600.0
    # 04:00 local exactly -> next reset is tomorrow
    at_reset = datetime(2026, 6, 12, 2, 0, tzinfo=UTC)
    assert seconds_until_next_reset(at_reset, VIENNA, reset) == 86400.0
