# AquaCam Raspberry Pi YouTube Stream (Community Tutorial)

This tutorial explains how to set up a Raspberry Pi to stream continuously to YouTube on a schedule, auto-recover from local stream stalls, and shut down safely at night.

All sensitive values are replaced with placeholders.

## 1) What this project does

- Streams camera video + silent audio to YouTube using ffmpeg
- Runs as a systemd service (starts on boot)
- Streams only within allowed time window
- Stops cleanly at STOP_TIME so YouTube sees stream end
- Optional auto-shutdown at SHUTDOWN_TIME
- Local-only stuck-stream detection (no cloud API dependency)

## 2) Folder layout (on Pi)

Use this structure on the Pi:

- /home/<PI_USER>/aquacam-stream/start_stream.sh
- /home/<PI_USER>/aquacam-stream/aquacam-stream.conf
- /home/<PI_USER>/aquacam-stream/stream.key
- /home/<PI_USER>/aquacam-stream/stream.log

## 3) Prerequisites

Hardware:
- Raspberry Pi (recommended Pi 4 or better)
- USB camera at /dev/video0
- Stable power (smart plug optional)

Software:
- Raspberry Pi OS (Lite is fine)
- ffmpeg installed
- systemd (default on Raspberry Pi OS)
- sudo access

Install packages:

```bash
sudo apt update
sudo apt install -y ffmpeg v4l-utils
```

Check camera device:

```bash
v4l2-ctl --list-devices
```

## 4) Create project directory

```bash
mkdir -p /home/<PI_USER>/aquacam-stream
cd /home/<PI_USER>/aquacam-stream
```

## 5) Add stream key securely

Create key file:

```bash
nano /home/<PI_USER>/aquacam-stream/stream.key
```

Paste only your YouTube stream key (single line), save, then lock permissions:

```bash
chmod 600 /home/<PI_USER>/aquacam-stream/stream.key
```

## 6) Add config and script

Copy these template files from this project:

- configs/aquacam-stream.conf.example
- scripts/start_stream.sh

On Pi, place them as:

- /home/<PI_USER>/aquacam-stream/aquacam-stream.conf
- /home/<PI_USER>/aquacam-stream/start_stream.sh

Make script executable:

```bash
chmod +x /home/<PI_USER>/aquacam-stream/start_stream.sh
```

Edit config:

```bash
nano /home/<PI_USER>/aquacam-stream/aquacam-stream.conf
```

Important fields:
- START_TIME="08:30"
- STOP_TIME="20:30"
- SHUTDOWN_TIME="20:35"
- STUCK_TIMEOUT_SECONDS="480"
- STREAM_KEY_FILE path
- LOG_FILE path

## 7) Configure timezone (critical)

```bash
sudo timedatectl set-timezone <YOUR_TIMEZONE>
timedatectl
```

Example timezone: Europe/Malta

## 8) Allow passwordless shutdown for service user

Create sudoers file:

```bash
sudo cp sudoers/aquacam-shutdown.sudoers /etc/sudoers.d/aquacam-shutdown
sudo sed -i "s|<PI_USER>|$(whoami)|g" /etc/sudoers.d/aquacam-shutdown
sudo chmod 440 /etc/sudoers.d/aquacam-shutdown
sudo visudo -cf /etc/sudoers.d/aquacam-shutdown
```

## 9) Install systemd service

Copy service template:

```bash
sudo cp systemd/aquacam.service /etc/systemd/system/aquacam.service
sudo sed -i "s|<PI_USER>|$(whoami)|g" /etc/systemd/system/aquacam.service
```

Enable + start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable aquacam.service
sudo systemctl restart aquacam.service
sudo systemctl status aquacam.service --no-pager
```

## 10) How local stuck detection works

The script tells ffmpeg to write progress to:
- /tmp/aquacam-ffmpeg.progress

Logic:
- If `total_size` increases, stream is healthy
- If `total_size` does not increase for STUCK_TIMEOUT_SECONDS, ffmpeg is restarted

This helps recover from local stalls without YouTube API polling.

## 11) Verify behavior

Follow logs:

```bash
tail -f /home/<PI_USER>/aquacam-stream/stream.log
```

Expected:
- Inside schedule: ffmpeg launches/retries as needed
- At STOP_TIME: "Stopping FFmpeg cleanly"
- After stop: waits until SHUTDOWN_TIME then `shutdown -h now`

## 12) Smart plug power-cut planning

Recommended:
- STOP_TIME = 20:30
- SHUTDOWN_TIME = 20:35
- Smart plug OFF = 20:45

This gives the Pi enough time to end stream and power down safely.

## 13) Operations cheat sheet

Service control:

```bash
sudo systemctl start aquacam.service
sudo systemctl stop aquacam.service
sudo systemctl restart aquacam.service
sudo systemctl disable aquacam.service
sudo systemctl enable aquacam.service
```

Quick diagnostics:

```bash
systemctl is-active aquacam.service
journalctl -u aquacam.service -n 100 --no-pager
tail -n 100 /home/<PI_USER>/aquacam-stream/stream.log
```

## 14) Backup and restore

Backup current config/script:

```bash
TS=$(date +%Y%m%d-%H%M%S)
mkdir -p /home/<PI_USER>/aquacam-stream/backups/$TS
cp /home/<PI_USER>/aquacam-stream/start_stream.sh /home/<PI_USER>/aquacam-stream/backups/$TS/
cp /home/<PI_USER>/aquacam-stream/aquacam-stream.conf /home/<PI_USER>/aquacam-stream/backups/$TS/
```

Restore:

```bash
cp /home/<PI_USER>/aquacam-stream/backups/<TIMESTAMP>/start_stream.sh /home/<PI_USER>/aquacam-stream/start_stream.sh
cp /home/<PI_USER>/aquacam-stream/backups/<TIMESTAMP>/aquacam-stream.conf /home/<PI_USER>/aquacam-stream/aquacam-stream.conf
sudo systemctl restart aquacam.service
```

## 15) Security and privacy notes

Do NOT publish:
- Real stream key
- Home IP/domain
- SSH private keys
- Personal usernames/hostnames (optional; replace with placeholders)

Safe practice:
- Keep `stream.key` out of git
- Use placeholders in public docs
- Review logs before sharing screenshots

---

If you want, add your DIY hardware/build section after this tutorial (camera mount, enclosure, cooling, solar/battery, waterproofing, etc.).
