import threading


class FrameBuffer:
    """Thread-safe holder for the latest JPEG camera frame.

    The camera capture thread (writer) calls :meth:`set` with each encoded
    frame; HTTP stream consumers call :meth:`wait_for` to block until a frame
    newer than the one they last saw is available. A monotonically increasing
    sequence number lets a consumer skip frames it has already sent without
    busy-waiting.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._frame: bytes | None = None
        self._seq = 0
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def set(self, jpeg: bytes) -> None:
        with self._cond:
            self._frame = jpeg
            self._seq += 1
            self._cond.notify_all()

    def close(self) -> None:
        """Wake all waiters so streams can shut down on service stop."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def wait_for(self, last_seq: int, timeout: float = 5.0) -> tuple[int, bytes | None]:
        """Return ``(seq, frame)`` once a frame newer than ``last_seq`` exists.

        Blocks up to ``timeout`` seconds; on timeout returns the current
        (possibly unchanged) state so the caller can re-check ``closed``.
        """
        with self._cond:
            if self._seq == last_seq and not self._closed:
                self._cond.wait(timeout)
            return self._seq, self._frame
