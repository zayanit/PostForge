#!/usr/bin/env bash
set -euo pipefail

backend_pid=""
frontend_pid=""
shutting_down=false
shutdown_signal=TERM

start_backend() {
  (
    cd /app/backend
    exec uvicorn app.main:app --host 127.0.0.1 --port 8000
  ) &
  backend_pid=$!
  printf 'Started backend (pid %s)\n' "$backend_pid"

  if [[ "$shutting_down" == true ]]; then
    kill -s "$shutdown_signal" "$backend_pid" 2>/dev/null || true
  fi
}

start_frontend() {
  (
    cd /app/frontend
    exec next start -p 3000
  ) &
  frontend_pid=$!
  printf 'Started frontend (pid %s)\n' "$frontend_pid"

  if [[ "$shutting_down" == true ]]; then
    kill -s "$shutdown_signal" "$frontend_pid" 2>/dev/null || true
  fi
}

request_shutdown() {
  local signal=$1

  if [[ "$shutting_down" == true ]]; then
    return
  fi

  shutting_down=true
  shutdown_signal=$signal
  printf 'Received %s; stopping child processes\n' "$signal"

  if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill -s "$signal" "$backend_pid" 2>/dev/null || true
  fi
  if [[ -n "$frontend_pid" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
    kill -s "$signal" "$frontend_pid" 2>/dev/null || true
  fi
}

wait_for_child() {
  local pid=$1

  if [[ -n "$pid" ]]; then
    wait "$pid" 2>/dev/null || true
  fi
}

trap 'request_shutdown TERM' TERM
trap 'request_shutdown INT' INT

start_backend
if [[ "$shutting_down" == false ]]; then
  start_frontend
fi

while [[ "$shutting_down" == false ]]; do
  exit_status=0
  wait -n "$backend_pid" "$frontend_pid" || exit_status=$?

  if [[ "$shutting_down" == true ]]; then
    break
  fi

  if ! kill -0 "$backend_pid" 2>/dev/null; then
    wait_for_child "$backend_pid"
    printf 'Backend exited with status %s; restarting\n' "$exit_status"
    start_backend
  fi

  if ! kill -0 "$frontend_pid" 2>/dev/null; then
    wait_for_child "$frontend_pid"
    printf 'Frontend exited with status %s; restarting\n' "$exit_status"
    start_frontend
  fi
done

wait_for_child "$backend_pid"
wait_for_child "$frontend_pid"
