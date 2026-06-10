#!/usr/bin/env bash
# DeckPilot boot diagnosis — find out why the Pi takes long to start.
# Read-only: prints findings and the exact commands to fix them.
set -uo pipefail

C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'
if [[ ! -t 1 ]] || [[ -n "${NO_COLOR:-}" ]]; then
  C_RESET=""; C_BOLD=""; C_DIM=""; C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""
fi

section() { printf '\n%s%s%s\n' "$C_BOLD" "$1" "$C_RESET"; }
finding() { printf '  %s▲%s %s\n' "$C_YELLOW" "$C_RESET" "$1"; }
ok()      { printf '  %s✔%s %s\n' "$C_GREEN" "$C_RESET" "$1"; }
tip()     { printf '    %s$ %s%s\n' "$C_DIM" "$1" "$C_RESET"; }

if ! command -v systemd-analyze >/dev/null 2>&1; then
  echo "systemd-analyze is not available — this script targets the Raspberry Pi (systemd) install." >&2
  exit 1
fi

printf '%sDECKPILOT BOOT DIAGNOSIS%s  %s%s%s\n' "$C_BOLD$C_CYAN" "$C_RESET" "$C_DIM" "$(hostname 2>/dev/null)" "$C_RESET"

section "Total boot time"
systemd-analyze 2>/dev/null | sed 's/^/  /'

section "Top 12 slowest units"
systemd-analyze blame 2>/dev/null | head -12 | sed 's/^/  /'

section "Critical chain to DeckPilot"
systemd-analyze critical-chain deckpilot.service 2>/dev/null | sed 's/^/  /' \
  || echo "  deckpilot.service not found (manual install?)"

section "Known boot-time offenders"
FOUND_ISSUE=0

for unit in NetworkManager-wait-online.service systemd-networkd-wait-online.service; do
  if systemctl is-enabled "$unit" >/dev/null 2>&1; then
    duration="$(systemd-analyze blame 2>/dev/null | grep -F "$unit" | awk '{print $1}')"
    finding "$unit is enabled${duration:+ (cost: $duration)} — it blocks boot until DHCP completes."
    tip "sudo systemctl disable $unit"
    FOUND_ISSUE=1
  fi
done

if grep -q 'network-online.target' /etc/systemd/system/deckpilot.service 2>/dev/null; then
  finding "deckpilot.service still waits for network-online.target (old unit file)."
  tip "re-run the bootstrap installer, or edit the unit: After=network.target, then 'sudo systemctl daemon-reload'"
  FOUND_ISSUE=1
else
  ok "deckpilot.service does not wait for network-online."
fi

if systemctl is-enabled dphys-swapfile.service >/dev/null 2>&1; then
  duration="$(systemd-analyze blame 2>/dev/null | grep -F 'dphys-swapfile' | awk '{print $1}')"
  [[ -n "$duration" ]] && finding "dphys-swapfile costs $duration at boot (swap on SD also wears the card)." && \
    tip "sudo systemctl disable dphys-swapfile.service   # if you have enough RAM headroom"
fi

if [[ -f /boot/config.txt ]] || [[ -f /boot/firmware/config.txt ]]; then
  cfg=/boot/config.txt; [[ -f /boot/firmware/config.txt ]] && cfg=/boot/firmware/config.txt
  if ! grep -q '^boot_delay=0' "$cfg" 2>/dev/null; then
    finding "firmware boot_delay not set to 0 (default adds ~1s)."
    tip "echo 'boot_delay=0' | sudo tee -a $cfg"
  fi
  if ! grep -q '^disable_splash=1' "$cfg" 2>/dev/null; then
    finding "rainbow splash enabled (~0.5s)."
    tip "echo 'disable_splash=1' | sudo tee -a $cfg"
  fi
fi

[[ $FOUND_ISSUE -eq 0 ]] && ok "no classic offender detected — check the blame list above."

section "DeckPilot service timing"
systemctl show deckpilot.service --property=ExecMainStartTimestamp --value 2>/dev/null | sed 's/^/  started: /'
journalctl -u deckpilot.service -b --no-pager 2>/dev/null | grep -F 'DeckPilot ready in' | tail -1 | sed 's/^/  /'

printf '\n%sRe-run after a reboot to compare. Nothing was modified.%s\n\n' "$C_DIM" "$C_RESET"
