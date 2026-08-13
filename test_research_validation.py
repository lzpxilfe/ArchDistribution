import csv
import json
from pathlib import Path
import tempfile
import unittest

from research_validation import (
    LABEL_RELATED_SEPARATE,
    LABEL_SAME_ENTITY,
    LABEL_UNCERTAIN,
    LABEL_UNRELATED,
    MIN_AUTOMATIC_MERGE_PRECISION,
    MIN_CANDIDATE_RECALL,
    PilotValidationError,
    SPLIT_DEVELOPMENT,
    SPLIT_LOCKED_EVALUATION,
    blinded_labeling_rows,
    calculate_pilot_metrics,
    deterministic_project_split,
    export_blinded_labeling_csv,
    merge_blinded_labels,
    write_metrics_json,
)


def pilot_row(index, project=None):
    return {
        "pair_id": f"pair-{index:03d}",
        "project_key": (
            f"project-{index:03d}" if project is None else project
        ),
        "source_a_name": f"A {index}",
        "source_b_name": f"B {index}",
        "recommended_decision": "merge",
        "match_score": "0.99",
        "match_rule": "exact_name_and_overlap",
        "automatic_merge": "true",
        "is_candidate": "true",
    }


class ProjectSplitTests(unittest.TestCase):
    def test_default_split_is_exact_deterministic_and_project_safe(self):
        rows = [pilot_row(index) for index in range(350)]

        first = deterministic_project_split(rows)
        second = deterministic_project_split(reversed(rows))

        self.assertEqual(len(first.development), 200)
        self.assertEqual(len(first.locked_evaluation), 100)
        self.assertEqual(len(first.excluded), 50)
        self.assertEqual(
            [row["pair_id"] for row in first.development],
            [row["pair_id"] for row in second.development],
        )
        self.assertEqual(
            [row["pair_id"] for row in first.locked_evaluation],
            [row["pair_id"] for row in second.locked_evaluation],
        )
        development_projects = {
            row["project_key"] for row in first.development
        }
        evaluation_projects = {
            row["project_key"] for row in first.locked_evaluation
        }
        self.assertTrue(development_projects.isdisjoint(evaluation_projects))
        self.assertEqual(
            {row["project_split"] for row in first.development},
            {SPLIT_DEVELOPMENT},
        )
        self.assertEqual(
            {row["project_split"] for row in first.locked_evaluation},
            {SPLIT_LOCKED_EVALUATION},
        )
        self.assertFalse(first.manifest()["labels_present"])

    def test_multi_pair_projects_never_leak(self):
        rows = [
            pilot_row(index, project=f"project-{index // 2:02d}")
            for index in range(60)
        ]
        split = deterministic_project_split(
            rows,
            development_size=40,
            locked_evaluation_size=20,
            seed="test-seed",
        )

        development_projects = {
            row["project_key"] for row in split.development
        }
        evaluation_projects = {
            row["project_key"] for row in split.locked_evaluation
        }
        self.assertTrue(development_projects.isdisjoint(evaluation_projects))

    def test_split_refuses_impossible_group_assignment(self):
        rows = [
            pilot_row(index, project="one-large-project")
            for index in range(250)
        ]
        rows.extend(
            pilot_row(index + 250, project="one-small-project")
            for index in range(50)
        )

        with self.assertRaisesRegex(
            PilotValidationError, "without project leakage"
        ):
            deterministic_project_split(rows)

    def test_missing_project_or_duplicate_pair_is_rejected(self):
        with self.assertRaisesRegex(PilotValidationError, "no project_key"):
            deterministic_project_split(
                [pilot_row(index, project="") for index in range(300)]
            )

        rows = [pilot_row(index) for index in range(300)]
        rows[1]["pair_id"] = rows[0]["pair_id"]
        with self.assertRaisesRegex(PilotValidationError, "duplicate pair_id"):
            deterministic_project_split(rows)


class BlindedExportTests(unittest.TestCase):
    def test_blinding_removes_predictions_and_leaves_label_empty(self):
        blinded = blinded_labeling_rows([pilot_row(1)])

        self.assertNotIn("recommended_decision", blinded[0])
        self.assertNotIn("match_score", blinded[0])
        self.assertNotIn("match_rule", blinded[0])
        self.assertNotIn("automatic_merge", blinded[0])
        self.assertNotIn("is_candidate", blinded[0])
        self.assertEqual(blinded[0]["blind_label"], "")
        self.assertIn("source_a_name", blinded[0])

    def test_csv_export_reports_real_hash_and_blank_label(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "labels.csv"
            metadata = export_blinded_labeling_csv(
                [pilot_row(1), pilot_row(2)], output
            )

            self.assertEqual(metadata["row_count"], 2)
            self.assertRegex(metadata["sha256"], r"^[0-9a-f]{64}$")
            with output.open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                exported = list(csv.DictReader(handle))
            self.assertEqual([row["blind_label"] for row in exported], ["", ""])
            self.assertNotIn("recommended_decision", exported[0])

    def test_completed_labels_rejoin_private_predictions_by_pair_id(self):
        predictions = [pilot_row(1), pilot_row(2)]
        labels = [
            {"pair_id": "pair-002", "blind_label": LABEL_UNRELATED},
            {"pair_id": "pair-001", "blind_label": LABEL_SAME_ENTITY},
        ]

        joined = merge_blinded_labels(predictions, labels)

        self.assertEqual(
            [row["blind_label"] for row in joined],
            [LABEL_SAME_ENTITY, LABEL_UNRELATED],
        )
        self.assertEqual(joined[0]["automatic_merge"], "true")

    def test_label_join_requires_identical_pair_sets(self):
        with self.assertRaisesRegex(PilotValidationError, "pair IDs differ"):
            merge_blinded_labels(
                [pilot_row(1), pilot_row(2)],
                [{"pair_id": "pair-001", "blind_label": LABEL_SAME_ENTITY}],
            )


class PilotMetricTests(unittest.TestCase):
    @staticmethod
    def labeled(pair_id, label, candidate, automatic_merge):
        return {
            "pair_id": pair_id,
            "project_split": SPLIT_LOCKED_EVALUATION,
            "blind_label": label,
            "is_candidate": candidate,
            "automatic_merge": automatic_merge,
        }

    def test_metrics_use_documented_denominators_and_count_errors(self):
        rows = [
            self.labeled("1", LABEL_SAME_ENTITY, True, True),
            self.labeled("2", LABEL_SAME_ENTITY, True, False),
            self.labeled("3", LABEL_SAME_ENTITY, False, False),
            self.labeled("4", LABEL_RELATED_SEPARATE, True, True),
            self.labeled("5", LABEL_UNRELATED, True, False),
            self.labeled("6", LABEL_UNCERTAIN, False, False),
        ]

        metrics = calculate_pilot_metrics(
            rows, required_split=SPLIT_LOCKED_EVALUATION
        )

        self.assertEqual(metrics.automatic_merge_precision, 0.5)
        self.assertAlmostEqual(metrics.candidate_recall, 2 / 3)
        self.assertAlmostEqual(metrics.review_rate, 2 / 6)
        self.assertEqual(metrics.false_automatic_merges, 1)
        self.assertEqual(metrics.missed_same_entities, 1)
        self.assertEqual(metrics.error_counts["auto_merged_related_separate"], 1)
        self.assertFalse(metrics.release_gate_pass)

    def test_release_gate_uses_fixed_precision_and_recall_thresholds(self):
        rows = [
            self.labeled("1", LABEL_SAME_ENTITY, True, True),
            self.labeled("2", LABEL_UNRELATED, True, False),
        ]
        metrics = calculate_pilot_metrics(rows)
        result = metrics.as_dict()

        self.assertEqual(
            result["thresholds"]["automatic_merge_precision"],
            MIN_AUTOMATIC_MERGE_PRECISION,
        )
        self.assertEqual(
            result["thresholds"]["candidate_recall"], MIN_CANDIDATE_RECALL
        )
        self.assertTrue(metrics.release_gate_pass)

    def test_empty_denominators_do_not_become_perfect_scores(self):
        metrics = calculate_pilot_metrics([
            self.labeled("1", LABEL_UNRELATED, False, False),
            self.labeled("2", LABEL_UNCERTAIN, False, False),
        ])

        self.assertIsNone(metrics.automatic_merge_precision)
        self.assertIsNone(metrics.candidate_recall)
        self.assertFalse(metrics.precision_pass)
        self.assertFalse(metrics.recall_pass)
        self.assertFalse(metrics.release_gate_pass)

    def test_incomplete_labels_and_inconsistent_predictions_are_rejected(self):
        with self.assertRaisesRegex(PilotValidationError, "invalid or blank"):
            calculate_pilot_metrics([
                self.labeled("1", "", True, False)
            ])
        with self.assertRaisesRegex(PilotValidationError, "not a candidate"):
            calculate_pilot_metrics([
                self.labeled("1", LABEL_SAME_ENTITY, False, True)
            ])

    def test_locked_score_rejects_development_row(self):
        row = self.labeled("1", LABEL_SAME_ENTITY, True, True)
        row["project_split"] = SPLIT_DEVELOPMENT
        with self.assertRaisesRegex(PilotValidationError, "not in required split"):
            calculate_pilot_metrics(
                [row], required_split=SPLIT_LOCKED_EVALUATION
            )

    def test_metrics_json_contains_calculated_values_only(self):
        metrics = calculate_pilot_metrics([
            self.labeled("1", LABEL_SAME_ENTITY, True, True)
        ])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "metrics.json"
            digest = write_metrics_json(metrics, output)
            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertEqual(result["total_pairs"], 1)
        self.assertEqual(result["automatic_merge_precision"], 1.0)
        self.assertTrue(result["release_gate_pass"])


if __name__ == "__main__":
    unittest.main()
