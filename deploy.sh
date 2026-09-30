#!/bin/bash
# deploy.sh — sync local changes to server and restart services
SERVER="root@5.223.80.199"
REMOTE="/opt/pospal-report"
LOCAL="$(dirname "$0")"

echo "Uploading files..."
rsync -avz --exclude='cache/' --exclude='__pycache__/' --exclude='*.pyc' \
  --exclude='data/' \
  "$LOCAL/" "$SERVER:$REMOTE/"

echo "Restarting pospal service..."
ssh "$SERVER" "systemctl restart pospal"

echo "Done. Server is running."
