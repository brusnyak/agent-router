"""Gate for library bundles: a bundle = persona + command + hook + loop + gate + acceptance in ONE row, so a task class gets the
whole engineered setup. Exit 0 only if every file under the given paths is a valid bundle. Deterministic, no LLM."""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backbone.evidence import missing_paths  # noqa: E402
from backbone.library import parse_markdown  # noqa: E402

REQUIRED = ("## Persona", "## Command", "## Hook", "## Loop", "## Gate", "## Acceptance", "## Failure modes")
FM_KEYS = ("name", "description", "task_class", "triggers")


def check(path: str) -> list:
    errs = []
    text = open(path, encoding="utf-8").read()
    meta, body = parse_markdown(text)
    for k in FM_KEYS:
        if not meta.get(k):
            errs.append(f"front matter missing '{k}'")
    if meta.get("task_class") and meta["task_class"] not in ("classify", "code_edit", "multi_file", "review", "research", "draft", "plan", "browse", "other"):
        errs.append(f"task_class '{meta['task_class']}' not one of the router task classes")
    for h in REQUIRED:
        m = re.search(re.escape(h) + r"\s*\n(.*?)(?=\n## |\Z)", body, re.S)
        if not m or len(m.group(1).strip()) < 60:
            errs.append(f"section '{h}' missing or under 60 chars")
    if not 1500 <= len(text) <= 9000:
        errs.append(f"length {len(text)} outside 1500..9000 chars")
    if re.search(r"/Users/[a-z]|yegor|brusnyak", text):
        errs.append("personal path or handle")
    fake = missing_paths(text, [os.getcwd()])
    if fake:
        errs.append(f"cites files that do not exist: {fake[:3]}")
    if "TODO" in text or "lorem" in text.lower():
        errs.append("placeholder text")
    return errs


def main(paths: list) -> int:
    files = []
    for p in paths:
        files += [os.path.join(d, f) for d, _, fs in os.walk(p) for f in fs if f.endswith(".md")] if os.path.isdir(p) else [p]
    if not files:
        print("no bundle files found")
        return 1
    bad = 0
    for f in sorted(files):
        e = check(f)
        print(("FAIL " if e else "ok   ") + f + ("".join("\n     - " + x for x in e)))
        bad += bool(e)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["library/bundles"]))
