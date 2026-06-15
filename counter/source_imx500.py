import logging
import time
from collections.abc import Iterator

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
    """

    def __init__(
        self,
        model_path: str,
        confidence: float = 0.5,
        person_class_id: int = 0,
        retry_interval: float = 5.0,
        max_retry_interval: float = 60.0,
    ):
        self._model_path = model_path
        self._confidence = confidence
        self._person_class_id = person_class_id
        self._retry_interval = retry_interval
        self._max_retry_interval = max_retry_interval

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
        try:
            while True:
                metadata = picam2.capture_metadata()
                outputs = imx500.get_outputs(metadata, add_batch=True)
                if outputs is None:
                    yield []
                    continue
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
                yield centroids
        finally:
            picam2.stop()
