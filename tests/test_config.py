from config import Settings


def test_defaults():
    settings = Settings(_env_file=None)
    assert settings.counter_source == "sim"
    assert settings.sensor_id == "raum-1"
    assert settings.timezone == "Europe/Vienna"
    assert settings.invert_direction is False
    assert settings.nightly_reset_time == "04:00"
    assert settings.line_position == 0.5
    assert settings.line_axis == "x"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("COUNTER_SOURCE", "imx500")
    monkeypatch.setenv("INVERT_DIRECTION", "true")
    settings = Settings(_env_file=None)
    assert settings.counter_source == "imx500"
    assert settings.invert_direction is True
