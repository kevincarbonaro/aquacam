#!/usr/bin/env python3
"""Send AquaCam notifications according to aquacam-email.conf."""
from __future__ import annotations

import argparse
import datetime as dt
import shlex
import smtplib
import socket
from email.message import EmailMessage
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_EMAIL_CONFIG = PROJECT_DIR / "aquacam-email.conf"
DEFAULT_LOG = PROJECT_DIR / "webmgr" / "aquacam-notifications.log"

EVENT_FLAGS = {
    "token_status": "NOTIFY_TOKEN_STATUS",
    "token_expired": "NOTIFY_TOKEN_EXPIRED",
    "stream_started": "NOTIFY_STREAM_STARTED",
    "stream_stopped": "NOTIFY_STREAM_STOPPED",
    "pi_alive": "NOTIFY_PI_ALIVE",
    "pi_shutting_down": "NOTIFY_PI_SHUTTING_DOWN",
}

EVENT_TITLES = {
    "token_status": "YouTube token status",
    "token_expired": "YouTube token problem",
    "stream_started": "Live stream started",
    "stream_stopped": "Live stream stopped",
    "pi_alive": "Pi is alive",
    "pi_shutting_down": "Pi is shutting down",
}


def parse_shell_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().split(" #", 1)[0].strip()
        try:
            values[key] = shlex.split(value)[0] if value else ""
        except Exception:
            values[key] = value.strip('"').strip("'")
    return values


def enabled(value: str) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def log_line(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    with path.open("a") as f:
        f.write(f"[{stamp}] {text}\n")


def send_email(cfg: dict[str, str], subject: str, body: str) -> tuple[bool, str]:
    if not enabled(cfg.get("SMTP_ENABLED", "false")):
        return False, "SMTP disabled"
    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        return False, "Missing email config keys: " + ", ".join(missing)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.get("MAIL_FROM") or cfg["SMTP_USER"]
    msg["To"] = cfg["MAIL_TO"]
    msg.set_content(body)

    host = cfg["SMTP_HOST"]
    port = int(cfg["SMTP_PORT"])
    use_ssl = enabled(cfg.get("SMTP_SSL", "false"))
    use_starttls = enabled(cfg.get("SMTP_STARTTLS", "true"))

    if use_ssl:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
    with server:
        server.ehlo()
        if use_starttls and not use_ssl:
            server.starttls()
            server.ehlo()
        server.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
        server.send_message(msg)
    return True, "email sent"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("event", choices=sorted(EVENT_FLAGS))
    parser.add_argument("--message", default="")
    parser.add_argument("--email-config", default=str(DEFAULT_EMAIL_CONFIG))
    parser.add_argument("--log", default=str(DEFAULT_LOG))
    parser.add_argument("--force", action="store_true", help="Send even if the event checkbox is disabled")
    args = parser.parse_args()

    cfg = parse_shell_config(Path(args.email_config))
    cfg.setdefault("NOTIFY_TOKEN_STATUS", "false")
    cfg.setdefault("NOTIFY_TOKEN_EXPIRED", "true")
    cfg.setdefault("NOTIFY_STREAM_STARTED", "false")
    cfg.setdefault("NOTIFY_STREAM_STOPPED", "false")
    cfg.setdefault("NOTIFY_PI_ALIVE", "false")
    cfg.setdefault("NOTIFY_PI_SHUTTING_DOWN", "true")
    flag = EVENT_FLAGS[args.event]
    log_path = Path(args.log)

    if not args.force and not enabled(cfg.get(flag, "false")):
        log_line(log_path, f"skipped {args.event}: {flag}=false")
        return 0

    host = socket.gethostname()
    title = EVENT_TITLES[args.event]
    subject = f"AquaCam: {title} on {host}"
    body = f"AquaCam notification: {title}\n\nHost: {host}\nTime: {dt.datetime.now().astimezone().isoformat(timespec='seconds')}\n\n{args.message}\n"
    try:
        ok, msg = send_email(cfg, subject, body)
    except Exception as exc:
        ok, msg = False, f"email failed: {exc}"
    log_line(log_path, f"{args.event}: {msg}")
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
