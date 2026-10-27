#!/usr/bin/env bash
set -euo pipefail

check_url() {
  local status

  if ! status=$(curl \
    --silent \
    --show-error \
    --max-redirs 0 \
    --max-time 2 \
    --output /dev/null \
    --write-out '%{http_code}' \
    "$1"); then
    return 1
  fi

  [[ "$status" =~ ^2[0-9]{2}$ ]]
}

if check_url "http://127.0.0.1:8000/health" \
  && check_url "http://127.0.0.1:3000/login" \
  && python -c 'import os,pathlib,time; p=pathlib.Path(os.getenv("GENERATION_WORKER_HEARTBEAT", "/tmp/postforge-worker-heartbeat")); assert p.exists() and time.time()-float(p.read_text()) < 60'; then
  exit 0
fi

exit 1
