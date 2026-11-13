import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
import shadow_eval as se


def w(p, rows):
    p.write_text("\n".join(json.dumps(r) for r in rows))


def setup(tmp_path):
    # dev: a (margin .5, right), b (margin 0, wrong top1, right top3); test: c
    w(tmp_path / "silver.jsonl", [{"id": "a", "split": "dev", "silver": "x"},
                                  {"id": "b", "split": "dev", "silver": "x"},
                                  {"id": "c", "split": "test", "silver": "x"}])
    w(tmp_path / "router_ranks.jsonl", [
        {"id": "a", "top": [["skill:x:h1", 0.9], ["y", 0.4]]},
        {"id": "b", "top": [["y", 0.5], ["z", 0.5], ["x", 0.1]]},
        {"id": "c", "top": [["y", 0.9], ["z", 0.4]]}])


def test_abstain_and_coverage(tmp_path):
    setup(tmp_path)
    rows = se.load("router", "dev", tmp_path)
    assert len(rows) == 2
    e = se.evaluate(rows, 0.1)
    assert e["coverage"] == 0.5 and e["top1"] == 1.0
    e0 = se.evaluate(rows, 0)
    assert e0["coverage"] == 1.0 and e0["top1"] == 0.5 and e0["top3"] == 1.0


def test_tune_dev_only(tmp_path):
    setup(tmp_path)
    with open(tmp_path / "silver.jsonl", "a") as f:  # dev row d: margin 0, silver missing from top3
        f.write("\n" + json.dumps({"id": "d", "split": "dev", "silver": "x"}))
    with open(tmp_path / "router_ranks.jsonl", "a") as f:
        f.write("\n" + json.dumps({"id": "d", "top": [["y", 0.5], ["z", 0.5], ["w", 0.1]]}))
    assert se.main(["--source", "router", "--tune", "--thresholds", "0,0.1"], tmp_path) == 0
    g = json.loads((tmp_path / "gate.json").read_text())
    assert g["T"] == 0.1 and g["dev"]["n"] == 3  # test row c excluded


def test_test_refused_without_final(tmp_path):
    setup(tmp_path)
    assert se.main(["--source", "router", "--split", "test"], tmp_path) == 2
    assert se.main(["--source", "router", "--split", "test", "--final"], tmp_path) == 0
