from api.routes import _mjpeg_frames
from counter.preview import FrameBuffer
from counter.source_imx500 import Imx500Source


def test_frame_buffer_starts_empty():
    seq, frame = FrameBuffer().wait_for(last_seq=0, timeout=0.01)
    assert seq == 0
    assert frame is None


def test_frame_buffer_set_increments_sequence_and_returns_frame():
    buffer = FrameBuffer()
    buffer.set(b"jpeg-1")
    seq, frame = buffer.wait_for(last_seq=0, timeout=0.01)
    assert seq == 1
    assert frame == b"jpeg-1"


def test_frame_buffer_wait_returns_immediately_for_unseen_frame():
    buffer = FrameBuffer()
    buffer.set(b"a")
    buffer.set(b"b")
    # consumer has seen seq 1, the latest is 2 -> returns without blocking
    seq, frame = buffer.wait_for(last_seq=1, timeout=5.0)
    assert seq == 2
    assert frame == b"b"


def test_frame_buffer_close_sets_flag():
    buffer = FrameBuffer()
    assert not buffer.closed
    buffer.close()
    assert buffer.closed


def test_mjpeg_frames_emits_multipart_jpeg():
    buffer = FrameBuffer()
    buffer.set(b"JPEGDATA")
    chunk = next(_mjpeg_frames(buffer))
    assert chunk.startswith(b"--frame\r\n")
    assert b"Content-Type: image/jpeg" in chunk
    assert b"Content-Length: 8" in chunk
    assert chunk.endswith(b"JPEGDATA\r\n")


def test_mjpeg_frames_stops_when_buffer_closed():
    buffer = FrameBuffer()
    buffer.close()
    assert list(_mjpeg_frames(buffer)) == []


class _FakeImx500:
    def __init__(self, outputs):
        self._outputs = outputs

    def get_outputs(self, metadata, add_batch=True):
        return self._outputs


def test_centroids_normalizes_box_centers():
    # one box [y0, x0, y1, x1] -> center (160, 80) in a 320x320 input
    outputs = ([[[0.0, 0.0, 160.0, 320.0]]], [[0.9]], [[0]])
    source = Imx500Source("model.rpk", confidence=0.5)
    assert source._centroids(_FakeImx500(outputs), None, 320, 320) == [(0.5, 0.25)]


def test_centroids_filters_low_score_and_non_person():
    # box 0: person but score below threshold; box 1: high score but wrong class
    outputs = ([[[0, 0, 320, 320], [0, 0, 320, 320]]], [[0.1, 0.9]], [[0, 5]])
    source = Imx500Source("model.rpk", confidence=0.5, person_class_id=0)
    assert source._centroids(_FakeImx500(outputs), None, 320, 320) == []


def test_centroids_returns_empty_when_no_outputs():
    source = Imx500Source("model.rpk")
    assert source._centroids(_FakeImx500(None), None, 320, 320) == []
