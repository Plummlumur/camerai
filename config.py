from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    counter_source: str = "sim"
    sensor_id: str = "raum-1"
    db_path: str = "data/raumzaehler.db"
    timezone: str = "Europe/Vienna"
    invert_direction: bool = False
    nightly_reset_time: str = "04:00"
    line_position: float = 0.5
    line_axis: str = "x"
    imx500_model_path: str = (
        "/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk"
    )
    detection_confidence: float = 0.5
    # Camera preview (MJPEG) for setup/calibration. Off by default: the
    # privacy-by-design baseline keeps raw video on the sensor. Enabling this
    # streams the camera image (with the counting line overlaid) to the
    # dashboard. Only effective with COUNTER_SOURCE=imx500.
    camera_preview_enabled: bool = False
    camera_preview_fps: int = Field(default=10, ge=1, le=60)
    camera_preview_quality: int = Field(default=70, ge=1, le=95)


@lru_cache
def get_settings() -> Settings:
    return Settings()
