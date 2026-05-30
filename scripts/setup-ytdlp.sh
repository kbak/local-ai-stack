#!/usr/bin/env bash
# Run yt-dlp-service natively on this box as a systemd service (no Docker).
# Mirrors how it runs on Windows, but auto-starts on boot.
# Run as your normal user (it calls sudo for the privileged bits):
#   bash scripts/setup-ytdlp.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SVC_DIR="$REPO_ROOT/yt-dlp-service"
USER_NAME="$(id -un)"

echo "[1] system deps: ffmpeg, nodejs, python venv"
sudo apt-get update -qq
sudo apt-get install -y ffmpeg nodejs python3-venv >/dev/null

echo "[2] python venv + requirements"
python3 -m venv "$SVC_DIR/.venv"
"$SVC_DIR/.venv/bin/pip" install -q -U pip
"$SVC_DIR/.venv/bin/pip" install -q -r "$SVC_DIR/requirements.txt"

echo "[3] cookies check"
if [[ -f "$SVC_DIR/youtube_cookies.txt" ]]; then
  echo "    found youtube_cookies.txt"
else
  echo "    !! NO youtube_cookies.txt — copy it from Windows or YouTube auth will fail:"
  echo "       scp <win>:~/local-ai-stack/yt-dlp-service/youtube_cookies.txt $SVC_DIR/"
fi

echo "[4] systemd unit -> /etc/systemd/system/yt-dlp-service.service"
sudo tee /etc/systemd/system/yt-dlp-service.service >/dev/null <<EOF
[Unit]
Description=yt-dlp download service
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$SVC_DIR
Environment=PORT=8200
ExecStart=$SVC_DIR/.venv/bin/python server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo "[5] enable + start"
sudo systemctl daemon-reload
sudo systemctl enable --now yt-dlp-service
sleep 2
sudo systemctl --no-pager --full status yt-dlp-service | head -8
echo "--- health ---"
curl -s -o /dev/null -w "localhost:8200 -> %{http_code}\n" http://localhost:8200/health
