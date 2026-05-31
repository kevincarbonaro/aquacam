#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/aquacam-stream.conf"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Missing config: $CONFIG_FILE" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$CONFIG_FILE"

: "${STREAM_URL:?missing STREAM_URL}"
PROGRESS_FILE="${PROGRESS_FILE:-/tmp/aquacam-ffmpeg.progress}"
STUCK_TIMEOUT_SECONDS="${STUCK_TIMEOUT_SECONDS:-480}"
WARM_RESTART_AFTER_SECONDS="${WARM_RESTART_AFTER_SECONDS:-60}"
WARM_RESTART_ENABLED="${WARM_RESTART_ENABLED:-true}"

: "${STREAM_KEY_FILE:?missing STREAM_KEY_FILE}"
: "${LOG_FILE:?missing LOG_FILE}"

STREAM_KEY="$(cat "$STREAM_KEY_FILE")"
retry_count=0
ffmpeg_pid=""
last_total_size=0
last_progress_ts=0
warm_restart_done=false
launch_ts=0

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

time_to_minutes() {
  local t="$1"
  local h="${t%%:*}" m="${t##*:}"
  printf '%d' "$((10#$h * 60 + 10#$m))"
}

now_minutes() {
  date +%H:%M | awk -F: '{print ($1*60)+$2}'
}

in_stream_window() {
  [[ -z "${START_TIME:-}" || -z "${STOP_TIME:-}" ]] && return 0
  local now start stop
  now="$(now_minutes)"
  start="$(time_to_minutes "$START_TIME")"
  stop="$(time_to_minutes "$STOP_TIME")"

  if (( start < stop )); then
    (( now >= start && now < stop ))
  else
    # window spans midnight, e.g. 22:00 -> 06:00
    (( now >= start || now < stop ))
  fi
}

maybe_shutdown_after_stop() {
  if [[ "${SHUTDOWN_AFTER_STOP:-false}" != "true" ]] || [[ -z "${START_TIME:-}" ]] || [[ -z "${STOP_TIME:-}" ]]; then
    return 0
  fi
  if in_stream_window; then
    return 0
  fi

  local now stop_min shutdown_min wait_s
  now="$(now_minutes)"
  stop_min="$(time_to_minutes "$STOP_TIME")"

  if [[ -n "${SHUTDOWN_TIME:-}" ]]; then
    shutdown_min="$(time_to_minutes "$SHUTDOWN_TIME")"
    if (( now >= shutdown_min )); then
      wait_s=0
    elif (( now >= stop_min )); then
      wait_s=$(( (shutdown_min - now) * 60 ))
    else
      return 0
    fi
    log "Outside stream window (${START_TIME}-${STOP_TIME}). Shutdown target ${SHUTDOWN_TIME}. Waiting ${wait_s}s."
  else
    wait_s="${SHUTDOWN_DELAY_SECONDS:-300}"
    log "Outside stream window (${START_TIME}-${STOP_TIME}). Scheduling shutdown in ${wait_s}s."
  fi

  sleep "$wait_s"
  sudo /sbin/shutdown -h now
}

is_stream_stuck() {
  [[ -f "$PROGRESS_FILE" ]] || return 1
  local now total
  now=$(date +%s)
  total=$(awk -F= '/^total_size=/{v=$2} END{print v+0}' "$PROGRESS_FILE" 2>/dev/null || echo 0)
  [[ -n "$total" ]] || total=0

  if (( total > last_total_size )); then
    last_total_size=$total
    last_progress_ts=$now
    return 1
  fi

  if (( last_progress_ts == 0 )); then
    last_progress_ts=$now
    return 1
  fi

  (( (now - last_progress_ts) >= STUCK_TIMEOUT_SECONDS )) && return 0
  return 1
}

reset_progress_file() {
  : > "$PROGRESS_FILE"
  last_total_size=0
  last_progress_ts=0
}

stop_ffmpeg() {
  if [[ -n "$ffmpeg_pid" ]] && kill -0 "$ffmpeg_pid" 2>/dev/null; then
    kill "$ffmpeg_pid" 2>/dev/null || true
    wait "$ffmpeg_pid" 2>/dev/null || true
  fi
}

cleanup() {
  log "Signal received. Stopping stream cleanly."
  stop_ffmpeg
  exit 0
}
trap cleanup SIGINT SIGTERM

launch_ffmpeg() {
  /usr/bin/ffmpeg \
    -fflags nobuffer \
    -flags low_delay \
    -f lavfi -i anullsrc=r=${AUDIO_RATE}:cl=stereo \
    -f v4l2 -input_format "${INPUT_FORMAT}" -framerate "${FRAMERATE}" -video_size "${VIDEO_SIZE}" -i "${VIDEO_DEVICE}" \
    -shortest \
    -c:v libx264 \
    -preset ultrafast \
    -tune zerolatency \
    -pix_fmt yuv420p \
    -g "${GOP}" \
    -b:v "${VIDEO_BITRATE}" \
    -maxrate "${MAXRATE}" \
    -bufsize "${BUFSIZE}" \
    -c:a aac \
    -b:a "${AUDIO_BITRATE}" \
    -ar "${AUDIO_RATE}" \
    -f flv \
    -progress "$PROGRESS_FILE" \
    "${STREAM_URL}/${STREAM_KEY}" >> "$LOG_FILE" 2>&1 &
  ffmpeg_pid=$!
}

log "Starting AquaCam stream supervisor"

while true; do
  if ! in_stream_window; then
    log "Outside schedule window. Waiting ${CHECK_INTERVAL}s."
    maybe_shutdown_after_stop
    sleep "${CHECK_INTERVAL:-20}"
    continue
  fi

  log "Launching FFmpeg (attempt $((retry_count + 1)))"
  reset_progress_file
  launch_ffmpeg
  launch_ts=$(date +%s)

  while kill -0 "$ffmpeg_pid" 2>/dev/null; do
    if ! in_stream_window; then
      log "Reached STOP_TIME window. Stopping FFmpeg cleanly."
      stop_ffmpeg
      maybe_shutdown_after_stop
      break
    fi
    if [[ "$WARM_RESTART_ENABLED" == "true" && "$warm_restart_done" == "false" ]]; then
      now_ts=$(date +%s)
      if (( (now_ts - launch_ts) >= WARM_RESTART_AFTER_SECONDS )); then
        log "Warm restart trigger reached (${WARM_RESTART_AFTER_SECONDS}s after launch). Restarting FFmpeg once to clear YouTube ingest/preparing stalls."
        warm_restart_done=true
        stop_ffmpeg
        break
      fi
    fi

    if is_stream_stuck; then
      log "Detected local stuck stream (no progress for ${STUCK_TIMEOUT_SECONDS}s). Restarting FFmpeg."
      stop_ffmpeg
      break
    fi
    sleep "${CHECK_INTERVAL:-20}"
  done

  wait "$ffmpeg_pid" 2>/dev/null || true
  exit_code=$?
  log "FFmpeg exited with code $exit_code"

  retry_count=$((retry_count + 1))
  if [[ "${MAX_RETRIES:-0}" != "0" ]] && (( retry_count >= MAX_RETRIES )); then
    log "Max retries reached (${MAX_RETRIES}). Exiting."
    exit 1
  fi

  log "Retrying in ${RETRY_DELAY}s"
  sleep "${RETRY_DELAY:-10}"
done