#!/usr/bin/env python3
"""NIM key harness: key rotation + retry with backoff + per-key cooldown.

Why this exists (measured 2026-11-11):
- nim_call.chat() walks its key list but STOPS at the first non-429 HTTP error
  (nim_call.py:106 `if e.code != 429: break`). One dead key (403) kills every
  call even when NIM_2/NIM_1 are valid — reproduced: broken NIM_3 -> "http 403",
  valid keys never tried.
- nim_call.chat() has no retry and no backoff.
- Its global KEYS order (NIM_3 first) makes per-model/per-agent `api_key_env`
  pinning dead: every call lands on NIM_3.

This harness owns key selection, rotates on failure, parks unhealthy keys, and
reuses nim_call's shared cross-process throttle (MIN_GAP) and dispatch logging.

Keys are read from the process env, then the project .env, then ~/.env.
Never printed, never in argv.
"""
from __future__ import annotations

import os
import re
import sys
import time

HOME = os.path.expanduser("~")
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPTS_DIR)
sys.path.insert(0, _SCRIPTS_DIR)
_memory_vault_scripts = os.path.join(HOME, "memory-vault", "scripts")
if os.path.isdir(_memory_vault_scripts):
    sys.path.insert(0, _memory_vault_scripts)
import nim_call  # noqa: E402

PROJECT_ENV = os.path.join(_PROJECT_ROOT, ".env")
HOME_ENV = os.path.join(HOME, ".env")

KEY_ENVS = ("NIM_3", "NIM_2", "NIM_1")
DEFAULT_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"
BACKOFF = (1.0, 2.0, 4.0)
COOLDOWN_RATE = 60.0      # 429: park the key for a minute
COOLDOWN_DEAD = 3600.0    # 401/403: quarantine the key for an hour
COOLDOWN_TRANSIENT = 5.0  # timeout/5xx: short park, then try it again


def _read_env_file(path, names):
    """Read the given names from a dotenv file. Values never logged."""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip().removeprefix("export ")
                k, s, v = line.partition("=")
                k = k.strip()
                if s and k in names:
                    v = v.strip().strip('"').strip("'")
                    if v:
                        out[k] = v
    except OSError:
        pass
    return out


class NimKeyHarness:
    """Rotate NIM keys, retry with backoff, park unhealthy keys."""

    def __init__(self, key_envs=KEY_ENVS, model=DEFAULT_MODEL):
        self.key_envs = list(key_envs)
        self.model = model
        self._rr = 0
        self._until = {}   # key env -> cooldown end (epoch seconds)
        self._dead = set()  # key env -> quarantined (401/403)
        self.stats = {"attempts": 0, "ok": 0, "fail": 0, "rotations": 0, "by_kind": {}}

    # -- key plumbing ---------------------------------------------------
    def _resolve(self, name: str) -> str:
        """Key value for `name` from env, project .env, then ~/.env."""
        v = os.environ.get(name, "")
        if v:
            return v
        for path in (PROJECT_ENV, HOME_ENV):
            got = _read_env_file(path, {name})
            if name in got:
                os.environ[name] = got[name]  # nim_call._env() reads os.environ only
                return got[name]
        return ""

    def get_client(self, preferred: str | None = None) -> str | None:
        """Next usable key env name (round-robin), skipping parked/dead/missing keys.

        If `preferred` is set, only that key is considered — no fallback to
        other keys when the pinned key has no value.
        """
        now = time.time()
        if preferred:
            if preferred in self._dead or self._until.get(preferred, 0) > now:
                return None
            if not self._resolve(preferred):
                return None
            return preferred
        order = list(self.key_envs)
        n = len(order)
        if n:
            offset = self._rr % n
            order = order[offset:] + order[:offset]  # start at the rotation cursor
        for name in order:
            if name in self._dead or self._until.get(name, 0) > now:
                continue
            if not self._resolve(name):
                continue
            self._rr = (self.key_envs.index(name) + 1) % n
            return name
        return None

    def mark_key_unhealthy(self, key: str, seconds: float) -> None:
        """Park `key` for `seconds` (429 cooldown, dead-key quarantine, transient park)."""
        self._until[key] = time.time() + seconds

    def has_key(self, name: str) -> bool:
        """True if `name` resolves to a non-empty key (env, project .env, or ~/.env)."""
        return bool(self._resolve(name))

    # -- retry ----------------------------------------------------------
    @staticmethod
    def _classify(err) -> str:
        """Map a nim_call RuntimeError message to a failure kind."""
        s = str(err)
        if "http 429" in s:
            return "rate"
        if re.search(r"http (401|403)", s):
            return "dead"
        if re.search(r"http 4\d\d", s):
            return "fatal"  # bad request: another key will not fix it
        return "transient"  # timeout, DNS, 5xx

    def call_with_retry(self, messages, model=None, timeout=120, max_tokens=1500,
                        attempts=3, backoff=None, preferred=None):
        """Call the model, rotating keys across attempts. Raises RuntimeError on give-up.

        `preferred` is a key env name to try first (honours models.yaml api_key_env).
        """
        model = model or self.model
        if "," in model or model.endswith("chain"):
            raise ValueError("chain models bypass key_order; call one model at a time")
        backoff = BACKOFF if backoff is None else backoff
        last = None
        for attempt in range(attempts):
            key = self.get_client(preferred=preferred)
            if not key:
                raise RuntimeError("no healthy NIM key")
            self.stats["attempts"] += 1
            try:
                out = nim_call.chat(model, messages, timeout=timeout,
                                    max_tokens=max_tokens, key_order=[key], rules=False)
                self.stats["ok"] += 1
                return out
            except Exception as e:
                last = e
                kind = self._classify(e)
                self.stats["fail"] += 1
                self.stats["by_kind"][kind] = self.stats["by_kind"].get(kind, 0) + 1
                if kind == "fatal":
                    break
                if kind == "dead":
                    self._dead.add(key)
                    self.mark_key_unhealthy(key, COOLDOWN_DEAD)
                elif kind == "rate":
                    self.mark_key_unhealthy(key, COOLDOWN_RATE)
                else:
                    self.mark_key_unhealthy(key, COOLDOWN_TRANSIENT)
                self.stats["rotations"] += 1
                if attempt < attempts - 1:
                    time.sleep(backoff[min(attempt, len(backoff) - 1)])
        raise RuntimeError(f"nim failed after {attempts} attempt(s): {last}")
