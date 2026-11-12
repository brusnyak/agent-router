"""Key policy: lease NIM keys with per-key concurrency caps, cooldown on failure, retry + failover.

Deterministic: preferred key first, then the next free one. No gateway process.
"""
from __future__ import annotations

import contextlib
import os
import threading
import time
from typing import Callable, Dict, List, Optional, TypeVar

T = TypeVar("T")


class Transient(Exception):
    """Worth retrying, ideally on another key: 429, 5xx, timeouts, queue/safety-screen errors."""


class KeyPool:
    def __init__(self, names: List[str], max_concurrent: int = 2, cooldown_s: float = 20.0,
                 env: Optional[dict] = None, wait_s: float = 120.0):
        self.env = env if env is not None else os.environ
        self.names = [n for n in names if self.env.get(n)]
        self.all_names = list(names)
        self.cooldown_s = cooldown_s
        self.wait_s = wait_s
        self._sem = {n: threading.BoundedSemaphore(max_concurrent) for n in self.names}
        self._cool: Dict[str, float] = {n: 0.0 for n in self.names}
        self.stats: Dict[str, Dict[str, int]] = {n: {"ok": 0, "fail": 0} for n in self.names}
        self._mu = threading.Lock()

    def value(self, name: str) -> str:
        return self.env.get(name, "")

    def status(self) -> Dict[str, dict]:
        now = time.time()
        return {n: {"present": n in self.names, "cooling_s": max(0, round(self._cool.get(n, 0) - now, 1)),
                    **self.stats.get(n, {})} for n in self.all_names}

    def _order(self, prefer: Optional[str], avoid: Optional[str]) -> List[str]:
        now = time.time()
        order = [n for n in self.names]
        if prefer in order:
            order.remove(prefer)
            order.insert(0, prefer)
        order.sort(key=lambda n: (self._cool[n] > now, n == avoid))  # stable: cooled/avoided keys last
        return order

    @contextlib.contextmanager
    def lease(self, prefer: Optional[str] = None, avoid: Optional[str] = None):
        if not self.names:
            raise RuntimeError("no NIM keys present in environment (" + ", ".join(self.all_names) + ")")
        deadline = time.time() + self.wait_s
        got = None
        while got is None:
            for n in self._order(prefer, avoid):
                if self._sem[n].acquire(blocking=False):
                    got = n
                    break
            if got is None:
                if time.time() > deadline:
                    raise Transient("all keys busy past wait budget")
                time.sleep(0.2)
        try:
            yield got
        finally:
            self._sem[got].release()

    def report(self, name: str, ok: bool) -> None:
        with self._mu:
            self.stats[name]["ok" if ok else "fail"] += 1
            if not ok:
                self._cool[name] = time.time() + self.cooldown_s

    def call(self, fn: Callable[[str, str], T], prefer: Optional[str] = None,
             retries: int = 1, backoff_s: float = 3.0) -> T:
        """fn(key_name, key_value). Transient errors retry (max `retries`), moving to another key."""
        last: Optional[Exception] = None
        used: Optional[str] = None
        attempts = max(retries + 1, len(self.names))  # every key gets a chance (SPEC D4)
        for attempt in range(attempts):
            try:
                with self.lease(prefer=prefer if attempt == 0 else None, avoid=used) as name:
                    used = name
                    try:
                        out = fn(name, self.value(name))
                        self.report(name, True)
                        return out
                    except Transient as e:
                        self.report(name, False)
                        last = e
            except Transient as e:
                last = e
            if attempt < attempts - 1:
                time.sleep(backoff_s * min(attempt + 1, 3))
        raise Transient(f"failed after {attempts} attempts: {last}")
