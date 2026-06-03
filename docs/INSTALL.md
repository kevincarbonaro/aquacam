# Install checklist

## On the Pi

```bash
sudo apt update
sudo apt install -y ffmpeg v4l-utils python3 python3-pip python3-venv rsync
sudo timedatectl set-timezone Europe/Malta
mkdir -p /home/<PI_USER>/aquacam-stream-ytapi
```

## Copy project files

From your computer:

```bash
rsync -a --exclude='.git' ./ <PI_USER>@aquacam.local:/home/<PI_USER>/aquacam-stream-ytapi/
```

On the Pi:

```bash
cd /home/<PI_USER>/aquacam-stream-ytapi
python3 -m pip install -r requirements.txt
cp configs/aquacam-stream.conf.example aquacam-stream.conf
cp scripts/start_stream.sh ./start_stream.sh
cp scripts/ytapi_prepare_broadcast.py ./ytapi_prepare_broadcast.py
cp assets/the-calm-aquarium-thumbnail.png ./the-calm-aquarium-thumbnail.png
chmod +x start_stream.sh ytapi_prepare_broadcast.py
```

## Add OAuth client secret

Download OAuth Desktop App credentials from Google Cloud and save as:

```text
/home/<PI_USER>/aquacam-stream-ytapi/client_secret.json
```

Then:

```bash
chmod 600 /home/<PI_USER>/aquacam-stream-ytapi/client_secret.json
```

## Edit config

```bash
nano /home/<PI_USER>/aquacam-stream-ytapi/aquacam-stream.conf
```

Set:

```bash
YT_API_ENABLED="true"
YT_CLIENT_SECRETS="/home/<PI_USER>/aquacam-stream-ytapi/client_secret.json"
YT_TOKEN_FILE="/home/<PI_USER>/aquacam-stream-ytapi/token.json"
YT_THUMBNAIL_FILE="/home/<PI_USER>/aquacam-stream-ytapi/the-calm-aquarium-thumbnail.png"
```

## Authorize YouTube once

From your computer:

```bash
ssh -L 8080:localhost:8080 <PI_USER>@aquacam.local
```

On the Pi:

```bash
cd /home/<PI_USER>/aquacam-stream-ytapi
python3 ytapi_prepare_broadcast.py --config ./aquacam-stream.conf
chmod 600 token.json stream.key
```

## Install service

```bash
cd /home/<PI_USER>/aquacam-stream-ytapi
sudo cp systemd/aquacam-ytapi.service /etc/systemd/system/aquacam-ytapi.service
sudo sed -i "s|<PI_USER>|$(whoami)|g" /etc/systemd/system/aquacam-ytapi.service
sudo systemctl daemon-reload
sudo systemctl enable aquacam-ytapi.service
sudo systemctl restart aquacam-ytapi.service
```

## Verify

```bash
systemctl is-active aquacam-ytapi.service
journalctl -u aquacam-ytapi.service -n 100 --no-pager
tail -n 100 /home/<PI_USER>/aquacam-stream-ytapi/stream.log
```
