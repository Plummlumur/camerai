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
