import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


try:
    from qgis.core import (
        QgsApplication,
        QgsFeature,
        QgsGeometry,
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
        return False

    def close(self):
        self.closed = True


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python runtime is not available")
class QgisDecisionCommitPersistenceTests(unittest.TestCase):
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
        from ArchDistribution.heritage_identity_store import DecisionStore
        from ArchDistribution.heritage_matching import DECISION_KEEP

        Processing.initialize()
        cls.module = arch_distribution
        cls.plugin_class = arch_distribution.ArchDistribution
        cls.decision_store_class = DecisionStore
        cls.keep_decision = DECISION_KEEP

    def setUp(self):
        QgsProject.instance().clear()
        self.project = QgsProject.instance()
        self.root = self.project.layerTreeRoot()
        self.iface = _FakeIface()
        self.plugin = self.plugin_class(self.iface)
        self.plugin.dlg = _FakeDialog()
        self.logs = []
        self.plugin.log = self.logs.append

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
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            name,
            "memory",
        )
        feature = QgsFeature(layer.fields())
        feature.setGeometry(
            QgsGeometry.fromWkt(
                "POLYGON((0 0,100 0,100 100,0 100,0 0))"
            )
        )
        layer.dataProvider().addFeature(feature)
        layer.updateExtents()
        return layer

    @staticmethod
    def _point_layer(name):
        layer = QgsVectorLayer(
            "Point?crs=EPSG:5186",
            name,
            "memory",
        )
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt("POINT(0 0)"))
        layer.dataProvider().addFeature(feature)
        layer.updateExtents()
        return layer

    def _add_result_layer(self, group, name="committed_result"):
        layer = self._point_layer(name)
        self.project.addMapLayer(layer, False)
        group.addLayer(layer)
        return layer

    def _new_store(
        self,
        *,
        left_uid="designated:one",
        right_uid="distribution:one",
        left_fingerprint="designated-fp-v1",
        right_fingerprint="distribution-fp-v1",
        policy_version="source-aware-v1:balanced",
    ):
        store = self.decision_store_class()
        store.record(
            left_uid,
            left_fingerprint,
            right_uid,
            right_fingerprint,
            decision=self.keep_decision,
            policy_version=policy_version,
        )
        return store

    @staticmethod
    def _distribution_settings(study):
        return {
            "workflow_mode": "distribution",
            "study_area_id": study.id(),
            "topo_layer_ids": [],
            "heritage_layer_ids": [],
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

    def test_failed_processing_rolls_back_without_writing_pending_store(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            decision_path = temporary_path / "review_decisions.json"
            original_bytes = b'{"existing":"must remain byte-identical"}\n'
            decision_path.write_bytes(original_bytes)
            self.plugin.plugin_dir = str(temporary_path)

            study = self._polygon_layer("study")
            self.project.addMapLayer(study)

            def fail_after_pending_decision(*_args, **_kwargs):
                self.plugin._pending_decision_store = self._new_store()
                self.plugin._pending_decision_store_path = str(
                    decision_path
                )
                self.plugin._pending_decision_store_dirty = True
                raise RuntimeError("forced failure before output commit")

            self.plugin.apply_study_style = fail_after_pending_decision
            with patch.object(
                self.plugin,
                "_save_pending_decision_store",
                wraps=self.plugin._save_pending_decision_store,
            ) as save_spy:
                self.plugin.process_distribution_map(
                    self._distribution_settings(study)
                )

            save_spy.assert_not_called()
            self.assertEqual(decision_path.read_bytes(), original_bytes)
            self.assertIsNone(
                getattr(self.plugin, "_active_output_transaction", None)
            )
            self.assertIsNone(self.plugin._pending_decision_store)
            self.assertIsNone(self.plugin._pending_decision_store_path)
            self.assertFalse(self.plugin._pending_decision_store_dirty)

    def test_committed_output_then_atomic_save_is_loadable_and_reusable(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            decision_path = (
                Path(temporary_directory) / "review_decisions.json"
            )
            staging = self.plugin._begin_output_transaction(
                "Committed Output",
                "Staging Output",
            )
            result_layer = self._add_result_layer(staging)

            store = self._new_store()
            self.plugin._pending_decision_store = store
            self.plugin._pending_decision_store_path = str(decision_path)
            self.plugin._pending_decision_store_dirty = True

            self.plugin._commit_output_transaction()
            self.assertFalse(
                decision_path.exists(),
                "Committing map layers must not itself persist decisions.",
            )
            committed = self.root.findGroup("Committed Output")
            self.assertIsNotNone(committed)
            self.assertIn(
                result_layer.id(),
                [node.layerId() for node in committed.findLayers()],
            )

            self.plugin._save_pending_decision_store()

            self.assertTrue(decision_path.is_file())
            self.assertEqual(
                list(
                    decision_path.parent.glob(
                        f".{decision_path.name}.*.tmp"
                    )
                ),
                [],
            )
            loaded = self.decision_store_class.load(decision_path)
            lookup = loaded.lookup(
                "distribution:one",
                "distribution-fp-v1",
                "designated:one",
                "designated-fp-v1",
                policy_version="source-aware-v1:balanced",
            )
            self.assertTrue(lookup.reusable)
            self.assertEqual(lookup.decision, self.keep_decision)
            self.assertIsNotNone(self.root.findGroup("Committed Output"))
            self.assertIsNotNone(self.project.mapLayer(result_layer.id()))

    def test_save_failure_does_not_remove_already_committed_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            decision_path = (
                Path(temporary_directory) / "review_decisions.json"
            )
            prior_store = self._new_store(
                left_uid="designated:prior",
                right_uid="distribution:prior",
                left_fingerprint="prior-designated-fp",
                right_fingerprint="prior-distribution-fp",
            )
            prior_store.save(decision_path)
            original_bytes = decision_path.read_bytes()

            staging = self.plugin._begin_output_transaction(
                "Committed Output",
                "Staging Output",
            )
            result_layer = self._add_result_layer(staging)
            self.plugin._pending_decision_store = self._new_store(
                left_uid="designated:new",
                right_uid="distribution:new",
            )
            self.plugin._pending_decision_store_path = str(decision_path)
            self.plugin._pending_decision_store_dirty = True
            self.plugin._commit_output_transaction()

            module_name = (
                "ArchDistribution.heritage_identity_store.os.replace"
            )
            with patch(
                module_name,
                side_effect=OSError("forced decision-cache write failure"),
            ):
                self.plugin._save_pending_decision_store()

            committed = self.root.findGroup("Committed Output")
            self.assertIsNotNone(committed)
            self.assertIn(
                result_layer.id(),
                [node.layerId() for node in committed.findLayers()],
            )
            self.assertIsNotNone(self.project.mapLayer(result_layer.id()))
            self.assertEqual(decision_path.read_bytes(), original_bytes)
            self.assertEqual(
                list(
                    decision_path.parent.glob(
                        f".{decision_path.name}.*.tmp"
                    )
                ),
                [],
            )
            loaded = self.decision_store_class.load(decision_path)
            prior_lookup = loaded.lookup(
                "distribution:prior",
                "prior-distribution-fp",
                "designated:prior",
                "prior-designated-fp",
                policy_version="source-aware-v1:balanced",
            )
            self.assertTrue(prior_lookup.reusable)
            self.assertIn(
                "forced decision-cache write failure",
                "\n".join(self.logs),
            )
            self.assertIsNone(self.plugin._pending_decision_store)
            self.assertIsNone(self.plugin._pending_decision_store_path)
            self.assertFalse(self.plugin._pending_decision_store_dirty)


if __name__ == "__main__":
    unittest.main()
