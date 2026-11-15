import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml  # noqa: E402

from backbone import rules  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_eq_ne():
    assert rules.match({"a": {"$eq": 1}}, {"a": 1})
    assert not rules.match({"a": {"$eq": 1}}, {"a": 2})
    assert rules.match({"a": {"$ne": 2}}, {"a": 1})
    assert not rules.match({"a": {"$ne": 1}}, {"a": 1})


def test_gt_gte_lt_lte():
    assert rules.match({"a": {"$gt": 5}}, {"a": 6})
    assert not rules.match({"a": {"$gt": 5}}, {"a": 5})
    assert rules.match({"a": {"$gte": 5}}, {"a": 5})
    assert not rules.match({"a": {"$gte": 5}}, {"a": 4})
    assert rules.match({"a": {"$lt": 5}}, {"a": 4})
    assert not rules.match({"a": {"$lt": 5}}, {"a": 5})
    assert rules.match({"a": {"$lte": 5}}, {"a": 5})
    assert not rules.match({"a": {"$lte": 5}}, {"a": 6})


def test_in_nin():
    assert rules.match({"a": {"$in": [1, 2, 3]}}, {"a": 2})
    assert not rules.match({"a": {"$in": [1, 2, 3]}}, {"a": 4})
    assert rules.match({"a": {"$nin": [1, 2, 3]}}, {"a": 4})
    assert not rules.match({"a": {"$nin": [1, 2, 3]}}, {"a": 2})


def test_regex():
    assert rules.match({"a": {"$regex": "^he"}}, {"a": "hello"})
    assert not rules.match({"a": {"$regex": "^bye"}}, {"a": "hello"})


def test_and_or():
    assert rules.match({"$and": [{"a": {"$eq": 1}}, {"b": {"$eq": 2}}]}, {"a": 1, "b": 2})
    assert not rules.match({"$and": [{"a": {"$eq": 1}}, {"b": {"$eq": 9}}]}, {"a": 1, "b": 2})
    assert rules.match({"$or": [{"a": {"$eq": 9}}, {"b": {"$eq": 2}}]}, {"a": 1, "b": 2})
    assert not rules.match({"$or": [{"a": {"$eq": 9}}, {"b": {"$eq": 8}}]}, {"a": 1, "b": 2})


def test_nested_and_or():
    query = {"$or": [{"$and": [{"a": {"$eq": 1}}, {"b": {"$eq": 2}}]}, {"c": {"$eq": 3}}]}
    assert rules.match(query, {"a": 1, "b": 2})
    assert rules.match(query, {"c": 3})
    assert not rules.match(query, {"a": 1})


def test_dotted_path():
    assert rules.match({"a.b": {"$eq": 2}}, {"a": {"b": 2}})
    assert not rules.match({"a.b": {"$eq": 2}}, {"a": {"b": 3}})
    assert not rules.match({"a.b": {"$eq": 2}}, {"a": {}})
    assert rules.match({"a.b": {"$in": [2, 3]}}, {"a": {"b": 3}})
    assert rules.match({"a.b": {"$regex": "^x"}}, {"a": {"b": "xylophone"}})


def test_resolve_first_match_and_none():
    rule_list = [
        {"when": {"a": {"$eq": 1}}, "then": {"worker": "w1"}},
        {"when": {"a": {"$eq": 2}}, "then": {"worker": "w2"}},
        {"when": {"a": {"$eq": 3}}, "then": {"worker": "w3"}},
    ]
    assert rules.resolve(rule_list, {"a": 2})["then"]["worker"] == "w2"
    assert rules.resolve(rule_list, {"a": 1})["then"]["worker"] == "w1"
    assert rules.resolve(rule_list, {"a": 9}) is None
    assert rules.resolve([], {"a": 1}) is None


def test_routes_yaml():
    with open(os.path.join(ROOT, "config", "routes.yaml")) as f:
        data = yaml.safe_load(f)
    rule_list = data["rules"]
    assert len(rule_list) == 6
    for rule in rule_list:
        then = rule["then"]
        assert "worker" in then
        assert "fallbacks" in then and isinstance(then["fallbacks"], list)
    assert rules.resolve(rule_list, {"task_class": "review", "size": "small"})["then"]["worker"] == "nim1"
    assert rules.resolve(rule_list, {"task_class": "code_edit", "size": "large"})["then"]["worker"] == "claude"
    assert rules.resolve(rule_list, {"task_class": "other", "size": "large"})["then"]["worker"] == "claude"
    assert rules.resolve(rule_list, {"task_class": "other", "size": "medium"})["then"]["worker"] == "nim1"
    assert rules.resolve(rule_list, {"task_class": "unknown", "size": "huge"}) is None
