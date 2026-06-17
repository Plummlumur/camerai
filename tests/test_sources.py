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


def test_factory_accepts_frame_buffer_for_non_camera_sources():
    from counter.preview import FrameBuffer

    source = build_source(Settings(_env_file=None, counter_source="sim"), FrameBuffer())
    assert isinstance(source, SimulatedSource)


def test_factory_rejects_unknown_source():
    with pytest.raises(ValueError, match="unknown COUNTER_SOURCE"):
        build_source(Settings(_env_file=None, counter_source="kaputt"))
