from backbone.rerank import rerank

HITS = [{"id": "a", "name": "alpha", "description": "x"}, {"id": "b", "name": "beta", "description": "y"},
        {"id": "c", "name": "gamma", "description": "z"}]


def test_reorders_by_model_answer():
    out = rerank(lambda m: '["c","a"]', "q", HITS, k=3)
    assert [h["id"] for h in out] == ["c", "a", "b"]


def test_k_limits():
    assert [h["id"] for h in rerank(lambda m: '["b"]', "q", HITS, k=1)] == ["b"]


def test_garbage_or_error_falls_back_to_original_order():
    assert [h["id"] for h in rerank(lambda m: "no json here", "q", HITS, k=2)] == ["a", "b"]

    def boom(m):
        raise RuntimeError("nim down")

    assert [h["id"] for h in rerank(boom, "q", HITS, k=3)] == ["a", "b", "c"]


def test_unknown_ids_ignored_and_prompt_mentions_query():
    seen = {}

    def chat(messages):
        seen["text"] = messages[0]["content"]
        return '["zzz","b"]'

    out = rerank(chat, "find email skill", HITS, k=3)
    assert [h["id"] for h in out][0] == "b" and "find email skill" in seen["text"]
