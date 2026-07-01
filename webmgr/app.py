#!/usr/bin/env python3
"""Tiny AquaCam web settings manager.

No third-party dependencies. Designed for a Raspberry Pi LAN admin page.
First visit creates the admin user, then authenticated users can edit selected
settings in aquacam-stream.conf.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import html
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Tuple
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PROJECT_DIR = BASE_DIR.parent
CONFIG_FILE = Path(os.environ.get("AQUACAM_CONFIG", DEFAULT_PROJECT_DIR / "aquacam-stream.conf"))
STATE_FILE = Path(os.environ.get("AQUACAM_WEB_STATE", DEFAULT_PROJECT_DIR / ".aquacam-webmgr.json"))
HOST = os.environ.get("AQUACAM_WEB_HOST", "0.0.0.0")
PORT = int(os.environ.get("AQUACAM_WEB_PORT", "8080"))
SESSION_TTL_SECONDS = int(os.environ.get("AQUACAM_SESSION_TTL_SECONDS", "86400"))
SERVICE_NAME = os.environ.get("AQUACAM_SERVICE", "aquacam-ytapi.service")
YT_SCOPES = ["https://www.googleapis.com/auth/youtube"]
EMAIL_CONFIG_FILE = Path(os.environ.get("AQUACAM_EMAIL_CONFIG", DEFAULT_PROJECT_DIR / "aquacam-email.conf"))

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
INT_RE = re.compile(r"^\d+$")
BITRATE_RE = re.compile(r"^\d+[kKmM]?$")
SIZE_RE = re.compile(r"^\d{2,5}x\d{2,5}$")
DEVICE_RE = re.compile(r"^/dev/[A-Za-z0-9_.\-/]+$")
PATH_RE = re.compile(r"^/[A-Za-z0-9_ .@%+=:,/\-]+$")

FIELDS = [
    ("Schedule", [
        ("START_TIME", "Start time", "time", "Stream must not start before this time."),
        ("STOP_TIME", "Stop time", "time", "Stream stops at/after this time."),
        ("CHECK_INTERVAL", "Check interval seconds", "int", "How often the supervisor checks schedule/progress."),
    ]),
    ("Shutdown", [
        ("SHUTDOWN_AFTER_STOP", "Shutdown after stop", "bool", "Cleanly power down after the stop window."),
        ("SHUTDOWN_TIME", "Shutdown time", "time_or_empty", "Target shutdown time; blank uses delay only."),
        ("SHUTDOWN_DELAY_SECONDS", "Shutdown delay seconds", "int", "Grace period before shutdown."),
    ]),
    ("Video / audio", [
        ("VIDEO_DEVICE", "Video device", "device", "Usually /dev/video0."),
        ("INPUT_FORMAT", "Input format", "short", "Usually mjpeg."),
        ("VIDEO_SIZE", "Video size", "size", "Example: 1920x1080 or 1280x720."),
        ("FRAMERATE", "Frame rate", "int", "Requested camera FPS."),
        ("VIDEO_ENCODER", "Video encoder", "short", "Example: h264_v4l2m2m or libx264, if supported by script."),
        ("VIDEO_BITRATE", "Video bitrate", "bitrate", "Example: 1400k."),
        ("MAXRATE", "Max bitrate", "bitrate", "Example: 1400k."),
        ("BUFSIZE", "Buffer size", "bitrate", "Example: 2800k."),
        ("GOP", "GOP", "int", "Keyframe interval."),
        ("AUDIO_BITRATE", "Audio bitrate", "bitrate", "Example: 128k."),
        ("AUDIO_RATE", "Audio rate", "int", "Example: 44100."),
    ]),
    ("YouTube API", [
        ("YT_API_ENABLED", "YouTube API enabled", "bool", "Prepare/end broadcasts via YouTube API."),
        ("YT_PRIVACY_STATUS", "Privacy", "choice:public,unlisted,private", "Broadcast privacy."),
        ("YT_BROADCAST_TITLE", "Broadcast title", "text", "{date} is supported by the prepare script."),
        ("YT_BROADCAST_DESCRIPTION", "Description", "textarea", "YouTube video description."),
        ("YT_BROADCAST_TAGS", "Tags", "text", "Comma-separated tags."),
        ("YT_LATENCY_PREFERENCE", "Latency", "choice:normal,low,ultraLow", "YouTube live latency preference."),
        ("YT_ENABLE_AUTO_START", "Auto-start", "bool", "Let YouTube go live when ingest starts."),
        ("YT_ENABLE_AUTO_STOP", "Auto-stop", "bool", "Let YouTube stop when ingest ends."),
        ("YT_ENABLE_DVR", "Enable DVR", "bool", "Allow rewind during live."),
        ("YT_ENABLE_EMBED", "Enable embed", "bool", "Allow embedding."),
        ("YT_SELF_DECLARED_MADE_FOR_KIDS", "Made for kids", "bool", "Usually false for AquaCam."),
    ]),
    ("Resilience", [
        ("MAX_RETRIES", "Max retries", "int", "0 means infinite retries."),
        ("RETRY_DELAY", "Retry delay seconds", "int", "Delay after ffmpeg exits."),
        ("STUCK_TIMEOUT_SECONDS", "Stuck timeout seconds", "int", "Restart if ffmpeg progress stops."),
        ("WARM_RESTART_ENABLED", "Warm restart enabled", "bool", "Usually false in API mode."),
        ("WARM_RESTART_AFTER_SECONDS", "Warm restart after seconds", "int", "If warm restart is enabled."),
    ]),
    ("Paths", [
        ("LOG_FILE", "Log file", "path", "Stream supervisor log path."),
        ("PROGRESS_FILE", "Progress file", "path", "ffmpeg progress file path."),
    ]),
]

FIELD_TYPES = {key: typ for _, group in FIELDS for key, _, typ, _ in group}
FIELD_LABELS = {key: label for _, group in FIELDS for key, label, _, _ in group}

EMAIL_FIELDS = [
    ("SMTP_ENABLED", "Email alerts enabled", "bool", "Send an email if the boot-time YouTube token check fails."),
    ("SMTP_HOST", "SMTP host", "text", "For Gmail SMTP use smtp.gmail.com."),
    ("SMTP_PORT", "SMTP port", "int", "For Gmail STARTTLS use 587."),
    ("SMTP_STARTTLS", "Use STARTTLS", "bool", "Usually true for port 587."),
    ("SMTP_SSL", "Use SSL", "bool", "Usually false for Gmail port 587; true for port 465."),
    ("SMTP_USER", "SMTP username", "text", "For Gmail, your Gmail address."),
    ("SMTP_PASSWORD", "SMTP password / app password", "password", "For Gmail, use a Google App Password, not your normal password."),
    ("MAIL_FROM", "From address", "text", "Usually same as SMTP username."),
    ("MAIL_TO", "Alert recipient", "text", "Where AquaCam should send alerts."),
    ("NOTIFY_TOKEN_STATUS", "Token status daily / boot", "bool", "Send an OK email when the token check passes."),
    ("NOTIFY_TOKEN_EXPIRED", "Token expired / auth failed", "bool", "Send an alert if YouTube token check fails."),
    ("NOTIFY_STREAM_STARTED", "Live stream started", "bool", "Send an email when FFmpeg starts streaming."),
    ("NOTIFY_STREAM_STOPPED", "Live stream stopped", "bool", "Send an email when FFmpeg stops."),
    ("NOTIFY_PI_ALIVE", "Pi is alive after boot", "bool", "Send an email after boot when the monitor runs."),
    ("NOTIFY_PI_SHUTTING_DOWN", "Pi is shutting down", "bool", "Send an email just before AquaCam requests shutdown."),
]
EMAIL_FIELD_TYPES = {key: typ for key, _, typ, _ in EMAIL_FIELDS}

ASSIGN_RE = re.compile(r'^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*?)(?P<comment>\s+#.*)?$')


def read_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def write_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
    os.chmod(STATE_FILE, 0o600)


def hash_password(password: str, salt_b64: str | None = None) -> Tuple[str, str]:
    salt = base64.b64decode(salt_b64) if salt_b64 else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return base64.b64encode(salt).decode(), base64.b64encode(digest).decode()


def verify_password(password: str, state: dict) -> bool:
    salt = state.get("password_salt", "")
    expected = state.get("password_hash", "")
    if not salt or not expected:
        return False
    _, actual = hash_password(password, salt)
    return hmac.compare_digest(actual, expected)


def make_session(state: dict, username: str) -> str:
    sid = secrets.token_urlsafe(32)
    state.setdefault("sessions", {})[sid] = {"username": username, "created": int(time.time())}
    write_state(state)
    return sid


def logged_in(headers) -> bool:
    state = read_state()
    raw = headers.get("Cookie", "")
    cookie = SimpleCookie(raw)
    morsel = cookie.get("aquacam_session")
    if not morsel:
        return False
    sid = morsel.value
    sess = state.get("sessions", {}).get(sid)
    if not sess:
        return False
    if int(time.time()) - int(sess.get("created", 0)) > SESSION_TTL_SECONDS:
        state.get("sessions", {}).pop(sid, None)
        write_state(state)
        return False
    return True


def parse_config() -> Tuple[Dict[str, str], list[str]]:
    if not CONFIG_FILE.exists():
        return {}, []
    lines = CONFIG_FILE.read_text().splitlines()
    values: Dict[str, str] = {}
    for line in lines:
        m = ASSIGN_RE.match(line)
        if not m:
            continue
        key = m.group("key")
        raw = m.group("value").strip()
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            raw = raw[1:-1]
        values[key] = raw
    return values, lines


def parse_key_value_file(path: Path, defaults: Dict[str, str] | None = None) -> Dict[str, str]:
    values = dict(defaults or {})
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        m = ASSIGN_RE.match(line.strip())
        if not m:
            continue
        key = m.group("key")
        raw = m.group("value").strip()
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            raw = raw[1:-1]
        values[key] = raw
    return values


def shell_quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`') + '"'


def validate_value(key: str, value: str) -> str | None:
    typ = FIELD_TYPES[key]
    if typ == "bool":
        return None if value in ("true", "false") else "must be true or false"
    if typ == "time":
        return None if TIME_RE.match(value) else "must be HH:MM"
    if typ == "time_or_empty":
        return None if value == "" or TIME_RE.match(value) else "must be blank or HH:MM"
    if typ == "int":
        return None if INT_RE.match(value) else "must be a whole number"
    if typ == "bitrate":
        return None if BITRATE_RE.match(value) else "must look like 1400k"
    if typ == "size":
        return None if SIZE_RE.match(value) else "must look like 1280x720"
    if typ == "device":
        return None if DEVICE_RE.match(value) else "must be a /dev/... path"
    if typ == "path":
        return None if PATH_RE.match(value) else "must be an absolute path"
    if typ == "short":
        return None if re.match(r"^[A-Za-z0-9_.-]+$", value) else "contains unsupported characters"
    if typ.startswith("choice:"):
        choices = typ.split(":", 1)[1].split(",")
        return None if value in choices else "must be one of " + ", ".join(choices)
    if typ in ("text", "textarea"):
        return None if "\x00" not in value else "contains invalid character"
    return None


def save_config(new_values: Dict[str, str]) -> None:
    old_values, lines = parse_config()
    seen = set()
    out = []
    for line in lines:
        m = ASSIGN_RE.match(line)
        if not m or m.group("key") not in new_values:
            out.append(line)
            continue
        key = m.group("key")
        seen.add(key)
        comment = m.group("comment") or ""
        out.append(f"{key}={shell_quote(new_values[key])}{comment}")
    missing = [key for key in new_values if key not in seen and key in FIELD_TYPES]
    if missing:
        out.append("")
        out.append("# Added by AquaCam web manager")
        for key in missing:
            out.append(f"{key}={shell_quote(new_values[key])}")
    backup = CONFIG_FILE.with_suffix(CONFIG_FILE.suffix + f".bak.{time.strftime('%Y%m%d-%H%M%S')}")
    if CONFIG_FILE.exists():
        backup.write_text(CONFIG_FILE.read_text())
    CONFIG_FILE.write_text("\n".join(out) + "\n")


def save_email_config(new_values: Dict[str, str]) -> None:
    if EMAIL_CONFIG_FILE.exists():
        backup = EMAIL_CONFIG_FILE.with_suffix(EMAIL_CONFIG_FILE.suffix + f".bak.{time.strftime('%Y%m%d-%H%M%S')}")
        backup.write_text(EMAIL_CONFIG_FILE.read_text())
    lines = [
        "# AquaCam SMTP email alert settings",
        "# For Gmail, enable 2-Step Verification and use an App Password.",
    ]
    for key, _, _, _ in EMAIL_FIELDS:
        lines.append(f"{key}={shell_quote(new_values.get(key, ''))}")
    EMAIL_CONFIG_FILE.write_text("\n".join(lines) + "\n")
    os.chmod(EMAIL_CONFIG_FILE, 0o600)


def validate_email_config(values: Dict[str, str]) -> list[str]:
    errors = []
    for key in ("SMTP_ENABLED", "SMTP_STARTTLS", "SMTP_SSL", "NOTIFY_TOKEN_STATUS", "NOTIFY_TOKEN_EXPIRED", "NOTIFY_STREAM_STARTED", "NOTIFY_STREAM_STOPPED", "NOTIFY_PI_ALIVE", "NOTIFY_PI_SHUTTING_DOWN"):
        if values.get(key) not in ("true", "false"):
            errors.append(f"{key} must be true or false")
    if values.get("SMTP_PORT") and not INT_RE.match(values["SMTP_PORT"]):
        errors.append("SMTP_PORT must be a number")
    if values.get("SMTP_ENABLED") == "true":
        for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"):
            if not values.get(key):
                errors.append(f"{key} is required when email alerts are enabled")
    return errors


def run_email_test() -> Tuple[bool, str]:
    script = DEFAULT_PROJECT_DIR / "scripts" / "aquacam_token_monitor.py"
    py = str(DEFAULT_PROJECT_DIR / ".venv" / "bin" / "python")
    if not Path(py).exists():
        py = shutil.which("python3") or "python3"
    return run_cmd([py, str(script), "--config", str(CONFIG_FILE), "--email-config", str(EMAIL_CONFIG_FILE), "--notify-success"], timeout=150)


def restart_service() -> Tuple[bool, str]:
    """Restart the stream service.

    Prefer systemctl via passwordless sudo when available. On Kevin's Pi the
    web manager runs as the same `aquacam` user as the stream script, while
    systemd has `Restart=always`. If sudo is unavailable, killing that user's
    `start_stream.sh` process is a safe lightweight restart trigger: the script
    cleanup trap stops ffmpeg/end-broadcast, exits, and systemd starts it again.
    """
    cmd = ["sudo", "-n", "/bin/systemctl", "restart", SERVICE_NAME]
    try:
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
        if p.returncode == 0:
            return True, p.stdout.strip() or f"systemctl restart {SERVICE_NAME} succeeded"
        sudo_output = p.stdout.strip()
    except Exception as exc:
        sudo_output = str(exc)

    script_path = str(DEFAULT_PROJECT_DIR / "start_stream.sh")
    try:
        ps = subprocess.run(
            ["ps", "-u", str(os.getuid()), "-o", "pid=,args="],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        pids = []
        for line in ps.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            pid_s, _, args = line.partition(" ")
            if not pid_s.isdigit():
                continue
            args = args.strip()
            if args in (f"bash {script_path}", f"/usr/bin/bash {script_path}", script_path):
                pids.append(int(pid_s))
        if not pids:
            # The service may be between auto-restart cycles, or inactive outside
            # maintenance. The settings are already saved; avoid showing a scary
            # failure when there is simply no same-user process to signal.
            return True, f"settings saved; sudo restart unavailable ({sudo_output}); no running start_stream.sh process found to signal"
        for pid in pids:
            if pid != os.getpid():
                os.kill(pid, 15)
        return True, f"sudo restart unavailable; signalled start_stream.sh PID(s) {', '.join(map(str, pids))}. systemd should auto-restart it."
    except Exception as exc:
        return False, f"sudo restart failed ({sudo_output}); signal fallback failed: {exc}"


def project_path(values: Dict[str, str], key: str, default: str = "") -> Path:
    raw = values.get(key) or default
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = CONFIG_FILE.parent / p
    return p


def prepare_script_path() -> Path:
    candidates = [DEFAULT_PROJECT_DIR / "ytapi_prepare_broadcast.py", DEFAULT_PROJECT_DIR / "scripts" / "ytapi_prepare_broadcast.py"]
    return next((p for p in candidates if p.exists()), candidates[0])


def run_cmd(cmd: list[str], timeout: int = 20) -> Tuple[bool, str]:
    try:
        p = subprocess.run(cmd, cwd=str(DEFAULT_PROJECT_DIR), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode == 0, p.stdout.strip()
    except Exception as exc:
        return False, str(exc)


def service_summary(values: Dict[str, str]) -> dict:
    active_ok, active = run_cmd(["systemctl", "is-active", SERVICE_NAME], timeout=5)
    enabled_ok, enabled = run_cmd(["systemctl", "is-enabled", SERVICE_NAME], timeout=5)
    ffmpeg_ok, ffmpeg = run_cmd(["pgrep", "-a", "ffmpeg"], timeout=5)
    progress_file = project_path(values, "PROGRESS_FILE", "/tmp/aquacam-ffmpeg.progress")
    progress = ""
    if progress_file.exists():
        try:
            progress = "\n".join(progress_file.read_text(errors="replace").splitlines()[-20:])
        except Exception as exc:
            progress = f"Could not read progress file: {exc}"
    return {
        "active": active if active_ok else active or "unknown",
        "enabled": enabled if enabled_ok else enabled or "unknown",
        "ffmpeg": ffmpeg if ffmpeg_ok else "not running",
        "progress": progress or "No progress file found yet.",
    }


def token_summary(values: Dict[str, str]) -> dict:
    token_file = project_path(values, "YT_TOKEN_FILE", "token.json")
    info = {"path": str(token_file), "status": "missing", "details": "No token file found.", "class": "error"}
    if not token_file.exists():
        return info
    try:
        data = json.loads(token_file.read_text())
        expiry_raw = data.get("expiry", "")
        has_refresh = bool(data.get("refresh_token"))
        status = "present"
        details = [f"refresh token: {'yes' if has_refresh else 'no'}"]
        if expiry_raw:
            expiry = dt.datetime.fromisoformat(expiry_raw.replace("Z", "+00:00"))
            now = dt.datetime.now(expiry.tzinfo or dt.timezone.utc)
            if expiry <= now:
                status = "access token expired, refresh should be attempted automatically"
            else:
                status = "valid access token"
            details.append(f"access token expiry: {expiry_raw}")
        info.update({"status": status, "details": "; ".join(details), "class": "ok" if has_refresh else "error"})
    except Exception as exc:
        info.update({"status": "unreadable", "details": str(exc), "class": "error"})
    return info


def latest_log(values: Dict[str, str], lines: int = 80) -> str:
    log_file = project_path(values, "LOG_FILE", str(DEFAULT_PROJECT_DIR / "stream.log"))
    if not log_file.exists():
        return f"Log file not found: {log_file}"
    try:
        raw = subprocess.run(["tail", "-n", str(lines), str(log_file)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=8).stdout
        return raw.replace("\r", "\n")
    except Exception as exc:
        return f"Could not read log: {exc}"


def youtube_dry_run() -> Tuple[bool, str]:
    script = prepare_script_path()
    py = shutil.which("python3") or "python3"
    venv_py = DEFAULT_PROJECT_DIR / ".venv" / "bin" / "python"
    if venv_py.exists():
        py = str(venv_py)
    return run_cmd([py, str(script), "--config", str(CONFIG_FILE), "--auth-check"], timeout=90)


def oauth_flow(redirect_uri: str):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    try:
        from google_auth_oauthlib.flow import Flow
    except Exception as exc:
        raise RuntimeError(f"Missing OAuth dependency: {exc}") from exc
    values, _ = parse_config()
    client_secrets = project_path(values, "YT_CLIENT_SECRETS", "client_secret.json")
    if not client_secrets.exists():
        raise FileNotFoundError(f"Missing client secret file: {client_secrets}")
    return Flow.from_client_secrets_file(str(client_secrets), scopes=YT_SCOPES, redirect_uri=redirect_uri)


def oauth_redirect_uri(handler: BaseHTTPRequestHandler) -> str:
    host = handler.headers.get("Host", f"aquacam.local:{PORT}")
    return f"http://{host}/oauth/callback"


def oauth_authorization_url(flow, redirect_uri: str) -> Tuple[str, str]:
    kwargs = {"access_type": "offline", "include_granted_scopes": "true", "prompt": "consent"}
    return flow.authorization_url(**kwargs)


def oauth_client_info(values: Dict[str, str]) -> Tuple[str, str]:
    client_secrets = project_path(values, "YT_CLIENT_SECRETS", "client_secret.json")
    data = json.loads(client_secrets.read_text())
    cfg = data.get("installed") or data.get("web") or {}
    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret", "")
    if not client_id:
        raise RuntimeError(f"Missing client_id in {client_secrets}")
    return client_id, client_secret


def post_form_json(url: str, data: Dict[str, str], timeout: int = 20) -> dict:
    encoded = urlencode(data).encode()
    req = Request(url, data=encoded, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        body = ""
        if hasattr(exc, "read"):
            try:
                body = exc.read().decode()
            except Exception:
                body = ""
        if body:
            try:
                return json.loads(body)
            except Exception:
                raise RuntimeError(body) from exc
        raise


def write_google_token(values: Dict[str, str], token: dict) -> Path:
    client_id, client_secret = oauth_client_info(values)
    expires_in = int(token.get("expires_in", 3600))
    expiry = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=expires_in)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    creds = {
        "token": token.get("access_token"),
        "refresh_token": token.get("refresh_token"),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": token.get("scope", " ".join(YT_SCOPES)).split(),
        "expiry": expiry,
    }
    if not creds["token"] or not creds["refresh_token"]:
        raise RuntimeError("Google did not return both access_token and refresh_token. Try again and approve consent.")
    token_file = project_path(values, "YT_TOKEN_FILE", "token.json")
    if token_file.exists():
        backup = token_file.with_name(token_file.name + f".bak.{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(token_file, backup)
    token_file.write_text(json.dumps(creds, indent=2) + "\n")
    os.chmod(token_file, 0o600)
    return token_file


def start_device_flow(values: Dict[str, str]) -> dict:
    client_id, _ = oauth_client_info(values)
    return post_form_json("https://oauth2.googleapis.com/device/code", {
        "client_id": client_id,
        "scope": " ".join(YT_SCOPES),
    })


def poll_device_flow(values: Dict[str, str], device_code: str) -> dict:
    client_id, client_secret = oauth_client_info(values)
    payload = {
        "client_id": client_id,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    if client_secret:
        payload["client_secret"] = client_secret
    return post_form_json("https://oauth2.googleapis.com/token", payload)


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:980px;margin:24px auto;padding:0 14px;background:#f7f9fb;color:#17202a}}
.card{{background:white;border:1px solid #d7dee8;border-radius:12px;padding:18px;margin:14px 0;box-shadow:0 1px 2px #0001}}
label{{display:block;font-weight:650;margin:.7rem 0 .25rem}} input,select,textarea{{width:100%;box-sizing:border-box;padding:.55rem;border:1px solid #b8c2cc;border-radius:8px;font:inherit}}
textarea{{min-height:90px}} .hint{{color:#52616f;font-size:.9rem}} .row{{display:grid;grid-template-columns:1fr 1fr;gap:14px}} @media(max-width:700px){{.row{{grid-template-columns:1fr}}}}
button,.button{{background:#1769aa;color:white;border:0;border-radius:8px;padding:.65rem 1rem;text-decoration:none;display:inline-block;font-weight:650;cursor:pointer}}
.danger{{background:#9b1c1c}} .secondary{{background:#52616f}} .muted{{color:#52616f}} .error{{background:#ffe9e9;border-color:#f2b8b8}} .ok{{background:#e9f7ef;border-color:#a9dfbf}}
header{{display:flex;align-items:center;justify-content:space-between;gap:10px}} code{{background:#eef2f6;padding:2px 5px;border-radius:5px}} pre{{white-space:pre-wrap;overflow:auto;background:#0f1720;color:#d8e5f2;padding:12px;border-radius:8px;font-size:.9rem}} .pill{{display:inline-block;padding:3px 8px;border-radius:999px;background:#eef2f6;font-weight:700}}
</style></head><body><header><h1>{esc(title)}</h1><nav><a href="/">Dashboard</a> · <a href="/logs">Logs</a> · <a href="/logout">Log out</a></nav></header>{body}</body></html>""".encode()


class Handler(BaseHTTPRequestHandler):
    server_version = "AquaCamWebMgr/0.1"

    def send_html(self, status: int, body: bytes, cookie: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, payload: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def redirect(self, path: str, cookie: str | None = None) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", path)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def read_post(self) -> Dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        parsed = parse_qs(raw, keep_blank_values=True)
        return {k: v[-1] for k, v in parsed.items()}

    def require_auth(self) -> bool:
        state = read_state()
        if not state.get("username"):
            self.redirect("/setup")
            return False
        if not logged_in(self.headers):
            self.redirect("/login")
            return False
        return True

    def do_GET(self) -> None:
        state = read_state()
        if self.path.startswith("/setup"):
            if state.get("username"):
                self.redirect("/login")
                return
            self.send_html(200, page("AquaCam setup", """
<div class="card"><p>First-time setup. Create the web admin login for this AquaCam.</p>
<form method="post" action="/setup"><label>Username</label><input name="username" required autocomplete="username"><label>Password</label><input name="password" type="password" required autocomplete="new-password"><button>Create login</button></form></div>"""))
            return
        if self.path.startswith("/login"):
            self.send_html(200, page("AquaCam login", """
<div class="card"><form method="post" action="/login"><label>Username</label><input name="username" required autocomplete="username"><label>Password</label><input name="password" type="password" required autocomplete="current-password"><button>Log in</button></form></div>"""))
            return
        if self.path.startswith("/logout"):
            cookie = "aquacam_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
            self.redirect("/login", cookie)
            return
        if not self.require_auth():
            return
        parsed_path = urlsplit(self.path)
        path_only = parsed_path.path
        values, _ = parse_config()

        if path_only == "/logs":
            status = service_summary(values)
            body = f'''<div class="card"><h2>Service</h2><p><b>Status:</b> <span class="pill">{esc(status['active'])}</span> &nbsp; <b>Enabled:</b> {esc(status['enabled'])}</p><p><b>FFmpeg:</b></p><pre>{esc(status['ffmpeg'])}</pre><p><b>Progress:</b></p><pre>{esc(status['progress'])}</pre></div><div class="card"><h2>Latest stream log</h2><pre>{esc(latest_log(values))}</pre></div>'''
            self.send_html(200, page("AquaCam logs", body))
            return

        if path_only == "/health":
            body = '<div class="card"><h2>YouTube API health check removed</h2><p>This manual check was removed because it could block the web UI and is not required for normal streaming. Use <b>Re-authorise YouTube</b> if the token is missing/revoked, then let the stream service prepare the broadcast at start time.</p></div><p><a class="button" href="/">Back to dashboard</a></p>'
            self.send_html(200, page("AquaCam YouTube health", body))
            return

        if path_only == "/youtube/reauth":
            try:
                device = start_device_flow(values)
                if device.get("error"):
                    if device.get("error") == "invalid_client":
                        raise RuntimeError("Google rejected the current OAuth client for device sign-in: invalid_client / Invalid client type. Create a Google OAuth Client ID of type 'TVs and Limited Input devices', download it as client_secret.json, and place it at the configured YT_CLIENT_SECRETS path. Then this self-contained re-authorisation page will work without SSH tunnels or callback URLs.")
                    raise RuntimeError(f"{device.get('error')}: {device.get('error_description', '')}")
                state = read_state()
                state["device_oauth"] = {"device_code": device["device_code"], "created": int(time.time()), "expires_in": int(device.get("expires_in", 1800))}
                write_state(state)
                verify_url = device.get("verification_url") or device.get("verification_uri") or "https://www.google.com/device"
                user_code = device.get("user_code", "")
                interval = int(device.get("interval", 5))
                body = f'''<div class="card"><h2>YouTube re-authorisation</h2><p>This uses Google's device sign-in flow, so no SSH tunnel or callback URL is needed.</p><ol><li>Click <a class="button" href="{esc(verify_url)}" target="_blank" rel="noopener">Open Google device sign-in</a></li><li>Enter this code:</li></ol><h1 style="letter-spacing:.12em">{esc(user_code)}</h1><p id="oauth-status" class="hint">Waiting for Google approval...</p><p><a class="button secondary" href="/">Back to dashboard</a></p><script>
async function poll(){{
  try{{
    const r = await fetch('/youtube/device/poll', {{cache:'no-store'}});
    const j = await r.json();
    document.getElementById('oauth-status').textContent = j.message || j.status;
    if(j.status === 'ok'){{ setTimeout(()=>location.href='/', 1500); return; }}
    if(j.status === 'error'){{ return; }}
  }}catch(e){{ document.getElementById('oauth-status').textContent = 'Poll failed: '+e; }}
  setTimeout(poll, {interval * 1000});
}}
setTimeout(poll, {interval * 1000});
</script><p class="hint">If Google says the app is in Testing, its refresh token may expire after about 7 days. Move the OAuth app to Production in Google Cloud to avoid that testing-mode expiry.</p></div>'''
            except Exception as exc:
                body = f'<div class="card error"><h2>Could not start OAuth</h2><pre>{esc(exc)}</pre></div>'
            self.send_html(200, page("AquaCam YouTube reauth", body))
            return

        if path_only == "/youtube/device/poll":
            try:
                state = read_state()
                dev = state.get("device_oauth") or {}
                code = dev.get("device_code")
                if not code:
                    self.send_json(400, {"status": "error", "message": "No device authorisation is in progress."})
                    return
                token = poll_device_flow(values, code)
                err = token.get("error")
                if err in ("authorization_pending", "slow_down"):
                    self.send_json(200, {"status": "pending", "message": "Waiting for Google approval..."})
                    return
                if err:
                    self.send_json(200, {"status": "error", "message": f"{err}: {token.get('error_description', '')}"})
                    return
                token_file = write_google_token(values, token)
                state.pop("device_oauth", None)
                write_state(state)
                self.send_json(200, {"status": "ok", "message": f"YouTube token saved to {token_file}. Returning to dashboard..."})
            except Exception as exc:
                self.send_json(500, {"status": "error", "message": str(exc)})
            return

        if path_only == "/oauth/callback":
            try:
                state = read_state()
                oauth = state.get("oauth", {})
                expected_state = oauth.get("state")
                got_state = parse_qs(parsed_path.query).get("state", [""])[0]
                if not expected_state or got_state != expected_state:
                    raise RuntimeError("OAuth state mismatch. Please start re-authorisation again.")
                flow = oauth_flow(oauth.get("redirect_uri") or oauth_redirect_uri(self))
                flow.fetch_token(authorization_response=f"http://{self.headers.get('Host', f'aquacam.local:{PORT}')}{self.path}")
                token_file = project_path(values, "YT_TOKEN_FILE", "token.json")
                if token_file.exists():
                    backup = token_file.with_name(token_file.name + f".bak.{time.strftime('%Y%m%d-%H%M%S')}")
                    shutil.copy2(token_file, backup)
                token_file.write_text(flow.credentials.to_json())
                os.chmod(token_file, 0o600)
                body = f'<div class="card ok"><h2>YouTube token saved</h2><p>New token written to <code>{esc(token_file)}</code>.</p><p>The stream service will use this token automatically at the next start time.</p></div><p><a class="button" href="/">Back to dashboard</a></p>'
            except Exception as exc:
                body = f'<div class="card error"><h2>OAuth callback failed</h2><pre>{esc(exc)}</pre></div><p><a class="button" href="/youtube/reauth">Try again</a></p>'
            self.send_html(200, page("AquaCam OAuth callback", body))
            return

        msg = ""
        if parsed_path.query:
            qs = parse_qs(parsed_path.query)
            if qs.get("saved"):
                msg = '<div class="card ok">Settings saved. Restart the service for running-stream changes to apply.</div>'
            if qs.get("restarted"):
                msg = '<div class="card ok">Settings saved and restart command succeeded.</div>'
            if qs.get("restart_failed"):
                msg = '<div class="card error">Settings saved, but service restart failed. It may need a sudoers rule or manual restart.</div>'
            if qs.get("email_saved"):
                msg = '<div class="card ok">Email alert settings saved.</div>'
        token = token_summary(values)
        svc = service_summary(values)
        email_defaults = {
            "SMTP_ENABLED": "false",
            "SMTP_HOST": "smtp.gmail.com",
            "SMTP_PORT": "587",
            "SMTP_STARTTLS": "true",
            "SMTP_SSL": "false",
            "SMTP_USER": "",
            "SMTP_PASSWORD": "",
            "MAIL_FROM": "",
            "MAIL_TO": "",
            "NOTIFY_TOKEN_STATUS": "false",
            "NOTIFY_TOKEN_EXPIRED": "true",
            "NOTIFY_STREAM_STARTED": "false",
            "NOTIFY_STREAM_STOPPED": "false",
            "NOTIFY_PI_ALIVE": "false",
            "NOTIFY_PI_SHUTTING_DOWN": "true",
        }
        email_values = parse_key_value_file(EMAIL_CONFIG_FILE, email_defaults)
        email_status = "enabled" if email_values.get("SMTP_ENABLED") == "true" else "disabled"
        dashboard = f'''<div class="card"><h2>Status</h2><p><b>Stream service:</b> <span class="pill">{esc(svc['active'])}</span> &nbsp; <b>FFmpeg:</b> {esc('running' if svc['ffmpeg'] != 'not running' else 'not running')}</p><p><b>YouTube token:</b> <span class="pill">{esc(token['status'])}</span></p><p class="hint">{esc(token['details'])}<br>{esc(token['path'])}</p><p><a class="button secondary" href="/youtube/reauth">Re-authorise YouTube</a> <a class="button secondary" href="/logs">View logs/progress</a></p><p class="hint">Tip: Google OAuth refresh tokens cannot be recreated fully automatically if Google revokes them; if this keeps happening after about 7 days, move the Google OAuth app from Testing to Production.</p></div>'''
        email_card = [f'''<div class="card"><h2>Email alerts</h2><p><b>Status:</b> <span class="pill">{esc(email_status)}</span></p><p class="hint">AquaCam checks the YouTube token after each boot. If the check fails, it can send an SMTP email alert. For Gmail, use an App Password.</p><form method="post" action="/email"><div class="row">''']
        for key, label, typ, hint in EMAIL_FIELDS:
            val = email_values.get(key, "")
            email_card.append("<div>")
            email_card.append(f'<label for="email_{esc(key)}">{esc(label)}</label>')
            if typ == "bool":
                checked = "checked" if val == "true" else ""
                email_card.append(f'<input type="hidden" name="{esc(key)}" value="false"><input id="email_{esc(key)}" name="{esc(key)}" type="checkbox" value="true" {checked} style="width:auto">')
            else:
                input_type = "password" if typ == "password" else "text"
                email_card.append(f'<input id="email_{esc(key)}" name="{esc(key)}" type="{input_type}" value="{esc(val)}">')
            email_card.append(f'<div class="hint">{esc(key)} — {esc(hint)}</div></div>')
        email_card.append('</div><p><button name="action" value="save">Save email settings</button> <button name="action" value="test" class="secondary">Save and send test email</button></p></form></div>')
        body = [msg, dashboard, "".join(email_card), f'<div class="card muted">Editing <code>{esc(CONFIG_FILE)}</code>. Backups are created beside the config before every save.</div>', '<form method="post" action="/save">']
        for section, group in FIELDS:
            body.append(f'<div class="card"><h2>{esc(section)}</h2><div class="row">')
            for key, label, typ, hint in group:
                val = values.get(key, "")
                body.append('<div>')
                body.append(f'<label for="{esc(key)}">{esc(label)}</label>')
                if typ == "bool":
                    body.append(f'<select id="{esc(key)}" name="{esc(key)}"><option value="true" {"selected" if val=="true" else ""}>true</option><option value="false" {"selected" if val!="true" else ""}>false</option></select>')
                elif typ.startswith("choice:"):
                    choices = typ.split(":", 1)[1].split(",")
                    body.append(f'<select id="{esc(key)}" name="{esc(key)}">')
                    for choice in choices:
                        body.append(f'<option value="{esc(choice)}" {"selected" if val==choice else ""}>{esc(choice)}</option>')
                    body.append('</select>')
                elif typ == "textarea":
                    body.append(f'<textarea id="{esc(key)}" name="{esc(key)}">{esc(val)}</textarea>')
                else:
                    input_type = "time" if typ in ("time", "time_or_empty") else "text"
                    body.append(f'<input id="{esc(key)}" name="{esc(key)}" type="{input_type}" value="{esc(val)}">')
                body.append(f'<div class="hint">{esc(key)} — {esc(hint)}</div></div>')
            body.append('</div></div>')
        body.append('<div class="card"><button name="action" value="save">Save settings</button> <button name="action" value="save_restart" class="danger">Save and restart service</button></div></form>')
        self.send_html(200, page("AquaCam settings", "".join(body)))

    def do_POST(self) -> None:
        if self.path == "/setup":
            state = read_state()
            if state.get("username"):
                self.redirect("/login")
                return
            form = self.read_post()
            username = form.get("username", "").strip()
            password = form.get("password", "")
            if not username or len(password) < 8:
                self.send_html(400, page("Setup error", '<div class="card error">Username required and password must be at least 8 characters.</div>'))
                return
            salt, digest = hash_password(password)
            state = {"username": username, "password_salt": salt, "password_hash": digest, "sessions": {}}
            sid = make_session(state, username)
            self.redirect("/", f"aquacam_session={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL_SECONDS}")
            return
        if self.path == "/login":
            state = read_state()
            form = self.read_post()
            if form.get("username") == state.get("username") and verify_password(form.get("password", ""), state):
                sid = make_session(state, state["username"])
                self.redirect("/", f"aquacam_session={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL_SECONDS}")
            else:
                self.send_html(403, page("Login failed", '<div class="card error">Login failed.</div><p><a href="/login">Try again</a></p>'))
            return
        if self.path == "/email":
            if not self.require_auth():
                return
            form = self.read_post()
            email_values = {key: form.get(key, "").strip() for key in EMAIL_FIELD_TYPES}
            errors = validate_email_config(email_values)
            if errors:
                self.send_html(400, page("Email settings error", '<div class="card error"><pre>' + esc("\n".join(errors)) + '</pre></div><p><a href="/">Back</a></p>'))
                return
            save_email_config(email_values)
            if form.get("action") == "test":
                ok, output = run_email_test()
                klass = "ok" if ok else "error"
                self.send_html(200, page("AquaCam email test", f'<div class="card {klass}"><h2>Email test {"sent" if ok else "failed"}</h2><pre>{esc(output)}</pre></div><p><a class="button" href="/">Back to dashboard</a></p>'))
                return
            self.redirect("/?email_saved=1")
            return
        if self.path == "/save":
            if not self.require_auth():
                return
            form = self.read_post()
            new_values = {key: form.get(key, "").strip() for key in FIELD_TYPES}
            errors = []
            for key, value in new_values.items():
                err = validate_value(key, value)
                if err:
                    errors.append(f"{FIELD_LABELS[key]}: {err}")
            if errors:
                self.send_html(400, page("Validation error", '<div class="card error"><b>Could not save:</b><ul>' + ''.join(f'<li>{esc(e)}</li>' for e in errors) + '</ul></div><p><a href="/">Back</a></p>'))
                return
            save_config(new_values)
            if form.get("action") == "save_restart":
                ok, output = restart_service()
                self.redirect("/?" + urlencode({"restarted" if ok else "restart_failed": "1"}))
            else:
                self.redirect("/?saved=1")
            return
        self.send_error(404)


def main() -> None:
    if not CONFIG_FILE.exists():
        raise SystemExit(f"Config file not found: {CONFIG_FILE}")
    print(f"AquaCam web manager on http://{HOST}:{PORT}/ editing {CONFIG_FILE}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
