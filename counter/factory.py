from config import Settings
from counter.source_base import DetectionSource
from counter.source_sim import NullSource, SimulatedSource


def build_source(settings: Settings) -> DetectionSource:
    if settings.counter_source == "sim":
        return SimulatedSource()
    if settings.counter_source == "none":
        return NullSource()
    if settings.counter_source == "imx500":
        from counter.source_imx500 import Imx500Source

        return Imx500Source(
            model_path=settings.imx500_model_path,
            confidence=settings.detection_confidence,
        )
    raise ValueError(f"unknown COUNTER_SOURCE: {settings.counter_source!r}")
