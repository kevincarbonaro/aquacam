# Raspberry Pi Hardening Tips for AquaCam

These are practical hardening recommendations for running AquaCam on a Raspberry Pi. The goal is to reduce risk without making the Pi painful to maintain.

AquaCam normally needs:

- Outbound internet access to YouTube/Google APIs
- Inbound SSH access from your admin machine or VPN
- Camera access, usually `/dev/video0` or Raspberry Pi camera support
- Local read/write access for config, OAuth token, stream key, logs, and state files

It usually does **not** need inbound public internet ports.

---

## 1. Keep SSH safe

### Use SSH keys only

Create or use an SSH key on your admin computer, then copy it to the Pi:

```bash
ssh-copy-id kevin@PI_HOSTNAME_OR_IP
```

Test key login before disabling passwords:

```bash
ssh kevin@PI_HOSTNAME_OR_IP
```

### Disable password login and root SSH

Create a hardening file:

```bash
sudo nano /etc/ssh/sshd_config.d/99-aquacam-hardening.conf
```

Recommended contents:

```conf
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
X11Forwarding no
```

Optional: restrict SSH to one user:

```conf
AllowUsers kevin
```

Restart SSH:

```bash
sudo systemctl restart ssh
```

Important: keep your current SSH session open and test a second login before closing it, so you do not lock yourself out.

---

## 2. Enable a simple firewall

Install and configure UFW:

```bash
sudo apt update
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
```

Allow SSH only from your LAN or VPN. Example for a common home network:

```bash
sudo ufw allow from 192.168.1.0/24 to any port 22 proto tcp
```

Then enable it:

```bash
sudo ufw enable
sudo ufw status verbose
```

AquaCam streams to YouTube using outbound RTMP/HTTPS, so you should not need to open inbound streaming ports.

---

## 3. Use automatic security updates

Install unattended upgrades:

```bash
sudo apt update
sudo apt install -y unattended-upgrades apt-listchanges
sudo dpkg-reconfigure unattended-upgrades
```

Check status:

```bash
systemctl status unattended-upgrades
```

---

## 4. Install Fail2ban if SSH is exposed beyond your LAN

If SSH is reachable from a VPN, port forward, or public network, install Fail2ban:

```bash
sudo apt install -y fail2ban
```

Create a local jail file:

```bash
sudo nano /etc/fail2ban/jail.d/sshd.local
```

Contents:

```ini
[sshd]
enabled = true
port = ssh
maxretry = 5
findtime = 10m
bantime = 1h
```

Enable it:

```bash
sudo systemctl enable --now fail2ban
sudo fail2ban-client status sshd
```

---

## 5. Run AquaCam as a dedicated user

Avoid running the stream service as root.

Create a dedicated user:

```bash
sudo useradd --system --create-home --home-dir /opt/aquacam --shell /usr/sbin/nologin aquacam
```

If the camera needs video device access:

```bash
sudo usermod -aG video aquacam
```

If the service needs Raspberry Pi GPIO/camera groups, add only what is required for your model and OS, for example:

```bash
sudo usermod -aG video,render aquacam
```

---

## 6. Protect secrets and runtime state

Sensitive AquaCam files can include:

- Google OAuth client secret JSON
- OAuth token JSON
- YouTube stream key file
- `.env` config
- Saved YouTube broadcast/stream IDs

Recommended layout:

```text
/opt/aquacam/
  app/
  configs/
  secrets/
  state/
  logs/
```

Recommended ownership and permissions:

```bash
sudo chown -R aquacam:aquacam /opt/aquacam
sudo chmod 750 /opt/aquacam
sudo chmod 750 /opt/aquacam/app /opt/aquacam/configs /opt/aquacam/secrets /opt/aquacam/state /opt/aquacam/logs
sudo chmod 600 /opt/aquacam/configs/.env
sudo chmod 600 /opt/aquacam/secrets/*.json
sudo chmod 600 /opt/aquacam/state/*.id
sudo chmod 600 /opt/aquacam/state/stream.key
```

Never commit these files to GitHub. This repository's `.gitignore` excludes common secret and state filenames, but permissions still matter on the Pi.

---

## 7. Harden the systemd service carefully

Systemd can restrict what the AquaCam service can access. Start with moderate hardening, then test the stream.

Example options for `aquacam-ytapi.service`:

```ini
[Service]
User=aquacam
Group=aquacam
SupplementaryGroups=video
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/opt/aquacam /var/log/aquacam
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true
CapabilityBoundingSet=
```

If camera access breaks, you may need to relax device isolation or explicitly allow the camera device:

```ini
PrivateDevices=false
DeviceAllow=/dev/video0 rw
```

After changes:

```bash
sudo systemctl daemon-reload
sudo systemctl restart aquacam-ytapi.service
sudo systemctl status aquacam-ytapi.service
```

Check logs:

```bash
journalctl -u aquacam-ytapi.service -n 100 --no-pager
```

---

## 8. Limit sudo access

If AquaCam needs to shut down the Pi at the end of the day, do not give broad sudo access.

Use a narrow sudoers rule such as:

```conf
aquacam ALL=(root) NOPASSWD: /sbin/shutdown
```

Install it safely:

```bash
sudo visudo -f /etc/sudoers.d/aquacam-shutdown
```

Validate:

```bash
sudo visudo -cf /etc/sudoers.d/aquacam-shutdown
```

---

## 9. Rotate logs to protect the SD card

Create a logrotate config:

```bash
sudo nano /etc/logrotate.d/aquacam
```

Example:

```conf
/var/log/aquacam/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
```

Test it:

```bash
sudo logrotate -d /etc/logrotate.d/aquacam
```

Also prefer `journald` limits so logs do not grow forever:

```bash
sudo nano /etc/systemd/journald.conf
```

Useful settings:

```conf
SystemMaxUse=200M
RuntimeMaxUse=50M
MaxRetentionSec=14day
```

Then:

```bash
sudo systemctl restart systemd-journald
```

---

## 10. Remove or disable unused services

Check open ports:

```bash
sudo ss -tulpn
```

Check enabled services:

```bash
systemctl list-unit-files --state=enabled
```

Disable only what you know you do not need. Common examples:

```bash
sudo systemctl disable --now bluetooth
sudo systemctl disable --now cups
sudo systemctl disable --now avahi-daemon
```

Do not disable networking, SSH, camera dependencies, or anything you do not understand.

---

## 11. Put the Pi on a safer network

Best practical network setup:

- Put the Pi on an IoT VLAN or guest network
- Allow outbound HTTPS/RTMP to the internet
- Allow SSH only from your admin PC or VPN
- Block the Pi from reaching sensitive LAN devices unless required

This gives strong protection even if the Pi or camera stack is compromised.

---

## 12. Improve SD card reliability

For daily streaming:

- Use a high-endurance SD card
- Keep logs rotated
- Avoid writing video recordings to the SD card unless needed
- Consider a USB SSD for long-running deployments
- Keep a known-good backup image after setup

Useful checks:

```bash
df -h
free -h
vcgencmd measure_temp 2>/dev/null || true
```

---

## 13. Back up the important parts

Back up:

- AquaCam config
- OAuth client secret JSON
- OAuth token JSON
- YouTube stream key/state files
- systemd service file
- sudoers file

Example:

```bash
sudo tar -czf aquacam-backup.tar.gz \
  /opt/aquacam/configs \
  /opt/aquacam/secrets \
  /opt/aquacam/state \
  /etc/systemd/system/aquacam-ytapi.service \
  /etc/sudoers.d/aquacam-shutdown
```

If the backup contains OAuth tokens or stream keys, store it encrypted and do not commit it to GitHub.

---

## 14. Basic monitoring checklist

At minimum, monitor:

- `aquacam-ytapi.service` is active
- ffmpeg is running during the stream window
- Disk is not full
- Pi is not overheating
- YouTube API preparation succeeded
- Stream key/token files still exist and are readable only by the service user

Quick commands:

```bash
systemctl status aquacam-ytapi.service
journalctl -u aquacam-ytapi.service -n 100 --no-pager
df -h
sudo ss -tulpn
```

---

## Recommended minimum checklist

For most AquaCam deployments, do these first:

- [ ] SSH keys only
- [ ] Root SSH login disabled
- [ ] UFW enabled, SSH allowed only from LAN/VPN
- [ ] Automatic security updates enabled
- [ ] AquaCam runs as a dedicated non-root user
- [ ] Secrets and state files set to `chmod 600`
- [ ] Logs rotated or journald size-limited
- [ ] systemd service has moderate hardening
- [ ] Pi is on an IoT/guest/VLAN network if possible
- [ ] Encrypted backup made after setup

---

## Important warning

Harden in small steps and test after each change. Camera access, ffmpeg, OAuth token refresh, and shutdown behavior can break if permissions are made too restrictive.

Safe workflow:

```bash
sudo systemctl restart aquacam-ytapi.service
sudo systemctl status aquacam-ytapi.service
journalctl -u aquacam-ytapi.service -n 100 --no-pager
```

If the stream fails after a hardening change, revert the most recent change first.
