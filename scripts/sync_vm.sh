#!/bin/sh
# Mac -> Oracle code sync (one way; the VM keeps its own data/, credentials file, .deps, .git).
# Usage: scripts/sync_vm.sh [--dry] [--restart]
set -e
cd "$(dirname "$0")/.."
OPT="-az --delete"
[ "$1" = "--dry" ] && OPT="-azn --delete"
rsync $OPT --exclude data/ --exclude .tools/ --exclude '.env*' --exclude .deps/ --exclude .git/ --exclude __pycache__/ \
  --exclude node_modules/ --exclude '*.db*' --exclude .pytest_cache/ ./ oracle-vm:agent-router/
[ "$1" = "--restart" ] && ssh oracle-vm 'systemctl --user restart agent-router; sleep 3; systemctl --user is-active agent-router'
echo done
