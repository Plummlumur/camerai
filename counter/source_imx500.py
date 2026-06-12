import logging
from collections.abc import Iterator

from counter.source_base import Centroid

logger = logging.getLogger(__name__)


class Imx500Source:
    """Person centroids from the Sony IMX500 on-sensor MobileNet-SSD model.

    Only bounding-box metadata reaches the Pi; raw video never leaves the
    sensor. Model firmware upload takes several seconds at startup.
    """

    def __init__(self, model_path: str, confidence: float = 0.5, person_class_id: int = 0):
        self._model_path = model_path
        self._confidence = confidence
        self._person_class_id = person_class_id

    def frames(self) -> Iterator[list[Centroid]]:
        from picamera2 import Picamera2
        from picamera2.devices import IMX500

        imx500 = IMX500(self._model_path)
        picam2 = Picamera2(imx500.camera_num)
        config = picam2.create_preview_configuration(
            controls={"FrameRate": 30}, buffer_count=12
        )
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
