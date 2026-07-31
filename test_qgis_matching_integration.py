import json
import sys
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
class QgisMatchingIntegrationTests(unittest.TestCase):
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
        from ArchDistribution.heritage_matching import (
            DECISION_KEEP,
            ROLE_DISTRIBUTION,
            ROLE_EXCAVATION,
            ROLE_LOCAL_DESIGNATED,
            ROLE_PROTECTION_ZONE,
            ROLE_SURFACE,
        )

        Processing.initialize()
        cls.plugin_class = ArchDistribution
        cls.keep_decision = DECISION_KEEP
        cls.roles = {
            "distribution": ROLE_DISTRIBUTION,
            "excavation": ROLE_EXCAVATION,
            "designated": ROLE_LOCAL_DESIGNATED,
            "protection": ROLE_PROTECTION_ZONE,
            "surface": ROLE_SURFACE,
        }

    def make_layer(self, rows, crs="EPSG:5186"):
        layer = QgsVectorLayer(
            f"Polygon?crs={crs}",
            "matching_input",
            "memory",
        )
        fields = [
            QgsField("유적명", QVariant.String),
            QgsField("주소", QVariant.String),
            QgsField("사업명", QVariant.String),
            QgsField("SRC_NAME", QVariant.String),
            QgsField("HERITAGE_CODE", QVariant.String),
            QgsField("SRC_UID", QVariant.String),
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
        ]
        layer.dataProvider().addAttributes(fields)
        layer.updateFields()

        features = []
        for row in rows:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromWkt(row["wkt"]))
            feature["유적명"] = row["name"]
            feature["SRC_NAME"] = row["name"]
            feature["HERITAGE_CODE"] = row.get("code", "")
            feature["SRC_UID"] = row["uid"]
            feature["SOURCE_ROLE"] = row["role"]
            feature["ENTITY_KEY"] = f"{row['role']}:{row['uid']}"
            feature["MATCH_STATUS"] = "UNIQUE"
            feature["REP_SOURCE"] = row["role"]
            feature["IS_REP"] = (
                0 if row["role"] == self.roles["protection"] else 1
            )
            feature["NUMBER_KEY"] = f"{row['role']}:{row['uid']}"
            feature["GROUP_KEY"] = f"{row['role']}:{row['uid']}"
            feature["SRC_COUNT"] = 1
            feature["SRC_JSON"] = json.dumps([{"uid": row["uid"]}])
            feature["사업명"] = row.get("project", "")
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        return layer

    @staticmethod
    def recommended(candidates):
        decisions = []
        for candidate in candidates:
            item = dict(candidate)
            item["decision"] = candidate["recommended_decision"]
            item["decision_source"] = (
                "auto" if candidate["auto_apply"] else "user"
            )
            decisions.append(item)
        return decisions

    def test_designated_suppresses_distribution_but_preserves_metadata(self):
        layer = self.make_layer([
            {
                "uid": "d1",
                "role": self.roles["designated"],
                "name": "공주 A유적",
                "wkt": "POLYGON((0 0,10 0,10 10,0 10,0 0))",
            },
            {
                "uid": "m1",
                "role": self.roles["distribution"],
                "name": "공주 A유적",
                "wkt": "POLYGON((0 0,10 0,10 10,0 10,0 0))",
            },
        ])
        result = self.plugin_class(None).apply_source_aware_matching(
            layer,
            decision_provider=self.recommended,
        )
        self.assertEqual(result["main"].featureCount(), 1)
        self.assertEqual(result["suppressed"].featureCount(), 1)
        self.assertEqual(result["audit"].featureCount(), 1)
        main = next(result["main"].getFeatures())
        self.assertEqual(len(json.loads(main["SRC_JSON"])), 2)

    def test_geographic_crs_uses_metre_distance_for_nearby_exact_names(self):
        layer = self.make_layer(
            [
                {
                    "uid": "designated-near",
                    "role": self.roles["designated"],
                    "name": "공주 근접 유적",
                    "wkt": (
                        "POLYGON((127 36,127.00002 36,"
                        "127.00002 36.00002,127 36.00002,127 36))"
                    ),
                },
                {
                    "uid": "distribution-near",
                    "role": self.roles["distribution"],
                    "name": "공주 근접 유적",
                    "wkt": (
                        "POLYGON((127.00055 36,127.00057 36,"
                        "127.00057 36.00002,127.00055 36.00002,"
                        "127.00055 36))"
                    ),
                },
            ],
            crs="EPSG:4326",
        )
        plugin = self.plugin_class(None)
        captured = []

        def decisions(candidates):
            captured.extend(candidates)
            return self.recommended(candidates)

        result = plugin.apply_source_aware_matching(
            layer,
            decision_provider=decisions,
        )

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["rule"], "exact_name_within_50m")
        self.assertLessEqual(captured[0]["distance"], 50)
        self.assertEqual(result["main"].featureCount(), 1)

    def test_designated_and_excavation_keep_separate_number_entities(self):
        layer = self.make_layer([
            {
                "uid": "d1",
                "role": self.roles["designated"],
                "name": "경희궁지",
                "wkt": "POLYGON((0 0,20 0,20 20,0 20,0 0))",
            },
            {
                "uid": "e1",
                "role": self.roles["excavation"],
                "name": "경희궁지",
                "wkt": "POLYGON((2 2,8 2,8 8,2 8,2 2))",
            },
        ])
        result = self.plugin_class(None).apply_source_aware_matching(
            layer,
            decision_provider=self.recommended,
        )
        self.assertEqual(result["main"].featureCount(), 2)
        self.assertEqual(result["suppressed"].featureCount(), 0)
        keys = {
            feature["NUMBER_KEY"]
            for feature in result["main"].getFeatures()
        }
        self.assertEqual(len(keys), 2)

    def test_three_way_overlap_keeps_legal_and_excavation_numbers(self):
        layer = self.make_layer([
            {
                "uid": "d1",
                "role": self.roles["designated"],
                "name": "공주 삼자 중복 유적",
                "wkt": "POLYGON((0 0,20 0,20 20,0 20,0 0))",
            },
            {
                "uid": "e1",
                "role": self.roles["excavation"],
                "name": "공주 삼자 중복 유적",
                "wkt": "POLYGON((0 0,20 0,20 20,0 20,0 0))",
            },
            {
                "uid": "m1",
                "role": self.roles["distribution"],
                "name": "공주 삼자 중복 유적",
                "wkt": "POLYGON((0 0,20 0,20 20,0 20,0 0))",
            },
        ])
        result = self.plugin_class(None).apply_source_aware_matching(
            layer,
            decision_provider=self.recommended,
        )

        self.assertEqual(result["main"].featureCount(), 2)
        self.assertEqual(result["suppressed"].featureCount(), 1)
        main_by_role = {
            feature["SOURCE_ROLE"]: feature
            for feature in result["main"].getFeatures()
        }
        self.assertEqual(
            main_by_role[self.roles["designated"]]["MATCH_STATUS"],
            "AUTO_MERGED",
        )
        self.assertEqual(
            main_by_role[self.roles["excavation"]]["MATCH_STATUS"],
            "LINKED",
        )
        suppressed = next(result["suppressed"].getFeatures())
        self.assertEqual(
            suppressed["REP_SOURCE"],
            self.roles["designated"],
        )
        self.assertEqual(suppressed["MATCH_STATUS"], "AUTO_MERGED")

    def test_surface_default_stays_separate_and_protection_is_unnumbered(self):
        layer = self.make_layer([
            {
                "uid": "s1",
                "role": self.roles["surface"],
                "name": "공주 A유적",
                "wkt": "POLYGON((0 0,10 0,10 10,0 10,0 0))",
            },
            {
                "uid": "e1",
                "role": self.roles["excavation"],
                "name": "공주 A유적",
                "wkt": "POLYGON((0 0,10 0,10 10,0 10,0 0))",
            },
            {
                "uid": "p1",
                "role": self.roles["protection"],
                "name": "공주 A유적 보호구역",
                "wkt": "POLYGON((-5 -5,15 -5,15 15,-5 15,-5 -5))",
            },
        ])
        result = self.plugin_class(None).apply_source_aware_matching(
            layer,
            decision_provider=self.recommended,
        )
        self.assertEqual(result["main"].featureCount(), 2)
        self.assertEqual(result["protection"].featureCount(), 1)
        protection = next(result["protection"].getFeatures())
        self.assertFalse(protection["NUMBER_KEY"])

    def test_protection_zone_links_to_designated_asset_by_source_code(self):
        layer = self.make_layer([
            {
                "uid": "d1",
                "role": self.roles["designated"],
                "name": "공주 A유적",
                "code": "ASSET-1",
                "wkt": "POLYGON((0 0,10 0,10 10,0 10,0 0))",
            },
            {
                "uid": "p1",
                "role": self.roles["protection"],
                "name": "공주 A유적 보호구역",
                "code": "ASSET-1",
                "wkt": "POLYGON((-5 -5,15 -5,15 15,-5 15,-5 -5))",
            },
        ])
        result = self.plugin_class(None).apply_source_aware_matching(
            layer,
            decision_provider=self.recommended,
        )
        designated = next(result["main"].getFeatures())
        protection = next(result["protection"].getFeatures())
        self.assertIn("p1", designated["LINKED_IDS"])
        self.assertIn("d1", protection["LINKED_IDS"])
        self.assertTrue(protection["RELATION_KEY"])

    def test_full_consolidation_uses_roles_before_dissolve(self):
        project = QgsProject.instance()
        project.clear()

        designated = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "시도지정유산",
            "memory",
        )
        designated.dataProvider().addAttributes([
            QgsField("국가유산명", QVariant.String),
            QgsField("유산코드", QVariant.String),
        ])
        designated.updateFields()
        d_feature = QgsFeature(designated.fields())
        d_feature.setGeometry(QgsGeometry.fromWkt(
            "POLYGON((0 0,10 0,10 10,0 10,0 0))"
        ))
        d_feature["국가유산명"] = "공주 A유적"
        d_feature["유산코드"] = "D-1"
        designated.dataProvider().addFeature(d_feature)

        distribution = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "문화유적분포지도",
            "memory",
        )
        distribution.dataProvider().addAttributes([
            QgsField("명칭", QVariant.String),
            QgsField("유산코드", QVariant.String),
        ])
        distribution.updateFields()
        m_feature = QgsFeature(distribution.fields())
        m_feature.setGeometry(QgsGeometry.fromWkt(
            "POLYGON((0 0,10 0,10 10,0 10,0 0))"
        ))
        m_feature["명칭"] = "공주 A유적"
        m_feature["유산코드"] = "M-1"
        distribution.dataProvider().addFeature(m_feature)

        study = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "조사구역",
            "memory",
        )
        study_feature = QgsFeature(study.fields())
        study_feature.setGeometry(QgsGeometry.fromWkt(
            "POLYGON((40 40,41 40,41 41,40 41,40 40))"
        ))
        study.dataProvider().addFeature(study_feature)

        project.addMapLayers([designated, distribution, study])
        source_group = project.layerTreeRoot().addGroup("원본")
        plugin = self.plugin_class.__new__(self.plugin_class)
        plugin.log = lambda _message: None
        result = plugin.consolidate_heritage_layers(
            [designated.id(), distribution.id()],
            QgsGeometry.fromRect(QgsRectangle(-5, -5, 50, 50)),
            study,
            source_group,
            source_roles={
                designated.id(): self.roles["designated"],
                distribution.id(): self.roles["distribution"],
            },
            matching_decision_provider=self.recommended,
        )

        self.assertEqual(result["main"].featureCount(), 1)
        self.assertEqual(result["suppressed"].featureCount(), 1)
        representative = next(result["main"].getFeatures())
        self.assertEqual(
            representative["SOURCE_ROLE"],
            self.roles["designated"],
        )
        self.assertEqual(
            len(json.loads(representative["SRC_JSON"])),
            2,
        )

    def test_invalid_candidate_geometry_is_repaired_before_matching(self):
        layer = self.make_layer([
            {
                "uid": "d1",
                "role": self.roles["designated"],
                "name": "공주 교차유적",
                "wkt": "POLYGON((0 0,10 10,10 0,0 10,0 0))",
            },
            {
                "uid": "m1",
                "role": self.roles["distribution"],
                "name": "공주 교차유적",
                "wkt": "POLYGON((0 0,10 0,10 10,0 10,0 0))",
            },
        ])
        result = self.plugin_class(None).apply_source_aware_matching(
            layer,
            decision_provider=self.recommended,
        )
        self.assertEqual(result["main"].featureCount(), 1)
        self.assertEqual(result["suppressed"].featureCount(), 1)
        self.assertTrue(
            all(
                feature.geometry().isGeosValid()
                for feature in result["main"].getFeatures()
            )
        )


if __name__ == "__main__":
    unittest.main()
