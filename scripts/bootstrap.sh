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
SMB_MODE="ask"
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
  --install-smb          Share the clips folder over SMB (network file drop)
  --skip-smb             Do not configure the SMB clip share
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
    --install-smb) SMB_MODE="yes"; shift ;;
    --skip-smb) SMB_MODE="no"; shift ;;
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
  # ntfs-3g / exfatprogs let the USB auto-mount handle Windows-formatted drives;
  # in-kernel drivers cover vfat/exfat/ntfs3 on recent kernels but these are the
  # safe fallback on older ones.
  if command_exists apt-get; then
    $SUDO apt-get update
    # cage + seatd: a Pi 3 only plays 1080p smoothly when mpv runs as a
    # dmabuf-wayland client of a nested compositor (cage), with seatd granting
    # the DRM seat to the headless service. Harmless extras on non-Pi Debian.
    $SUDO apt-get install -y git curl rsync python3 python3-venv python3-pip ffmpeg mpv sqlite3 ntfs-3g exfatprogs dosfstools cage seatd
  elif command_exists dnf; then
    $SUDO dnf install -y git curl rsync python3 python3-pip ffmpeg mpv sqlite ntfs-3g exfatprogs
  elif command_exists yum; then
    $SUDO yum install -y git curl rsync python3 python3-pip ffmpeg mpv sqlite ntfs-3g exfatprogs
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
  # On a Pi/SBC, run mpv under cage so 1080p plays via the hardware plane.
  local compositor=""
  is_linux_sbc && compositor="cage"
  INSTALL_DIR="$INSTALL_DIR" CONFIG_PATH="$config_path" SOCKET_PATH="$socket_path" COMPOSITOR="$compositor" python3 <<'PY'
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

compositor = os.environ.get("COMPOSITOR", "").strip()
if compositor:
    data["mpv_compositor"] = compositor
    # Same hardware limit drives both: a Pi can't scale video live, so conform
    # off-format clips to the project resolution at import.
    data["conform_clips"] = True

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

install_usb_automount() {
  # Headless Pi OS Lite has no desktop automounter, so a plugged-in USB drive is
  # never mounted and DeckPilot (which only reads mounted volumes) can't see it.
  # A udev rule hands each new USB filesystem to a templated systemd unit that
  # mounts it under /media/deckpilot/<label>; DeckPilot already scans /media.
  command_exists systemctl || return 0
  command_exists udevadm || return 0

  local helper_path="/usr/local/bin/deckpilot-usb-mount"
  local unit_path="/etc/systemd/system/deckpilot-usb-mount@.service"
  local rules_path="/etc/udev/rules.d/99-deckpilot-usb.rules"

  # Helper is fully literal (single-quoted heredoc); the run user arrives via
  # the unit's Environment so file ownership on FAT/exFAT/NTFS is set correctly.
  $SUDO tee "$helper_path" >/dev/null <<'EOF'
#!/usr/bin/env bash
# Managed by DeckPilot bootstrap.sh — auto-mounts USB partitions for the library.
set -euo pipefail

cmd="${1:-}"
dev="${2:-}"
node="/dev/${dev}"
base="/media/deckpilot"
run_user="${DECKPILOT_USER:-root}"

log() { logger -t deckpilot-usb-mount -- "$*" 2>/dev/null || true; }

# The web app calls eject/repair through passwordless sudo, so treat the
# device argument as hostile: a bare kernel name only, and it must exist.
case "$dev" in
  ''|*[!a-zA-Z0-9]*) echo "invalid device name: $dev" >&2; exit 1 ;;
esac
[ -b "$node" ] || { echo "$node is not a block device" >&2; exit 1; }

case "$cmd" in
  mount)
    fstype="$(blkid -o value -s TYPE "$node" 2>/dev/null || true)"
    [ -n "$fstype" ] || { log "no filesystem on $node, skipping"; exit 0; }
    label="$(blkid -o value -s LABEL "$node" 2>/dev/null || true)"
    [ -n "$label" ] || label="$dev"
    label="$(printf '%s' "$label" | tr -c 'A-Za-z0-9._-' '_')"
    target="${base}/${label}"
    if mountpoint -q "$target"; then target="${target}-${dev}"; fi
    mkdir -p "$target"
    uid="$(id -u "$run_user" 2>/dev/null || echo 0)"
    gid="$(id -g "$run_user" 2>/dev/null || echo 0)"
    case "$fstype" in
      vfat|exfat|ntfs|ntfs3) opts="rw,noatime,uid=${uid},gid=${gid},umask=022" ;;
      *)                     opts="rw,noatime" ;;
    esac
    if [ "$fstype" = "ntfs" ]; then
      mount -t ntfs3 -o "$opts" "$node" "$target" 2>/dev/null \
        || mount -t ntfs-3g -o "$opts" "$node" "$target" 2>/dev/null \
        || mount "$node" "$target"
    else
      mount -o "$opts" "$node" "$target" 2>/dev/null \
        || mount "$node" "$target"
    fi
    log "mounted $node ($fstype) at $target"
    ;;
  unmount)
    mp="$(findmnt -n -o TARGET --source "$node" 2>/dev/null || true)"
    if [ -n "$mp" ]; then
      umount "$mp" 2>/dev/null || umount -l "$mp" 2>/dev/null || true
      rmdir "$mp" 2>/dev/null || true
      log "unmounted $node from $mp"
    fi
    ;;
  eject)
    # Safe-eject: flush, then a *strict* unmount — a busy drive (clip still
    # playing from it) must fail loudly, never fall back to a lazy unmount
    # that would let the operator pull a dirty filesystem.
    mp="$(findmnt -n -o TARGET --source "$node" 2>/dev/null || true)"
    [ -n "$mp" ] || { log "eject: $node not mounted"; exit 0; }
    sync
    if ! umount "$mp"; then
      echo "Drive is busy — a clip on it may be playing or a copy still running. Stop it and retry." >&2
      exit 1
    fi
    rmdir "$mp" 2>/dev/null || true
    # Manual unmount already done; stopping the unit just keeps systemd's
    # view consistent (its ExecStop unmount is a no-op by then).
    systemctl stop "deckpilot-usb-mount@${dev}.service" 2>/dev/null || true
    log "ejected $node from $mp"
    ;;
  repair)
    fstype="$(blkid -o value -s TYPE "$node" 2>/dev/null || true)"
    [ -n "$fstype" ] || { echo "No filesystem detected on $node — nothing to repair." >&2; exit 1; }
    mp="$(findmnt -n -o TARGET --source "$node" 2>/dev/null || true)"
    if [ -n "$mp" ]; then
      sync
      umount "$mp" || { echo "Drive is busy — stop playback from it and retry." >&2; exit 1; }
      rmdir "$mp" 2>/dev/null || true
    fi
    # Exit codes: fsck-family tools return 1 (and e2fsck 2) after *fixing*
    # errors — that is a success for our purposes, so tolerate those.
    case "$fstype" in
      ntfs|ntfs3)     ntfsfix -d "$node" ;;
      vfat)           fsck.vfat -a "$node" || [ $? -le 1 ] ;;
      exfat)          fsck.exfat -y "$node" || [ $? -le 1 ] ;;
      ext2|ext3|ext4) e2fsck -f -p "$node" || [ $? -le 2 ] ;;
      *) echo "No repair tool for filesystem type: $fstype" >&2; exit 1 ;;
    esac
    log "repaired $node ($fstype)"
    # Remount through the systemd unit so ownership options come from its
    # DECKPILOT_USER environment, same as a fresh plug-in.
    systemctl restart "deckpilot-usb-mount@${dev}.service" 2>/dev/null || "$0" mount "$dev"
    ;;
esac
EOF
  $SUDO chmod 755 "$helper_path"
  $SUDO chown root:root "$helper_path"

  # The web UI's safe-eject / repair buttons call this helper as root; the
  # helper validates its device argument, so this is the whole surface.
  local sudoers_path="/etc/sudoers.d/91-deckpilot-usb-maintenance"
  $SUDO mkdir -p /etc/sudoers.d
  $SUDO tee "$sudoers_path" >/dev/null <<EOF
$RUN_USER ALL=(root) NOPASSWD: $helper_path
EOF
  $SUDO chmod 440 "$sudoers_path"

  $SUDO tee "$unit_path" >/dev/null <<EOF
[Unit]
Description=DeckPilot USB auto-mount for /dev/%i
Requires=dev-%i.device
BindsTo=dev-%i.device
After=dev-%i.device

[Service]
Type=oneshot
RemainAfterExit=yes
Environment=DECKPILOT_USER=$RUN_USER
ExecStart=$helper_path mount %i
ExecStop=$helper_path unmount %i
EOF

  $SUDO tee "$rules_path" >/dev/null <<'EOF'
# DeckPilot: auto-mount USB filesystem volumes under /media/deckpilot/<label>.
ACTION=="add", SUBSYSTEM=="block", SUBSYSTEMS=="usb", ENV{ID_FS_USAGE}=="filesystem", ENV{SYSTEMD_WANTS}+="deckpilot-usb-mount@%k.service", TAG+="systemd"
EOF

  $SUDO systemctl daemon-reload
  $SUDO udevadm control --reload-rules 2>/dev/null || true
  # Replay add events so drives already plugged in get mounted now, no reboot.
  $SUDO udevadm trigger --subsystem-match=block --action=add 2>/dev/null || true
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

configure_samba() {
  # Share the clips folder over SMB so an operator can drop files straight from
  # a laptop. The watch folder then ingests them progressively as each finishes
  # copying. Guest access keeps it friction-free on a trusted production LAN;
  # `force user` makes every drop land owned by the app so it can conform/delete.
  command_exists apt-get || return 0
  local clips_dir="$INSTALL_DIR/runtime/clips"
  $SUDO mkdir -p "$clips_dir"
  $SUDO chown -R "$RUN_USER" "$clips_dir" 2>/dev/null || true

  if ! command_exists smbd; then
    $SUDO apt-get install -y samba >/dev/null 2>&1 || return 0
  fi

  local smb_conf="/etc/samba/smb.conf"
  [[ -f "$smb_conf" ]] || $SUDO touch "$smb_conf"
  # Idempotent: strip any previous DeckPilot block before appending a fresh one,
  # so re-running the installer (or changing the path) never duplicates it.
  $SUDO sed -i '/# >>> DeckPilot share >>>/,/# <<< DeckPilot share <<</d' "$smb_conf" 2>/dev/null || true
  $SUDO tee -a "$smb_conf" >/dev/null <<EOF
# >>> DeckPilot share >>>
[global]
   map to guest = Bad User
   server min protocol = SMB2

[DeckPilot]
   comment = DeckPilot clips
   path = $clips_dir
   browseable = yes
   read only = no
   guest ok = yes
   force user = $RUN_USER
   create mask = 0664
   directory mask = 0775
# <<< DeckPilot share <<<
EOF

  # Reject a broken config rather than leaving smbd down.
  if command_exists testparm && ! $SUDO testparm -s "$smb_conf" >/dev/null 2>&1; then
    warn "Samba config check failed; SMB share not enabled."
    return 0
  fi
  $SUDO systemctl enable smbd >/dev/null 2>&1 || true
  $SUDO systemctl restart smbd >/dev/null 2>&1 || true
  # nmbd advertises the host over NetBIOS so it shows up in network browsers.
  $SUDO systemctl restart nmbd >/dev/null 2>&1 || true
}

install_systemd_service() {
  command_exists systemctl || return 0
  local service_name="deckpilot.service"
  local service_path="/etc/systemd/system/$service_name"

  # On a Pi/SBC, mpv runs under cage (see write_config). cage acquires the DRM
  # seat via seatd and needs a writable XDG_RUNTIME_DIR for its Wayland socket;
  # seatd must be running first.
  local svc_groups="audio video render input"
  local svc_after=""
  local svc_extra=""
  if is_linux_sbc; then
    svc_after=" seatd.service"
    svc_extra=$'RuntimeDirectory=deckpilot\nRuntimeDirectoryMode=0700\nEnvironment=XDG_RUNTIME_DIR=/run/deckpilot\n'
    $SUDO systemctl enable --now seatd 2>/dev/null || true
    # Raspberry Pi OS runs `seatd -g video`, so the `video` group above already
    # grants seat access. Some distros use a dedicated `_seatd` group instead —
    # add it only if it exists, else systemd fails with status=216/GROUP.
    if getent group _seatd >/dev/null 2>&1; then
      svc_groups="$svc_groups _seatd"
    fi
  fi

  $SUDO tee "$service_path" >/dev/null <<EOF
[Unit]
Description=DeckPilot HyperDeck Emulator
# network.target (not network-online.target): waiting for *-wait-online can
# stall boot by 60-120s on a Pi with slow DHCP; DeckPilot binds 0.0.0.0 and
# does not need the network to be fully up.
After=network.target${svc_after}

[Service]
Type=simple
User=$RUN_USER
# Lift the whole playback chain above everything else on the Pi: this process
# spawns cage, cage spawns mpv, and both inherit this niceness, so decode and
# render always win the CPU. Background ffmpeg enrichment renices itself +19
# *relative* in-process, landing well below this (~14) — never starving mpv.
Nice=-5
# A playout deck must not be the OOM killer's first pick on a 1 GB Pi 3 when a
# large import spikes memory; bias the killer firmly away from it.
OOMScoreAdjust=-400
SupplementaryGroups=$svc_groups
WorkingDirectory=$INSTALL_DIR
${svc_extra}Environment=PIDECK_CONFIG=$INSTALL_DIR/config.json
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
  install_usb_automount
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
After=network.target
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
  if [[ "${DO_SMB:-no}" == "yes" ]]; then
    box_line "  SMB drop      \\\\$host_display\\DeckPilot" "$C_CYAN"
  fi
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
DO_SMB="no"
if [[ "$OS_NAME" == "linux" ]] && command_exists systemctl; then
  if [[ "$SERVICE_MODE" == "yes" ]] || { [[ "$SERVICE_MODE" == "ask" ]] && ask_yes_no "Install DeckPilot as a systemd service?" "y"; }; then
    DO_SERVICE="yes"
  fi
  # Share the clips folder over SMB by default on Linux (apt only); it's the
  # main way operators drop files onto an appliance.
  if command_exists apt-get; then
    if [[ "$SMB_MODE" == "no" ]]; then
      DO_SMB="no"
    elif [[ "$SMB_MODE" == "yes" ]] || { [[ "$SMB_MODE" == "ask" ]] && ask_yes_no "Share the clips folder over SMB (network drop)?" "y"; }; then
      DO_SMB="yes"
    fi
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
[[ "$DO_SMB" == "yes" ]] && TOTAL_STEPS=$((TOTAL_STEPS + 1))

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
[[ "$DO_SMB" == "yes" ]] && run_step "SMB clip share" configure_samba

print_summary
