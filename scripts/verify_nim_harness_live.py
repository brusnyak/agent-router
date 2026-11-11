"""Live integration proof for the NIM key harness + supervisor integration.

Run: .venv/bin/python scripts/verify_nim_harness_live.py
"""
import os
import sys
import time

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router", "scripts"))

from graph.supervisor import RouterSupervisor  # noqa: E402
import nim_key_harness as h  # noqa: E402

MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"
fails = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        fails.append(name)


print("1. harness with a BROKEN first key must rotate to a valid one")
os.environ["NIM_BROKEN"] = "nvapi-broken-" + "0" * 60
hn = h.NimKeyHarness(key_envs=("NIM_BROKEN", "NIM_3", "NIM_2"))
t0 = time.time()
try:
    r = hn.call_with_retry([{"role": "user", "content": "ping"}], model=MODEL,
                           timeout=25, max_tokens=5, attempts=3, backoff=(0.5,))
    ok = bool(r.get("content"))
    check("rotates off dead key and succeeds", ok,
          f"in {time.time()-t0:.1f}s content={str(r.get('content'))[:12]!r}")
    check("dead key quarantined", "NIM_BROKEN" in hn._dead)
except Exception as e:
    check("rotates off dead key and succeeds", False, f"{type(e).__name__}: {e}")

print("2. supervisor._check_nim_available must report the model AVAILABLE")
s = RouterSupervisor()
t0 = time.time()
avail = s._check_nim_available("NIM_3", MODEL)
check("model reported available", avail is True, f"in {time.time()-t0:.1f}s")

print("3. probe must be cached per model (one probe for 3 key_env entries)")
t0 = time.time()
s._model_cache.clear()
m1 = s.get_available_models()
probes_1 = len(s._model_cache)
s._model_cache.clear()
s.get_available_models()
probes_2 = len(s._model_cache)
check("one probe result for 3 model entries", probes_1 == 1 and probes_2 == 1,
      f"cache entries={probes_1}/{probes_2}")

print("4. second probe call is served from cache (no API call)")
t0 = time.time()
s._check_nim_available("NIM_2", MODEL)
cached = time.time() - t0
check("cached probe is instant", cached < 0.5, f"{cached:.3f}s")

print("5. supervisor._call_llm must reach the real model")
t0 = time.time()
try:
    out = s._call_llm("You are a terse assistant.", "Reply with exactly: PONG", task_type="triage")
    check("_call_llm returned model output", bool(out) and "PONG" in out.upper(),
          f"in {time.time()-t0:.1f}s out={str(out)[:60]!r}")
except Exception as e:
    check("_call_llm returned model output", False, f"{type(e).__name__}: {e}")

print("6. no key material in the harness state")
leaked = [k for k in hn._until if len(str(hn._until[k])) > 0 and "nvapi" in str(hn._until[k])]
check("no key values stored in harness state", not leaked)

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
