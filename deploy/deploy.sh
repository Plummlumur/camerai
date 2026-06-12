#!/usr/bin/env bash
set -euo pipefail

PI_HOST="${PI_HOST:-pi@raumzaehler.local}"
TARGET_DIR="/home/pi/raumzaehler"

rsync -av --delete \
  --exclude '.git' --exclude '.venv' --exclude 'data' \
  --exclude '__pycache__' --exclude '.pytest_cache' --exclude '.ruff_cache' \
  --exclude '.claude' --exclude 'docs' \
  ./ "$PI_HOST:$TARGET_DIR/"

# --system-site-packages: picamera2 comes from apt and must stay visible
ssh "$PI_HOST" "cd $TARGET_DIR \
  && python3 -m venv --system-site-packages .venv \
  && .venv/bin/pip install -r requirements.txt \
  && sudo systemctl restart raumzaehler"

echo "Deployed to $PI_HOST"
