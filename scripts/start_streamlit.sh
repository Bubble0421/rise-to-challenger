#!/usr/bin/env bash

set -e

cd "$(dirname "$0")/.."

PORT="${PORT:-8510}"
LOG_FILE="${LOG_FILE:-streamlit.log}"
PID_FILE="${PID_FILE:-streamlit.pid}"

if [ -f "$PID_FILE" ] && ps -p "$(cat "$PID_FILE")" >/dev/null 2>&1; then
  echo "Streamlit is already running on PID $(cat "$PID_FILE")."
  echo "If you want to restart it, stop that process first."
  exit 0
fi

nohup python -m streamlit run app.py --server.port "$PORT" --server.headless true > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

sleep 3

if ps -p "$(cat "$PID_FILE")" >/dev/null 2>&1; then
  echo "Streamlit started successfully."
  echo "Port: $PORT"
  echo "PID: $(cat "$PID_FILE")"
  echo "Log: $LOG_FILE"
else
  echo "Streamlit failed to start. Check $LOG_FILE"
  exit 1
fi
