from collections.abc import Iterator
from typing import Protocol

Centroid = tuple[float, float]


class DetectionSource(Protocol):
    def frames(self) -> Iterator[list[Centroid]]:
        """Yield one list of normalized (x, y) person centroids per frame."""
        ...
