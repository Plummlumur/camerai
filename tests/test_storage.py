from datetime import date
from zoneinfo import ZoneInfo

import pytest

from storage.events import EventStore

VIENNA = ZoneInfo("Europe/Vienna")
T = "2026-06-12T{:02d}:{:02d}:00+00:00"


@pytest.fixture
def store(tmp_path):
    event_store = EventStore(tmp_path / "test.db")
    yield event_store
    event_store.close()


def test_wal_mode_enabled(store):
    assert store.journal_mode() == "wal"


def test_add_and_count_events(store):
    store.add_event(T.format(8, 0), "in", "raum-1")
    store.add_event(T.format(8, 5), "in", "raum-1")
    store.add_event(T.format(9, 0), "out", "raum-1")
    counts = store.counts_between(T.format(0, 0), T.format(23, 59))
    assert counts == {"in": 2, "out": 1}


def test_counts_between_respects_range(store):
    store.add_event(T.format(8, 0), "in", "raum-1")
    counts = store.counts_between(T.format(9, 0), T.format(23, 59))
    assert counts == {"in": 0, "out": 0}


def test_replay_occupancy_clamps_at_zero(store):
    store.add_event(T.format(8, 0), "out", "raum-1")
    store.add_event(T.format(8, 1), "in", "raum-1")
    store.add_event(T.format(8, 2), "in", "raum-1")
    assert store.replay_occupancy(T.format(0, 0)) == 2


def test_replay_occupancy_applies_corrections(store):
    store.add_event(T.format(8, 0), "in", "raum-1")
    store.add_event(T.format(9, 0), "correction", "raum-1", value=10)
    store.add_event(T.format(9, 5), "in", "raum-1")
    assert store.replay_occupancy(T.format(0, 0)) == 11


def test_replay_occupancy_ignores_older_events(store):
    store.add_event(T.format(1, 0), "in", "raum-1")
    store.add_event(T.format(8, 0), "in", "raum-1")
    assert store.replay_occupancy(T.format(2, 0)) == 1


def test_hourly_counts_buckets_by_local_hour(store):
    # 08:30 UTC = 10:30 Vienna (CEST) -> bucket 10
    store.add_event(T.format(8, 30), "in", "raum-1")
    store.add_event(T.format(8, 45), "out", "raum-1")
    hours = store.hourly_counts(T.format(0, 0), T.format(23, 59), VIENNA)
    assert len(hours) == 24
    assert hours[10] == {"hour": 10, "in": 1, "out": 1}
    assert hours[9] == {"hour": 9, "in": 0, "out": 0}


def test_daily_totals(store):
    store.add_event("2026-06-11T10:00:00+00:00", "in", "raum-1")
    store.add_event("2026-06-12T10:00:00+00:00", "in", "raum-1")
    store.add_event("2026-06-12T11:00:00+00:00", "out", "raum-1")
    days = store.daily_totals(2, VIENNA, today=date(2026, 6, 12))
    assert days == [
        {"date": "2026-06-11", "in": 1, "out": 0},
        {"date": "2026-06-12", "in": 1, "out": 1},
    ]
