#!/usr/bin/env python3
"""AquaCam YouTube token monitor with optional SMTP notification.

Runs the YouTube API auth check. If it fails, sends an email if
`aquacam-email.conf` exists and is configured.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shlex
import smtplib
import socket
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_DIR / "aquacam-stream.conf"
DEFAULT_EMAIL_CONFIG = PROJECT_DIR / "aquacam-email.conf"
DEFAULT_LOG = PROJECT_DIR / "webmgr" / "youtube-token-monitor.log"


def notify(event: str, email_config: Path, message: str) -> None:
    script = PROJECT_DIR / "scripts" / "aquacam_notify.py"
    python_bin = str(PROJECT_DIR / ".venv" / "bin" / "python")
    if not Path(python_bin).exists():
        python_bin = sys.executable
    subprocess.run(
        [python_bin, str(script), event, "--email-config", str(email_config), "--message", message],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=45,
    )


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


def log_line(log_path: Path, text: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    with log_path.open("a") as f:
        f.write(f"[{stamp}] {text}\n")


def run_auth_check(config_file: Path, timeout: int) -> tuple[bool, str, int]:
    cfg = parse_shell_config(config_file)
    python_bin = cfg.get("PYTHON_BIN") or str(PROJECT_DIR / ".venv" / "bin" / "python")
    script = cfg.get("YT_API_PREPARE_SCRIPT") or str(PROJECT_DIR / "ytapi_prepare_broadcast.py")
    cmd = [python_bin, script, "--config", str(config_file), "--auth-check"]
    try:
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return proc.returncode == 0, proc.stdout.strip(), proc.returncode
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return False, f"Timed out after {timeout}s.\n{output}".strip(), 124
    except Exception as exc:
        return False, f"Could not run auth check: {exc}", 125


def send_email(email_cfg_path: Path, subject: str, body: str) -> tuple[bool, str]:
    cfg = parse_shell_config(email_cfg_path)
    if not cfg or cfg.get("SMTP_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        return False, f"SMTP not enabled/configured: {email_cfg_path}"

    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        return False, f"Missing email config keys: {', '.join(missing)}"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.get("MAIL_FROM") or cfg["SMTP_USER"]
    msg["To"] = cfg["MAIL_TO"]
    msg.set_content(body)

    host = cfg["SMTP_HOST"]
    port = int(cfg["SMTP_PORT"])
    use_ssl = cfg.get("SMTP_SSL", "false").lower() in {"1", "true", "yes", "on"}
    use_starttls = cfg.get("SMTP_STARTTLS", "true").lower() in {"1", "true", "yes", "on"}

    try:
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
    except Exception as exc:
        return False, f"email failed: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--email-config", default=str(DEFAULT_EMAIL_CONFIG))
    parser.add_argument("--log", default=str(DEFAULT_LOG))
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--notify-success", action="store_true")
    args = parser.parse_args()

    config_file = Path(args.config)
    email_config = Path(args.email_config)
    log_path = Path(args.log)
    host = socket.gethostname()

    try:
        notify("pi_alive", email_config, f"AquaCam Pi boot token monitor is running on {host}.")
    except Exception:
        pass

    ok, output, code = run_auth_check(config_file, args.timeout)
    if ok:
        msg = f"OK: YouTube token auth check passed. {output}"
        log_line(log_path, msg)
        try:
            notify("token_status", email_config, f"YouTube token check passed.\n\nOutput:\n{output}")
        except Exception:
            pass
        if args.notify_success:
            send_ok, send_msg = send_email(
                email_config,
                f"AquaCam OK: YouTube token check passed on {host}",
                f"AquaCam YouTube token check passed.\n\nHost: {host}\nConfig: {config_file}\n\nOutput:\n{output}\n",
            )
            log_line(log_path, f"success notification: {send_msg}")
            return 0 if send_ok else 2
        return 0

    body = (
        "AquaCam YouTube token check FAILED.\n\n"
        f"Host: {host}\n"
        f"Config: {config_file}\n"
        f"Exit code: {code}\n\n"
        "What to do:\n"
        "Open the AquaCam web UI and click Re-authorise YouTube.\n\n"
        "Output:\n"
        f"{output}\n"
    )
    log_line(log_path, "FAILED: " + output.replace("\n", " | "))
    try:
        notify("token_expired", email_config, body)
        send_msg = "notification attempted via aquacam_notify.py"
    except Exception as exc:
        send_msg = f"notification failed: {exc}"
    log_line(log_path, f"failure notification: {send_msg}")
    print(body)
    print(send_msg)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
