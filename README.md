# Raumzaehler — Edge People Counter

Raumzaehler counts people entering and leaving a room and serves a live web
dashboard. It runs on a Raspberry Pi 4 with the Raspberry Pi AI Camera (Sony
IMX500). Person detection happens **on the camera sensor** — the Pi only ever
receives bounding-box metadata, never the video stream. The Pi does tracking,
line-crossing counting, SQLite storage, and serves the dashboard.

This is Version 1: a fully functional single device. It is built to become one
unit of a future multi-site fleet that reports to a central server via MQTT
(Version 2, not yet implemented).

---

## Hardware

| Component | Role |
|-----------|------|
| Raspberry Pi 4 | Host: tracking, counting, storage, dashboard |
| Raspberry Pi AI Camera (Sony IMX500, SC1174) | On-sensor person detection |
| Hailo-8 AI HAT+ | Installed reserve — **deliberately unused** in V1 |

### On-sensor inference (IMX500)

The Sony IMX500 is an intelligent vision sensor: a neural-network accelerator
sits on the same silicon as the image sensor. A MobileNet-SSD detection model
(`imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk`, COCO class `0` =
person) is uploaded to the sensor at startup and runs there. The Pi receives
only the resulting bounding boxes as metadata alongside each frame.

This has two consequences that shaped the whole design:

- **Privacy by design.** Raw video never leaves the sensor. There is no frame
  buffer to leak, store, or stream — only anonymous coordinates reach the Pi.
- **Minimal CPU load.** Inference (the expensive part) is offloaded to the
  sensor. The Pi only does lightweight bookkeeping, so a Pi 4 is plenty.

### Notes / gotchas

- **Firmware upload delay.** Uploading the model to the IMX500 takes several
  seconds at startup. The service tolerates this (`TimeoutStartSec=120` in the
  systemd unit) and the dashboard shows a "starting" state until the first
  detection arrives.
- **Camera orientation determines direction.** Which crossing direction counts
  as an *entry* depends on how the camera is physically mounted. This is never
  hardcoded — flip it with the `INVERT_DIRECTION` config flag on site.
- **Hailo-8 is reserve.** The AI HAT+ is installed but intentionally has no code
  path in V1. Do not add one unless explicitly required; a future Hailo source
  would plug into the same detection-source interface as the IMX500.

---

## Software

### Tech stack

- **Python 3.11+** (Raspberry Pi OS Bookworm on target; developed on 3.14)
- **picamera2 + IMX500** support (`imx500-all` apt package) — target only
- **FastAPI + uvicorn**, WebSocket for live updates
- **SQLite** (stdlib `sqlite3`, WAL mode)
- **Frontend**: static HTML/CSS/JS + Chart.js (vendored, no build step)
- **paho-mqtt** for future central reporting (off by default)
- **pytest**, **ruff** for tests and linting

### The pipeline

Each frame flows through five stages:

```
IMX500 sensor ─ bounding boxes ─▶ DetectionSource ─▶ CentroidTracker
                                                          │
                                                   stable per-person IDs
                                                          ▼
   Dashboard ◀─ WebSocket/REST ◀─ EventStore ◀─ LineCrossingCounter
   (live)        (broadcast)       (SQLite)       (entry / exit)
```

1. **DetectionSource** yields normalized person centroids (x, y in `0..1`) per
   frame. It is an interface with pluggable implementations selected by the
   `COUNTER_SOURCE` env var:
   - `imx500` — the real camera (`counter/source_imx500.py`, Pi only)
   - `sim` — a simulator generating synthetic crossings (dev machines)
   - `none` — a null source (no detections)
2. **CentroidTracker** (`counter/tracker.py`) matches detections frame-to-frame
   by greedy nearest-neighbour, assigning each person a stable ID that is never
   reused. It tolerates a few missed frames before dropping a track.
3. **LineCrossingCounter** (`counter/counting.py`) watches each tracked centroid
   relative to a virtual line (the *Zaehllinie*). When a centroid flips from one
   side to the other, that is an entry or an exit (subject to `INVERT_DIRECTION`).
4. **EventStore** (`storage/events.py`) appends one row per crossing.
5. **WebSocketHub / REST** push the update to every connected dashboard.

`CounterService` (`counter/service.py`) wires the pipeline together and runs the
blocking detection loop in a daemon thread. Persistence and broadcast are
wrapped in `try/except` so a storage or network hiccup can never kill the
counting loop.

### Event sourcing & occupancy

The single source of truth is an append-only event log:

```sql
events(id, ts_utc, direction, value, sensor_id)
--   direction ∈ ('in', 'out', 'correction')
```

- **Every entry/exit is a row.** Day/week/month totals are *always* SQL
  aggregations over this table — never separately maintained counters that could
  drift out of sync. (Week = ISO week.)
- **Occupancy** (*Belegung*, people currently in the room) is in-memory state.
  On startup it is restored by replaying every event since the last nightly-reset
  boundary. It is clamped to never go below 0.
- **Nightly reset.** At a configurable local time (default 04:00) occupancy is
  reset to 0. This clears accumulated *drift* from missed or double counts.
- **Manual correction.** The dashboard can set the current occupancy directly.
  This writes an auditable `correction` event (storing the new value) rather than
  silently mutating state.

### Time handling

All timestamps are stored in **UTC** (ISO 8601). Aggregation and display happen
in the configured local timezone (default `Europe/Vienna`). The helpers in
`timeutils.py` convert between the two and compute day boundaries and the
next-reset moment.

### API

REST endpoints (all under `/api`, all behind a — currently no-op — auth hook):

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/api/status` | Current occupancy + today's in/out totals |
| `GET`  | `/api/stats/today` | 24 hourly buckets for today |
| `GET`  | `/api/stats/history?days=N` | Daily totals (N bounded 1–366) |
| `POST` | `/api/occupancy` | Manual correction (`{"value": N}`, N ≥ 0) |
| `WS`   | `/ws` | Live event stream broadcast to all clients |

Every counting event and every correction is broadcast over the WebSocket so all
open dashboards update instantly; the REST endpoints expose the same data for
initial load and reconnection.

### Dashboard

`web/` is a static dark-themed dashboard served directly by FastAPI — no build
step. It shows the current *Belegung*, today's *Eintritte* / *Austritte* as big
numbers, and an hourly bar chart (Chart.js, vendored under `web/vendor/`). It
connects to `/ws` for live updates and offers a correction form. All dynamic
text is rendered via `textContent` (no HTML injection).

### Multi-site readiness (Version 2 hooks)

These are wired in but inert in V1, so V2 needs no restructuring:

- **`sensor_id`** is stamped on every event (config).
- An **MQTT publisher** module is present to mirror events to
  `counter/<sensor_id>/events`. It is disabled by default and, when enabled,
  must never block or crash the counting loop.
- A FastAPI **auth dependency** guards every route — currently a no-op, ready to
  hold real login later.

---

## Project structure

```
raumzaehler/
├── config.py         # All settings (pydantic-settings, env / .env)
├── timeutils.py      # UTC ⇄ local helpers, day bounds, reset timing
├── counter/          # Detection, tracking, counting
│   ├── source_base.py     # DetectionSource interface + null source
│   ├── source_sim.py      # Simulator (dev machines, no camera)
│   ├── source_imx500.py   # Real camera (lazy picamera2 import — Pi only)
│   ├── factory.py         # build_source() — selects source by config
│   ├── tracker.py         # Centroid tracker
│   ├── counting.py        # Line-crossing logic + occupancy state
│   └── service.py         # Pipeline glue, runs the detection loop
├── storage/          # SQLite event log + aggregate queries
│   └── events.py
├── api/              # FastAPI app
│   ├── main.py            # App factory, lifespan, /ws, static mount
│   ├── routes.py          # REST endpoints
│   ├── hub.py             # WebSocket connection hub
│   └── auth.py            # Auth dependency (no-op placeholder)
├── web/              # Static dashboard (index.html, app.js, style.css, Chart.js)
├── deploy/           # systemd unit + deploy.sh
└── tests/            # pytest suite
```

### Code conventions

- **Hardware imports are isolated.** `picamera2` / IMX500 are imported only
  inside `counter/source_imx500.py`, and lazily (inside the frame loop). Dev
  machines lack these packages, so every other module must import cleanly without
  them.
- Detection sources implement one common interface; a future Hailo-8 source plugs
  in the same way.
- Configuration lives in a single `config.py`; no hardcoded values in business
  logic.
- `snake_case` throughout, type hints on public functions, English identifiers.

---

## Development (no camera needed)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
COUNTER_SOURCE=sim .venv/bin/uvicorn api.main:app --reload
```

Dashboard: <http://localhost:8000> — the simulator generates synthetic
crossings, so the whole stack runs on any machine.

```bash
.venv/bin/pytest          # tests
.venv/bin/ruff check .    # lint
.venv/bin/ruff format .   # format
```

## Configuration

Set via environment variables or a `.env` file (see `.env.example`):

| Variable | Default | Meaning |
|----------|---------|---------|
| `COUNTER_SOURCE` | `sim` | `imx500` \| `sim` \| `none` |
| `SENSOR_ID` | `raum-1` | Stamped on every event (multi-site) |
| `DB_PATH` | `data/raumzaehler.db` | SQLite database file |
| `TIMEZONE` | `Europe/Vienna` | Local tz for aggregation/display |
| `INVERT_DIRECTION` | `false` | Flip entry/exit (camera mounting) |
| `NIGHTLY_RESET_TIME` | `04:00` | Local time to reset occupancy to 0 |
| `LINE_POSITION` | `0.5` | Counting line position (0..1) |
| `LINE_AXIS` | `x` | Axis the line crosses (`x` \| `y`) |
| `IMX500_MODEL_PATH` | `/usr/share/imx500-models/...ssd_mobilenetv2...rpk` | Detection model |
| `DETECTION_CONFIDENCE` | `0.5` | Minimum detection score |

## Deployment (Raspberry Pi, Bookworm)

One-time on the Pi:

```bash
sudo apt install -y python3-picamera2 imx500-all python3-opencv
sudo cp deploy/raumzaehler.service /etc/systemd/system/
sudo systemctl enable raumzaehler
```

> `python3-opencv` is required: picamera2's IMX500 device module imports `cv2`.
> Without it the counting thread fails at startup with `No module named 'cv2'`.

Then deploy. From a dev machine over ssh:

```bash
./deploy/deploy.sh                     # rsync + provision + restart service
PI_HOST=pi@<host> ./deploy/deploy.sh   # override target host
```

Or directly on the Pi itself (no ssh; the checkout lives on the device):

```bash
PI_HOST=local ./deploy/deploy.sh
```

The script syncs from the repo root regardless of where you invoke it from, and
provisioning (`apt-get install python3-opencv`, venv build, `pip install`,
`systemctl restart`) needs `sudo` — run it in a real terminal so the password
prompt works.

> **Note:** the systemd unit sets `COUNTER_SOURCE=imx500`, but a `.env` file on
> the Pi overrides it. Do **not** copy `.env.example` (which sets `sim`) to the
> Pi unchanged, or the camera will be ignored.
