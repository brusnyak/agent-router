#!/usr/bin/env python3
"""NVIDIA NIM chat call (stdlib). Keys read from the process env (set -a; . ~/.env) or the env file; never printed, never in argv.
Rotates to the next key on 429. Library: chat(model, messages, ...) ; CLI: nim_call.py <model> [--system-file F] [--timeout S] < prompt
Public-data tasks only (same class as the free models)."""
import fcntl, json, os, sys, time, urllib.request, urllib.error

URL = "https://integrate.api.nvidia.com/v1/chat/completions"
KEYS = ["NIM_3", "NIM_2", "NIM_1", "NVIDIA_API_KEY_2", "NVIDIA_API_KEY_1"]  # NIM_3 (separate account) first, then NIM_2 (owner 2026-11-04)  # renamed to NIM_* in ~/.env 2026-11-03; old names kept as fallback
ENVFILE = os.path.join(os.path.expanduser("~"), ".env")
# Chain for long jobs (clippings, distill): benchmark 2026-10-27, ~/.config/free-models/nim-bench-20261027.json. DeepSeek/GLM timed out there, so they are not in it.
# Use as model "chain" (or "nim:chain"), or pass a comma-separated list.
CHAIN = ["nvidia/nemotron-3.5-super-vl-120b-a12b", "nvidia/nemotron-3-ultra-550b-a55b", "minimaxai/minimax-m3.1-flash", "nvidia/nemotron-3.5-bolt-e4b"]
CHAIN_TIMEOUT = 90
# The 40 rpm cap is per account (both keys sit in one org), so every caller shares one limiter: >= 2.5 s between request starts (24 rpm) across processes.
MIN_GAP = 2.5
STAMP = os.path.join(os.path.expanduser("~"), ".cache", "nim_throttle")


def _throttle():
    os.makedirs(os.path.dirname(STAMP), exist_ok=True)
    with open(STAMP, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            last = float(f.read() or 0)
        except ValueError:
            last = 0.0
        wait = last + MIN_GAP - time.time()
        if wait > 0:
            time.sleep(wait)
        f.seek(0); f.truncate(); f.write(str(time.time()))


def _env(name):
    if os.environ.get(name):
        return os.environ[name]
    try:
        for line in open(ENVFILE, encoding="utf-8"):
            k, s, v = line.strip().removeprefix("export ").partition("=")
            if s and k.strip() == name:
                return v.strip().strip("\"'")
    except OSError:
        pass
    return ""


LOG = os.path.join(os.path.expanduser("~"), ".claude", "dispatch-log.jsonl")


def _log(model, ok, err=""):
    """Self-log every real HTTP attempt (metadata only, no prompt content) so dispatch-log.jsonl stops undercounting direct nim_call.py/role.sh usage."""
    try:
        with open(LOG, "a") as f:
            f.write(json.dumps({"ts": int(time.time()), "engine": "nim", "model": model, "ok": ok, "err": err}) + "\n")
    except OSError:
        pass


RULES_JSON = os.path.join(os.path.expanduser("~"), "memory-vault/pages/dispatch-routes.json")


def with_rules(messages):
    """Opt-in: prepend the global agent-rules preamble (dispatch-routes.json 'preamble') as the first system message. NOT for structured/JSON-output callers."""
    pre = json.load(open(RULES_JSON))["preamble"]
    return [{"role": "system", "content": pre}] + list(messages)


def chat(model, messages, timeout=120, max_tokens=1500, tools=None, key_order=KEYS, rules=False, think=False):
    """Return message dict. Raises RuntimeError('http <code>') on failure (after trying every key on 429).
    model "chain" or "a,b,c": try each model in turn (key 2 first, CHAIN_TIMEOUT per model) until one answers."""
    model = model.removeprefix("nim:")
    if rules:
        messages = with_rules(messages)
    if model == "chain" or "," in model:
        models = CHAIN if model == "chain" else [m.strip() for m in model.split(",") if m.strip()]
        errs = []
        for m in models:
            try:
                r = chat(m, messages, min(timeout, CHAIN_TIMEOUT), max_tokens, tools, key_order=KEYS, think=think)  # rules already applied above
                if r.get("content") or r.get("tool_calls"):
                    r["_model"] = m  # which chain model answered, for yield telemetry
                    return r
                errs.append(f"{m.split('/')[-1]}:empty (reasoning used the token budget)")
            except RuntimeError as e:
                errs.append(f"{m.split('/')[-1]}:{e}")
        raise RuntimeError("chain failed " + " | ".join(errs))
    keys = [k for k in (_env(n) for n in key_order) if k]
    if not keys:
        raise RuntimeError("no NVIDIA key")
    body = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens}
    if "nemotron" in model and not think:
        body["chat_template_kwargs"] = {"enable_thinking": False}  # thinking mode burned all max_tokens on 3.5-super-vl (diagnosed 2026-11-04: 4000 reasoning tokens, empty content)
    if tools:
        body["tools"] = tools
    err = "unknown"
    for key in keys:
        _throttle()
        req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as f:
                _log(model, True)
                return json.loads(f.read())["choices"][0]["message"]
        except urllib.error.HTTPError as e:
            err = f"http {e.code}"
            if e.code != 429:
                break
        except Exception as e:  # timeout, DNS
            err = type(e).__name__
            break
    _log(model, False, err)
    raise RuntimeError(err)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("model"); ap.add_argument("--system-file"); ap.add_argument("--timeout", type=int, default=120); ap.add_argument("--no-rules", dest="rules", action="store_false", help="CLI default: global agent-rules preamble is prepended; this turns it off (use for JSON/structured output)")
    a = ap.parse_args()
    msgs = []
    if a.system_file:
        msgs.append({"role": "system", "content": open(a.system_file).read()})
    msgs.append({"role": "user", "content": sys.stdin.read()})
    try:
        print(chat(a.model, msgs, timeout=a.timeout, rules=a.rules).get("content") or "")
    except RuntimeError as e:
        print(f"nim error: {e}", file=sys.stderr); sys.exit(1)
