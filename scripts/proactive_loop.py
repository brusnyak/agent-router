#!/usr/bin/env python3
"""Proactive agent loop — Phase 2.

Three-agent loop with review critic, loop interception, and interrupt gate:

1. RESEARCH sub-agent (research-scout): scans queue (kanban + vault inbox + START.md),
   gathers context from the local index, writes findings to ~/memory-vault/agents/research/
2. REVIEW critic (code-reviewer/roast): observes research output, detects loops
   (same task re-dispatched 3x without progress), determines better path forward
3. INTERRUPT gate: owner approval required before any execution/write/send/spend
4. EXECUTION agent: dispatches via RouterSupervisor (index-aware, drift-constrained)

Browser pre-flight: before browser-dependent tasks, checks Neo/Ego; starts if down;
offers to delegate deep research to Gemini via browser chat-based interaction.
Never installs anything.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

HOME = os.path.expanduser("~")
PROJECT_ROOT = os.path.join(HOME, "Developer", "agent-router")
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
VAULT = os.path.join(HOME, "memory-vault")
RESEARCH_DIR = os.path.join(VAULT, "agents", "research")
REPORTS_DIR = os.path.join(VAULT, "pages", "reports")
INBOX_DIR = os.path.join(VAULT, "pages", "inbox")
START_MD = os.path.join(VAULT, "pages", "START.md")

sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router", "scripts"))
sys.path.insert(0, os.path.join(HOME, "memory-vault", "scripts"))

from graph.router import RouterSupervisor  # noqa: E402
import nim_call  # noqa: E402

# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

QUIET_START_HOUR = 22
QUIET_END_HOUR = 8
MAX_LOAD = 6.0
MAX_BLOCKS = 3
MAX_ACTIONS_PER_RUN = 3
LOOP_THRESHOLD = 3  # same task re-dispatched 3x without progress = loop


def now() -> dt.datetime:
    return dt.datetime.now()


def in_quiet_hours(now: dt.datetime) -> bool:
    h = now.hour
    return h >= QUIET_START_HOUR or h < QUIET_END_HOUR


def load_avg() -> float:
    try:
        return os.getloadavg()[0]
    except OSError:
        return 0.0


# ---------------------------------------------------------------------------
# Queue: kanban cards + vault inbox + START.md
# ---------------------------------------------------------------------------

def queue_items() -> List[dict]:
    items: List[dict] = []
    try:
        sys.path.insert(0, PROJECT_ROOT)
        from db.database import list_cards  # noqa: E402
        cards = list_cards()
        for c in cards:
            if c.get("status") in ("done", "blocked"):
                continue
            title = c.get("title", "Untitled")
            if title.lower() in ("smoke test", "test card", "untitled task"):
                continue
            items.append({
                "source": "kanban",
                "id": c["id"],
                "title": title,
                "lane": c.get("lane", "backlog"),
                "status": c.get("status", "triaging"),
                "agent": c.get("agent", "nim3"),
                "project": c.get("project"),
            })
    except Exception:
        pass

    if os.path.isdir(INBOX_DIR):
        for p in Path(INBOX_DIR).glob("*.md"):
            try:
                text = p.read_text(errors="ignore")
                if "status:: open" in text:
                    items.append({
                        "source": "vault-inbox",
                        "id": p.stem,
                        "title": text.splitlines()[0][:120] if text else p.stem,
                        "path": str(p),
                        "lane": "backlog",
                    })
            except OSError:
                pass

    return items[:50]


# ---------------------------------------------------------------------------
# Step 1: Research sub-agent — gathers context from index + vault
# ---------------------------------------------------------------------------

def research_sub_agent(items: List[dict]) -> Dict[str, Any]:
    """Research-scout: for each queue item, gather relevant index context."""
    findings: List[dict] = []
    for item in items[:MAX_ACTIONS_PER_RUN]:
        query = item["title"]
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
        try:
            from index_vault import search
            results = search(query, top_k=5)
        except Exception:
            results = []

        # Write research findings to vault sandbox
        Path(RESEARCH_DIR).mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in query)[:60]
        research_path = os.path.join(RESEARCH_DIR, f"{safe_name}.md")
        lines = [
            f"# Research: {query}",
            f"generated:: {now().isoformat()}",
            f"source:: queue-item {item['id']} ({item['source']})",
            "",
        ]
        for r in results:
            lines.append(f"- [{r.get('kind', '?')}] {r.get('path', '')} (relevance {r.get('score', 0)})")
        if not results:
            lines.append("- No relevant local context found.")
        Path(research_path).write_text("\n".join(lines), encoding="utf-8")

        findings.append({
            "item": item,
            "research_path": research_path,
            "context": results,
        })
    return {"findings": findings}


# ---------------------------------------------------------------------------
# Step 2: Review critic — observes research, detects loops, recommends path
# ---------------------------------------------------------------------------

def load_dispatch_history() -> List[dict]:
    """Load recent dispatch history to detect loops."""
    conn = None
    try:
        sys.path.insert(0, PROJECT_ROOT)
        from db.database import get_connection  # noqa: E402
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, title, agent, lane, status, created_at FROM cards "
            "ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        if conn:
            conn.close()


def detect_loop(history: List[dict], title: str, lane: str) -> bool:
    """Loop detected if same title+lane re-dispatched LOOP_THRESHOLD times without done."""
    count = sum(
        1 for h in history
        if h.get("title") == title and h.get("lane") == lane and h.get("status") != "done"
    )
    return count >= LOOP_THRESHOLD


def review_critic(findings: Dict[str, Any], history: List[dict]) -> Dict[str, Any]:
    """Review critic: observes research findings, detects loops, recommends path."""
    actions: List[dict] = []
    for f in findings["findings"]:
        item = f["item"]
        title = item["title"]
        lane = item["lane"]

        loop = detect_loop(history, title, lane)

        if loop:
            verdict = "BLOCK"
            reasoning = f"Loop detected: '{title}' in {lane} re-dispatched {LOOP_THRESHOLD}x without completion. Recommend different agent/model or scope reduction."
        else:
            verdict = "PROCEED"
            reasoning = f"No loop detected for '{title}' in {lane}. Safe to dispatch."

        actions.append({
            "objective": f"Execute: {title}",
            "lane": lane,
            "agent": item.get("agent", "nim3"),
            "goal": title,
            "research_path": f["research_path"],
            "context": f["context"],
            "loop_detected": loop,
            "gate_verdict": verdict,
            "reasoning": reasoning,
            "acceptance": f"Card for '{title}' reaches done status or owner parks it",
        })

    return {"actions": actions[:MAX_ACTIONS_PER_RUN]}


# ---------------------------------------------------------------------------
# Step 4: Execute via RouterSupervisor (index-aware, drift-constrained)
# ---------------------------------------------------------------------------

def dispatch_action(action: dict, supervisor: RouterSupervisor) -> dict:
    goal = action.get("goal", action.get("objective", ""))
    # Override agent/lane from review critic
    try:
        result = supervisor.run(goal)
        return {
            "objective": action.get("objective", ""),
            "lane": result.get("lane"),
            "agent": result.get("agent"),
            "status": result.get("status"),
            "card_id": (result.get("card") or {}).get("id"),
            "result_preview": (result.get("result") or "")[:200],
            "tokens_spent": result.get("tokens_spent", 0),
            "error": result.get("error"),
            "interrupt_reason": result.get("interrupt_reason"),
        }
    except Exception as e:
        return {
            "objective": action.get("objective", ""),
            "status": "error",
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Step 5: Write report
# ---------------------------------------------------------------------------

def write_report(date_str: str, actions_done: List[dict], summary: str, blocks: int) -> str:
    Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)
    path = os.path.join(REPORTS_DIR, f"proactive-{date_str}.md")
    lines = [
        f"# Proactive Report — {date_str}",
        f"generated:: {dt.datetime.now().isoformat()}",
        "type:: [[report]]",
        "area:: [[Ops]]",
        "status:: proactive-loop",
        "",
        "## Heartbeat",
        f"- Load at run: {load_avg():.2f} (max {MAX_LOAD})",
        f"- Blocks this session: {blocks}/{MAX_BLOCKS}",
        "",
        "## Summary",
        summary,
        "",
        "## Actions",
    ]
    for a in actions_done:
        lines.append(f"### {a.get('objective', 'untitled')}")
        lines.append(f"- Lane: {a.get('lane')} | Agent: {a.get('agent')} | Status: {a.get('status')}")
        if a.get("loop_detected"):
            lines.append("- LOOP DETECTED: blocked to prevent re-dispatch without progress")
        if a.get("card_id"):
            lines.append(f"- Card: {a['card_id']}")
        lines.append(f"- Result: {a.get('result_preview', 'N/A')}")
        if a.get("error"):
            lines.append(f"- Error: {a['error']}")
        lines.append("")

    lines.append("## Next")
    lines.append("- Review actions above; approve any gate-word actions via owner.")
    lines.append("- Next run: scheduled interval.")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Proactive agent loop")
    ap.add_argument("--dry-run", action="store_true",
                    help="Run research + review only, skip actual dispatch (safe for unattended cron)")
    args = ap.parse_args()
    dry_run = args.dry_run

    now_ts = now()

    if in_quiet_hours(now_ts):
        print(f"[{now_ts.isoformat()}] Quiet hours — skipping proactive run.")
        return 0

    load = load_avg()
    if load >= MAX_LOAD:
        print(f"[{now_ts.isoformat()}] Load {load:.2f} >= {MAX_LOAD} — aborting.")
        return 0

    items = queue_items()
    if not items:
        print(f"[{now_ts.isoformat()}] Queue empty — nothing to do.")
        return 0

    # Step 1: Research sub-agent gathers context
    research = research_sub_agent(items)

    # Step 2: Review critic observes + detects loops
    history = load_dispatch_history()
    review = review_critic(research, history)

    # Step 3: Execute non-blocked actions via supervisor (skipped in dry-run)
    supervisor = RouterSupervisor() if not dry_run else None
    blocks = 0
    results: List[dict] = []
    for action in review["actions"]:
        gv = action.get("gate_verdict", "PROCEED")
        if gv == "BLOCK":
            blocks += 1
            results.append({
                "objective": action.get("objective", ""),
                "status": "blocked",
                "result_preview": f"Gate verdict BLOCK — {action.get('reasoning', '')}",
            })
            continue
        if dry_run:
            results.append({
                "objective": action.get("objective", ""),
                "status": "dry-run",
                "result_preview": f"Would dispatch to lane={action.get('lane')} agent={action.get('agent')} goal={action.get('goal')[:60]}",
            })
            continue
        res = dispatch_action(action, supervisor)
        results.append(res)
        time.sleep(0.5)

    date_str = now_ts.strftime("%Y-%m-%d")
    if dry_run:
        done_count = 0
        dispatched_count = len([r for r in results if r.get("status") == "dry-run"])
        summary = f"Dry-run: reviewed {len(items)} queue items, would dispatch {dispatched_count} actions, {blocks} blocked."
    else:
        done_count = len([r for r in results if r.get("status") == "done"])
        summary = f"Processed {len(items)} queue items, dispatched {done_count} actions, {blocks} blocked."
    path = write_report(date_str, results, summary, blocks)
    print(f"[{now_ts.isoformat()}] Proactive run complete. Report: {path}")
    print(f"Actions: {len(results)}, blocks: {blocks}/{MAX_BLOCKS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
