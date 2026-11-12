"""LangGraph supervisor — Phase 2: index-aware routing with model availability + config drift.

Adds on top of Phase 1:
- Index-aware triage: queries the local index (skills/hooks/systems/vault/repos) before routing
- Model availability: picks the idle/available model first (NIM key rotation via nim_key_harness)
- Config drift: reads config/drift/config-drift.yaml routing constraints and applies them
- Trust tiers: agent write_access + vault sandbox enforcement

Public API unchanged: RouterSupervisor.run(user_input) -> dict
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import yaml
from typing import Dict, Any, Optional, List
from pathlib import Path

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

HOME = os.path.expanduser("~")

# Project root resolved from this file's location, so the same code runs on any
# host (Mac, Oracle VM, etc.) without hardcoded paths.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

# Load project .env first (agent-router/.env), then ~/.env as fallback.
# Never read global env directly — only project-local env files.
PROJECT_ENV = os.path.join(_PROJECT_ROOT, ".env")
HOME_ENV = os.path.join(HOME, ".env")

# Scripts directory for harness modules (nim_key_harness, agent_harness, etc.)
_PROJECT_SCRIPTS = os.path.join(_PROJECT_ROOT, "scripts")


def _load_env() -> None:
    for envfile in (PROJECT_ENV, HOME_ENV):
        try:
            with open(envfile, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except OSError:
            pass

_load_env()

from graph.state import RouterState
from graph.agent_base import create_agent, load_agent_config, AGENT_CLASSES
from graph.prompt_library import (
    build_packet, render_system_prompt, load_all_skills,
    load_lanes, load_project_context, get_lane,
)
from graph.evaluation import evaluate_card, store_evaluation, load_llm_judge
from db import create_card, get_card, list_cards, add_comment, add_delegation_flow, add_token_usage, get_analytics

CONFIG_DIR = os.path.join(_PROJECT_ROOT, "config")
INDEX_DB = os.path.join(CONFIG_DIR, "index.db")
DRIFT_PATH = os.path.join(CONFIG_DIR, "drift", "config-drift.yaml")
VAULT_SANDBOX = os.path.join(HOME, "memory-vault", "agents")

# sys.path for nim_call and index_vault
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "scripts"))
_memory_vault_scripts = os.path.join(HOME, "memory-vault", "scripts")
if os.path.isdir(_memory_vault_scripts):
    sys.path.insert(0, _memory_vault_scripts)

import nim_call  # noqa: E402
import nim_key_harness  # noqa: E402

# Availability probe: cached per model (not per key) — all three models.yaml entries
# point at the same model name, so key-scoped caching fired three identical probes.
NIM_PROBE_TTL = 300      # seconds a probe result stays valid
NIM_PROBE_TIMEOUT = 15   # measured p50 ~7s / max ~23s for a 5-token ping


class RouterSupervisor:
    """Phase 2 supervisor: index-aware, model-availability-driven, drift-constrained."""

    def __init__(self):
        self.state: RouterState = self._empty_state()
        self.graph = self._build_graph()
        self.llm = self._init_judge_llm()
        self.agents: Dict[str, Any] = {}
        self.index_available = os.path.exists(INDEX_DB)
        self.drift = self._load_drift()
        self._load_agent_registry()
        self.nim_key_available = self._ensure_nim_key()
        self.interactive_mode = False  # unattended by default; set True for attended sessions

        # Circuit breaker state per agent
        self._cb_state: Dict[str, dict] = {}
        # NIM key harness: rotation + retry/backoff + per-key cooldown
        self._nim = nim_key_harness.NimKeyHarness()
        self._model_cache: Dict[str, tuple] = {}
        # Fallback chain per agent
        self._fallback_chain: Dict[str, list[str]] = self._build_fallback_chain()
        # Trace id for observability across this run
        self.trace_id: str = str(uuid.uuid4())

    # ------------------------------------------------------------------
    # Circuit breaker (ECC multi-agent-systems-architect pattern)
    # ------------------------------------------------------------------

    CB_CLOSED = "closed"
    CB_OPEN = "open"
    CB_HALF_OPEN = "half_open"

    def _build_fallback_chain(self) -> Dict[str, list[str]]:
        """Define fallback chains for each agent based on capability and lane."""
        import yaml as _yaml
        with open(os.path.join(CONFIG_DIR, "agents.yaml")) as f:
            cfg = _yaml.safe_load(f) or {}
        chain: Dict[str, list[str]] = {}
        for a in cfg.get("agents", []):
            aid = a.get("id")
            if not aid:
                continue
            provider = a.get("provider", "")
            route_reasons = a.get("route_reasons", [])
            if provider == "nim":
                nim_others = [
                    other["id"]
                    for other in cfg.get("agents", [])
                    if other.get("provider") == "nim" and other.get("id") != aid
                ]
                chain[aid] = nim_others
            elif provider in ("claude", "codex", "gemini"):
                nim_matches = [
                    other["id"]
                    for other in cfg.get("agents", [])
                    if other.get("provider") == "nim"
                    and any(r in other.get("route_reasons", []) for r in route_reasons)
                ]
                chain[aid] = nim_matches[:2]
            else:
                chain[aid] = []
        return chain

    def _cb_get(self, agent_id: str) -> dict:
        if agent_id not in self._cb_state:
            self._cb_state[agent_id] = {
                "state": self.CB_CLOSED,
                "failures": 0,
                "tripped_at": 0.0,
                "last_success": 0.0,
            }
        return self._cb_state[agent_id]

    def _cb_record_success(self, agent_id: str) -> None:
        cb = self._cb_get(agent_id)
        if cb["state"] == self.CB_HALF_OPEN:
            cb["probe_in_flight"] = False
            cb["state"] = self.CB_CLOSED
            cb["failures"] = 0
            cb["last_success"] = time.time()
            return
        cb["state"] = self.CB_CLOSED
        cb["failures"] = 0
        cb["last_success"] = time.time()

    def _cb_record_failure(self, agent_id: str) -> None:
        cb = self._cb_get(agent_id)
        cb["failures"] += 1
        cb["tripped_at"] = time.time()
        # In HALF_OPEN, any failure trips back to OPEN immediately
        if cb["state"] == self.CB_HALF_OPEN:
            cb["state"] = self.CB_OPEN
            return
        if cb["failures"] >= 3:
            cb["state"] = self.CB_OPEN

    def _cb_can_call(self, agent_id: str) -> bool:
        cb = self._cb_get(agent_id)
        if cb["state"] == self.CB_CLOSED:
            return True
        if cb["state"] == self.CB_OPEN:
            if time.time() - cb["tripped_at"] > 60:
                cb["state"] = self.CB_HALF_OPEN
                cb["probe_in_flight"] = False
                return True
            return False
        if cb["state"] == self.CB_HALF_OPEN:
            # Single-probe lockout: only one test request allowed
            if cb.get("probe_in_flight"):
                return False
            cb["probe_in_flight"] = True
            return True
        return False

    def _cb_probe_done(self, agent_id: str, success: bool) -> None:
        """Called after a HALF_OPEN probe completes. Close on success, trip on failure."""
        cb = self._cb_get(agent_id)
        cb["probe_in_flight"] = False
        if cb["state"] == self.CB_HALF_OPEN:
            if success:
                cb["state"] = self.CB_CLOSED
                cb["failures"] = 0
            else:
                cb["state"] = self.CB_OPEN
                cb["tripped_at"] = time.time()

    def _select_agent_with_fallback(self, preferred_agent: str, lane: str) -> str:
        """Select agent using fallback chain if primary is circuit-broken."""
        if self._cb_can_call(preferred_agent):
            return preferred_agent
        for fallback in self._fallback_chain.get(preferred_agent, []):
            if self._cb_can_call(fallback):
                return fallback
        import yaml as _yaml
        with open(os.path.join(CONFIG_DIR, "agents.yaml")) as f:
            cfg = _yaml.safe_load(f) or {}
        for a in cfg.get("agents", []):
            if a.get("provider") == "nim" and a.get("id") != preferred_agent:
                if self._cb_can_call(a["id"]):
                    return a["id"]
        return preferred_agent

    def _ensure_nim_key(self) -> bool:
        """Pre-flight check: is any NIM key available for evaluation/NIM dispatch?"""
        for key_name in ("NIM_3", "NIM_2", "NIM_1"):
            if os.environ.get(key_name):
                return True
        envfile = os.path.join(HOME, ".env")
        try:
            with open(envfile, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k in ("NIM_3", "NIM_2", "NIM_1") and v:
                        os.environ[k] = v
                        return True
        except OSError:
            pass
        print("WARNING: No NIM key (NIM_3/NIM_2/NIM_1) found in env or ~/.env. "
              "LLM judge and NIM agent dispatch will use deterministic fallback.")
        return False

    def _init_judge_llm(self):
        """NIM 3 as LLM judge for PEEM evaluation."""
        try:
            from langchain_nvidia_ai_endpoints import ChatNVIDIA
            api_key = os.environ.get("NIM_3", "")
            if not api_key:
                return None
            return ChatNVIDIA(
                model="nvidia/nemotron-3.5-super-vl-120b-a12b",
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=api_key,
                temperature=0.1,
                max_tokens=2048,
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _empty_state(self) -> RouterState:
        return RouterState(
            messages=[],
            current_card=None,
            lane=None,
            agent=None,
            project=None,
            status="triaging",
            result=None,
            tokens_spent=0,
            delegation_flow=[],
            packet=None,
            interrupt_reason=None,
            project_vision="",
            direct_market="",
            value_exchange="",
            action_chain="",
            next_step="",
        )

    def _load_drift(self) -> dict:
        """Load config-drift.yaml routing constraints (suggest+gate, read-only)."""
        if not os.path.exists(DRIFT_PATH):
            return {"routing_constraints": [], "model_routing": {}, "proposals": []}
        try:
            import yaml as _yaml
            with open(DRIFT_PATH) as f:
                return _yaml.safe_load(f) or {}
        except Exception:
            return {"routing_constraints": [], "model_routing": {}, "proposals": []}

    def _load_agent_registry(self):
        import yaml as _yaml
        path = os.path.join(CONFIG_DIR, "agents.yaml")
        with open(path) as f:
            cfg = _yaml.safe_load(f) or {}
        for a in cfg.get("agents", []):
            aid = a.get("id")
            if aid:
                self.agents[aid] = create_agent(aid, a)

    # ------------------------------------------------------------------
    # Model availability
    # ------------------------------------------------------------------

    def _check_nim_available(self, key_env: str, model: str) -> bool:
        """Can any NIM key serve this model? One probe per model, cached, rotating keys.

        The old probe used a 3s timeout: measured latency for this model is p50 ~7s,
        max ~23s, so 10 of 12 probes timed out (83%) and the model was reported
        unavailable on most refreshes.
        """
        now = time.time()
        hit = self._model_cache.get(model)
        if hit and now - hit[1] < NIM_PROBE_TTL:
            return hit[0]
        try:
            r = self._nim.call_with_retry(
                [{"role": "user", "content": "ping"}],
                model=model,
                timeout=NIM_PROBE_TIMEOUT,
                max_tokens=5,
                attempts=2,
                backoff=(0.5,),
                preferred=key_env,
            )
            result = bool(r.get("content") or r.get("tool_calls"))
        except Exception:
            result = False
        self._model_cache[model] = (result, now)
        return result

    def get_available_agents(self) -> List[Dict[str, Any]]:
        """Return list of agents with availability status (public API)."""
        import yaml as _yaml
        path = os.path.join(CONFIG_DIR, "agents.yaml")
        with open(path) as f:
            cfg = _yaml.safe_load(f) or {}
        agents = []
        nim_keys_available = any(self._nim.has_key(k) for k in ("NIM_3", "NIM_2", "NIM_1"))
        for a in cfg.get("agents", []):
            aid = a.get("id")
            # NIM agents (including virtual persona agents) are available if their key is in env
            if a.get("provider") == "nim" or aid.startswith("nim"):
                available = nim_keys_available and self._cb_can_call(aid)
            else:
                # CLI agents: available if CLI binary exists on PATH
                available = aid in ("claude", "codex", "gemini") and shutil.which(a.get("cli", aid)) is not None
            agents.append({
                "id": aid,
                "cli": a.get("cli"),
                "model": a.get("model"),
                "provider": a.get("provider", ""),
                "write_access": a.get("write_access", False),
                "available": available,
                "route_reasons": a.get("route_reasons", []),
                "skills": a.get("skills", []),
                "note": a.get("note"),
            })
        return agents

    def get_available_models(self) -> List[Dict[str, Any]]:
        """Return models with availability status (idle/available first)."""
        import yaml as _yaml
        with open(os.path.join(CONFIG_DIR, "models.yaml")) as f:
            cfg = _yaml.safe_load(f) or {}
        models = []
        for m in cfg.get("models", []):
            key_env = m.get("api_key_env", "")
            model_name = m.get("name", "")
            provider = m.get("provider", "")
            available = False
            if provider in ("anthropic", "openai", "google"):
                # API-key providers: assume available if key in env
                available = bool(os.environ.get(key_env, ""))
            elif key_env and self._nim.has_key(key_env):
                available = self._check_nim_available(key_env, model_name)
            models.append({
                "id": m.get("id"),
                "name": model_name,
                "provider": provider,
                "role": m.get("role"),
                "available": available,
                "api_key_env": key_env,
            })
        # Sort: available first
        models.sort(key=lambda x: (not x["available"], x["role"] != "supervisor"))
        return models

    def select_model_for_task(self, task_type: str) -> Optional[str]:
        """Pick the best available model for a task type.
        supervisor role -> triage/reasoning; worker -> execution.
        Falls back to deterministic if no NIM available.
        """
        models = self.get_available_models()
        if not models:
            return None
        # Prefer supervisor for triage, worker for execution
        preferred_role = "supervisor" if task_type == "triage" else "worker"
        for m in models:
            if m["available"] and m["role"] == preferred_role:
                return m["name"]
        for m in models:
            if m["available"]:
                return m["name"]
        return None  # no model available — will use deterministic fallback

    # ------------------------------------------------------------------
    # Index-aware retrieval
    # ------------------------------------------------------------------

    def _index_search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if not self.index_available:
            return []
        _PROJECT_SCRIPTS = os.path.join(_PROJECT_ROOT, "scripts")
        sys.path.insert(0, _PROJECT_SCRIPTS)
        try:
            from index_vault import search
            return search(query, top_k=top_k)
        except Exception:
            return []

    def _build_index_context(self, user_input: str) -> str:
        """Query index for relevant skills/hooks/systems and format as context."""
        results = self._index_search(user_input, top_k=8)
        if not results:
            return ""
        lines = ["## Relevant context from local index (skills, hooks, systems, vault):"]
        for r in results:
            kind = r.get("kind", "unknown")
            path = r.get("path", "")
            score = r.get("score", 0)
            lines.append(f"- [{kind}] {path} (relevance {score})")
        return "\n".join(lines)

    def _router_find(self, user_input: str, top_k: int = 5) -> list[dict]:
        """Ask the project's skill+agent router (router.py) which skills/agents fit this task.
        Returns matches with id, kind, status, path, sem, lex, score. Empty on failure."""
        router_py = os.path.join(HOME, ".agent-skills", "router", "router.py")
        if not os.path.exists(router_py):
            return []
        try:
            import subprocess, json as _json
            r = subprocess.run(
                ["python3", router_py, "find", user_input, "-k", str(top_k), "--json"],
                capture_output=True, text=True, timeout=30,
                cwd=os.path.join(HOME, ".agent-skills", "router"),
            )
            if r.returncode != 0:
                return []
            return _json.loads(r.stdout)
        except Exception:
            return []

    def _build_router_context(self, user_input: str) -> str:
        """Format router.py self-routing results as context for the triager."""
        matches = self._router_find(user_input, top_k=5)
        if not matches:
            return ""
        lines = ["## Self-routing from project skill+agent router (router.py):"]
        for m in matches:
            mid = m.get("id", "")
            kind = m.get("kind", "")
            status = m.get("status", "")
            score = m.get("sem", m.get("score", 0))
            path = m.get("path", "")
            lines.append(f"- [{kind}:{status}] {mid} (score {score:.2f}) — {path}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Config drift constraints
    # ------------------------------------------------------------------

    def _apply_drift_constraints(self, agent_id: Optional[str], model_name: Optional[str]) -> tuple[Optional[str], Optional[str], List[str]]:
        """Apply routing constraints from config drift. Returns (agent, model, warnings)."""
        warnings: List[str] = []
        constraints = self.drift.get("routing_constraints", [])
        model_routing = self.drift.get("model_routing", {})

        # Check agent constraints
        if agent_id:
            for c in constraints:
                if agent_id in c and "avoid" in c.lower():
                    warnings.append(f"Drift constraint: {c}")
                    agent_id = None  # block this agent
                    break

        # Check model constraints
        if model_name:
            mr = model_routing.get(model_name)
            if mr == "avoid-critical":
                warnings.append(f"Drift constraint: avoid critical routing via {model_name}")
                model_name = None

        return agent_id, model_name, warnings

    # ------------------------------------------------------------------
    # Graph construction (Phase 2: adds index_retrieval node before triager)
    # ------------------------------------------------------------------

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(RouterState)

        workflow.add_node("index_retrieval", self.index_retrieval_node)
        workflow.add_node("triager", self.triager_node)
        workflow.add_node("gate_keeper", self.gate_keeper_node)
        workflow.add_node("dispatcher", self.dispatcher_node)
        workflow.add_node("worker", self.worker_node)
        workflow.add_node("card_writer", self.card_writer_node)
        workflow.add_node("reviewer", self.reviewer_node)

        workflow.set_entry_point("index_retrieval")
        workflow.add_edge("index_retrieval", "triager")
        workflow.add_edge("triager", "gate_keeper")
        workflow.add_conditional_edges(
            "gate_keeper",
            self._gate_router,
            {"interrupt": END, "dispatch": "dispatcher"},
        )
        workflow.add_edge("dispatcher", "worker")
        workflow.add_edge("worker", "card_writer")
        workflow.add_edge("card_writer", "reviewer")
        workflow.add_conditional_edges(
            "reviewer",
            self._review_router,
            {"revision": "worker", "done": END},
        )

        from langgraph.checkpoint.memory import MemorySaver
        return workflow.compile(checkpointer=MemorySaver())

    def _gate_router(self, state: RouterState) -> str:
        return "interrupt" if state.get("interrupt_reason") else "dispatch"

    def _review_router(self, state: RouterState) -> str:
        return "revision" if state.get("status") == "review" else "done"

    # ------------------------------------------------------------------
    # Nodes (Phase 2)
    # ------------------------------------------------------------------

    def index_retrieval_node(self, state: RouterState) -> RouterState:
        """Query local index for relevant skills/hooks/systems before triage."""
        user_input = state["messages"][-1].content if state["messages"] else ""
        context = self._build_index_context(user_input)
        state["index_context"] = context
        return state

    def triager_node(self, state: RouterState) -> RouterState:
        """NIM supervisor classifies input with index context + model availability."""
        user_input = state["messages"][-1].content if state["messages"] else ""
        index_context = state.get("index_context", "")

        # Explicit dispatch overrides from Dispatch Cockpit UI — bypass auto-triage
        explicit_lane = state.get("lane")
        explicit_model = state.get("chosen_model")
        explicit_skills = state.get("explicit_skills")

        if explicit_lane:
            # Resolve agent for explicit lane from lanes.yaml
            lane_def = get_lane(explicit_lane) or {}
            lane_agents = lane_def.get("agents", [])
            # Find first available agent matching the lane
            chosen_agent = None
            for aid in lane_agents:
                for a in self.get_available_agents():
                    if a["id"] == aid and a["available"]:
                        chosen_agent = aid
                        break
                if chosen_agent:
                    break
            if not chosen_agent:
                # Fallback: any available agent
                for a in self.get_available_agents():
                    if a["available"]:
                        chosen_agent = a["id"]
                        break

            state["lane"] = explicit_lane
            state["agent"] = chosen_agent
            state["chosen_model"] = explicit_model
            state["status"] = "triaging"
            state["delegation_flow"] = [f"user -> {chosen_agent or 'none'} (explicit)"]
            state["project_vision"] = state.get("project_vision", "")
            state["direct_market"] = state.get("direct_market", "")
            state["value_exchange"] = state.get("value_exchange", "")
            state["action_chain"] = state.get("action_chain", "")
            state["next_step"] = state.get("next_step", "")
            # Merge explicit skills with index context
            state["skills_override"] = explicit_skills or []
            return state

        agents = self.get_available_agents()
        # Apply drift constraints to filter agents
        drift_constraints = self.drift.get("routing_constraints", [])
        available_agent_ids = []
        for a in agents:
            aid = a["id"]
            blocked = any(aid in c and "avoid" in c.lower() for c in drift_constraints)
            if not blocked and a["available"]:
                available_agent_ids.append(aid)

        lanes = load_lanes()
        projects = load_projects_for_triage()
        skills = load_all_skills()
        skills_json = json.dumps([{"id": s["id"], "description": s["description"]} for s in skills], indent=2)

        # Model availability for triage
        triage_model = self.select_model_for_task("triage")
        model_note = f"Using model: {triage_model}" if triage_model else "No model available — deterministic fallback"

        router_context = self._build_router_context(user_input)

        system_prompt = f"""You are a triage supervisor with project comprehension for a multi-agent system.

PROJECT COMPREHENSION FRAMEWORK:
Before routing, understand:
1. PROJECT VISION — what is the user trying to build or achieve? What is the deliverable?
2. DIRECT MARKET — who is the buyer/user? What is the quid-pro-quo value exchange?
3. ACTION CHAIN — which model/agent reasons, which gathers resources, which manages execution, where is vision held?
4. NEXT STEP — immediate concrete action moving the project forward.

SELF-ROUTING (from project skill+agent router — use these to pick the right skill/agent/model):
{router_context if router_context else "No router matches found — use available agents/skills below."}

INDEX CONTEXT (relevant local skills, hooks, systems, vault):
{index_context if index_context else "No relevant local context found."}

AVAILABLE AGENTS (drift-constrained, available first):
{json.dumps([a for a in agents if a["id"] in available_agent_ids], indent=2)}

AVAILABLE LANES:
{json.dumps(lanes, indent=2)}

AVAILABLE PROJECTS:
{json.dumps(projects, indent=2)}

AVAILABLE SKILLS:
{skills_json}

MODEL NOTE: {model_note}

TASK: Classify the user's input and decide:
1. Which lane should handle this?
2. Which agent should execute it? (must be in available_agent_ids above)
3. Which project? (null if unclear → ask user)
4. Which skills should the agent read first? (from index context + skills list)
5. Project comprehension: vision, market, value exchange, action chain, next step

Respond with JSON only: {{"lane": "...", "agent": "...", "project": "...", "skills": [...], "reasoning": "...", "project_vision": "...", "direct_market": "...", "value_exchange": "...", "action_chain": "...", "next_step": "..."}}

If project is unclear, set project to null. If no agent available, say so in reasoning."""

        response = self._call_llm(system_prompt, user_input, task_type="triage")

        try:
            decision = json.loads(response)
        except json.JSONDecodeError:
            decision = {
                "lane": "planner",
                "agent": available_agent_ids[0] if available_agent_ids else "claude",
                "project": None,
                "skills": [],
                "reasoning": "Failed to parse LLM response, defaulting to planner",
                "project_vision": "", "direct_market": "", "value_exchange": "",
                "action_chain": "", "next_step": "",
            }

        chosen_agent = decision.get("agent", "claude")
        chosen_model = None
        # Map agent to model from agents.yaml
        import yaml as _yaml
        with open(os.path.join(CONFIG_DIR, "agents.yaml")) as f:
            agents_cfg = _yaml.safe_load(f) or {}
        for a in agents_cfg.get("agents", []):
            if a.get("id") == chosen_agent:
                chosen_model = a.get("model")
                break

        # Apply drift constraints
        chosen_agent, chosen_model, drift_warnings = self._apply_drift_constraints(chosen_agent, chosen_model)
        if drift_warnings:
            decision["reasoning"] = decision.get("reasoning", "") + " | " + "; ".join(drift_warnings)

        # If drift blocked the chosen agent, fall back to another available agent
        if not chosen_agent and available_agent_ids:
            for fallback in available_agent_ids:
                fb_agent, fb_model, fw = self._apply_drift_constraints(fallback, None)
                if fb_agent:
                    chosen_agent = fallback
                    chosen_model = fb_model
                    drift_warnings = (drift_warnings or []) + list(fw)
                    decision["reasoning"] = decision.get("reasoning", "") + " | drifted to fallback " + fallback
                    break

        # If chosen agent is an interactive CLI blocked in unattended mode,
        # fall back to a NIM agent (direct API, no TTY needed)
        if chosen_agent and not self.interactive_mode:
            from graph.agent_base import CLIAgent
            if chosen_agent in CLIAgent.INTERACTIVE_CLIS:
                # Find a NIM agent as fallback
                nim_agents = [a for a in available_agent_ids if a.startswith("nim")]
                if nim_agents:
                    chosen_agent = nim_agents[0]
                    # Map to model
                    import yaml as _yaml
                    with open(os.path.join(CONFIG_DIR, "agents.yaml")) as f:
                        agents_cfg = _yaml.safe_load(f) or {}
                    for a in agents_cfg.get("agents", []):
                        if a.get("id") == chosen_agent:
                            chosen_model = a.get("model")
                            break
                    decision["reasoning"] = decision.get("reasoning", "") + " | fell back to NIM agent (interactive CLI blocked in unattended mode)"

        state["lane"] = decision.get("lane", "planner")
        state["agent"] = chosen_agent
        state["project"] = decision.get("project")
        state["delegation_flow"] = [f"user -> {chosen_agent or 'none'}"]
        state["status"] = "triaging"
        state["project_vision"] = decision.get("project_vision", "")
        state["direct_market"] = decision.get("direct_market", "")
        state["value_exchange"] = decision.get("value_exchange", "")
        state["action_chain"] = decision.get("action_chain", "")
        state["next_step"] = decision.get("next_step", "")
        state["chosen_model"] = chosen_model

        return state

    def _call_llm(self, system_prompt: str, user_input: str, task_type: str = "triage") -> str:
        """Call the best available model for the task type."""
        model_name = self.select_model_for_task(task_type)
        if not model_name:
            return self._deterministic_triage(user_input)
        try:
            # Use nim_call for NIM models; langchain for others
            if model_name.startswith("nvidia/") or "nemotron" in model_name:
                # Find the key env for this model
                import yaml as _yaml
                with open(os.path.join(CONFIG_DIR, "models.yaml")) as f:
                    mc = _yaml.safe_load(f) or {}
                key_env = None
                for m in mc.get("models", []):
                    if m.get("name") == model_name:
                        key_env = m.get("api_key_env")
                        break
                resp = self._nim.call_with_retry(
                    [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_input}],
                    model=model_name,
                    timeout=120,
                    max_tokens=4096,
                    attempts=3,
                    preferred=key_env,
                )
                return resp.get("content", "") or ""
            else:
                # Anthropic/OpenAI/Google via langchain or direct
                return self._call_non_nim_llm(system_prompt, user_input, model_name)
        except Exception:
            return self._deterministic_triage(user_input)

    def _call_non_nim_llm(self, system_prompt: str, user_input: str, model_name: str) -> str:
        """Call non-NIM model (Claude, Codex via CLI, etc.)."""
        # For non-NIM models, delegate to the agent CLI directly
        # This is handled in worker_node; here we just return a routing hint
        return json.dumps({
            "route_to": "agent_cli",
            "model": model_name,
            "system_prompt": system_prompt,
            "user_input": user_input,
        })

    def _deterministic_triage(self, user_input: str) -> str:
        lower = user_input.lower()
        # Prefer NIM agents (direct API, no TTY needed) in unattended mode
        nim_agents = ["nim3", "nim2", "nim1"]
        if any(w in lower for w in ["build", "code", "implement", "fix", "refactor"]):
            lane = "build"
            agent = nim_agents[0] if not self.interactive_mode else "codex"
        elif any(w in lower for w in ["review", "roast", "audit", "check"]):
            lane = "review-roast"
            agent = nim_agents[0] if not self.interactive_mode else "codex"
        elif any(w in lower for w in ["research", "search", "find", "web"]):
            lane = "research-public"
            agent = nim_agents[0]
        else:
            lane = "planner"
            agent = nim_agents[0] if not self.interactive_mode else "claude"
        return json.dumps({
            "lane": lane,
            "agent": agent,
            "project": None,
            "skills": [],
            "reasoning": "Deterministic fallback (no model available)",
        })

    def gate_keeper_node(self, state: RouterState) -> RouterState:
        user_input = state["messages"][-1].content if state["messages"] else ""
        gate_words = ["send", "spend", "deploy", "approve", "submit", "push", "delete", "auth",
                      "vault-write", "vault_write"]
        lower = user_input.lower()
        for word in gate_words:
            if word in lower:
                state["interrupt_reason"] = f"Gate word '{word}' detected — requires owner approval"
                state["status"] = "blocked"
                interrupt({
                    "type": "gate_approval",
                    "gate_word": word,
                    "message": f"This action requires '{word}' approval. Approve to proceed?",
                    "state": dict(state),
                })
                break
        return state

    def dispatcher_node(self, state: RouterState) -> RouterState:
        lane = state["lane"]
        agent = state["agent"]
        project = state["project"]
        user_input = state["messages"][-1].content if state["messages"] else ""

        lane_def = get_lane(lane) or {}
        skills = lane_def.get("skills", [])
        # Merge index-retrieved skills
        index_context = state.get("index_context", "")
        if index_context:
            skills = list(dict.fromkeys(skills + ["index-retrieved"]))
        acceptance = lane_def.get("acceptance", "run acceptance check")

        packet = build_packet(
            lane_id=lane,
            agent_id=agent,
            project_id=project or "global",
            user_input=user_input,
            skills=skills,
        )
        packet["lane_def"] = lane_def
        packet["index_context"] = index_context
        packet["chosen_model"] = state.get("chosen_model")
        packet["task_id"] = str(uuid.uuid4())[:8]

        state["packet"] = packet
        state["status"] = "running"
        return state

    def worker_node(self, state: RouterState) -> RouterState:
        packet = state["packet"]
        agent_id = state["agent"]

        # Circuit breaker + fallback selection
        selected_agent = self._select_agent_with_fallback(agent_id, state.get("lane", ""))
        if selected_agent != agent_id:
            state["agent"] = selected_agent
            agent_id = selected_agent
            state["delegation_flow"].append(f"fallback -> {agent_id}")

        # Trust tier + vault sandbox check
        if state.get("packet", {}).get("vault_write") and not self._agent_has_vault_write(agent_id):
            state["result"] = f"Error: agent {agent_id} lacks vault-write trust tier"
            state["status"] = "blocked"
            self._cb_record_failure(agent_id)
            return state

        agent = self.agents.get(agent_id)
        if not agent:
            cfg = load_agent_config(agent_id)
            if cfg:
                agent = create_agent(agent_id, cfg)
                self.agents[agent_id] = agent
            else:
                state["result"] = f"Error: agent {agent_id} not found in registry"
                state["status"] = "blocked"
                self._cb_record_failure(agent_id)
                return state

        if not agent.is_available():
            state["result"] = f"Error: agent {agent_id} not available"
            state["status"] = "blocked"
            self._cb_record_failure(agent_id)
            return state

        system_prompt = render_system_prompt(packet)
        packet["system_prompt"] = system_prompt

        import time as _time
        t0 = _time.time()
        try:
            result = agent.dispatch(packet)
            # Interactive CLI agents return an error string in unattended mode
            # Fall back to a NIM agent instead of failing
            if ("is interactive and" in result and "interactive_mode is disabled" in result):
                # Fall back to NIM agent
                nim_fallback = None
                for aid in ["nim3", "nim2", "nim1"]:
                    if aid in self.agents and self._cb_can_call(aid):
                        nim_fallback = aid
                        break
                if nim_fallback:
                    state["delegation_flow"].append(f"interactive-fallback -> {nim_fallback}")
                    agent = self.agents.get(nim_fallback)
                    if not agent:
                        cfg = load_agent_config(nim_fallback)
                        if cfg:
                            agent = create_agent(nim_fallback, cfg)
                            self.agents[nim_fallback] = agent
                    system_prompt = render_system_prompt(packet)
                    packet["system_prompt"] = system_prompt
                    result = agent.dispatch(packet)
                    latency_ms = int((_time.time() - t0) * 1000)
                    state["agent"] = nim_fallback
                    agent_id = nim_fallback
                    state["delegation_flow"].append(f"{nim_fallback} -> completed")
                    self._cb_record_success(nim_fallback)
                else:
                    state["result"] = result
                    state["status"] = "blocked"
                    self._cb_record_failure(agent_id)
                    return state

            # NIM agents cannot write files — extract code blocks from output
            # and write them to disk so results are real, not fabricated.
            agent_obj = self.agents.get(agent_id) or create_agent(agent_id, load_agent_config(agent_id) or {})
            if not agent_obj.can_write():
                harness_path = _PROJECT_SCRIPTS
                sys.path.insert(0, harness_path)
                from agent_harness import AgentHarness
                harness = AgentHarness()
                written = harness._write_code_blocks(result, workdir=_PROJECT_ROOT)
                # Verify claimed files using harness's canonical extractor
                claimed = harness.extract_claimed_files(result) + written
                verification = harness.verify_claimed_files(claimed, agent_can_write=False)
                state["delegation_flow"].append(f"wrote {len(written)} file(s); verified {sum(1 for v in verification.values() if v == 'verified')}/{len(claimed)}")
            else:
                written = []
                claimed = []
                verification = {}

            latency_ms = int((_time.time() - t0) * 1000)
            state["result"] = result
            state["status"] = "done"
            state["delegation_flow"].append(f"{agent_id} -> completed")
            state["tokens_spent"] = (len(json.dumps(packet)) + len(result)) // 4
            # Observability: trace entry
            state.setdefault("trace_log", []).append({
                "trace_id": self.trace_id,
                "span_id": str(uuid.uuid4())[:8],
                "agent_id": agent_id,
                "step": len(state.get("trace_log", [])) + 1,
                "latency_ms": latency_ms,
                "status": "success",
            })
            self._cb_record_success(agent_id)
        except Exception as e:
            latency_ms = int((_time.time() - t0) * 1000)
            state["result"] = f"Error: {e}"
            state["status"] = "blocked"
            state.setdefault("trace_log", []).append({
                "trace_id": self.trace_id,
                "span_id": str(uuid.uuid4())[:8],
                "agent_id": agent_id,
                "step": len(state.get("trace_log", [])) + 1,
                "latency_ms": latency_ms,
                "status": "failure",
                "error": str(e),
            })
            self._cb_record_failure(agent_id)

        return state

    def _agent_has_vault_write(self, agent_id: str) -> bool:
        """Check trust tier: which agents can write to vault sandbox."""
        import yaml as _yaml
        with open(os.path.join(CONFIG_DIR, "agents.yaml")) as f:
            cfg = _yaml.safe_load(f) or {}
        for a in cfg.get("agents", []):
            if a.get("id") == agent_id:
                return a.get("write_access", False)
        return False

    def card_writer_node(self, state: RouterState) -> RouterState:
        packet = state["packet"]
        result = state["result"]
        agent_id = state["agent"]
        lane = state["lane"]
        project = state["project"]
        tokens = state["tokens_spent"]

        # Post-dispatch verification: check claimed files against disk
        agent_obj = self.agents.get(agent_id) or create_agent(agent_id, load_agent_config(agent_id) or {})
        has_file_write = agent_obj.can_write()
        claimed = agent_obj.claimed_files(result) if result else []

        verification: dict[str, str] = {}
        for path in claimed:
            expanded = os.path.expanduser(path)
            if os.path.exists(expanded):
                verification[path] = "verified"
            else:
                verification[path] = "not-found" if has_file_write else "fabricated-no-write-tool"

        card = {
            "title": packet.get("goal", "Untitled task")[:100],
            "lane": lane,
            "agent": agent_id,
            "model": packet.get("agent_config", {}).get("model", state.get("chosen_model", "unknown")),
            "status": state["status"],
            "project": project,
            "prompt_sent": render_system_prompt(packet)[:500],
            "output": result,
            "tokens_spent": tokens,
            "project_vision": state.get("project_vision", ""),
            "direct_market": state.get("direct_market", ""),
            "value_exchange": state.get("value_exchange", ""),
            "action_chain": state.get("action_chain", ""),
            "next_step": state.get("next_step", ""),
            "claimed_files": claimed,
            "file_verification": verification,
        }

        card_id = create_card(card)
        state["current_card"] = {**card, "id": card_id}
        add_delegation_flow(card_id, None, agent_id, "created")
        add_delegation_flow(card_id, state["delegation_flow"][-2] if len(state["delegation_flow"]) > 1 else None, agent_id, "dispatched")
        # Get agent model for token usage tracking
        _agent = self.agents.get(agent_id) or create_agent(agent_id, load_agent_config(agent_id) or {})
        add_token_usage(card_id, agent_id, _agent.model if _agent and _agent.model != "unknown" else state.get("chosen_model", "unknown"), state["tokens_spent"])
        return state

    def reviewer_node(self, state: RouterState) -> RouterState:
        if state["status"] == "done" and state.get("current_card"):
            try:
                card = get_card(state["current_card"]["id"])
                if not card:
                    return state

                # Primary judge: NIM 3
                nim_result = None
                if self.llm:
                    nim_result = evaluate_card(card, self.llm)

                # Second judge: gemini API (different model family for cross-weighting)
                gemini_result = self._evaluate_with_gemini_api(card)

                # Combine: prefer consensus, flag divergence
                combined = self._combine_evaluations(nim_result, gemini_result)

                if combined.get("status") == "evaluated":
                    store_evaluation(state["current_card"]["id"], combined)
                    add_comment(
                        state["current_card"]["id"],
                        "system",
                        f"Evaluation: {combined['verdict']} (score {combined['overall_score']}/5, "
                        f"judges: {combined.get('judges', 'nim3')}, "
                        f"divergence: {combined.get('divergence', 0):.2f})",
                    )
                    # Auto-generate drift proposals when enough evaluations exist
                    self._maybe_generate_drift()
            except Exception:
                pass
        return state

    def _evaluate_with_gemini_api(self, card: dict) -> dict:
        """Second PEEM judge via Gemini direct API — different model family from NIM 3."""
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if not gemini_key:
            return {"status": "skipped", "reason": "no GEMINI_API_KEY"}

        prompt_sent = card.get("prompt_sent", "") or ""
        output = card.get("output", "") or ""

        eval_prompt = f"""You are an expert evaluator. Score this agent response on PEEM criteria (1-5 each):

1. Accuracy - Is the information correct and factually grounded?
2. Coherence - Does the response flow logically and stay on topic?
3. Relevance - Does it directly answer the user's request?
4. Objectivity - Is it unbiased, not manufactured?
5. Clarity - Is it clear, well-structured, easy to understand?
6. Conciseness - Is it concise, without filler or verbosity?

USER REQUEST: {prompt_sent[:2000]}

AGENT OUTPUT: {output[:4000]}

Respond with valid JSON only:
{{
  "accuracy": <1-5>,
  "coherence": <1-5>,
  "relevance": <1-5>,
  "objectivity": <1-5>,
  "clarity": <1-5>,
  "conciseness": <1-5>,
  "strengths": [],
  "weaknesses": [],
  "improvement": ""
}}"""

        try:
            import urllib.request, json as _json
            payload = {
                "contents": [{"parts": [{"text": eval_prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
            }
            data = _json.dumps(payload).encode()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = _json.loads(resp.read().decode())
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            import re
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                scores = _json.loads(m.group(0))
                PEEM_CRITERIA_LOCAL = ["accuracy", "coherence", "relevance", "objectivity", "clarity", "conciseness"]
                normalized = {}
                for crit in PEEM_CRITERIA_LOCAL:
                    val = scores.get(crit, 3)
                    try:
                        normalized[crit] = max(1, min(5, int(val)))
                    except (ValueError, TypeError):
                        normalized[crit] = 3
                overall = sum(normalized.values()) / len(normalized)
                verdict = "PASS" if overall >= 4.0 else ("PASS_WITH_NOTES" if overall >= 3.0 else "FAIL")
                return {
                    "card_id": card["id"],
                    "agent": card.get("agent", "unknown"),
                    "model": "gemini-2.0-flash",
                    "peem_scores": normalized,
                    "overall_score": round(overall, 2),
                    "verdict": verdict,
                    "strengths": scores.get("strengths", []),
                    "weaknesses": scores.get("weaknesses", []),
                    "improvement": scores.get("improvement", ""),
                    "status": "evaluated",
                    "judge": "gemini",
                }
        except Exception:
            pass
        return {"status": "error", "judge": "gemini"}

    def _combine_evaluations(self, nim_result: dict | None, gemini_result: dict | None) -> dict:
        """Combine NIM 3 and gemini PEEM evaluations. Flag divergence between judges."""
        if not nim_result or nim_result.get("status") != "evaluated":
            if gemini_result and gemini_result.get("status") == "evaluated":
                return {**gemini_result, "judges": "gemini-only", "divergence": None}
            return {"status": "error", "reason": "no judge produced evaluation"}

        if not gemini_result or gemini_result.get("status") != "evaluated":
            return {**nim_result, "judges": "nim3-only", "divergence": None}

        nim_score = nim_result["overall_score"]
        gem_score = gemini_result["overall_score"]
        divergence = abs(nim_score - gem_score)

        # Consensus: average the two scores
        combined_score = round((nim_score + gem_score) / 2, 2)
        combined_verdict = "PASS" if combined_score >= 4.0 else ("PASS_WITH_NOTES" if combined_score >= 3.0 else "FAIL")

        # Average per-criterion
        nim_peem = nim_result.get("peem_scores", {})
        gem_peem = gemini_result.get("peem_scores", {})
        PEEM_CRITERIA_LOCAL = ["accuracy", "coherence", "relevance", "objectivity", "clarity", "conciseness"]
        combined_peem = {}
        for crit in PEEM_CRITERIA_LOCAL:
            n = nim_peem.get(crit, 3)
            g = gem_peem.get(crit, 3)
            combined_peem[crit] = round((n + g) / 2, 2)

        return {
            "card_id": nim_result["card_id"],
            "agent": nim_result.get("agent", "unknown"),
            "model": "nim3+gemini",
            "peem_scores": combined_peem,
            "overall_score": combined_score,
            "verdict": combined_verdict,
            "strengths": nim_result.get("strengths", []) + gemini_result.get("strengths", []),
            "weaknesses": nim_result.get("weaknesses", []) + gemini_result.get("weaknesses", []),
            "improvement": nim_result.get("improvement", "") or gemini_result.get("improvement", ""),
            "status": "evaluated",
            "judges": "nim3+gemini",
            "divergence": round(divergence, 2),
            "nim3_score": nim_score,
            "gemini_score": gem_score,
        }

    def _maybe_generate_drift(self) -> None:
        """Auto-generate config drift proposals when evaluation count crosses threshold."""
        try:
            _PROJECT_SCRIPTS = os.path.join(_PROJECT_ROOT, "scripts")
            sys.path.insert(0, _PROJECT_SCRIPTS)
            from config_drift import _load_evals, analyze, generate_drift, write_drift, AVG_SCORE_WARN, MIN_CARDS_FOR_DRIFT
            evals = _load_evals()
            if len(evals) < MIN_CARDS_FOR_DRIFT:
                return
            analysis = analyze(evals)
            drift = generate_drift(analysis)
            write_drift(drift)
            # Reload drift into supervisor so constraints take effect immediately
            self.drift = drift
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, user_input: str, project: Optional[str] = None,
            lane: Optional[str] = None, model: Optional[str] = None,
            skills: Optional[List[str]] = None) -> Dict[str, Any]:
        """Run a task through the supervisor.

        Explicit overrides (lane, model, skills) bypass automatic triage
        selection — used by the Dispatch Cockpit UI for user-controlled routing.
        """
        self.state = self._empty_state()
        self.state["messages"] = [HumanMessage(content=user_input)]
        self.state["project"] = project
        # Explicit dispatch overrides from the Dispatch Cockpit UI
        if lane is not None:
            self.state["lane"] = lane
        if model is not None:
            self.state["chosen_model"] = model
        if skills is not None:
            self.state["explicit_skills"] = skills
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        try:
            result = self.graph.invoke(self.state, config=config)
            # LangGraph interrupts: __interrupt__ key carries gate reason
            interrupt_reason = result.get("interrupt_reason")
            if not interrupt_reason and "__interrupt__" in result:
                try:
                    interrupt_reason = result["__interrupt__"][0].value.get("message", "")
                except Exception:
                    interrupt_reason = str(result["__interrupt__"][0].value)
            return {
                "status": result.get("status", "unknown"),
                "lane": result.get("lane"),
                "agent": result.get("agent"),
                "project": result.get("project"),
                "result": result.get("result"),
                "card": result.get("current_card"),
                "tokens_spent": result.get("tokens_spent", 0),
                "delegation_flow": result.get("delegation_flow", []),
                "interrupt_reason": interrupt_reason,
                "index_context": result.get("index_context", ""),
                "chosen_model": result.get("chosen_model"),
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "interrupt_reason": str(e),
            }

    def get_agents(self) -> List[Dict[str, Any]]:
        return self.get_available_agents()

    def get_token_analytics(self) -> dict:
        """Get token usage analytics per agent, model, and lane with optimization suggestions."""
        import sqlite3
        db_path = os.path.join(_PROJECT_ROOT, "kanban.db")
        if not os.path.exists(db_path):
            return {"error": "No database found"}
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("""
                SELECT c.agent, c.model, c.lane,
                       SUM(c.tokens_spent) as total_tokens,
                       COUNT(*) as card_count,
                       AVG(c.tokens_spent) as avg_tokens
                FROM cards c
                WHERE c.tokens_spent > 0
                GROUP BY c.agent, c.model, c.lane
                ORDER BY total_tokens DESC
            """).fetchall()
            result = {
                "by_agent_model_lane": [dict(r) for r in rows],
                "total_tokens": sum(r["total_tokens"] for r in rows),
                "optimization_suggestions": [],
            }
            # Optimization: flag high-token agents that could use NIM instead
            for r in rows:
                if r["total_tokens"] > 5000 and r["agent"] in ("claude", "codex"):
                    result["optimization_suggestions"].append({
                        "type": "route_to_nim",
                        "agent": r["agent"],
                        "model": r["model"],
                        "lane": r["lane"],
                        "current_tokens": r["total_tokens"],
                        "suggestion": f"Consider routing {r['lane']} tasks from {r['agent']} to NIM agents to reduce token usage",
                    })
            return result
        except sqlite3.OperationalError:
            return {"error": "Cards table not found or missing tokens_spent column"}
        finally:
            conn.close()


def load_projects_for_triage() -> List[Dict[str, Any]]:
    path = os.path.join(CONFIG_DIR, "projects.yaml")
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    return [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "path": p.get("path"),
            "type": p.get("type"),
            "default_agent": p.get("default_agent"),
        }
        for p in cfg.get("projects", [])
    ]
