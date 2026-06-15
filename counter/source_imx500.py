import io
import logging
import time
from collections.abc import Iterator

from counter.preview import FrameBuffer
from counter.source_base import Centroid

logger = logging.getLogger(__name__)


class Imx500Source:
    """Person centroids from the Sony IMX500 on-sensor MobileNet-SSD model.

    Only bounding-box metadata reaches the Pi; raw video never leaves the
    sensor. Model firmware upload takes several seconds at startup.

    A camera error (e.g. the sensor briefly busy at startup, or a transient
    runtime failure) must not permanently kill the counting loop: ``frames``
    catches it, emits an empty frame as a heartbeat, and retries with
    exponential backoff instead of letting the exception propagate.

    If a ``frame_buffer`` is supplied, each capture also yields a JPEG image
    (throttled to ``preview_fps``) for the dashboard MJPEG stream. The camera
    can only be held by one process, so the preview image is pulled from this
    same capture loop rather than a second camera handle.
    """

    def __init__(
        self,
        model_path: str,
        confidence: float = 0.5,
        person_class_id: int = 0,
        retry_interval: float = 5.0,
        max_retry_interval: float = 60.0,
        frame_buffer: FrameBuffer | None = None,
        preview_fps: int = 10,
        preview_quality: int = 70,
    ):
        self._model_path = model_path
        self._confidence = confidence
        self._person_class_id = person_class_id
        self._retry_interval = retry_interval
        self._max_retry_interval = max_retry_interval
        self._frame_buffer = frame_buffer
        self._preview_fps = preview_fps
        self._preview_quality = preview_quality

    def frames(self) -> Iterator[list[Centroid]]:
        from picamera2 import Picamera2
        from picamera2.devices import IMX500

        backoff = self._retry_interval
        while True:
            try:
                for centroids in self._stream(Picamera2, IMX500):
                    backoff = self._retry_interval  # healthy frame -> reset backoff
                    yield centroids
            except Exception:
                logger.exception("IMX500 camera error; recovering in %.0fs", backoff)
                yield []  # heartbeat so the consuming loop stays alive
                time.sleep(backoff)
                backoff = min(backoff * 2, self._max_retry_interval)

    def _stream(self, picamera2_cls, imx500_cls) -> Iterator[list[Centroid]]:
        imx500 = imx500_cls(self._model_path)
        picam2 = picamera2_cls(imx500.camera_num)
        config = picam2.create_preview_configuration(controls={"FrameRate": 30}, buffer_count=12)
        imx500.show_network_fw_progress_bar()
        picam2.start(config)
        input_width, input_height = imx500.get_input_size()
        logger.info("IMX500 started, model input %dx%d", input_width, input_height)
        encode_interval = (
            1.0 / self._preview_fps
            if self._frame_buffer is not None and self._preview_fps > 0
            else 0.0
        )
        last_encode = 0.0
        try:
            while True:
                if self._frame_buffer is None:
                    metadata = picam2.capture_metadata()
                else:
                    # capture_request gives metadata and image from one frame.
                    request = picam2.capture_request()
                    try:
                        metadata = request.get_metadata()
                        now = time.monotonic()
                        if encode_interval and now - last_encode >= encode_interval:
                            self._publish_frame(request)
                            last_encode = now
                    finally:
                        request.release()
                yield self._centroids(imx500, metadata, input_width, input_height)
        finally:
            picam2.stop()

    def _centroids(self, imx500, metadata, input_width, input_height) -> list[Centroid]:
        outputs = imx500.get_outputs(metadata, add_batch=True)
        if outputs is None:
            return []
        boxes, scores, classes = outputs[0][0], outputs[1][0], outputs[2][0]
        centroids: list[Centroid] = []
        for box, score, class_id in zip(boxes, scores, classes, strict=False):
            if int(class_id) != self._person_class_id or score < self._confidence:
                continue
            y0, x0, y1, x1 = box
            centroids.append(
                (
                    float((x0 + x1) / 2 / input_width),
                    float((y0 + y1) / 2 / input_height),
                )
            )
        return centroids

    def _publish_frame(self, request) -> None:
        image = request.make_image("main")  # PIL image, format conversion handled
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=self._preview_quality)
        self._frame_buffer.set(buf.getvalue())
