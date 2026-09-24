#!/bin/bash -e
APP_DIR="/societies/kcsu/alerting"
SOCKET="$APP_DIR/web.sock"

cd "$APP_DIR"

exec "$APP_DIR/.venv/bin/gunicorn" -w 2 -b "unix:$SOCKET" --log-file - app.run:app
