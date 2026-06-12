# Raumzaehler

Edge people counter on a Raspberry Pi 4 with the Raspberry Pi AI Camera
(Sony IMX500). Person detection runs on the camera sensor; the Pi receives
only bounding-box metadata and does tracking, line-crossing counting,
SQLite storage, and serves a live web dashboard.

## Development (no camera needed)

    python3 -m venv .venv
    .venv/bin/pip install -r requirements-dev.txt
    COUNTER_SOURCE=sim .venv/bin/uvicorn api.main:app --reload

Dashboard: http://localhost:8000 — the simulator generates synthetic
crossings. Tests: `.venv/bin/pytest` · Lint: `.venv/bin/ruff check .`

## Configuration

Env vars / `.env` (see `.env.example`): `COUNTER_SOURCE` (`imx500`|`sim`),
`SENSOR_ID`, `DB_PATH`, `TIMEZONE`, `INVERT_DIRECTION` (flip entry/exit if
the camera is mounted the other way), `NIGHTLY_RESET_TIME`, `LINE_POSITION`,
`LINE_AXIS`.

## Deployment (Raspberry Pi, Bookworm)

One-time on the Pi:

    sudo apt install -y python3-picamera2 imx500-all
    sudo cp deploy/raumzaehler.service /etc/systemd/system/
    sudo systemctl enable raumzaehler

Then from the dev machine: `./deploy/deploy.sh` (override target with
`PI_HOST=pi@<host>`).

Note: the systemd unit sets `COUNTER_SOURCE=imx500`, but a `.env` file on
the Pi overrides it — do not copy `.env.example` (which sets `sim`) to the
Pi unchanged.
