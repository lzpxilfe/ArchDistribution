import sys
import unittest
from pathlib import Path
from unittest.mock import patch


try:
    from qgis.core import (
        QgsApplication,
        QgsFeature,
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
    cancelled = False

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
        return self.cancelled

    def close(self):
        self.closed = True


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python runtime is not available")
class QgisAtomicOutputTransactionTests(unittest.TestCase):
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
        cls.cancelled_error = arch_distribution.ProcessingCancelled

    def setUp(self):
        QgsProject.instance().clear()
        _FakeProgressDialog.cancelled = False
        self.project = QgsProject.instance()
        self.root = self.project.layerTreeRoot()
        self.iface = _FakeIface()
        self.plugin = self.plugin_class(self.iface)
        self.plugin.dlg = _FakeDialog()
        self.plugin.log = lambda _message: None
        self.plugin.get_study_area_centroid = (
            lambda _layer: QgsPointXY(50, 50)
        )
        self.plugin.create_extent_polygon = (
            lambda *_args, **_kwargs: QgsGeometry.fromWkt(
                "POLYGON((-100 -100,200 -100,200 200,-100 200,-100 -100))"
            )
        )
        self.plugin.zoom_canvas_to_extent = lambda *_args, **_kwargs: None
        self.plugin.apply_study_style = lambda *_args, **_kwargs: None

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
        self.progress_patch.start()
        self.critical_patch.start()

    def tearDown(self):
        self.critical_patch.stop()
        self.progress_patch.stop()
        QgsProject.instance().clear()

    @staticmethod
    def _polygon_layer(name):
        layer = QgsVectorLayer("Polygon?crs=EPSG:5186", name, "memory")
        feature = QgsFeature(layer.fields())
        feature.setGeometry(
            QgsGeometry.fromWkt(
                "POLYGON((0 0,100 0,100 100,0 100,0 0))"
            )
        )
        layer.dataProvider().addFeature(feature)
        return layer

    @staticmethod
    def _point_layer(name):
        layer = QgsVectorLayer("Point?crs=EPSG:5186", name, "memory")
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt("POINT(0 0)"))
        layer.dataProvider().addFeature(feature)
        return layer

    @staticmethod
    def _layer_ids(group):
        return [node.layerId() for node in group.findLayers()]

    def _add_layer(self, layer, group):
        self.project.addMapLayer(layer, False)
        group.addLayer(layer)
        return layer

    def _make_existing_output(self):
        output_group = self.root.addGroup("ArchDistribution_결과물")
        sentinel = self._add_layer(
            self._point_layer("이전_결과_표식"),
            output_group,
        )
        return output_group, sentinel

    def _make_ordered_inputs(self):
        input_group = self.root.addGroup("사용자_입력")
        before = self._add_layer(self._point_layer("앞_레이어"), input_group)
        study = self._add_layer(self._polygon_layer("조사구역"), input_group)
        after = self._add_layer(self._point_layer("뒤_레이어"), input_group)
        del before, after
        study_node = self.root.findLayer(study.id())
        study_node.setItemVisibilityChecked(True)
        return input_group, study, input_group.children().index(study_node)

    @staticmethod
    def _settings(study, heritage_ids=None):
        return {
            "workflow_mode": "distribution",
            "study_area_id": study.id(),
            "topo_layer_ids": [],
            "heritage_layer_ids": list(heritage_ids or []),
            "zone_layer_id": None,
            "study_style": {},
            "topo_style": {},
            "heritage_style": {},
            "buffer_style": {},
            "buffers": [],
            "paper_width": 210,
            "paper_height": 297,
            "scale": 25000,
            "sort_order": 0,
            "source_roles": {},
        }

    def test_fatal_error_preserves_previous_output_and_cleans_staging(self):
        _old_group, sentinel = self._make_existing_output()
        _input_group, study, _study_index = self._make_ordered_inputs()
        heritage = self._add_layer(
            self._polygon_layer("주변유적"),
            self.root.findGroup("사용자_입력"),
        )
        self.plugin.consolidate_heritage_layers = (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("forced failure after source relocation")
            )
        )

        self.plugin.process_distribution_map(
            self._settings(study, [heritage.id()])
        )

        restored = self.root.findGroup("ArchDistribution_결과물")
        self.assertIsNotNone(restored)
        self.assertIn(sentinel.id(), self._layer_ids(restored))
        self.assertIsNone(self.root.findGroup("ArchDistribution_작업중"))
        self.assertIsNone(
            self.root.findGroup("ArchDistribution_원본_데이터"),
            "A source group created only for a failed run must be removed.",
        )
        self.assertFalse(
            any(
                layer.name() == "00_조사구역"
                for layer in self.project.mapLayers().values()
            ),
            "A failed staging run must not leak temporary result layers.",
        )

    def test_cancel_restores_source_parent_order_and_visibility(self):
        _old_group, sentinel = self._make_existing_output()
        input_group, study, study_index = self._make_ordered_inputs()
        source_group = self.root.addGroup("ArchDistribution_원본_데이터")
        source_group.setItemVisibilityChecked(True)
        heritage = self._add_layer(
            self._polygon_layer("주변유적"),
            input_group,
        )
        self.plugin.consolidate_heritage_layers = (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                self.cancelled_error()
            )
        )

        self.plugin.process_distribution_map(
            self._settings(study, [heritage.id()])
        )

        restored_output = self.root.findGroup("ArchDistribution_결과물")
        self.assertIn(sentinel.id(), self._layer_ids(restored_output))
        self.assertIsNone(self.root.findGroup("ArchDistribution_작업중"))

        restored_node = self.root.findLayer(study.id())
        self.assertIs(restored_node.parent(), input_group)
        self.assertEqual(
            input_group.children().index(restored_node),
            study_index,
        )
        self.assertTrue(restored_node.itemVisibilityChecked())
        self.assertTrue(
            source_group.itemVisibilityChecked(),
            "Rollback must restore the visibility of a pre-existing group.",
        )

    def test_progress_dialog_cancel_rolls_back_instead_of_finishing(self):
        _old_group, sentinel = self._make_existing_output()
        _input_group, study, _study_index = self._make_ordered_inputs()
        settings = self._settings(study)
        settings["buffers"] = [100]
        settings["buffer_style"] = {
            "color": "#ff0000",
            "style": 0,
            "width": 0.3,
        }
        _FakeProgressDialog.cancelled = True

        self.plugin.process_distribution_map(settings)

        restored_output = self.root.findGroup("ArchDistribution_결과물")
        self.assertIn(sentinel.id(), self._layer_ids(restored_output))
        self.assertIsNone(self.root.findGroup("ArchDistribution_작업중"))
        self.assertFalse(
            any(
                message[0][1] == "작업 완료"
                for message in self.iface.messageBar().messages
            )
        )

    def test_success_keeps_old_output_until_atomic_commit(self):
        _old_group, sentinel = self._make_existing_output()
        sentinel_id = sentinel.id()
        _input_group, study, _study_index = self._make_ordered_inputs()
        state_seen_during_build = {}

        def inspect_tree_during_build(*_args, **_kwargs):
            old_output = self.root.findGroup("ArchDistribution_결과물")
            staging = self.root.findGroup("ArchDistribution_작업중")
            state_seen_during_build["old_output_has_sentinel"] = (
                old_output is not None
                and sentinel.id() in self._layer_ids(old_output)
            )
            state_seen_during_build["staging_exists"] = staging is not None

        self.plugin.apply_study_style = inspect_tree_during_build

        self.plugin.process_distribution_map(self._settings(study))

        self.assertEqual(
            state_seen_during_build,
            {
                "old_output_has_sentinel": True,
                "staging_exists": True,
            },
        )
        committed = self.root.findGroup("ArchDistribution_결과물")
        self.assertIsNotNone(committed)
        self.assertNotIn(sentinel_id, self._layer_ids(committed))
        self.assertIsNone(
            self.project.mapLayer(sentinel_id),
            "Committed replacement must unregister superseded result layers.",
        )
        self.assertIsNone(self.root.findGroup("ArchDistribution_작업중"))
        self.assertIn(
            "00_조사구역",
            [node.layer().name() for node in committed.findLayers()],
        )


if __name__ == "__main__":
    unittest.main()
