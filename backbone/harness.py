"""Offline, stdlib-only shared rules installer. Never writes without --apply.

Config accepts JSON or a deliberately small YAML subset: block maps/lists,
scalar inline lists, quoted/plain scalars, booleans and comments. YAML tags,
anchors and multiline scalars are not supported; reject rather than guess.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime
import difflib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
BEGIN = "<!-- BEGIN backbone rules -->"
END = "<!-- END backbone rules -->"


def _scalar(value):
    value = value.strip()
    if not value:
        return None
    if value.startswith(("'", '"')):
        result = ast.literal_eval(value)
        if not isinstance(result, str):
            raise ValueError("expected quoted string")
        return result
    if value.startswith("[") and value.endswith("]"):
        return [_scalar(v) for v in re.split(
            r''',(?=(?:[^'"\[\]]|'[^']*'|"[^"]*")*$)''', value[1:-1]) if v.strip()]
    if value in ("true", "false"):
        return value == "true"
    if value in ("null", "~"):
        return None
    if value.startswith(("{", "[", "&", "*", "!", "|", ">")):
        raise ValueError("unsupported YAML scalar; use JSON for complex values")
    return value


def load_yaml(path):
    """Read the documented subset without requiring PyYAML or executing tags."""
    source = Path(path).read_text(encoding="utf-8")
    uncommented = "\n".join(l for l in source.splitlines() if not l.lstrip().startswith("#"))
    try:
        return json.loads(uncommented)
    except json.JSONDecodeError:
        pass
    lines = []
    for line in source.splitlines():
        # Strip comments only outside quotes.
        line = re.sub(r'''\s+#(?=(?:[^'"]|'[^']*'|"[^"]*")*$).*''', "", line).rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "\t" in line[:len(line) - len(line.lstrip())]:
            raise ValueError(f"{path}: tabs in indentation")
        lines.append((len(line) - len(line.lstrip()), line.lstrip()))

    def parse(index, indent):
        sequence = lines[index][1].startswith("- ") or lines[index][1] == "-"
        result = [] if sequence else {}
        while index < len(lines) and lines[index][0] == indent:
            text = lines[index][1]
            is_item = text == "-" or text.startswith("- ")
            if is_item != sequence:
                break
            index += 1
            if sequence:
                text = text[1:].strip()
                if re.match(r"^[\w-]+:\s|^[\w-]+:$", text):
                    # Normalize '- id: x' into a mapping at the child indent.
                    lines.insert(index, (indent + 2, text))
                    item, index = parse(index, indent + 2)
                elif text:
                    item = _scalar(text)
                elif index < len(lines) and lines[index][0] > indent:
                    item, index = parse(index, lines[index][0])
                else:
                    item = None
                result.append(item)
            else:
                key, sep, value = text.partition(":")
                if not sep or not re.fullmatch(r"[\w.-]+", key):
                    raise ValueError(f"{path}: unsupported mapping: {text}")
                if key in result:
                    raise ValueError(f"{path}: duplicate key {key}")
                if value.strip():
                    item = _scalar(value)
                elif index < len(lines) and (lines[index][0] > indent or
                        (lines[index][0] == indent and lines[index][1].startswith("-"))):
                    item, index = parse(index, lines[index][0])
                else:
                    item = None
                result[key] = item
        return result, index

    if not lines:
        return {}
    result, consumed = parse(0, lines[0][0])
    if consumed != len(lines):
        raise ValueError(f"{path}: unsupported YAML indentation")
    return result


def expand(value, base=None):
    path = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return (base / path if base is not None and not path.is_absolute() else path).absolute()


def config(root=None):
    root = Path(root) if root is not None else ROOT
    defaults = load_yaml(root / "config/harness.yaml")
    owner_home = expand(os.environ.get("AGENT_ROUTER_HOME", "~/.agent-router"))
    owner_path = owner_home / "harness.yaml"
    owner = load_yaml(owner_path) if owner_path.exists() else {}
    if not isinstance(owner, dict):
        raise ValueError("owner harness.yaml must be a mapping")
    includes = owner.get("include", [])
    disabled = owner.get("disable", [])
    overrides = owner.get("rules_path", {})
    if (not isinstance(includes, list) or not all(isinstance(x, str) for x in includes)
            or not isinstance(disabled, list) or not all(isinstance(x, str) for x in disabled)
            or not isinstance(overrides, dict)
            or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in overrides.items())):
        raise ValueError("expected include/disable lists and rules_path mapping of strings")
    adapters = defaults["adapters"]
    ids = {a["id"] for a in adapters}
    if set(disabled) - ids or set(overrides) - ids:
        raise ValueError("unknown harness id in owner overrides")
    return [dict(a, rules_path=overrides.get(a["id"], a["rules_path"]))
            for a in adapters if a["id"] not in disabled], [expand(p, owner_home) for p in includes]


def detected(adapter):
    detection = adapter["detect"]
    binary = detection.get("binary")
    directory = detection.get("config_dir")
    return bool((binary and shutil.which(binary)) or (directory and expand(directory).is_dir()))


def render_rules(root=None, includes=()):
    root = Path(root) if root is not None else ROOT
    agents = load_yaml(root / "config/agents.yaml").get("agents", [])
    workers = "\n".join("- " + a["id"] + (": " + str(a.get("note") or a.get("notes"))
                          if a.get("note") or a.get("notes") else "") for a in agents)
    template = (root / "config/rules/core.md").read_text(encoding="utf-8")
    replacements = {
        "workers": workers,
        "retrieval_cmd": 'backbone retrieval search "<topic>" -k 5',
        "router_cmd": "backbone run --worker <w> --gate '<cmd>' '<task>'",
    }
    rendered = re.sub(r"\{\{(workers|retrieval_cmd|router_cmd)\}\}",
                      lambda m: replacements[m[1]], template).rstrip()
    for path in includes:
        rendered += "\n\n" + path.read_text(encoding="utf-8").rstrip()
    if BEGIN in rendered or END in rendered:
        raise ValueError("rules content must not contain backbone markers")
    return BEGIN + "\n" + rendered + "\n" + END


def update_block(original, block):
    """Preserve all characters outside the managed block, including CRLF."""
    if BEGIN not in original and END not in original:
        return original + ("\n" if original and not original.endswith("\n") else "") + block + "\n"
    if original.count(BEGIN) != 1 or original.count(END) != 1:
        raise ValueError("unbalanced or duplicate backbone rules markers")
    start, end = original.index(BEGIN), original.index(END)
    if end < start:
        raise ValueError("backbone rules END precedes BEGIN")
    return original[:start] + block + original[end + len(END):]


def _read(path):
    return path.read_bytes().decode("utf-8") if path.exists() else None


def plan(root=None, only=None):
    root = Path(root) if root is not None else ROOT
    adapters, includes = config(root)
    known = {a["id"] for a in load_yaml(root / "config/harness.yaml")["adapters"]}
    if only is not None and set(only) - known:
        raise ValueError("unknown harness id: " + ",".join(sorted(set(only) - known)))
    block = render_rules(root, includes)
    result, targets = [], set()
    for adapter in adapters:
        if (only is not None and adapter["id"] not in only) or not detected(adapter):
            continue
        if adapter["format"] != "markdown block":
            raise ValueError("unsupported harness format")
        path = expand(adapter["rules_path"])
        old = _read(path)
        files = [(path, old, update_block(old or "", block))]
        for extra in adapter.get("extras", []):
            target = expand(extra["path"])
            files.append((target, _read(target), (root / extra["source"]).read_text(encoding="utf-8")))
        for target, _, _ in files:
            resolved = target.resolve()
            if resolved in targets:
                raise ValueError(f"multiple harness files target {target}")
            targets.add(resolved)
        state = ("missing" if any(old is None for _, old, _ in files) else
                 "drift" if any(old != new for _, old, new in files) else "in-sync")
        result.append((adapter, path, state, files))
    return result


def _write(path, old, new):
    # Resolve symlinks so atomic replacement preserves the original link.
    destination = path.resolve()
    if _read(path) != old:
        raise ValueError(f"file changed since planning: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if old is not None:
        today = datetime.now().strftime("%Y%m%d")
        if not list(path.parent.glob(path.name + "." + today + "*.bak")):
            backup = path.with_name(path.name + "." + datetime.now().strftime("%Y%m%dT%H%M%S%f") + ".bak")
            with backup.open("xb") as stream:
                stream.write(old.encode("utf-8"))
            shutil.copymode(destination, backup)
    fd, temporary = tempfile.mkstemp(prefix=".backbone-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(new.encode("utf-8"))
        if destination.exists():
            shutil.copymode(destination, temporary)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="backbone harness")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="show detected harnesses and drift")
    sync = sub.add_parser("sync", help="preview diffs; write only with --apply")
    sync.add_argument("--apply", action="store_true")
    sync.add_argument("--only", help="comma-separated harness ids")
    sub.add_parser("check", help="exit 2 if any detected harness is out of sync")
    args = parser.parse_args(argv)
    try:
        only = [s.strip() for s in args.only.split(",")] if getattr(args, "only", None) else None
        planned = plan(only=only)  # Validate every target before writing any file.
        for adapter, path, state, files in planned:
            print(f"{adapter['id']} {path} verified={str(adapter['verified']).lower()} {state}")
            if args.command == "sync":
                for target, old, new in files:
                    if old == new:
                        continue
                    diff_lines = difflib.unified_diff(
                        (old or "").splitlines(keepends=True), new.splitlines(keepends=True),
                        fromfile=str(target), tofile=str(target))
                    diff = "".join(line if line.endswith("\n") else
                                   line + "\n\\ No newline at end of file\n" for line in diff_lines)
                    print(diff, end="" if diff.endswith("\n") else "\n")
                    if args.apply:
                        _write(target, old, new)
        if args.command == "check" and any(state != "in-sync" for _, _, state, _ in planned):
            return 2
        return 0
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as error:
        print(f"harness: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
