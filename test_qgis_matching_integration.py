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

    def make_family_source(
        self,
        geometry_uri,
        layer_name,
        site_name,
        wkt=None,
    ):
        layer = QgsVectorLayer(
            f"{geometry_uri}?crs=EPSG:5186",
            layer_name,
            "memory",
        )
        layer.dataProvider().addAttributes([
            QgsField("유적명", QVariant.String),
        ])
        layer.updateFields()
        feature = QgsFeature(layer.fields())
        if wkt is not None:
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
        elif geometry_uri == "Point":
            feature.setGeometry(QgsGeometry.fromWkt("POINT(200100 450100)"))
        elif geometry_uri == "LineString":
            feature.setGeometry(QgsGeometry.fromWkt(
                "LINESTRING(200200 450200,200300 450300)"
            ))
        else:
            feature.setGeometry(QgsGeometry.fromWkt(
                "POLYGON((200400 450400,200500 450400,200500 450500,"
                "200400 450500,200400 450400))"
            ))
        feature["유적명"] = site_name
        layer.dataProvider().addFeature(feature)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        return layer

    def test_mixed_geometry_families_remain_separate_and_number_continuously(self):
        project = QgsProject.instance()
        project.clear()
        study = QgsVectorLayer("Polygon?crs=EPSG:5186", "study", "memory")
        study_feature = QgsFeature()
        study_feature.setGeometry(QgsGeometry.fromRect(
            QgsRectangle(199900, 449900, 200000, 450000)
        ))
        study.dataProvider().addFeature(study_feature)
        study.updateExtents()
        project.addMapLayer(study)
        sources = [
            self.make_family_source("Point", "point_sites", "점 유적"),
            self.make_family_source("LineString", "line_sites", "선 유적"),
            self.make_family_source("Polygon", "polygon_sites", "면 유적"),
        ]
        plugin = self.plugin_class(None)
        plugin.log = lambda _message: None
        plugin._active_progress = None
        plugin._current_processing_stats = {}
        source_group = project.layerTreeRoot().addGroup("sources")
        result = plugin.consolidate_heritage_layers(
            [layer.id() for layer in sources],
            QgsGeometry.fromRect(
                QgsRectangle(199000, 449000, 202000, 452000)
            ),
            study,
            source_group,
            source_roles={layer.id(): self.roles["surface"] for layer in sources},
            matching_decision_provider=lambda candidates: [
                {**candidate, "decision": self.keep_decision}
                for candidate in candidates
            ],
        )

        main_layers = result["main_layers"]
        self.assertEqual({layer.geometryType() for layer in main_layers}, {0, 1, 2})
        summary = plugin.number_heritage_layers_v4(
            main_layers,
            study,
            0,
            QgsGeometry.fromRect(
                QgsRectangle(199000, 449000, 202000, 452000)
            ),
            study.crs(),
            [],
            False,
        )
        self.assertEqual(summary["number_group_count"], 3)
        numbers = {
            feature["번호"]
            for layer in main_layers
            for feature in layer.getFeatures()
        }
        self.assertEqual(numbers, {1, 2, 3})

    def consolidate_cross_family_pair(self, decision):
        project = QgsProject.instance()
        project.clear()
        study = QgsVectorLayer("Polygon?crs=EPSG:5186", "study", "memory")
        study_feature = QgsFeature()
        study_feature.setGeometry(QgsGeometry.fromRect(
            QgsRectangle(199900, 449900, 200100, 450100)
        ))
        study.dataProvider().addFeature(study_feature)
        study.updateExtents()
        project.addMapLayer(study)
        point = self.make_family_source(
            "Point",
            "designated_points",
            "공주 교차형상 유적",
            "POINT(200050 450050)",
        )
        polygon = self.make_family_source(
            "Polygon",
            "distribution_polygons",
            "공주 교차형상 유적",
            (
                "POLYGON((200000 450000,200100 450000,200100 450100,"
                "200000 450100,200000 450000))"
            ),
        )
        plugin = self.plugin_class(None)
        plugin.log = lambda _message: None
        plugin._active_progress = None
        plugin._current_processing_stats = {}
        observed = []

        def provider(candidates):
            observed.extend(candidates)
            return [
                {**candidate, "decision": decision}
                for candidate in candidates
            ]

        result = plugin.consolidate_heritage_layers(
            [point.id(), polygon.id()],
            QgsGeometry.fromRect(
                QgsRectangle(199000, 449000, 201000, 451000)
            ),
            study,
            project.layerTreeRoot().addGroup("sources"),
            source_roles={
                point.id(): self.roles["designated"],
                polygon.id(): self.roles["distribution"],
            },
            matching_decision_provider=provider,
        )
        return plugin, study, result, observed

    def test_cross_family_keep_is_audited_without_relation(self):
        _plugin, _study, result, observed = self.consolidate_cross_family_pair(
            self.keep_decision
        )
        self.assertEqual(len(observed), 1)
        self.assertFalse(observed[0]["auto_apply"])
        self.assertIn(
            observed[0]["geometry_pair"],
            {"point_polygon", "polygon_point"},
        )
        self.assertEqual(len(result["main_layers"]), 2)
        cross_audit = result["audit_layers"][-1]
        self.assertEqual(cross_audit.featureCount(), 1)
        self.assertEqual(next(cross_audit.getFeatures())["DECISION"], "keep")
        for layer in result["main_layers"]:
            feature = next(layer.getFeatures())
            self.assertFalse(feature["RELATION_KEY"])
            self.assertFalse(feature["RELATION_TYPE"])
            self.assertFalse(feature["LINKED_IDS"])

    def test_cross_family_link_populates_reciprocal_relation(self):
        _plugin, _study, result, _observed = (
            self.consolidate_cross_family_pair("link")
        )
        features = [
            next(layer.getFeatures()) for layer in result["main_layers"]
        ]
        self.assertNotEqual(features[0]["NUMBER_KEY"], features[1]["NUMBER_KEY"])
        self.assertEqual(
            {feature["MATCH_STATUS"] for feature in features},
            {"LINKED"},
        )
        self.assertEqual(
            {feature["RELATION_TYPE"] for feature in features},
            {"same_entity"},
        )
        self.assertEqual(
            {features[0]["LINKED_IDS"], features[1]["LINKED_IDS"]},
            {features[0]["SRC_UID"], features[1]["SRC_UID"]},
        )

    def test_cross_family_merge_keeps_both_geometries_and_one_label(self):
        plugin, study, result, _observed = self.consolidate_cross_family_pair(
            "merge"
        )
        main_layers = result["main_layers"]
        self.assertEqual({layer.geometryType() for layer in main_layers}, {0, 2})
        features = [next(layer.getFeatures()) for layer in main_layers]
        self.assertEqual(
            {feature["NUMBER_KEY"] for feature in features},
            {features[0]["NUMBER_KEY"]},
        )
        self.assertEqual(
            {feature["SITE_ENTITY_KEY"] for feature in features},
            {features[0]["SITE_ENTITY_KEY"]},
        )
        self.assertEqual(
            {feature["ENTITY_KEY"] for feature in features},
            {features[0]["ENTITY_KEY"]},
        )
        summary = plugin.number_heritage_layers_v4(
            main_layers,
            study,
            0,
            QgsGeometry.fromRect(
                QgsRectangle(199000, 449000, 201000, 451000)
            ),
            study.crs(),
            [],
            False,
        )
        self.assertEqual(summary["number_group_count"], 1)
        numbered = [
            feature
            for layer in main_layers
            for feature in layer.getFeatures()
        ]
        self.assertEqual({feature["번호"] for feature in numbered}, {1})
        self.assertEqual(sum(feature["LABEL_OK"] for feature in numbered), 1)

    def test_parent_child_merge_shares_number_but_not_entity(self):
        layer = self.make_layer([
            {
                "uid": "park",
                "role": self.roles["designated"],
                "name": "공주 탑골공원",
                "wkt": "POLYGON((0 0,10 0,10 10,0 10,0 0))",
            },
            {
                "uid": "pavilion",
                "role": self.roles["distribution"],
                "name": "공주 탑골공원 팔각정",
                "wkt": "POLYGON((1 1,2 1,2 2,1 2,1 1))",
            },
        ])

        def merge(candidates):
            self.assertEqual(candidates[0]["relation_type"], "parent_child")
            return [{**candidate, "decision": "merge"} for candidate in candidates]

        result = self.plugin_class(None).apply_source_aware_matching(
            layer,
            decision_provider=merge,
        )
        main = next(result["main"].getFeatures())
        suppressed = next(result["suppressed"].getFeatures())
        self.assertEqual(main["NUMBER_KEY"], suppressed["NUMBER_KEY"])
        self.assertNotEqual(
            main["SITE_ENTITY_KEY"], suppressed["SITE_ENTITY_KEY"]
        )
        self.assertNotEqual(main["ENTITY_KEY"], suppressed["ENTITY_KEY"])
        self.assertEqual(
            {main["RELATION_TYPE"], suppressed["RELATION_TYPE"]},
            {"parent_child"},
        )

    def test_source_metadata_order_is_deterministic(self):
        layer = self.make_layer([
            {
                "uid": "metadata-b",
                "role": self.roles["surface"],
                "name": "메타데이터 유적",
                "wkt": "POLYGON((0 0,1 0,1 1,0 1,0 0))",
            },
            {
                "uid": "metadata-a",
                "role": self.roles["surface"],
                "name": "메타데이터 유적",
                "wkt": "POLYGON((2 0,3 0,3 1,2 1,2 0))",
            },
        ])
        layer.startEditing()
        key_index = layer.fields().indexFromName("NUMBER_KEY")
        for feature in layer.getFeatures():
            layer.changeAttributeValue(feature.id(), key_index, "shared")
        layer.commitChanges()
        plugin = self.plugin_class(None)
        plugin.aggregate_source_metadata(layer)
        payloads = {feature["SRC_JSON"] for feature in layer.getFeatures()}
        self.assertEqual(len(payloads), 1)
        self.assertEqual(
            [record["uid"] for record in json.loads(payloads.pop())],
            ["metadata-a", "metadata-b"],
        )

    def test_excavation_area_merge_keeps_all_parts_visible(self):
        layer = self.make_layer([
            {
                "uid": "area-i",
                "role": self.roles["excavation"],
                "name": "공주 월송유적 I지역",
                "project": "공주 월송 개발사업",
                "wkt": "POLYGON((0 0,10 0,10 10,0 10,0 0))",
            },
            {
                "uid": "area-ii",
                "role": self.roles["excavation"],
                "name": "공주 월송유적 II지역",
                "project": "공주 월송 개발사업",
                "wkt": "POLYGON((9 0,19 0,19 10,9 10,9 0))",
            },
        ])

        result = self.plugin_class(None).apply_source_aware_matching(
            layer,
            decision_provider=self.recommended,
        )

        self.assertEqual(result["main"].featureCount(), 2)
        self.assertEqual(result["suppressed"].featureCount(), 0)
        features = list(result["main"].getFeatures())
        self.assertEqual(
            len({feature["SITE_ENTITY_KEY"] for feature in features}), 1
        )
        self.assertEqual(
            len({feature["NUMBER_KEY"] for feature in features}), 1
        )
        self.assertEqual(
            len({feature["GROUP_KEY"] for feature in features}), 1
        )
        self.assertTrue(
            all(int(feature["IS_REP"]) == 1 for feature in features)
        )

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

    def test_contained_polygons_record_boundary_not_geometry_distance(self):
        layer = self.make_layer([
            {
                "uid": "designated-outer",
                "role": self.roles["designated"],
                "name": "공주 경계거리 유적",
                "wkt": "POLYGON((0 0,10 0,10 10,0 10,0 0))",
            },
            {
                "uid": "excavation-inner",
                "role": self.roles["excavation"],
                "name": "공주 경계거리 유적",
                "wkt": "POLYGON((2 2,8 2,8 8,2 8,2 2))",
            },
        ])
        captured = []

        def decisions(candidates):
            captured.extend(candidates)
            return self.recommended(candidates)

        self.plugin_class(None).apply_source_aware_matching(
            layer,
            decision_provider=decisions,
        )

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["distance"], 0.0)
        self.assertAlmostEqual(
            captured[0]["boundary_distance"], 2.0, places=6
        )

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
        for feature in result["main"].getFeatures():
            self.assertFalse(feature["LINKED_IDS"])
            self.assertFalse(feature["RELATION_KEY"])
            self.assertFalse(feature["RELATION_TYPE"])
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

    def test_protection_code_alone_does_not_link_unrelated_asset(self):
        layer = self.make_layer([
            {
                "uid": "d1",
                "role": self.roles["designated"],
                "name": "공주 서로 다른 유적",
                "code": "COLLISION-1",
                "wkt": "POLYGON((0 0,10 0,10 10,0 10,0 0))",
            },
            {
                "uid": "p1",
                "role": self.roles["protection"],
                "name": "부여 무관 유적 보호구역",
                "code": "COLLISION-1",
                "wkt": "POLYGON((-5 -5,15 -5,15 15,-5 15,-5 -5))",
            },
        ])
        result = self.plugin_class(None).apply_source_aware_matching(
            layer,
            decision_provider=self.recommended,
        )
        designated = next(result["main"].getFeatures())
        protection = next(result["protection"].getFeatures())

        self.assertFalse(designated["LINKED_IDS"])
        self.assertFalse(protection["LINKED_IDS"])
        self.assertFalse(protection["RELATION_KEY"])

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
        # The same supplier code/name/geometry in different source roles is a
        # matching candidate, not a duplicate selected layer to discard.
        m_feature["유산코드"] = "D-1"
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
