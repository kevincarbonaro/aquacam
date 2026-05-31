---
name: YouTube stuck on "Preparing stream"
about: Report recurring YouTube ingest stalls and recovery behavior
labels: bug, youtube-ingest
---

## Summary
Describe when/how often YouTube remains on "Preparing stream".

## Environment
- Pi model:
- OS version (`cat /etc/os-release`):
- Camera model:
- Network: Ethernet / Wi-Fi

## AquaCam config (redact secrets)
- `WARM_RESTART_ENABLED`:
- `WARM_RESTART_AFTER_SECONDS`:
- `STUCK_TIMEOUT_SECONDS`:
- `VIDEO_SIZE`:
- `VIDEO_BITRATE`:

## What happened
- Expected behavior:
- Actual behavior:
- Approx timestamp (local time):

## Relevant logs
Paste from:
- `/home/<PI_USER>/aquacam-stream/stream.log`
- `journalctl -u aquacam.service -n 200 --no-pager`

Please include lines around:
- `Warm restart trigger reached`
- `Detected local stuck stream`
- `FFmpeg exited with code`

## Extra notes
Anything else that may help reproduce (network instability, power event, YouTube Studio observations, etc.).
