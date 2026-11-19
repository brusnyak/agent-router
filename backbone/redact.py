"""Mask secrets in any text before the router stores, logs or prints it. Stdlib only, no network.

Two layers, because neither alone is enough:
  shape  well-known key formats (nvapi-, sk-, ghp_, github_pat_, AKIA..., xox*-, AIza..., KGAT_, Bearer <token>, JWT)
  value  the exact values of keys this machine really has (names from keys.env_key_names, values from the process
         environment), so a key in a format nobody wrote a pattern for is still masked once the router holds it

Applied where output leaves the router: CLI JSON, run results, node job results, tickets. A worker may echo a key it saw;
the router must not persist it."""
from __future__ import annotations

import os
import re
from typing import Iterable, List, Optional

MASK = "[REDACTED:{}]"
MIN_VALUE_LEN = 12          # shorter values are too likely to be ordinary words
SHAPES = [
    ("nvidia", re.compile(r"nvapi-[A-Za-z0-9_\-]{20,}")),
    ("openai", re.compile(r"sk-(?:proj-|or-v1-)?[A-Za-z0-9_\-]{24,}")),
    ("github", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}")),
    ("aws", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("google", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("kaggle", re.compile(r"KGAT_[a-f0-9]{20,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("bearer", re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=\-]{20,}")),
]


def known_values(environ: Optional[dict] = None, names: Optional[Iterable[str]] = None) -> List[str]:
    """Values of key-like variables this process holds, longest first (so a key containing another is masked whole)."""
    from .keys import env_key_names
    env = os.environ if environ is None else environ
    wanted = set(names) if names is not None else set(env_key_names(paths=(), environ=env))
    vals = {env[n] for n in wanted if n in env and len(env[n]) >= MIN_VALUE_LEN}
    return sorted(vals, key=len, reverse=True)


def redact(text, environ: Optional[dict] = None) -> str:
    """Return text with every known secret replaced by [REDACTED:kind]. Non-strings are returned unchanged."""
    if not isinstance(text, str) or not text:
        return text
    out = text
    for kind, rx in SHAPES:
        out = rx.sub(lambda m, k=kind: (m.group(1) + MASK.format(k)) if k == "bearer" else MASK.format(k), out)
    for v in known_values(environ):
        if v in out:
            out = out.replace(v, MASK.format("key"))
    return out


def redact_obj(o, environ: Optional[dict] = None):
    """Recursively redact every string in a JSON-like structure (dict keys are left alone)."""
    if isinstance(o, str):
        return redact(o, environ)
    if isinstance(o, dict):
        return {k: redact_obj(v, environ) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [redact_obj(v, environ) for v in o]
    return o
