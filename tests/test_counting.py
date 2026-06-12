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
