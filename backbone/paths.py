"""Path resolution with no import cycle.

`vault_dir()` answers "where does the owner's vault live" for every vault-scoped feature. The
tracked default is neutral (`~/vault`) so the public repo carries no personal path; a local
`~/.agent-router/backbone.yaml` (untracked) sets `vault_dir:` to where the vault actually is,
and `$BACKBONE_VAULT` overrides both.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACKED_CFG = ROOT / "config" / "backbone.yaml"


def _user_cfg() -> Path:
    # expanduser, not Path.home(): resolves per call and honours a patched HOME in tests
    return Path(os.path.expanduser("~/.agent-router/backbone.yaml"))


def _cfg_vault_dir() -> str | None:
    try:
        import yaml
    except Exception:
        return None
    for p in (_user_cfg(), TRACKED_CFG):
        if not p.exists():
            continue
        try:
            cfg = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        if cfg.get("vault_dir"):
            return str(cfg["vault_dir"])
        return None  # the user config wins even when it has no vault_dir
    return None


def vault_dir(*parts: str, cfg: dict | None = None) -> str:
    """Vault root: explicit cfg -> $BACKBONE_VAULT -> backbone.yaml vault_dir -> ~/vault."""
    base = None
    if cfg is not None:
        base = cfg.get("vault_dir")
    base = base or os.environ.get("BACKBONE_VAULT") or _cfg_vault_dir() or "~/vault"
    return os.path.join(os.path.expanduser(str(base)), *parts)
