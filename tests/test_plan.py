from backbone import plan as P

RULES = [
    {"when": {"task_class": "review"}, "then": {"worker": "claude", "fallbacks": ["nim1"], "gate_hint": ""}},
    {"when": {"task_class": "code_edit"}, "then": {"worker": "nim1", "fallbacks": ["nim2", "codex"], "gate_hint": "pytest -q"}},
]


def test_classify():
    assert P.classify("please review this diff")["task_class"] == "review"
    assert P.classify("implement the parser")["task_class"] == "code_edit"
    assert P.classify("hello")["task_class"] == "other"
    assert P.classify("x" * 2000)["size"] == "large"


def test_rule_order_and_availability():
    p = P.plan("implement the parser", rules=RULES, avail={"nim1", "nim2", "codex"})
    assert p["worker"] == "nim1" and p["fallbacks"] == ["nim2", "codex"] and "--gate 'pytest -q'" in p["command"]
    q = P.plan("implement the parser", rules=RULES, avail={"codex"})
    assert q["worker"] == "codex"          # first rule target missing -> next available
    r = P.plan("review it", rules=RULES, avail={"nim1"})
    assert r["worker"] == "nim1"           # claude missing -> fallback


def test_no_worker_is_explicit():
    assert P.plan("implement x", rules=RULES, avail=set())["worker"] == ""


def test_packet_shape_by_worker():
    assert "RULES:" in P.packet("do x", "nim1", "pytest")
    assert "RULES:" not in P.packet("do x", "codex", "pytest")


def test_bandit_used_when_given():
    class B:
        def pick(self, cls, cands, rng=None):
            return "codex", {}
    p = P.plan("implement the parser", bandit=B(), rules=RULES, avail={"nim1", "nim2", "codex"})
    assert p["worker"] == "codex" and p["why"] == "thompson"


def test_real_routes_yaml_plans():
    p = P.plan("refactor the whole module and write tests", avail={"nim1", "nim2", "claude"})
    assert p["worker"] in {"nim1", "nim2", "claude"} and p["packet"]
