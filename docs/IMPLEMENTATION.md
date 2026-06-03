# Implementation notes

## Components

### `start_stream.sh`

This is the long-running supervisor called by systemd.

Responsibilities:

- Load `aquacam-stream.conf`
- Wait until the stream window is active
- Run the YouTube API prepare step when enabled
- Read the generated stream key
- Launch ffmpeg
- Monitor ffmpeg progress
- Restart ffmpeg if local progress stalls
- Stop ffmpeg cleanly at the end of the stream window
- Optionally shut the Pi down after streaming

### `ytapi_prepare_broadcast.py`

This script talks to YouTube Data API v3.

Responsibilities:

- Load config and environment overrides
- Authenticate via OAuth
- Refresh `token.json` when needed
- Reuse saved `stream.id` if still valid
- Create a reusable `liveStream` if missing
- Reuse saved `broadcast.id` if it is still usable
- Create a fresh `liveBroadcast` if the saved one is complete or missing
- Bind the broadcast to the stream
- Apply the AquaCam metadata template via `videos.update`
- Upload the thumbnail once per broadcast
- Write the RTMP stream key to `stream.key`

## YouTube API resources used

- `liveStreams.list`
- `liveStreams.insert`
- `liveBroadcasts.list`
- `liveBroadcasts.insert`
- `liveBroadcasts.bind`
- `videos.list`
- `videos.update`
- `thumbnails.set`

OAuth scope:

```text
https://www.googleapis.com/auth/youtube
```

## Runtime state files

These files are created on the Pi and should not be committed:

```text
client_secret.json
token.json
stream.key
stream.id
broadcast.id
thumbnail_set.id
stream.log
```

## Broadcast lifecycle logic

- If `stream.id` exists and YouTube returns it, reuse it.
- Otherwise create a new reusable YouTube liveStream and save the ID.
- If `broadcast.id` exists and its lifecycle status is not `complete`, reuse it.
- If the saved broadcast is complete/missing, create a new broadcast and save the ID.
- Always ensure the chosen broadcast is bound to the chosen stream.
- Always re-apply metadata to keep YouTube Studio settings aligned with the config.

## Metadata template

Configured in `aquacam-stream.conf`:

```bash
YT_BROADCAST_TITLE="AquaCam Live - {date}"
YT_BROADCAST_DESCRIPTION="Live aquarium camera."
YT_BROADCAST_TAGS="aquarium, aquatic, livestream, fish, water, pets, animals, relaxation"
YT_DEFAULT_LANGUAGE="en"
YT_DEFAULT_AUDIO_LANGUAGE="en"
YT_PRIVACY_STATUS="public"
YT_SELF_DECLARED_MADE_FOR_KIDS="false"
YT_ENABLE_AUTO_START="true"
YT_ENABLE_AUTO_STOP="true"
YT_ENABLE_DVR="true"
YT_ENABLE_EMBED="true"
YT_LATENCY_PREFERENCE="low"
```

`{date}` is replaced with the scheduled local date.

## What the API does not do

The YouTube API does not capture or encode video. ffmpeg still handles camera capture and RTMP upload.

Some YouTube Studio toggles are not exposed as simple writable API fields, for example some automatic chapter/key-moment/place/concept settings. Those should be controlled through YouTube Studio/channel defaults if needed.

## Why warm restart is disabled

The non-API version used a warm ffmpeg restart as a workaround for YouTube getting stuck on "Preparing stream". In API mode, `WARM_RESTART_ENABLED` should stay `false` because the Pi prepares the YouTube broadcast before pushing video.
