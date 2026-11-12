from backbone.dedupe import drop_ids

R = lambda i, kind, name, body: {"id": i, "kind": kind, "name": name, "body": body}


def test_keeps_longest_body_among_same_kind_and_name():
    rows = [R("a", "skill", "Code-Reviewer", "short"), R("b", "skill", "code-reviewer", "a much longer body here"), R("c", "skill", "code-reviewer", "mid body")]
    assert drop_ids(rows) == {"a", "c"}


def test_same_name_in_different_kinds_is_not_a_duplicate():
    rows = [R("a", "agent", "debugger", "x"), R("b", "subagent", "debugger", "y")]
    assert drop_ids(rows) == set()


def test_same_body_different_names_is_not_a_duplicate_and_empty_ok():
    assert drop_ids([R("a", "skill", "one", "same"), R("b", "skill", "two", "same")]) == set()
    assert drop_ids([]) == set()


def test_tie_on_length_keeps_first_id_sorted():
    rows = [R("z", "skill", "x", "abc"), R("a", "skill", "x", "abc")]
    assert drop_ids(rows) == {"z"}
