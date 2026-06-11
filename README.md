# AquaCam Pi Stream - YouTube API version

This is the recommended AquaCam implementation.

It streams a Raspberry Pi camera to YouTube with ffmpeg, but uses the YouTube Data API before ffmpeg starts. The API step prepares or reuses the correct YouTube Live broadcast, binds it to the saved reusable stream, applies the video template, uploads the thumbnail, and writes the current YouTube stream key locally for ffmpeg.

## Why this version exists

The original non-API version pushed RTMP directly to a manually configured YouTube Studio stream key. It worked most of the time, but sometimes YouTube stayed stuck on "Preparing stream" after the Pi booted in the morning. The practical workaround was to open YouTube Studio and/or reboot the Pi.

This API version fixes that workflow by preparing YouTube Live from the Pi before streaming starts.

## Features

- ffmpeg-based YouTube RTMP streaming
- systemd service that starts on boot
- Daily start/stop window
- Clean end-of-day ffmpeg stop
- Optional Pi shutdown after the stream window
- Maintenance-safe outside-hours boot: manual boots outside the active window stay on instead of immediately shutting down
- Lightweight web settings manager with first-run login setup
- Local stuck-stream detection using ffmpeg progress output
- YouTube Data API v3 broadcast preparation
- Reuses saved YouTube liveStream where possible
- Creates a fresh broadcast if the saved broadcast is complete or missing
- Binds broadcast to stream automatically
- Applies title, description, category, privacy, tags, language, Made for Kids, DVR, embed, auto-start, and auto-stop settings
- Uploads a configured thumbnail once per broadcast
- Keeps OAuth files, stream key, and YouTube IDs out of git

## Runtime flow

1. The Pi boots.
2. systemd starts `aquacam-ytapi.service`.
3. `start_stream.sh` checks the configured stream window.
4. If inside the window and `YT_API_ENABLED="true"`, it runs `ytapi_prepare_broadcast.py`.
5. The API script:
   - refreshes/uses OAuth credentials
   - reuses or creates a YouTube liveStream
   - reuses or creates a YouTube liveBroadcast
   - binds the broadcast to the stream
   - applies the configured video metadata
   - uploads the thumbnail if configured
   - writes YouTube's RTMP stream key to `stream.key`
6. ffmpeg pushes video to `rtmp://a.rtmp.youtube.com/live2/<stream-key>`.
7. YouTube auto-starts the live broadcast when ingest begins.
8. At `STOP_TIME`, ffmpeg stops cleanly; optional shutdown follows.

## Project structure

- `README.md` - overview
- `docs/TUTORIAL.md` - full setup tutorial
- `docs/INSTALL.md` - concise install checklist
- `docs/IMPLEMENTATION.md` - how the API implementation works
- `docs/TROUBLESHOOTING.md` - diagnostics and fixes
- `scripts/start_stream.sh` - stream supervisor
- `scripts/ytapi_prepare_broadcast.py` - YouTube API prepare step
- `configs/aquacam-stream.conf.example` - config template
- `systemd/aquacam-ytapi.service` - systemd unit template
- `systemd/aquacam-webmgr.service` - optional web manager systemd unit template
- `webmgr/` - lightweight LAN web UI for editing safe config settings
- `sudoers/aquacam-shutdown.sudoers` - optional shutdown sudoers rule
- `assets/the-calm-aquarium-thumbnail.png` - sample thumbnail

## Quick install

For a fresh Raspberry Pi that is already imaged, booted, online, and reachable
over SSH, you can run the interactive installer directly on the Pi:

```bash
curl -fsSL https://raw.githubusercontent.com/kevincarbonaro/aquacam/main/scripts/install_aquacam.sh -o install_aquacam.sh
bash install_aquacam.sh
```

The installer asks for camera, schedule, YouTube metadata, OAuth, and systemd
settings. It uses a Python virtual environment and does not include secrets in
the repository.

Manual install steps are below.

```bash
sudo apt update
sudo apt install -y ffmpeg v4l-utils python3 python3-pip python3-venv rsync

mkdir -p /home/<PI_USER>/aquacam-stream-ytapi
rsync -a ./ /home/<PI_USER>/aquacam-stream-ytapi/
cd /home/<PI_USER>/aquacam-stream-ytapi
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
cp configs/aquacam-stream.conf.example aquacam-stream.conf
cp scripts/start_stream.sh ./start_stream.sh
cp scripts/ytapi_prepare_broadcast.py ./ytapi_prepare_broadcast.py
cp assets/the-calm-aquarium-thumbnail.png ./the-calm-aquarium-thumbnail.png
chmod +x start_stream.sh ytapi_prepare_broadcast.py
```

Then edit:

```bash
nano /home/<PI_USER>/aquacam-stream-ytapi/aquacam-stream.conf
```

Set at least:

```bash
YT_API_ENABLED="true"
PYTHON_BIN="/home/<PI_USER>/aquacam-stream-ytapi/.venv/bin/python"
YT_CLIENT_SECRETS="/home/<PI_USER>/aquacam-stream-ytapi/client_secret.json"
YT_TOKEN_FILE="/home/<PI_USER>/aquacam-stream-ytapi/token.json"
YT_THUMBNAIL_FILE="/home/<PI_USER>/aquacam-stream-ytapi/the-calm-aquarium-thumbnail.png"
```

Full setup is in `docs/TUTORIAL.md`.

## Required Google/YouTube setup

- YouTube livestreaming enabled on the channel
- Google Cloud project
- YouTube Data API v3 enabled
- OAuth consent screen configured
- OAuth Desktop App credentials downloaded as `client_secret.json`
- OAuth scope used by this project:

```text
https://www.googleapis.com/auth/youtube
```

## First-time OAuth authorization

On a headless Pi, create a tunnel from your computer:

```bash
ssh -L 8080:localhost:8080 <PI_USER>@aquacam.local
```

In another SSH session:

```bash
cd /home/<PI_USER>/aquacam-stream-ytapi
.venv/bin/python ytapi_prepare_broadcast.py --config ./aquacam-stream.conf
```

Open the printed Google authorization URL on your computer, approve the YouTube channel, and let it redirect to localhost through the tunnel. This creates `token.json`. After that, the service can run unattended.

## Service install

```bash
sudo cp systemd/aquacam-ytapi.service /etc/systemd/system/aquacam-ytapi.service
sudo sed -i "s|<PI_USER>|$(whoami)|g" /etc/systemd/system/aquacam-ytapi.service
sudo systemctl daemon-reload
sudo systemctl enable aquacam-ytapi.service
sudo systemctl restart aquacam-ytapi.service
sudo systemctl status aquacam-ytapi.service --no-pager
```

## Optional web settings manager

The `webmgr/` folder provides a tiny LAN-only web UI for editing common safe
settings in `aquacam-stream.conf`. It uses only Python's standard library.
First visit asks you to create the admin login.

```bash
cd /home/<PI_USER>/aquacam-stream-ytapi
sudo cp systemd/aquacam-webmgr.service /etc/systemd/system/aquacam-webmgr.service
sudo sed -i "s|<PI_USER>|$(whoami)|g" /etc/systemd/system/aquacam-webmgr.service
sudo systemctl daemon-reload
sudo systemctl enable --now aquacam-webmgr.service
```

Then open:

```text
http://<pi-ip>:8080/
```

Do not expose this HTTP service to the internet.

## Security

Never commit:

- `client_secret.json`
- `token.json`
- `stream.key`
- `broadcast.id`
- `stream.id`
- logs or personal network details

The `.gitignore` is set up for these runtime files.

For Raspberry Pi hardening guidance, see:

```text
docs/PI_HARDENING.md
```

## Versions in this repository

### Recommended: API version

The files in the repository root are the current YouTube API version. Use this version for the AquaCam Pi.

This version prepares YouTube Live through the YouTube Data API before ffmpeg starts. That avoids the morning boot problem where the Pi pushes RTMP but YouTube remains stuck on "Preparing stream".

### Legacy: non-API version

The older direct-RTMP-only version has been moved to:

```text
non-api-version/
```

That version is kept for history/reference. It can work, but it was sometimes unreliable because it depended on an existing YouTube Studio setup and static stream key. When YouTube got stuck on "Preparing stream", the workaround was to open YouTube Studio and/or reboot the Pi.

## Recommended choice

Use the root API version for normal operation.

Only use `non-api-version/` if you deliberately want the old no-API workflow or need to compare behaviour.
