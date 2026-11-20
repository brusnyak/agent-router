#!/usr/bin/env python3
"""Hourly broad Upwork scan through the Upwork MCP (claude -p, Haiku). Writes new, deduped survivors to
~/memory-vault/pages/reports/upwork/INDEX.md. Read-only: no applying, no Connects. org_uid from the upwork-scan skill."""
import json, os, re, subprocess, sys, time

HOME = os.path.expanduser("~")
OUT = f"{HOME}/memory-vault/pages/reports/upwork"
SEEN = f"{HOME}/.agent-router/data/upwork_seen.json"
PROMPT = """Run the upwork-scan skill (~/.claude/skills/upwork-scan/SKILL.md) in READ-ONLY mode with org_uid 1644199947802345473.
Use ONLY the Upwork find_jobs tool (search/smart_search/get). Run the broad query set in ONE parallel block: smart_search most_recent days_posted=3; search categories "Web, Mobile & Software Dev", "Data Science & Analytics", "Sales & Marketing", "Writing", "Translation", "Design & Creative", "Admin Support", "IT & Networking"; queries "python automation scraping API integration", "n8n OR make.com OR zapier workflow AI agent", "whatsapp OR twilio OR chatbot OR voice agent", "copywriting OR landing page OR cold email OR SEO", "google sheets OR apps script OR airtable OR CRM setup", "slovak OR ukrainian OR russian". Filters: sort recency, verified_payment_only true, proposals_max 10, limit 10. Keep only jobs created in the last 3 days, proposals tier <=10, fixed budget >=100 USD or hourly >=15, no cold-calling/phone roles, no data-labelling. Do NOT call `get` except for at most 3 best candidates.
Output ONLY one JSON object, no prose: {"seen":{"<query label>":<jobs returned>,...},"survivors":[{"id":"","title":"","budget":"","tier":"","client":"spend/hire rate/rating","grade":"A|B|C|D","why":"one line: what we can prove","url":""}],"crowded_great":[{"id":"","title":"","tier":"","why":"great fit but tier 20+","url":""}]}. Grade A/B only if we can show a runnable demo or repo for it today."""

def main():
    os.makedirs(OUT, exist_ok=True)
    seen = {}
    try: seen = json.load(open(SEEN))
    except Exception: pass
    p = subprocess.run(["claude", "-p", PROMPT, "--model", "haiku", "--output-format", "text",
                        "--allowedTools", "mcp__upwork__upwork__find_jobs", "mcp__upwork__upwork__get_profile"],
                       capture_output=True, text=True, timeout=900, cwd=HOME)
    txt = p.stdout
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        print("no JSON in output:", txt[:300], p.stderr[:200]); return 1
    d = json.loads(m.group(0))
    new = [j for j in d.get("survivors", []) if j.get("id") and j["id"] not in seen]
    newc = [j for j in d.get("crowded_great", []) if j.get("id") and j["id"] not in seen]
    ts = time.strftime("%Y-%m-%d %H:%M")
    line = f"- {ts} seen {sum(v for v in d.get('seen', {}).values() if isinstance(v, int)) if isinstance(d.get('seen'), dict) else '?'} jobs, new survivors {len(new)}, crowded-great {len(newc)}\n"
    idx = f"{OUT}/INDEX.md"
    if not os.path.exists(idx):
        open(idx, "w").write("type:: [[report]]\narea:: [[Sales]]\n\n# Upwork hourly scan (newest last; read-only, nothing applied)\n\n")
    with open(idx, "a") as f:
        f.write(line)
        for j in new:
            f.write(f"  - [{j.get('grade','?')}] {j.get('title','')[:80]} | {j.get('budget','')} | {j.get('tier','')} | {j.get('why','')[:100]} | {j.get('url','')}\n")
        for j in newc:
            f.write(f"  - [crowded] {j.get('title','')[:80]} | {j.get('tier','')} | {j.get('why','')[:100]} | {j.get('url','')}\n")
    for j in new + newc: seen[j["id"]] = time.time()  # mark seen only AFTER the report is written
    json.dump(seen, open(SEEN, "w"))
    print(line.strip()); return 0

if __name__ == "__main__":
    sys.exit(main())
