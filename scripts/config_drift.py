#!/usr/bin/env python3
"""Config drift system — PEEM feedback → config-drift.yaml proposals (suggest + gate).

Reads PEEM evaluations from kanban.db, analyzes agent/lane/model performance,
and writes config/drift/config-drift.yaml with PROPOSED changes. Nothing is
applied automatically — the owner reviews and applies via interrupt gate.

This is Option B (suggest + gate): the system observes and proposes; the owner
decides. Safe for unattended operation because it never mutates live config.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

HOME = os.path.expanduser("~")
PROJECT_ROOT = os.path.join(HOME, "Developer", "agent-router")
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
DRIFT_DIR = os.path.join(CONFIG_DIR, "drift")
DRIFT_PATH = os.path.join(DRIFT_DIR, "config-drift.yaml")
DB_PATH = os.path.join(PROJECT_ROOT, "kanban.db")

# Thresholds
AVG_SCORE_WARN = 3.5
AVG_SCORE_BLOCK = 3.0
MIN_CARDS_FOR_DRIFT = 2


def _load_evals() -> List[dict]:
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT c.id, c.title, c.lane, c.agent, c.model, c.status,
                   e.overall_score, e.verdict, e.accuracy, e.coherence,
                   e.relevance, e.objectivity, e.clarity, e.conciseness,
                   e.strengths, e.weaknesses, e.improvement,
                   c.project_vision, c.direct_market, c.value_exchange,
                   c.action_chain, c.next_step
            FROM evaluations e
            JOIN cards c ON c.id = e.card_id
            ORDER BY e.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _top(items: List[str], limit: int = 5) -> List[str]:
    from collections import Counter
    return [it for it, _ in Counter(items).most_common(limit)]


def analyze(evals: List[dict]) -> Dict[str, Any]:
    by_agent: Dict[str, dict] = {}
    by_lane: Dict[str, dict] = {}
    by_model: Dict[str, dict] = {}

    for e in evals:
        agent = e.get("agent") or "unknown"
        lane = e.get("lane") or "unknown"
        model = e.get("model") or "unknown"
        score = e.get("overall_score") or 0

        for bucket, key in ((by_agent, agent), (by_lane, lane), (by_model, model)):
            if key not in bucket:
                bucket[key] = {"scores": [], "cards": [], "weaknesses": [], "improvements": [], "verdicts": []}
            b = bucket[key]
            b["scores"].append(score)
            b["cards"].append(e)
            b["verdicts"].append(e.get("verdict") or "unknown")
            w = e.get("weaknesses")
            if w:
                try:
                    ws = json.loads(w) if isinstance(w, str) else w
                    b["weaknesses"].extend(ws if isinstance(ws, list) else [ws])
                except (json.JSONDecodeError, TypeError):
                    pass
            imp = e.get("improvement")
            if imp:
                b["improvements"].append(imp)

    def summarize(bucket: dict) -> dict:
        out: Dict[str, dict] = {}
        for k, d in bucket.items():
            scores = d["scores"]
            avg = round(sum(scores) / len(scores), 2) if scores else 0
            out[k] = {
                "avg_score": avg,
                "card_count": len(scores),
                "fail_count": sum(1 for v in d["verdicts"] if v == "FAIL"),
                "top_weaknesses": _top(d["weaknesses"]),
                "top_improvements": _top(d["improvements"]),
            }
        return out

    return {
        "by_agent": summarize(by_agent),
        "by_lane": summarize(by_lane),
        "by_model": summarize(by_model),
        "total_evals": len(evals),
    }


def generate_drift(analysis: dict) -> Dict[str, Any]:
    """Turn analysis into proposed config changes (suggest, not apply)."""
    proposals: List[dict] = []
    routing_constraints: List[str] = []
    skill_recommendations: Dict[str, List[str]] = {}
    model_routing: Dict[str, str] = {}

    # Agent-level: below-warn → prompt/skill update; below-block → routing constraint
    for agent, d in analysis["by_agent"].items():
        if d["card_count"] < MIN_CARDS_FOR_DRIFT:
            continue
        if d["avg_score"] < AVG_SCORE_BLOCK:
            routing_constraints.append(
                f"Avoid routing critical tasks to {agent} (avg PEEM {d['avg_score']}/5, {d['card_count']} cards)"
            )
            model_routing[agent] = "avoid-critical"
        elif d["avg_score"] < AVG_SCORE_WARN:
            proposals.append({
                "target": f"agent:{agent}",
                "type": "prompt_update",
                "issue": f"Avg PEEM {d['avg_score']}/5 below {AVG_SCORE_WARN}",
                "top_weaknesses": d["top_weaknesses"],
                "top_improvements": d["top_improvements"],
                "proposed_action": f"Review and update system prompt + skill briefs for {agent}",
                "status": "proposed",
            })
            skill_recommendations[agent] = d["top_improvements"]

    # Lane-level: below-warn → acceptance check update
    for lane, d in analysis["by_lane"].items():
        if d["card_count"] < MIN_CARDS_FOR_DRIFT:
            continue
        if d["avg_score"] < AVG_SCORE_WARN:
            proposals.append({
                "target": f"lane:{lane}",
                "type": "acceptance_update",
                "issue": f"Lane {lane} avg PEEM {d['avg_score']}/5 below {AVG_SCORE_WARN}",
                "proposed_action": f"Update lane acceptance criteria in config/lanes.yaml for {lane}",
                "status": "proposed",
            })

    # Model-level: below-block → avoid for critical; below-warn → downgrade role
    for model, d in analysis["by_model"].items():
        if d["card_count"] < MIN_CARDS_FOR_DRIFT:
            continue
        if d["avg_score"] < AVG_SCORE_BLOCK:
            routing_constraints.append(
                f"Avoid routing critical tasks via {model} (avg PEEM {d['avg_score']}/5)"
            )
            model_routing[model] = "avoid-critical"
        elif d["avg_score"] < AVG_SCORE_WARN:
            model_routing[model] = "worker-only"

    # Summary
    total = analysis["total_evals"]
    n_constraints = len(routing_constraints)
    n_proposals = len(proposals)

    drift = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "peem-evaluations",
        "mode": "suggest-gate",
        "note": "Nothing is applied automatically. Owner reviews and applies via interrupt gate.",
        "total_evaluations": total,
        "routing_constraints": routing_constraints,
        "proposals": proposals,
        "skill_recommendations": skill_recommendations,
        "model_routing": model_routing,
        "summary": (
            f"Reviewed {total} evaluations. {n_constraints} routing constraints, "
            f"{n_proposals} config proposals (all status: proposed)."
        ),
    }
    return drift


def write_drift(drift: dict) -> str:
    Path(DRIFT_DIR).mkdir(parents=True, exist_ok=True)
    # Write YAML manually (avoid pyyaml dependency issues in some envs)
    lines = [
        f"version: {drift['version']}",
        f"generated_at: {drift['generated_at']}",
        f"source: {drift['source']}",
        f"mode: {drift['mode']}",
        f"note: \"{drift['note']}\"",
        f"total_evaluations: {drift['total_evaluations']}",
        "",
        "# ========================================================================",
        "# CONFIG DRIFT — PROPOSED CHANGES (suggest + gate, NOT auto-applied)",
        "# Owner: review each proposal, apply approved ones to config/*.yaml",
        "# ========================================================================",
        "",
    ]

    if drift["routing_constraints"]:
        lines.append("routing_constraints:  # apply to triager/supervisor")
        for c in drift["routing_constraints"]:
            lines.append(f"  - \"{c}\"")
        lines.append("")

    if drift["model_routing"]:
        lines.append("model_routing:  # per-model routing guidance")
        for m, g in drift["model_routing"].items():
            lines.append(f"  {m}: {g}")
        lines.append("")

    if drift["proposals"]:
        lines.append("proposals:")
        for p in drift["proposals"]:
            lines.append(f"  - target: {p['target']}")
            lines.append(f"    type: {p['type']}")
            lines.append(f"    issue: \"{p['issue']}\"")
            lines.append(f"    proposed_action: \"{p['proposed_action']}\"")
            lines.append(f"    status: {p['status']}")
            if p.get("top_weaknesses"):
                lines.append(f"    top_weaknesses: {p['top_weaknesses']}")
            if p.get("top_improvements"):
                lines.append(f"    top_improvements: {p['top_improvements']}")
            lines.append("")

    if drift["skill_recommendations"]:
        lines.append("skill_recommendations:")
        for agent, skills in drift["skill_recommendations"].items():
            lines.append(f"  {agent}: {skills}")
        lines.append("")

    lines.append(f"summary: \"{drift['summary']}\"")
    lines.append("")

    Path(DRIFT_PATH).write_text("\n".join(lines), encoding="utf-8")
    return DRIFT_PATH


def main() -> int:
    evals = _load_evals()
    if not evals:
        print("No PEEM evaluations found — nothing to drift. Run evaluation first.")
        return 0
    analysis = analyze(evals)
    drift = generate_drift(analysis)
    path = write_drift(drift)
    print(json.dumps({
        "evaluations": len(evals),
        "drift_path": path,
        "routing_constraints": len(drift["routing_constraints"]),
        "proposals": len(drift["proposals"]),
        "summary": drift["summary"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
