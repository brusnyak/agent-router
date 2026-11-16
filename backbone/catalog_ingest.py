"""Catalog ingestion for ECC personas and agency agents (Horizon 2B).

Reads ECC persona .md files and agency agent .md files and produces catalog
skill entries with persona_file bindings, ready to be merged into
config/skills.yaml. Propose-only: it prints entries; the configurator writes
them to skills.yaml.
"""
from __future__ import annotations

import os
import re
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional


def _first_paragraph(text: str) -> str:
    """Return the first non-empty paragraph after the frontmatter, trimmed."""
    # Strip frontmatter
    body = text
    if body.startswith("---\n"):
        parts = body.split("---\n", 2)
        if len(parts) >= 3:
            body = parts[2]
    # Remove markdown headings and code fences for the description
    lines = []
    in_code = False
    for line in body.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)  # strip heading markers
        line = re.sub(r"^\*\s+", "", line)       # strip bullet markers
        line = line.strip()
        if line:
            lines.append(line)
        if len(lines) >= 3:
            break
    desc = " ".join(lines)
    return desc[:220] + ("…" if len(desc) > 220 else "")


def _extract_frontmatter(text: str) -> Dict[str, Any]:
    """Extract YAML frontmatter from a persona/agent file."""
    if not text.startswith("---\n"):
        return {}
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}


def slugify(name: str) -> str:
    return name.lower().replace(" ", "-").replace("_", "-").replace("/", "-")


def ingest_ecc_agents(ecc_dir: str) -> List[dict]:
    """Ingest ECC persona .md files as catalog skills.

    Each skill:
      id: ecc-<filename-without-ext>
      path: <ecc_dir>/<file>.md
      category: ecc-persona
      description: first paragraph
      persona_file: <ecc_dir>/<file>.md
      _source: ecc-reference
    """
    skills: List[dict] = []
    ecc_path = Path(ecc_dir).expanduser()
    if not ecc_path.is_dir():
        return skills
    for md in sorted(ecc_path.glob("*.md")):
        text = md.read_text(encoding="utf-8", errors="replace")
        fm = _extract_frontmatter(text)
        name = fm.get("name") or md.stem
        desc = fm.get("description") or _first_paragraph(text)
        sid = f"ecc-{slugify(name)}"
        skills.append({
            "id": sid,
            "path": str(md),
            "category": "ecc-persona",
            "description": desc,
            "persona_file": str(md),
            "_source": "ecc-reference",
        })
    return skills


def ingest_agency_agents(agency_dir: str) -> List[dict]:
    """Ingest agency agent .md files as catalog skills.

    Scans all subdirectories of agency_dir for *.md files (excluding
    CONTRIBUTING, README, SECURITY). Each skill:
      id: agency-<subdir>-<filename-without-ext>
      path: <file>.md
      category: agency-<subdir>
      description: first paragraph or frontmatter description
      persona_file: <file>.md
      _source: agency-agents
    """
    skills: List[dict] = []
    agency_path = Path(agency_dir).expanduser()
    if not agency_path.is_dir():
        return skills
    excluded = {"contributing", "readme", "security"}
    for md in sorted(agency_path.rglob("*.md")):
        stem = md.stem.lower()
        if stem in excluded:
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        fm = _extract_frontmatter(text)
        name = fm.get("name") or md.stem
        desc = fm.get("description") or _first_paragraph(text)
        # category from relative subdirectory
        rel = md.relative_to(agency_path)
        subdir = rel.parts[0] if len(rel.parts) > 1 else "general"
        sid = f"agency-{slugify(subdir)}-{slugify(name)}"
        skills.append({
            "id": sid,
            "path": str(md),
            "category": f"agency-{slugify(subdir)}",
            "description": desc,
            "persona_file": str(md),
            "_source": "agency-agents",
        })
    return skills


def ingest_all(ecc_dir: str, agency_dir: str) -> List[dict]:
    """Ingest both ECC and agency agents, deduplicating by id."""
    seen: Dict[str, dict] = {}
    for s in ingest_ecc_agents(ecc_dir):
        seen[s["id"]] = s
    for s in ingest_agency_agents(agency_dir):
        seen[s["id"]] = s
    return list(seen.values())


def main() -> int:
    ecc_dir = os.path.expanduser("~/Developer/ecc-reference/agents")
    agency_dir = os.path.expanduser("~/.agent-skills/vendor/msitarzewski_agency-agents")
    skills = ingest_all(ecc_dir, agency_dir)
    print(yaml.safe_dump({"version": 1, "skills": skills}, sort_keys=False, allow_unicode=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
