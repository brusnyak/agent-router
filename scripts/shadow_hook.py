"""Install / uninstall the agent-router SHADOW hook in ~/.claude/settings.json. stdlib only.
  python3 scripts/shadow_hook.py status|install|uninstall [--dry-run] [--settings PATH] [--python PATH]
Shadow = the hook only writes receipts; it injects nothing. Ownership is recorded by the command path
(entries containing OWN_MARK); uninstall removes only those. A timestamped backup is written before any change.
Design borrowed from meta-router's install manifest idea (third_party/meta-router, README 'Installing into a host')."""
import argparse, json, os, shutil, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWN_MARK = "agent-router/"  # every command we add contains this path fragment plus one of the two script names
SCRIPTS = ("backbone/hook.py", "scripts/outcome_hook.py")


def entries(py):
    return {
        "UserPromptSubmit": {"hooks": [{"type": "command", "command": f"{py} {ROOT}/backbone/hook.py"}]},
        "PostToolUse": {"matcher": "Skill|Agent|Task", "hooks": [{"type": "command", "command": f"{py} {ROOT}/scripts/outcome_hook.py"}]},
    }


def owned(cmd):
    return OWN_MARK in cmd and any(s in cmd for s in SCRIPTS)


def strip_ours(hooks):
    n = 0
    for ev, groups in list(hooks.items()):
        keep = []
        for g in groups:
            hs = [h for h in g.get("hooks", []) if not owned(h.get("command", ""))]
            n += len(g.get("hooks", [])) - len(hs)
            if hs:
                keep.append({**g, "hooks": hs})
        if keep:
            hooks[ev] = keep
        else:
            del hooks[ev]
    return n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["status", "install", "uninstall"])
    ap.add_argument("--settings", default=os.path.expanduser("~/.claude/settings.json"))
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    raw = open(a.settings).read()
    cfg = json.loads(raw)
    hooks = cfg.setdefault("hooks", {})
    present = sum(1 for gs in hooks.values() for g in gs for h in g.get("hooks", []) if owned(h.get("command", "")))
    if a.action == "status":
        print(json.dumps({"settings": a.settings, "owned_entries": present, "events": sorted(hooks)}))
        return 0
    if a.action == "install":
        for s in SCRIPTS:
            if not os.path.exists(os.path.join(ROOT, s)):
                print(f"refuse: {s} does not exist yet", file=sys.stderr)
                return 2
        strip_ours(hooks)  # idempotent: replace our old entries, never duplicate, never touch others
        for ev, group in entries(a.python).items():
            hooks.setdefault(ev, []).append(group)
    else:
        removed = strip_ours(hooks)
        if not removed:
            print("nothing to remove")
            return 0
    out = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    if a.dry_run:
        print(f"dry-run: {a.action}; owned entries before={present}; settings unchanged")
        return 0
    bak = f"{a.settings}.bak-{time.strftime('%Y%m%d-%H%M%S')}-shadowhook"
    shutil.copy2(a.settings, bak)
    tmp = a.settings + ".tmp-shadowhook"
    open(tmp, "w").write(out)
    json.loads(open(tmp).read())  # re-parse before swapping in
    os.replace(tmp, a.settings)
    print(f"{a.action}: done; backup {bak}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
