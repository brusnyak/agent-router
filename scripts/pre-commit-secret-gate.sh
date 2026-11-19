#!/bin/sh
# Secret gate for git commits: blocks a commit whose staged changes contain a key. Values are redacted in the output.
# Install: cp scripts/pre-commit-secret-gate.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
CFG="${GITLEAKS_CONFIG:-$HOME/.claude/security/gitleaks.toml}"
command -v gitleaks >/dev/null 2>&1 || { echo "pre-commit: gitleaks not installed, secret gate SKIPPED" >&2; exit 0; }
[ -r "$CFG" ] || CFG=""
if [ -n "$CFG" ]; then
  gitleaks git --staged -c "$CFG" --redact=100 --no-banner -l error
else
  gitleaks git --staged --redact=100 --no-banner -l error
fi
rc=$?
[ $rc -eq 0 ] || { echo "pre-commit: secret found in staged changes (value redacted above). Put it in ~/.env and load it with ~/.claude/scripts/with-env." >&2; exit 1; }
exit 0
