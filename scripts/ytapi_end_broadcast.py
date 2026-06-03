#!/usr/bin/env python3
"""Cleanly end the saved AquaCam YouTube Live broadcast, if it is currently live/testing."""
from __future__ import annotations

import argparse
import pathlib
import sys

from ytapi_prepare_broadcast import (
    bool_cfg,
    call,
    get_broadcast,
    get_credentials,
    path_from_cfg,
    parse_shell_config,
    read_id,
    youtube_service,
)

ENDABLE_STATES = {"live", "testing"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="aquacam-stream.conf")
    args = parser.parse_args()

    config_file = pathlib.Path(args.config).expanduser().resolve()
    cfg = parse_shell_config(config_file)
    if not bool_cfg(cfg, "YT_API_ENABLED"):
        print("YT_API_ENABLED is false; nothing to end")
        return 0

    broadcast_id_file = path_from_cfg(config_file, cfg, "YT_BROADCAST_ID_FILE")
    bid = read_id(broadcast_id_file)
    if not bid:
        print(f"No broadcast id found at {broadcast_id_file}; nothing to end")
        return 0

    creds = get_credentials(
        path_from_cfg(config_file, cfg, "YT_CLIENT_SECRETS"),
        path_from_cfg(config_file, cfg, "YT_TOKEN_FILE"),
    )
    youtube = youtube_service(creds)
    broadcast = get_broadcast(youtube, bid)
    if not broadcast:
        print(f"Broadcast {bid} not found; nothing to end")
        return 0

    state = broadcast.get("status", {}).get("lifeCycleStatus", "unknown")
    print(f"Broadcast {bid} lifecycle state: {state}")
    if state in ENDABLE_STATES:
        call(youtube.liveBroadcasts().transition(broadcastStatus="complete", id=bid, part="status"))
        print(f"Transitioned broadcast {bid} to complete")
    else:
        print(f"No API end transition needed for state={state}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
