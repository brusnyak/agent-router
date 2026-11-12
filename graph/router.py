"""Thin router — the Brain layer of the agent-router pivot.

Replaces the archived LangGraph supervisor (graph/ARCHIVED_supervisor.py).

Owns: classify task, resolve skill/agent/prompt/hook, choose tier, plan,
verify, escalate, log.

Gateway (OmniRoute at http://localhost:20128/v1) owns: NIM key rotation,
fallback, quota, rate limiting across nim1/nim2/nim3.

Public API (stable — consumed by main.py, api/chat.py, api/ws.py):
  RouterSupervisor() -> instance
  .run(message, project, lane, model, skills) -> dict
  .get_available_agents() -> list[dict]
  .get_available_models() -> list[dict]
  .select_model_for_task(task_type) -> str | None
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

import yaml

HOME = os.path.expanduser("~")
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "scripts"))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "graph"))

CONFIG_DIR = os.path.join(_PROJECT_ROOT, "config")
OMNIROUTE_BASE_URL = "http://localhost:20128/v1"

# Backbone is the single execution engine (checkpoints, key pool, gates,
# NIM/OpenRouter/claude/codex workers). RouterSupervisor delegates to it.
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "backbone"))
from backbone.core import Backbone  # noqa: E402

from agent_base import create_agent, load_agent_config, AGENT_CLASSES, NIMAgent, CLIAgent
from prompt_library import (
    build_packet, render_system_prompt, load_all_skills, load_lanes,
    load_project_context, get_lane,
)
from evaluation import evaluate_card, store_evaluation
from db.database import (
    get_connection, create_card, get_card, list_cards, add_comment,
    add_delegation_flow, add_token_usage, get_analytics, init_db,
)

# Ensure DB schema exists
init_db()

OMNIROUTE_HEALTH_CACHE: Dict[str, tuple] = {}  # model -> (available, ts)

OMNIROUTE_KEY_FILE = os.path.join(HOME, ".omniroute", "client.key")


def _omniroute_api_key() -> str:
    """Read the OmniRoute API key from ~/.omniroute/client.key (never printed)."""
    try:
        with open(OMNIROUTE_KEY_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _load_agents() -> List[dict]:
    return _load_yaml(os.path.join(CONFIG_DIR, "agents.yaml")).get("agents", [])


def _load_models() -> List[dict]:
    return _load_yaml(os.path.join(CONFIG_DIR, "models.yaml")).get("models", [])


def _load_lanes() -> dict:
    return _load_yaml(os.path.join(CONFIG_DIR, "lanes.yaml"))


def _load_drift() -> dict:
    drift_path = os.path.join(CONFIG_DIR, "drift", "config-drift.yaml")
    if not os.path.exists(drift_path):
        return {"routing_constraints": [], "model_routing": {}, "proposals": []}
    try:
        return _load_yaml(drift_path)
    except Exception:
        return {"routing_constraints": [], "model_routing": {}, "proposals": []}


# ---------------------------------------------------------------------------
# OmniRoute health check (replaces nim key harness probing)
# ---------------------------------------------------------------------------

def _omniroute_available(model: str) -> bool:
    """Check if OmniRoute can serve this model. Cached 300s."""
    now = time.time()
    hit = OMNIROUTE_HEALTH_CACHE.get(model)
    if hit and now - hit[1] < 300:
        return hit[0]
    try:
        import urllib.request
        api_key = _omniroute_api_key()
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(
            f"{OMNIROUTE_BASE_URL}/models",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        models = data.get("data", [])
        available = any(m.get("id") == model or model in str(m) for m in models)
    except Exception:
        available = False
    OMNIROUTE_HEALTH_CACHE[model] = (available, now)
    return available


# ---------------------------------------------------------------------------
# Resolver (wires router.py hits into lane/agent/packet)
# ---------------------------------------------------------------------------

def _resolver_find(user_input: str, top_k: int = 5) -> List[dict]:
    """Ask ~/.agent-skills/router/router.py which skills/agents fit this task."""
    router_py = os.path.join(HOME, ".agent-skills", "router", "router.py")
    if not os.path.exists(router_py):
        return []
    try:
        r = subprocess.run(
            ["python3", router_py, "find", user_input, "-k", str(top_k), "--json"],
            capture_output=True, text=True, timeout=30,
            cwd=os.path.join(HOME, ".agent-skills", "router"),
        )
        if r.returncode != 0:
            return []
        return json.loads(r.stdout)
    except Exception:
        return []


def _resolve_skills_for_lane(lane_id: str) -> List[str]:
    """Return skills for a lane from lanes.yaml."""
    lanes_cfg = _load_lanes()
    for lane in lanes_cfg.get("lanes", []):
        if lane.get("id") == lane_id:
            return lane.get("skills", [])
    return []


# ---------------------------------------------------------------------------
# Research enforcement (mandatory pre-check before any triage/dispatch)
# ---------------------------------------------------------------------------

def _research_enforcement(message: str) -> Dict[str, Any]:
    """Mandatory pre-check: verify existing assets/config before any suggestion.

    Runs router.py find to check if the skill/agent/command/MCP/loop already
    exists in the index. Checks models.yaml/agents.yaml/lanes.yaml for existing
    config. If no A/B evidence found, blocks generic suggestions.

    Returns dict with: sufficient (bool), materials (list), findings (list),
    recommended_asset (str|None), reason (str|None).
    """
    materials: List[str] = []
    findings: List[str] = []

    # 1. Run router.py find to check existing assets
    router_py = os.path.join(HOME, ".agent-skills", "router", "router.py")
    resolver_hits: List[dict] = []
    if os.path.exists(router_py):
        materials.append(f"router.py find: {message}")
        try:
            r = subprocess.run(
                ["python3", router_py, "find", message, "-k", "5", "--json"],
                capture_output=True, text=True, timeout=30,
                cwd=os.path.join(HOME, ".agent-skills", "router"),
            )
            if r.returncode == 0:
                resolver_hits = json.loads(r.stdout)
        except Exception:
            resolver_hits = []

    # 2. Check backbone config for existing model/agent/lane
    models_cfg = _load_models()
    agents_cfg = _load_agents()
    lanes_cfg = _load_lanes()

    materials.append(f"models.yaml: {len(models_cfg)} models")
    materials.append(f"agents.yaml: {len(agents_cfg)} agents")
    materials.append(f"lanes.yaml: {len(lanes_cfg.get('lanes', []))} lanes")

    # 3. Grade findings: A = exact asset match, B = config exists, C = none
    recommended_asset: Optional[str] = None
    grade = "C"

    for hit in resolver_hits:
        score = hit.get("sem", hit.get("score", 0))
        hit_id = hit.get("id", "")
        hit_kind = hit.get("kind", "")
        if score >= 0.35:
            findings.append(f"A: existing asset '{hit_id}' ({hit_kind}) score={score:.2f} path={hit.get('path','')}")
            grade = "A"
            if not recommended_asset:
                recommended_asset = hit_id
        elif score >= 0.20:
            findings.append(f"B: potential asset '{hit_id}' ({hit_kind}) score={score:.2f}")
            if grade == "C":
                grade = "B"

    # Check models config for NIM/claude/codex match
    lower = message.lower()
    for m in models_cfg:
        mid = m.get("id", "").lower()
        mname = m.get("name", "").lower()
        if "nim" in lower and ("nim" in mid or "nemotron" in mname):
            findings.append(f"B: model config exists '{m.get('id')}' provider={m.get('provider')} key={m.get('api_key_env')}")
            if grade == "C":
                grade = "B"
        if "claude" in lower and "claude" in mid:
            findings.append(f"B: agent config exists '{m.get('id')}' provider={m.get('provider')}")
            if grade == "C":
                grade = "B"
        if "codex" in lower and "codex" in mid:
            findings.append(f"B: agent config exists '{m.get('id')}' provider={m.get('provider')}")
            if grade == "C":
                grade = "B"

    # Check agents config
    for a in agents_cfg:
        aid = a.get("id", "").lower()
        if any(w in lower for w in ["review", "roast"]) and "review" in aid:
            findings.append(f"B: agent '{aid}' lane_reasons={a.get('route_reasons',[])}")
            if grade == "C":
                grade = "B"

    # Check lanes config
    for lane in lanes_cfg.get("lanes", []):
        lid = lane.get("id", "").lower()
        if lid in lower:
            findings.append(f"B: lane '{lid}' agents={lane.get('agents',[])} skills={lane.get('skills',[])}")
            if grade == "C":
                grade = "B"

    sufficient = grade in ("A", "B")
    reason = None
    if not sufficient:
        reason = f"No existing asset or config found for: {message}. Do not suggest generically. Run research skill or ask owner."

    return {
        "sufficient": sufficient,
        "grade": grade,
        "materials": materials,
        "findings": findings,
        "recommended_asset": recommended_asset,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Agent availability
# ---------------------------------------------------------------------------

def _agent_available(a: dict) -> bool:
    aid = a.get("id")
    provider = a.get("provider", "")
    if provider == "nim" or aid.startswith("nim"):
        # NIM agents are available when their api_key_env key is present
        # (nim_call.py owns key rotation across NIM_1/NIM_2/NIM_3).
        key_env = a.get("api_key_env", "NIM_3")
        return bool(os.environ.get(key_env, ""))
    # CLI agents: available if CLI binary exists on PATH
    cli = a.get("cli", aid)
    return shutil.which(cli) is not None


# ---------------------------------------------------------------------------
# RouterSupervisor
# ---------------------------------------------------------------------------

class RouterSupervisor:
    """Thin router: triage → dispatch → card → evaluate."""

    def __init__(self):
        self.agents_cfg: Dict[str, dict] = {}
        for a in _load_agents():
            aid = a.get("id")
            if aid:
                self.agents_cfg[aid] = a
        self.models_cfg: List[dict] = _load_models()
        self.drift: dict = _load_drift()
        self.trace_id: str = str(uuid.uuid4())
        self.interactive_mode: bool = False
        # Single Backbone engine — checkpoints, key pool, gates, workers
        self._backbone = Backbone()

    # -- public API -------------------------------------------------------

    def get_available_agents(self) -> List[Dict[str, Any]]:
        agents = []
        for a in _load_agents():
            aid = a.get("id")
            agents.append({
                "id": aid,
                "cli": a.get("cli"),
                "model": a.get("model"),
                "provider": a.get("provider", ""),
                "write_access": a.get("write_access", False),
                "available": _agent_available(a),
                "route_reasons": a.get("route_reasons", []),
                "skills": a.get("skills", []),
                "note": a.get("note"),
            })
        return agents

    def get_available_models(self) -> List[Dict[str, Any]]:
        models = []
        for m in _load_models():
            model_name = m.get("name", "")
            provider = m.get("provider", "")
            key_env = m.get("api_key_env", "")
            if provider in ("anthropic", "openai", "google") or provider == "nim":
                # NIM via OmniRoute: available when its api_key_env key is present
                # (nim_call.py owns key rotation across NIM_1/NIM_2/NIM_3).
                available = bool(os.environ.get(key_env, ""))
            models.append({
                "id": m.get("id"),
                "name": model_name,
                "provider": provider,
                "role": m.get("role"),
                "available": available,
                "api_key_env": key_env,
            })
        models.sort(key=lambda x: (not x["available"], x["role"] != "supervisor"))
        return models

    def select_model_for_task(self, task_type: str) -> Optional[str]:
        models = self.get_available_models()
        if not models:
            return None
        preferred_role = "supervisor" if task_type == "triage" else "worker"
        for m in models:
            if m["available"] and m["role"] == preferred_role:
                return m["name"]
        for m in models:
            if m["available"]:
                return m["name"]
        return None

    def run(
        self,
        message: str,
        project: Optional[str] = None,
        lane: Optional[str] = None,
        model: Optional[str] = None,
        skills: Optional[List[str]] = None,
    ) -> dict:
        """Triage → dispatch → card → evaluate. Returns chat-response dict.

        MANDATORY pre-check: research-enforcement runs before any triage.
        If no existing asset/config evidence is found, blocks generic
        suggestions and returns insufficient_evidence.
        """
        # --- MANDATORY: research-enforcement pre-check ---
        enforcement = _research_enforcement(message)
        if not enforcement["sufficient"]:
            return {
                "status": "blocked",
                "interrupt_reason": "insufficient_evidence",
                "reason": enforcement["reason"],
                "materials": enforcement["materials"],
                "findings": enforcement["findings"],
                "lane": None,
                "agent": None,
                "project": project,
                "result": None,
                "card": None,
                "tokens_spent": 0,
                "delegation_flow": ["user -> router (blocked: insufficient_evidence)"],
                "index_context": "",
                "chosen_model": None,
            }

        agents = self.get_available_agents()
        available_agent_ids = [a["id"] for a in agents if a["available"]]

        # Apply drift constraints
        drift_constraints = self.drift.get("routing_constraints", [])
        available_agent_ids = [
            aid for aid in available_agent_ids
            if not any(aid in c and "avoid" in c.lower() for c in drift_constraints)
        ]

        # Resolver hits → attach to packet
        resolver_matches = _resolver_find(message, top_k=5)
        resolver_skills: List[str] = []
        for m in resolver_matches:
            score = m.get("sem", m.get("score", 0))
            if score > 0.35:
                resolver_skills.append(m.get("id", ""))

        # Explicit lane override (from Dispatch Cockpit UI)
        if lane:
            lane_def = get_lane(lane) or {}
            lane_agents = lane_def.get("agents", [])
            chosen_agent = None
            for aid in lane_agents:
                if aid in available_agent_ids:
                    chosen_agent = aid
                    break
            if not chosen_agent and available_agent_ids:
                chosen_agent = available_agent_ids[0]
            chosen_model = model or (lane_def.get("model"))
            state = {
                "lane": lane,
                "agent": chosen_agent,
                "project": project,
                "skills": list(dict.fromkeys((skills or []) + _resolve_skills_for_lane(lane) + resolver_skills)),
                "reasoning": "Explicit lane override",
                "project_vision": "", "direct_market": "", "value_exchange": "",
                "action_chain": "", "next_step": "",
                "chosen_model": chosen_model,
            }
        else:
            # Triage: deterministic classification (no LLM supervisor call —
            # NIM models are for execution, triage uses keyword rules to avoid
            # burning supervisor model quota on every message)
            lower = message.lower()
            if any(w in lower for w in ["build", "code", "implement", "fix", "refactor"]):
                lane_id = "build"
            elif any(w in lower for w in ["review", "roast", "audit", "check"]):
                lane_id = "review-roast"
            elif any(w in lower for w in ["research", "search", "find", "web"]):
                lane_id = "research-public"
            else:
                lane_id = "planner"

            lane_def = get_lane(lane_id) or {}
            lane_agents = lane_def.get("agents", [])
            chosen_agent = None
            for aid in lane_agents:
                if aid in available_agent_ids:
                    chosen_agent = aid
                    break
            if not chosen_agent and available_agent_ids:
                chosen_agent = available_agent_ids[0]

            chosen_model = model
            if not chosen_model and chosen_agent:
                for a in self.agents_cfg.get(chosen_agent, {}) if isinstance(self.agents_cfg.get(chosen_agent), dict) else []:
                    pass
                # Find model from agents config
                agent_cfg = self.agents_cfg.get(chosen_agent, {})
                chosen_model = agent_cfg.get("model")

            state = {
                "lane": lane_id,
                "agent": chosen_agent,
                "project": project,
                "skills": list(dict.fromkeys((skills or []) + _resolve_skills_for_lane(lane_id) + resolver_skills)),
                "reasoning": f"Triage: {lane_id} lane, agent {chosen_agent}",
                "project_vision": "", "direct_market": "", "value_exchange": "",
                "action_chain": "", "next_step": "",
                "chosen_model": chosen_model,
            }

        # Gate keeper
        gate_words = ["send", "spend", "deploy", "approve", "submit", "push", "delete", "auth", "vault-write", "vault_write"]
        lower = message.lower()
        for word in gate_words:
            if word in lower:
                return {
                    "status": "blocked",
                    "interrupt_reason": f"Gate word '{word}' detected — requires owner approval",
                    "lane": state["lane"],
                    "agent": state["agent"],
                    "project": state["project"],
                    "result": None,
                    "card": None,
                    "tokens_spent": 0,
                    "delegation_flow": [f"user -> {state['agent'] or 'none'} (blocked: {word})"],
                    "index_context": "",
                    "chosen_model": state["chosen_model"],
                }

        # Dispatch
        agent_id = state["agent"]
        if not agent_id:
            return {
                "status": "blocked",
                "interrupt_reason": "No available agent for this lane",
                "lane": state["lane"],
                "agent": None,
                "project": state["project"],
                "result": None,
                "card": None,
                "tokens_spent": 0,
                "delegation_flow": ["user -> none (no agent)"],
                "index_context": "",
                "chosen_model": state["chosen_model"],
            }

        packet = build_packet(
            lane_id=state["lane"],
            agent_id=agent_id,
            project_id=state["project"] or "global",
            user_input=message,
            skills=state["skills"],
        )
        packet["lane_def"] = get_lane(state["lane"]) or {}
        packet["chosen_model"] = state["chosen_model"]
        packet["task_id"] = str(uuid.uuid4())[:8]

        # Map agent id → Backbone worker spec.
        # nim1/nim2/nim3 -> pi:NIM_1/NIM_2/NIM_3 (key pool rotation)
        # ecc-* / agency-* (virtual NIM agents) -> pi:NIM_<n> from their config
        # claude/codex -> own-login CLI workers
        # openrouter -> or:<model-slug> (OpenRouter, read-only by construction)
        def _worker_for_agent(aid: str, acfg: dict) -> str:
            prov = acfg.get("provider", "")
            if prov == "nim" or aid.startswith("nim"):
                key_env = acfg.get("api_key_env", "NIM_1")
                nim_n = key_env.replace("NIM", "") or "1"
                return f"pi:NIM_{nim_n}"
            if prov in ("claude", "codex"):
                return prov
            if prov == "openrouter":
                model = acfg.get("model", "nvidia/nemotron-3-ultra-550b-a55b:free")
                # Strip "openrouter/" prefix if present for the `or:` spec
                slug = model.removeprefix("openrouter/")
                return f"or:{slug}"
            # Default: virtual NIM agent on NIM_1
            return "pi:NIM_1"

        agent_cfg = self.agents_cfg.get(agent_id, {})
        worker_spec = _worker_for_agent(agent_id, agent_cfg)

        # Build the prompt for Backbone: include lane as a gate, skills as context.
        lane_def = get_lane(state["lane"]) or {}
        gate_name = state["lane"] if state["lane"] in ("pytest", "compile", "noop") else None
        prompt_parts = [message]
        if state["skills"]:
            prompt_parts.append(f"\nSkills to apply: {', '.join(state['skills'])}")
        if lane_def.get("acceptance"):
            prompt_parts.append(f"\nAcceptance check: {lane_def['acceptance']}")
        if lane_def.get("never"):
            prompt_parts.append(f"\nNever: {', '.join(lane_def['never'])}")
        backbone_prompt = "\n".join(prompt_parts)

        t0 = time.time()
        try:
            bb_result = self._backbone.run(
                backbone_prompt,
                session=state["lane"],
                project=state["project"] or "",
                gate=gate_name,
                worker=worker_spec,
                read_only=not agent_cfg.get("write_access", False),
            )

            # Backbone returns a dict; extract output text and status.
            bb_out = bb_result.get("output", bb_result.get("text", "")) if isinstance(bb_result, dict) else str(bb_result)
            bb_ok = bb_result.get("state", "done") != "failed" if isinstance(bb_result, dict) else True
            latency_ms = int((time.time() - t0) * 1000)

            # Extract claimed files from output (read-only verification, no direct writes).
            from agent_harness import AgentHarness
            harness = AgentHarness()
            claimed = harness.extract_claimed_files(bb_out)
            verification = harness.verify_claimed_files(claimed, agent_can_write=agent_cfg.get("write_access", False))
            patch_artifact = {
                "agent": agent_id,
                "worker": worker_spec,
                "model": state["chosen_model"] or "unknown",
                "claimed_files": claimed,
                "verification": verification,
                "status": "pending_owner_apply" if claimed else "no_claims",
                "note": "Response-driven writes disabled. Patch artifact only; owner applies via explicit allowed write path.",
            }

            # Card
            card = {
                "title": packet.get("goal", "Untitled task")[:100],
                "lane": state["lane"],
                "agent": agent_id,
                "model": state["chosen_model"] or "unknown",
                "status": "done" if bb_ok else "failed",
                "project": state["project"],
                "prompt_sent": system_prompt[:500],
                "output": bb_out,
                "tokens_spent": (len(json.dumps(packet)) + len(bb_out)) // 4,
                "project_vision": state["project_vision"],
                "direct_market": state["direct_market"],
                "value_exchange": state["value_exchange"],
                "action_chain": state["action_chain"],
                "next_step": state["next_step"],
                "claimed_files": claimed,
                "file_verification": verification,
                "patch_artifact": patch_artifact,
                "backbone_result": bb_result if isinstance(bb_result, dict) else {"state": "done", "output": bb_result},
            }
            card_id = create_card(card)
            add_delegation_flow(card_id, None, agent_id, "created")
            add_delegation_flow(card_id, None, agent_id, "dispatched")
            add_token_usage(card_id, agent_id, state["chosen_model"] or "unknown", card["tokens_spent"])

            # Evaluate
            eval_result = None
            try:
                card_full = get_card(card_id)
                if card_full:
                    eval_result = evaluate_card(card_full)
                    if eval_result:
                        store_evaluation(card_id, eval_result)
            except Exception:
                pass

            return {
                "status": "done" if bb_ok else "blocked",
                "lane": state["lane"],
                "agent": agent_id,
                "project": state["project"],
                "result": bb_out,
                "card": {**card, "id": card_id},
                "tokens_spent": card["tokens_spent"],
                "delegation_flow": [f"user -> {agent_id} -> {'completed' if bb_ok else 'failed'}"],
                "index_context": "",
                "chosen_model": state["chosen_model"],
                "evaluation": eval_result,
                "latency_ms": latency_ms,
            }
        except Exception as e:
            latency_ms = int((time.time() - t0) * 1000)
            return {
                "status": "blocked",
                "lane": state["lane"],
                "agent": agent_id,
                "project": state["project"],
                "result": f"Error: {e}",
                "card": None,
                "tokens_spent": 0,
                "delegation_flow": [f"user -> {agent_id} (error: {e})"],
                "index_context": "",
                "chosen_model": state["chosen_model"],
                "latency_ms": latency_ms,
            }

    # -- compatibility aliases (old supervisor interface) ----------------

    def get_token_analytics(self) -> dict:
        try:
            return get_analytics()
        except Exception:
            return {"error": "analytics unavailable"}

    def _apply_drift_constraints(self, agent_id: Optional[str], model_name: Optional[str]):
        warnings: List[str] = []
        if agent_id:
            for c in self.drift.get("routing_constraints", []):
                if agent_id in c and "avoid" in c.lower():
                    warnings.append(f"Drift constraint: {c}")
                    agent_id = None
                    break
        return agent_id, model_name, warnings

    def _deterministic_triage(self, user_input: str) -> str:
        lower = user_input.lower()
        if any(w in lower for w in ["build", "code", "implement", "fix", "refactor"]):
            lane = "build"
        elif any(w in lower for w in ["review", "roast", "audit", "check"]):
            lane = "review-roast"
        elif any(w in lower for w in ["research", "search", "find", "web"]):
            lane = "research-public"
        else:
            lane = "planner"
        return json.dumps({"lane": lane, "agent": "nim3", "project": None, "skills": [],
                           "reasoning": "Deterministic fallback"})
