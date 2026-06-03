# AquaCam Raspberry Pi YouTube Stream (Beginner-Friendly Tutorial)

This guide takes you from a fresh Raspberry Pi to a reliable, always-on stream service.

Goal:
- Stream from camera to YouTube with ffmpeg
- Start automatically on boot (systemd)
- Run only in your allowed time window
- Recover from local stalls automatically
- Shut down safely after stream window (optional)

All sensitive values are placeholders.

## 1) Before you start

Hardware:
- Raspberry Pi 4 (recommended) or better
- Good power supply (important for stability)
- USB camera (or UVC-compatible capture device)
- microSD (or SSD) with Raspberry Pi OS
- Network connection (Ethernet preferred for reliability)

Accounts/access:
- YouTube stream key available
- SSH access to Pi (recommended)
- User with sudo privileges

## 2) Prepare Raspberry Pi OS (fresh install)

1. Flash Raspberry Pi OS (Lite is fine).
2. In Raspberry Pi Imager, set:
   - hostname
   - username/password
   - enable SSH
   - Wi-Fi (if needed)
   - timezone/locale
3. Boot Pi and SSH in.

Update OS:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

After reboot, install packages:

```bash
sudo apt update
sudo apt install -y ffmpeg v4l-utils
```

## 3) Basic Pi checks (do not skip)

Time/timezone (critical for START_TIME/STOP_TIME):

```bash
timedatectl
sudo timedatectl set-timezone <YOUR_TIMEZONE>
timedatectl
```

Camera detection:

```bash
v4l2-ctl --list-devices
ls -l /dev/video*
```

If your camera is not `/dev/video0`, note the correct device path.

Quick camera capability check:

```bash
v4l2-ctl -d /dev/video0 --list-formats-ext
```

## 4) Create runtime directory on Pi

```bash
mkdir -p /home/<PI_USER>/aquacam-stream
cd /home/<PI_USER>/aquacam-stream
```

Expected files after setup:
- `/home/<PI_USER>/aquacam-stream/start_stream.sh`
- `/home/<PI_USER>/aquacam-stream/aquacam-stream.conf`
- `/home/<PI_USER>/aquacam-stream/stream.key`
- `/home/<PI_USER>/aquacam-stream/stream.log`

## 5) Add stream key securely

Create key file:

```bash
nano /home/<PI_USER>/aquacam-stream/stream.key
```

Paste only the YouTube stream key (single line), save, then:

```bash
chmod 600 /home/<PI_USER>/aquacam-stream/stream.key
```

Never commit this file to git.

## 6) Copy project templates to Pi

From this repo, copy:
- `scripts/start_stream.sh` -> `/home/<PI_USER>/aquacam-stream/start_stream.sh`
- `configs/aquacam-stream.conf.example` -> `/home/<PI_USER>/aquacam-stream/aquacam-stream.conf`

Make script executable:

```bash
chmod +x /home/<PI_USER>/aquacam-stream/start_stream.sh
```

## 7) Configure aquacam-stream.conf

Edit config:

```bash
nano /home/<PI_USER>/aquacam-stream/aquacam-stream.conf
```

Minimum fields to verify:
- `STREAM_KEY_FILE` path
- `VIDEO_DEVICE` (example: `/dev/video0`)
- `FRAMERATE`, `VIDEO_SIZE`, bitrate values
- `START_TIME`, `STOP_TIME`
- `SHUTDOWN_AFTER_STOP`, `SHUTDOWN_TIME` (if using scheduled power-off)
- `LOG_FILE`

Safe beginner defaults:
- `VIDEO_SIZE="640x480"`
- `FRAMERATE="30"`
- `VIDEO_BITRATE="1200k"`
- `STUCK_TIMEOUT_SECONDS="480"`

## 8) Test ffmpeg manually once (important)

Before systemd, do one direct test:

```bash
/home/<PI_USER>/aquacam-stream/start_stream.sh
```

Watch output/logs for 1-2 minutes. Then stop with Ctrl+C.

If it fails:
- Check camera device path
- Check stream key file exists and permissions
- Check network connectivity
- Check ffmpeg errors in `stream.log`

## 9) Install sudoers rule for safe auto-shutdown (optional but recommended)

If `SHUTDOWN_AFTER_STOP="true"`, install sudoers rule:

```bash
sudo cp sudoers/aquacam-shutdown.sudoers /etc/sudoers.d/aquacam-shutdown
sudo sed -i "s|<PI_USER>|$(whoami)|g" /etc/sudoers.d/aquacam-shutdown
sudo chmod 440 /etc/sudoers.d/aquacam-shutdown
sudo visudo -cf /etc/sudoers.d/aquacam-shutdown
```

## 10) Install and enable systemd service

```bash
sudo cp systemd/aquacam.service /etc/systemd/system/aquacam.service
sudo sed -i "s|<PI_USER>|$(whoami)|g" /etc/systemd/system/aquacam.service
sudo systemctl daemon-reload
sudo systemctl enable aquacam.service
sudo systemctl restart aquacam.service
sudo systemctl status aquacam.service --no-pager
```

## 11) Verify real behavior

Live logs:

```bash
tail -f /home/<PI_USER>/aquacam-stream/stream.log
```

Service logs:

```bash
journalctl -u aquacam.service -f
```

Expected:
- Inside window: ffmpeg launches
- At STOP_TIME: clean stop message
- After stop: optional scheduled shutdown
- If stream stalls locally: automatic ffmpeg restart

## 12) Smart plug timing strategy (recommended)

Example daily automation:
- Smart plug ON: `14:30` (Pi boots)
- `START_TIME=14:30`
- `STOP_TIME=20:30`
- `SHUTDOWN_TIME=20:30`
- Smart plug OFF power cut: `20:45`

Behavior:
- If Pi boots during active window, service starts streaming automatically.
- AquaCam does a one-time warm restart after `WARM_RESTART_AFTER_SECONDS` (recommended `60`) to clear YouTube ingest stalls.
- At `STOP_TIME`, AquaCam stops ffmpeg cleanly first, then shuts down OS.
- Plug cut at `20:45` is only a safety cutoff after clean shutdown.

## 13) Beginner troubleshooting

Service won’t start:

```bash
sudo systemctl status aquacam.service --no-pager
journalctl -u aquacam.service -n 120 --no-pager
```

No camera video:
- Wrong `VIDEO_DEVICE`
- Unsupported format/resolution
- Camera not powered/recognized

Permission issues:
- Check file owner/permissions in `/home/<PI_USER>/aquacam-stream`
- Verify `stream.key` is readable by service user

Timezone/schedule mismatch:
- Run `timedatectl`
- Confirm START/STOP are local Pi time

YouTube stuck on "Preparing stream":
- This is a known intermittent ingest issue.
- AquaCam tries to self-heal in two ways:
  1) one-time warm restart shortly after startup (`WARM_RESTART_ENABLED`, `WARM_RESTART_AFTER_SECONDS`)
  2) local stuck detection based on ffmpeg progress file (`STUCK_TIMEOUT_SECONDS`)
- Check for these log lines in `stream.log`:
  - `Warm restart trigger reached ... Restarting FFmpeg once ...`
  - `Detected local stuck stream ... Restarting FFmpeg.`
- If this keeps happening, try:
  - increasing `WARM_RESTART_AFTER_SECONDS` (e.g., 120 -> 180)
  - lowering camera bitrate/resolution temporarily
  - testing wired Ethernet instead of Wi-Fi
  - restarting the scheduled stream window cleanly (stop/start service)

## 14) Backup and restore

Backup config/script:

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

## 15) Security checklist before publish/commit

Never publish:
- real stream key
- private SSH keys
- personal IP/domain details

Run scan before every commit:

```bash
./scripts/scan_secrets.sh
```

Optional local pre-commit hook:

```bash
cat > .git/hooks/pre-commit << 'EOF'
#!/usr/bin/env bash
./scripts/scan_secrets.sh
EOF
chmod +x .git/hooks/pre-commit
```
