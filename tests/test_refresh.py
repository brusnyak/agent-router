"""Acceptance test for backbone/refresh.py (the spec for `backbone library refresh`).

refresh(home, registry, index, ingest, export, now=None) -> {"added": [paths], "pruned": [paths], "changed": bool, "exported": int|None}
  1. discover sources under `home` (backbone.sources.discover) and add NEW roots to the registry JSON file at `registry`
     (same format sources.save_registry writes: a JSON list of {"path","kind"}); paths keep the "~/" form discover returns.
  2. prune registry entries whose directory no longer exists.
  3. compute a signature of every file under every registry root (relative path, size, mtime); if it equals the signature
     stored in `<index>.sig` AND the index file exists, do NOT call ingest/export: return changed False, exported None.
  4. otherwise call ingest() then n = export(index_path), write the new signature to `<index>.sig`, return changed True, exported n.
  5. always write `<index>.stamp` containing the refresh time as a float (seconds since epoch).
Stdlib only. Must not touch anything outside the given paths."""
import json
import os
import time

from backbone import refresh as R


def mk(p, text="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def setup(tmp_path):
    home = tmp_path / "home"
    mk(home / "tools/skills/alpha/SKILL.md", "---\nname: alpha\ndescription: a\n---\nbody")
    calls = {"ingest": 0, "export": 0}

    def ingest():
        calls["ingest"] += 1

    def export(path):
        calls["export"] += 1
        open(path, "w").write("{}\n")
        return 1

    return home, tmp_path / "sources.json", tmp_path / "library-index.jsonl", ingest, export, calls


def test_first_refresh_registers_the_source_and_exports(tmp_path):
    home, reg, idx, ingest, export, calls = setup(tmp_path)
    out = R.refresh(str(home), str(reg), str(idx), ingest, export)
    assert out["changed"] is True and out["exported"] == 1 and len(out["added"]) == 1 and out["pruned"] == []
    assert calls == {"ingest": 1, "export": 1}
    saved = json.load(open(reg))
    assert [s["kind"] for s in saved] == ["skill"] and saved[0]["path"].endswith("tools/skills")
    assert float(open(str(idx) + ".stamp").read()) <= time.time()


def test_unchanged_sources_skip_ingest_and_export_but_restamp(tmp_path):
    home, reg, idx, ingest, export, calls = setup(tmp_path)
    R.refresh(str(home), str(reg), str(idx), ingest, export)
    first = float(open(str(idx) + ".stamp").read())
    out = R.refresh(str(home), str(reg), str(idx), ingest, export, now=first + 100)
    assert out["changed"] is False and out["exported"] is None and out["added"] == []
    assert calls == {"ingest": 1, "export": 1}
    assert float(open(str(idx) + ".stamp").read()) == first + 100


def test_new_skill_triggers_reexport(tmp_path):
    home, reg, idx, ingest, export, calls = setup(tmp_path)
    R.refresh(str(home), str(reg), str(idx), ingest, export)
    mk(home / "tools/skills/beta/SKILL.md", "---\nname: beta\ndescription: b\n---\nbody")
    out = R.refresh(str(home), str(reg), str(idx), ingest, export)
    assert out["changed"] is True and calls == {"ingest": 2, "export": 2}


def test_removed_source_is_pruned_from_registry(tmp_path):
    home, reg, idx, ingest, export, calls = setup(tmp_path)
    R.refresh(str(home), str(reg), str(idx), ingest, export)
    import shutil
    shutil.rmtree(home / "tools")
    out = R.refresh(str(home), str(reg), str(idx), ingest, export)
    assert len(out["pruned"]) == 1 and out["changed"] is True
    assert json.load(open(reg)) == []


def test_missing_index_forces_export_even_if_signature_matches(tmp_path):
    home, reg, idx, ingest, export, calls = setup(tmp_path)
    R.refresh(str(home), str(reg), str(idx), ingest, export)
    os.remove(idx)
    out = R.refresh(str(home), str(reg), str(idx), ingest, export)
    assert out["changed"] is True and calls["export"] == 2
