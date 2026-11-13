"""Offline enrich of shadow-hook receipts: fills would_surface. No prompt text is stored or printed.
Assumptions (spec files absent in this tree): receipt keys receipt_id/mode/would_surface/session_id/prompt_hash;
catalog.json = list of {name, description} or {name: description}; gate.json = {"threshold": float}."""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import urllib.request
from pathlib import Path

HOME = Path.home()
ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "heldout_v2" / "judge" / "catalog.json"
GATE = ROOT / "heldout_v2" / "gate.json"
CACHE = HOME / ".agent-router" / "catalog-embed.json"
URL = os.environ.get("NIM_EMBED_URL", "https://integrate.api.nvidia.com/v1/embeddings")
MODEL = os.environ.get("NIM_EMBED_MODEL", "nvidia/nv-embedqa-e5-v5")


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def jsonl(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    pass
    except OSError:
        return


def find_prompt(session_id: str, prompt_hash: str, projects: str | None = None) -> str | None:
    base = projects or str(HOME / ".claude" / "projects")
    for p in glob.glob(os.path.join(base, "*", f"{session_id}.jsonl")):
        for o in jsonl(p):
            m = o.get("message") or {}
            if o.get("type") != "user" and m.get("role") != "user":
                continue
            c = m.get("content")
            texts = [c] if isinstance(c, str) else [b.get("text", "") for b in c or [] if isinstance(b, dict)]
            for t in texts:
                if isinstance(t, str) and prompt_hash in (sha(t.strip()), sha(t)):
                    return t
    return None


def embed(text: str, kind: str) -> list:
    ks = [os.environ[k] for k in ("NIM_1", "NIM_2", "NIM_3") if os.environ.get(k)]
    if not ks:
        raise RuntimeError("no NIM_1..NIM_3 in env")
    body = json.dumps({"model": MODEL, "input": [text], "input_type": kind, "truncate": "END"}).encode()
    err = None
    for k in ks:
        req = urllib.request.Request(URL, data=body, headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())["data"][0]["embedding"]
        except Exception as e:  # try next key; never echo key
            err = type(e).__name__
    raise RuntimeError(f"embed failed: {err}")


def cosine(a, b):
    d = sum(x * y for x, y in zip(a, b))
    return d / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5) or 1.0)


def nim_retriever(catalog=CATALOG, cache=CACHE):
    raw = json.loads(Path(catalog).read_text())
    items = raw.items() if isinstance(raw, dict) else [(e.get("name"), e.get("description", "")) for e in raw]
    try:
        store = json.loads(Path(cache).read_text())
    except (OSError, ValueError):
        store = {}
    vecs = {}
    for name, desc in items:
        h = sha(f"{name}\n{desc}")
        if h not in store:
            store[h] = embed(f"{name}: {desc}", "passage")
        vecs[name] = store[h]
    Path(cache).parent.mkdir(parents=True, exist_ok=True)
    Path(cache).write_text(json.dumps(store))

    def retrieve(query):
        q = embed(query[:300], "query")
        return sorted(((n, cosine(q, v)) for n, v in vecs.items()), key=lambda x: -x[1])[:3]
    return retrieve


def threshold(gate=GATE) -> float:
    try:
        return float(json.loads(Path(gate).read_text()).get("threshold", 0.0))
    except (OSError, ValueError, AttributeError, TypeError):
        return 0.0


def enrich(receipts, out, retrieve, projects=None, limit=None, T=0.0):
    done = {r.get("receipt_id") for r in jsonl(out)}
    todo = [r for r in jsonl(receipts) if r.get("mode") == "shadow" and not r.get("would_surface")
            and r.get("receipt_id") not in done]
    todo = todo[:limit] if limit else todo
    rows = []
    for r in todo:
        text = find_prompt(r.get("session_id", ""), r.get("prompt_hash", ""), projects)
        row = dict(r, would_surface=[], scores=[], margin=None, gate=T)
        if text is None:
            row["abstention"] = "prompt-not-found"
        else:
            top = retrieve(text[:300])[:3]
            row["scores"] = [round(s, 4) for _, s in top]
            row["margin"] = round(top[0][1] - top[1][1], 4) if len(top) > 1 else None
            if row["margin"] is not None and row["margin"] < T:
                row["abstention"] = "margin"
            else:
                row["would_surface"] = [n for n, _ in top]
        rows.append(row)
    return todo, rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipts", default=str(HOME / ".agent-router" / "hook-shadow.jsonl"))
    ap.add_argument("--out", default=str(HOME / ".agent-router" / "hook-shadow-enriched.jsonl"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.dry_run:
        todo, rows = enrich(a.receipts, a.out, lambda q: [], limit=a.limit)
        print(f"pending={len(todo)} prompt_found={sum(1 for r in rows if r.get('abstention') != 'prompt-not-found')}")
        return 0
    _, rows = enrich(a.receipts, a.out, nim_retriever(), limit=a.limit, T=threshold())
    if rows:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        with open(a.out, "a") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)
    print(f"written={len(rows)} abstained={sum(1 for r in rows if r.get('abstention'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
