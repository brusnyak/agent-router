from backbone.decide import decide, validate, heuristic, TIERS

ALLOWED = {
    "commands": {"review", "roast"},
    "projects": {"alpha"},
    "workers": {"nim1", "nim2"},
    "gates": {"pytest"},
    "personas": {"Product Manager": "agent"},
    "default_worker": "nim1",
}

def chat(messages):
    return '{"command": "review", "worker": "nim1", "tier": "bogus", "rationale": "x"}'

def test_invalid_tier_dropped_to_auto():
    plan = decide(chat, "review this", ALLOWED, [])
    assert plan["tier"] == "auto"
    assert "tier=bogus" in plan["dropped"]

def test_valid_tiers_kept():
    for tier in ("strong", "weak", "auto"):
        def c(messages, tier=tier):
            return f'{{"command": "", "worker": "nim1", "tier": "{tier}", "rationale": "x"}}'
        plan = decide(c, "review this", ALLOWED, [])
        assert plan["tier"] == tier, tier
        assert f"tier={tier}" not in plan["dropped"]

def test_heuristic_tier_is_auto():
    assert heuristic("review something", ALLOWED)["tier"] == "auto"

def test_validate_keeps_tier_directly():
    out = validate({"tier": "weak", "dropped": []}, ALLOWED)
    assert out["tier"] == "weak"
    out = validate({"tier": "strong", "dropped": []}, ALLOWED)
    assert out["tier"] == "strong"
    out = validate({"tier": "nope", "dropped": []}, ALLOWED)
    assert out["tier"] == "auto"
