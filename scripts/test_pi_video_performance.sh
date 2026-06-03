#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${1:-${SCRIPT_DIR}/aquacam-stream.conf}"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Missing config: $CONFIG_FILE" >&2
  echo "Usage: $0 /path/to/aquacam-stream.conf" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$CONFIG_FILE"

VIDEO_DEVICE="${VIDEO_DEVICE:-/dev/video0}"
INPUT_FORMAT="${INPUT_FORMAT:-mjpeg}"
FRAMERATE="${FRAMERATE:-30}"
AUDIO_RATE="${AUDIO_RATE:-44100}"
GOP="${GOP:-60}"
VIDEO_BITRATE="${VIDEO_BITRATE:-1200k}"
MAXRATE="${MAXRATE:-$VIDEO_BITRATE}"
BUFSIZE="${BUFSIZE:-2400k}"
TEST_SECONDS="${TEST_SECONDS:-90}"
TEST_LOG_DIR="${TEST_LOG_DIR:-/tmp/aquacam-perf}"
TEST_SIZES="${TEST_SIZES:-640x480 854x480 1280x720}"
TEST_PRESET="${TEST_PRESET:-ultrafast}"
TEST_REPORT="$TEST_LOG_DIR/report-$(date '+%Y%m%d-%H%M%S').txt"

mkdir -p "$TEST_LOG_DIR"

log() {
  echo "$*" | tee -a "$TEST_REPORT"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

sample_process() {
  local pid="$1" samples="$2"
  while kill -0 "$pid" 2>/dev/null; do
    ps -p "$pid" -o %cpu=,%mem=,rss= >> "$samples" 2>/dev/null || true
    sleep 5
  done
}

summarise_samples() {
  local samples="$1"
  python3 - "$samples" <<'PY'
import sys
path = sys.argv[1]
rows = []
try:
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 3:
                try:
                    rows.append((float(parts[0]), float(parts[1]), int(parts[2])))
                except ValueError:
                    pass
except FileNotFoundError:
    pass
if not rows:
    print("cpu_avg=unknown cpu_max=unknown mem_avg=unknown rss_max_mb=unknown")
else:
    cpu = [r[0] for r in rows]
    mem = [r[1] for r in rows]
    rss = [r[2] / 1024 for r in rows]
    print(f"cpu_avg={sum(cpu)/len(cpu):.1f}% cpu_max={max(cpu):.1f}% mem_avg={sum(mem)/len(mem):.1f}% rss_max_mb={max(rss):.1f}")
PY
}

summarise_progress() {
  local progress="$1" seconds="$2"
  python3 - "$progress" "$seconds" <<'PY'
import sys
path = sys.argv[1]
seconds = float(sys.argv[2])
last = {}
try:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                last[k] = v
except FileNotFoundError:
    pass
frame = int(last.get("frame", "0") or 0)
drop = int(last.get("drop_frames", "0") or 0)
dup = int(last.get("dup_frames", "0") or 0)
speed = last.get("speed", "unknown")
fps = frame / seconds if seconds else 0
print(f"frames={frame} observed_fps={fps:.1f} drop_frames={drop} dup_frames={dup} speed={speed}")
PY
}

require_cmd ffmpeg
require_cmd ps
require_cmd python3

log "AquaCam Pi video performance test"
log "Date: $(date)"
log "Host: $(hostname)"
log "Config: $CONFIG_FILE"
log "Device: $VIDEO_DEVICE"
log "Input format: $INPUT_FORMAT"
log "Framerate: $FRAMERATE"
log "Test seconds per size: $TEST_SECONDS"
log "Sizes: $TEST_SIZES"
log "Bitrate: $VIDEO_BITRATE maxrate=$MAXRATE bufsize=$BUFSIZE preset=$TEST_PRESET"
log ""

if command -v v4l2-ctl >/dev/null 2>&1; then
  log "Camera-supported formats/resolutions:"
  v4l2-ctl --device "$VIDEO_DEVICE" --list-formats-ext 2>&1 | tee -a "$TEST_REPORT" || true
  log ""
fi

for size in $TEST_SIZES; do
  safe_size="${size//x/_}"
  ffmpeg_log="$TEST_LOG_DIR/ffmpeg-${safe_size}.log"
  progress_file="$TEST_LOG_DIR/progress-${safe_size}.txt"
  samples_file="$TEST_LOG_DIR/samples-${safe_size}.txt"
  rm -f "$ffmpeg_log" "$progress_file" "$samples_file"

  log "--- Testing $size ---"
  set +e
  /usr/bin/ffmpeg \
    -hide_banner \
    -nostdin \
    -stats \
    -fflags nobuffer \
    -flags low_delay \
    -f lavfi -i "anullsrc=r=${AUDIO_RATE}:cl=stereo" \
    -f v4l2 -input_format "$INPUT_FORMAT" -framerate "$FRAMERATE" -video_size "$size" -i "$VIDEO_DEVICE" \
    -t "$TEST_SECONDS" \
    -shortest \
    -c:v libx264 \
    -preset "$TEST_PRESET" \
    -tune zerolatency \
    -pix_fmt yuv420p \
    -g "$GOP" \
    -b:v "$VIDEO_BITRATE" \
    -maxrate "$MAXRATE" \
    -bufsize "$BUFSIZE" \
    -c:a aac \
    -b:a "${AUDIO_BITRATE:-128k}" \
    -ar "$AUDIO_RATE" \
    -f flv \
    -progress "$progress_file" \
    -y \
    /dev/null > "$ffmpeg_log" 2>&1 &
  ffmpeg_pid=$!
  sample_process "$ffmpeg_pid" "$samples_file" &
  sampler_pid=$!
  wait "$ffmpeg_pid"
  rc=$?
  kill "$sampler_pid" 2>/dev/null || true
  wait "$sampler_pid" 2>/dev/null || true
  set -e

  log "exit_code=$rc"
  log "$(summarise_progress "$progress_file" "$TEST_SECONDS")"
  log "$(summarise_samples "$samples_file")"

  if [[ "$rc" -ne 0 ]]; then
    log "ffmpeg_error_tail:"
    tail -n 20 "$ffmpeg_log" | tee -a "$TEST_REPORT" || true
  else
    log "ffmpeg_log=$ffmpeg_log"
  fi
  log ""
done

log "Report saved to: $TEST_REPORT"
log "Rule of thumb: 16:9 is healthy only if observed_fps is close to $FRAMERATE, speed is >=1.0x, CPU is not pinned near 100% per core, and drop_frames stays at 0/very low."
