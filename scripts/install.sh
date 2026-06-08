#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

"$SCRIPT_DIR/bootstrap.sh" --install-dir "/home/pi/pideck" --install-service --yes
