"""Pluggable retrieval; stdlib only. Config supports JSON and a small YAML subset.

YAML: indented mappings/lists, quoted/plain scalars and JSON inline values.
No tags, aliases, multiline scalars or implicit dates. Providers fail closed.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from itertools import islice
import json
import math
import os
from pathlib import Path
import re
import selectors
import shlex
import shutil
import subprocess
import time
from typing import Protocol
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path):
    """Read the documented config subset without requiring PyYAML."""
    text = Path(path).expanduser().read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except ValueError:
        pass
    rows = []
    for raw in text.splitlines():
        # Preserve # inside quotes (including URL fragments and shell arguments).
        quoted = None
        escaped = False
        for i, char in enumerate(raw):
            if escaped:
                escaped = False
            elif char == "\\" and quoted == '"':
                escaped = True
            elif char == quoted:
                quoted = None
            elif char in "\"'" and quoted is None:
                quoted = char
            elif char == "#" and quoted is None and (i == 0 or raw[i - 1].isspace()):
                raw = raw[:i]
                break
        if raw.strip() and raw.strip() not in ("---", "..."):
            if "\t" in raw[:len(raw) - len(raw.lstrip())]:
                raise ValueError("YAML indentation must use spaces")
            rows.append((len(raw) - len(raw.lstrip()), raw.strip()))

    def scalar(value):
        if value.startswith(('"', "'")):
            if value.startswith("'"):
                if not value.endswith("'"):
                    raise ValueError("unterminated YAML string")
                return value[1:-1].replace("''", "'")
            return json.loads(value)
        if value.lower() in ("true", "false", "null", "~"):
            return {"true": True, "false": False, "null": None, "~": None}[value.lower()]
        if value.startswith(("[", "{")):
            try:
                return json.loads(value)
            except ValueError:
                try:
                    return ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    if value.startswith("[") and value.endswith("]") and "{" not in value:
                        # YAML flow list of plain words: [a, b, c]
                        return [item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()]
                    raise
        if value.startswith(("|", ">", "&", "*", "!")):
            raise ValueError("unsupported YAML scalar; use a quoted string")
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return value

    def block(pos, indent):
        sequence = rows[pos][1] == "-" or rows[pos][1].startswith("- ")
        result = [] if sequence else {}
        while pos < len(rows) and rows[pos][0] == indent:
            value = rows[pos][1]
            if sequence:
                if not (value == "-" or value.startswith("- ")):
                    raise ValueError("mixed YAML sequence and mapping")
                value = value[1:].strip()
                if not value:
                    item, pos = block(pos + 1, rows[pos + 1][0])
                    result.append(item)
                    continue
                if re.match(r"[^:]+:\s|[^:]+:$", value):
                    # Treat '- key: value' as a mapping at the dash's content indent.
                    rows[pos] = (indent + 2, value)
                    item, pos = block(pos, indent + 2)
                    result.append(item)
                    continue
                result.append(scalar(value))
                pos += 1
            else:
                key, sep, value = value.partition(":")
                if not sep:
                    raise ValueError("expected YAML mapping")
                pos += 1
                if value.strip():
                    result[key] = scalar(value.strip())
                elif pos < len(rows) and rows[pos][0] > indent:
                    result[key], pos = block(pos, rows[pos][0])
                else:
                    result[key] = None
        return result, pos

    if not rows:
        return {}
    result, pos = block(0, rows[0][0])
    if pos != len(rows):
        raise ValueError("invalid YAML indentation")
    return result


@dataclass
class Hit:
    id: str
    title: str
    text: str
    score: float
    source: str


class Provider(Protocol):
    name: str

    def detect(self) -> bool: ...
    def search(self, query: str, k: int) -> list[Hit]: ...
    def doctor(self) -> dict: ...


def _hits(data):
    if isinstance(data, dict):
        data = data.get("hits", data.get("results", []))
    if not isinstance(data, list):
        raise ValueError("expected a JSON list of hits")
    out = []
    for row in data:
        source = str(row.get("source") or row.get("path") or row.get("id") or "")
        ident = str(row.get("id") or source)
        score = float(row.get("score", 0))
        if not ident or not math.isfinite(score):
            raise ValueError("hit needs an id/path and a finite score")
        out.append(Hit(ident, str(row.get("title", row.get("name", ident))),
                       str(row.get("text", row.get("description", ""))), score, source))
    return out


def _lines(text):
    out = []
    for line in text.splitlines():
        match = re.match(r"^\[([+-]?[\d.eE]+)\]\s+(\S+)\s+—\s+(.*?)(?:\s+\(area=.*)?$", line)
        if match:
            score, path, title = match.groups()
            out.extend(_hits([dict(id=path, title=title.strip(), score=score, source=path)]))
    if text.strip() and not out:
        raise ValueError("no recognized result lines")
    return out


def _argv(command, query="", k=5):
    # Split BEFORE substitution: queries cannot inject flags, shell syntax or argv.
    parts = shlex.split(command) if isinstance(command, str) else list(command)
    return [re.sub(r"\{([qk])\}", lambda m: query if m[1] == "q" else str(k),
                   os.path.expanduser(str(p))) for p in parts]


class BaseProvider:
    def __init__(self, name, params=None):
        self.name, self.params = name, params or {}
        self.status = {"ok": False, "latency_s": 0.0, "note": "not checked"}

    def _attempt(self, fn, fallback):
        start = time.monotonic()
        try:
            result = fn()
            self.status = dict(ok=True, latency_s=time.monotonic() - start, note="ok")
            return result
        except Exception as exc:
            self.status = dict(ok=False, latency_s=time.monotonic() - start,
                               note=f"{type(exc).__name__}: {exc}")
            return fallback

    def detect(self):
        start = time.monotonic()
        try:
            if self._detect():
                return True
            raise RuntimeError("provider not detected")
        except Exception as exc:
            self.status = dict(ok=False, latency_s=time.monotonic() - start,
                               note=f"{type(exc).__name__}: {exc}")
            return False

    def _detect(self):
        return True

    def search(self, query, k=5):
        return self._attempt(lambda: self._search(query, max(0, int(k))) if int(k) > 0 else [], [])

    def doctor(self):
        # Keep the most recent failure visible; a later search can recover it.
        if self.status["note"] == "not checked":
            self._attempt(self._probe, None)
        return dict(self.status)

    def _probe(self):
        if not self._detect():
            raise RuntimeError("provider not detected")


class CmdProvider(BaseProvider):
    def _detect(self):
        args = _argv(self.params["command"])
        return bool(args and shutil.which(args[0]))

    def _search(self, query, k):
        result = subprocess.run(_argv(self.params["command"], query, k), shell=False,
                                capture_output=True, text=True, check=True,
                                timeout=float(self.params.get("timeout_s", 10)))
        return _lines(result.stdout)[:k]

    def _probe(self):
        self._search(self.params.get("doctor_query", "retrieval"), 1)


class BuiltinProvider(BaseProvider):
    def __init__(self, name="builtin", params=None, rag=None):
        super().__init__(name, params)
        self.rag = rag

    def _detect(self):
        return self.rag is not None or Path(self.params.get("db", "~/.agent-router/data/backbone.db")).expanduser().is_file()

    def _search(self, query, k):
        if self.rag is not None:
            rows = self.rag.search(query, k=k)
        else:
            self._probe()
            import sqlite3
            from .keys import KeyPool
            from .rag import Rag
            path = Path(self.params.get("db", "~/.agent-router/data/backbone.db")).expanduser().resolve()
            con = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=1)
            con.row_factory = sqlite3.Row
            try:
                # Empty pool: local FTS retrieval, no credential lookup or network.
                rows = Rag(con, KeyPool([], env={}), {}).search(query, k=k)
            finally:
                con.close()
        return _hits([dict(row, source=(row.get("meta") or {}).get("path") or row.get("source") or row["id"]) for row in rows])[:k]


class HttpProvider(BaseProvider):
    def _detect(self):
        return self.params["url"].startswith(("http://", "https://"))

    def _search(self, query, k):
        if not self._detect():
            raise ValueError("HTTP provider requires an http(s) URL")
        url = self.params["url"].replace("{q}", quote(query, safe="")).replace("{k}", str(k))
        with urlopen(url, timeout=float(self.params.get("timeout_s", 10))) as response:
            return _hits(json.load(response))[:k]

    def _probe(self):
        self._search(self.params.get("doctor_query", "retrieval"), 1)


class McpStdioProvider(CmdProvider):
    def _session(self, query=None, k=5):
        # Legacy MCP lifecycle, as requested: initialize -> initialized -> tools.
        # https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle
        proc = subprocess.Popen(_argv(self.params["command"]), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False)
        deadline = time.monotonic() + float(self.params.get("timeout_s", 10))
        buffer = b""
        counter = 0
        sel = selectors.DefaultSelector()
        try:
            sel.register(proc.stdout, selectors.EVENT_READ)

            def send(message):
                proc.stdin.write((json.dumps(dict(jsonrpc="2.0", **message)) + "\n").encode())
                proc.stdin.flush()

            def call(method, params):
                nonlocal buffer, counter
                counter += 1
                ident = counter
                send(dict(id=ident, method=method, params=params))
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("MCP session timed out")
                    if b"\n" not in buffer:
                        if not sel.select(remaining):
                            raise TimeoutError("MCP response timed out")
                        chunk = os.read(proc.stdout.fileno(), 65536)
                        if not chunk:
                            raise RuntimeError("MCP server closed stdout")
                        buffer += chunk
                        continue
                    line, buffer = buffer.split(b"\n", 1)
                    message = json.loads(line)
                    if message.get("id") != ident or "method" in message:
                        continue
                    if "error" in message:
                        raise RuntimeError(f"MCP error: {message['error']}")
                    return message["result"]

            version = "2025-11-25"
            initialized = call("initialize", dict(protocolVersion=version, capabilities={},
                                                 clientInfo=dict(name="agent-router-retrieval", version="1.0")))
            if initialized.get("protocolVersion") not in ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"):
                raise ValueError("unsupported MCP protocol version")
            send(dict(method="notifications/initialized"))
            if query is None:
                tools = call("tools/list", {})
                if not any(t["name"] == self.params["tool"] for t in tools.get("tools", [])):
                    raise ValueError("configured MCP tool is unavailable")
                return []
            arguments = dict(self.params.get("arguments", {}))
            arguments[self.params.get("query_arg", "query")] = query
            arguments[self.params.get("k_arg", "k")] = k
            result = call("tools/call", dict(name=self.params["tool"], arguments=arguments))
            if result.get("isError"):
                raise RuntimeError("MCP tool reported an error")
            if "structuredContent" in result:
                return _hits(result["structuredContent"])[:k]
            hits = []
            for item in result.get("content", []):
                if item.get("type") == "text":
                    text = item["text"]
                    try:
                        data = json.loads(text)
                    except ValueError:
                        hits.extend(_lines(text))
                    else:
                        hits.extend(_hits(data))
            return hits[:k]
        finally:
            sel.close()
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            proc.wait()
            proc.stdin.close()
            proc.stdout.close()

    def _probe(self):
        self._session()

    def _search(self, query, k):
        return self._session(query, k)


class Registry:
    def __init__(self, config_path=None, *, providers=None, projects_path=None):
        self.config_path = Path(config_path or ROOT / "config/retrieval.yaml").expanduser()
        self.projects_path = Path(projects_path or self.config_path.with_name("projects.yaml")).expanduser()
        self.providers = list(providers) if providers is not None else []
        self.notes = []
        if providers is not None:
            return
        types = dict(cmd=CmdProvider, builtin=BuiltinProvider, mcp_stdio=McpStdioProvider, http=HttpProvider)
        try:
            config = load_yaml(self.config_path)
            for i, entry in enumerate(config.get("providers", [])):
                if entry.get("enabled", False) is not True:
                    continue
                try:
                    self.providers.append(types[entry["type"]](entry.get("name", f"{entry['type']}-{i}"), entry.get("params", {})))
                except Exception as exc:
                    self.notes.append(f"provider {i}: {exc}")
        except Exception as exc:
            self.notes.append(f"config: {type(exc).__name__}: {exc}")

    def doctor(self):
        return {"providers": {p.name: p.doctor() for p in self.providers}, "notes": self.notes}

    def search_all(self, query, k=5):
        fused, hits = {}, {}
        for provider in self.providers:
            seen = set()
            try:
                ranking = provider.search(query, max(0, k))
                for rank, hit in enumerate(ranking, 1):
                    if hit.id in seen:
                        continue
                    seen.add(hit.id)
                    hits.setdefault(hit.id, hit)
                    fused[hit.id] = fused.get(hit.id, 0.0) + 1.0 / (60 + rank)
            except Exception as exc:
                self.notes.append(f"{provider.name}: {type(exc).__name__}: {exc}")
        return [replace(hits[i], score=score) for i, score in sorted(fused.items(), key=lambda pair: -pair[1])[:max(0, k)]]

    def resolve_project(self, task):
        """Pick the project whose `keywords:` (projects.yaml) match the task best; "" when none match."""
        try:
            projects = load_yaml(self.projects_path).get("projects", [])
        except Exception:
            return ""
        words = set(re.findall(r"[a-z0-9][a-z0-9_-]+", str(task).lower()))
        best, best_hits = "", 0
        for spec in projects:
            keys = {str(k).lower() for k in (spec.get("keywords") or [])} | {str(spec.get("id", "")).lower()}
            hits = len(words & keys)
            if hits > best_hits:
                best, best_hits = str(spec.get("id", "")), hits
        return best

    def context_pack(self, task, project=None):
        header = f"checked_at: {datetime.now(timezone.utc).isoformat()}\n"
        items = []
        if project == "auto":
            project = self.resolve_project(task)
        if project:
            try:
                config = load_yaml(self.projects_path)
                projects = config.get("projects", [])
                spec = next((p for p in projects if p.get("id") == project), {})
                base = Path(spec.get("path", str(self.projects_path.parent))).expanduser()
                if not base.is_absolute():
                    base = self.projects_path.parent / base
                for anchor in spec.get("anchors") or []:
                    path = Path(anchor).expanduser()
                    if not path.is_absolute():
                        path = base / path
                    try:
                        with path.open(encoding="utf-8", errors="replace") as fh:
                            body = "".join(islice(fh, 40))
                    except OSError as exc:
                        body = f"unavailable: {exc.strerror}"
                    items.append((f"\nsource: {path}\n", body))
            except Exception as exc:
                self.notes.append(f"anchors: {type(exc).__name__}: {exc}")
        for hit in self.search_all(task, 5):
            items.append((f"\nsource: {hit.source or hit.id}\n", f"{hit.title}\n{hit.text}\n"))
        # Reserve provenance for every item before distributing the text budget.
        remaining = max(0, 6000 - len(header) - sum(len(source) for source, _ in items))
        parts = [header]
        for index, (source, body) in enumerate(items):
            budget = min(len(body), remaining // (len(items) - index))
            parts.append(source + body[:budget])
            remaining -= budget
        return "".join(parts)[:6000]

    @staticmethod
    def discover():
        return discover()


def discover():
    """Proposals only: never modify config or silently activate a provider."""
    entries = []
    script = Path.home() / "memory-vault/scripts/vector_memory/query.py"
    if script.is_file():
        entries.append(dict(name="vault", type="cmd", enabled=False, params=dict(
            command=['python3', str(script), '{q}', '--top-k', '{k}'])))
    for binary in ("qmd", "basic-memory"):
        if shutil.which(binary):
            entries.append(dict(name=binary, type="cmd", enabled=False,
                                params=dict(command=[binary, 'search', '{q}'])))
    return entries


def search_all(query, k=5):
    return Registry().search_all(query, k)


def context_pack(task, project=None):
    return Registry().context_pack(task, project)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="backbone retrieval")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("-k", type=int, default=5)
    pack = sub.add_parser("pack")
    pack.add_argument("task")
    pack.add_argument("--project")
    sub.add_parser("discover")
    args = parser.parse_args(argv)
    registry = Registry()
    if args.command == "pack":
        print(registry.context_pack(args.task, args.project))
        return
    result = (registry.doctor() if args.command == "doctor" else discover() if args.command == "discover"
              else [asdict(h) for h in registry.search_all(args.query, args.k)])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0
