#!/usr/bin/env python3
"""PEEM feedback loop — feeds EOD review results back into triager prompts
and agent configurations. Run after EOD review to continuously improve routing.

Reads evaluation data from kanban.db, identifies worst-performing agents/lanes,
and writes updated triager system prompt sections + agent config notes.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HOME = os.path.expanduser("~")
VAULT = os.path.join(HOME, "memory-vault")
REPORTS_DIR = os.path.join(VAULT, "pages", "reports")
FEEDBACK_DIR = os.path.join(VAULT, "pages", "feedback")

sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))
from db.database import get_connection  # noqa: E402


def fetch_evaluation_data() -> dict:
    """Fetch all evaluations with card context."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT c.id, c.title, c.lane, c.agent, c.model, c.status,
                   c.project_vision, c.direct_market, c.value_exchange,
                   c.action_chain, c.next_step,
                   e.overall_score, e.verdict, e.accuracy, e.coherence,
                   e.relevance, e.objectivity, e.clarity, e.conciseness,
                   e.strengths, e.weaknesses, e.improvement,
                   c.output, c.prompt_sent
            FROM evaluations e
            JOIN cards c ON c.id = e.card_id
            ORDER BY e.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def analyze_by_agent(cards: list[dict]) -> dict:
    """Group evaluation data by agent, compute averages and patterns."""
    by_agent = {}
    for card in cards:
        agent = card.get("agent", "unknown")
        score = card.get("overall_score") or 0
        if agent not in by_agent:
            by_agent[agent] = {
                "scores": [], "cards": [], "weaknesses": [],
                "improvements": [], "verdicts": [],
            }
        by_agent[agent]["scores"].append(score)
        by_agent[agent]["cards"].append(card)
        if card.get("weaknesses"):
            try:
                w = json.loads(card["weaknesses"]) if isinstance(card["weaknesses"], str) else card["weaknesses"]
                by_agent[agent]["weaknesses"].extend(w if isinstance(w, list) else [w])
            except (json.JSONDecodeError, TypeError):
                pass
        if card.get("improvement"):
            by_agent[agent]["improvements"].append(card["improvement"])
        by_agent[agent]["verdicts"].append(card.get("verdict", "unknown"))

    result = {}
    for agent, data in by_agent.items():
        scores = data["scores"]
        result[agent] = {
            "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "card_count": len(scores),
            "fail_count": sum(1 for v in data["verdicts"] if v == "FAIL"),
            "top_weaknesses": _top_items(data["weaknesses"]),
            "top_improvements": _top_items(data["improvements"]),
            "worst_card": min(data["cards"], key=lambda c: c.get("overall_score") or 99) if data["cards"] else None,
        }
    return result


def analyze_by_lane(cards: list[dict]) -> dict:
    """Group evaluation data by lane."""
    by_lane = {}
    for card in cards:
        lane = card.get("lane", "unknown")
        score = card.get("overall_score") or 0
        if lane not in by_lane:
            by_lane[lane] = {"scores": [], "cards": [], "agents": set()}
        by_lane[lane]["scores"].append(score)
        by_lane[lane]["cards"].append(card)
        by_lane[lane]["agents"].add(card.get("agent", "unknown"))

    result = {}
    for lane, data in by_lane.items():
        scores = data["scores"]
        result[lane] = {
            "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "card_count": len(scores),
            "agents": list(data["agents"]),
        }
    return result


def _top_items(items: list, limit: int = 5) -> list:
    from collections import Counter
    return [item for item, _ in Counter(items).most_common(limit)]


def generate_feedback(agent_analysis: dict, lane_analysis: dict) -> dict:
    """Generate actionable feedback for triager prompts and agent configs."""
    feedback = {
        "agent_prompt_updates": {},
        "lane_acceptance_updates": {},
        "routing_constraints": [],
        "skill_recommendations": {},
        "summary": "",
    }

    # Agent-level: which agents need prompt/skill updates
    for agent, data in agent_analysis.items():
        if data["avg_score"] < 3.5:
            feedback["agent_prompt_updates"][agent] = {
                "issue": f"Avg PEEM score {data['avg_score']}/5 below 3.5 threshold",
                "top_weaknesses": data["top_weaknesses"],
                "top_improvements": data["top_improvements"],
                "recommended_action": "Review and update system prompt + skill briefs for this agent",
            }

    # Lane-level: which lanes need acceptance check updates
    for lane, data in lane_analysis.items():
        if data["avg_score"] < 3.5:
            feedback["lane_acceptance_updates"][lane] = {
                "issue": f"Lane {lane} avg score {data['avg_score']}/5 below threshold",
                "agents": data["agents"],
                "recommended_action": "Update lane acceptance criteria in config/lanes.yaml",
            }

    # Routing constraints: avoid routing to consistently failing agents
    failing_agents = [a for a, d in agent_analysis.items() if d["avg_score"] < 3.0 and d["card_count"] >= 2]
    if failing_agents:
        feedback["routing_constraints"] = [
            f"Avoid routing to {a} for critical tasks (avg {agent_analysis[a]['avg_score']}/5)"
            for a in failing_agents
        ]

    # Summary
    total = sum(d["card_count"] for d in agent_analysis.values())
    failing_count = len(failing_agents)
    feedback["summary"] = (
        f"Reviewed {total} evaluations across {len(agent_analysis)} agents. "
        f"{failing_count} agents below 3.0 threshold need routing constraints."
    )

    return feedback


def write_feedback_page(date_str: str, feedback: dict) -> str:
    """Write feedback page to vault."""
    Path(FEEDBACK_DIR).mkdir(parents=True, exist_ok=True)
    path = os.path.join(FEEDBACK_DIR, f"peem-feedback-{date_str}.md")
    lines = [
        f"# PEEM Feedback Loop — {date_str}",
        f"generated:: {__import__('datetime').datetime.now().isoformat()}",
        "type:: [[report]]",
        "area:: [[Ops]]",
        "status:: peem-feedback",
        "",
        "## Summary",
        feedback["summary"],
        "",
    ]

    if feedback["routing_constraints"]:
        lines.append("## Routing Constraints (apply to triager)")
        for c in feedback["routing_constraints"]:
            lines.append(f"- {c}")
        lines.append("")

    if feedback["agent_prompt_updates"]:
        lines.append("## Agent Prompt Updates")
        for agent, update in feedback["agent_prompt_updates"].items():
            lines.append(f"### {agent}")
            lines.append(f"- Issue: {update['issue']}")
            lines.append(f"- Top weaknesses: {', '.join(update['top_weaknesses'])}")
            lines.append(f"- Top improvements: {', '.join(update['top_improvements'])}")
            lines.append(f"- Action: {update['recommended_action']}")
            lines.append("")

    if feedback["lane_acceptance_updates"]:
        lines.append("## Lane Acceptance Updates")
        for lane, update in feedback["lane_acceptance_updates"].items():
            lines.append(f"### {lane}")
            lines.append(f"- Issue: {update['issue']}")
            lines.append(f"- Agents: {', '.join(update['agents'])}")
            lines.append(f"- Action: {update['recommended_action']}")
            lines.append("")

    lines.append("## Next")
    lines.append("- Apply agent prompt updates to graph/prompt_library.py render_system_prompt")
    lines.append("- Update lane acceptance criteria in config/lanes.yaml")
    lines.append("- Add routing constraints to triager system prompt")
    lines.append("- Re-run evaluation on improved cards to confirm progress")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    import datetime as dt
    date_str = dt.datetime.now().strftime("%Y-%m-%d")
    cards = fetch_evaluation_data()
    if not cards:
        print("No evaluations found — nothing to feed back.")
        return 0

    agent_analysis = analyze_by_agent(cards)
    lane_analysis = analyze_by_lane(cards)
    feedback = generate_feedback(agent_analysis, lane_analysis)
    path = write_feedback_page(date_str, feedback)
    print(f"PEEM feedback written: {path}")
    print(f"Evaluations: {len(cards)}, agents: {len(agent_analysis)}")
    print(f"Summary: {feedback['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
