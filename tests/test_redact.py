"""Secrets must not survive the router boundary: shape patterns, exact known values, nested structures, worker results."""
from backbone import redact as R


def fake(prefix, n=40):
    return prefix + ("A1b2C3d4" * 8)[:n]


def test_shapes_are_masked_and_prose_is_untouched():
    t = f"key {fake('nvapi-')} and {fake('ghp_', 36)} and AKIA{'ABCDEFGH' * 2} and Bearer {fake('', 30)} ok"
    out = R.redact(t)
    assert "nvapi-" not in out and "ghp_" not in out and "AKIA" not in out and "A1b2C3d4" not in out
    assert out.startswith("key [REDACTED:nvidia] and [REDACTED:github]") and "Bearer [REDACTED:bearer]" in out
    assert R.redact("the api key is rotated weekly, see the plan") == "the api key is rotated weekly, see the plan"


def test_exact_value_of_a_held_key_is_masked_even_without_a_known_shape():
    secret = "zq9-WEIRD-format-token-0123456789"
    env = {"ACMEAI_API_KEY": secret, "SHORT_KEY": "abc", "PATH": "/usr/bin"}
    out = R.redact(f"worker printed {secret} to stdout, and abc stays", environ=env)
    assert secret not in out and "[REDACTED:key]" in out and "and abc stays" in out      # too-short values are not masked


def test_nested_objects_and_non_strings():
    env = {"X_API_KEY": "long-secret-value-123456"}
    o = {"a": ["long-secret-value-123456", 3, None], "b": {"c": fake("nvapi-")}, "n": 7}
    out = R.redact_obj(o, environ=env)
    assert out == {"a": ["[REDACTED:key]", 3, None], "b": {"c": "[REDACTED:nvidia]"}, "n": 7}


def test_worker_dispatch_masks_result_text(monkeypatch):
    from backbone.core import Backbone
    from backbone.workers import Result
    leaked = fake("nvapi-")
    bb = Backbone.__new__(Backbone)
    monkeypatch.setattr(Backbone, "_dispatch_raw", lambda self, *a, **k: Result(True, "found " + leaked, "w", meta={"e": leaked}))
    res = Backbone._dispatch(bb, "claude", "p", ".", True, 0)
    assert leaked not in res.text and leaked not in str(res.meta) and "[REDACTED:nvidia]" in res.text
