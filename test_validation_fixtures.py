import json
from pathlib import Path
import unittest

from validation.run_synthetic_policy import run_fixture


class SyntheticPolicyFixtureTests(unittest.TestCase):
    def test_public_policy_fixture_matches_expected_contract(self):
        root = Path(__file__).resolve().parent
        fixture = json.loads((
            root / "validation/fixtures/policy_cases.json"
        ).read_text(encoding="utf-8"))
        expected = json.loads((
            root / "validation/expected/policy_cases.json"
        ).read_text(encoding="utf-8"))

        results = run_fixture(fixture)
        self.assertEqual(len(results), expected["expected_case_count"])
        self.assertTrue(all(item["passed"] for item in results))
        self.assertEqual(expected["false_merge_tolerance"], 0)
        self.assertEqual(expected["source_deletion_tolerance"], 0)


if __name__ == "__main__":
    unittest.main()
