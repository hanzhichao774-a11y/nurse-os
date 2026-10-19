#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/root/exam_backend
PYTHON_BIN=/root/miniconda3/envs/livetalking/bin/python
PID_FILE="$APP_DIR/exam-backend.pid"
LOG_FILE="$APP_DIR/exam-backend.log"

if curl --silent --fail http://127.0.0.1:8002/health >/dev/null; then
  exit 0
fi

if [ -f "$PID_FILE" ]; then
  old_pid=$(cat "$PID_FILE" 2>/dev/null || true)
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
    kill "$old_pid" || true
  fi
fi

cd "$APP_DIR"
EXAM_DB_PATH="$APP_DIR/data/exam.db" \
EXAM_SESSION_DAYS=7 \
EXAM_COOKIE_SECURE=1 \
nohup "$PYTHON_BIN" -m uvicorn app:app --host 127.0.0.1 --port 8002 > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

for ((attempt=0; attempt<40; attempt++)); do
  if curl --silent --fail http://127.0.0.1:8002/health >/dev/null; then
    exit 0
  fi
  sleep 0.25
done

echo "教资用户服务启动失败，请查看 $LOG_FILE" >&2
exit 1
