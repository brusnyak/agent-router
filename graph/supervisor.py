"""LangGraph supervisor for the agent router."""
import os
import json
import uuid
from typing import Optional, Dict, Any, List
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_nvidia_ai_endpoints import ChatNVIDIA

from .state import RouterState
from .tools import (
    discover_agents,
    discover_skills,
    discover_lanes,
    discover_projects,
    discover_models,
    build_packet,
    dispatch_to_agent,
    check_gate_words,
)
import db as db_module

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(HOME, "Developer", "agent-router", "config")


class RouterSupervisor:
    def __init__(self):
        self.state: RouterState = RouterState(
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
        self.graph = self._build_graph()
        self.llm = self._init_llm()

    def _init_llm(self):
        """Initialize the supervisor LLM (NIM 3)."""
        models_cfg = discover_models()
        supervisor_model = None
        for m in models_cfg:
            if m.get("role") == "supervisor":
                supervisor_model = m
                break
        if not supervisor_model:
            supervisor_model = {
                "name": "nvidia/nemotron-3.5-super-vl-120b-a12b",
                "provider": "nim",
                "api_key_env": "NIM_3",
                "base_url": "https://integrate.api.nvidia.com/v1",
            }

        api_key = os.environ.get(supervisor_model.get("api_key_env", "NIM_3"), "")
        return ChatNVIDIA(
            model=supervisor_model["name"],
            base_url=supervisor_model.get("base_url", "https://integrate.api.nvidia.com/v1"),
            api_key=api_key,
            temperature=0.2,
            max_tokens=4096,
        )

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph supervisor graph."""
        workflow = StateGraph(RouterState)

        # Nodes
        workflow.add_node("triager", self.triager_node)
        workflow.add_node("dispatcher", self.dispatcher_node)
        workflow.add_node("worker", self.worker_node)
        workflow.add_node("reviewer", self.reviewer_node)
        workflow.add_node("gate_keeper", self.gate_keeper_node)
        workflow.add_node("card_writer", self.card_writer_node)

        # Edges
        workflow.set_entry_point("triager")
        workflow.add_edge("triager", "gate_keeper")
        workflow.add_conditional_edges(
            "gate_keeper",
            self._gate_router,
            {
                "interrupt": END,  # Wait for human approval
                "dispatch": "dispatcher",
            },
        )
        workflow.add_edge("dispatcher", "worker")
        workflow.add_edge("worker", "card_writer")
        workflow.add_edge("card_writer", "reviewer")
        workflow.add_conditional_edges(
            "reviewer",
            self._review_router,
            {
                "revision": "worker",
                "done": END,
            },
        )

        return workflow.compile()

    def _gate_router(self, state: RouterState) -> str:
        """Route after gate keeper check."""
        if state.get("interrupt_reason"):
            return "interrupt"
        return "dispatch"

    def _review_router(self, state: RouterState) -> str:
        """Route after review."""
        if state.get("status") == "review":
            return "revision"
        return "done"

    def triager_node(self, state: RouterState) -> RouterState:
        """NIM 3 supervisor classifies input and selects lane/agent/project."""
        user_input = state["messages"][-1].content if state["messages"] else ""

        # Load config
        agents = discover_agents()
        lanes = discover_lanes()
        projects = discover_projects()
        skills = discover_skills()

        # Build system prompt for triage
        system_prompt = f"""You are a triage supervisor for a multi-agent system.

AVAILABLE AGENTS:
{json.dumps(agents, indent=2)}

AVAILABLE LANES:
{json.dumps(lanes, indent=2)}

AVAILABLE PROJECTS:
{json.dumps(projects, indent=2)}

AVAILABLE SKILLS:
{json.dumps(skills, indent=2)}

TASK: Classify the user's input and decide:
1. Which lane (from available lanes) should handle this?
2. Which agent (from available agents) should execute it?
3. Which project should this be associated with? (ask if unclear)
4. What skills should the agent read first?

Respond with a JSON object: {{"lane": "...", "agent": "...", "project": "...", "skills": [...], "reasoning": "..."}}

If project is unclear, set project to null and we will ask the user."""

        # Call the LLM
        response = self.llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_input),
        ])

        try:
            decision = json.loads(response.content)
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

    def gate_keeper_node(self, state: RouterState) -> RouterState:
        """Check for gate words that require human approval."""
        user_input = state["messages"][-1].content if state["messages"] else ""
        gate_word = check_gate_words(user_input)

        if gate_word:
            state["interrupt_reason"] = f"Gate word '{gate_word}' detected — requires owner approval"
            state["status"] = "blocked"
            # Interrupt to wait for human
            interrupt({
                "type": "gate_approval",
                "gate_word": gate_word,
                "message": f"This action requires '{gate_word}' approval. Approve to proceed?",
                "state": state,
            })

        return state

    def dispatcher_node(self, state: RouterState) -> RouterState:
        """Build the packet and prepare for dispatch."""
        lane = state["lane"]
        agent = state["agent"]
        project = state["project"]
        user_input = state["messages"][-1].content if state["messages"] else ""

        lanes_cfg = discover_lanes()
        lane_def = next((l for l in lanes_cfg if l["id"] == lane), None)
        skills = lane_def.get("skills", []) if lane_def else []
        acceptance = lane_def.get("acceptance", "run acceptance check")
        forbidden = lane_def.get("never", ["send", "spend", "delete", "push", "auth/DNS/mail config"])

        # Load project context
        projects_cfg = discover_projects()
        project_def = next((p for p in projects_cfg if p["id"] == project or p["path"] == project), None) if project else None
        project_context = project_def or {}

        packet = build_packet(
            lane=lane,
            agent=agent,
            project=project or "global",
            user_input=user_input,
            skills=skills,
            acceptance=acceptance,
            forbidden=forbidden,
        )
        packet["project_context"] = project_context

        state["packet"] = packet
        state["status"] = "running"

        return state

    def worker_node(self, state: RouterState) -> RouterState:
        """Dispatch the packet to the selected agent."""
        packet = state["packet"]
        agent = state["agent"]
        lane = state["lane"]

        result = dispatch_to_agent(agent, packet, lane)
        state["result"] = result
        state["status"] = "done"
        state["delegation_flow"].append(f"{agent} -> completed")

        # Estimate tokens (rough)
        state["tokens_spent"] = len(json.dumps(packet)) + len(result)

        return state

    def card_writer_node(self, state: RouterState) -> RouterState:
        """Write the result to the Kanban database."""
        packet = state["packet"]
        result = state["result"]
        agent = state["agent"]
        lane = state["lane"]
        project = state["project"]
        tokens = state["tokens_spent"]

        card = {
            "title": packet.get("goal", "Untitled task")[:100],
            "lane": lane,
            "agent": agent,
            "model": packet.get("model", "unknown"),
            "status": state["status"],
            "project": project,
            "prompt_sent": json.dumps(packet)[:500],
            "output": result,
            "tokens_spent": tokens,
        }

        card_id = db_module.create_card(card)
        state["current_card"] = {**card, "id": card_id}

        return state

    def reviewer_node(self, state: RouterState) -> RouterState:
        """Review the result and decide if revision is needed."""
        # MVP: auto-approve, but can be extended
        if state["status"] == "done":
            state["status"] = "done"
        return state

    def run(self, user_input: str, project: Optional[str] = None) -> Dict[str, Any]:
        """Run the supervisor graph with user input."""
        self.state = RouterState(
            messages=[HumanMessage(content=user_input)],
            current_card=None,
            lane=None,
            agent=None,
            project=project,
            status="triaging",
            result=None,
            tokens_spent=0,
            delegation_flow=[],
            packet=None,
            interrupt_reason=None,
        )

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
