"""Measure configured retrieval: python3 eval/golden_recall.py [--config FILE]."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backbone.retrieval import ROOT, Registry, load_yaml


def evaluate(registry, entries):
    at1 = at5 = 0
    for entry in entries:
        hits = registry.search_all(entry["query"], 5)
        matches = [entry["must_match_path_substring"] in (h.source + " " + h.id) for h in hits]
        at1 += bool(matches and matches[0])
        at5 += any(matches[:5])
    total = len(entries)
    return {"queries": total, "hit@1": at1 / total if total else 0.0,
            "hit@5": at5 / total if total else 0.0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "config/golden_recall.yaml"))
    parser.add_argument("--retrieval-config", default=str(ROOT / "config/retrieval.yaml"))
    args = parser.parse_args(argv)
    registry = Registry(args.retrieval_config)
    print(json.dumps(evaluate(registry, load_yaml(args.config)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
