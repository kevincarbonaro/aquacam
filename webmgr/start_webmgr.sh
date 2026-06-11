#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
PID_FILE="webmgr/webmgr.pid"
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  exit 0
fi
export AQUACAM_CONFIG="${AQUACAM_CONFIG:-$PROJECT_DIR/aquacam-stream.conf}"
export AQUACAM_WEB_STATE="${AQUACAM_WEB_STATE:-$PROJECT_DIR/.aquacam-webmgr.json}"
export AQUACAM_WEB_HOST="${AQUACAM_WEB_HOST:-0.0.0.0}"
export AQUACAM_WEB_PORT="${AQUACAM_WEB_PORT:-8080}"
export AQUACAM_SERVICE="${AQUACAM_SERVICE:-aquacam-ytapi.service}"
nohup /usr/bin/python3 webmgr/app.py >> webmgr/webmgr.log 2>&1 &
echo $! > "$PID_FILE"
