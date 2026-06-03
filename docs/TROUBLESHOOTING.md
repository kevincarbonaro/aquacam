# Troubleshooting

## Service status

```bash
systemctl is-active aquacam-ytapi.service
systemctl status aquacam-ytapi.service --no-pager
journalctl -u aquacam-ytapi.service -n 200 --no-pager
```

Project log:

```bash
tail -n 200 /home/<PI_USER>/aquacam-stream-ytapi/stream.log
```

## Test the API prepare step manually

```bash
cd /home/<PI_USER>/aquacam-stream-ytapi
python3 ytapi_prepare_broadcast.py --config ./aquacam-stream.conf
```

Success should include messages like:

```text
Reusing YouTube liveStream
Reusing YouTube broadcast
Broadcast already bound to the saved stream
Applied AquaCam video template
Wrote stream key
YouTube API prepare complete
```

## OAuth problems

If you see missing/invalid token errors:

1. Confirm `client_secret.json` exists.
2. Re-run first-time OAuth using the localhost tunnel.
3. Confirm `token.json` was created.
4. Confirm the authorized Google account has access to the YouTube channel.

Tunnel command from your computer:

```bash
ssh -L 8080:localhost:8080 <PI_USER>@aquacam.local
```

Then on the Pi:

```bash
cd /home/<PI_USER>/aquacam-stream-ytapi
python3 ytapi_prepare_broadcast.py --config ./aquacam-stream.conf
```

## YouTube API quota/errors

If the API returns quota or permission errors:

- Confirm YouTube Data API v3 is enabled in Google Cloud.
- Confirm the OAuth consent screen is configured.
- Confirm the scope is `https://www.googleapis.com/auth/youtube`.
- Avoid running the prepare script repeatedly in a tight loop.
- Check Google Cloud quota for YouTube Data API v3.

## Camera not found

```bash
v4l2-ctl --list-devices
ls -l /dev/video0
```

If the device path changed, update:

```bash
VIDEO_DEVICE="/dev/video0"
```

in `aquacam-stream.conf`.

## ffmpeg fails

Run:

```bash
which ffmpeg
ffmpeg -version
```

Check the log:

```bash
tail -n 200 /home/<PI_USER>/aquacam-stream-ytapi/stream.log
```

Common fixes:

- Lower `VIDEO_SIZE`
- Lower `FRAMERATE`
- Lower `VIDEO_BITRATE`
- Confirm `INPUT_FORMAT` is supported by the camera

## Stream does not go live

Check:

```bash
cat /home/<PI_USER>/aquacam-stream-ytapi/stream.key
cat /home/<PI_USER>/aquacam-stream-ytapi/broadcast.id
cat /home/<PI_USER>/aquacam-stream-ytapi/stream.id
```

Then manually run:

```bash
cd /home/<PI_USER>/aquacam-stream-ytapi
python3 ytapi_prepare_broadcast.py --config ./aquacam-stream.conf
```

If the saved broadcast is complete, the script should create a new one automatically.

## Reset saved YouTube IDs

Only do this if the saved YouTube resources are broken or deleted in YouTube Studio.

```bash
cd /home/<PI_USER>/aquacam-stream-ytapi
mv broadcast.id broadcast.id.bak.$(date +%Y%m%d-%H%M%S) 2>/dev/null || true
mv stream.id stream.id.bak.$(date +%Y%m%d-%H%M%S) 2>/dev/null || true
python3 ytapi_prepare_broadcast.py --config ./aquacam-stream.conf
sudo systemctl restart aquacam-ytapi.service
```

## Check schedule logic

```bash
date
grep -E '^(START_TIME|STOP_TIME|SHUTDOWN_TIME|CHECK_INTERVAL)' /home/<PI_USER>/aquacam-stream-ytapi/aquacam-stream.conf
```

Make sure the Pi timezone is correct:

```bash
timedatectl
```
