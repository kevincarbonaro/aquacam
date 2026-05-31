# AquaCam Pi Stream

Community-ready Raspberry Pi project for scheduled YouTube livestreaming with automatic recovery and safe shutdown.

## Features

- ffmpeg-based livestream to YouTube RTMP
- systemd service (auto-start on boot)
- Daily stream window scheduler
- Clean stop at end-of-window so YouTube sees stream ended
- Optional timed shutdown (for smart plug workflows)
- Local-only stuck stream detection (no API/cloud dependencies)
- One-time warm restart after boot to clear YouTube 'Preparing stream' stalls

## Project structure

- `docs/TUTORIAL.md` — full setup guide
- `scripts/start_stream.sh` — stream supervisor script
- `configs/aquacam-stream.conf.example` — config template
- `systemd/aquacam.service` — systemd unit template
- `sudoers/aquacam-shutdown.sudoers` — sudoers rule template
- `backups/` — local backups from Pi (do not publish if sensitive)

## Quick start

1. Read `docs/TUTORIAL.md`
2. Copy templates to Pi and replace placeholders
3. Add your YouTube stream key to `stream.key` on Pi
4. Enable/start `aquacam.service`

## Safety check before every commit

Run:

```bash
./scripts/scan_secrets.sh
```

Optional (better): install `gitleaks` so scans are stronger:

```bash
sudo apt install -y gitleaks
```

Then run the same script again.

## Runtime recovery behavior

- Warm restart enabled: `true`
- Warm restart delay: `120s`
- Behavior: ffmpeg starts, waits 120s, restarts once, then continues normal monitoring

## Known issue: YouTube stuck on "Preparing stream"

Sometimes YouTube Studio stays on "Preparing stream" even when ffmpeg is already pushing.

Current self-healing approach in this project:
- One-time warm restart: after initial launch, the supervisor waits `WARM_RESTART_AFTER_SECONDS` and restarts ffmpeg once.
- Local stuck detection: if ffmpeg progress (`total_size`) does not increase for `STUCK_TIMEOUT_SECONDS`, ffmpeg is restarted.

Config knobs (in `aquacam-stream.conf`):
- `WARM_RESTART_ENABLED="true"`
- `WARM_RESTART_AFTER_SECONDS="120"`
- `STUCK_TIMEOUT_SECONDS="480"`

If you still see repeated "Preparing stream" stalls, please open an issue with logs and timestamps.
Use the issue template: `.github/ISSUE_TEMPLATE/preparing-stream-stuck.md`.

## Default schedule in template

- Start: `08:30`
- Stop: `20:30`
- Shutdown: `20:35`

## Security note

Never commit:
- real stream keys
- private SSH keys
- personal network details

Use `.gitignore` in this repo and keep secrets local.

## License

MIT (see `LICENSE`)
