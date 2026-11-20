#!/bin/bash
# Mac node: outbound ssh -L tunnel to the Oracle hub + `backbone node`. Outbound only, no Tailscale.
# Exits non-zero when the tunnel or the node dies, so launchd (KeepAlive) restarts both after
# sleep, network loss or a reboot.
set -u

HUB_HOST="${HUB_HOST:-oracle-vm}"
HUB_PORT="${HUB_PORT:-8799}"
NODE_NAME="${NODE_NAME:-mac}"
LOG_DIR="${LOG_DIR:-$HOME/Library/Logs/agent-router}"
mkdir -p "$LOG_DIR"
cd "$HOME/Developer/agent-router" || exit 1

TUNNEL_PID=""; NODE_PID=""
cleanup() { kill $TUNNEL_PID $NODE_PID 2>/dev/null; }
trap cleanup EXIT TERM INT

ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o BatchMode=yes -o ConnectTimeout=15 \
    -L "127.0.0.1:${HUB_PORT}:127.0.0.1:${HUB_PORT}" "$HUB_HOST" >>"$LOG_DIR/tunnel.log" 2>&1 &
TUNNEL_PID=$!

for _ in $(seq 1 30); do
  nc -z 127.0.0.1 "$HUB_PORT" 2>/dev/null && break
  kill -0 "$TUNNEL_PID" 2>/dev/null || exit 1
  sleep 1
done
nc -z 127.0.0.1 "$HUB_PORT" 2>/dev/null || exit 1

# BACKBONE_TOKEN is never stored in the plist: take it from the environment, else from the local secret loader.
WITH_ENV="${WITH_ENV:-$HOME/.claude/scripts/with-env}"
LOAD=""
if [ -z "${BACKBONE_TOKEN:-}" ] && [ -x "$WITH_ENV" ]; then LOAD="$WITH_ENV BACKBONE_TOKEN --"; fi
$LOAD python3 -m backbone node --hub "http://127.0.0.1:${HUB_PORT}" --name "$NODE_NAME" >>"$LOG_DIR/node.log" 2>&1 &
NODE_PID=$!

# macOS bash 3.2 has no `wait -n`: poll both children, exit when either dies.
while kill -0 "$TUNNEL_PID" 2>/dev/null && kill -0 "$NODE_PID" 2>/dev/null; do sleep 5; done
exit 1
