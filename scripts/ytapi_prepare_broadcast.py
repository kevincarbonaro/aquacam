#!/usr/bin/env python3
"""
Prepare a YouTube Live broadcast/stream for AquaCam before ffmpeg starts.

What it does:
- Authenticates using OAuth on the Raspberry Pi.
- Reuses a saved YouTube liveStream when possible.
- Reuses a saved broadcast if it is still upcoming/live/testing.
- Creates a new scheduled broadcast if the saved one is completed/missing.
- Binds the liveStream to the broadcast.
- Writes YouTube's RTMP stream key to STREAM_KEY_FILE so the existing ffmpeg command can stream.

First-time auth on the Pi:
  python3 -m pip install -r requirements.txt
  YT_CLIENT_SECRETS=/home/kevin/aquacam-stream/client_secret.json ./ytapi_prepare_broadcast.py --config ./aquacam-stream.conf
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
from typing import Any

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
except ImportError as exc:
    print(f"Missing Python dependency: {exc}", file=sys.stderr)
    print("Install with: python3 -m pip install -r requirements.txt", file=sys.stderr)
    sys.exit(2)

SCOPES = ["https://www.googleapis.com/auth/youtube"]
DEFAULTS = {
    "YT_API_ENABLED": "false",
    "YT_PRIVACY_STATUS": "public",
    "YT_BROADCAST_TITLE": "AquaCam Live - {date}",
    "YT_BROADCAST_DESCRIPTION": "Live aquarium camera.",
    "YT_BROADCAST_TAGS": "aquarium, aquatic, livestream, fish, water, pets, animals, relaxation",
    "YT_DEFAULT_LANGUAGE": "en",
    "YT_DEFAULT_AUDIO_LANGUAGE": "en",
    "YT_STREAM_TITLE": "AquaCam reusable stream",
    "YT_CATEGORY_ID": "15",  # Pets & Animals
    "YT_ENABLE_AUTO_START": "true",
    "YT_ENABLE_AUTO_STOP": "true",
    "YT_ENABLE_DVR": "true",  # Keeps live chat replay/DVR-style playback available when YouTube allows it.
    "YT_ENABLE_EMBED": "true",
    "YT_SELF_DECLARED_MADE_FOR_KIDS": "false",
    "YT_LATENCY_PREFERENCE": "low",
    "YT_TOKEN_FILE": "token.json",
    "YT_CLIENT_SECRETS": "client_secret.json",
    "YT_BROADCAST_ID_FILE": "broadcast.id",
    "YT_STREAM_ID_FILE": "stream.id",
    "YT_THUMBNAIL_FILE": "",
    "YT_THUMBNAIL_SET_ID_FILE": "thumbnail_set.id",
    "YT_TIMEZONE": "Europe/Malta",
}


def parse_shell_config(path: pathlib.Path) -> dict[str, str]:
    cfg = DEFAULTS.copy()
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().split(" #", 1)[0].strip()
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            cfg[key] = value
    # Environment overrides config.
    for key in list(DEFAULTS) + [
        "STREAM_URL", "STREAM_KEY_FILE", "START_TIME", "STOP_TIME", "LOG_FILE",
    ]:
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    return cfg


def bool_cfg(cfg: dict[str, str], key: str) -> bool:
    return cfg.get(key, "").lower() in {"1", "true", "yes", "on"}


def path_from_cfg(config_file: pathlib.Path, cfg: dict[str, str], key: str) -> pathlib.Path:
    raw = cfg[key]
    p = pathlib.Path(raw).expanduser()
    if not p.is_absolute():
        p = config_file.parent / p
    return p


def local_schedule_iso(cfg: dict[str, str]) -> str:
    # Python 3.9+ on Raspberry Pi OS has zoneinfo. Fall back to local time if absent.
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(cfg.get("YT_TIMEZONE", "Europe/Malta"))
    except Exception:
        tz = dt.datetime.now().astimezone().tzinfo

    now = dt.datetime.now(tz)
    start = cfg.get("START_TIME") or "08:30"
    hour, minute = [int(x) for x in start.split(":", 1)]
    today = now.date()
    scheduled = dt.datetime(today.year, today.month, today.day, hour, minute, tzinfo=tz)

    # If the Pi boots after START_TIME, today's scheduled time is already in the past.
    # YouTube rejects new broadcasts with invalidScheduledStartTime in that case, so
    # create the replacement broadcast a few minutes in the future and let auto-start
    # take it live as soon as ffmpeg begins pushing to the bound stream key.
    minimum_start = now + dt.timedelta(minutes=5)
    if scheduled <= minimum_start:
        scheduled = minimum_start

    return scheduled.isoformat()


def safe_title(template: str, scheduled_iso: str) -> str:
    date_text = scheduled_iso[:10]
    title = template.format(date=date_text)
    return title[:95]


def csv_cfg(cfg: dict[str, str], key: str) -> list[str]:
    return [item.strip() for item in cfg.get(key, "").split(",") if item.strip()]


def get_credentials(client_secrets: pathlib.Path, token_file: pathlib.Path) -> Credentials:
    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not client_secrets.exists():
            raise FileNotFoundError(f"Missing OAuth client secret file: {client_secrets}")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
        # Google has removed the old copy/paste console OAuth flow.
        # This starts a temporary localhost callback server and prints the auth URL.
        # On a headless Pi, SSH with: ssh -L 8080:localhost:8080 pi@<pi-ip>
        creds = flow.run_local_server(host="localhost", port=8080, open_browser=False, prompt="consent")
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json())
    return creds


def youtube_service(creds: Credentials):
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def read_id(path: pathlib.Path) -> str | None:
    if path.exists():
        value = path.read_text().strip()
        if re.fullmatch(r"[-_A-Za-z0-9]+", value):
            return value
    return None


def write_id(path: pathlib.Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n")


def call(req):
    try:
        return req.execute()
    except HttpError as exc:
        body = exc.content.decode("utf-8", errors="replace") if getattr(exc, "content", None) else str(exc)
        raise RuntimeError(f"YouTube API error: {body}") from exc


def get_broadcast(youtube, broadcast_id: str) -> dict[str, Any] | None:
    resp = call(youtube.liveBroadcasts().list(part="id,snippet,status,contentDetails", id=broadcast_id))
    items = resp.get("items", [])
    return items[0] if items else None


def create_broadcast(youtube, cfg: dict[str, str], title: str, scheduled_iso: str) -> dict[str, Any]:
    body = {
        "snippet": {
            "title": title,
            "description": cfg.get("YT_BROADCAST_DESCRIPTION", ""),
            "scheduledStartTime": scheduled_iso,
            "categoryId": cfg.get("YT_CATEGORY_ID", "15"),
        },
        "status": {
            "privacyStatus": cfg.get("YT_PRIVACY_STATUS", "public"),
            "selfDeclaredMadeForKids": bool_cfg(cfg, "YT_SELF_DECLARED_MADE_FOR_KIDS"),
        },
        "contentDetails": {
            "enableAutoStart": bool_cfg(cfg, "YT_ENABLE_AUTO_START"),
            "enableAutoStop": bool_cfg(cfg, "YT_ENABLE_AUTO_STOP"),
            "enableDvr": bool_cfg(cfg, "YT_ENABLE_DVR"),
            "enableEmbed": bool_cfg(cfg, "YT_ENABLE_EMBED"),
            "latencyPreference": cfg.get("YT_LATENCY_PREFERENCE", "low"),
        },
    }
    return call(youtube.liveBroadcasts().insert(part="snippet,status,contentDetails", body=body))


def apply_video_template(youtube, cfg: dict[str, str], video_id: str, title: str) -> None:
    """Apply video-level metadata that liveBroadcasts.insert cannot fully set."""
    resp = call(youtube.videos().list(part="snippet,status", id=video_id))
    items = resp.get("items", [])
    if not items:
        print(f"WARNING: video metadata not found for broadcast/video {video_id}")
        return

    current = items[0]
    snippet = current.get("snippet", {}).copy()
    status = current.get("status", {}).copy()
    snippet.update(
        {
            "title": title,
            "description": cfg.get("YT_BROADCAST_DESCRIPTION", ""),
            "categoryId": cfg.get("YT_CATEGORY_ID", "15"),
            "tags": csv_cfg(cfg, "YT_BROADCAST_TAGS"),
            "defaultLanguage": cfg.get("YT_DEFAULT_LANGUAGE", "en"),
            "defaultAudioLanguage": cfg.get("YT_DEFAULT_AUDIO_LANGUAGE", "en"),
        }
    )
    status.update(
        {
            "privacyStatus": cfg.get("YT_PRIVACY_STATUS", "public"),
            "selfDeclaredMadeForKids": bool_cfg(cfg, "YT_SELF_DECLARED_MADE_FOR_KIDS"),
            # Explicitly leave age restriction off. YouTube age restriction is not set through a simple
            # boolean in videos.update; omitting contentRating keeps the normal/non-age-restricted state.
        }
    )

    call(
        youtube.videos().update(
            part="snippet,status",
            body={"id": video_id, "snippet": snippet, "status": status},
        )
    )
    print(f"Applied AquaCam video template to {video_id}")


def maybe_set_thumbnail(
    youtube,
    config_file: pathlib.Path,
    cfg: dict[str, str],
    broadcast_id: str,
) -> None:
    """Upload the configured thumbnail once for each YouTube broadcast."""
    raw_thumbnail = cfg.get("YT_THUMBNAIL_FILE", "").strip()
    if not raw_thumbnail:
        return

    thumbnail = pathlib.Path(raw_thumbnail).expanduser()
    if not thumbnail.is_absolute():
        thumbnail = config_file.parent / thumbnail
    if not thumbnail.exists():
        print(f"WARNING: thumbnail file not found; skipping: {thumbnail}")
        return

    marker_file = path_from_cfg(config_file, cfg, "YT_THUMBNAIL_SET_ID_FILE")
    if read_id(marker_file) == broadcast_id:
        print(f"Thumbnail already set for broadcast {broadcast_id}")
        return

    try:
        call(
            youtube.thumbnails().set(
                videoId=broadcast_id,
                media_body=MediaFileUpload(str(thumbnail), resumable=False),
            )
        )
    except Exception as exc:
        print(f"WARNING: failed to set YouTube thumbnail; continuing: {exc}")
        return

    write_id(marker_file, broadcast_id)
    print(f"Set thumbnail for broadcast {broadcast_id}: {thumbnail}")


def get_stream(youtube, stream_id: str) -> dict[str, Any] | None:
    resp = call(youtube.liveStreams().list(part="id,snippet,cdn,status", id=stream_id))
    items = resp.get("items", [])
    return items[0] if items else None


def create_stream(youtube, cfg: dict[str, str]) -> dict[str, Any]:
    body = {
        "snippet": {"title": cfg.get("YT_STREAM_TITLE", "AquaCam reusable stream")},
        "cdn": {
            "frameRate": "30fps",
            "ingestionType": "rtmp",
            "resolution": "variable",
        },
    }
    return call(youtube.liveStreams().insert(part="snippet,cdn", body=body))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="aquacam-stream.conf")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config_file = pathlib.Path(args.config).expanduser().resolve()
    cfg = parse_shell_config(config_file)
    if not bool_cfg(cfg, "YT_API_ENABLED"):
        print("YT_API_ENABLED is false; nothing to do")
        return 0

    token_file = path_from_cfg(config_file, cfg, "YT_TOKEN_FILE")
    client_secrets = path_from_cfg(config_file, cfg, "YT_CLIENT_SECRETS")
    broadcast_id_file = path_from_cfg(config_file, cfg, "YT_BROADCAST_ID_FILE")
    stream_id_file = path_from_cfg(config_file, cfg, "YT_STREAM_ID_FILE")
    stream_key_file = pathlib.Path(cfg["STREAM_KEY_FILE"]).expanduser()

    scheduled_iso = local_schedule_iso(cfg)
    title = safe_title(cfg.get("YT_BROADCAST_TITLE", DEFAULTS["YT_BROADCAST_TITLE"]), scheduled_iso)

    creds = get_credentials(client_secrets, token_file)
    youtube = youtube_service(creds)

    stream = None
    sid = read_id(stream_id_file)
    if sid:
        stream = get_stream(youtube, sid)
    if not stream:
        stream = create_stream(youtube, cfg)
        write_id(stream_id_file, stream["id"])
        print(f"Created YouTube liveStream: {stream['id']}")
    else:
        print(f"Reusing YouTube liveStream: {stream['id']}")

    broadcast = None
    bid = read_id(broadcast_id_file)
    if bid:
        broadcast = get_broadcast(youtube, bid)
        if broadcast and broadcast.get("status", {}).get("lifeCycleStatus") == "complete":
            print(f"Saved broadcast {bid} is complete; creating a fresh one")
            broadcast = None
    if not broadcast:
        broadcast = create_broadcast(youtube, cfg, title, scheduled_iso)
        write_id(broadcast_id_file, broadcast["id"])
        print(f"Created YouTube broadcast: {broadcast['id']} ({title})")
    else:
        print(f"Reusing YouTube broadcast: {broadcast['id']} status={broadcast.get('status', {}).get('lifeCycleStatus')}")

    bound_stream_id = broadcast.get("contentDetails", {}).get("boundStreamId")
    if bound_stream_id != stream["id"]:
        call(youtube.liveBroadcasts().bind(part="id,contentDetails", id=broadcast["id"], streamId=stream["id"]))
        print(f"Bound broadcast {broadcast['id']} to stream {stream['id']}")
    else:
        print("Broadcast already bound to the saved stream")

    apply_video_template(youtube, cfg, broadcast["id"], title)
    maybe_set_thumbnail(youtube, config_file, cfg, broadcast["id"])

    ingestion = stream.get("cdn", {}).get("ingestionInfo", {})
    stream_name = ingestion.get("streamName")
    address = ingestion.get("ingestionAddress") or ingestion.get("backupIngestionAddress")
    if not stream_name:
        raise RuntimeError("YouTube API did not return a streamName/stream key")
    if address:
        print(f"YouTube ingest address: {address}")

    if not args.dry_run:
        stream_key_file.parent.mkdir(parents=True, exist_ok=True)
        old_umask = os.umask(0o177)
        try:
            stream_key_file.write_text(stream_name + "\n")
        finally:
            os.umask(old_umask)
        print(f"Wrote stream key to {stream_key_file}")

    print("YouTube API prepare complete")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
