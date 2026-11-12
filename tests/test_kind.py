from backbone.kind import predict_kind

EX = [("review my rust code for safety", "agent"), ("check rust code idioms and lifetimes", "agent"),
      ("fix the failing build", "command"), ("repair the compile error in the build", "command"),
      ("write a cold email to prospects", "playbook"), ("first outreach message to a stranger", "playbook")]


def test_predicts_by_nearest_examples():
    assert predict_kind("review my go code for idioms", EX)[0] == "agent"
    assert predict_kind("the build is red, repair it", EX)[0] == "command"
    assert predict_kind("draft an outreach email to a prospect", EX)[0] == "playbook"


def test_margin_is_in_unit_range_and_empty_is_safe():
    k, m = predict_kind("review my rust code", EX)
    assert 0.0 <= m <= 1.0 and m > 0.0
    assert predict_kind("anything", []) == ("", 0.0)
    assert predict_kind("", EX)[1] == 0.0  # nothing to match on: no confidence


def test_ambiguous_query_has_lower_margin_than_clear_one():
    clear = predict_kind("review my rust code for safety", EX)[1]
    vague = predict_kind("code", EX)[1]
    assert clear > vague
