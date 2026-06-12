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


def test_service_survives_failing_callback(tmp_path):
    store = EventStore(tmp_path / "test.db")

    def failing_callback(event):
        raise RuntimeError("broadcast broken")

    service = CounterService(
        source=SimulatedSource(frame_interval=0, seed=42, max_crossings=3),
        tracker=CentroidTracker(),
        line_counter=LineCrossingCounter(),
        occupancy=OccupancyState(),
        store=store,
        sensor_id="test-sensor",
        on_event=failing_callback,
    )
    service.run()  # must not raise
    counts = store.counts_between(*ALL_TIME)
    assert counts["in"] + counts["out"] == 3
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
