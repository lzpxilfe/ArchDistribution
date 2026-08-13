#!/usr/bin/env python3
"""Execute the public, QGIS-independent synthetic policy fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY = Path(__file__).resolve().parents[1]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from cartographic_filtering import is_insignificant_extent_fragment
from heritage_grouping import resolve_heritage_identity
from heritage_matching import evaluate_candidate


def run_fixture(document):
    results = []
    for case in document["cases"]:
        kind = case["kind"]
        if kind == "identity":
            actual = resolve_heritage_identity(**case["input"])
            selected = {
                key: actual[key] for key in case["expected"]
            }
        elif kind == "matching":
            spatial = dict(case["spatial"])
            spatial.setdefault("distance", 0.0)
            actual_candidate = evaluate_candidate(
                case["left"],
                case["right"],
                preset="balanced",
                **spatial,
            )
            if actual_candidate is None:
                selected = None
            else:
                actual = actual_candidate.as_dict()
                selected = {
                    key: actual[key] for key in case["expected"]
                }
        elif kind == "cartographic_fragment":
            selected = is_insignificant_extent_fragment(**case["input"])
        else:
            raise ValueError(f"Unsupported fixture kind: {kind}")
        if selected != case["expected"]:
            raise AssertionError(
                f"{case['id']}: expected {case['expected']!r}, got {selected!r}"
            )
        results.append({"id": case["id"], "passed": True})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "fixture",
        nargs="?",
        type=Path,
        default=REPOSITORY / "validation/fixtures/policy_cases.json",
    )
    arguments = parser.parse_args()
    document = json.loads(arguments.fixture.read_text(encoding="utf-8"))
    results = run_fixture(document)
    print(json.dumps({
        "schema_version": 1,
        "fixture": arguments.fixture.name,
        "case_count": len(results),
        "passed": all(item["passed"] for item in results),
        "cases": results,
    }, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
