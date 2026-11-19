"""Static audit of skill folders: risk flags, duplicates, cold skills. Stdlib only."""
import os
import re

WEIGHTS = {
    "exec-shell": 40,
    "exfil-network": 50,
    "secrets-read": 30,
    "prompt-injection": 40,
    "hidden-unicode": 30,
    "obfuscation": 25,
    "destructive": 30,
}

FRONT = re.compile(r"^---\s*$")
NAME_RE = re.compile(r"^\s*name:\s*(.+?)\s*$", re.I)
DESC_RE = re.compile(r"^\s*description:\s*(.+?)\s*$", re.I)

EXEC_SHELL = re.compile(
    r"\b(?:curl|wget)\b[^|\n]*\|\s*(?:sh|bash|zsh)\b"
    r"|os\.system\s*\("
    r"|\bsubprocess\b.*\bshell\s*=\s*True"
    r"|\beval\s*\("
    r"|\bexec\s*\(",
    re.I | re.S,
)
EXFIL_NET = re.compile(r"\b(?:curl|wget|requests\.post)\b|\bPOST\b", re.I)
EXFIL_URL = re.compile(r"https?://", re.I)
SECRET_SRC = re.compile(
    r"~/\.ssh|~/\.aws|~/\.env|\.env|id_rsa|credentials|token|api_key|keychain|\.netrc",
    re.I,
)
SECRETS_READ = re.compile(
    r"~/\.ssh|~/\.aws|~/\.env|id_rsa|credentials|keychain|\.netrc", re.I
)
PROMPT_INJECTION = re.compile(
    r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions"
    r"|disregard\s+(?:all\s+)?(?:previous|prior)"
    r"|do\s+not\s+tell\s+the\s+user"
    r"|override\s+the\s+system\s+prompt",
    re.I,
)
HIDDEN_UNICODE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
OBFUSCATION = re.compile(r"[A-Za-z0-9+/=]{200,}")
DESTRUCTIVE = re.compile(
    r"rm\s+-rf\s+/|rm\s+-rf\s+~|chmod\s+777|git\s+push\s+--force", re.I
)


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_frontmatter(text):
    name, desc = None, None
    lines = text.splitlines()
    if lines and FRONT.match(lines[0]):
        end = None
        for i in range(1, len(lines)):
            if FRONT.match(lines[i]):
                end = i
                break
        if end is not None:
            for line in lines[1:end]:
                m = NAME_RE.match(line)
                if m:
                    name = _unquote(m.group(1))
                    continue
                m = DESC_RE.match(line)
                if m:
                    desc = _unquote(m.group(1))
    return name, desc


def _read_texts(skill_dir):
    texts = {}
    for root, _dirs, files in os.walk(skill_dir):
        for fn in files:
            path = os.path.join(root, fn)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    texts[path] = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
    return texts


def _has_exfil(text):
    return bool(
        EXFIL_NET.search(text) and EXFIL_URL.search(text) and SECRET_SRC.search(text)
    )


def audit(skill_dirs, usage=None):
    usage = usage or {}
    seen = {}
    rows = []
    for skill_dir in skill_dirs:
        if not os.path.isdir(skill_dir):
            continue
        subs = sorted(
            d
            for d in os.listdir(skill_dir)
            if os.path.isdir(os.path.join(skill_dir, d))
        )
        for sub in subs:
            skill_path = os.path.join(skill_dir, sub)
            texts = _read_texts(skill_path)
            skill_text = "\n".join(texts.values())
            md_text = texts.get(os.path.join(skill_path, "SKILL.md"), "")
            name, desc = _parse_frontmatter(md_text)
            if not name:
                name = sub
            flags = set()
            if EXEC_SHELL.search(skill_text):
                flags.add("exec-shell")
            if any(_has_exfil(t) for t in texts.values()):
                flags.add("exfil-network")
            if SECRETS_READ.search(skill_text):
                flags.add("secrets-read")
            if PROMPT_INJECTION.search(skill_text):
                flags.add("prompt-injection")
            if HIDDEN_UNICODE.search(skill_text):
                flags.add("hidden-unicode")
            if OBFUSCATION.search(skill_text):
                flags.add("obfuscation")
            if DESTRUCTIVE.search(skill_text):
                flags.add("destructive")
            key = name.lower()
            duplicate_of = seen.get(key)
            if duplicate_of is None:
                seen[key] = skill_path
            rows.append(
                {
                    "name": name,
                    "path": skill_path,
                    "risk": min(100, sum(WEIGHTS[f] for f in flags)),
                    "flags": sorted(flags),
                    "duplicate_of": duplicate_of,
                    "cold": usage.get(name, 0) == 0,
                    "desc_chars": len(desc or ""),
                }
            )
    return rows


def render(rows):
    lines = []
    for r in sorted(rows, key=lambda r: (-r["risk"], r["name"])):
        marks = []
        if r["cold"]:
            marks.append("cold")
        if r["duplicate_of"]:
            marks.append("duplicate")
        line = (
            f"{r['risk']:3d} {r['name']} "
            f"flags=[{','.join(r['flags'])}] "
            f"{' '.join(marks)}"
        )
        lines.append(line.strip())
    return "\n".join(lines)


DEFAULT_DIRS = ["~/.claude/skills", "~/.config/opencode/skills", "~/.agents/skills", "~/.codex/skills", "~/.agent-skills/core"]
RECEIPTS = "~/.agent-router/hook-shadow.jsonl"


def usage_from_receipts(path=RECEIPTS):
    """Skill names the picker surfaced for a prompt (hook receipts: would_surface). Read-only; absent file = no usage known."""
    import json
    counts = {}
    try:
        for line in open(os.path.expanduser(path), encoding="utf-8"):
            for name in (json.loads(line).get("would_surface") or []):
                counts[name] = counts.get(name, 0) + 1
    except (OSError, ValueError):
        pass
    return counts


def summarize(rows):
    flagged = [r for r in rows if r["flags"]]
    by_flag = {}
    for r in rows:
        for f in r["flags"]:
            by_flag[f] = by_flag.get(f, 0) + 1
    return {"skills": len(rows), "flagged": len(flagged), "risk_ge_40": sum(r["risk"] >= 40 for r in rows),
            "duplicates": sum(1 for r in rows if r["duplicate_of"]), "cold": sum(r["cold"] for r in rows),
            "desc_chars_total": sum(r["desc_chars"] for r in rows), "by_flag": dict(sorted(by_flag.items()))}


def main(argv=None):
    """Read-only. python3 -m backbone.skill_audit [DIR ...] [--json]  (default: the agent skill folders found on this machine)."""
    import json
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args
    dirs = [os.path.expanduser(a) for a in args if not a.startswith("--")] or [os.path.expanduser(d) for d in DEFAULT_DIRS]
    dirs = [d for d in dirs if os.path.isdir(d)]
    rows = audit(dirs, usage=usage_from_receipts())
    summary = summarize(rows)
    if as_json:
        print(json.dumps({"dirs": dirs, "summary": summary, "rows": rows}, indent=1, default=str))
    else:
        print("dirs:", ", ".join(d.replace(os.path.expanduser("~"), "~") for d in dirs))
        print(json.dumps(summary))
        print(render([r for r in rows if r["risk"] > 0][:25]) or "no risky skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
