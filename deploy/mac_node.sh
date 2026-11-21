#!/bin/bash
# Mac node: outbound ssh -L tunnel to the Oracle hub + `backbone node`. Outbound only, no Tailscale.
# Exits non-zero when the tunnel or the node dies, so launchd (KeepAlive) restarts both after
# sleep, network loss or a reboot.
set -u

HUB_HOST="${HUB_HOST:-oracle-vm}"
HUB_PORT="${HUB_PORT:-8799}"          # port of the hub on the remote host
LOCAL_PORT="${LOCAL_PORT:-18799}"     # local end of the tunnel; 8799 is usually a local `backbone serve`
NODE_NAME="${NODE_NAME:-mac}"
LOG_DIR="${LOG_DIR:-$HOME/Library/Logs/agent-router}"
mkdir -p "$LOG_DIR"
cd "$HOME/Developer/agent-router" || exit 1

TUNNEL_PID=""; NODE_PID=""
cleanup() { kill $TUNNEL_PID $NODE_PID 2>/dev/null; }
trap cleanup EXIT TERM INT

ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o BatchMode=yes -o ConnectTimeout=15 \
    -L "127.0.0.1:${LOCAL_PORT}:127.0.0.1:${HUB_PORT}" "$HUB_HOST" >>"$LOG_DIR/tunnel.log" 2>&1 &
TUNNEL_PID=$!

for _ in $(seq 1 30); do
  nc -z 127.0.0.1 "$LOCAL_PORT" 2>/dev/null && break
  kill -0 "$TUNNEL_PID" 2>/dev/null || exit 1
  sleep 1
done
nc -z 127.0.0.1 "$LOCAL_PORT" 2>/dev/null || exit 1

# BACKBONE_TOKEN is never stored in the plist: take it from the environment, else from the local secret loader.
# HUB_AUTH_REF names the stored key holding the hub's token (default BACKBONE_TOKEN), so a local
# `backbone serve` token with the same name never collides with the remote hub's token.
WITH_ENV="${WITH_ENV:-$HOME/.claude/scripts/with-env}"
BACKBONE_BIN="${BACKBONE_BIN:-$HOME/.local/bin/backbone}"   # the shim picks the interpreter (BACKBONE_PYTHON, venv, python3)
TOKEN_KEY="${HUB_AUTH_REF:-BACKBONE_TOKEN}"
if [ -z "${BACKBONE_TOKEN:-}" ] && [ -x "$WITH_ENV" ]; then
  "$WITH_ENV" "$TOKEN_KEY" -- sh -c 'export BACKBONE_TOKEN="$(printenv "$1")"; shift; exec "$@"' sh "$TOKEN_KEY" \
    "$BACKBONE_BIN" node --hub "http://127.0.0.1:${LOCAL_PORT}" --name "$NODE_NAME" >>"$LOG_DIR/node.log" 2>&1 &
else
  "$BACKBONE_BIN" node --hub "http://127.0.0.1:${LOCAL_PORT}" --name "$NODE_NAME" >>"$LOG_DIR/node.log" 2>&1 &
fi
NODE_PID=$!

# macOS bash 3.2 has no `wait -n`: poll both children, exit when either dies.
while kill -0 "$TUNNEL_PID" 2>/dev/null && kill -0 "$NODE_PID" 2>/dev/null; do sleep 5; done
exit 1
