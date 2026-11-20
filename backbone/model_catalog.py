"""Daily free-model health receipts. No agents, tools, retries or paid fallback.

Kilo/Cline use their public OpenAI-compatible model catalogs. OpenCode uses
`opencode models` intersected with zero-price models.dev metadata.
Keys enter probe children through with-env, never argv or persisted snapshots.
Invoke daily via `backbone catalog models`; this module installs no scheduler.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

BASES = {
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "opencode": "https://opencode.ai/inference/openai/v1",
    "kilo": "https://ai-gateway.kilo.ai/api/v1",
    "cline": "https://api.cline.bot/api/v1",
}
KEYS = {"nvidia": "NIM_1", "kilo": "KILO_API_KEY", "cline": "CLINE_API_KEY",
        "opencode": "OPENCODE_API_KEY"}
TIMEOUT = 15
PROMPT = "Reply OK."


def fetch(url, *, data=None, key=None):
    headers = {"Content-Type": "application/json", "User-Agent": "backbone-model-catalog"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        return json.load(response)


def is_free(row):
    """Unknown/negative prices never authorize a call. Explicit prices win."""
    pricing = row.get("pricing")
    if pricing is not None:
        try:
            return (all(Decimal(str(pricing[k])) == 0 for k in ("prompt", "completion"))
                    and all(Decimal(str(v)) == 0 for v in pricing.values()))
        except (KeyError, TypeError, InvalidOperation, ValueError):
            return False
    if "isFree" in row:
        return row["isFree"] is True
    return row["id"].endswith((":free", "-free"))


def discover(provider):
    if provider == "opencode":
        result = subprocess.run(["opencode", "models"], capture_output=True,
                                text=True, timeout=TIMEOUT, check=True)
        # Never interpret diagnostic output or another provider's model as Zen.
        ids = [line.strip()[len("opencode/"):] for line in result.stdout.splitlines()
               if re.fullmatch(r"opencode/[\w./:-]+", line.strip())]
        if not ids:
            raise ValueError("no OpenCode model IDs")
        # A free promotion can end without an ID changing. Never rely on the
        # name alone when current pricing metadata is available.
        metadata = fetch("https://models.dev/api.json")["opencode"]["models"]
        if not isinstance(metadata, dict):
            raise ValueError("invalid OpenCode pricing metadata")
        rows = []
        for model in ids:
            cost = metadata.get(model, {}).get("cost", {})
            if not isinstance(cost, dict):
                continue
            rows.append({"id": model, "pricing": {
                "prompt": cost.get("input"), "completion": cost.get("output"),
                **{k: v for k, v in cost.items() if k not in ("input", "output")}}})
    else:
        rows = fetch(BASES[provider] + "/models")["data"]
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("id"), str)
        or not re.fullmatch(r"[\w./:-]+", row["id"]) for row in rows
    ):
        raise ValueError("invalid model list")
    return sorted({row["id"] for row in rows if provider == "nvidia" or is_free(row)})


def tiny_call(provider, model):
    """Run inside the key-loader child; report no response body or exceptions."""
    start = time.monotonic()
    try:
        key = os.environ.get(KEYS.get(provider, "OPENCODE_API_KEY"))
        if provider in KEYS and not key:
            return {"ok": False, "latency": None, "error": "missing_key"}
        body = json.dumps({"model": model, "messages": [{"role": "user", "content": PROMPT}],
                           "max_tokens": 8, "stream": False}).encode()
        reply = fetch(BASES[provider] + "/chat/completions", data=body, key=key)
        choices = reply.get("choices", [])
        ok = any(isinstance(c, dict) and isinstance(c.get("message"), dict)
                 and bool((c["message"].get("content") or "").strip()) for c in choices)
        result = {"ok": ok}
        if not ok:
            result["error"] = "empty_completion"
    except Exception as exc:
        result = {"ok": False, "error": type(exc).__name__}
    return {**result, "latency": round(time.monotonic() - start, 4)}


def probe(provider, model):
    try:
        result = subprocess.run(
            [str(Path.home() / ".claude/scripts/with-env"), KEYS[provider], "--",
             sys.executable, "-m", "backbone.model_catalog", "--probe", provider, model],
            capture_output=True, text=True, timeout=TIMEOUT + 5, check=True)
        reply = json.loads(result.stdout)
        if not isinstance(reply.get("ok"), bool):
            raise ValueError("invalid probe result")
        return reply
    except Exception as exc:
        return {"ok": False, "latency": None, "error": type(exc).__name__}


def diff_models(current, yesterday, available):
    def index(rows):
        return {(r["provider"], r["id"]): r for r in rows if r["provider"] in available}
    new, old = index(current), index(yesterday)
    def names(keys):
        return [f"{p}/{m}" for p, m in sorted(keys)]
    return {"new": names(new.keys() - old.keys()),
            "removed": names(old.keys() - new.keys()),
            "failing": names(k for k, row in new.items() if not row["ok"])}


def atomic_json(path, value):
    from .redact import redact_obj
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        try:
            json.dump(redact_obj(value), handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def snapshot(out="~/.agent-router/model_catalog.json", *, force=False, now=None):
    """One locked snapshot/day, compared against the actual previous UTC day.

    Keep last observations for unavailable sources with stale=true. Never infer
    removals or new probe failures from a failed discovery request.
    Latency is seconds; checked is UTC ISO-8601. --force retains yesterday's baseline.
    """
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    out = Path(out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    history = out.parent / out.stem
    history.mkdir(exist_ok=True)
    today = history / f"{now.date()}.json"
    yesterday = history / f"{(now - timedelta(days=1)).date()}.json"
    with out.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if today.exists() and not force:
            return json.loads(today.read_text())
        previous = json.loads(out.read_text()) if out.exists() else {"models": []}
        baseline = json.loads(yesterday.read_text()) if yesterday.exists() else {"models": []}
        rows, errors, available = [], {}, []
        for provider in BASES:
            try:
                ids = discover(provider)
            except Exception as exc:
                errors[provider] = type(exc).__name__
                rows.extend({**r, "stale": True} for r in previous["models"]
                            if r["provider"] == provider)
                continue
            available.append(provider)
            for model in ids:
                result = probe(provider, model)
                rows.append({"provider": provider, "id": model, "free": True,
                             "latency": result["latency"], "ok": result["ok"],
                             "checked": now.isoformat(), "stale": False,
                             **({"error": result["error"]} if "error" in result else {})})
        report = {"checked": now.isoformat(), "models": rows, "errors": errors,
                  "baseline": str(yesterday) if yesterday.exists() else None,
                  "diff": diff_models(rows, baseline["models"], available)}
        # No yesterday receipt means no evidence for new/removed.
        if report["baseline"] is None:
            report["diff"]["new"] = []
            report["diff"]["removed"] = []
        atomic_json(today, report)
        atomic_json(out, report)
        atomic_json(out.with_suffix(".diff.json"), report["diff"])
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", nargs=2, metavar=("PROVIDER", "MODEL"), required=True)
    args = parser.parse_args()
    provider, model = args.probe
    if provider not in BASES:
        parser.error("unknown provider")
    print(json.dumps(tiny_call(provider, model)))
