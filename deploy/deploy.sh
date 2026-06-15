#!/usr/bin/env bash
set -euo pipefail

# Deploy Raumzaehler to the target Pi.
#   ./deploy/deploy.sh                  # remote deploy over ssh to $PI_HOST
#   PI_HOST=pi@host ./deploy/deploy.sh  # override remote target
#   PI_HOST=local ./deploy/deploy.sh    # deploy on the Pi itself (no ssh)
PI_HOST="${PI_HOST:-pi@kam-01}"
TARGET_DIR="/home/pi/raumzaehler"

# Always sync from the repo root, regardless of the caller's working directory.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --exclude '.env': preserve the Pi-local config; without it --delete would wipe it.
RSYNC_EXCLUDES=(
  --exclude '.git' --exclude '.venv' --exclude 'data'
  --exclude '__pycache__' --exclude '.pytest_cache' --exclude '.ruff_cache'
  --exclude '.claude' --exclude 'docs' --exclude '.env'
)

# Provisioning runs on the target after the sync.
# --system-site-packages: picamera2/cv2 come from apt and must stay visible.
# python3-opencv: required by picamera2's IMX500 device module (imports cv2).
read -r -d '' PROVISION <<PROV || true
set -euo pipefail
sudo apt-get install -y python3-opencv
cd "$TARGET_DIR"
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
sudo systemctl restart raumzaehler
PROV

if [ "$PI_HOST" = "local" ]; then
  rsync -av --delete "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/" "$TARGET_DIR/"
  bash -c "$PROVISION"
  echo "Deployed locally to $TARGET_DIR"
else
  rsync -av --delete "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/" "$PI_HOST:$TARGET_DIR/"
  ssh "$PI_HOST" "$PROVISION"
  echo "Deployed to $PI_HOST:$TARGET_DIR"
fi
