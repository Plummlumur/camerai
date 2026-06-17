#!/usr/bin/env bash
set -euo pipefail

# Interactive installer for Raumzaehler on a Raspberry Pi (Bookworm).
#
# Run ON the Pi, as the service user (e.g. `pi`), NOT with sudo — the script
# calls sudo itself for the few steps that need root (apt, systemd). It:
#   1. asks for the deployment-relevant config (each value defaults to the
#      current setting if already installed, otherwise the app default),
#   2. syncs the code into the target dir (preserving the per-device .env),
#   3. writes the per-device .env from your answers,
#   4. installs python3-opencv, builds the venv, installs deps,
#   5. installs + enables the systemd unit and (re)starts the service.
#
# Re-running it is safe: it reuses the existing .env as the prompt defaults, so
# pressing Enter through every prompt performs an in-place upgrade.
#
# Override non-prompted locations via env vars, e.g.:
#   TARGET_DIR=/srv/raumzaehler ./deploy/install.sh

TARGET_DIR="${TARGET_DIR:-/home/pi/raumzaehler}"
SERVICE_USER="${SERVICE_USER:-$(id -un)}"
SERVICE_NAME="raumzaehler"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_FILE="${TARGET_DIR}/.env"

# Always sync from the repo root, regardless of the caller's working directory.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$REPO_ROOT" = "$TARGET_DIR" ]; then
  echo "ERROR: repo root and TARGET_DIR are the same ($TARGET_DIR)." >&2
  echo "Run the installer from the source checkout, deploying into a separate dir." >&2
  exit 1
fi

# --- prompt helpers ---------------------------------------------------------

# ask "Prompt" "default" -> echoes the chosen value (default on empty/non-tty).
ask() {
  local prompt="$1" default="$2" reply=""
  if [ -t 0 ] && [ -r /dev/tty ]; then
    read -r -p "$prompt [$default]: " reply </dev/tty
  fi
  printf '%s' "${reply:-$default}"
}

# ask_bool "Prompt" "default" -> normalises to true/false, re-asks on garbage.
ask_bool() {
  local prompt="$1" default="$2" reply
  while true; do
    reply="$(ask "$prompt (true/false)" "$default")"
    case "${reply,,}" in
      true | t | yes | y | 1) printf 'true'; return ;;
      false | f | no | n | 0) printf 'false'; return ;;
      *) echo "  Bitte 'true' oder 'false' eingeben." >&2 ;;
    esac
  done
}

# ask_choice "Prompt" "default" opt1 opt2 ... -> echoes one of the options.
ask_choice() {
  local prompt="$1" default="$2"; shift 2
  local options=("$@") reply opt
  while true; do
    reply="$(ask "$prompt ($(IFS=/; echo "${options[*]}"))" "$default")"
    for opt in "${options[@]}"; do
      [ "$reply" = "$opt" ] && { printf '%s' "$reply"; return; }
    done
    echo "  Erlaubt: ${options[*]}" >&2
  done
}

# env_default KEY fallback -> current value from an existing .env, else fallback.
env_default() {
  local key="$1" fallback="$2" val=""
  if [ -f "$ENV_FILE" ]; then
    val="$(grep -E "^${key}=" "$ENV_FILE" | tail -1 | cut -d= -f2-)"
  fi
  printf '%s' "${val:-$fallback}"
}

# COUNTER_SOURCE and the port live in the systemd unit, not the .env — read
# their current values from an existing unit so a re-run defaults to them.
source_default() {
  local val=""
  [ -f "$UNIT_PATH" ] && val="$(grep -oE 'COUNTER_SOURCE=[^ ]+' "$UNIT_PATH" | tail -1 | cut -d= -f2)"
  printf '%s' "${val:-imx500}"
}
port_default() {
  local val=""
  [ -f "$UNIT_PATH" ] && val="$(grep -oE -- '--port [0-9]+' "$UNIT_PATH" | tail -1 | awk '{print $2}')"
  printf '%s' "${val:-8000}"
}

# --- gather configuration ---------------------------------------------------

echo "== Raumzaehler-Installation =="
echo "Zielverzeichnis : $TARGET_DIR"
echo "Service-User    : $SERVICE_USER"
if [ -f "$ENV_FILE" ]; then
  echo "(Bestehende .env gefunden — Werte werden als Defaults vorgeschlagen.)"
fi
echo "Enter = Default uebernehmen."
echo

COUNTER_SOURCE="$(ask_choice  "Detektionsquelle"        "$(source_default)" imx500 sim)"
SENSOR_ID="$(ask              "Sensor-ID (Geraetename)" "$(env_default SENSOR_ID raum-1)")"
HTTP_PORT="$(ask              "HTTP-Port"               "$(port_default)")"
TIMEZONE="$(ask               "Zeitzone"                "$(env_default TIMEZONE Europe/Vienna)")"
NIGHTLY_RESET_TIME="$(ask     "Naechtlicher Reset (HH:MM lokal)" "$(env_default NIGHTLY_RESET_TIME 04:00)")"
LINE_AXIS="$(ask_choice       "Zaehllinien-Achse"       "$(env_default LINE_AXIS x)" x y)"
LINE_POSITION="$(ask          "Linienposition (0..1)"   "$(env_default LINE_POSITION 0.5)")"
INVERT_DIRECTION="$(ask_bool  "Richtung invertieren"    "$(env_default INVERT_DIRECTION false)")"
DETECTION_CONFIDENCE="$(ask   "Erkennungs-Schwelle (0..1)" "$(env_default DETECTION_CONFIDENCE 0.5)")"
CAMERA_PREVIEW_ENABLED="$(ask_bool "Kamera-Preview aktivieren (Einrichtungshilfe)" "$(env_default CAMERA_PREVIEW_ENABLED false)")"

# Non-prompted, kept at current/default values (written so the .env is complete).
DB_PATH="$(env_default DB_PATH data/raumzaehler.db)"
IMX500_MODEL_PATH="$(env_default IMX500_MODEL_PATH /usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk)"
CAMERA_PREVIEW_FPS="$(env_default CAMERA_PREVIEW_FPS 10)"
CAMERA_PREVIEW_QUALITY="$(env_default CAMERA_PREVIEW_QUALITY 70)"

echo
echo "== Zusammenfassung =="
cat <<SUMMARY
  Quelle           : $COUNTER_SOURCE      (systemd-Unit, nicht in .env)
  Sensor-ID        : $SENSOR_ID
  HTTP-Port        : $HTTP_PORT
  Zeitzone         : $TIMEZONE
  Nacht-Reset      : $NIGHTLY_RESET_TIME
  Zaehllinie       : Achse $LINE_AXIS @ $LINE_POSITION (invertiert: $INVERT_DIRECTION)
  Erkennungs-Conf  : $DETECTION_CONFIDENCE
  Kamera-Preview   : $CAMERA_PREVIEW_ENABLED
SUMMARY
echo
if [ "$(ask "Fortfahren?" "j")" != "j" ]; then
  echo "Abgebrochen."
  exit 0
fi

# --- 1. sync code (preserve per-device .env, data, venv) --------------------

echo
echo "-> Synchronisiere Code nach $TARGET_DIR"
mkdir -p "$TARGET_DIR"
rsync -a --delete \
  --exclude '.git' --exclude '.venv' --exclude 'data' \
  --exclude '__pycache__' --exclude '.pytest_cache' --exclude '.ruff_cache' \
  --exclude '.claude' --exclude 'docs' --exclude '.env' \
  "$REPO_ROOT/" "$TARGET_DIR/"

# --- 2. write the per-device .env -------------------------------------------

echo "-> Schreibe $ENV_FILE"
cat > "$ENV_FILE" <<ENV
# Pi-local runtime config — the AUTHORITATIVE config for the running service.
# Generated by deploy/install.sh. The systemd unit's WorkingDirectory is
# $TARGET_DIR, so both systemd (EnvironmentFile=) and pydantic
# (env_file=".env") read THIS file. Deploys exclude .env, so it survives
# upgrades and is never overwritten by the repo's .env.
#
# Do NOT set COUNTER_SOURCE here — the systemd unit sets it ($COUNTER_SOURCE);
# EnvironmentFile would otherwise override the unit.

# Device identity (carried on every event; future MQTT topic counter/<id>/events).
SENSOR_ID=$SENSOR_ID

# Storage and locale.
DB_PATH=$DB_PATH
TIMEZONE=$TIMEZONE

# Counting line and direction.
INVERT_DIRECTION=$INVERT_DIRECTION
LINE_POSITION=$LINE_POSITION
LINE_AXIS=$LINE_AXIS

# On-sensor detection.
IMX500_MODEL_PATH=$IMX500_MODEL_PATH
DETECTION_CONFIDENCE=$DETECTION_CONFIDENCE

# Nightly occupancy reset (local time) to clear accumulated drift.
NIGHTLY_RESET_TIME=$NIGHTLY_RESET_TIME

# Camera preview for setup/calibration. Set to false in normal operation
# (privacy-by-design baseline keeps raw video on the sensor).
CAMERA_PREVIEW_ENABLED=$CAMERA_PREVIEW_ENABLED
CAMERA_PREVIEW_FPS=$CAMERA_PREVIEW_FPS
CAMERA_PREVIEW_QUALITY=$CAMERA_PREVIEW_QUALITY
ENV

# --- 3. system deps (apt) ---------------------------------------------------

echo "-> Installiere System-Abhaengigkeiten (sudo)"
# python3-opencv: picamera2's IMX500 device module imports cv2.
sudo apt-get install -y python3-picamera2 imx500-all python3-opencv

# --- 4. virtualenv + Python deps --------------------------------------------

echo "-> Baue virtualenv und installiere Python-Abhaengigkeiten"
# --system-site-packages: picamera2/cv2 come from apt and must stay visible.
python3 -m venv --system-site-packages "$TARGET_DIR/.venv"
"$TARGET_DIR/.venv/bin/pip" install --upgrade pip >/dev/null
"$TARGET_DIR/.venv/bin/pip" install -r "$TARGET_DIR/requirements.txt"

# --- 5. systemd unit --------------------------------------------------------

echo "-> Installiere systemd-Unit $UNIT_PATH (sudo)"
sudo tee "$UNIT_PATH" >/dev/null <<UNIT
[Unit]
Description=Raumzaehler people counter
After=network-online.target
Wants=network-online.target

[Service]
User=$SERVICE_USER
WorkingDirectory=$TARGET_DIR
Environment=COUNTER_SOURCE=$COUNTER_SOURCE
EnvironmentFile=-$ENV_FILE
ExecStart=$TARGET_DIR/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port $HTTP_PORT
Restart=on-failure
RestartSec=5
# IMX500 firmware upload takes several seconds at startup
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo
echo "== Fertig =="
echo "Dashboard: http://$(hostname -I | awk '{print $1}'):$HTTP_PORT/"
echo "Status:    systemctl status $SERVICE_NAME"
