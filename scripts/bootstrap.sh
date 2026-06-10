#!/usr/bin/env bash
# DeckPilot bootstrap installer.
# Pure bash + ANSI: no dependency is needed to render the UI, so it works on a
# fresh Raspberry Pi OS over `curl | bash` as well as on macOS (bash 3.2).
set -euo pipefail

DECKPILOT_REPO_URL="${DECKPILOT_REPO_URL:-https://github.com/JulesMellot/deckpilot.git}"
APP_NAME="DeckPilot"
ASSUME_YES=0
SERVICE_MODE="ask"
BOOT_INFO_MODE="auto"
UI_DEMO=0
LOG_FILE="$(mktemp -t deckpilot-install.XXXXXX.log 2>/dev/null || echo /tmp/deckpilot-install.log)"

# --------------------------------------------------------------------------
# Terminal UI
# --------------------------------------------------------------------------

IS_TTY=0
[[ -t 1 ]] && IS_TTY=1

USE_COLOR=0
if [[ $IS_TTY -eq 1 ]] && [[ -z "${NO_COLOR:-}" ]] && [[ "${TERM:-dumb}" != "dumb" ]]; then
  USE_COLOR=1
fi

if [[ $USE_COLOR -eq 1 ]]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
  C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
  C_RED=$'\033[31m'; C_BLUE=$'\033[34m'
else
  C_RESET=""; C_BOLD=""; C_DIM=""; C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_BLUE=""
fi

UTF8_OK=0
case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
  *UTF-8*|*utf-8*|*UTF8*|*utf8*) UTF8_OK=1 ;;
esac

if [[ $UTF8_OK -eq 1 ]]; then
  SYM_OK="✔"; SYM_FAIL="✖"; SYM_WARN="▲"; SYM_ARROW="▸"; SYM_DOT="·"
  SPINNER_FRAMES="⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏"
  BOX_TL="╭"; BOX_TR="╮"; BOX_BL="╰"; BOX_BR="╯"; BOX_H="─"; BOX_V="│"
else
  SYM_OK="OK"; SYM_FAIL="XX"; SYM_WARN="!!"; SYM_ARROW=">"; SYM_DOT="-"
  SPINNER_FRAMES="| / - \\"
  BOX_TL="+"; BOX_TR="+"; BOX_BL="+"; BOX_BR="+"; BOX_H="-"; BOX_V="|"
fi

BOX_WIDTH=58

repeat_char() {
  local char="$1" count="$2" out=""
  while [[ $count -gt 0 ]]; do out="$out$char"; count=$((count - 1)); done
  printf '%s' "$out"
}

box_top()    { printf '%s%s%s%s%s\n' "$C_DIM" "$BOX_TL" "$(repeat_char "$BOX_H" $BOX_WIDTH)" "$BOX_TR" "$C_RESET"; }
box_bottom() { printf '%s%s%s%s%s\n' "$C_DIM" "$BOX_BL" "$(repeat_char "$BOX_H" $BOX_WIDTH)" "$BOX_BR" "$C_RESET"; }

box_line() {
  # box_line "text" [color-of-text]; pads to the box width (plain-text length).
  local text="$1" color="${2:-}"
  local pad=$((BOX_WIDTH - 2 - ${#text}))
  [[ $pad -lt 0 ]] && pad=0
  printf '%s%s%s %s%s%s%s %s%s%s\n' \
    "$C_DIM" "$BOX_V" "$C_RESET" \
    "$color" "$text" "$C_RESET" "$(repeat_char ' ' $pad)" \
    "$C_DIM" "$BOX_V" "$C_RESET"
}

banner() {
  printf '\n'
  box_top
  box_line ""
  box_line "  D E C K P I L O T" "$C_BOLD$C_CYAN"
  box_line "  Open HyperDeck-style playout for ATEM & Companion" "$C_DIM"
  box_line ""
  box_bottom
  printf '\n'
}

info()  { printf '  %s%s%s %s\n' "$C_CYAN" "$SYM_ARROW" "$C_RESET" "$1"; }
warn()  { printf '  %s%s WARNING%s %s\n' "$C_YELLOW" "$SYM_WARN" "$C_RESET" "$1"; }
die() {
  printf '\n  %s%s ERROR%s %s\n' "$C_RED" "$SYM_FAIL" "$C_RESET" "$1" >&2
  printf '  %sFull log: %s%s\n\n' "$C_DIM" "$LOG_FILE" "$C_RESET" >&2
  exit 1
}

TOTAL_STEPS=0
CURRENT_STEP=0

run_step() {
  # run_step "Title" command [args...] — spinner UI on a TTY, plain otherwise.
  local title="$1"; shift
  CURRENT_STEP=$((CURRENT_STEP + 1))
  local label
  label="$(printf '[%d/%d] %s' "$CURRENT_STEP" "$TOTAL_STEPS" "$title")"
  {
    printf '\n===== STEP %d/%d: %s =====\n' "$CURRENT_STEP" "$TOTAL_STEPS" "$title"
  } >>"$LOG_FILE"

  if [[ $IS_TTY -eq 1 ]]; then
    local status=0 pid frame
    ("$@") >>"$LOG_FILE" 2>&1 &
    pid=$!
    printf '\033[?25l' # hide cursor
    while kill -0 "$pid" 2>/dev/null; do
      for frame in $SPINNER_FRAMES; do
        printf '\r  %s%s%s %s%s%s' "$C_CYAN" "$frame" "$C_RESET" "$C_DIM" "$label" "$C_RESET"
        sleep 0.1
        kill -0 "$pid" 2>/dev/null || break
      done
    done
    wait "$pid" || status=$?
    printf '\033[?25h' # restore cursor
    if [[ $status -eq 0 ]]; then
      printf '\r  %s%s%s %s\n' "$C_GREEN" "$SYM_OK" "$C_RESET" "$label"
    else
      printf '\r  %s%s%s %s\n\n' "$C_RED" "$SYM_FAIL" "$C_RESET" "$label"
      printf '  %sLast lines of the install log:%s\n' "$C_DIM" "$C_RESET"
      tail -n 15 "$LOG_FILE" | sed 's/^/    /'
      die "Step failed: $title"
    fi
  else
    printf '%s ...\n' "$label"
    if ! "$@" >>"$LOG_FILE" 2>&1; then
      tail -n 15 "$LOG_FILE" | sed 's/^/    /'
      die "Step failed: $title"
    fi
    printf '%s done\n' "$label"
  fi
}

ask_yes_no() {
  # ask_yes_no "Question?" default(y|n) — reads /dev/tty so it works via curl|bash.
  local prompt="$1" default="${2:-y}" suffix reply
  if [[ "$ASSUME_YES" -eq 1 ]] || [[ ! -r /dev/tty ]]; then
    [[ "$default" == "y" ]]
    return
  fi
  suffix="[y/N]"
  [[ "$default" == "y" ]] && suffix="[Y/n]"
  printf '  %s?%s %s %s%s%s ' "$C_BLUE" "$C_RESET" "$prompt" "$C_DIM" "$suffix" "$C_RESET"
  read -r reply < /dev/tty || reply=""
  reply="${reply:-$default}"
  case "$reply" in
    [Yy]*) return 0 ;;
    *) return 1 ;;
  esac
}

usage() {
  cat <<'EOF'
DeckPilot bootstrap installer

Options:
  --install-dir PATH     Installation directory
  --repo-url URL         Repository URL
  --yes                  Non-interactive mode (accept defaults)
  --install-service      Install and enable a systemd service when available
  --skip-service         Do not install a systemd service
  --install-boot-info    Install the HDMI boot info service on supported Linux SBCs
  --skip-boot-info       Do not install the HDMI boot info service
  -h, --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --repo-url) DECKPILOT_REPO_URL="$2"; shift 2 ;;
    --yes) ASSUME_YES=1; shift ;;
    --install-service) SERVICE_MODE="yes"; shift ;;
    --skip-service) SERVICE_MODE="no"; shift ;;
    --install-boot-info) BOOT_INFO_MODE="yes"; shift ;;
    --skip-boot-info) BOOT_INFO_MODE="no"; shift ;;
    --ui-demo) UI_DEMO=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

# --------------------------------------------------------------------------
# Environment detection
# --------------------------------------------------------------------------

command_exists() { command -v "$1" >/dev/null 2>&1; }

detect_os() {
  case "$(uname -s)" in
    Linux) echo "linux" ;;
    Darwin) echo "macos" ;;
    *) echo "unsupported" ;;
  esac
}

detect_arch() { uname -m; }

detect_model() {
  if [[ -f /sys/firmware/devicetree/base/model ]]; then
    tr -d '\0' < /sys/firmware/devicetree/base/model
  else
    uname -m
  fi
}

is_linux_sbc() {
  [[ "$OS_NAME" == "linux" ]] || return 1
  local arch
  arch="$(detect_arch)"
  [[ "$arch" =~ ^(armv|aarch64|arm64) ]] && return 0
  [[ -f /sys/firmware/devicetree/base/model ]] && return 0
  return 1
}

SUDO=""
if [[ "$(id -u)" -ne 0 ]] && command_exists sudo; then
  SUDO="sudo"
fi

resolve_run_user() {
  if [[ "$(id -u)" -eq 0 ]] && [[ -n "${SUDO_USER:-}" ]] && [[ "${SUDO_USER}" != "root" ]]; then
    echo "${SUDO_USER}"
    return
  fi
  id -un
}

resolve_home_dir() {
  local user_name="$1"
  if command_exists getent; then
    getent passwd "$user_name" | cut -d: -f6
    return
  fi
  USER_NAME="$user_name" python3 - <<'PY'
import os
import pwd
print(pwd.getpwnam(os.environ["USER_NAME"]).pw_dir)
PY
}

RUN_USER="$(resolve_run_user)"
RUN_HOME="$(resolve_home_dir "$RUN_USER")"
RUN_HOME="${RUN_HOME:-$HOME}"
INSTALL_DIR="${INSTALL_DIR:-${DECKPILOT_INSTALL_DIR:-$RUN_HOME/deckpilot}}"

OS_NAME="$(detect_os)"

# --------------------------------------------------------------------------
# Install steps (all output goes to $LOG_FILE; the UI stays clean)
# --------------------------------------------------------------------------

install_homebrew() {
  command_exists brew && return 0
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
  command_exists brew
}

install_packages_linux() {
  if command_exists apt-get; then
    $SUDO apt-get update
    $SUDO apt-get install -y git curl rsync python3 python3-venv python3-pip ffmpeg mpv sqlite3
  elif command_exists dnf; then
    $SUDO dnf install -y git curl rsync python3 python3-pip ffmpeg mpv sqlite
  elif command_exists yum; then
    $SUDO yum install -y git curl rsync python3 python3-pip ffmpeg mpv sqlite
  elif command_exists pacman; then
    $SUDO pacman -Sy --noconfirm git curl rsync python python-pip ffmpeg mpv sqlite
  elif command_exists zypper; then
    $SUDO zypper --non-interactive install git curl rsync python3 python3-pip python3-virtualenv ffmpeg-6 mpv sqlite3 || \
      $SUDO zypper --non-interactive install git curl rsync python3 python3-pip python3-virtualenv ffmpeg mpv sqlite3
  elif command_exists apk; then
    $SUDO apk add git curl rsync python3 py3-pip ffmpeg mpv sqlite
  else
    echo "Unsupported Linux package manager." >&2
    return 1
  fi
}

install_packages_macos() {
  brew update
  brew install git python ffmpeg mpv sqlite
}

clone_or_update_repo() {
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" pull --ff-only
    return
  fi
  if [[ -d "$INSTALL_DIR" ]] && [[ -n "$(find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | head -n 1)" ]]; then
    echo "Install directory '$INSTALL_DIR' exists and is not empty." >&2
    return 1
  fi
  git clone "$DECKPILOT_REPO_URL" "$INSTALL_DIR"
}

write_config() {
  local config_path="$INSTALL_DIR/config.json"
  local socket_path="/tmp/deckpilot-mpv.sock"
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
        "mpv_log_path": str(data_dir / "mpv.log"),
    }
)

config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
}

setup_python_env() {
  python3 -m venv "$INSTALL_DIR/.venv"
  "$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip
  "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
}

install_reboot_helper() {
  command_exists systemctl || return 0
  command_exists sudo || return 0

  local helper_path="/usr/local/bin/deckpilot-system-reboot"
  local sudoers_path="/etc/sudoers.d/90-deckpilot-system-reboot"
  local systemctl_path
  systemctl_path="$(command -v systemctl)"
  [[ -n "$systemctl_path" ]] || return 0

  $SUDO tee "$helper_path" >/dev/null <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec $systemctl_path reboot
EOF
  $SUDO chmod 755 "$helper_path"
  $SUDO chown root:root "$helper_path"

  $SUDO mkdir -p /etc/sudoers.d
  $SUDO tee "$sudoers_path" >/dev/null <<EOF
$RUN_USER ALL=(root) NOPASSWD: $helper_path
EOF
  $SUDO chmod 440 "$sudoers_path"
}

configure_console_boot() {
  command_exists systemctl || return 0
  is_linux_sbc || return 0

  $SUDO systemctl set-default multi-user.target || true
  if $SUDO systemctl list-unit-files display-manager.service >/dev/null 2>&1; then
    $SUDO systemctl disable display-manager.service >/dev/null 2>&1 || true
    if $SUDO systemctl is-active --quiet display-manager.service; then
      $SUDO systemctl stop display-manager.service >/dev/null 2>&1 || true
    fi
  fi
}

install_systemd_service() {
  command_exists systemctl || return 0
  local service_name="deckpilot.service"
  local service_path="/etc/systemd/system/$service_name"

  $SUDO tee "$service_path" >/dev/null <<EOF
[Unit]
Description=DeckPilot HyperDeck Emulator
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
SupplementaryGroups=audio video render input
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
  install_reboot_helper
}

install_boot_info_service() {
  command_exists systemctl || return 0
  [[ -e /dev/tty1 ]] || return 0

  local service_name="deckpilot-boot-info.service"
  local service_path="/etc/systemd/system/$service_name"
  local script_path="$INSTALL_DIR/scripts/show_boot_ip.py"
  local python_path="$INSTALL_DIR/.venv/bin/python"

  [[ -f "$script_path" ]] || return 0
  if [[ ! -x "$python_path" ]]; then
    python_path="$(command -v python3 || true)"
  fi
  [[ -n "$python_path" ]] || return 0

  $SUDO tee "$service_path" >/dev/null <<EOF
[Unit]
Description=DeckPilot HDMI Boot Info
After=network-online.target
Wants=network-online.target
Conflicts=getty@tty1.service display-manager.service
Before=getty@tty1.service display-manager.service

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$python_path $script_path --config $INSTALL_DIR/config.json --tty /dev/tty1
Restart=always
RestartSec=3
StandardInput=tty
StandardOutput=tty
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes

[Install]
WantedBy=multi-user.target
EOF
  $SUDO systemctl daemon-reload
  configure_console_boot
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

  printf '\n'
  box_top
  box_line ""
  box_line "  ${SYM_OK} ${APP_NAME} is installed and ready" "$C_BOLD$C_GREEN"
  box_line ""
  box_line "  Web UI        http://$host_display:8080" "$C_CYAN"
  box_line "  HyperDeck     $host_display:9993" "$C_CYAN"
  box_line "  Directory     $INSTALL_DIR"
  if [[ "$DO_SERVICE" == "yes" ]]; then
    box_line "  Service       deckpilot.service (enabled)"
  else
    box_line "  Run manually  cd $INSTALL_DIR"
    box_line "                .venv/bin/python -m app.main"
  fi
  box_line ""
  box_line "  ATEM: add the HyperDeck target shown in the web UI" "$C_DIM"
  box_line ""
  box_bottom
  printf '  %sInstall log: %s%s\n\n' "$C_DIM" "$LOG_FILE" "$C_RESET"
}

# --------------------------------------------------------------------------
# UI demo mode (development helper: renders the full flow with fake steps)
# --------------------------------------------------------------------------

if [[ $UI_DEMO -eq 1 ]]; then
  banner
  info "Platform   : demo"
  info "Install to : $INSTALL_DIR"
  printf '\n'
  ask_yes_no "Install DeckPilot as a systemd service?" "y" || true
  printf '\n'
  TOTAL_STEPS=4
  run_step "System packages (apt)" sleep 1.2
  run_step "Fetching DeckPilot" sleep 0.8
  run_step "Python environment" sleep 1.0
  run_step "Writing configuration" sleep 0.4
  DO_SERVICE="yes" OS_NAME="linux" print_summary
  exit 0
fi

# --------------------------------------------------------------------------
# Main flow: detect, ask everything up front, then execute with progress
# --------------------------------------------------------------------------

[[ "$OS_NAME" != "unsupported" ]] || die "This bootstrap supports Linux and macOS. Use bootstrap.ps1 on Windows."

banner
info "Platform   : $OS_NAME ($(detect_model))"
info "Install to : $INSTALL_DIR"
info "Repository : $DECKPILOT_REPO_URL"
printf '\n'

# Decide the whole plan before running anything.
DO_SERVICE="no"
DO_BOOT_INFO="no"
if [[ "$OS_NAME" == "linux" ]] && command_exists systemctl; then
  if [[ "$SERVICE_MODE" == "yes" ]] || { [[ "$SERVICE_MODE" == "ask" ]] && ask_yes_no "Install DeckPilot as a systemd service?" "y"; }; then
    DO_SERVICE="yes"
  fi
  if [[ "$BOOT_INFO_MODE" == "yes" ]]; then
    DO_BOOT_INFO="yes"
  elif [[ "$BOOT_INFO_MODE" == "auto" ]] && is_linux_sbc && ask_yes_no "Install the HDMI boot info screen service?" "y"; then
    DO_BOOT_INFO="yes"
  fi
fi

if [[ "$OS_NAME" == "macos" ]] && ! command_exists brew; then
  ask_yes_no "Homebrew is required and missing. Install it now?" "y" || die "Homebrew is required to continue."
fi

# Warm up sudo while we can still show its password prompt.
if [[ -n "$SUDO" ]] && [[ $IS_TTY -eq 1 ]]; then
  info "Administrator rights are needed for system packages."
  $SUDO -v || die "sudo authentication failed."
fi

TOTAL_STEPS=4
[[ "$OS_NAME" == "macos" ]] && ! command_exists brew && TOTAL_STEPS=$((TOTAL_STEPS + 1))
[[ "$DO_SERVICE" == "yes" ]] && TOTAL_STEPS=$((TOTAL_STEPS + 1))
[[ "$DO_BOOT_INFO" == "yes" ]] && TOTAL_STEPS=$((TOTAL_STEPS + 1))

printf '\n'
if [[ "$OS_NAME" == "linux" ]]; then
  run_step "System packages" install_packages_linux
else
  if ! command_exists brew; then
    run_step "Homebrew" install_homebrew
  fi
  run_step "System packages (Homebrew)" install_packages_macos
fi
run_step "Fetching DeckPilot" clone_or_update_repo
run_step "Python environment" setup_python_env
run_step "Writing configuration" write_config
[[ "$DO_SERVICE" == "yes" ]] && run_step "systemd service" install_systemd_service
[[ "$DO_BOOT_INFO" == "yes" ]] && run_step "HDMI boot info service" install_boot_info_service

print_summary
