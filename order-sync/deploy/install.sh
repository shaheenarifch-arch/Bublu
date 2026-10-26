#!/usr/bin/env bash
# Install BUBLU order sync on the Oracle VPS (Ubuntu). Run from the order-sync folder: sudo bash deploy/install.sh
set -euo pipefail
DEST=/opt/bublu
mkdir -p "$DEST"
cp -r bublu sku_map.json requirements.txt "$DEST"/
[ -f "$DEST/.env" ] || cp .env.example "$DEST/.env"
chmod 600 "$DEST/.env"
python3 -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install -q -r requirements.txt
chown -R ubuntu:ubuntu "$DEST"
cp deploy/bublu.service deploy/bublu.timer /etc/systemd/system/
systemctl daemon-reload
echo "Installed. Next: edit $DEST/.env, run 'cd $DEST && .venv/bin/python -m bublu check-cj', then 'systemctl enable --now bublu.timer'."
