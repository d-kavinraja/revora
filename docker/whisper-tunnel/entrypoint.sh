#!/usr/bin/env bash
set -u

# A small supervisor for the private tunnel. Compose restarts this container
# after a crash or host reboot; this loop handles upstream loss while the
# container itself remains alive. It never prints the API key or the speech
# bearer token.

remote="${WHISPER_TUNNEL_REMOTE:-server-2}"
local_port="${WHISPER_TUNNEL_LOCAL_PORT:-18010}"
remote_port="${WHISPER_TUNNEL_REMOTE_PORT:-8010}"
child=""
stopping=0

log() {
  printf '[whisper-tunnel] %s\n' "$*" >&2
}

stop_child() {
  if [ -n "$child" ]; then
    # The forward is started with setsid, so its PID is also the process-group
    # ID. Kill the whole group even when the leader already exited; otherwise
    # an orphaned ssh process keeps the local port bound and masks the loss.
    if kill -0 -- "-$child" 2>/dev/null; then
      kill -TERM -- "-$child" 2>/dev/null || true
    elif kill -0 "$child" 2>/dev/null; then
      kill -TERM "$child" 2>/dev/null || true
    fi
    for _ in 1 2 3 4 5 6; do
      kill -0 -- "-$child" 2>/dev/null || break
      sleep 0.5
    done
    if kill -0 -- "-$child" 2>/dev/null; then
      kill -KILL -- "-$child" 2>/dev/null || true
    elif kill -0 "$child" 2>/dev/null; then
      kill -KILL "$child" 2>/dev/null || true
    fi
    wait "$child" 2>/dev/null || true
  fi
  child=""
}

on_term() {
  stopping=1
  log 'stopping'
  stop_child
  exit 0
}
trap on_term TERM INT

sleep_interruptible() {
  sleep "$1" &
  wait $! 2>/dev/null || true
}

health_code() {
  curl --silent --show-error --max-time 4 --output /dev/null \
    --write-out '%{http_code}' "http://127.0.0.1:${local_port}/health" 2>/dev/null || true
}

healthy() {
  code="$(health_code)"
  [ "$code" = "200" ] || [ "$code" = "401" ]
}

have_credentials() {
  # Re-read on every pass so adding the key file after the container starts
  # recovers without a restart. Never print the value.
  if [ -n "${INSTABOX_API_KEY_FILE:-}" ] && [ -f "$INSTABOX_API_KEY_FILE" ]; then
    INSTABOX_API_KEY="$(cat "$INSTABOX_API_KEY_FILE" 2>/dev/null || true)"
    export INSTABOX_API_KEY
  fi
  [ -n "${INSTABOX_API_KEY:-}" ] || [ -f "${HOME}/.config/instabox/credentials.json" ]
}

mkdir -p "$HOME"
failures=0

while [ "$stopping" -eq 0 ]; do
  if ! have_credentials; then
    log 'Instabox credentials are unavailable; waiting (speech will fail closed)'
    sleep_interruptible 30
    continue
  fi

  log "starting private forward ${local_port}:${remote_port} to ${remote}"
  setsid instabox port-forward "$remote" "${local_port}:${remote_port}" --address 0.0.0.0 >/tmp/instabox-forward.log 2>&1 &
  child=$!

  ready=0
  for _ in $(seq 1 30); do
    if [ "$stopping" -eq 1 ]; then break; fi
    if ! kill -0 "$child" 2>/dev/null; then break; fi
    if healthy; then ready=1; break; fi
    sleep 1
  done

  if [ "$ready" -eq 1 ]; then
    log 'tunnel is healthy'
    failures=0
    bad=0
    while [ "$stopping" -eq 0 ] && kill -0 "$child" 2>/dev/null; do
      sleep 5
      if healthy; then
        bad=0
      else
        bad=$((bad + 1))
        log "health probe failed (${bad}/2)"
        [ "$bad" -ge 2 ] && break
      fi
    done
    if [ "$stopping" -eq 0 ]; then
      log 'tunnel is unavailable; recycling it'
    fi
  else
    log 'tunnel did not become healthy'
  fi

  stop_child
  [ "$stopping" -eq 1 ] && break

  failures=$((failures + 1))
  delay=$((1 << (failures > 6 ? 6 : failures)))
  [ "$delay" -gt 60 ] && delay=60
  log "retrying in ${delay}s"
  sleep_interruptible "$delay"
done
