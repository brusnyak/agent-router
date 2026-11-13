"""PostToolUse hook: record which Skill / Agent the session actually invoked. stdlib only, fail-open, silent.
Reads the Claude Code hook payload on stdin; appends one row via backbone.hook_log.append_outcome."""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    try:
        from backbone.hook_log import append_outcome
        p = json.loads(sys.stdin.read())
        inp = p.get("tool_input") or {}
        name = inp.get("skill") if p.get("tool_name") == "Skill" else inp.get("subagent_type")
        if name:
            path = os.environ.get("OUTCOME_LOG") or os.path.expanduser("~/.agent-router/outcomes.jsonl")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            append_outcome(path, str(name), p.get("session_id", ""), p.get("prompt_id", ""), p.get("tool_use_id", ""))
    except BaseException:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
