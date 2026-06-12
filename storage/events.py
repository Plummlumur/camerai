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
        self._conn.commit()
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
                count = max(0, value if value is not None else 0)
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
