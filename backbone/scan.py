"""Self-scan install: find agent clients on this machine by what they contain, not by a hard-coded list,
then wire the shared rules block and, where the client has a Claude-style hooks block, the router hooks.

Never writes without --apply. Managed hook commands carry BACKBONE_MANAGED=1 so uninstall is exact.
A hand-installed hook that runs backbone.hook / backbone.enforce is replaced by the managed entry (a .bak is kept)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import harness as h

MARK = "BACKBONE_MANAGED=1"
INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".goosehints")
CLAUDE_EVENTS = {"PreToolUse", "UserPromptSubmit"}   # events the router hooks use; a client without them has another schema
SKIP = {".ssh", ".aws", ".git", ".cache", ".npm", ".docker", ".gnupg", ".Trash", ".local", ".config", ".agent-router"}


def _find(base: Path, names):
    for sub in ("", "agent"):
        for n in names:
            p = base / sub / n
            if p.is_file():
                return p
    return None


def scan(home=None):
    """-> [{id, dir, rules, settings, hooks}] for every dot-dir or ~/.config/* dir that holds an instruction file
    or a settings.json with a hooks mapping."""
    home = Path(home or os.path.expanduser("~"))
    dirs = [p for p in sorted(home.glob(".*")) if p.is_dir() and p.name not in SKIP]
    cfg = home / ".config"
    dirs += [p for p in sorted(cfg.glob("*")) if p.is_dir()] if cfg.is_dir() else []
    found = []
    for d in dirs:
        rules = _find(d, INSTRUCTION_FILES)
        settings = _find(d, ("settings.json",))
        hooks = False
        if settings:
            try:
                m = json.loads(settings.read_text()).get("hooks")
                hooks = isinstance(m, dict) and (not m or bool(set(m) & CLAUDE_EVENTS))   # other event names = other schema, leave alone
            except (OSError, ValueError, AttributeError):
                hooks = False
        if rules or hooks:
            found.append({"id": d.name.lstrip("."), "dir": d, "rules": rules, "settings": settings if hooks else None, "hooks": hooks})
    return found


def hook_entries(root=None, python=None):
    root, python = str(root or h.ROOT), python or sys.executable
    run = lambda mod: f"{MARK} PYTHONPATH={root} {python} -m backbone.{mod}"
    return {"UserPromptSubmit": {"hooks": [{"type": "command", "command": run("hook"), "timeout": 5}]},
            "PreToolUse": {"matcher": "Agent|Task", "hooks": [{"type": "command", "command": run("enforce"), "timeout": 5}]}}


def _commands(entry):
    return [x.get("command", "") for x in entry.get("hooks", [])]


def merge_hooks(text, entries, remove=False):
    """Router-owned: any row that already runs the same router hook (hand-installed or managed) is replaced by
    the managed entry, so the router's own invocation always wins and uninstall removes it cleanly."""
    d = json.loads(text)
    hooks = d.setdefault("hooks", {})
    for event, entry in entries.items():
        mod = _commands(entry)[0].split("-m ")[1]
        names = (mod, mod.replace(".", "/") + ".py")
        rows = [r for r in hooks.get(event, []) if not any(n in c for n in names for c in _commands(r))]
        if not remove:
            rows.append(entry)
        hooks[event] = rows
        if not rows:
            del hooks[event]
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def _strip_block(text):
    if h.BEGIN not in text:
        return text
    a, b = text.index(h.BEGIN), text.index(h.END) + len(h.END)
    return (text[:a].rstrip("\n") + "\n" + text[b:].lstrip("\n")).lstrip("\n")


FULL_RULES = Path(os.path.expanduser("~/.agent-router/rules.md"))


def compact():
    return h.BEGIN + "\n- Router: heavy work via `backbone run --worker <w> --gate '<cmd>' '<task>'`; rules: ~/.agent-router/rules.md\n" + h.END


def plan(home=None, remove=False):
    """-> [(path, old, new)] for every file that would change."""
    block = h.render_rules(h.ROOT, h.config(h.ROOT)[1])
    changes, seen = [], set()
    for c in scan(home):
        if c["rules"] and c["rules"].resolve() not in seen:
            seen.add(c["rules"].resolve())
            old = h._read(c["rules"]) or ""
            # hook-capable clients get the hooks as enforcement, so their (size-budgeted) rules file only gets a pointer
            mine = compact() if c["hooks"] else block
            new = _strip_block(old) if remove else h.update_block(old, mine)
            changes.append((c["rules"], old, new))
        if c["settings"]:
            old = h._read(c["settings"])
            changes.append((c["settings"], old, merge_hooks(old, hook_entries(), remove)))
    return [(p, o, n) for p, o, n in changes if o != n]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="backbone install", description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--scan", action="store_true", help="only list detected clients")
    a = ap.parse_args(argv)
    try:
        if a.scan:
            for c in scan():
                print(f"{c['id']:12} rules={c['rules'] or '-'} hooks={'yes' if c['hooks'] else 'no'}")
            return 0
        changes = plan(remove=a.uninstall)
        for p, o, n in changes:
            print(f"{'would change' if not a.apply else 'writing'} {p}")
            if a.apply:
                h._write(p, o, n)
        if a.apply and not a.uninstall:
            FULL_RULES.parent.mkdir(parents=True, exist_ok=True)
            FULL_RULES.write_text(h.render_rules(h.ROOT, h.config(h.ROOT)[1]) + "\n")
        if a.apply and not a.uninstall:
            import subprocess  # (re)discover every skill/agent/command source on this machine, ingest, rebuild the hook index
            subprocess.run([sys.executable, "-m", "backbone", "library", "sources", "--apply"], cwd=h.ROOT, check=False)
            if not os.path.exists(os.path.expanduser("~/.agent-router/library-index.jsonl")):
                subprocess.run([sys.executable, "-m", "backbone", "library", "export-index"], cwd=h.ROOT, check=False)
        print(f"{len(changes)} file(s) {'changed' if a.apply else 'need change (re-run with --apply)'}")
        return 0
    except (OSError, ValueError, KeyError) as e:
        print(f"install: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
