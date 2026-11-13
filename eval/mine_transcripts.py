"""Mine REAL owner prompts from Claude Code transcripts into a held-out eval set. Read-only on the transcripts.
Label = the skill/agent the session actually invoked after the prompt (Skill / Agent tool calls): a free, non-self-authored signal.
Output stays local (eval/heldout/, gitignored): it contains private text. Secrets are dropped, not masked."""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from typing import Iterator, Optional

SECRET = re.compile(r"(nvapi-|sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{16,}|xox[bp]-|AKIA[0-9A-Z]{12,}|\d{8,}:AA[\w-]{30,}|BEGIN [A-Z ]*PRIVATE KEY|password\s*[:=]|api[_-]?key\s*[:=])", re.I)
NOISE = ("Another Claude session sent", "[SYSTEM NOTIFICATION", "<system-reminder", "<command-", "Caveat:", "<local-command", "[Request interrupted", "<task-notification", "<ide_", "<user-prompt")


def human_text(msg: dict) -> Optional[str]:
    c = msg.get("message", {}).get("content")
    if isinstance(c, list):
        if any(b.get("type") == "tool_result" for b in c if isinstance(b, dict)):
            return None
        c = " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(c, str):
        return None
    c = c.strip()
    if len(c) < 25 or any(n in c[:80] for n in NOISE) or SECRET.search(c):
        return None
    return c if len(c) <= 3000 else c[:1500] + "\n[TRUNCATED]"  # long dictation kept (head only), not dropped


def tool_labels(msg: dict) -> tuple[list, list]:
    skills, agents = [], []
    c = msg.get("message", {}).get("content")
    for b in c if isinstance(c, list) else []:
        if isinstance(b, dict) and b.get("type") == "tool_use":
            inp = b.get("input", {}) or {}
            if b.get("name") == "Skill" and inp.get("skill"):
                skills.append(str(inp["skill"]))
            if b.get("name") in ("Agent", "Task") and inp.get("subagent_type"):
                agents.append(str(inp["subagent_type"]))
    return skills, agents


def walk(path: str) -> Iterator[dict]:
    cur: Optional[dict] = None
    n = 0  # human prompts seen so far in this session file
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("isSidechain"):
            continue
        if m.get("type") == "user":
            t = human_text(m)
            if cur:
                yield cur
            cur = {"prompt": t, "skills": [], "agents": [], "ts": m.get("timestamp", ""), "project": os.path.basename(os.path.dirname(path)),
                   "truncated": t.endswith("[TRUNCATED]"), "n_prior_prompts_in_session": n} if t else None
            n += 1 if t else 0
        elif m.get("type") == "assistant" and cur:
            s, a = tool_labels(m)
            cur["skills"] += s
            cur["agents"] += a
    if cur:
        yield cur


def main(out_dir: str = "eval/heldout") -> None:
    os.makedirs(out_dir, exist_ok=True)
    seen, rows = set(), []
    for f in sorted(glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))):
        for r in walk(f):
            key = re.sub(r"\W+", " ", r["prompt"].lower())
            if key in seen:
                continue
            seen.add(key)
            rows.append(r)
    rows.sort(key=lambda r: r["ts"])
    cut = int(len(rows) * 0.8)  # time split: the LAST 20% is the frozen test set, never used for tuning
    for name, part in (("dev", rows[:cut]), ("test", rows[cut:])):
        with open(os.path.join(out_dir, f"{name}.jsonl"), "w") as fh:
            for i, r in enumerate(part):
                fh.write(json.dumps({"id": f"{name}-{i}", **r}) + "\n")
    lab = [r for r in rows if r["skills"] or r["agents"]]
    print(json.dumps({"prompts": len(rows), "dev": cut, "test": len(rows) - cut, "labelled_skill_or_agent": len(lab),
                      "labelled_in_test": sum(1 for r in rows[cut:] if r["skills"] or r["agents"]),
                      "distinct_labels": len({x for r in lab for x in r["skills"] + r["agents"]}),
                      "first": rows[0]["ts"][:10] if rows else "", "last": rows[-1]["ts"][:10] if rows else ""}))


if __name__ == "__main__":
    main(*sys.argv[1:])
