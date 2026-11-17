"""Deterministic planner: prompt -> task class + size -> candidate workers (Portkey-style rules) -> pick (LiteLLM-style Thompson
bandit, rewarded by our own hard gates) -> compiled command and a worker-shaped prompt packet. No LLM, no network, stdlib + yaml."""
from __future__ import annotations

import os
import re
import shutil

import yaml
from .rules import resolve
from .tier import predict_tier

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKERS = {
    "nim1": {"tier": 2, "cost": 0.0, "bin": None, "key": "NIM_1"}, "nim2": {"tier": 2, "cost": 0.0, "bin": None, "key": "NIM_2"},
    "nim3": {"tier": 2, "cost": 0.0, "bin": None, "key": "NIM_3"},
    "codex": {"tier": 3, "cost": 0.6, "bin": "codex"}, "claude": {"tier": 3, "cost": 0.8, "bin": "claude"},
    "opencode": {"tier": 2, "cost": 0.0, "bin": None, "key": None},  # proxy holds the keys; availability = proxy up
    "agy": {"tier": 3, "cost": 0.5, "bin": "agy"},  # read-only, Google quota
    "jcode": {"tier": 2, "cost": 0.2, "bin": "jcode", "key": "NIM_1"},  # ~29k input tokens per call measured: not free
}
CLASS_WORDS = (
    ("review", ("review", "roast", "critique", "audit", "red team")),
    ("research", ("research", "compare", "find out", "summarize", "summarise", "what is", "survey")),
    ("code_edit", ("implement", "refactor", "fix ", "add ", "write ", "port ", "rewrite", "migrate", "build ")),
)


def classify(prompt: str) -> dict:
    low = prompt.lower()
    cls = next((c for c, ws in CLASS_WORDS if any(w in low for w in ws)), "other")
    n = len(prompt)
    return {"task_class": cls, "size": "small" if n < 400 else "medium" if n < 1500 else "large"}


def _proxy_up(port: int = 8787) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def available(env=None) -> set:
    if env is None:
        from .keys import load_named
        env = {**load_named(["NIM_1", "NIM_2", "NIM_3"]), **os.environ}
    out = set()
    for w, m in WORKERS.items():
        if w == "opencode" and not _proxy_up():
            continue
        if (m["bin"] is None or shutil.which(m["bin"])) and (not m.get("key") or env.get(m["key"])):
            out.add(w)
    return out


def load_rules(path: str | None = None) -> list:
    with open(path or os.path.join(ROOT, "config", "routes.yaml")) as f:
        return yaml.safe_load(f).get("rules", [])


def packet(prompt: str, worker: str, gate: str) -> str:
    """Worker-shaped prompt: small NIM models get a rigid checklist, strong CLIs get the goal and the gate."""
    done = f"Done = `{gate}` exits 0." if gate else "State what you verified."
    if worker.startswith("nim"):
        return f"TASK: {prompt.strip()}\nRULES: smallest diff; touch only needed files; run the gate before answering.\n{done}"
    return f"{prompt.strip()}\n\n{done} Keep the diff minimal and mention anything out of scope in one line."


def plan(prompt: str, bandit=None, rules=None, avail=None, rng=None) -> dict:
    ctx = classify(prompt)
    rule = resolve(rules if rules is not None else load_rules(), ctx) or {}
    then = rule.get("then") or {"worker": "nim1", "fallbacks": ["nim2"], "gate_hint": ""}
    avail = available() if avail is None else avail
    cands = [w for w in [then["worker"], *then.get("fallbacks", [])] if w in avail] or sorted(avail & {"nim1", "nim2", "nim3"})
    if not cands:
        return {**ctx, "worker": "", "fallbacks": [], "gate_hint": "", "command": "", "packet": "", "why": "no worker available"}
    picked, why = cands[0], "rule order"
    min_tier = predict_tier(prompt)
    if bandit is not None and len(cands) > 1:
        meta = {w: {"tier": WORKERS[w]["tier"], "cost": WORKERS[w]["cost"], "strengths": []} for w in cands}
        try:
            picked, _ = bandit.pick(ctx["task_class"], meta, rng=rng, min_tier=min_tier)
        except TypeError:  # mock/stub bandits without min_tier
            picked, _ = bandit.pick(ctx["task_class"], meta, rng=rng)
        why = "thompson"
    gate = str(then.get("gate_hint") or "")
    gate = "" if gate in ("True", "true") else gate
    task = " ".join(prompt.split())[:240].replace("'", "")
    cmd = f"python3 -m backbone run --worker {picked} --gate '{gate or '<gate cmd>'}' '{task}'"
    return {**ctx, "worker": picked, "fallbacks": [w for w in cands if w != picked], "gate_hint": gate, "command": cmd,
            "packet": packet(prompt, picked, gate), "why": why}


def quick_pick(prompt: str) -> dict:
    """For the enforcement hook: read-only, no bandit writes."""
    try:
        p = plan(prompt)
        return {"worker": p["worker"] or "nim1", "gate_hint": p["gate_hint"]}
    except Exception:
        return {}


def bandit_path() -> str:
    return os.environ.get("BANDIT_DB") or os.path.expanduser("~/.agent-router/data/bandit.db")


def label(worker: str) -> str:
    """Worker string from a run ('pi:NIM_2', 'jcode:NIM_1', 'codex') -> planner name ('nim2', 'jcode', 'codex')."""
    kind, _, arg = worker.partition(":")
    m = re.search(r"(\d+)$", arg)
    return f"nim{m.group(1)}" if kind == "pi" and m else ("nim1" if kind == "pi" else kind)


def learn(prompt: str, worker: str, gate_present: bool, gate_passed: bool, latency_ms: int = 0) -> None:
    """Gate result -> bandit. No gate = no learning (an unverified answer is not evidence). Never raises."""
    try:
        from .bandit import Bandit
        w = label(worker)
        if w not in WORKERS:
            return
        cls = classify(prompt)["task_class"]
        b = Bandit(bandit_path())
        m = WORKERS[w]
        b.pick(cls, {w: {"tier": m["tier"], "cost": m["cost"], "strengths": []}})  # creates the cell with its prior if new
        b.update(cls, w, gate_passed if gate_present else None, latency_ms)
    except Exception:
        pass
