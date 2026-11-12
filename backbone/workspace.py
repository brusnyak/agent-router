"""Isolated working copy per run (git worktree) so owners review a patch instead of trusting claims."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from typing import Optional, Tuple


def _git(args: list, cwd: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def is_repo(path: str) -> bool:
    return os.path.isdir(path) and _git(["rev-parse", "--is-inside-work-tree"], path).returncode == 0


class IsolationError(RuntimeError):
    pass


class Workspace:
    """isolate=True -> detached worktree, and failing to create one is an error (fail closed).
    isolate=False -> runs in place with no diff isolation; the caller chose that explicitly."""

    def __init__(self, project_path: str, run_id: str, work_root: str, isolate: bool = True):
        self.project = os.path.abspath(os.path.expanduser(project_path))
        self.run_id = run_id
        self.path = self.project
        self.isolated = False
        self.base = ""
        if isolate:
            if not is_repo(self.project):
                raise IsolationError(f"{self.project} is not a git repo; pass --no-isolate to run in place")
            self.path = os.path.join(os.path.abspath(os.path.expanduser(work_root)), run_id)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            head = _git(["rev-parse", "HEAD"], self.project)
            r = _git(["worktree", "add", "--detach", self.path, "HEAD"], self.project)
            if head.returncode != 0 or r.returncode != 0:
                self.path = self.project
                raise IsolationError(f"cannot create worktree in {self.project}: {(r.stderr or head.stderr).strip()[:200]}")
            self.base = head.stdout.strip()
            self.isolated = True

    @classmethod
    def attach(cls, project: str, path: str, base: str, isolated: bool) -> "Workspace":
        """Rebuild a handle from checkpointed state (resume after a crash)."""
        w = cls.__new__(cls)
        w.project, w.run_id, w.path, w.base, w.isolated = project, os.path.basename(path), path, base, isolated
        return w

    def diff(self) -> str:
        if not self.isolated:
            return ""
        ex = [":(exclude)__pycache__", ":(exclude)*.pyc", ":(exclude)node_modules", ":(exclude).DS_Store"]
        _git(["add", "-N", ".", *ex], self.path)
        # against the start commit, so work a harness committed is still captured; --binary keeps it applicable
        return _git(["diff", "--binary", self.base, "--", ".", *ex], self.path).stdout

    def cleanup(self) -> None:
        if self.isolated:
            _git(["worktree", "remove", "--force", self.path], self.project)
            shutil.rmtree(self.path, ignore_errors=True)
            self.isolated = False


def scratch_repo(prefix: str = "bb-") -> str:
    d = tempfile.mkdtemp(prefix=prefix)
    _git(["init", "-q"], d)
    _git(["-c", "user.email=b@b", "-c", "user.name=b", "commit", "-q", "--allow-empty", "-m", "init"], d)
    return d


def run_gate(cmd: str, cwd: str, timeout: int = 180) -> Tuple[bool, str]:
    """Acceptance command run by the router, never by the model. Exit 0 = pass."""
    try:
        p = run_group(cmd, cwd=cwd, timeout=timeout, shell=True)
    except subprocess.TimeoutExpired:
        return False, f"gate timeout after {timeout}s"
    return p.returncode == 0, ((p.stdout or "") + (p.stderr or ""))[-1500:]


def run_group(cmd, cwd: str, timeout: int, env: Optional[dict] = None, shell: bool = False) -> subprocess.CompletedProcess:
    """subprocess.run that kills the whole process group on timeout (no orphaned tool processes)."""
    p = subprocess.Popen(cmd, cwd=cwd, env=env, shell=shell, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.communicate()
        raise
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)
