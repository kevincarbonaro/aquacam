#!/usr/bin/env bash
set -euo pipefail

REPO_TARBALL_URL_DEFAULT="https://github.com/kevincarbonaro/aquacam/archive/refs/heads/main.tar.gz"
DEFAULT_INSTALL_DIR="$HOME/aquacam-stream-ytapi"

say() { printf '\n==> %s\n' "$*"; }
warn() { printf '\nWARNING: %s\n' "$*" >&2; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

ask() {
  local prompt="$1" default="${2:-}" answer
  if [[ -n "$default" ]]; then
    read -r -p "$prompt [$default]: " answer || true
    printf '%s' "${answer:-$default}"
  else
    read -r -p "$prompt: " answer || true
    printf '%s' "$answer"
  fi
}

ask_yes_no() {
  local prompt="$1" default="${2:-y}" answer suffix
  case "$default" in
    y|Y|yes|YES) suffix="Y/n"; default="y" ;;
    n|N|no|NO) suffix="y/N"; default="n" ;;
    *) suffix="y/n" ;;
  esac
  while true; do
    read -r -p "$prompt [$suffix]: " answer || true
    answer="${answer:-$default}"
    case "$answer" in
      y|Y|yes|YES) return 0 ;;
      n|N|no|NO) return 1 ;;
      *) echo "Please answer yes or no." ;;
    esac
  done
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

replace_or_append() {
  local file="$1" key="$2" value="$3" escaped
  escaped="$(printf '%s' "$value" | sed 's/[&|\\]/\\&/g')"
  if grep -qE "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=\"${escaped}\"|" "$file"
  else
    printf '%s="%s"\n' "$key" "$value" >> "$file"
  fi
}

replace_or_append_raw() {
  local file="$1" key="$2" value="$3"
  if grep -qE "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}

main() {
  [[ "${BASH_VERSION:-}" ]] || fail "Run this script with bash, not sh."
  require_cmd sudo
  require_cmd sed
  require_cmd awk

  local pi_user install_dir repo_url tmpdir src_dir config service_tmp sudoers_tmp
  pi_user="$(id -un)"

  say "AquaCam installer"
  echo "This installs AquaCam for the current user: $pi_user"
  echo "It will install apt packages, download the AquaCam project, create a Python venv, write config, and optionally install systemd."

  install_dir="$(ask "Install directory" "$DEFAULT_INSTALL_DIR")"
  repo_url="$(ask "AquaCam GitHub tarball URL" "$REPO_TARBALL_URL_DEFAULT")"

  say "Collecting stream settings"
  local video_device input_format framerate video_size video_encoder video_bitrate maxrate bufsize gop audio_bitrate audio_rate
  video_device="$(ask "Video device" "/dev/video0")"
  input_format="$(ask "Input format" "mjpeg")"
  framerate="$(ask "Framerate" "30")"
  video_size="$(ask "Video size" "640x480")"
  video_encoder="$(ask "Video encoder" "libx264")"
  video_bitrate="$(ask "Video bitrate" "1200k")"
  maxrate="$(ask "Max bitrate" "$video_bitrate")"
  bufsize="$(ask "Buffer size" "2400k")"
  gop="$(ask "GOP/keyframe interval" "60")"
  audio_bitrate="$(ask "Audio bitrate" "128k")"
  audio_rate="$(ask "Audio sample rate" "44100")"

  say "Collecting schedule/power settings"
  local timezone start_time stop_time check_interval shutdown_after_stop shutdown_time shutdown_delay
  timezone="$(ask "Timezone" "Europe/Malta")"
  start_time="$(ask "Daily start time HH:MM" "08:30")"
  stop_time="$(ask "Daily stop time HH:MM" "20:30")"
  check_interval="$(ask "Supervisor check interval seconds" "60")"
  if ask_yes_no "Shutdown Pi after stop window" "y"; then
    shutdown_after_stop="true"
    shutdown_time="$(ask "Shutdown time HH:MM" "20:35")"
    shutdown_delay="$(ask "Shutdown delay seconds if no shutdown time is used" "60")"
  else
    shutdown_after_stop="false"
    shutdown_time=""
    shutdown_delay="300"
  fi

  say "Collecting YouTube metadata"
  local yt_title yt_description yt_tags yt_privacy yt_category yt_stream_title yt_latency made_for_kids enable_dvr enable_embed enable_auto_start enable_auto_stop
  yt_title="$(ask "Broadcast title template" "AquaCam Live - {date}")"
  yt_description="$(ask "Broadcast description" "Live aquarium camera.")"
  yt_tags="$(ask "Broadcast tags comma-separated" "aquarium, aquatic, livestream, fish, water, pets, animals, relaxation")"
  yt_privacy="$(ask "Privacy status: public, unlisted, or private" "public")"
  yt_category="$(ask "YouTube category ID" "15")"
  yt_stream_title="$(ask "Reusable stream title" "AquaCam reusable stream")"
  yt_latency="$(ask "Latency preference: normal, low, ultraLow" "low")"
  ask_yes_no "Made for kids" "n" && made_for_kids="true" || made_for_kids="false"
  ask_yes_no "Enable DVR" "y" && enable_dvr="true" || enable_dvr="false"
  ask_yes_no "Enable embed" "y" && enable_embed="true" || enable_embed="false"
  ask_yes_no "Enable YouTube auto-start" "y" && enable_auto_start="true" || enable_auto_start="false"
  ask_yes_no "Enable YouTube auto-stop" "y" && enable_auto_stop="true" || enable_auto_stop="false"

  say "YouTube API / stream key"
  local yt_api_enabled client_secret_source direct_stream_key
  if ask_yes_no "Use YouTube Data API automation" "y"; then
    yt_api_enabled="true"
    client_secret_source="$(ask "Path to OAuth client_secret.json on this Pi, or leave blank to copy later" "")"
  else
    yt_api_enabled="false"
    direct_stream_key=""
    if ask_yes_no "Enter a YouTube stream key now for direct RTMP mode" "n"; then
      read -r -s -p "YouTube stream key (hidden): " direct_stream_key || true
      printf '\n'
    fi
  fi

  say "Installing system packages"
  sudo apt update
  sudo apt install -y curl tar rsync ffmpeg v4l-utils python3 python3-pip python3-venv
  sudo timedatectl set-timezone "$timezone" || warn "Could not set timezone; continuing."

  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' EXIT

  say "Downloading AquaCam from GitHub"
  require_cmd curl
  curl -fsSL "$repo_url" -o "$tmpdir/aquacam.tar.gz"
  tar -xzf "$tmpdir/aquacam.tar.gz" -C "$tmpdir"
  src_dir="$(find "$tmpdir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [[ -d "$src_dir" ]] || fail "Could not find extracted AquaCam source directory."

  say "Copying files to $install_dir"
  mkdir -p "$install_dir"
  rsync -a \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='backups' \
    --exclude='scratch' \
    --exclude='json' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.log' \
    --exclude='stream.key' \
    --exclude='token.json' \
    --exclude='client_secret*.json' \
    --exclude='broadcast.id' \
    --exclude='stream.id' \
    --exclude='thumbnail_set.id' \
    "$src_dir/" "$install_dir/"

  cd "$install_dir"
  cp -f configs/aquacam-stream.conf.example aquacam-stream.conf
  cp -f scripts/start_stream.sh ./start_stream.sh
  cp -f scripts/ytapi_prepare_broadcast.py ./ytapi_prepare_broadcast.py
  if [[ -f scripts/ytapi_end_broadcast.py ]]; then
    cp -f scripts/ytapi_end_broadcast.py ./ytapi_end_broadcast.py
  fi
  cp -f assets/the-calm-aquarium-thumbnail.png ./the-calm-aquarium-thumbnail.png
  chmod +x start_stream.sh ytapi_prepare_broadcast.py
  [[ -f ytapi_end_broadcast.py ]] && chmod +x ytapi_end_broadcast.py
  [[ -f webmgr/start_webmgr.sh ]] && chmod +x webmgr/start_webmgr.sh

  say "Creating Python virtual environment"
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt

  say "Writing AquaCam config"
  config="$install_dir/aquacam-stream.conf"
  sed -i "s|/home/<PI_USER>/aquacam-stream-ytapi|$install_dir|g" "$config"
  replace_or_append "$config" STREAM_KEY_FILE "$install_dir/stream.key"
  replace_or_append "$config" VIDEO_DEVICE "$video_device"
  replace_or_append "$config" INPUT_FORMAT "$input_format"
  replace_or_append "$config" FRAMERATE "$framerate"
  replace_or_append "$config" VIDEO_SIZE "$video_size"
  replace_or_append "$config" VIDEO_ENCODER "$video_encoder"
  replace_or_append "$config" VIDEO_BITRATE "$video_bitrate"
  replace_or_append "$config" MAXRATE "$maxrate"
  replace_or_append "$config" BUFSIZE "$bufsize"
  replace_or_append "$config" GOP "$gop"
  replace_or_append "$config" AUDIO_BITRATE "$audio_bitrate"
  replace_or_append "$config" AUDIO_RATE "$audio_rate"
  replace_or_append "$config" START_TIME "$start_time"
  replace_or_append "$config" STOP_TIME "$stop_time"
  replace_or_append "$config" CHECK_INTERVAL "$check_interval"
  replace_or_append "$config" SHUTDOWN_AFTER_STOP "$shutdown_after_stop"
  replace_or_append "$config" SHUTDOWN_TIME "$shutdown_time"
  replace_or_append "$config" SHUTDOWN_DELAY_SECONDS "$shutdown_delay"
  replace_or_append "$config" LOG_FILE "$install_dir/stream.log"
  replace_or_append "$config" YT_API_ENABLED "$yt_api_enabled"
  replace_or_append "$config" PYTHON_BIN "$install_dir/.venv/bin/python"
  replace_or_append "$config" YT_API_PREPARE_SCRIPT "$install_dir/ytapi_prepare_broadcast.py"
  [[ -f "$install_dir/ytapi_end_broadcast.py" ]] && replace_or_append "$config" YT_API_END_SCRIPT "$install_dir/ytapi_end_broadcast.py"
  replace_or_append "$config" YT_CLIENT_SECRETS "$install_dir/client_secret.json"
  replace_or_append "$config" YT_TOKEN_FILE "$install_dir/token.json"
  replace_or_append "$config" YT_BROADCAST_ID_FILE "$install_dir/broadcast.id"
  replace_or_append "$config" YT_STREAM_ID_FILE "$install_dir/stream.id"
  replace_or_append "$config" YT_THUMBNAIL_FILE "$install_dir/the-calm-aquarium-thumbnail.png"
  replace_or_append "$config" YT_THUMBNAIL_SET_ID_FILE "$install_dir/thumbnail_set.id"
  replace_or_append "$config" YT_TIMEZONE "$timezone"
  replace_or_append "$config" YT_PRIVACY_STATUS "$yt_privacy"
  replace_or_append "$config" YT_BROADCAST_TITLE "$yt_title"
  replace_or_append "$config" YT_BROADCAST_DESCRIPTION "$yt_description"
  replace_or_append "$config" YT_BROADCAST_TAGS "$yt_tags"
  replace_or_append "$config" YT_STREAM_TITLE "$yt_stream_title"
  replace_or_append "$config" YT_CATEGORY_ID "$yt_category"
  replace_or_append "$config" YT_LATENCY_PREFERENCE "$yt_latency"
  replace_or_append "$config" YT_SELF_DECLARED_MADE_FOR_KIDS "$made_for_kids"
  replace_or_append "$config" YT_ENABLE_DVR "$enable_dvr"
  replace_or_append "$config" YT_ENABLE_EMBED "$enable_embed"
  replace_or_append "$config" YT_ENABLE_AUTO_START "$enable_auto_start"
  replace_or_append "$config" YT_ENABLE_AUTO_STOP "$enable_auto_stop"

  if [[ "${yt_api_enabled}" == "true" && -n "${client_secret_source:-}" ]]; then
    [[ -f "$client_secret_source" ]] || fail "client_secret.json not found: $client_secret_source"
    install -m 600 "$client_secret_source" "$install_dir/client_secret.json"
  fi

  if [[ "${yt_api_enabled}" == "false" && -n "${direct_stream_key:-}" ]]; then
    umask 077
    printf '%s\n' "$direct_stream_key" > "$install_dir/stream.key"
    chmod 600 "$install_dir/stream.key"
  fi

  say "Verifying scripts"
  bash -n "$install_dir/start_stream.sh"
  [[ -f "$install_dir/webmgr/start_webmgr.sh" ]] && bash -n "$install_dir/webmgr/start_webmgr.sh"
  [[ -f "$install_dir/webmgr/app.py" ]] && python3 -m py_compile "$install_dir/webmgr/app.py"
  .venv/bin/python -m py_compile "$install_dir/ytapi_prepare_broadcast.py"
  [[ -f "$install_dir/ytapi_end_broadcast.py" ]] && .venv/bin/python -m py_compile "$install_dir/ytapi_end_broadcast.py"

  if [[ "${yt_api_enabled}" == "true" && -f "$install_dir/client_secret.json" ]]; then
    if ask_yes_no "Run YouTube OAuth/API preparation now" "n"; then
      warn "If this Pi is headless, create an SSH tunnel first from your computer: ssh -L 8080:localhost:8080 $pi_user@<pi-hostname-or-ip>"
      "$install_dir/.venv/bin/python" "$install_dir/ytapi_prepare_broadcast.py" --config "$config"
      chmod 600 "$install_dir/token.json" "$install_dir/stream.key" 2>/dev/null || true
    fi
  else
    warn "YouTube API credentials were not completed now. Copy client_secret.json later and run: cd '$install_dir' && .venv/bin/python ytapi_prepare_broadcast.py --config ./aquacam-stream.conf"
  fi

  if [[ "$shutdown_after_stop" == "true" ]] && ask_yes_no "Install sudoers rule for unattended shutdown" "y"; then
    sudoers_tmp="$tmpdir/aquacam-shutdown"
    sed "s|<PI_USER>|$pi_user|g" "$install_dir/sudoers/aquacam-shutdown.sudoers" > "$sudoers_tmp"
    sudo install -m 440 "$sudoers_tmp" /etc/sudoers.d/aquacam-shutdown
    sudo visudo -cf /etc/sudoers.d/aquacam-shutdown
  fi

  if ask_yes_no "Install systemd service" "y"; then
    service_tmp="$tmpdir/aquacam-ytapi.service"
    sed "s|<PI_USER>|$pi_user|g" "$install_dir/systemd/aquacam-ytapi.service" > "$service_tmp"
    # The template assumes /home/<PI_USER>/aquacam-stream-ytapi. Support custom install_dir too.
    sed -i "s|/home/$pi_user/aquacam-stream-ytapi|$install_dir|g" "$service_tmp"
    sudo install -m 644 "$service_tmp" /etc/systemd/system/aquacam-ytapi.service
    sudo systemctl daemon-reload
    if ask_yes_no "Enable service at boot" "y"; then
      sudo systemctl enable aquacam-ytapi.service
    fi
    if ask_yes_no "Start service now (this may go live if stream.key exists and the schedule is active)" "n"; then
      sudo systemctl restart aquacam-ytapi.service
      sudo systemctl status aquacam-ytapi.service --no-pager || true
    else
      echo "Service installed but not started. Start later with: sudo systemctl start aquacam-ytapi.service"
    fi
  fi

  if [[ -f "$install_dir/webmgr/app.py" ]] && ask_yes_no "Install lightweight web settings manager" "y"; then
    local web_service_tmp
    web_service_tmp="$tmpdir/aquacam-webmgr.service"
    sed "s|<PI_USER>|$pi_user|g" "$install_dir/systemd/aquacam-webmgr.service" > "$web_service_tmp"
    sed -i "s|/home/$pi_user/aquacam-stream-ytapi|$install_dir|g" "$web_service_tmp"
    sudo install -m 644 "$web_service_tmp" /etc/systemd/system/aquacam-webmgr.service
    sudo systemctl daemon-reload
    sudo systemctl enable aquacam-webmgr.service
    if ask_yes_no "Start web manager now" "y"; then
      sudo systemctl restart aquacam-webmgr.service
      sudo systemctl status aquacam-webmgr.service --no-pager || true
    fi
    echo "Web manager URL: http://<this-pi-ip>:8080/"
    echo "First visit creates the admin username/password. Do not expose this LAN-only HTTP service to the internet."
  fi

  say "Install complete"
  echo "Install directory: $install_dir"
  echo "Config file: $config"
  echo "Log file: $install_dir/stream.log"
  echo "Check camera: v4l2-ctl --list-devices"
  echo "Check service: systemctl status aquacam-ytapi.service --no-pager"
}

main "$@"
