"""Packaging/structure only. Does not measure agent decisions or improvement."""
from pathlib import Path
import re


SKILL = Path(__file__).parents[1] / 'skill-candidates/reasoned-choice/SKILL.md'


def test_candidate_frontmatter_and_size():
    text = SKILL.read_text()
    frontmatter, body = text.split('---', 2)[1:]
    assert re.search(r'^name: reasoned-choice$', frontmatter, re.M)
    assert re.search(r'^description: .+', frontmatter, re.M)
    assert body.strip()
    assert len(text.splitlines()) <= 70


def test_source_declarations_do_not_require_private_local_files():
    """Portable declarations only; not source truth or behavioral validation."""
    text = SKILL.read_text()
    paths = set(re.findall(r'`(~/[^`]+)`', text))
    assert paths == {'~/.agent-skills/core/reproduce/SKILL.md'}
    assert 'optional' in text
    assert 'standalone use' in text
    assert 'memory-' + 'vault/' not in text  # private vault paths stay out of the skill


def test_candidate_not_in_discoverable_skill_roots():
    """Candidate location only; cannot prove absence from every global registry."""
    candidate = SKILL.resolve()
    roots = [Path.home() / '.codex/skills', Path.home() / '.agents/skills',
             Path.home() / '.agent-skills']
    assert all(not candidate.is_relative_to(root.resolve()) for root in roots)
