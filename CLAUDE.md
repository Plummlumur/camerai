# Raumzaehler — Edge People Counter

Edge device that counts people entering/leaving a room and serves a live web
dashboard. Runs on a Raspberry Pi 4 with the Raspberry Pi AI Camera (Sony
IMX500, SC1174). Person detection (MobileNet-SSD) runs **on the camera
sensor**; the Pi only receives bounding-box metadata and performs tracking,
line-crossing counting, storage, and the dashboard. Designed as one unit of a
future multi-site fleet reporting to a central Linux server via MQTT.

## Tech Stack

- Python 3.11+ (Raspberry Pi OS Bookworm on target)
- `picamera2` + IMX500 support (`imx500-all` apt package) — **target only**
- FastAPI + uvicorn, WebSocket for live updates
- SQLite (stdlib `sqlite3`), WAL mode
- Frontend: static HTML/JS + Chart.js (served by FastAPI, no build step)
- `paho-mqtt` for future central reporting (module present, disabled by default)
- pytest, ruff

## Project Structure

```
raumzaehler/
├── counter/          # Detection, tracking, counting logic
│   ├── source_imx500.py   # Real camera (imports picamera2 — Pi only)
│   ├── source_sim.py      # Simulator: synthetic crossings for dev machines
│   ├── tracker.py         # Centroid tracker
│   └── counting.py        # Line-crossing logic, occupancy state
├── storage/          # SQLite event log + aggregate queries
├── api/              # FastAPI app, REST + WebSocket, auth hook
├── web/              # Static dashboard (index.html, app.js, Chart.js)
├── mqtt/             # MQTT publisher (future central server)
├── deploy/           # systemd unit, install/deploy scripts
└── tests/
```

## Development Commands

- Dev server (simulator, no camera needed): `COUNTER_SOURCE=sim uvicorn api.main:app --reload`
- Test: `pytest`
- Lint: `ruff check .`
- Format: `ruff format .`
- Deploy to Pi: `./deploy/deploy.sh` (rsync to Pi, restart systemd service `raumzaehler`)

Development happens on a Linux/desktop machine **without camera hardware**.
All code except `counter/source_imx500.py` must run on the dev machine.

## Code Conventions

- `picamera2`/IMX500 imports only inside `counter/source_imx500.py`, lazily.
  Never import them at module level anywhere else — dev machines lack them.
- Detection sources implement a common `DetectionSource` interface (yields
  normalized centroids per frame). Selection via `COUNTER_SOURCE` env var
  (`imx500` | `sim`). A future Hailo-8 source plugs in the same way.
- All timestamps stored in UTC (ISO 8601); aggregation/display in the
  configured local timezone (default `Europe/Vienna`).
- Configuration via a single `config.py` reading env vars / `.env`; no
  hardcoded values in business logic.
- snake_case throughout; type hints on public functions.

## Architecture Decisions

- **On-sensor inference (IMX500)**: raw video never leaves the sensor — only
  metadata reaches the Pi. Privacy by design, minimal CPU load. The installed
  Hailo-8 AI HAT+ is a deliberate reserve; do not add Hailo code paths unless
  asked.
- **Event sourcing**: every entry/exit is a row in `events(id, ts_utc,
  direction, sensor_id)`. Day/week/month totals are SQL aggregations, never
  separately maintained counters. Week = ISO week.
- **Occupancy** is in-memory state, restored on startup by replaying today's
  events; never allowed below 0. Nightly reset to 0 at a configurable time
  (default 04:00 local) to clear accumulated counting drift.
- **Manual correction**: dashboard has a control to set the current occupancy
  (POST endpoint, writes a `correction` event for auditability).
- **Live updates**: every counting event is broadcast over WebSocket to all
  connected dashboard clients; REST endpoints exist for the same data.
- **Multi-site ready**: every event carries `sensor_id` (config). MQTT
  publisher mirrors events to `counter/<sensor_id>/events` when enabled —
  off by default, must never block or crash the counting loop.
- **Auth**: FastAPI dependency hook in place for all routes, currently a
  no-op. Wire real login later without restructuring.

## Domain Knowledge

- **Eintritt / Austritt**: entry / exit event (German UI labels).
- **Belegung**: current occupancy (people in the room right now).
- **Zaehllinie**: virtual line in the image; crossing direction determines
  entry vs. exit.
- **Drift**: accumulated occupancy error from missed/double counts; mitigated
  by nightly reset and manual correction.

## Agent Setup

### Available Subagents

- **code-reviewer**: invoke after implementing or significantly changing a
  feature, before committing. Read-only review for correctness, asyncio
  pitfalls, and the hardware-import rule.
- **test-runner**: invoke to run the test suite and get a structured failure
  report, e.g. after refactors or before deploy.

## Known Issues / Gotchas

- Direction mapping (which crossing direction is "entry") depends on physical
  camera orientation. Provide config flag `INVERT_DIRECTION`; never hardcode.
- IMX500 model firmware upload takes several seconds at startup — the service
  must tolerate this delay; dashboard shows "starting" state.
- Detection model: `/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk`,
  COCO class 0 = person.
- SQLite is accessed from the counting loop and API: use WAL mode and a single
  writer; keep write transactions short.
- A working prototype script (`personenzaehler.py`) exists with IMX500
  metadata parsing, centroid tracker, and line-crossing logic — reuse its
  logic when building `counter/`.
