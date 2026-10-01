#!/bin/bash
# Free port 8004 first so a restart can never hit "address already in use".
pkill -f 'uvicorn app.main:app' 2>/dev/null || true
sleep 2

cd /var/www/hms-backend
exec /var/www/hms-backend/.venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8004 \
  --workers 1
