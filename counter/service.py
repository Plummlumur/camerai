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
