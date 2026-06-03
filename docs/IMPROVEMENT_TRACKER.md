# Aquacam Improvement Tracker

Last updated: 2026-06-03T18:44:33+02:00

## Current production state

- Active service on Pi: `aquacam-ytapi.service`
- Current safe stream config: `640x480`
- Current encoder path: software `libx264`
- Current issue: camera/encoder appears limited to about 18-19 fps in real tests, and higher resolutions consume much more CPU.

## Latest performance findings

### 640x480, software encoder

- Approx fps: 19
- Speed: about 1.02x
- CPU average: about 73%
- Result: safe baseline; keep this as rollback option.

### 1280x720, software encoder

- Approx fps: 19
- Speed: about 1.02x
- CPU average: about 178%
- CPU peaks: around 200%
- Result: works in short test but has low CPU headroom; not ready as default.

### 1920x1080, software encoder

- Approx fps: 17
- Speed: about 0.89x
- CPU average: about 299%
- Result: not suitable.

## Next improvement to test

### Test Raspberry Pi hardware H.264 encoder

Goal: check whether `h264_v4l2m2m` can make 1280x720 16:9 viable with lower CPU and stable real-time encoding.

Confirmed available on Pi:

```text
h264_v4l2m2m         V4L2 mem2mem H.264 encoder wrapper
libx264              software H.264 encoder
```

Suggested next test command pattern:

```bash
ffmpeg -hide_banner -y \
  -f v4l2 -framerate 20 -video_size 1280x720 -input_format mjpeg -i /dev/video0 \
  -c:v h264_v4l2m2m -b:v 2500k -maxrate 2500k -bufsize 5000k \
  -f null /dev/null
```

If that fails, test a more conservative profile:

```bash
ffmpeg -hide_banner -y \
  -f v4l2 -framerate 15 -video_size 1280x720 -input_format mjpeg -i /dev/video0 \
  -c:v h264_v4l2m2m -b:v 2000k -maxrate 2000k -bufsize 4000k \
  -f null /dev/null
```

## Acceptance criteria before switching live stream

- Test runs for at least 5-10 minutes.
- Encoding speed stays at or above `1.0x`.
- No continuous frame drops or buffer errors.
- CPU is clearly lower than software 720p, ideally under 100-120% average.
- YouTube test stream remains stable after reboot.
- Existing 640x480 config remains available as rollback.

## Proposed next steps

1. Stop `aquacam-ytapi.service` temporarily.
2. Run hardware encoder tests at 1280x720.
3. Save performance report under `/home/kevin/Jarvis/reports/aquacam/`.
4. If stable, update `scripts/start_stream.sh` and config template to support hardware encoder as an option.
5. Deploy to Pi as a test-only change.
6. Reboot Pi and confirm the morning auto-start path works without needing YouTube Studio.

## Rollback plan

If hardware encoding is unstable:

- Restore `640x480` config.
- Use `libx264` baseline.
- Restart `aquacam-ytapi.service`.
- Confirm FFmpeg process is active and YouTube broadcast is live.
