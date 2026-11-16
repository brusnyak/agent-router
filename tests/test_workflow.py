"""Tests for the Workflow DAG orchestration layer (Horizon 2A)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backbone.workflow import load_workflows, run_workflow, _topo_order, _eligible_steps
from backbone.workflow import WorkflowStep, Workflow


def test_load_workflows():
    wfs = load_workflows("config/workflows.yaml")
    assert "research-and-write" in wfs
    assert "build-and-review" in wfs
    assert "lead-qualify-and-outreach" in wfs
    rw = wfs["research-and-write"]
    assert rw.synthesize == "claude"
    assert rw.fan_out == ["research"]
    assert len(rw.steps) == 2
    assert rw.steps[0].id == "research"
    assert rw.steps[0].worker == "nim-chat"
    assert rw.steps[0].gate is not None


def test_topo_order():
    steps = [
        WorkflowStep(id="c", worker="a", depends_on=["a", "b"]),
        WorkflowStep(id="a", worker="a", depends_on=[]),
        WorkflowStep(id="b", worker="a", depends_on=[]),
    ]
    order = _topo_order(steps)
    assert order.index("a") < order.index("c")
    assert order.index("b") < order.index("c")
    assert len(order) == 3


def test_topo_order_rejects_cycle():
    steps = [
        WorkflowStep(id="a", worker="a", depends_on=["b"]),
        WorkflowStep(id="b", worker="a", depends_on=["a"]),
    ]
    try:
        _topo_order(steps)
        assert False, "expected ValueError for cycle"
    except ValueError:
        pass


def test_topo_order_rejects_unknown_dependency():
    steps = [
        WorkflowStep(id="a", worker="a", depends_on=["missing"]),
    ]
    try:
        _topo_order(steps)
        assert False, "expected ValueError for unknown dependency"
    except ValueError:
        pass


def test_eligible_steps_skips_failed_dependencies():
    steps = [
        WorkflowStep(id="a", worker="a", depends_on=[]),
        WorkflowStep(id="b", worker="a", depends_on=["a"]),
    ]
    results = {
        "a": type("SR", (), {"ok": False, "gate_passed": False})(),
    }
    # 'a' failed -> 'b' should be skipped (not eligible for dispatch)
    eligible = _eligible_steps(["a", "b"], results, steps, set())
    assert eligible == []  # b is skipped, not dispatched


def test_eligible_steps_allows_passed_dependencies():
    steps = [
        WorkflowStep(id="a", worker="a", depends_on=[]),
        WorkflowStep(id="b", worker="a", depends_on=["a"]),
    ]
    results = {
        "a": type("SR", (), {"ok": True, "gate_passed": True})(),
    }
    eligible = _eligible_steps(["a", "b"], results, steps, set())
    assert eligible == ["b"]


def test_unknown_workflow_returns_false():
    from backbone.core import Backbone
    b = Backbone()
    res = run_workflow(b, "does-not-exist", "prompt", "/tmp", read_only=True)
    assert res.ok is False
    assert res.step_results == {}
    assert res.synthesis is None


def test_workflow_grammar_in_allowed():
    from backbone.core import Backbone
    b = Backbone()
    al = b.allowed()
    assert "workflow" in al["workers"]


if __name__ == "__main__":
    test_load_workflows()
    test_topo_order()
    test_topo_order_rejects_cycle()
    test_topo_order_rejects_unknown_dependency()
    test_eligible_steps_skips_failed_dependencies()
    test_eligible_steps_allows_passed_dependencies()
    test_unknown_workflow_returns_false()
    test_workflow_grammar_in_allowed()
    print("All workflow tests passed.")
