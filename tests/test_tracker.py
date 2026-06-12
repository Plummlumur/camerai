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
