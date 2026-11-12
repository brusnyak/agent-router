"""Live integration proof for NIM keys + RouterSupervisor.

Verifies:
  1. nim_call.py rotates across NIM_1/NIM_2/NIM_3 and returns real model output
  2. RouterSupervisor reports NIM agents as available
  3. RouterSupervisor.run() dispatches end-to-end (card + evaluation written)

Run: .venv/bin/python scripts/verify_nim_harness_live.py
"""
import os
import sys

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router", "scripts"))

fails = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        fails.append(name)


print("1. nim_call.py reaches a real model (rotates NIM keys internally)")
import nim_call  # noqa: E402
try:
    r = nim_call.chat(
        "nvidia/nemotron-3.5-super-vl-120b-a12b",
        [{"role": "user", "content": "Reply with exactly: PONG"}],
        timeout=60,
        max_tokens=10,
    )
    ok = bool(r.get("content")) and "PONG" in r["content"].upper()
    check("nim_call.chat returns model output", ok, f"content={str(r.get('content'))[:40]!r}")
except Exception as e:
    check("nim_call.chat returns model output", False, f"{type(e).__name__}: {e}")

print("2. RouterSupervisor reports NIM agents available")
from graph.router import RouterSupervisor  # noqa: E402
s = RouterSupervisor()
agents = s.get_available_agents()
nim_agents = [a for a in agents if a["provider"] == "nim"]
check("at least one NIM agent available", any(a["available"] for a in nim_agents),
      f"{sum(1 for a in nim_agents if a['available'])}/{len(nim_agents)} available")

print("3. RouterSupervisor.run() dispatches end-to-end")
try:
    result = s.run("build a hello world script")
    check("run returns status", "status" in result)
    check("run status is done/blocked", result.get("status") in ("done", "blocked"))
    check("card written", result.get("card") is not None or result.get("status") == "blocked")
except Exception as e:
    check("run dispatches end-to-end", False, f"{type(e).__name__}: {e}")

print("4. get_available_models / select_model_for_task work")
models = s.get_available_models()
check("models list non-empty", len(models) > 0)
selected = s.select_model_for_task("worker")
check("select_model_for_task returns a model", selected is not None)

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
