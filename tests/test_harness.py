"""Code graders for shared harness installation; all writes use a temporary HOME."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from backbone import harness as h

NODE = shutil.which("node")


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AGENT_ROUTER_HOME", str(home / "router"))
    bins = tmp_path / "bin"
    bins.mkdir()
    monkeypatch.setenv("PATH", str(bins))
    return home


def binary(name):
    path = Path(os.environ["PATH"]) / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)


def owner(text):
    path = Path(os.environ["AGENT_ROUTER_HOME"]) / "harness.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def snapshot(home):
    return {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()}


def test_default_adapters_and_detection(home):
    adapters, includes = h.config()
    assert includes == []
    assert {a["id"] for a in adapters} == {
        "omp", "codex", "claude", "goose", "cline", "opencode", "kilo", "gemini", "pi"}
    assert not any(h.detected(a) for a in adapters)
    binary("codex")
    (home / ".gemini").mkdir()
    assert {a["id"] for a in adapters if h.detected(a)} == {"codex", "gemini"}
    assert {a["id"] for a in adapters if not a["verified"]} == {"cline", "kilo", "pi"}


def test_owner_home_default(home, monkeypatch):
    monkeypatch.delenv("AGENT_ROUTER_HOME")
    directory = home / ".agent-router"
    directory.mkdir()
    (directory / "harness.yaml").write_text("disable: [pi]\n")
    assert "pi" not in {a["id"] for a in h.config()[0]}


@pytest.mark.parametrize("original", ["", "User rules", "User rules\n", "User rules\r\n"])
def test_insert_and_idempotence(original):
    block = h.BEGIN + "\nmanaged\n" + h.END
    updated = h.update_block(original, block)
    assert updated.startswith(original)
    assert updated.count(h.BEGIN) == 1
    assert h.update_block(updated, block) == updated


def test_replace_preserves_surrounding_bytes():
    before, after = "private\r\n\r\n", "\r\nprivate tail"
    old = before + h.BEGIN + "\nold\n" + h.END + after
    block = h.BEGIN + "\nnew\n" + h.END
    assert h.update_block(old, block) == before + block + after


@pytest.mark.parametrize("text", [h.BEGIN, h.END, h.END + h.BEGIN,
                                     h.BEGIN + h.BEGIN + h.END, h.BEGIN + h.END + h.END])
def test_bad_markers_refused(text):
    with pytest.raises(ValueError):
        h.update_block(text, "replacement")


def test_include_disable_override_merge(home):
    (home / "router").mkdir()
    (home / "router/extra.md").write_text("Owner's additional rules\n")
    owner("include:\n  - extra.md\ndisable: [pi, omp]\nrules_path:\n  codex: ~/custom/rules.md\n")
    binary("codex")
    binary("pi")
    binary("omp")
    adapters, includes = h.config()
    codex = next(a for a in adapters if a["id"] == "codex")
    assert codex["detect"]["binary"] == "codex"
    assert codex["rules_path"] == "~/custom/rules.md"
    rows = h.plan()
    assert [a["id"] for a, _, _, _ in rows] == ["codex"]
    assert rows[0][1] == home / "custom/rules.md"
    assert "Owner's additional rules" in h.render_rules(includes=includes)


def test_workers_and_commands_rendered(home):
    rendered = h.render_rules()
    assert "{{" not in rendered
    for agent in h.load_yaml(h.ROOT / "config/agents.yaml")["agents"]:
        assert "- " + agent["id"] in rendered
        if agent.get("note"):
            assert agent["note"] in rendered
    assert 'backbone retrieval search "<topic>" -k 5' in rendered
    assert "backbone run --worker <w> --gate '<cmd>' '<task>'" in rendered


def test_dry_run_no_writes_and_only(home, capsys):
    binary("codex")
    binary("omp")
    before = snapshot(home)
    assert h.main(["sync", "--only", "codex"]) == 0
    assert snapshot(home) == before
    output = capsys.readouterr().out
    assert "--- " in output and "+++ " in output and "+<!-- BEGIN" in output
    assert ".omp" not in output


def test_apply_backup_once_and_check(home, capsys):
    binary("claude")
    target = home / ".claude/CLAUDE.md"
    target.parent.mkdir()
    original = b"personal\r\nlast line"
    target.write_bytes(original)
    target.chmod(0o640)
    assert h.main(["check"]) == 2
    assert h.main(["sync", "--apply"]) == 0
    assert target.read_bytes().startswith(original)
    backups = list(target.parent.glob("*.bak"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert target.stat().st_mode & 0o777 == 0o640
    assert h.main(["check"]) == 0
    assert h.main(["sync", "--apply"]) == 0
    assert len(list(target.parent.glob("*.bak"))) == 1
    target.write_text(target.read_text().replace("Shared agent rules", "Stale agent rules"))
    assert h.main(["check"]) == 2
    assert h.main(["sync", "--apply"]) == 0
    assert len(list(target.parent.glob("*.bak"))) == 1
    assert backups[0].read_bytes() == original
    assert h.main(["check"]) == 0
    assert "drift" in capsys.readouterr().out


def test_missing_file_no_backup(home):
    binary("codex")
    assert h.main(["sync", "--apply"]) == 0
    target = home / ".codex/AGENTS.md"
    assert target.read_text().startswith(h.BEGIN)
    assert not list(target.parent.glob("*.bak"))


def test_bad_marker_preflight_prevents_all_writes(home, capsys):
    binary("codex")
    binary("claude")
    target = home / ".claude/CLAUDE.md"
    target.parent.mkdir()
    target.write_text(h.BEGIN)
    before = snapshot(home)
    assert h.main(["sync", "--apply"]) == 2
    assert "unbalanced" in capsys.readouterr().err
    assert snapshot(home) == before


def test_omp_extension_only_when_detected_and_checked(home):
    binary("codex")
    extension = home / ".omp/agent/extensions/vault-recall.ts"
    assert h.main(["sync", "--apply"]) == 0
    assert not extension.exists()
    binary("omp")
    assert h.main(["sync", "--apply"]) == 0
    expected = (h.ROOT / "config/harness/omp/vault-recall.ts").read_bytes()
    assert extension.read_bytes() == expected
    assert b"before_agent_start" in expected and b"timeout: 9000" in expected
    assert b"'backbone'" in expected
    assert h.main(["check"]) == 0
    extension.write_text("stale")
    assert h.main(["check"]) == 2
    assert h.main(["sync", "--apply", "--only", "omp"]) == 0
    assert extension.read_bytes() == expected
    assert list(extension.parent.glob("*.bak"))[0].read_text() == "stale"


def test_list_and_empty_check(home, capsys):
    assert h.main(["check"]) == 0
    binary("kilo")
    assert h.main(["list"]) == 0
    output = capsys.readouterr().out
    assert f"kilo {home}/.config/kilo/AGENTS.md verified=false missing" in output


@pytest.mark.parametrize("text", ["include: not-a-list", "disable: [unknown]",
                                     "rules_path:\n  typo: ~/x", "include: [missing.md]",
                                     "include: [true]", "rules_path: nope"])
def test_invalid_owner_config_fails_without_writes(home, text):
    binary("codex")
    owner(text)
    before = snapshot(home)
    assert h.main(["sync", "--apply"]) == 2
    assert snapshot(home) == before


def test_invalid_only_fails(home):
    assert h.main(["sync", "--only", "typo"]) == 2


def test_symlink_preserved(home):
    binary("claude")
    target = home / "canonical.md"
    target.write_text("Canonical rules\n")
    link = home / ".claude/CLAUDE.md"
    link.parent.mkdir()
    link.symlink_to(target)
    assert h.main(["sync", "--apply"]) == 0
    assert link.is_symlink()
    assert target.read_text().startswith("Canonical rules\n" + h.BEGIN)


def test_changed_since_plan_refused(home):
    target = home / "file"
    target.write_text("changed")
    with pytest.raises(ValueError, match="changed since planning"):
        h._write(target, "original", "replacement")
    assert target.read_text() == "changed"


def test_duplicate_target_refused(home):
    binary("codex")
    binary("claude")
    owner("rules_path:\n  codex: ~/same.md\n  claude: ~/same.md\n")
    assert h.main(["sync", "--apply"]) == 2
    assert not (home / "same.md").exists()


def test_yaml_subset_and_reject_unsupported(home):
    path = home / "sample.yaml"
    path.write_text("include:\n- 'a b.md'\n- \"c#d.md\" # comment\n"
                    "rules_path:\n  codex: ~/x\ndisable: ['pi', omp]\n")
    assert h.load_yaml(path) == {"include": ["a b.md", "c#d.md"],
                                 "rules_path": {"codex": "~/x"}, "disable": ["pi", "omp"]}
    path.write_text("include: !execute bad\n")
    with pytest.raises(ValueError):
        h.load_yaml(path)


def test_cli_dispatch_and_help(home):
    for args in (["harness", "--help"], ["harness", "sync", "--only", "codex"]):
        result = subprocess.run([sys.executable, "-m", "backbone", *args],
                                cwd=h.ROOT, env=os.environ.copy(), capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    binary("codex")
    result = subprocess.run([sys.executable, "-m", "backbone", "harness", "check"],
                            cwd=h.ROOT, capture_output=True, text=True)
    assert result.returncode == 2 and "codex" in result.stdout


def test_module_uses_stdlib_only(home):
    result = subprocess.run([sys.executable, "-S", "-m", "backbone.harness", "check"],
                            cwd=h.ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_cli_harness_uses_stdlib_only(home):
    """The public CLI must not import optional worker dependencies for harness."""
    result = subprocess.run(
        [sys.executable, "-S", "-m", "backbone", "harness", "check"],
        cwd=h.ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_diff_handles_missing_final_newline(home, capsys):
    binary("codex")
    target = home / ".codex/AGENTS.md"
    target.parent.mkdir()
    target.write_text("last line")
    assert h.main(["sync"]) == 0
    assert "-last line\n\\ No newline at end of file\n+last line\n" in capsys.readouterr().out


@pytest.mark.skipif(NODE is None, reason="Node needed to execute the OMP TypeScript template")
@pytest.mark.parametrize("mode", ["success", "error", "missing"])
def test_omp_hook_runtime(home, monkeypatch, mode):
    monkeypatch.setenv("BACKBONE_DEFAULT_PROJECT", "example")
    if mode != "missing":
        executable = Path(os.environ["PATH"]) / "backbone"
        executable.write_text(f"#!{sys.executable}\nimport json, sys\n" +
                              ("print(json.dumps(sys.argv[1:]))\n" if mode == "success" else "sys.exit(1)\n"))
        executable.chmod(0o755)
    # OMP loads .ts as a module; .mts gives Node the same module semantics
    # without inheriting this repository's package.json type.
    extension = home / "vault-recall.mts"
    extension.write_bytes((h.ROOT / "config/harness/omp/vault-recall.ts").read_bytes())
    prompt = 'Recall "quoted" topic; $(do-not-execute)'
    script = (f"import install from {json.dumps(extension.as_uri())};\n"
              "let handler; install({on(event, cb) { if(event !== 'before_agent_start') throw Error(event); handler=cb; }});\n"
              f"console.log(JSON.stringify(await handler({{prompt: {json.dumps(prompt)}}}) ?? null));")
    result = subprocess.run([NODE, "--input-type=module", "-e", script],
                            capture_output=True, text=True, timeout=15)
    # Older Node versions may not support TypeScript imports.
    if "ERR_UNKNOWN_FILE_EXTENSION" in result.stderr:
        pytest.skip("Node version cannot load TypeScript")
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    if mode == "success":
        text = output["message"]["content"][0]["text"]
        assert json.loads(text.split("\n", 1)[1]) == [
            "retrieval", "pack", prompt, "--project", "example"]
    else:
        assert output is None
