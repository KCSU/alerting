#!/bin/bash -e
APP_DIR="${APP_DIR:-/societies/kcsu/alerting}"

cd "$APP_DIR"

exec "$APP_DIR/.venv/bin/flask" --app app.run probe
