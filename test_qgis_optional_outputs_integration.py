import gc
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


try:
    from qgis.PyQt.QtCore import QSettings, QVariant
    from qgis.PyQt.QtGui import QImageReader
    from qgis.core import (
        QgsApplication,
        QgsCoordinateReferenceSystem,
        QgsFeature,
        QgsField,
        QgsGeometry,
        QgsLayoutItemMap,
        QgsProject,
        QgsRectangle,
        QgsVectorLayer,
    )

    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python runtime is not available")
class QgisOptionalOutputsIntegrationTests(unittest.TestCase):
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

        from processing.core.Processing import Processing
        from ArchDistribution.arch_distribution import ArchDistribution
        from ArchDistribution.arch_distribution_dialog import (
            ArchDistributionDialog,
            EXPORT_JPG_PREF_KEY,
            EXPORT_PDF_PREF_KEY,
            OUTPUT_DIRECTORY_PREF_KEY,
            SAVE_GPKG_PREF_KEY,
            get_plugin_version,
        )

        Processing.initialize()
        cls.plugin_class = ArchDistribution
        cls.dialog_class = ArchDistributionDialog
        cls.get_plugin_version = staticmethod(get_plugin_version)
        cls.output_setting_keys = (
            OUTPUT_DIRECTORY_PREF_KEY,
            SAVE_GPKG_PREF_KEY,
            EXPORT_JPG_PREF_KEY,
            EXPORT_PDF_PREF_KEY,
        )

    def setUp(self):
        self.project = QgsProject.instance()
        self.project.clear()
        self.project.setCrs(QgsCoordinateReferenceSystem("EPSG:5186"))
        self.temp_directory = tempfile.TemporaryDirectory()
        self.output_directory = Path(self.temp_directory.name)
        self.plugin = self.plugin_class(None)
        self.plugin.log = lambda _message: None

    def tearDown(self):
        manager = self.project.layoutManager()
        for layout in list(manager.layouts()):
            manager.removeLayout(layout)
        self.project.clear()
        gc.collect()
        self.temp_directory.cleanup()

    def _make_temporary_output_group(self):
        root = self.project.layerTreeRoot()
        output_group = root.addGroup("ArchDistribution_작업중")
        spatial_group = output_group.addGroup("유적_결과")
        audit_group = output_group.addGroup("검수_테이블")

        spatial = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "주변유적_대표",
            "memory",
        )
        spatial.dataProvider().addAttributes([
            QgsField("NAME", QVariant.String),
            QgsField("SRC_UID", QVariant.String),
            QgsField("SRC_JSON", QVariant.String),
        ])
        spatial.updateFields()
        spatial_rows = (
            (
                "공주 신관동 유적",
                "distribution:site-1",
                '{"명칭":"공주 신관동 유적","source":"분포지도"}',
                "POLYGON((200000 450000,201000 450000,"
                "201000 451000,200000 451000,200000 450000))",
            ),
            (
                "공주 월송 발굴유적",
                "excavation:site-2",
                '{"유적명":"공주 월송 발굴유적","사업명":"국민임대주택"}',
                "POLYGON((202000 452000,203000 452000,"
                "203000 453000,202000 453000,202000 452000))",
            ),
        )
        features = []
        for name, uid, source_json, wkt in spatial_rows:
            feature = QgsFeature(spatial.fields())
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
            feature["NAME"] = name
            feature["SRC_UID"] = uid
            feature["SRC_JSON"] = source_json
            features.append(feature)
        spatial.dataProvider().addFeatures(features)
        spatial.updateExtents()

        audit = QgsVectorLayer("None", "중복_검수", "memory")
        self.assertTrue(audit.isValid())
        audit.dataProvider().addAttributes([
            QgsField("SRC_UID", QVariant.String),
            QgsField("MATCH_STATUS", QVariant.String),
            QgsField("SRC_JSON", QVariant.String),
        ])
        audit.updateFields()
        audit_rows = (
            (
                "distribution:site-1",
                "대표",
                '{"decision":"merge","representative":"distribution:site-1"}',
            ),
            (
                "excavation:site-2",
                "별도 유지",
                '{"decision":"keep","reason":"different investigation"}',
            ),
            (
                "surface:site-3",
                "연결만",
                '{"decision":"link","relation":"same place"}',
            ),
        )
        audit_features = []
        for uid, status, source_json in audit_rows:
            feature = QgsFeature(audit.fields())
            feature["SRC_UID"] = uid
            feature["MATCH_STATUS"] = status
            feature["SRC_JSON"] = source_json
            audit_features.append(feature)
        audit.dataProvider().addFeatures(audit_features)

        self.project.addMapLayer(spatial, False)
        spatial_group.addLayer(spatial)
        self.project.addMapLayer(audit, False)
        audit_group.addLayer(audit)
        return output_group, spatial, audit

    def _open_gpkg_layer(self, gpkg_path, layer_name):
        layer = QgsVectorLayer(
            f"{gpkg_path}|layername={layer_name}",
            layer_name,
            "ogr",
        )
        self.assertTrue(
            layer.isValid(),
            f"Failed to reopen {layer_name} from {gpkg_path}",
        )
        return layer

    @staticmethod
    def _distribution_layout_settings(output_directory):
        return {
            "paper_width": 160,
            "paper_height": 240,
            "scale": 25000,
            "output_directory": str(output_directory),
        }

    def test_writes_spatial_and_nonspatial_results_to_one_gpkg(self):
        output_group, spatial, audit = self._make_temporary_output_group()
        target = self.output_directory / "선택결과.gpkg"

        exported = self.plugin._write_output_group_to_gpkg(
            output_group,
            target,
        )

        self.assertTrue(target.is_file())
        self.assertGreater(target.stat().st_size, 0)
        self.assertEqual(len(exported), 2)
        self.assertEqual(
            {item["name"] for item in exported},
            {spatial.name(), audit.name()},
        )
        self.assertEqual(
            {item["name"]: item["feature_count"] for item in exported},
            {
                spatial.name(): 2,
                audit.name(): 3,
            },
        )

        reopened = {}
        for item in exported:
            reopened[item["name"]] = self._open_gpkg_layer(
                target,
                item["gpkg_layer"],
            )

        spatial_copy = reopened[spatial.name()]
        audit_copy = reopened[audit.name()]
        self.assertEqual(spatial_copy.featureCount(), 2)
        self.assertEqual(audit_copy.featureCount(), 3)
        self.assertTrue(spatial_copy.isSpatial())
        self.assertFalse(audit_copy.isSpatial())
        self.assertTrue(
            {"NAME", "SRC_UID", "SRC_JSON"}.issubset(
                {field.name() for field in spatial_copy.fields()}
            )
        )
        self.assertTrue(
            {"SRC_UID", "MATCH_STATUS", "SRC_JSON"}.issubset(
                {field.name() for field in audit_copy.fields()}
            )
        )
        self.assertEqual(
            {feature["SRC_JSON"] for feature in spatial_copy.getFeatures()},
            {row[2] for row in (
                (
                    "공주 신관동 유적",
                    "distribution:site-1",
                    '{"명칭":"공주 신관동 유적","source":"분포지도"}',
                ),
                (
                    "공주 월송 발굴유적",
                    "excavation:site-2",
                    '{"유적명":"공주 월송 발굴유적","사업명":"국민임대주택"}',
                ),
            )},
        )
        self.assertEqual(
            {feature["SRC_JSON"] for feature in audit_copy.getFeatures()},
            {
                '{"decision":"merge","representative":"distribution:site-1"}',
                '{"decision":"keep","reason":"different investigation"}',
                '{"decision":"link","relation":"same place"}',
            },
        )

    def test_exports_report_size_layout_to_jpg_and_pdf(self):
        # A real post-processing layout always has the just-created result
        # group available to the project map theme.
        self._make_temporary_output_group()
        image_path = self.output_directory / "신관동_주변유적.jpg"
        pdf_path = self.output_directory / "신관동_주변유적.pdf"
        extent = QgsGeometry.fromRect(
            QgsRectangle(200000, 450000, 204000, 456000)
        )
        crs = QgsCoordinateReferenceSystem("EPSG:5186")

        result = self.plugin._export_print_layout(
            self._distribution_layout_settings(self.output_directory),
            extent,
            crs,
            "distribution_map",
            base_name="신관동_인쇄조판",
            image_path=image_path,
            pdf_path=pdf_path,
        )

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["paper_mm"], [160.0, 240.0])
        self.assertEqual(result["scale"], 25000.0)
        self.assertEqual(
            set(result["paths"]),
            {str(image_path), str(pdf_path)},
        )
        for path in (image_path, pdf_path):
            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 100)

        image_size = QImageReader(str(image_path)).size()
        self.assertTrue(image_size.isValid())
        expected_width = round(160 / 25.4 * 300)
        expected_height = round(240 / 25.4 * 300)
        self.assertLessEqual(abs(image_size.width() - expected_width), 2)
        self.assertLessEqual(abs(image_size.height() - expected_height), 2)
        self.assertAlmostEqual(
            image_size.width() / image_size.height(),
            160 / 240,
            delta=0.002,
        )

        layout = self.project.layoutManager().layoutByName(
            result["layout_name"]
        )
        self.assertIsNotNone(layout)
        map_items = [
            item for item in layout.items()
            if isinstance(item, QgsLayoutItemMap)
        ]
        self.assertEqual(len(map_items), 1)
        self.assertAlmostEqual(
            map_items[0].scale(),
            25000,
            delta=1,
            msg=(
                f"extent={map_items[0].extent().toString()}, "
                f"rect={map_items[0].rect()}, "
                f"size={map_items[0].sizeWithUnits()}"
            ),
        )

    def test_print_layout_uses_extent_crs_when_project_crs_differs(self):
        self.project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        extent_crs = QgsCoordinateReferenceSystem("EPSG:5179")
        extent_rectangle = QgsRectangle(
            958000,
            1917000,
            962000,
            1923000,
        )
        extent = QgsGeometry.fromRect(extent_rectangle)

        result = self.plugin._export_print_layout(
            self._distribution_layout_settings(self.output_directory),
            extent,
            extent_crs,
            "distribution_map",
            base_name="cross_crs_distribution_layout",
        )

        self.assertEqual(result["errors"], [])
        layout = self.project.layoutManager().layoutByName(
            result["layout_name"]
        )
        self.assertIsNotNone(layout)
        map_items = [
            item for item in layout.items()
            if isinstance(item, QgsLayoutItemMap)
        ]
        self.assertEqual(len(map_items), 1)

        map_item = map_items[0]
        self.assertEqual(map_item.crs().authid(), "EPSG:5179")
        self.assertAlmostEqual(map_item.scale(), 25000, delta=1)

        map_extent = map_item.extent()
        self.assertAlmostEqual(map_extent.xMinimum(), 958000, delta=0.01)
        self.assertAlmostEqual(map_extent.yMinimum(), 1917000, delta=0.01)
        self.assertAlmostEqual(map_extent.xMaximum(), 962000, delta=0.01)
        self.assertAlmostEqual(map_extent.yMaximum(), 1923000, delta=0.01)
        self.assertAlmostEqual(map_extent.width(), 4000, delta=0.01)
        self.assertAlmostEqual(map_extent.height(), 6000, delta=0.01)
        self.assertTrue(map_extent.contains(extent_rectangle))

    def test_optional_outputs_create_complete_artifact_bundle(self):
        output_group, spatial, audit = self._make_temporary_output_group()
        settings = self._distribution_layout_settings(
            self.output_directory
        )
        settings.update({
            "save_gpkg_manifest": True,
            "export_layout_jpg": True,
            "export_layout_pdf": True,
            "study_area_id": spatial.id(),
            "topo_layer_ids": [],
            "heritage_layer_ids": [],
            "source_roles": {},
            "zone_layer_id": None,
        })
        self.plugin._current_processing_stats = {
            "candidate_count": 7,
            "decision_reuse_count": 2,
        }
        extent = QgsGeometry.fromRect(
            QgsRectangle(200000, 450000, 204000, 456000)
        )

        result = self.plugin._run_optional_outputs(
            settings,
            output_group,
            extent,
            QgsCoordinateReferenceSystem("EPSG:5186"),
            "distribution_map",
            datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["paths"]), 4)
        paths_by_suffix = {
            Path(path).suffix.casefold(): Path(path)
            for path in result["paths"]
        }
        self.assertEqual(
            set(paths_by_suffix),
            {".gpkg", ".jpg", ".pdf", ".json"},
        )
        for path in paths_by_suffix.values():
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 0)

        manifest = json.loads(
            paths_by_suffix[".json"].read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["plugin"]["version"], "1.0.5")
        self.assertEqual(
            manifest["plugin"]["version"],
            self.get_plugin_version(),
        )
        self.assertEqual(manifest["workflow"], "distribution_map")
        self.assertEqual(manifest["status"], "success")
        self.assertEqual(
            {item["name"]: item["feature_count"]
             for item in manifest["outputs"]},
            {
                spatial.name(): 2,
                audit.name(): 3,
            },
        )
        self.assertEqual(
            manifest["processing"]["decision_reuse_count"],
            2,
        )
        statistics = manifest["processing"]["statistics"]
        self.assertEqual(statistics["candidate_count"], 7)
        self.assertEqual(len(statistics["gpkg_layers"]), 2)
        self.assertEqual(
            {item["name"]: item["feature_count"]
             for item in statistics["gpkg_layers"]},
            {
                spatial.name(): 2,
                audit.name(): 3,
            },
        )
        artifact_paths = {Path(path) for path in statistics["artifacts"]}
        self.assertEqual(
            {path.suffix.casefold() for path in artifact_paths},
            {".gpkg", ".jpg", ".pdf"},
        )
        self.assertTrue(all(path.is_file() for path in artifact_paths))

    def _restore_output_preferences(self, previous):
        settings = QSettings()
        for key, (existed, value) in previous.items():
            settings.remove(key)
            if existed:
                settings.setValue(key, value)
        settings.sync()

    def test_optional_output_controls_default_off_and_feed_settings(self):
        qsettings = QSettings()
        previous = {
            key: (qsettings.contains(key), qsettings.value(key))
            for key in self.output_setting_keys
        }
        self.addCleanup(self._restore_output_preferences, previous)
        for key in self.output_setting_keys:
            qsettings.remove(key)
        qsettings.sync()

        dialog = self.dialog_class()
        self.addCleanup(dialog.close)

        self.assertFalse(dialog.chkSaveGpkgManifest.isChecked())
        self.assertFalse(dialog.chkExportLayoutJpg.isChecked())
        self.assertFalse(dialog.chkExportLayoutPdf.isChecked())
        initial = dialog.get_settings()
        self.assertFalse(initial["save_gpkg_manifest"])
        self.assertFalse(initial["export_layout_jpg"])
        self.assertFalse(initial["export_layout_pdf"])

        dialog.lineOutputDirectory.setText(str(self.output_directory))
        dialog.chkSaveGpkgManifest.setChecked(True)
        dialog.chkExportLayoutJpg.setChecked(True)
        dialog.chkExportLayoutPdf.setChecked(True)
        selected = dialog.get_settings()
        self.assertEqual(
            selected["output_directory"],
            str(self.output_directory),
        )
        self.assertTrue(selected["save_gpkg_manifest"])
        self.assertTrue(selected["export_layout_jpg"])
        self.assertTrue(selected["export_layout_pdf"])


if __name__ == "__main__":
    unittest.main()
