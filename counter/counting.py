import threading
from enum import StrEnum

Centroid = tuple[float, float]


class Direction(StrEnum):
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
