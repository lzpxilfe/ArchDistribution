import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


try:
    from qgis.PyQt.QtCore import QVariant
    from qgis.core import (
        QgsApplication,
        QgsFeature,
        QgsField,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsVectorLayer,
    )

    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


class _FakeButton:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, enabled):
        self.enabled = enabled


class _FakeDialog:
    def __init__(self):
        self.btnRun = _FakeButton()


class _FakeMessageBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, *args, **kwargs):
        self.messages.append((args, kwargs))


class _FakeCanvas:
    def setExtent(self, _extent):
        pass

    def refresh(self):
        pass


class _FakeIface:
    def __init__(self):
        self._message_bar = _FakeMessageBar()
        self._canvas = _FakeCanvas()

    def mainWindow(self):
        return None

    def messageBar(self):
        return self._message_bar

    def mapCanvas(self):
        return self._canvas


class _FakeProgressDialog:
    cancel_at_value = None

    def __init__(self, *_args, **_kwargs):
        self.value = 0
        self.closed = False

    def setWindowModality(self, _modality):
        pass

    def setWindowTitle(self, _title):
        pass

    def setMinimumDuration(self, _duration):
        pass

    def setValue(self, value):
        self.value = value

    def wasCanceled(self):
        return (
            self.cancel_at_value is not None
            and self.value >= self.cancel_at_value
        )

    def close(self):
        self.closed = True


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python runtime is not available")
class QgisPreservationAtomicOutputTransactionTests(unittest.TestCase):
    FINAL_GROUP = "ArchDistribution_매장유산유존지역"
    STAGING_GROUP = "ArchDistribution_매장유산_작업중"
    SOURCE_GROUP = "ArchDistribution_원본_데이터"

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
        from ArchDistribution import arch_distribution

        Processing.initialize()
        cls.module = arch_distribution
        cls.plugin_class = arch_distribution.ArchDistribution

    def setUp(self):
        QgsProject.instance().clear()
        _FakeProgressDialog.cancel_at_value = None
        self.project = QgsProject.instance()
        self.root = self.project.layerTreeRoot()
        self.iface = _FakeIface()
        self.plugin = self.plugin_class(self.iface)
        self.plugin.dlg = _FakeDialog()
        self.plugin.log = lambda _message: None
        self.plugin.get_study_area_centroid = (
            lambda _layer: QgsPointXY(50, 50)
        )
        self.plugin.calculate_extent_geometry = (
            lambda *_args, **_kwargs: QgsGeometry.fromWkt(
                "POLYGON((-100 -100,200 -100,200 200,-100 200,-100 -100))"
            )
        )
        self.plugin.number_heritage_v4 = lambda *_args, **_kwargs: None
        self.plugin.apply_heritage_style = lambda *_args, **_kwargs: None
        self.plugin.zoom_canvas_to_extent = lambda *_args, **_kwargs: None

        self.temp_dir = tempfile.TemporaryDirectory()
        self.plugin.plugin_dir = self.temp_dir.name
        self.progress_patch = patch.object(
            self.module,
            "QProgressDialog",
            _FakeProgressDialog,
        )
        self.critical_patch = patch.object(
            self.module.QMessageBox,
            "critical",
            lambda *_args, **_kwargs: None,
        )
        self.warning_patch = patch.object(
            self.module.QMessageBox,
            "warning",
            lambda *_args, **_kwargs: None,
        )
        self.progress_patch.start()
        self.critical_patch.start()
        self.warning_patch.start()

    def tearDown(self):
        self.warning_patch.stop()
        self.critical_patch.stop()
        self.progress_patch.stop()
        self.temp_dir.cleanup()
        QgsProject.instance().clear()

    @staticmethod
    def _polygon_layer(name, action=None):
        layer = QgsVectorLayer("Polygon?crs=EPSG:5186", name, "memory")
        if action is not None:
            layer.dataProvider().addAttributes(
                [QgsField("보존조치", QVariant.String)]
            )
            layer.updateFields()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(
            QgsGeometry.fromWkt(
                "POLYGON((0 0,100 0,100 100,0 100,0 0))"
            )
        )
        if action is not None:
            feature["보존조치"] = action
        layer.dataProvider().addFeature(feature)
        layer.updateExtents()
        return layer

    @staticmethod
    def _point_layer(name):
        layer = QgsVectorLayer("Point?crs=EPSG:5186", name, "memory")
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt("POINT(0 0)"))
        layer.dataProvider().addFeature(feature)
        return layer

    @staticmethod
    def _output_layer(name="매장유산유존지역"):
        layer = QgsVectorLayer("Polygon?crs=EPSG:5186", name, "memory")
        layer.dataProvider().addAttributes(
            [QgsField("번호", QVariant.Int)]
        )
        layer.updateFields()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(
            QgsGeometry.fromWkt(
                "POLYGON((0 0,100 0,100 100,0 100,0 0))"
            )
        )
        feature["번호"] = 1
        layer.dataProvider().addFeature(feature)
        layer.updateExtents()
        return layer

    @staticmethod
    def _layer_ids(group):
        return [node.layerId() for node in group.findLayers()]

    def _add_layer(self, layer, group):
        self.project.addMapLayer(layer, False)
        group.addLayer(layer)
        return layer

    def _make_existing_output(self):
        output_group = self.root.addGroup(self.FINAL_GROUP)
        sentinel = self._add_layer(
            self._point_layer("이전_매장유산_결과"),
            output_group,
        )
        return output_group, sentinel

    def _make_ordered_inputs(self):
        input_group = self.root.addGroup("사용자_입력")
        self._add_layer(self._point_layer("앞_레이어"), input_group)
        source = self._add_layer(
            self._polygon_layer("매장유산", "현상보존"),
            input_group,
        )
        study = self._add_layer(
            self._polygon_layer("조사구역"),
            input_group,
        )
        self._add_layer(self._point_layer("뒤_레이어"), input_group)

        source_node = self.root.findLayer(source.id())
        study_node = self.root.findLayer(study.id())
        source_node.setItemVisibilityChecked(True)
        study_node.setItemVisibilityChecked(False)
        return {
            "group": input_group,
            "source": source,
            "study": study,
            "source_index": input_group.children().index(source_node),
            "study_index": input_group.children().index(study_node),
        }

    @staticmethod
    def _settings(source, study):
        return {
            "workflow_mode": "preservation",
            "preservation_layer_id": source.id(),
            "preservation_study_area_id": study.id(),
            "preservation_action_field": "보존조치",
            "preservation_paper_width": 210,
            "preservation_paper_height": 297,
            "preservation_scale": 5000,
            "preservation_sort_order": 0,
            "preservation_stroke_width": 0.3,
            "preservation_opacity": 1.0,
            "preservation_exclude_extent_slivers": True,
        }

    def _move_inputs_and_add_staged_layer(self, inputs, src_group):
        self.plugin.move_layer_to_group(inputs["source"], src_group)
        self.plugin.move_layer_to_group(inputs["study"], src_group)
        staged = self._output_layer("실패한_임시_결과")
        self.project.addMapLayer(staged, False)
        self.root.findGroup(self.STAGING_GROUP).addLayer(staged)
        return staged

    def _assert_inputs_restored(self, inputs):
        input_group = inputs["group"]
        source_node = self.root.findLayer(inputs["source"].id())
        study_node = self.root.findLayer(inputs["study"].id())
        self.assertIs(source_node.parent(), input_group)
        self.assertIs(study_node.parent(), input_group)
        self.assertEqual(
            input_group.children().index(source_node),
            inputs["source_index"],
        )
        self.assertEqual(
            input_group.children().index(study_node),
            inputs["study_index"],
        )
        self.assertTrue(source_node.itemVisibilityChecked())
        self.assertFalse(study_node.itemVisibilityChecked())

    def test_fatal_error_preserves_sentinel_and_restores_both_inputs(self):
        _old_group, sentinel = self._make_existing_output()
        inputs = self._make_ordered_inputs()
        source_group = self.root.addGroup(self.SOURCE_GROUP)
        source_group.setItemVisibilityChecked(True)
        staged_id = None

        def fail_after_relocation(
            _layer_ids,
            _extent_geom,
            _study_layer,
            src_group,
            **_kwargs,
        ):
            nonlocal staged_id
            staged = self._move_inputs_and_add_staged_layer(
                inputs,
                src_group,
            )
            staged_id = staged.id()
            raise RuntimeError("forced preservation failure")

        self.plugin.consolidate_heritage_layers = fail_after_relocation
        self.plugin.process_preservation_area_map(
            self._settings(inputs["source"], inputs["study"])
        )

        restored = self.root.findGroup(self.FINAL_GROUP)
        self.assertIsNotNone(restored)
        self.assertIn(sentinel.id(), self._layer_ids(restored))
        self.assertIsNotNone(self.project.mapLayer(sentinel.id()))
        self.assertIsNone(self.root.findGroup(self.STAGING_GROUP))
        self.assertIsNone(self.project.mapLayer(staged_id))
        self._assert_inputs_restored(inputs)
        self.assertTrue(source_group.itemVisibilityChecked())

    def test_progress_cancel_removes_staging_and_restores_both_inputs(self):
        _old_group, sentinel = self._make_existing_output()
        inputs = self._make_ordered_inputs()
        staged_id = None

        def build_then_wait_for_progress_check(
            _layer_ids,
            _extent_geom,
            _study_layer,
            src_group,
            **_kwargs,
        ):
            nonlocal staged_id
            staged = self._move_inputs_and_add_staged_layer(
                inputs,
                src_group,
            )
            staged_id = staged.id()
            return self._output_layer()

        self.plugin.consolidate_heritage_layers = (
            build_then_wait_for_progress_check
        )
        _FakeProgressDialog.cancel_at_value = 3

        self.plugin.process_preservation_area_map(
            self._settings(inputs["source"], inputs["study"])
        )

        restored = self.root.findGroup(self.FINAL_GROUP)
        self.assertIn(sentinel.id(), self._layer_ids(restored))
        self.assertIsNone(self.root.findGroup(self.STAGING_GROUP))
        self.assertIsNone(self.project.mapLayer(staged_id))
        self._assert_inputs_restored(inputs)
        self.assertIsNone(
            self.root.findGroup(self.SOURCE_GROUP),
            "A source group created only for a canceled run must be removed.",
        )
        self.assertFalse(
            any(
                args[1] == "매장유산 유존지역 생성 완료"
                for args, _kwargs in self.iface.messageBar().messages
            )
        )

    def test_cancel_at_final_progress_value_must_not_commit(self):
        _old_group, sentinel = self._make_existing_output()
        sentinel_id = sentinel.id()
        inputs = self._make_ordered_inputs()
        self.plugin.consolidate_heritage_layers = (
            lambda *_args, **_kwargs: self._output_layer()
        )
        _FakeProgressDialog.cancel_at_value = 5

        self.plugin.process_preservation_area_map(
            self._settings(inputs["source"], inputs["study"])
        )

        restored = self.root.findGroup(self.FINAL_GROUP)
        self.assertIn(
            sentinel_id,
            self._layer_ids(restored),
            "Cancel after the final progress update must preserve old output.",
        )
        self.assertIsNone(self.root.findGroup(self.STAGING_GROUP))
        self.assertFalse(
            any(
                args[1] == "매장유산 유존지역 생성 완료"
                for args, _kwargs in self.iface.messageBar().messages
            )
        )

    def test_success_replaces_only_at_commit_and_unregisters_old_layers(self):
        _old_group, sentinel = self._make_existing_output()
        sentinel_id = sentinel.id()
        inputs = self._make_ordered_inputs()
        state_seen_during_build = {}

        def inspect_before_return(*_args, **_kwargs):
            old_output = self.root.findGroup(self.FINAL_GROUP)
            staging = self.root.findGroup(self.STAGING_GROUP)
            state_seen_during_build["old_output_has_sentinel"] = (
                old_output is not None
                and sentinel_id in self._layer_ids(old_output)
            )
            state_seen_during_build["staging_exists"] = staging is not None
            return self._output_layer()

        self.plugin.consolidate_heritage_layers = inspect_before_return

        self.plugin.process_preservation_area_map(
            self._settings(inputs["source"], inputs["study"])
        )

        self.assertEqual(
            state_seen_during_build,
            {
                "old_output_has_sentinel": True,
                "staging_exists": True,
            },
        )
        committed = self.root.findGroup(self.FINAL_GROUP)
        self.assertIsNotNone(committed)
        self.assertNotIn(sentinel_id, self._layer_ids(committed))
        self.assertIsNone(
            self.project.mapLayer(sentinel_id),
            "Committed replacement must unregister superseded layers.",
        )
        self.assertIsNone(self.root.findGroup(self.STAGING_GROUP))
        self.assertIn(
            "매장유산유존지역",
            [node.layer().name() for node in committed.findLayers()],
        )


if __name__ == "__main__":
    unittest.main()
