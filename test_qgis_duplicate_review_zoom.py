import sys
import unittest
from pathlib import Path


try:
    from qgis.core import QgsApplication

    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python runtime is not available")
class DuplicateReviewZoomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], False)
        cls.app.initQgis()

        plugin_parent = str(Path(__file__).resolve().parent.parent)
        if plugin_parent not in sys.path:
            sys.path.insert(0, plugin_parent)

        from ArchDistribution.heritage_matching_dialog import (
            DuplicateReviewDialog,
        )

        cls.dialog_class = DuplicateReviewDialog

    def _candidates(self):
        return [
            {
                "left_uid": "designated-1",
                "right_uid": "distribution-1",
                "left_role": "local_designated",
                "right_role": "distribution",
                "left_name": "첫 번째 후보",
                "right_name": "첫 번째 후보",
                "pair_kind": "designated_distribution",
                "confidence": "high",
                "overlap_ratio": 1.0,
                "distance": 0,
                "rule": "exact_name_and_overlap",
                "recommended_decision": "merge",
                "auto_apply": False,
            },
            {
                "left_uid": "excavation-2",
                "right_uid": "distribution-2",
                "left_role": "excavation",
                "right_role": "distribution",
                "left_name": "두 번째 후보",
                "right_name": "두 번째 후보",
                "pair_kind": "excavation_distribution",
                "confidence": "medium",
                "overlap_ratio": 0.5,
                "distance": 3,
                "rule": "fuzzy_name_and_overlap",
                "recommended_decision": "keep",
                "auto_apply": False,
            },
        ]

    def test_zoom_button_is_disabled_without_callback(self):
        dialog = self.dialog_class(self._candidates())
        self.addCleanup(dialog.close)

        self.assertFalse(dialog.btn_zoom.isEnabled())

    def test_zoom_button_uses_first_or_current_candidate(self):
        received = []
        dialog = self.dialog_class(
            self._candidates(),
            zoom_callback=received.append,
        )
        self.addCleanup(dialog.close)

        self.assertTrue(dialog.btn_zoom.isEnabled())
        dialog.btn_zoom.click()
        self.assertEqual(received[-1]["left_uid"], "designated-1")

        dialog.table.setCurrentCell(1, 3)
        dialog.btn_zoom.click()
        self.assertEqual(received[-1]["left_uid"], "excavation-2")

    def test_row_double_click_zooms_and_callback_error_is_contained(self):
        received = []
        dialog = self.dialog_class(
            self._candidates(),
            zoom_callback=received.append,
        )
        self.addCleanup(dialog.close)

        dialog.table.cellDoubleClicked.emit(1, 6)
        self.assertEqual(received[-1]["right_uid"], "distribution-2")
        self.assertIsNone(dialog.last_zoom_error)

        def fail_zoom(_candidate):
            raise RuntimeError("canvas unavailable")

        dialog.zoom_callback = fail_zoom
        dialog.table.cellDoubleClicked.emit(0, 3)
        self.assertIsInstance(dialog.last_zoom_error, RuntimeError)
        self.assertEqual(dialog.result(), 0)

    def test_english_review_translates_controls_but_preserves_candidate_values(self):
        candidates = self._candidates()
        candidates[0].update(
            rule="survey_revision_same_site",
            auto_apply=True,
            overlap_ratio=None,
            distance=None,
        )
        candidates[1]["rule"] = "affix_omitted_generic_name_within_distance"
        dialog = self.dialog_class(candidates, ui_lang="en")
        self.addCleanup(dialog.close)

        self.assertEqual(dialog.action_combos[0].currentText(), "Share one map number")
        merge_index = dialog.bulk_action.findData("merge")
        self.assertEqual(dialog.bulk_action.itemText(merge_index), "Share one map number")
        self.assertEqual(dialog.table.item(0, 1).text(), "High · Auto-selected")
        self.assertEqual(dialog.table.item(0, 3).text(), candidates[0]["left_name"])
        self.assertEqual(dialog.table.item(0, 8).text(), "—")
        self.assertEqual(dialog.table.item(0, 9).text(), "—")
        self.assertEqual(dialog.table.item(1, 9).text(), "3.0 m")
        self.assertEqual(
            dialog.table.item(0, 10).text(),
            "Possible surface-survey update to the same site",
        )
        self.assertEqual(
            dialog.table.item(1, 10).text(),
            "Generic name missing a qualifier at a nearby location",
        )
        decisions = dialog.decisions()
        self.assertEqual(decisions[0]["rule"], candidates[0]["rule"])
        self.assertEqual(decisions[0]["decision"], "merge")
        self.assertEqual(decisions[0]["decision_source"], "auto")
        self.assertEqual(decisions[1]["rule"], candidates[1]["rule"])

    def test_english_keep_button_applies_to_only_rows_shown_by_filter(self):
        candidates = self._candidates()
        for candidate in candidates:
            candidate.update(auto_apply=True, recommended_decision="merge")
        dialog = self.dialog_class(candidates, ui_lang="en")
        self.addCleanup(dialog.close)

        pair_index = dialog.pair_filter.findData("designated_distribution")
        dialog.pair_filter.setCurrentIndex(pair_index)
        self.assertEqual(dialog.btn_keep.text(), "Keep shown rows separate")
        dialog.btn_keep.click()
        self.assertEqual([row["decision"] for row in dialog.decisions()], ["keep", "merge"])
        self.assertEqual(dialog.summary.text(), "All rows · Keep 1 · Link 0 · Share 1")


if __name__ == "__main__":
    unittest.main()
