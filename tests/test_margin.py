from backbone.margin import needs_llm


def test_clear_winner_needs_no_llm():
    assert needs_llm([0.9, 0.3, 0.2]) is False


def test_close_top_two_needs_llm():
    assert needs_llm([0.50, 0.48, 0.1]) is True


def test_low_top_score_needs_llm_even_with_margin():
    assert needs_llm([0.2, 0.01], min_top=0.4) is True


def test_edge_cases():
    assert needs_llm([]) is True            # nothing retrieved: ask the model
    assert needs_llm([0.8]) is False        # single strong candidate
    assert needs_llm([0.1], min_top=0.4) is True
    assert needs_llm([0.5, 0.5]) is True    # exact tie
    assert needs_llm([0.0, 0.0]) is True    # zero scores: no division error
