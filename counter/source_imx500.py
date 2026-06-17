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
                            self._publish_frame(request, imx500, metadata)
                            last_encode = now
                    finally:
                        request.release()
                yield self._centroids(imx500, metadata)
        finally:
            picam2.stop()

    def _person_detections(self, imx500, metadata) -> list:
        """Raw ``[y0, x0, y1, x1]`` boxes of persons above the confidence threshold.

        Boxes are already normalized to 0..1 of the frame (this model carries no
        ``bbox_normalization``/``bbox_order`` intrinsics, so picamera2 returns the
        SSD post-processed coordinates as-is). They are shared by centroid
        extraction and preview box drawing so both reflect the same detections.
        """
        outputs = imx500.get_outputs(metadata, add_batch=True)
        if outputs is None:
            return []
        boxes, scores, classes = outputs[0][0], outputs[1][0], outputs[2][0]
        return [
            box
            for box, score, class_id in zip(boxes, scores, classes, strict=False)
            if int(class_id) == self._person_class_id and score >= self._confidence
        ]

    def _centroids(self, imx500, metadata) -> list[Centroid]:
        centroids: list[Centroid] = []
        for box in self._person_detections(imx500, metadata):
            y0, x0, y1, x1 = box
            cx = min(max((x0 + x1) / 2, 0.0), 1.0)
            cy = min(max((y0 + y1) / 2, 0.0), 1.0)
            centroids.append((float(cx), float(cy)))
        return centroids

    @staticmethod
    def _box_to_pixels(box, img_width, img_height) -> tuple:
        """Map a normalized ``[y0, x0, y1, x1]`` detection box to image pixels.

        Boxes are 0..1 of the frame, so they scale directly to the preview image
        size — matching the normalization the counter applies to centroids, so
        drawn boxes/centroids align with the counting line shown over the image.
        """
        y0, x0, y1, x1 = box
        return (
            x0 * img_width,
            y0 * img_height,
            x1 * img_width,
            y1 * img_height,
        )

    def _publish_frame(self, request, imx500, metadata) -> None:
        from PIL import ImageDraw

        image = request.make_image("main")  # PIL image, format conversion handled
        draw = ImageDraw.Draw(image)
        img_width, img_height = image.size
        for box in self._person_detections(imx500, metadata):
            left, top, right, bottom = self._box_to_pixels(box, img_width, img_height)
            draw.rectangle((left, top, right, bottom), outline=(76, 195, 138), width=2)
            cx, cy = (left + right) / 2, (top + bottom) / 2
            draw.ellipse(
                (cx - 4, cy - 4, cx + 4, cy + 4), fill=(255, 255, 255), outline=(20, 20, 20)
            )
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=self._preview_quality)
        self._frame_buffer.set(buf.getvalue())
