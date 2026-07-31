import sys
import tempfile
import unittest
from pathlib import Path


try:
    from qgis.PyQt.QtCore import QVariant
    from qgis.core import (
        QgsApplication,
        QgsFeature,
        QgsField,
        QgsGeometry,
        QgsProject,
        QgsRectangle,
        QgsVectorLayer,
    )

    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python runtime is not available")
class QgisIdentityDecisionIntegrationTests(unittest.TestCase):
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
        from ArchDistribution.heritage_identity_store import DecisionStore
        from ArchDistribution.heritage_matching import (
            DECISION_KEEP,
            ROLE_DISTRIBUTION,
            ROLE_LOCAL_DESIGNATED,
            ROLE_OTHER,
        )

        Processing.initialize()
        cls.plugin_class = ArchDistribution
        cls.decision_store_class = DecisionStore
        cls.keep_decision = DECISION_KEEP
        cls.distribution_role = ROLE_DISTRIBUTION
        cls.designated_role = ROLE_LOCAL_DESIGNATED
        cls.other_role = ROLE_OTHER

    def setUp(self):
        QgsProject.instance().clear()

    def make_plugin(self):
        plugin = self.plugin_class(None)
        plugin.log = lambda _message: None
        return plugin

    @staticmethod
    def make_study():
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "study_area",
            "memory",
        )
        feature = QgsFeature(layer.fields())
        feature.setGeometry(
            QgsGeometry.fromRect(QgsRectangle(40, 40, 50, 50))
        )
        layer.dataProvider().addFeature(feature)
        layer.updateExtents()
        return layer

    @staticmethod
    def make_raw_source(rows, *, prepend_outside_dummy=False):
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "stable_source",
            "memory",
        )
        layer.dataProvider().addAttributes([
            QgsField("NAME", QVariant.String),
            QgsField("PROJECT", QVariant.String),
            QgsField("ADDR", QVariant.String),
            QgsField("HERITAGE_CODE", QVariant.String),
            QgsField("DETAIL", QVariant.String),
        ])
        layer.updateFields()

        features = []
        if prepend_outside_dummy:
            dummy = QgsFeature(layer.fields())
            dummy.setGeometry(QgsGeometry.fromWkt(
                "POLYGON((10000 10000,10001 10000,10001 10001,"
                "10000 10001,10000 10000))"
            ))
            dummy["NAME"] = "outside-dummy"
            dummy["HERITAGE_CODE"] = "dummy"
            features.append(dummy)

        for row in rows:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromWkt(row["wkt"]))
            feature["NAME"] = row["name"]
            feature["PROJECT"] = row.get("project", "")
            feature["ADDR"] = row.get("address", "")
            feature["HERITAGE_CODE"] = row.get("code", "")
            feature["DETAIL"] = row.get("detail", "")
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        return layer

    def consolidate(self, source):
        project = QgsProject.instance()
        study = self.make_study()
        project.addMapLayers([source, study])
        source_group = project.layerTreeRoot().addGroup(
            f"source_{source.id()}"
        )
        result = self.make_plugin().consolidate_heritage_layers(
            [source.id()],
            QgsGeometry.fromRect(QgsRectangle(-5, -5, 35, 35)),
            study,
            source_group,
            source_roles={source.id(): self.other_role},
            matching_decision_provider=lambda candidates: candidates,
        )
        self.assertIsNotNone(result)
        return result["main"]

    @staticmethod
    def target_feature_id(layer, target_name):
        for feature in layer.getFeatures():
            if feature["NAME"] == target_name:
                return feature.id()
        raise AssertionError(f"Target feature not found: {target_name}")

    def test_reloaded_source_keeps_uid_and_fingerprint_across_layer_and_fid(self):
        target = {
            "name": "Stable Site",
            "project": "Stable Project",
            "address": "Gongju 1",
            "code": "SITE-001",
            "detail": "unchanged source attribute",
            "wkt": "POLYGON((0 0,10 0,10 10,0 10,0 0))",
        }

        first_source = self.make_raw_source([target])
        first_layer_id = first_source.id()
        first_feature_id = self.target_feature_id(
            first_source,
            target["name"],
        )
        first_output = self.consolidate(first_source)
        first_result = next(first_output.getFeatures())
        first_identity = (
            first_result["SRC_UID"],
            first_result["SRC_FP"],
        )

        QgsProject.instance().clear()
        second_source = self.make_raw_source(
            [target],
            prepend_outside_dummy=True,
        )
        second_layer_id = second_source.id()
        second_feature_id = self.target_feature_id(
            second_source,
            target["name"],
        )
        second_output = self.consolidate(second_source)
        second_result = next(second_output.getFeatures())
        second_identity = (
            second_result["SRC_UID"],
            second_result["SRC_FP"],
        )

        self.assertNotEqual(first_layer_id, second_layer_id)
        self.assertNotEqual(first_feature_id, second_feature_id)
        self.assertEqual(first_identity, second_identity)

    def test_same_native_code_with_different_polygons_has_distinct_uids(self):
        source = self.make_raw_source([
            {
                "name": "Shared Code Part A",
                "code": "SHARED-100",
                "wkt": "POLYGON((0 0,5 0,5 5,0 5,0 0))",
            },
            {
                "name": "Shared Code Part B",
                "code": "SHARED-100",
                "wkt": "POLYGON((20 20,25 20,25 25,20 25,20 20))",
            },
        ])

        output = self.consolidate(source)
        output_features = list(output.getFeatures())

        self.assertEqual(len(output_features), 2)
        self.assertEqual(
            {feature["HERITAGE_CODE"] for feature in output_features},
            {"SHARED-100"},
        )
        self.assertEqual(
            len({feature["SRC_UID"] for feature in output_features}),
            2,
        )

    def make_matching_layer(
        self,
        *,
        designated_fingerprint="fp-designated-v1",
        distribution_fingerprint="fp-distribution-v1",
    ):
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "decision_reuse_input",
            "memory",
        )
        layer.dataProvider().addAttributes([
            QgsField("SRC_NAME", QVariant.String),
            QgsField("HERITAGE_CODE", QVariant.String),
            QgsField("SRC_UID", QVariant.String),
            QgsField("SRC_FP", QVariant.String),
            QgsField("SOURCE_ROLE", QVariant.String),
            QgsField("ENTITY_KEY", QVariant.String),
            QgsField("RELATION_KEY", QVariant.String),
            QgsField("MATCH_STATUS", QVariant.String),
            QgsField("MATCH_SCORE", QVariant.Double),
            QgsField("MATCH_RULE", QVariant.String),
            QgsField("REP_SOURCE", QVariant.String),
            QgsField("LINKED_IDS", QVariant.String),
            QgsField("IS_REP", QVariant.Int),
            QgsField("NUMBER_KEY", QVariant.String),
            QgsField("GROUP_KEY", QVariant.String),
            QgsField("SRC_COUNT", QVariant.Int),
            QgsField("SRC_JSON", QVariant.String),
        ])
        layer.updateFields()

        rows = [
            {
                "uid": "designated:stable-1",
                "fingerprint": designated_fingerprint,
                "role": self.designated_role,
            },
            {
                "uid": "distribution:stable-1",
                "fingerprint": distribution_fingerprint,
                "role": self.distribution_role,
            },
        ]
        features = []
        for row in rows:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromWkt(
                "POLYGON((0 0,10 0,10 10,0 10,0 0))"
            ))
            feature["SRC_NAME"] = "Same Heritage"
            feature["HERITAGE_CODE"] = ""
            feature["SRC_UID"] = row["uid"]
            feature["SRC_FP"] = row["fingerprint"]
            feature["SOURCE_ROLE"] = row["role"]
            feature["ENTITY_KEY"] = row["uid"]
            feature["MATCH_STATUS"] = "UNIQUE"
            feature["REP_SOURCE"] = row["role"]
            feature["IS_REP"] = 1
            feature["NUMBER_KEY"] = row["uid"]
            feature["GROUP_KEY"] = row["uid"]
            feature["SRC_COUNT"] = 1
            feature["SRC_JSON"] = "[]"
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        return layer

    def make_persisted_store(self, directory, *, policy_version):
        path = Path(directory) / "review_decisions.json"
        store = self.decision_store_class()
        store.record(
            "designated:stable-1",
            "fp-designated-v1",
            "distribution:stable-1",
            "fp-distribution-v1",
            decision=self.keep_decision,
            policy_version=policy_version,
        )
        store.save(path)
        return self.decision_store_class.load(path)

    def test_saved_decision_reuse_and_stale_fingerprint_or_policy_review(self):
        calls = []

        def provider(candidates):
            calls.append(len(candidates))
            decisions = []
            for candidate in candidates:
                item = dict(candidate)
                item["decision"] = self.keep_decision
                item["decision_source"] = "user"
                decisions.append(item)
            return decisions

        with tempfile.TemporaryDirectory() as temporary_directory:
            current_store = self.make_persisted_store(
                temporary_directory,
                policy_version="policy-v1",
            )
            current_result = (
                self.make_plugin().apply_source_aware_matching(
                    self.make_matching_layer(),
                    decision_provider=provider,
                    decision_store=current_store,
                    reuse_saved_decisions=True,
                    policy_version="policy-v1",
                )
            )
            self.assertEqual(calls, [])
            self.assertEqual(current_result["audit"].featureCount(), 1)

            fingerprint_store = self.make_persisted_store(
                temporary_directory,
                policy_version="policy-v1",
            )
            self.make_plugin().apply_source_aware_matching(
                self.make_matching_layer(
                    distribution_fingerprint="fp-distribution-v2",
                ),
                decision_provider=provider,
                decision_store=fingerprint_store,
                reuse_saved_decisions=True,
                policy_version="policy-v1",
            )
            self.assertEqual(calls, [1])

            policy_store = self.make_persisted_store(
                temporary_directory,
                policy_version="policy-v1",
            )
            self.make_plugin().apply_source_aware_matching(
                self.make_matching_layer(),
                decision_provider=provider,
                decision_store=policy_store,
                reuse_saved_decisions=True,
                policy_version="policy-v2",
            )
            self.assertEqual(calls, [1, 1])


if __name__ == "__main__":
    unittest.main()
