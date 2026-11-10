"""LangGraph supervisor — NIM 3 reasoning layer that classifies input, picks
the right agent + skill + MCP + project, builds a dispatch packet, launches
the agent, writes a Kanban card, and streams results back.

Config-driven: agents, skills, lanes, models, projects all discovered from
YAML files + environment, not hardcoded.
"""
from __future__ import annotations

import os
import sys
import json
import uuid
import yaml
from typing import Dict, Any, Optional, List
from pathlib import Path

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))

from graph.state import RouterState
from graph.agent_base import create_agent, load_agent_config, AGENT_CLASSES
from graph.prompt_library import (
    build_packet, render_system_prompt, load_all_skills,
    load_lanes, load_project_context, get_lane,
)
from graph.evaluation import evaluate_card, store_evaluation, load_llm_judge
from db import create_card, get_card, list_cards, add_comment, add_delegation_flow, add_token_usage, get_analytics

CONFIG_DIR = os.path.join(HOME, "Developer", "agent-router", "config")


class RouterSupervisor:
    """LangGraph-based multi-agent supervisor with NIM 3 reasoning."""

    def __init__(self):
        self.state: RouterState = self._empty_state()
        self.graph = self._build_graph()
        self.llm = self._init_judge_llm()
        self.agents: Dict[str, Any] = {}
        self._load_agent_registry()

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
        )

    def _init_judge_llm(self):
        """NIM 3 as the LLM judge for evaluation."""
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

    def _load_agent_registry(self):
        """Load all agent configs and instantiate Agent objects."""
        import yaml
        path = os.path.join(CONFIG_DIR, "agents.yaml")
        with open(path) as f:
            cfg = yaml.safe_load(f) or {}
        for a in cfg.get("agents", []):
            aid = a.get("id")
            if aid:
                self.agents[aid] = create_agent(aid, a)

    def get_available_agents(self) -> List[Dict[str, Any]]:
        """Return list of agents with availability status."""
        return [
            {
                "id": aid,
                "cli": agent.cli,
                "model": agent.model,
                "provider": agent.provider,
                "write_access": agent.write_access,
                "available": agent.is_available(),
                "route_reasons": agent.route_reasons,
                "skills": agent.skills,
                "note": agent.note,
            }
            for aid, agent in self.agents.items()
        ]

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(RouterState)

        workflow.add_node("triager", self.triager_node)
        workflow.add_node("gate_keeper", self.gate_keeper_node)
        workflow.add_node("dispatcher", self.dispatcher_node)
        workflow.add_node("worker", self.worker_node)
        workflow.add_node("card_writer", self.card_writer_node)
        workflow.add_node("reviewer", self.reviewer_node)

        workflow.set_entry_point("triager")
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

        return workflow.compile()

    def _gate_router(self, state: RouterState) -> str:
        return "interrupt" if state.get("interrupt_reason") else "dispatch"

    def _review_router(self, state: RouterState) -> str:
        return "revision" if state.get("status") == "review" else "done"

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def triager_node(self, state: RouterState) -> RouterState:
        """NIM 3 supervisor classifies input and selects lane/agent/project."""
        user_input = state["messages"][-1].content if state["messages"] else ""

        agents = self.get_available_agents()
        lanes = load_lanes()
        projects = load_projects_for_triage()
        skills = load_all_skills()

        system_prompt = f"""You are a triage supervisor for a multi-agent system.

AVAILABLE AGENTS (with availability):
{json.dumps(agents, indent=2)}

AVAILABLE LANES:
{json.dumps(lanes, indent=2)}

AVAILABLE PROJECTS:
{json.dumps(projects, indent=2)}

AVAILABLE SKILLS:
{json.dumps([{"id": s["id"], "description": s["description"]} for s in skills], indent=2)}

TASK: Classify the user's input and decide:
1. Which lane should handle this?
2. Which agent should execute it? (must be available: cli_found=True or api_key set)
3. Which project should this be associated with? (null if unclear → ask user)
4. What skills should the agent read first?

Respond with JSON only: {{"lane": "...", "agent": "...", "project": "...", "skills": [...], "reasoning": "..."}}

If project is unclear, set project to null. If no agent is available for the chosen lane, say so in reasoning."""

        response = self._call_llm(system_prompt, user_input)

        try:
            decision = json.loads(response)
        except json.JSONDecodeError:
            decision = {
                "lane": "planner",
                "agent": "claude",
                "project": None,
                "skills": [],
                "reasoning": "Failed to parse LLM response, defaulting to planner",
            }

        state["lane"] = decision.get("lane", "planner")
        state["agent"] = decision.get("agent", "claude")
        state["project"] = decision.get("project")
        state["delegation_flow"] = [f"user -> {decision.get('agent', 'claude')}"]
        state["status"] = "triaging"

        return state

    def _call_llm(self, system_prompt: str, user_input: str) -> str:
        """Call NIM 3 for triage reasoning."""
        try:
            from langchain_nvidia_ai_endpoints import ChatNVIDIA
            api_key = os.environ.get("NIM_3", "")
            if not api_key:
                # Fallback: deterministic classification
                return self._deterministic_triage(user_input)
            llm = ChatNVIDIA(
                model="nvidia/nemotron-3.5-super-vl-120b-a12b",
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=api_key,
                temperature=0.2,
                max_tokens=1024,
            )
            resp = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_input),
            ])
            return resp.content if hasattr(resp, "content") else str(resp)
        except Exception:
            return self._deterministic_triage(user_input)

    def _deterministic_triage(self, user_input: str) -> str:
        """Fallback deterministic classification when NIM is unavailable."""
        lower = user_input.lower()
        if any(w in lower for w in ["build", "code", "implement", "fix", "refactor"]):
            lane, agent = "build", "codex"
        elif any(w in lower for w in ["review", "roast", "audit", "check"]):
            lane, agent = "review-roast", "codex"
        elif any(w in lower for w in ["research", "search", "find", "web"]):
            lane, agent = "research-public", "nim3"
        else:
            lane, agent = "planner", "claude"
        return json.dumps({
            "lane": lane,
            "agent": agent,
            "project": None,
            "skills": [],
            "reasoning": "Deterministic fallback (NIM unavailable)",
        })

    def gate_keeper_node(self, state: RouterState) -> RouterState:
        """Check for gate words requiring human approval."""
        user_input = state["messages"][-1].content if state["messages"] else ""
        gate_words = ["send", "spend", "deploy", "approve", "submit", "push", "delete", "auth"]
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
        """Build the dispatch packet using the prompt library."""
        lane = state["lane"]
        agent = state["agent"]
        project = state["project"]
        user_input = state["messages"][-1].content if state["messages"] else ""

        lane_def = get_lane(lane) or {}
        skills = lane_def.get("skills", [])
        acceptance = lane_def.get("acceptance", "run acceptance check")

        packet = build_packet(
            lane_id=lane,
            agent_id=agent,
            project_id=project or "global",
            user_input=user_input,
            skills=skills,
        )
        packet["lane_def"] = lane_def

        state["packet"] = packet
        state["status"] = "running"

        return state

    def worker_node(self, state: RouterState) -> RouterState:
        """Dispatch the packet to the selected agent."""
        packet = state["packet"]
        agent_id = state["agent"]

        agent = self.agents.get(agent_id)
        if not agent:
            # Try to load dynamically
            cfg = load_agent_config(agent_id)
            if cfg:
                agent = create_agent(agent_id, cfg)
                self.agents[agent_id] = agent
            else:
                state["result"] = f"Error: agent {agent_id} not found in registry"
                state["status"] = "blocked"
                return state

        if not agent.is_available():
            state["result"] = f"Error: agent {agent_id} not available (CLI not found or API key missing)"
            state["status"] = "blocked"
            return state

        # Render system prompt from prompt library
        system_prompt = render_system_prompt(packet)

        # Inject system prompt into packet for the agent
        packet["system_prompt"] = system_prompt

        # Dispatch
        result = agent.dispatch(packet)
        state["result"] = result
        state["status"] = "done"
        state["delegation_flow"].append(f"{agent_id} -> completed")

        # Estimate tokens (rough: chars / 4)
        state["tokens_spent"] = (len(json.dumps(packet)) + len(result)) // 4

        # Record delegation flow in DB if we have a card
        if state.get("current_card"):
            add_delegation_flow(
                state["current_card"]["id"],
                state["delegation_flow"][-2] if len(state["delegation_flow"]) > 1 else None,
                agent_id,
                "dispatched",
            )
            add_token_usage(
                state["current_card"]["id"],
                agent_id,
                agent.model,
                state["tokens_spent"],
            )

        return state

    def card_writer_node(self, state: RouterState) -> RouterState:
        """Write the result to the Kanban database."""
        packet = state["packet"]
        result = state["result"]
        agent_id = state["agent"]
        lane = state["lane"]
        project = state["project"]
        tokens = state["tokens_spent"]

        card = {
            "title": packet.get("goal", "Untitled task")[:100],
            "lane": lane,
            "agent": agent_id,
            "model": packet.get("agent_config", {}).get("model", "unknown"),
            "status": state["status"],
            "project": project,
            "prompt_sent": render_system_prompt(packet)[:500],
            "output": result,
            "tokens_spent": tokens,
        }

        card_id = create_card(card)
        state["current_card"] = {**card, "id": card_id}

        # Add delegation flow entry
        add_delegation_flow(card_id, None, agent_id, "created")

        return state

    def reviewer_node(self, state: RouterState) -> RouterState:
        """Auto-approve for MVP; can be extended for human review."""
        if state["status"] == "done":
            # Optionally auto-evaluate with NIM 3 judge
            if self.llm and state.get("current_card"):
                try:
                    card = get_card(state["current_card"]["id"])
                    if card:
                        eval_result = evaluate_card(card, self.llm)
                        if eval_result.get("status") == "evaluated":
                            store_evaluation(state["current_card"]["id"], eval_result)
                            add_comment(
                                state["current_card"]["id"],
                                "system",
                                f"Evaluation: {eval_result['verdict']} (score {eval_result['overall_score']}/5)",
                            )
                except Exception:
                    pass  # Evaluation is best-effort
        return state

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, user_input: str, project: Optional[str] = None) -> Dict[str, Any]:
        """Run the supervisor graph with user input."""
        self.state = self._empty_state()
        self.state["messages"] = [HumanMessage(content=user_input)]
        self.state["project"] = project

        try:
            result = self.graph.invoke(self.state)
            return {
                "status": result.get("status", "unknown"),
                "lane": result.get("lane"),
                "agent": result.get("agent"),
                "project": result.get("project"),
                "result": result.get("result"),
                "card": result.get("current_card"),
                "tokens_spent": result.get("tokens_spent", 0),
                "delegation_flow": result.get("delegation_flow", []),
                "interrupt_reason": result.get("interrupt_reason"),
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "interrupt_reason": str(e),
            }

    def get_agents(self) -> List[Dict[str, Any]]:
        return self.get_available_agents()


def load_projects_for_triage() -> List[Dict[str, Any]]:
    """Load projects for the triager to choose from."""
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
