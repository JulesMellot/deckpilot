#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/pi/pideck"
VENV_DIR="$APP_DIR/.venv"
SERVICE_NAME="pideck-open.service"
REPO_SOURCE="$(cd "$(dirname "$0")/.." && pwd)"

sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg mpv sqlite3 netcat-openbsd rsync

sudo mkdir -p "$APP_DIR"
sudo rsync -a --delete "$REPO_SOURCE/" "$APP_DIR/"
sudo chown -R pi:pi "$APP_DIR"

python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r "$APP_DIR/requirements.txt"

if [ ! -f "$APP_DIR/config.json" ]; then
  cp "$APP_DIR/config.json.example" "$APP_DIR/config.json"
fi

sudo cp "$APP_DIR/deploy/$SERVICE_NAME" "/etc/systemd/system/$SERVICE_NAME"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "Installation terminee. Interface web: http://$(hostname -I | awk '{print $1}'):8080"
