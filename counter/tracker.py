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
