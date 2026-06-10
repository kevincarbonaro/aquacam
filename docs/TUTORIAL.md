# AquaCam YouTube API Tutorial

This guide sets up the recommended AquaCam version: Raspberry Pi + ffmpeg + YouTube Data API.

The API version is preferred over the older direct-RTMP-only version because the older setup could boot in the morning and leave YouTube stuck on "Preparing stream" until YouTube Studio was opened or the Pi was rebooted.

## 1. What this project does

- Starts automatically when the Pi boots
- Streams only during a configured time window
- Uses the YouTube Data API before ffmpeg starts
- Reuses or creates the correct YouTube Live broadcast
- Applies the AquaCam video template
- Uploads the configured thumbnail
- Writes the YouTube stream key locally for ffmpeg
- Stops cleanly at the end of the stream window
- Optionally shuts the Pi down after the stream window

## 2. Folder layout on the Pi

Recommended folder:

```text
/home/<PI_USER>/aquacam-stream-ytapi/
```

Runtime files in that folder:

```text
aquacam-stream.conf
start_stream.sh
ytapi_prepare_broadcast.py
requirements.txt
the-calm-aquarium-thumbnail.png
client_secret.json      # secret, do not commit
token.json              # secret, do not commit
stream.key              # generated/secret, do not commit
broadcast.id            # runtime state, do not commit
stream.id               # runtime state, do not commit
thumbnail_set.id        # runtime state, do not commit
stream.log              # runtime log, do not commit
```

## 3. Pi prerequisites

```bash
sudo apt update
sudo apt install -y ffmpeg v4l-utils python3 python3-pip python3-venv rsync
```

Check the camera:

```bash
v4l2-ctl --list-devices
ls -l /dev/video0
```

Set the timezone:

```bash
sudo timedatectl set-timezone Europe/Malta
timedatectl
```

## 4. Copy files to the Pi

From your computer, copy the project to the Pi:

```bash
rsync -a --exclude='.git' ./ <PI_USER>@aquacam.local:/home/<PI_USER>/aquacam-stream-ytapi/
```

On the Pi:

```bash
cd /home/<PI_USER>/aquacam-stream-ytapi
chmod +x scripts/start_stream.sh scripts/ytapi_prepare_broadcast.py
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
cp configs/aquacam-stream.conf.example aquacam-stream.conf
cp scripts/start_stream.sh ./start_stream.sh
cp scripts/ytapi_prepare_broadcast.py ./ytapi_prepare_broadcast.py
cp assets/the-calm-aquarium-thumbnail.png ./the-calm-aquarium-thumbnail.png
chmod +x start_stream.sh ytapi_prepare_broadcast.py
```

## 5. Google Cloud / YouTube setup

In Google Cloud Console:

1. Create or select a project.
2. Enable `YouTube Data API v3`.
3. Configure the OAuth consent screen.
4. Create OAuth credentials for a `Desktop app`.
5. Download the JSON file.
6. Save it on the Pi as:

```text
/home/<PI_USER>/aquacam-stream-ytapi/client_secret.json
```

Required OAuth scope:

```text
https://www.googleapis.com/auth/youtube
```

YouTube requirements:

- Channel must have livestreaming enabled.
- Account must be verified if YouTube requires it.
- The Google account used for OAuth must have access to the YouTube channel.

## 6. Configure AquaCam

Edit:

```bash
nano /home/<PI_USER>/aquacam-stream-ytapi/aquacam-stream.conf
```

Important values:

```bash
STREAM_URL="rtmp://a.rtmp.youtube.com/live2"
STREAM_KEY_FILE="/home/<PI_USER>/aquacam-stream-ytapi/stream.key"
VIDEO_DEVICE="/dev/video0"
START_TIME="08:30"
STOP_TIME="20:30"
SHUTDOWN_AFTER_STOP="true"
SHUTDOWN_TIME="20:35"
LOG_FILE="/home/<PI_USER>/aquacam-stream-ytapi/stream.log"

YT_API_ENABLED="true"
PYTHON_BIN="/home/<PI_USER>/aquacam-stream-ytapi/.venv/bin/python"
YT_CLIENT_SECRETS="/home/<PI_USER>/aquacam-stream-ytapi/client_secret.json"
YT_TOKEN_FILE="/home/<PI_USER>/aquacam-stream-ytapi/token.json"
YT_BROADCAST_ID_FILE="/home/<PI_USER>/aquacam-stream-ytapi/broadcast.id"
YT_STREAM_ID_FILE="/home/<PI_USER>/aquacam-stream-ytapi/stream.id"
YT_THUMBNAIL_FILE="/home/<PI_USER>/aquacam-stream-ytapi/the-calm-aquarium-thumbnail.png"

YT_PRIVACY_STATUS="public"
YT_BROADCAST_TITLE="AquaCam Live - {date}"
YT_BROADCAST_DESCRIPTION="Live aquarium camera."
YT_BROADCAST_TAGS="aquarium, aquatic, livestream, fish, water, pets, animals, relaxation"
YT_DEFAULT_LANGUAGE="en"
YT_DEFAULT_AUDIO_LANGUAGE="en"
YT_SELF_DECLARED_MADE_FOR_KIDS="false"
YT_ENABLE_AUTO_START="true"
YT_ENABLE_AUTO_STOP="true"
YT_ENABLE_DVR="true"
YT_ENABLE_EMBED="true"
YT_LATENCY_PREFERENCE="low"
```

## 7. First-time OAuth authorization

If the Pi is headless, open a tunnel from your computer:

```bash
ssh -L 8080:localhost:8080 <PI_USER>@aquacam.local
```

In another SSH session:

```bash
cd /home/<PI_USER>/aquacam-stream-ytapi
.venv/bin/python ytapi_prepare_broadcast.py --config ./aquacam-stream.conf
```

The script prints a Google authorization URL. Open it on your computer, approve the correct YouTube channel, and let Google redirect to localhost. The SSH tunnel sends that callback to the Pi.

After success, the Pi has:

```text
token.json
stream.id
broadcast.id
stream.key
```

Lock permissions:

```bash
chmod 600 client_secret.json token.json stream.key
```

## 8. Install systemd service

```bash
cd /home/<PI_USER>/aquacam-stream-ytapi
sudo cp systemd/aquacam-ytapi.service /etc/systemd/system/aquacam-ytapi.service
sudo sed -i "s|<PI_USER>|$(whoami)|g" /etc/systemd/system/aquacam-ytapi.service
sudo systemctl daemon-reload
sudo systemctl enable aquacam-ytapi.service
sudo systemctl restart aquacam-ytapi.service
sudo systemctl status aquacam-ytapi.service --no-pager
```

Staging note: if the camera is not plugged in yet, OAuth files are not present,
or another Pi is currently streaming, stop after `sudo systemctl daemon-reload`.
Only enable/restart the service when you are ready for this Pi to attempt the
production stream.

## 9. Optional shutdown permission

If `SHUTDOWN_AFTER_STOP="true"`, install the sudoers rule:

```bash
sudo cp sudoers/aquacam-shutdown.sudoers /etc/sudoers.d/aquacam-shutdown
sudo sed -i "s|<PI_USER>|$(whoami)|g" /etc/sudoers.d/aquacam-shutdown
sudo chmod 440 /etc/sudoers.d/aquacam-shutdown
sudo visudo -cf /etc/sudoers.d/aquacam-shutdown
```

## 10. Verify

Check service:

```bash
systemctl is-active aquacam-ytapi.service
journalctl -u aquacam-ytapi.service -n 100 --no-pager
```

Check project log:

```bash
tail -n 100 /home/<PI_USER>/aquacam-stream-ytapi/stream.log
```

Expected log messages:

```text
Starting AquaCam stream supervisor
Preparing YouTube broadcast through API
YouTube API prepare succeeded
Launching FFmpeg
```

In YouTube Studio, the broadcast should auto-start when ffmpeg begins pushing.

## 11. Daily operation

Normal flow:

1. Smart plug powers Pi in the morning.
2. Pi boots.
3. systemd starts the API version.
4. API prepares YouTube.
5. ffmpeg streams.
6. YouTube goes live automatically.
7. At stop time, ffmpeg exits cleanly.
8. Pi optionally shuts down before the smart plug cuts power.

## 12. Backups

Before changing a working Pi, back up the runtime folder to your computer:

```bash
TS=$(date +%Y%m%d-%H%M%S)
mkdir -p ~/Jarvis/projects/aquacam-ytapi/backups/pi-$TS
rsync -a <PI_USER>@aquacam.local:/home/<PI_USER>/aquacam-stream-ytapi/ ~/Jarvis/projects/aquacam-ytapi/backups/pi-$TS/
chmod -R go-rwx ~/Jarvis/projects/aquacam-ytapi/backups/pi-$TS
```

Do not publish those backups because they may contain secrets.
