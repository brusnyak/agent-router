#!/usr/bin/env python3
"""End-of-day review system for the agent router.

Reviews worst-performing cards (low PEEM scores), identifies where/why/how
to improve, and feeds recommendations back into the reasoning system.

Output: pages/reports/eod-review-<date>.md in the vault.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

HOME = os.path.expanduser("~")
VAULT = os.path.join(HOME, "memory-vault")
REPORTS_DIR = os.path.join(VAULT, "pages", "reports")

sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))
from db.database import get_connection  # noqa: E402


def now_str() -> str:
    return dt.datetime.now().isoformat()


def fetch_low_scoring_cards(limit: int = 10) -> list[dict]:
    """Fetch cards with evaluations, ordered by lowest overall score."""
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
            ORDER BY e.overall_score ASC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def fetch_agent_performance() -> list[dict]:
    """Fetch evaluation analytics per agent."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT agent, model,
                   AVG(overall_score) as avg_score,
                   COUNT(*) as eval_count,
                   SUM(CASE WHEN verdict = 'FAIL' THEN 1 ELSE 0 END) as fail_count
            FROM evaluations
            GROUP BY agent, model
            ORDER BY avg_score ASC
        """).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def analyze_patterns(cards: list[dict], agent_perf: list[dict]) -> dict:
    """Analyze failure patterns across low-scoring cards."""
    patterns = {
        "common_weaknesses": {},
        "common_improvements": {},
        "agents_needing_attention": [],
        "lanes_needing_attention": {},
        "recommendations": [],
    }

    for card in cards:
        weaknesses = card.get("weaknesses")
        if weaknesses:
            try:
                wlist = json.loads(weaknesses) if isinstance(weaknesses, str) else weaknesses
                for w in wlist:
                    patterns["common_weaknesses"][w] = patterns["common_weaknesses"].get(w, 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass

        improvements = card.get("improvement")
        if improvements:
            patterns["common_improvements"][improvements] = patterns["common_improvements"].get(improvements, 0) + 1

        agent = card.get("agent", "unknown")
        score = card.get("overall_score") or 0
        if score < 3.0:
            patterns["agents_needing_attention"].append({
                "agent": agent,
                "card_id": card["id"],
                "score": score,
                "title": card.get("title", "")[:80],
            })

        lane = card.get("lane", "unknown")
        if lane not in patterns["lanes_needing_attention"]:
            patterns["lanes_needing_attention"][lane] = {"count": 0, "avg_score": 0, "scores": []}
        patterns["lanes_needing_attention"][lane]["count"] += 1
        patterns["lanes_needing_attention"][lane]["scores"].append(score)

    # Compute lane averages
    for lane, data in patterns["lanes_needing_attention"].items():
        if data["scores"]:
            data["avg_score"] = round(sum(data["scores"]) / len(data["scores"]), 2)

    # Agent performance summary
    for perf in agent_perf:
        if perf.get("avg_score", 99) < 3.5:
            patterns["recommendations"].append(
                f"Agent {perf['agent']} ({perf['model']}) avg score {perf['avg_score']}/5 "
                f"over {perf['eval_count']} evals — review prompts and skills for this agent."
            )

    # Top weaknesses
    top_weaknesses = sorted(patterns["common_weaknesses"].items(), key=lambda x: -x[1])[:5]
    if top_weaknesses:
        patterns["recommendations"].append(
            "Most common weaknesses: " + ", ".join(f"{w} ({n}x)" for w, n in top_weaknesses)
        )

    return patterns


def write_report(date_str: str, low_cards: list[dict], agent_perf: list[dict], patterns: dict) -> str:
    """Write the EOD review report page."""
    Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)
    path = os.path.join(REPORTS_DIR, f"eod-review-{date_str}.md")
    lines = [
        f"# EOD Review — {date_str}",
        f"generated:: {now_str()}",
        "type:: [[report]]",
        "area:: [[Ops]]",
        "status:: eod-review",
        "",
        "## Summary",
        f"- Cards reviewed: {len(low_cards)}",
        f"- Agents evaluated: {len(agent_perf)}",
        "",
    ]

    # Agent performance
    if agent_perf:
        lines.append("## Agent Performance (by avg PEEM score)")
        for perf in agent_perf:
            lines.append(
                f"- {perf['agent']} ({perf['model']}): "
                f"avg {perf.get('avg_score', 'N/A')}/5, "
                f"{perf.get('eval_count', 0)} evals, "
                f"{perf.get('fail_count', 0)} fails"
            )
        lines.append("")

    # Worst performing cards
    if low_cards:
        lines.append("## Worst-Performing Cards (lowest PEEM first)")
        for card in low_cards[:5]:
            lines.append(f"### Card {card['id']} — {card.get('title', 'Untitled')[:80]}")
            lines.append(f"- Lane: {card.get('lane')} | Agent: {card.get('agent')} | Score: {card.get('overall_score', 'N/A')}/5 | Verdict: {card.get('verdict', 'N/A')}")
            if card.get('project_vision'):
                lines.append(f"- Vision: {card['project_vision'][:150]}")
            if card.get('weaknesses'):
                try:
                    w = json.loads(card['weaknesses']) if isinstance(card['weaknesses'], str) else card['weaknesses']
                    lines.append(f"- Weaknesses: {', '.join(w) if isinstance(w, list) else w}")
                except (json.JSONDecodeError, TypeError):
                    lines.append(f"- Weaknesses: {card['weaknesses']}")
            if card.get('improvement'):
                lines.append(f"- Improvement: {card['improvement']}")
            lines.append("")

    # Patterns
    lines.append("## Patterns & Recommendations")
    for rec in patterns.get("recommendations", []):
        lines.append(f"- {rec}")
    lines.append("")

    # Feed back into reasoning system
    lines.append("## Feedback to Reasoning System")
    lines.append("The following should be reflected in triager prompts and agent skill briefs:")
    if patterns.get("common_weaknesses"):
        lines.append("- Address common weaknesses in triager system prompt: " +
                     ", ".join(sorted(patterns["common_weaknesses"].keys())[:5]))
    if patterns.get("agents_needing_attention"):
        lines.append("- Add skill briefs or routing constraints for underperforming agents")
    lines.append("- Update lane acceptance checks based on recurring failure modes")
    lines.append("")

    lines.append("## Next")
    lines.append("- Review recommendations above; apply to triager prompts and agent configs.")
    lines.append("- Re-run evaluation on improved cards to confirm progress.")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    date_str = dt.datetime.now().strftime("%Y-%m-%d")
    low_cards = fetch_low_scoring_cards(limit=10)
    agent_perf = fetch_agent_performance()
    patterns = analyze_patterns(low_cards, agent_perf)
    path = write_report(date_str, low_cards, agent_perf, patterns)
    print(f"EOD review written: {path}")
    print(f"Cards reviewed: {len(low_cards)}, agents: {len(agent_perf)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
