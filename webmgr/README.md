# AquaCam web manager

Tiny, no-dependency web UI for editing common AquaCam settings without SSH-editing `aquacam-stream.conf`.

Recommended location: keep it as a sub-folder of the AquaCam project (`webmgr/`), not a separate project. It edits the project config directly, uses only Python's standard library, and is light enough for a Raspberry Pi.

## What it does

- Listens on port `8080` by default.
- First visit asks you to create the admin username and password.
- Stores the password as PBKDF2-SHA256 in `.aquacam-webmgr.json` beside the config, mode `600`.
- Uses a local session cookie after login.
- Edits a safe allow-list of common settings only.
- Creates a timestamped backup before every config save.
- `Save and restart service` tries `sudo -n systemctl restart aquacam-ytapi.service` first.
- If passwordless sudo is unavailable, it falls back to signalling the same-user `start_stream.sh` process; with the normal `Restart=always` systemd unit, systemd restarts it.

## Install on the Pi with systemd

From the installed AquaCam project folder on the Pi:

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

## Simple user crontab fallback

If you do not want to install the systemd unit, start it at boot with the Pi user's crontab:

```bash
crontab -l 2>/dev/null | { grep -v 'aquacam-stream-ytapi/webmgr/start_webmgr.sh' || true; echo '@reboot /home/<PI_USER>/aquacam-stream-ytapi/webmgr/start_webmgr.sh'; } | crontab -
/home/<PI_USER>/aquacam-stream-ytapi/webmgr/start_webmgr.sh
```

## Optional restart button sudoers

The restart fallback usually avoids needing this. If you want the web UI to perform a real systemd restart without a password, add a narrow sudoers file:

```text
<PI_USER> ALL=(root) NOPASSWD: /bin/systemctl restart aquacam-ytapi.service
```

Install with `sudo visudo -f /etc/sudoers.d/aquacam-webmgr-restart` and validate with:

```bash
sudo visudo -cf /etc/sudoers.d/aquacam-webmgr-restart
```

## Security notes

This is intended for a trusted LAN only. It does not provide HTTPS. Do not expose port 8080 to the internet.
