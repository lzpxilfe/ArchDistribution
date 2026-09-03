import sys
import unittest
from unittest import mock
from pathlib import Path


try:
    from qgis.PyQt import QtWidgets
    from qgis.PyQt.QtCore import Qt, QVariant
    from qgis.core import (
        QgsApplication,
        QgsFeature,
        QgsField,
        QgsGeometry,
        QgsProject,
        QgsVectorLayer,
    )

    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python runtime is not available")
class QgisDialogWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], False)
        cls.app.initQgis()

        qgis_python_plugins = str(
            Path(QgsApplication.prefixPath()) / "python" / "plugins"
        )
        if qgis_python_plugins not in sys.path:
            sys.path.insert(0, qgis_python_plugins)

        plugin_parent = str(Path(__file__).resolve().parent.parent)
        if plugin_parent not in sys.path:
            sys.path.insert(0, plugin_parent)

        from ArchDistribution.arch_distribution_dialog import (
            ArchDistributionDialog,
        )
        from ArchDistribution.arch_distribution import ArchDistribution
        from ArchDistribution.heritage_matching_dialog import (
            DuplicateReviewDialog,
        )
        from processing.core.Processing import Processing

        Processing.initialize()
        cls.dialog_class = ArchDistributionDialog
        cls.plugin_class = ArchDistribution
        cls.review_dialog_class = DuplicateReviewDialog
        from ArchDistribution.attribute_classification import (
            build_reference_name_index,
        )
        cls.build_reference_name_index = staticmethod(
            build_reference_name_index
        )

    def setUp(self):
        QgsProject.instance().clear()

    @staticmethod
    def _add_archdistribution_result(name, is_rep=1, number_key="site:a"):
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            name,
            "memory",
        )
        layer.dataProvider().addAttributes([
            QgsField("번호", QVariant.Int),
            QgsField("SRC_UID", QVariant.String),
            QgsField("NUMBER_KEY", QVariant.String),
            QgsField("GROUP_KEY", QVariant.String),
            QgsField("IS_REP", QVariant.Int),
            QgsField("SRC_JSON", QVariant.String),
            QgsField("SOURCE_ROLE", QVariant.String),
            QgsField("MATCH_STATUS", QVariant.String),
            QgsField("LABEL_OK", QVariant.Int),
        ])
        layer.updateFields()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(
            "POLYGON((0 0,10 0,10 10,0 10,0 0))"
        ))
        feature["번호"] = 7
        feature["SRC_UID"] = f"{name}:1"
        feature["NUMBER_KEY"] = number_key
        feature["GROUP_KEY"] = number_key
        feature["IS_REP"] = is_rep
        feature["SRC_JSON"] = "{}"
        feature["SOURCE_ROLE"] = (
            "protection_zone"
            if not number_key
            else "distribution"
        )
        feature["MATCH_STATUS"] = (
            "PROTECTION_ZONE"
            if not number_key
            else "UNIQUE"
        )
        feature["LABEL_OK"] = 1 if is_rep else 0
        layer.dataProvider().addFeature(feature)
        QgsProject.instance().addMapLayer(layer)
        return layer

    def test_two_workflows_and_preservation_style_controls_exist(self):
        dialog = self.dialog_class()
        self.addCleanup(dialog.close)

        self.assertEqual(dialog.workflowTabs.count(), 2)
        self.assertTrue(dialog.chkExcludeExtentSlivers.isChecked())
        self.assertTrue(
            dialog.chkPreservationExcludeExtentSlivers.isChecked()
        )
        self.assertFalse(dialog.chkBufferKmLabels.isChecked())
        self.assertEqual(
            set(dialog.preservationColorButtons),
            {"현상보존", "정밀발굴조사", "시굴조사", "표본조사"},
        )

        dialog.workflowTabs.setCurrentIndex(0)
        self.assertEqual(
            dialog.get_settings()["workflow_mode"],
            "distribution",
        )
        dialog.chkBufferKmLabels.setChecked(True)
        self.assertTrue(
            dialog.get_settings()["buffer_style"]["format_km_labels"]
        )
        dialog.workflowTabs.setCurrentIndex(1)
        settings = dialog.get_settings()
        self.assertEqual(settings["workflow_mode"], "preservation")
        self.assertTrue(
            settings["preservation_exclude_extent_slivers"]
        )
        self.assertEqual(settings["preservation_scale"], 5000)
        self.assertEqual(
            set(settings["preservation_action_styles"]),
            {"현상보존", "정밀발굴조사", "시굴조사", "표본조사"},
        )
        self.assertEqual(dialog.workflowTabs.currentIndex(), 1)

    def test_verified_preservation_layer_is_kept_out_of_heritage_list(self):
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "유존지역입력",
            "memory",
        )
        layer.dataProvider().addAttributes([
            QgsField("보존조치", QVariant.String),
        ])
        layer.updateFields()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(
            "POLYGON((0 0,1 0,1 1,0 1,0 0))"
        ))
        feature["보존조치"] = "시굴조사"
        layer.dataProvider().addFeature(feature)
        QgsProject.instance().addMapLayer(layer)

        dialog = self.dialog_class()
        self.addCleanup(dialog.close)

        heritage_ids = {
            dialog.listHeritageLayers.item(index).data(Qt.UserRole)
            for index in range(dialog.listHeritageLayers.count())
        }
        self.assertNotIn(layer.id(), heritage_ids)
        dialog.comboPreservationLayer.setLayer(layer)
        self.assertEqual(
            dialog.comboPreservationActionField.currentData(),
            "보존조치",
        )
        encoding_index = dialog.comboPreservationEncoding.findData("UTF-8")
        dialog.comboPreservationEncoding.setCurrentIndex(encoding_index)
        self.assertEqual(
            layer.customProperty("ArchDistribution/encoding_override"),
            "UTF-8",
        )
        self.assertEqual(
            dialog.get_settings()["preservation_encoding"], "UTF-8"
        )

    def test_source_role_overrides_and_balanced_preset_are_available(self):
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "발굴유적위치도",
            "memory",
        )
        layer.dataProvider().addAttributes([
            QgsField("사업명", QVariant.String),
            QgsField("유적명", QVariant.String),
            QgsField("보고서명", QVariant.String),
        ])
        layer.updateFields()
        QgsProject.instance().addMapLayer(layer)

        dialog = self.dialog_class()
        self.addCleanup(dialog.close)
        settings = dialog.get_settings()

        self.assertEqual(settings["match_preset"], "balanced")
        self.assertIn(layer.id(), dialog.layerRoleCombos)
        self.assertIn(layer.id(), dialog.layerEncodingCombos)
        self.assertEqual(
            dialog.layerRoleCombos[layer.id()].currentData(),
            "excavation",
        )
        encoding_combo = dialog.layerEncodingCombos[layer.id()]
        encoding_combo.setCurrentIndex(
            encoding_combo.findData("CP949")
        )
        layer_item = next(
            dialog.listHeritageLayers.item(index)
            for index in range(dialog.listHeritageLayers.count())
            if dialog.listHeritageLayers.item(index).data(Qt.UserRole)
            == layer.id()
        )
        layer_item.setCheckState(Qt.Checked)
        settings = dialog.get_settings()
        self.assertEqual(
            settings["source_encodings"][layer.id()], "CP949"
        )
        self.assertEqual(
            layer.customProperty(
                "ArchDistribution/encoding_override"
            ),
            "CP949",
        )

    def test_attribute_scan_uses_local_reference_name_with_spacing(self):
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "주변유적",
            "memory",
        )
        layer.dataProvider().addAttributes([
            QgsField("유적명", QVariant.String),
        ])
        layer.updateFields()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(
            "POLYGON((0 0,1 0,1 1,0 1,0 0))"
        ))
        feature["유적명"] = "공주 정지산 유적"
        layer.dataProvider().addFeature(feature)
        QgsProject.instance().addMapLayer(layer)

        dialog = self.dialog_class()
        self.addCleanup(dialog.close)
        dialog.reference_data = {
            "공주정지산유적": {
                "e": "삼국시대",
                "t": "주거유적",
            },
        }
        dialog.reference_data_normalized = self.build_reference_name_index(
            dialog.reference_data
        )
        layer_item = next(
            dialog.listHeritageLayers.item(index)
            for index in range(dialog.listHeritageLayers.count())
            if dialog.listHeritageLayers.item(index).data(Qt.UserRole)
            == layer.id()
        )
        layer_item.setCheckState(Qt.Checked)

        with mock.patch.object(
            dialog,
            "_apply_automatic_shapefile_encoding",
            wraps=dialog._apply_automatic_shapefile_encoding,
        ) as encoding_check:
            dialog.scan_categories()
        encoding_check.assert_called_once_with(layer)

        self.assertEqual(
            [dialog.listEras.item(i).text()
             for i in range(dialog.listEras.count())],
            ["삼국시대"],
        )
        self.assertEqual(
            [dialog.listTypes.item(i).text()
             for i in range(dialog.listTypes.count())],
            ["주거유적"],
        )

    def test_unchecked_reference_category_excludes_during_analysis(self):
        plugin = self.plugin_class(None)
        plugin.reference_data = {
            "공주정지산유적": {
                "e": "삼국시대",
                "t": "주거유적",
            },
        }
        plugin.reference_data_normalized = self.build_reference_name_index(
            plugin.reference_data
        )
        plugin.smart_patterns = {"noise": [], "artifacts": {}}
        selection = {
            "available": {"ERA:삼국시대", "TYPE:주거유적"},
            "allowed": {"TYPE:주거유적"},
        }

        self.assertTrue(plugin.should_exclude(
            "공주 정지산 유적",
            selection,
        ))

    def test_existing_representative_result_has_dedicated_renumber_path(self):
        result = self._add_archdistribution_result(
            "사용자가_이름을_바꾼_대표결과",
        )
        ordinary = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "일반유적",
            "memory",
        )
        ordinary.dataProvider().addAttributes([
            QgsField("번호", QVariant.Int),
            QgsField("유적명", QVariant.String),
        ])
        ordinary.updateFields()
        QgsProject.instance().addMapLayer(ordinary)

        dialog = self.dialog_class()
        self.addCleanup(dialog.close)

        self.assertEqual(dialog.comboPreviousResultLayer.count(), 1)
        self.assertEqual(
            dialog.comboPreviousResultLayer.currentData(),
            result.id(),
        )
        self.assertTrue(dialog.btnRenumberPreviousResult.isEnabled())
        self.assertIn(
            "NUMBER_KEY",
            dialog.lblPreviousResultHelp.text(),
        )
        self.assertIn(
            "1",
            dialog.lblPreviousResultStatus.text(),
        )

        emitted = []
        dialog.renumber_requested.connect(emitted.append)
        dialog.renumber_previous_result()
        self.assertEqual(emitted, [result])

        result_item = next(
            dialog.listHeritageLayers.item(index)
            for index in range(dialog.listHeritageLayers.count())
            if dialog.listHeritageLayers.item(index).data(Qt.UserRole)
            == result.id()
        )
        self.assertTrue(result_item.data(Qt.UserRole + 1))
        result_item.setCheckState(Qt.Checked)
        self.assertFalse(dialog.lblPreviousResultInputWarning.isHidden())
        self.assertIn(
            result.name(),
            dialog.lblPreviousResultInputWarning.text(),
        )

        runs = []
        dialog.run_requested.connect(runs.append)
        with mock.patch.object(
            dialog,
            "_confirm_previous_result_reprocessing",
            return_value=False,
        ) as confirm:
            dialog.emit_run_requested()
        confirm.assert_called_once()
        self.assertEqual(runs, [])

        with mock.patch.object(
            dialog,
            "_confirm_previous_result_reprocessing",
            return_value=True,
        ):
            dialog.emit_run_requested()
        self.assertEqual(len(runs), 1)

    def test_auxiliary_results_are_not_offered_and_are_blocked(self):
        suppressed = self._add_archdistribution_result(
            "중복_보존",
            is_rep=0,
            number_key="site:suppressed",
        )
        protection = self._add_archdistribution_result(
            "지정유산_보호구역",
            is_rep=0,
            number_key="",
        )
        dialog = self.dialog_class()
        self.addCleanup(dialog.close)

        self.assertEqual(dialog.comboPreviousResultLayer.count(), 0)
        self.assertEqual(
            dialog._classify_result_layer(suppressed)["kind"],
            "suppressed",
        )
        self.assertEqual(
            dialog._classify_result_layer(protection)["kind"],
            "protection",
        )

        emitted = []
        dialog.renumber_requested.connect(emitted.append)
        with mock.patch.object(
            QtWidgets.QMessageBox,
            "warning",
            return_value=QtWidgets.QMessageBox.Ok,
        ) as warning:
            dialog._request_renumber(suppressed)
            dialog._request_renumber(protection)
        self.assertEqual(emitted, [])
        self.assertEqual(warning.call_count, 2)

    def test_matching_help_explains_decisions_and_renumbering_boundary(self):
        dialog = self.dialog_class()
        self.addCleanup(dialog.close)
        dialog.ui_lang = "ko"
        help_html = dialog._matching_rules_help_html()

        self.assertIn("도형이 겹친다는 이유만으로", help_html)
        self.assertIn("별도 유지", help_html)
        self.assertIn("연결만", help_html)
        self.assertIn("대표 번호로 묶기", help_html)
        self.assertIn("NUMBER_KEY", help_html)
        self.assertIn("중복 재분석이 아닙니다", help_html)

    def test_duplicate_review_defaults_are_safe(self):
        candidates = [
            {
                "left_uid": "d1",
                "right_uid": "m1",
                "left_role": "local_designated",
                "right_role": "distribution",
                "left_source": "시도지정문화유산",
                "right_source": "문화유적분포지도",
                "left_name": "공주 A유적",
                "right_name": "공주 A유적",
                "left_address": "공주시 A동",
                "right_address": "공주시 A동",
                "pair_kind": "designated_distribution",
                "confidence": "high",
                "score": 0.9,
                "overlap_ratio": 1.0,
                "distance": 0,
                "rule": "exact_name_and_overlap",
                "recommended_decision": "merge",
                "representative_uid": "d1",
                "auto_apply": True,
            },
            {
                "left_uid": "s1",
                "right_uid": "e1",
                "left_role": "surface_survey",
                "right_role": "excavation",
                "left_name": "공주 B유적",
                "right_name": "공주 B유적",
                "pair_kind": "surface",
                "confidence": "high",
                "score": 0.9,
                "overlap_ratio": 1.0,
                "distance": 0,
                "rule": "exact_name_and_overlap",
                "recommended_decision": "keep",
                "representative_uid": "e1",
                "auto_apply": False,
            },
        ]
        dialog = self.review_dialog_class(candidates)
        self.addCleanup(dialog.close)

        decisions = dialog.decisions()
        self.assertEqual(decisions[0]["decision"], "merge")
        self.assertEqual(decisions[1]["decision"], "keep")
        intro_text = dialog.layout().itemAt(0).widget().text()
        self.assertTrue(
            "도형을 삭제하는 화면" in intro_text
            or "does not delete geometry" in intro_text
        )
        self.assertIn("시도지정문화유산", dialog.table.item(0, 2).text())
        self.assertEqual(dialog.table.item(0, 4).text(), "공주시 A동")

        dialog.pair_filter.setCurrentIndex(
            dialog.pair_filter.findData("designated_distribution")
        )
        dialog.bulk_action.setCurrentIndex(
            dialog.bulk_action.findData("link")
        )
        dialog._bulk_apply_to_visible()
        decisions = dialog.decisions()
        self.assertEqual(decisions[0]["decision"], "link")
        self.assertEqual(decisions[1]["decision"], "keep")


if __name__ == "__main__":
    unittest.main()
