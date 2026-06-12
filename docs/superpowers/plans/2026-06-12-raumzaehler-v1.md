# Raumzaehler Version 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fully functional single-device people counter: detection-source pipeline (simulator on dev, IMX500 on the Pi), line-crossing counting, SQLite event log, occupancy state, and a sleek modern dark dashboard with live numbers and an hourly chart.

**Architecture:** A `DetectionSource` yields normalized centroids per frame; a counting service (background thread) runs tracker → line-crossing counter → occupancy and persists every entry/exit as an event row in SQLite (WAL, single writer). FastAPI serves REST + WebSocket and the static dashboard; events are bridged from the counting thread into the asyncio loop and broadcast to all connected clients. Occupancy is in-memory, restored on startup by replaying events since the last nightly-reset boundary.

**Tech Stack:** Python 3.11+ (dev venv: 3.14), FastAPI, uvicorn, pydantic-settings, sqlite3 (stdlib, WAL), static HTML/CSS/JS + Chart.js (vendored, no build step), pytest, ruff.

**Out of scope (Version 2):** MQTT publishing, central multi-site dashboard, real authentication (the no-op auth hook IS in scope), Hailo-8 source.

**Note:** CLAUDE.md mentions a prototype `personenzaehler.py`; it is not in this repo (it lives on the Pi). The tracker/counting logic below is written from scratch with tests. When Task 12 (IMX500 source) is verified on the Pi, compare its metadata parsing against the prototype.

---

## File Structure

```
raumzaehler/
├── config.py                  # Settings (pydantic-settings, env / .env)
├── timeutils.py               # UTC/local-tz helpers, reset boundaries
├── conftest.py                # empty; makes top-level packages importable in pytest
├── requirements.txt           # runtime deps
├── requirements-dev.txt       # dev deps (pytest, httpx, ruff)
├── pyproject.toml             # ruff + pytest config only (no packaging)
├── .env.example
├── counter/
│   ├── __init__.py
│   ├── source_base.py         # DetectionSource Protocol
│   ├── source_sim.py          # SimulatedSource, NullSource
│   ├── source_imx500.py       # real camera; picamera2 imports ONLY here, lazily
│   ├── factory.py             # build_source(settings)
│   ├── tracker.py             # CentroidTracker
│   ├── counting.py            # Direction, LineCrossingCounter, OccupancyState
│   └── service.py             # CounterService (source→tracker→counter→store→callback)
├── storage/
│   ├── __init__.py
│   └── events.py              # EventStore (schema, WAL, inserts, aggregates)
├── api/
│   ├── __init__.py
│   ├── auth.py                # require_auth no-op dependency
│   ├── hub.py                 # WebSocketHub
│   ├── routes.py              # /api REST router
│   └── main.py                # create_app(), lifespan, /ws, static mount
├── web/
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── vendor/chart.umd.js    # vendored Chart.js 4
├── deploy/
│   ├── raumzaehler.service    # systemd unit
│   └── deploy.sh              # rsync + pip install + restart
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_timeutils.py
    ├── test_storage.py
    ├── test_tracker.py
    ├── test_counting.py
    ├── test_sources.py
    ├── test_service.py
    └── test_api.py
```

**Key data contracts (used consistently in every task):**

- Centroid: `tuple[float, float]` — `(x, y)` normalized to `[0, 1]`.
- `DetectionSource.frames()` → `Iterator[list[tuple[float, float]]]` (one list per frame).
- `CentroidTracker.update(centroids) -> dict[int, tuple[float, float]]` (track_id → position).
- `Direction` enum: `Direction.IN` (`"in"`), `Direction.OUT` (`"out"`).
- Event row: `events(id, ts_utc TEXT, direction TEXT in ('in','out','correction'), value INTEGER NULL, sensor_id TEXT)`. `value` is only set for corrections (the absolute occupancy that was set).
- Timestamps: `datetime.now(timezone.utc).isoformat(timespec="seconds")` → e.g. `"2026-06-12T10:00:00+00:00"`. Uniform format ⇒ lexicographic string comparison in SQL is chronologically correct.
- WebSocket payloads: `{"type": "count", "direction": "in"|"out", "occupancy": int, "ts_utc": str}`, `{"type": "correction", "occupancy": int, "ts_utc": str}`, `{"type": "reset", "occupancy": 0, "ts_utc": str}`.

---

### Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `conftest.py`, `.env.example`
- Create: `counter/__init__.py`, `storage/__init__.py`, `api/__init__.py`, `tests/__init__.py` (all empty)
- Modify: `.gitignore` (add `data/`)

- [ ] **Step 1: Create `requirements.txt`**

```
fastapi>=0.115
uvicorn[standard]>=0.30
pydantic-settings>=2.6
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```
-r requirements.txt
pytest>=8.0
httpx>=0.27
ruff>=0.8
```

- [ ] **Step 3: Create `pyproject.toml`** (tool config only — the project is deployed by rsync, not packaged)

```toml
[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 4: Create empty files** `conftest.py`, `counter/__init__.py`, `storage/__init__.py`, `api/__init__.py`, `tests/__init__.py`. The root `conftest.py` makes pytest add the repo root to `sys.path` so `counter`, `storage`, `api` import as top-level packages.

- [ ] **Step 5: Create `.env.example`**

```
COUNTER_SOURCE=sim
SENSOR_ID=raum-1
DB_PATH=data/raumzaehler.db
TIMEZONE=Europe/Vienna
INVERT_DIRECTION=false
NIGHTLY_RESET_TIME=04:00
LINE_POSITION=0.5
LINE_AXIS=x
```

- [ ] **Step 6: Add `data/` to `.gitignore`** (append under the `# Project` section)

- [ ] **Step 7: Install dependencies**

Run: `.venv/bin/pip install -r requirements-dev.txt`
Expected: installs without error. Then `.venv/bin/pytest` → "no tests ran" (exit code 5 is fine).

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "chore: project scaffolding, deps, tool config"
```

---

### Task 2: Configuration (`config.py`)

**Files:**
- Create: `config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
from config import Settings


def test_defaults():
    settings = Settings(_env_file=None)
    assert settings.counter_source == "sim"
    assert settings.sensor_id == "raum-1"
    assert settings.timezone == "Europe/Vienna"
    assert settings.invert_direction is False
    assert settings.nightly_reset_time == "04:00"
    assert settings.line_position == 0.5
    assert settings.line_axis == "x"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("COUNTER_SOURCE", "imx500")
    monkeypatch.setenv("INVERT_DIRECTION", "true")
    settings = Settings(_env_file=None)
    assert settings.counter_source == "imx500"
    assert settings.invert_direction is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Implement `config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    counter_source: str = "sim"
    sensor_id: str = "raum-1"
    db_path: str = "data/raumzaehler.db"
    timezone: str = "Europe/Vienna"
    invert_direction: bool = False
    nightly_reset_time: str = "04:00"
    line_position: float = 0.5
    line_axis: str = "x"
    imx500_model_path: str = (
        "/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk"
    )
    detection_confidence: float = 0.5


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py && git commit -m "feat: settings via env vars / .env"
```

---

### Task 3: Time helpers (`timeutils.py`)

All timestamps are stored UTC; aggregation/boundaries use the configured local timezone. These helpers are the single place where that conversion happens.

**Files:**
- Create: `timeutils.py`
- Test: `tests/test_timeutils.py`

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from timeutils import (
    local_day_bounds_utc,
    occupancy_day_start_utc,
    parse_reset_time,
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
    after = datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc)
    assert occupancy_day_start_utc(after, VIENNA, reset) == "2026-06-12T02:00:00+00:00"
    # 03:00 local (01:00 UTC) -> boundary is YESTERDAY 04:00 local
    before = datetime(2026, 6, 12, 1, 0, tzinfo=timezone.utc)
    assert occupancy_day_start_utc(before, VIENNA, reset) == "2026-06-11T02:00:00+00:00"


def test_seconds_until_next_reset():
    reset = time(4, 0)
    # 03:00 local -> one hour until reset
    now = datetime(2026, 6, 12, 1, 0, tzinfo=timezone.utc)
    assert seconds_until_next_reset(now, VIENNA, reset) == 3600.0
    # 04:00 local exactly -> next reset is tomorrow
    at_reset = datetime(2026, 6, 12, 2, 0, tzinfo=timezone.utc)
    assert seconds_until_next_reset(at_reset, VIENNA, reset) == 86400.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_timeutils.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'timeutils'`

- [ ] **Step 3: Implement `timeutils.py`**

```python
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_timeutils.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add timeutils.py tests/test_timeutils.py && git commit -m "feat: UTC/local time helpers and reset boundaries"
```

---

### Task 4: Event store (`storage/events.py`)

SQLite with WAL. One `EventStore` instance per process, internal `threading.Lock` so the counting thread and API thread never write concurrently. Write transactions are single inserts (short, per project rules).

**Files:**
- Create: `storage/events.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: Implement `storage/events.py`**

```python
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from timeutils import local_day_bounds_utc

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out', 'correction')),
    value INTEGER,
    sensor_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts_utc);
"""


class EventStore:
    def __init__(self, db_path: str | Path):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def journal_mode(self) -> str:
        return self._conn.execute("PRAGMA journal_mode").fetchone()[0]

    def add_event(
        self, ts_utc: str, direction: str, sensor_id: str, value: int | None = None
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO events (ts_utc, direction, value, sensor_id) VALUES (?, ?, ?, ?)",
                (ts_utc, direction, value, sensor_id),
            )

    def counts_between(self, start_utc: str, end_utc: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT direction, COUNT(*) FROM events"
            " WHERE ts_utc >= ? AND ts_utc < ? AND direction IN ('in', 'out')"
            " GROUP BY direction",
            (start_utc, end_utc),
        ).fetchall()
        counts = {"in": 0, "out": 0}
        counts.update(dict(rows))
        return counts

    def replay_occupancy(self, since_utc: str) -> int:
        rows = self._conn.execute(
            "SELECT direction, value FROM events WHERE ts_utc >= ? ORDER BY id",
            (since_utc,),
        ).fetchall()
        count = 0
        for direction, value in rows:
            if direction == "in":
                count += 1
            elif direction == "out":
                count = max(0, count - 1)
            else:
                count = max(0, value or 0)
        return count

    def hourly_counts(self, start_utc: str, end_utc: str, tz: ZoneInfo) -> list[dict]:
        rows = self._conn.execute(
            "SELECT ts_utc, direction FROM events"
            " WHERE ts_utc >= ? AND ts_utc < ? AND direction IN ('in', 'out')",
            (start_utc, end_utc),
        ).fetchall()
        buckets = [{"hour": hour, "in": 0, "out": 0} for hour in range(24)]
        for ts_utc, direction in rows:
            local_hour = datetime.fromisoformat(ts_utc).astimezone(tz).hour
            buckets[local_hour][direction] += 1
        return buckets

    def daily_totals(self, days: int, tz: ZoneInfo, today: date) -> list[dict]:
        result = []
        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            start, end = local_day_bounds_utc(day, tz)
            counts = self.counts_between(start, end)
            result.append({"date": day.isoformat(), "in": counts["in"], "out": counts["out"]})
        return result

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_storage.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add storage/events.py tests/test_storage.py && git commit -m "feat: SQLite event store with WAL and aggregates"
```

---

### Task 5: Centroid tracker (`counter/tracker.py`)

Greedy nearest-neighbor matching. Track IDs are never reused. Unmatched tracks coast at their last position for `max_missed` frames, then drop.

**Files:**
- Create: `counter/tracker.py`
- Test: `tests/test_tracker.py`

- [ ] **Step 1: Write the failing tests**

```python
from counter.tracker import CentroidTracker


def test_assigns_id_and_follows_movement():
    tracker = CentroidTracker()
    first = tracker.update([(0.10, 0.5)])
    assert list(first.keys()) == [0]
    second = tracker.update([(0.15, 0.5)])
    assert second == {0: (0.15, 0.5)}


def test_distant_centroid_gets_new_id():
    tracker = CentroidTracker(max_distance=0.2)
    tracker.update([(0.1, 0.5)])
    tracks = tracker.update([(0.9, 0.5)])
    assert 1 in tracks  # too far to be track 0


def test_track_coasts_then_drops():
    tracker = CentroidTracker(max_missed=2)
    tracker.update([(0.5, 0.5)])
    assert 0 in tracker.update([])  # missed 1
    assert 0 in tracker.update([])  # missed 2
    assert tracker.update([]) == {}  # missed 3 -> dropped


def test_two_tracks_keep_identity():
    tracker = CentroidTracker(max_distance=0.2)
    tracker.update([(0.1, 0.2), (0.9, 0.8)])
    tracks = tracker.update([(0.15, 0.2), (0.85, 0.8)])
    assert tracks[0] == (0.15, 0.2)
    assert tracks[1] == (0.85, 0.8)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_tracker.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `counter/tracker.py`**

```python
import math

Centroid = tuple[float, float]


class CentroidTracker:
    def __init__(self, max_distance: float = 0.2, max_missed: int = 8):
        self._max_distance = max_distance
        self._max_missed = max_missed
        self._next_id = 0
        self._tracks: dict[int, Centroid] = {}
        self._missed: dict[int, int] = {}

    def update(self, centroids: list[Centroid]) -> dict[int, Centroid]:
        unmatched_tracks = set(self._tracks)
        unmatched_centroids = set(range(len(centroids)))
        candidates = sorted(
            (self._distance(self._tracks[track_id], centroids[index]), track_id, index)
            for track_id in unmatched_tracks
            for index in unmatched_centroids
        )
        for distance, track_id, index in candidates:
            if distance > self._max_distance:
                break
            if track_id not in unmatched_tracks or index not in unmatched_centroids:
                continue
            self._tracks[track_id] = centroids[index]
            self._missed[track_id] = 0
            unmatched_tracks.discard(track_id)
            unmatched_centroids.discard(index)
        for index in unmatched_centroids:
            self._tracks[self._next_id] = centroids[index]
            self._missed[self._next_id] = 0
            self._next_id += 1
        for track_id in unmatched_tracks:
            self._missed[track_id] += 1
            if self._missed[track_id] > self._max_missed:
                del self._tracks[track_id]
                del self._missed[track_id]
        return dict(self._tracks)

    @staticmethod
    def _distance(a: Centroid, b: Centroid) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_tracker.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add counter/tracker.py tests/test_tracker.py && git commit -m "feat: greedy centroid tracker"
```

---

### Task 6: Line crossing + occupancy (`counter/counting.py`)

A track "crosses" when its side of the line flips between frames. Default mapping: movement in positive axis direction = entry; `invert=True` flips it (config `INVERT_DIRECTION`, depends on camera orientation — never hardcode). `OccupancyState` is thread-safe and never goes below 0.

**Files:**
- Create: `counter/counting.py`
- Test: `tests/test_counting.py`

- [ ] **Step 1: Write the failing tests**

```python
from counter.counting import Direction, LineCrossingCounter, OccupancyState


def walk(counter, track_id, positions):
    events = []
    for x in positions:
        events.extend(counter.update({track_id: (x, 0.5)}))
    return events


def test_crossing_positive_direction_is_entry():
    counter = LineCrossingCounter(line_position=0.5, axis="x", invert=False)
    assert walk(counter, 0, [0.2, 0.4, 0.6, 0.8]) == [Direction.IN]


def test_crossing_negative_direction_is_exit():
    counter = LineCrossingCounter(line_position=0.5, axis="x", invert=False)
    assert walk(counter, 0, [0.8, 0.6, 0.4, 0.2]) == [Direction.OUT]


def test_invert_flips_directions():
    counter = LineCrossingCounter(line_position=0.5, axis="x", invert=True)
    assert walk(counter, 0, [0.2, 0.8]) == [Direction.OUT]


def test_y_axis_counting():
    counter = LineCrossingCounter(line_position=0.5, axis="y", invert=False)
    events = []
    for y in [0.2, 0.8]:
        events.extend(counter.update({0: (0.5, y)}))
    assert events == [Direction.IN]


def test_no_event_without_crossing():
    counter = LineCrossingCounter()
    assert walk(counter, 0, [0.1, 0.2, 0.3, 0.4]) == []


def test_disappeared_track_state_is_cleaned_up():
    counter = LineCrossingCounter()
    counter.update({0: (0.2, 0.5)})
    counter.update({})  # track gone
    # same id never comes back (tracker never reuses), but state must not leak
    assert counter.tracked_ids() == set()


def test_occupancy_never_below_zero():
    occupancy = OccupancyState()
    assert occupancy.apply(Direction.OUT) == 0
    assert occupancy.apply(Direction.IN) == 1
    assert occupancy.apply(Direction.OUT) == 0


def test_occupancy_manual_set_clamps():
    occupancy = OccupancyState()
    assert occupancy.set_count(12) == 12
    assert occupancy.set_count(-3) == 0
    assert occupancy.count == 0


def test_occupancy_restores_initial_value():
    assert OccupancyState(initial=5).count == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_counting.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `counter/counting.py`**

```python
import threading
from enum import Enum

Centroid = tuple[float, float]


class Direction(str, Enum):
    IN = "in"
    OUT = "out"


class LineCrossingCounter:
    def __init__(self, line_position: float = 0.5, axis: str = "x", invert: bool = False):
        if axis not in ("x", "y"):
            raise ValueError(f"axis must be 'x' or 'y', got {axis!r}")
        self._line_position = line_position
        self._axis_index = 0 if axis == "x" else 1
        self._invert = invert
        self._last_side: dict[int, int] = {}

    def update(self, tracks: dict[int, Centroid]) -> list[Direction]:
        crossings: list[Direction] = []
        for track_id, centroid in tracks.items():
            side = 1 if centroid[self._axis_index] >= self._line_position else -1
            previous = self._last_side.get(track_id)
            if previous is not None and side != previous:
                entering = side > previous
                if self._invert:
                    entering = not entering
                crossings.append(Direction.IN if entering else Direction.OUT)
            self._last_side[track_id] = side
        for track_id in list(self._last_side):
            if track_id not in tracks:
                del self._last_side[track_id]
        return crossings

    def tracked_ids(self) -> set[int]:
        return set(self._last_side)


class OccupancyState:
    def __init__(self, initial: int = 0):
        self._count = max(0, initial)
        self._lock = threading.Lock()

    @property
    def count(self) -> int:
        return self._count

    def apply(self, direction: Direction) -> int:
        with self._lock:
            if direction is Direction.IN:
                self._count += 1
            else:
                self._count = max(0, self._count - 1)
            return self._count

    def set_count(self, value: int) -> int:
        with self._lock:
            self._count = max(0, value)
            return self._count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_counting.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add counter/counting.py tests/test_counting.py && git commit -m "feat: line-crossing counter and occupancy state"
```

---

### Task 7: Detection sources — interface, simulator, factory

`SimulatedSource` generates one synthetic person at a time walking across the line (both directions, random idle gaps). `NullSource` yields nothing (for API tests). `frame_interval=0` disables sleeping so tests run instantly.

**Files:**
- Create: `counter/source_base.py`, `counter/source_sim.py`, `counter/factory.py`
- Test: `tests/test_sources.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from config import Settings
from counter.counting import LineCrossingCounter
from counter.factory import build_source
from counter.source_sim import NullSource, SimulatedSource
from counter.tracker import CentroidTracker


def test_simulator_produces_exact_number_of_crossings():
    source = SimulatedSource(frame_interval=0, seed=42, max_crossings=5)
    tracker = CentroidTracker()
    counter = LineCrossingCounter()
    crossings = []
    for centroids in source.frames():
        crossings.extend(counter.update(tracker.update(centroids)))
    assert len(crossings) == 5


def test_simulator_centroids_are_normalized():
    source = SimulatedSource(frame_interval=0, seed=1, max_crossings=2)
    for centroids in source.frames():
        for x, y in centroids:
            assert 0.0 <= x <= 1.0
            assert 0.0 <= y <= 1.0


def test_null_source_yields_nothing():
    assert list(NullSource().frames()) == []


def test_factory_builds_sim_and_none():
    assert isinstance(build_source(Settings(_env_file=None, counter_source="sim")), SimulatedSource)
    assert isinstance(build_source(Settings(_env_file=None, counter_source="none")), NullSource)


def test_factory_rejects_unknown_source():
    with pytest.raises(ValueError, match="unknown COUNTER_SOURCE"):
        build_source(Settings(_env_file=None, counter_source="kaputt"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sources.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `counter/source_base.py`**

```python
from collections.abc import Iterator
from typing import Protocol

Centroid = tuple[float, float]


class DetectionSource(Protocol):
    def frames(self) -> Iterator[list[Centroid]]:
        """Yield one list of normalized (x, y) person centroids per frame."""
        ...
```

- [ ] **Step 4: Implement `counter/source_sim.py`**

```python
import random
import time
from collections.abc import Iterator

from counter.source_base import Centroid

_WALK_STEPS = 10


class SimulatedSource:
    """Synthetic people walking across the counting line, one at a time."""

    def __init__(
        self,
        frame_interval: float = 0.3,
        seed: int | None = None,
        max_crossings: int | None = None,
    ):
        self._frame_interval = frame_interval
        self._rng = random.Random(seed)
        self._max_crossings = max_crossings

    def frames(self) -> Iterator[list[Centroid]]:
        crossings = 0
        while self._max_crossings is None or crossings < self._max_crossings:
            for _ in range(self._rng.randint(2, 6)):
                yield self._frame([])
            xs = [step / (_WALK_STEPS - 1) for step in range(_WALK_STEPS)]
            if self._rng.random() >= 0.55:
                xs.reverse()
            y = self._rng.uniform(0.3, 0.7)
            for x in xs:
                yield self._frame([(x, y)])
            crossings += 1

    def _frame(self, centroids: list[Centroid]) -> list[Centroid]:
        if self._frame_interval > 0:
            time.sleep(self._frame_interval)
        return centroids


class NullSource:
    """Produces no frames; used in tests and as a safe fallback."""

    def frames(self) -> Iterator[list[Centroid]]:
        return iter(())
```

- [ ] **Step 5: Implement `counter/factory.py`**

```python
from config import Settings
from counter.source_base import DetectionSource
from counter.source_sim import NullSource, SimulatedSource


def build_source(settings: Settings) -> DetectionSource:
    if settings.counter_source == "sim":
        return SimulatedSource()
    if settings.counter_source == "none":
        return NullSource()
    if settings.counter_source == "imx500":
        from counter.source_imx500 import Imx500Source

        return Imx500Source(
            model_path=settings.imx500_model_path,
            confidence=settings.detection_confidence,
        )
    raise ValueError(f"unknown COUNTER_SOURCE: {settings.counter_source!r}")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sources.py -v`
Expected: 5 passed (the imx500 branch is not exercised — `counter/source_imx500.py` comes in Task 12; the lazy import inside the `if` keeps everything importable on dev machines)

- [ ] **Step 7: Commit**

```bash
git add counter/source_base.py counter/source_sim.py counter/factory.py tests/test_sources.py
git commit -m "feat: detection source interface, simulator, factory"
```

---

### Task 8: Counting service (`counter/service.py`)

Ties the pipeline together. Runs blocking in a background thread; `on_event` is called synchronously from that thread (the API layer bridges it into asyncio).

**Files:**
- Create: `counter/service.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Write the failing test**

```python
from counter.counting import LineCrossingCounter, OccupancyState
from counter.service import CounterService
from counter.source_sim import SimulatedSource
from counter.tracker import CentroidTracker
from storage.events import EventStore

ALL_TIME = ("2000-01-01T00:00:00+00:00", "2100-01-01T00:00:00+00:00")


def test_service_persists_and_reports_crossings(tmp_path):
    store = EventStore(tmp_path / "test.db")
    received = []
    service = CounterService(
        source=SimulatedSource(frame_interval=0, seed=42, max_crossings=5),
        tracker=CentroidTracker(),
        line_counter=LineCrossingCounter(),
        occupancy=OccupancyState(),
        store=store,
        sensor_id="test-sensor",
        on_event=received.append,
    )
    service.run()
    assert len(received) == 5
    assert all(event["type"] == "count" for event in received)
    assert all(event["direction"] in ("in", "out") for event in received)
    counts = store.counts_between(*ALL_TIME)
    assert counts["in"] + counts["out"] == 5
    store.close()


def test_service_stop_breaks_loop(tmp_path):
    store = EventStore(tmp_path / "test.db")
    service = CounterService(
        source=SimulatedSource(frame_interval=0, seed=1, max_crossings=None),
        tracker=CentroidTracker(),
        line_counter=LineCrossingCounter(),
        occupancy=OccupancyState(),
        store=store,
        sensor_id="test-sensor",
        on_event=lambda event: service.stop(),
    )
    service.run()  # returns because stop() is called on the first event
    store.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `counter/service.py`**

```python
import logging
import threading
from collections.abc import Callable

from counter.counting import LineCrossingCounter, OccupancyState
from counter.source_base import DetectionSource
from counter.tracker import CentroidTracker
from storage.events import EventStore
from timeutils import utc_now_iso

logger = logging.getLogger(__name__)


class CounterService:
    def __init__(
        self,
        source: DetectionSource,
        tracker: CentroidTracker,
        line_counter: LineCrossingCounter,
        occupancy: OccupancyState,
        store: EventStore,
        sensor_id: str,
        on_event: Callable[[dict], None],
    ):
        self._source = source
        self._tracker = tracker
        self._line_counter = line_counter
        self._occupancy = occupancy
        self._store = store
        self._sensor_id = sensor_id
        self._on_event = on_event
        self._stop_requested = threading.Event()

    def run(self) -> None:
        logger.info("counter service started (source=%s)", type(self._source).__name__)
        for centroids in self._source.frames():
            if self._stop_requested.is_set():
                break
            tracks = self._tracker.update(centroids)
            for direction in self._line_counter.update(tracks):
                ts_utc = utc_now_iso()
                occupancy = self._occupancy.apply(direction)
                self._store.add_event(ts_utc, direction.value, self._sensor_id)
                self._on_event(
                    {
                        "type": "count",
                        "direction": direction.value,
                        "occupancy": occupancy,
                        "ts_utc": ts_utc,
                    }
                )
        logger.info("counter service stopped")

    def stop(self) -> None:
        self._stop_requested.set()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_service.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add counter/service.py tests/test_service.py && git commit -m "feat: counting service wiring source to storage"
```

---

### Task 9: FastAPI app — skeleton, status endpoint, static dashboard

`create_app(settings)` factory so tests inject `counter_source="none"` and a tmp DB. Lifespan: open store → restore occupancy (replay since reset boundary) → start counter thread → start broadcast pump + nightly reset task. Auth is a no-op dependency on the whole router (wire real login later without restructuring).

**Files:**
- Create: `api/auth.py`, `api/hub.py`, `api/routes.py`, `api/main.py`, `web/index.html` (minimal, replaced in Task 11)
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

```python
from fastapi.testclient import TestClient

from api.main import create_app
from config import Settings


def make_client(tmp_path) -> TestClient:
    settings = Settings(_env_file=None, counter_source="none", db_path=str(tmp_path / "test.db"))
    return TestClient(create_app(settings))


def test_status_starts_empty(tmp_path):
    with make_client(tmp_path) as client:
        response = client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["occupancy"] == 0
    assert body["today_in"] == 0
    assert body["today_out"] == 0
    assert body["sensor_id"] == "raum-1"


def test_status_restores_occupancy_from_events(tmp_path):
    settings = Settings(_env_file=None, counter_source="none", db_path=str(tmp_path / "test.db"))
    from storage.events import EventStore
    from timeutils import utc_now_iso

    store = EventStore(settings.db_path)
    store.add_event(utc_now_iso(), "in", "raum-1")
    store.add_event(utc_now_iso(), "in", "raum-1")
    store.close()
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/status").json()
    assert body["occupancy"] == 2
    assert body["today_in"] == 2


def test_dashboard_is_served(tmp_path):
    with make_client(tmp_path) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Raumzähler" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `api/auth.py`**

```python
async def require_auth() -> None:
    """Auth hook for all routes. No-op for now; replace with real login later."""
    return None
```

- [ ] **Step 4: Implement `api/hub.py`**

```python
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketHub:
    def __init__(self):
        self._clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def broadcast(self, payload: dict) -> None:
        for websocket in list(self._clients):
            try:
                await websocket.send_json(payload)
            except Exception:
                logger.warning("dropping unreachable websocket client")
                self._clients.discard(websocket)
```

- [ ] **Step 5: Implement `api/routes.py`** (status only for now; stats/correction come in Task 10)

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request

from api.auth import require_auth
from timeutils import local_day_bounds_utc

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


def _today_bounds(request: Request) -> tuple[str, str]:
    tz = ZoneInfo(request.app.state.settings.timezone)
    today = datetime.now(timezone.utc).astimezone(tz).date()
    return local_day_bounds_utc(today, tz)


@router.get("/status")
def get_status(request: Request) -> dict:
    state = request.app.state
    counts = state.store.counts_between(*_today_bounds(request))
    return {
        "occupancy": state.occupancy.count,
        "today_in": counts["in"],
        "today_out": counts["out"],
        "sensor_id": state.settings.sensor_id,
        "source": state.settings.counter_source,
    }
```

- [ ] **Step 6: Implement `api/main.py`**

```python
import asyncio
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from api.hub import WebSocketHub
from api.routes import router
from config import Settings, get_settings
from counter.counting import LineCrossingCounter, OccupancyState
from counter.factory import build_source
from counter.service import CounterService
from counter.tracker import CentroidTracker
from storage.events import EventStore
from timeutils import (
    occupancy_day_start_utc,
    parse_reset_time,
    seconds_until_next_reset,
    utc_now_iso,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tz = ZoneInfo(app_settings.timezone)
        reset_time = parse_reset_time(app_settings.nightly_reset_time)
        store = EventStore(app_settings.db_path)
        since = occupancy_day_start_utc(datetime.now(timezone.utc), tz, reset_time)
        occupancy = OccupancyState(initial=store.replay_occupancy(since))
        hub = WebSocketHub()
        event_queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_event(payload: dict) -> None:
            loop.call_soon_threadsafe(event_queue.put_nowait, payload)

        service = CounterService(
            source=build_source(app_settings),
            tracker=CentroidTracker(),
            line_counter=LineCrossingCounter(
                line_position=app_settings.line_position,
                axis=app_settings.line_axis,
                invert=app_settings.invert_direction,
            ),
            occupancy=occupancy,
            store=store,
            sensor_id=app_settings.sensor_id,
            on_event=on_event,
        )
        counter_thread = threading.Thread(target=service.run, name="counter", daemon=True)
        counter_thread.start()

        async def pump_events() -> None:
            while True:
                payload = await event_queue.get()
                await hub.broadcast(payload)

        async def nightly_reset() -> None:
            while True:
                delay = seconds_until_next_reset(datetime.now(timezone.utc), tz, reset_time)
                await asyncio.sleep(delay)
                occupancy.set_count(0)
                await hub.broadcast({"type": "reset", "occupancy": 0, "ts_utc": utc_now_iso()})

        background_tasks = [
            asyncio.create_task(pump_events()),
            asyncio.create_task(nightly_reset()),
        ]
        app.state.settings = app_settings
        app.state.store = store
        app.state.occupancy = occupancy
        app.state.hub = hub
        yield
        service.stop()
        for task in background_tasks:
            task.cancel()
        counter_thread.join(timeout=2)
        store.close()

    app = FastAPI(title="Raumzaehler", lifespan=lifespan)
    app.include_router(router)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        hub: WebSocketHub = websocket.app.state.hub
        await hub.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            hub.disconnect(websocket)

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
```

- [ ] **Step 7: Create minimal `web/index.html`** (full dashboard replaces this in Task 11)

```html
<!doctype html>
<html lang="de">
<head><meta charset="utf-8"><title>Raumzähler</title></head>
<body><h1>Raumzähler</h1></body>
</html>
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: 3 passed

- [ ] **Step 9: Smoke-test the dev server**

Run: `COUNTER_SOURCE=sim .venv/bin/uvicorn api.main:app --port 8000` (then `curl -s localhost:8000/api/status`, expect JSON with rising counters; Ctrl-C afterwards)

- [ ] **Step 10: Commit**

```bash
git add api/ web/index.html tests/test_api.py
git commit -m "feat: FastAPI app with lifespan, status endpoint, websocket hub"
```

---

### Task 10: Stats endpoints, manual correction, WebSocket broadcast

**Files:**
- Modify: `api/routes.py` (append endpoints)
- Test: `tests/test_api.py` (append tests)

- [ ] **Step 1: Append the failing tests to `tests/test_api.py`**

```python
def test_today_stats_has_24_hour_buckets(tmp_path):
    with make_client(tmp_path) as client:
        body = client.get("/api/stats/today").json()
    assert len(body["hours"]) == 24
    assert body["hours"][0] == {"hour": 0, "in": 0, "out": 0}


def test_history_defaults_to_seven_days(tmp_path):
    with make_client(tmp_path) as client:
        body = client.get("/api/stats/history").json()
    assert len(body["days"]) == 7


def test_correction_sets_occupancy_and_writes_event(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post("/api/occupancy", json={"value": 7})
        assert response.status_code == 200
        assert response.json()["occupancy"] == 7
        assert client.get("/api/status").json()["occupancy"] == 7
        store = client.app.state.store
        rows = store._conn.execute(
            "SELECT direction, value FROM events ORDER BY id"
        ).fetchall()
    assert rows == [("correction", 7)]


def test_correction_rejects_negative_values(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post("/api/occupancy", json={"value": -1})
    assert response.status_code == 422


def test_correction_is_broadcast_to_websocket_clients(tmp_path):
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as websocket:
            client.post("/api/occupancy", json={"value": 4})
            message = websocket.receive_json()
    assert message["type"] == "correction"
    assert message["occupancy"] == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: the 5 new tests FAIL with 404 / connection errors; the 3 old ones still pass.

- [ ] **Step 3: Append to `api/routes.py`**

Add imports at the top of the file:

```python
from pydantic import BaseModel, Field

from timeutils import utc_now_iso
```

Append below `get_status`:

```python
class CorrectionRequest(BaseModel):
    value: int = Field(ge=0)


@router.get("/stats/today")
def get_today_stats(request: Request) -> dict:
    state = request.app.state
    tz = ZoneInfo(state.settings.timezone)
    today = datetime.now(timezone.utc).astimezone(tz).date()
    start, end = local_day_bounds_utc(today, tz)
    return {"date": today.isoformat(), "hours": state.store.hourly_counts(start, end, tz)}


@router.get("/stats/history")
def get_history(request: Request, days: int = 7) -> dict:
    state = request.app.state
    tz = ZoneInfo(state.settings.timezone)
    today = datetime.now(timezone.utc).astimezone(tz).date()
    return {"days": state.store.daily_totals(days, tz, today)}


@router.post("/occupancy")
async def correct_occupancy(request: Request, correction: CorrectionRequest) -> dict:
    state = request.app.state
    occupancy = state.occupancy.set_count(correction.value)
    ts_utc = utc_now_iso()
    state.store.add_event(ts_utc, "correction", state.settings.sensor_id, value=occupancy)
    await state.hub.broadcast({"type": "correction", "occupancy": occupancy, "ts_utc": ts_utc})
    return {"occupancy": occupancy}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add api/routes.py tests/test_api.py
git commit -m "feat: stats endpoints, manual occupancy correction, ws broadcast"
```

---

### Task 11: Dashboard frontend (slim, modern, dark)

Single-page dark dashboard: large occupancy number, today's entries/exits, hourly bar chart (Chart.js, vendored — the Pi may have no internet), live WebSocket updates with auto-reconnect, correction form. No build step.

**Files:**
- Create: `web/style.css`, `web/app.js`, `web/vendor/chart.umd.js`
- Modify: `web/index.html` (replace placeholder)

- [ ] **Step 1: Vendor Chart.js**

Run:
```bash
mkdir -p web/vendor
curl -fsSL -o web/vendor/chart.umd.js https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.js
```
Expected: file exists, starts with `/*! For license information ...` or similar minified banner.

- [ ] **Step 2: Replace `web/index.html`**

```html
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Raumzähler</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <main class="dashboard">
    <header>
      <h1>Raumzähler</h1>
      <span id="connection" class="status">Verbinde …</span>
    </header>

    <section class="occupancy-card">
      <p class="label">Aktuelle Belegung</p>
      <p id="occupancy" class="occupancy-value">–</p>
      <div class="day-counts">
        <div>
          <span id="today-in" class="count-value">–</span>
          <span class="count-label">Eintritte heute</span>
        </div>
        <div>
          <span id="today-out" class="count-value">–</span>
          <span class="count-label">Austritte heute</span>
        </div>
      </div>
    </section>

    <section>
      <p class="label">Verlauf heute</p>
      <canvas id="hourly-chart" height="120"></canvas>
    </section>

    <section>
      <p class="label">Belegung korrigieren</p>
      <form id="correction-form">
        <input id="correction-value" type="number" min="0" step="1"
               placeholder="Neue Belegung" required>
        <button type="submit">Setzen</button>
      </form>
    </section>
  </main>
  <script src="/vendor/chart.umd.js"></script>
  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Create `web/style.css`**

```css
:root {
  --bg: #0e1116;
  --card: #161b22;
  --border: #232a33;
  --text: #e6e9ee;
  --muted: #8b95a3;
  --accent: #4cc38a;
  --accent-out: #e5704c;
}

* { box-sizing: border-box; margin: 0; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  min-height: 100vh;
  display: flex;
  justify-content: center;
  padding: 2rem 1rem;
}

.dashboard {
  width: min(720px, 100%);
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 0 0.25rem;
}

h1 { font-size: 1.25rem; font-weight: 600; letter-spacing: 0.02em; }

.status { font-size: 0.8rem; color: var(--muted); }
.status::before { content: "●"; margin-right: 0.4em; color: var(--accent-out); }
.status--live::before { color: var(--accent); }

section {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.5rem;
}

.label {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
  margin-bottom: 0.75rem;
}

.occupancy-value {
  font-size: 5rem;
  font-weight: 700;
  line-height: 1.1;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.day-counts {
  display: flex;
  justify-content: center;
  gap: 3rem;
  margin-top: 1.25rem;
}

.day-counts div { display: flex; flex-direction: column; align-items: center; }
.count-value { font-size: 1.5rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.count-label { font-size: 0.75rem; color: var(--muted); margin-top: 0.15rem; }

#correction-form { display: flex; gap: 0.5rem; }

#correction-form input {
  flex: 1;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  padding: 0.5rem 0.75rem;
  font-size: 1rem;
}

#correction-form button {
  background: var(--accent);
  border: none;
  border-radius: 8px;
  color: #08231a;
  font-weight: 600;
  padding: 0.5rem 1.25rem;
  cursor: pointer;
}

#correction-form button:hover { filter: brightness(1.1); }
```

- [ ] **Step 4: Create `web/app.js`**

```javascript
const occupancyEl = document.getElementById("occupancy");
const todayInEl = document.getElementById("today-in");
const todayOutEl = document.getElementById("today-out");
const connectionEl = document.getElementById("connection");
const correctionForm = document.getElementById("correction-form");
const correctionInput = document.getElementById("correction-value");

let chart = null;

function setConnection(live) {
  connectionEl.classList.toggle("status--live", live);
  connectionEl.textContent = live ? "Live" : "Getrennt";
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.json();
}

function renderStatus(status) {
  occupancyEl.textContent = status.occupancy;
  todayInEl.textContent = status.today_in;
  todayOutEl.textContent = status.today_out;
}

function renderChart(stats) {
  const labels = stats.hours.map((h) => `${String(h.hour).padStart(2, "0")}`);
  const datasets = [
    {
      label: "Eintritte",
      data: stats.hours.map((h) => h.in),
      backgroundColor: "#4cc38a",
      borderRadius: 3,
    },
    {
      label: "Austritte",
      data: stats.hours.map((h) => h.out),
      backgroundColor: "#e5704c",
      borderRadius: 3,
    },
  ];
  if (chart) {
    chart.data = { labels, datasets };
    chart.update();
    return;
  }
  chart = new Chart(document.getElementById("hourly-chart"), {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      animation: false,
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: "#8b95a3", maxTicksLimit: 12 },
        },
        y: {
          beginAtZero: true,
          grid: { color: "#232a33" },
          ticks: { color: "#8b95a3", precision: 0 },
        },
      },
      plugins: { legend: { labels: { color: "#e6e9ee", boxWidth: 12 } } },
    },
  });
}

async function refresh() {
  try {
    const [status, stats] = await Promise.all([
      fetchJson("/api/status"),
      fetchJson("/api/stats/today"),
    ]);
    renderStatus(status);
    renderChart(stats);
  } catch (error) {
    console.error("refresh failed", error);
  }
}

function handleMessage(message) {
  if (typeof message.occupancy === "number") {
    occupancyEl.textContent = message.occupancy;
  }
  if (message.type === "count") refresh();
}

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${location.host}/ws`);
  ws.onopen = () => setConnection(true);
  ws.onclose = () => {
    setConnection(false);
    setTimeout(connectWebSocket, 3000);
  };
  ws.onmessage = (event) => handleMessage(JSON.parse(event.data));
}

correctionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = Number(correctionInput.value);
  if (!Number.isInteger(value) || value < 0) return;
  await fetch("/api/occupancy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  correctionInput.value = "";
});

refresh();
connectWebSocket();
setInterval(refresh, 60000);
```

- [ ] **Step 5: Verify in the browser**

Run: `COUNTER_SOURCE=sim .venv/bin/uvicorn api.main:app --port 8000`, open `http://localhost:8000`.
Expected: dark dashboard; "Live" indicator green; occupancy and today counters change every few seconds as the simulator generates crossings; the chart's current-hour bars grow; entering a number in the correction form updates the big number immediately.

- [ ] **Step 6: Run the full test suite**

Run: `.venv/bin/pytest`
Expected: all tests pass (frontend has no unit tests — no JS toolchain by design; the API test asserts index.html is served).

- [ ] **Step 7: Commit**

```bash
git add web/
git commit -m "feat: dark live dashboard with occupancy, day counts, hourly chart"
```

---

### Task 12: IMX500 camera source (`counter/source_imx500.py`)

Pi-only. `picamera2`/IMX500 imports happen lazily inside `frames()` — this file is never imported on dev machines (the factory imports it only for `COUNTER_SOURCE=imx500`). Cannot be unit-tested on dev; verified on the Pi after deploy.

**Files:**
- Create: `counter/source_imx500.py`

- [ ] **Step 1: Implement `counter/source_imx500.py`**

```python
import logging
from collections.abc import Iterator

from counter.source_base import Centroid

logger = logging.getLogger(__name__)


class Imx500Source:
    """Person centroids from the Sony IMX500 on-sensor MobileNet-SSD model.

    Only bounding-box metadata reaches the Pi; raw video never leaves the
    sensor. Model firmware upload takes several seconds at startup.
    """

    def __init__(self, model_path: str, confidence: float = 0.5, person_class_id: int = 0):
        self._model_path = model_path
        self._confidence = confidence
        self._person_class_id = person_class_id

    def frames(self) -> Iterator[list[Centroid]]:
        from picamera2 import Picamera2
        from picamera2.devices import IMX500

        imx500 = IMX500(self._model_path)
        picam2 = Picamera2(imx500.camera_num)
        config = picam2.create_preview_configuration(
            controls={"FrameRate": 30}, buffer_count=12
        )
        imx500.show_network_fw_progress_bar()
        picam2.start(config)
        input_width, input_height = imx500.get_input_size()
        logger.info("IMX500 started, model input %dx%d", input_width, input_height)
        try:
            while True:
                metadata = picam2.capture_metadata()
                outputs = imx500.get_outputs(metadata, add_batch=True)
                if outputs is None:
                    yield []
                    continue
                boxes, scores, classes = outputs[0][0], outputs[1][0], outputs[2][0]
                centroids: list[Centroid] = []
                for box, score, class_id in zip(boxes, scores, classes, strict=False):
                    if int(class_id) != self._person_class_id or score < self._confidence:
                        continue
                    y0, x0, y1, x1 = box
                    centroids.append(
                        (
                            float((x0 + x1) / 2 / input_width),
                            float((y0 + y1) / 2 / input_height),
                        )
                    )
                yield centroids
        finally:
            picam2.stop()
```

- [ ] **Step 2: Verify dev machine stays clean**

Run: `.venv/bin/pytest && .venv/bin/ruff check .`
Expected: all tests still pass, no lint errors — and no `picamera2` import error anywhere (lazy import only).

- [ ] **Step 3: Note for Pi verification (do this during Task 13 deployment)**

On the Pi, compare the box-parsing order (`y0, x0, y1, x1` and the division by input size) against the working prototype `personenzaehler.py`. If the prototype parses differently (e.g. already-normalized boxes or `x0, y0, x1, y1`), adapt `frames()` to match the prototype — it is the ground truth.

- [ ] **Step 4: Commit**

```bash
git add counter/source_imx500.py
git commit -m "feat: IMX500 on-sensor detection source (Pi only)"
```

---

### Task 13: Deployment (systemd + deploy script) and README

**Files:**
- Create: `deploy/raumzaehler.service`, `deploy/deploy.sh`, `README.md`

- [ ] **Step 1: Create `deploy/raumzaehler.service`**

```ini
[Unit]
Description=Raumzaehler people counter
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/raumzaehler
Environment=COUNTER_SOURCE=imx500
EnvironmentFile=-/home/pi/raumzaehler/.env
ExecStart=/home/pi/raumzaehler/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
# IMX500 firmware upload takes several seconds at startup
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Create `deploy/deploy.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

PI_HOST="${PI_HOST:-pi@raumzaehler.local}"
TARGET_DIR="/home/pi/raumzaehler"

rsync -av --delete \
  --exclude '.git' --exclude '.venv' --exclude 'data' \
  --exclude '__pycache__' --exclude '.pytest_cache' --exclude '.ruff_cache' \
  --exclude '.claude' --exclude 'docs' \
  ./ "$PI_HOST:$TARGET_DIR/"

# --system-site-packages: picamera2 comes from apt and must stay visible
ssh "$PI_HOST" "cd $TARGET_DIR \
  && python3 -m venv --system-site-packages .venv \
  && .venv/bin/pip install -r requirements.txt \
  && sudo systemctl restart raumzaehler"

echo "Deployed to $PI_HOST"
```

Run: `chmod +x deploy/deploy.sh`

- [ ] **Step 3: Create `README.md`**

```markdown
# Raumzaehler

Edge people counter on a Raspberry Pi 4 with the Raspberry Pi AI Camera
(Sony IMX500). Person detection runs on the camera sensor; the Pi receives
only bounding-box metadata and does tracking, line-crossing counting,
SQLite storage, and serves a live web dashboard.

## Development (no camera needed)

    python3 -m venv .venv
    .venv/bin/pip install -r requirements-dev.txt
    COUNTER_SOURCE=sim .venv/bin/uvicorn api.main:app --reload

Dashboard: http://localhost:8000 — the simulator generates synthetic
crossings. Tests: `.venv/bin/pytest` · Lint: `.venv/bin/ruff check .`

## Configuration

Env vars / `.env` (see `.env.example`): `COUNTER_SOURCE` (`imx500`|`sim`),
`SENSOR_ID`, `DB_PATH`, `TIMEZONE`, `INVERT_DIRECTION` (flip entry/exit if
the camera is mounted the other way), `NIGHTLY_RESET_TIME`, `LINE_POSITION`,
`LINE_AXIS`.

## Deployment (Raspberry Pi, Bookworm)

One-time on the Pi:

    sudo apt install -y python3-picamera2 imx500-all
    sudo cp deploy/raumzaehler.service /etc/systemd/system/
    sudo systemctl enable raumzaehler

Then from the dev machine: `./deploy/deploy.sh` (override target with
`PI_HOST=pi@<host>`).
```

- [ ] **Step 4: Full verification**

Run: `.venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all pass. (If `ruff format --check` complains, run `.venv/bin/ruff format .` and re-run tests.)

- [ ] **Step 5: Commit**

```bash
git add deploy/ README.md
git commit -m "feat: systemd unit, deploy script, README"
```

- [ ] **Step 6: Deploy to the Pi and verify on-site (requires the Pi to be reachable)**

```bash
./deploy/deploy.sh
```
Expected: service restarts; dashboard reachable at `http://raumzaehler.local:8000`; walking through the door changes the count in the right direction (if inverted, set `INVERT_DIRECTION=true` in the Pi's `.env`). Verify Task 12 Step 3 (prototype comparison) now.

---

## Verification Checklist (end of Version 1)

- [ ] `pytest` green, `ruff check .` clean
- [ ] Dev: simulator dashboard live-updates (numbers + chart) over WebSocket
- [ ] Correction form writes a `correction` event and broadcasts to all clients
- [ ] Restarting the server restores occupancy (replay since last 04:00 boundary)
- [ ] Pi: real crossings counted in the correct direction; `INVERT_DIRECTION` honored
- [ ] Service survives reboot (`systemctl enable` + `Restart=on-failure`)
