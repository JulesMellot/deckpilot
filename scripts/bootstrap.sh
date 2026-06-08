#!/usr/bin/env bash
set -euo pipefail

DECKPILOT_REPO_URL="${DECKPILOT_REPO_URL:-https://github.com/JulesMellot/deckpilot.git}"
INSTALL_DIR="${DECKPILOT_INSTALL_DIR:-$HOME/deckpilot}"
APP_NAME="DeckPilot"
ASSUME_YES=0
SERVICE_MODE="ask"

log() {
  printf '\n[%s] %s\n' "$APP_NAME" "$1"
}

warn() {
  printf '\n[%s] WARNING: %s\n' "$APP_NAME" "$1"
}

die() {
  printf '\n[%s] ERROR: %s\n' "$APP_NAME" "$1" >&2
  exit 1
}

usage() {
  cat <<'EOF'
DeckPilot bootstrap installer

Options:
  --install-dir PATH     Installation directory
  --repo-url URL         Repository URL
  --yes                  Non-interactive mode
  --install-service      Install and enable a systemd service when available
  --skip-service         Do not install a systemd service
  -h, --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir)
      INSTALL_DIR="$2"
      shift 2
      ;;
    --repo-url)
      DECKPILOT_REPO_URL="$2"
      shift 2
      ;;
    --yes)
      ASSUME_YES=1
      shift
      ;;
    --install-service)
      SERVICE_MODE="yes"
      shift
      ;;
    --skip-service)
      SERVICE_MODE="no"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

confirm() {
  local prompt="$1"
  local default="${2:-y}"
  if [[ "$ASSUME_YES" -eq 1 ]]; then
    return 0
  fi
  local suffix="[y/N]"
  [[ "$default" == "y" ]] && suffix="[Y/n]"
  read -r -p "$prompt $suffix " reply
  reply="${reply:-$default}"
  [[ "$reply" =~ ^[Yy]$ ]]
}

detect_os() {
  case "$(uname -s)" in
    Linux) echo "linux" ;;
    Darwin) echo "macos" ;;
    *) echo "unsupported" ;;
  esac
}

SUDO=""
if [[ "$(id -u)" -ne 0 ]] && command_exists sudo; then
  SUDO="sudo"
fi

OS_NAME="$(detect_os)"
[[ "$OS_NAME" != "unsupported" ]] || die "This bootstrap supports Linux and macOS. Use bootstrap.ps1 on Windows."

install_homebrew() {
  if command_exists brew; then
    return
  fi
  log "Homebrew is required on macOS and is not installed."
  confirm "Install Homebrew now?" "y" || die "Homebrew is required to continue."
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
  command_exists brew || die "Homebrew installation failed."
}

install_packages_linux() {
  if command_exists apt-get; then
    log "Installing system packages with apt."
    $SUDO apt-get update
    $SUDO apt-get install -y git curl rsync python3 python3-venv python3-pip ffmpeg mpv sqlite3
    return
  fi
  if command_exists dnf; then
    log "Installing system packages with dnf."
    $SUDO dnf install -y git curl rsync python3 python3-pip ffmpeg mpv sqlite
    return
  fi
  if command_exists yum; then
    log "Installing system packages with yum."
    $SUDO yum install -y git curl rsync python3 python3-pip ffmpeg mpv sqlite
    return
  fi
  if command_exists pacman; then
    log "Installing system packages with pacman."
    $SUDO pacman -Sy --noconfirm git curl rsync python python-pip ffmpeg mpv sqlite
    return
  fi
  if command_exists zypper; then
    log "Installing system packages with zypper."
    $SUDO zypper --non-interactive install git curl rsync python3 python3-pip python3-virtualenv ffmpeg-6 mpv sqlite3 || \
      $SUDO zypper --non-interactive install git curl rsync python3 python3-pip python3-virtualenv ffmpeg mpv sqlite3
    return
  fi
  if command_exists apk; then
    log "Installing system packages with apk."
    $SUDO apk add git curl rsync python3 py3-pip ffmpeg mpv sqlite
    return
  fi
  die "Unsupported Linux package manager. Install git, curl, python3, venv, pip, ffmpeg, mpv, sqlite3, and rsync manually."
}

install_packages_macos() {
  install_homebrew
  log "Installing system packages with Homebrew."
  brew update
  brew install git python ffmpeg mpv sqlite
}

clone_or_update_repo() {
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    log "Updating existing DeckPilot checkout in $INSTALL_DIR."
    git -C "$INSTALL_DIR" pull --ff-only
    return
  fi
  if [[ -d "$INSTALL_DIR" ]] && [[ -n "$(find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | head -n 1)" ]]; then
    die "Install directory '$INSTALL_DIR' exists and is not empty."
  fi
  log "Cloning DeckPilot into $INSTALL_DIR."
  git clone "$DECKPILOT_REPO_URL" "$INSTALL_DIR"
}

write_config() {
  local config_path="$INSTALL_DIR/config.json"
  local runtime_dir="$INSTALL_DIR/runtime"
  local socket_path="/tmp/deckpilot-mpv.sock"
  if [[ "$OS_NAME" == "macos" ]]; then
    socket_path="/tmp/deckpilot-mpv.sock"
  fi
  INSTALL_DIR="$INSTALL_DIR" CONFIG_PATH="$config_path" SOCKET_PATH="$socket_path" python3 <<'PY'
import json
import os
from pathlib import Path

install_dir = Path(os.environ["INSTALL_DIR"]).resolve()
config_path = Path(os.environ["CONFIG_PATH"])
socket_path = os.environ["SOCKET_PATH"]
example_path = install_dir / "config.json.example"

with example_path.open("r", encoding="utf-8") as handle:
    data = json.load(handle)

runtime_dir = install_dir / "runtime"
clips_dir = runtime_dir / "clips"
data_dir = runtime_dir / "data"
thumbs_dir = data_dir / "thumbnails"

data.update(
    {
        "clips_dir": str(clips_dir),
        "data_dir": str(data_dir),
        "db_path": str(data_dir / "pideck.db"),
        "thumbnails_dir": str(thumbs_dir),
        "mpv_socket_path": socket_path,
    }
)

config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
}

setup_python_env() {
  log "Creating Python virtual environment."
  python3 -m venv "$INSTALL_DIR/.venv"
  "$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip
  "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
}

install_systemd_service() {
  command_exists systemctl || return
  local service_name="deckpilot.service"
  local service_path="/etc/systemd/system/$service_name"
  local run_user
  run_user="$(id -un)"

  log "Installing systemd service: $service_name"
  $SUDO tee "$service_path" >/dev/null <<EOF
[Unit]
Description=DeckPilot HyperDeck Emulator
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$run_user
WorkingDirectory=$INSTALL_DIR
Environment=PIDECK_CONFIG=$INSTALL_DIR/config.json
ExecStart=$INSTALL_DIR/.venv/bin/python -m app.main
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable "$service_name"
  $SUDO systemctl restart "$service_name"
}

print_summary() {
  local host_display="127.0.0.1"
  if [[ "$OS_NAME" == "linux" ]] && command_exists hostname; then
    host_display="$(hostname -I 2>/dev/null | awk '{print $1}')"
    host_display="${host_display:-127.0.0.1}"
  elif [[ "$OS_NAME" == "macos" ]] && command_exists ipconfig; then
    host_display="$(ipconfig getifaddr en0 2>/dev/null || true)"
    host_display="${host_display:-127.0.0.1}"
  fi

  cat <<EOF

$APP_NAME installation complete.

Install directory:
  $INSTALL_DIR

Run manually:
  cd "$INSTALL_DIR"
  source .venv/bin/activate
  python3 -m app.main

Web UI:
  http://$host_display:8080

HyperDeck endpoint:
  $host_display:9993
EOF
}

log "Starting installer for $APP_NAME."
log "Detected platform: $OS_NAME"
log "Target directory: $INSTALL_DIR"

if [[ "$OS_NAME" == "linux" ]]; then
  install_packages_linux
else
  install_packages_macos
fi

clone_or_update_repo
setup_python_env
write_config

if [[ "$OS_NAME" == "linux" ]] && command_exists systemctl; then
  if [[ "$SERVICE_MODE" == "yes" ]] || { [[ "$SERVICE_MODE" == "ask" ]] && confirm "Install DeckPilot as a systemd service?" "y"; }; then
    install_systemd_service
  fi
fi

print_summary
