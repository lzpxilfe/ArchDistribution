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


def square(x, y, size):
    return (
        f"POLYGON(({x} {y},{x + size} {y},{x + size} {y + size},"
        f"{x} {y + size},{x} {y}))"
    )


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python runtime is not available")
class QgisRelationIntegrationTests(unittest.TestCase):
    """Wholly synthetic checks of over-marking, chains and rule exclusion."""

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
            ROLE_NATIONAL_DESIGNATED,
        )

        Processing.initialize()
        cls.plugin_class = ArchDistribution
        cls.keep = DECISION_KEEP
        cls.distribution = ROLE_DISTRIBUTION
        cls.excavation = ROLE_EXCAVATION
        cls.designated = ROLE_NATIONAL_DESIGNATED

    def setUp(self):
        QgsProject.instance().clear()

    def make_plugin(self):
        plugin = self.plugin_class(None)
        plugin.log = lambda _message: None
        plugin._active_progress = None
        plugin._current_processing_stats = {}
        return plugin

    def accept_recommendations(self, candidates):
        """Behave like the review dialog's initial selection."""
        decisions = []
        for candidate in candidates:
            item = dict(candidate)
            if candidate.get("auto_apply"):
                item["decision"] = candidate["recommended_decision"]
                item["decision_source"] = "auto"
            else:
                item["decision"] = self.keep
                item["decision_source"] = "user"
            decisions.append(item)
        return decisions

    def make_matching_layer(self, rows):
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186", "relation_input", "memory"
        )
        layer.dataProvider().addAttributes([
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
        ])
        layer.updateFields()
        features = []
        for row in rows:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromWkt(row["wkt"]))
            feature["유적명"] = row["name"]
            feature["SRC_NAME"] = row["name"]
            feature["SRC_UID"] = row["uid"]
            feature["SOURCE_ROLE"] = row["role"]
            feature["ENTITY_KEY"] = f"{row['role']}:{row['uid']}"
            feature["MATCH_STATUS"] = "UNIQUE"
            feature["REP_SOURCE"] = row["role"]
            feature["IS_REP"] = 1
            feature["NUMBER_KEY"] = f"{row['role']}:{row['uid']}"
            feature["GROUP_KEY"] = f"{row['role']}:{row['uid']}"
            feature["SRC_COUNT"] = 1
            feature["SRC_JSON"] = json.dumps([{"uid": row["uid"]}])
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        return layer

    @staticmethod
    def by_uid(layer):
        return {
            feature["SRC_UID"]: feature for feature in layer.getFeatures()
        }

    def test_numbered_part_joins_site_and_unrelated_record_stays(self):
        layer = self.make_matching_layer([
            {"uid": "site", "role": self.distribution,
             "name": "가상리 고분군", "wkt": square(0, 0, 100)},
            {"uid": "tomb", "role": self.distribution,
             "name": "가상리고분군 제14호", "wkt": square(10, 10, 2)},
            {"uid": "dolmen", "role": self.distribution,
             "name": "나상 고인돌", "wkt": square(50, 50, 2)},
        ])
        result = self.make_plugin().apply_source_aware_matching(
            layer, decision_provider=self.accept_recommendations
        )
        main = self.by_uid(result["main"])
        suppressed = self.by_uid(result["suppressed"])
        self.assertEqual(set(main), {"site", "dolmen"})
        self.assertEqual(set(suppressed), {"tomb"})
        self.assertEqual(
            suppressed["tomb"]["NUMBER_KEY"], main["site"]["NUMBER_KEY"]
        )
        # A part shares the number but stays its own archaeological entity.
        self.assertNotEqual(
            suppressed["tomb"]["SITE_ENTITY_KEY"],
            main["site"]["SITE_ENTITY_KEY"],
        )
        self.assertIn("parent_child", suppressed["tomb"]["RELATION_TYPE"])

    def numbering_layer(self, rows, name="numbering_input"):
        layer = self.make_matching_layer(rows)
        layer.setName(name)
        layer.dataProvider().addAttributes([QgsField("번호", QVariant.Int)])
        layer.updateFields()
        QgsProject.instance().addMapLayer(layer)
        return layer

    def numbering_study(self):
        study = QgsVectorLayer("Polygon?crs=EPSG:5186", "study", "memory")
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromWkt(square(0, 0, 10)))
        study.dataProvider().addFeature(feature)
        study.updateExtents()
        QgsProject.instance().addMapLayer(study)
        return study

    COMPASS_SITES = [
        ("west", "서 유적", square(-110, 0, 10)),
        ("south", "남 유적", square(0, -110, 10)),
        ("north", "북 유적", square(0, 110, 10)),
        ("east", "동 유적", square(110, 0, 10)),
    ]

    def numbers(self, *layers):
        return {
            feature["SRC_UID"]: feature["번호"]
            for layer in layers for feature in layer.getFeatures()
        }

    def test_clockwise_numbering_and_investigations_after_sites(self):
        clockwise = 3
        rows = [
            {"uid": uid, "role": self.distribution, "name": name, "wkt": wkt}
            for uid, name, wkt in self.COMPASS_SITES
        ] + [{"uid": "dig", "role": self.excavation, "name": "북동 발굴",
              "wkt": square(80, 80, 10)}]
        for last, expected in (
            (False, {"north": 1, "dig": 2, "east": 3, "south": 4, "west": 5}),
            (True, {"north": 1, "east": 2, "south": 3, "west": 4, "dig": 5}),
        ):
            layer = self.numbering_layer(rows)
            self.make_plugin().number_heritage_v4(
                layer, self.numbering_study(), clockwise,
                restrict_to_buffer=False, investigations_last=last,
            )
            self.assertEqual(self.numbers(layer), expected)

    def test_investigations_follow_sites_across_geometry_layers(self):
        sites = self.numbering_layer([
            {"uid": uid, "role": self.distribution, "name": name, "wkt": wkt}
            for uid, name, wkt in self.COMPASS_SITES
        ], "sites")
        digs = self.numbering_layer([
            {"uid": "dig", "role": self.excavation, "name": "가까운 발굴",
             "wkt": square(12, 0, 5)},
        ], "digs")
        distance = 1
        self.make_plugin().number_heritage_layers_v4(
            [sites, digs], self.numbering_study(), distance,
            restrict_to_buffer=False, investigations_last=True,
        )
        numbers = self.numbers(sites, digs)
        self.assertEqual(numbers["dig"], 5)
        self.assertEqual(sorted(numbers.values()), [1, 2, 3, 4, 5])

    def test_designated_part_numbering_follows_the_operator_choice(self):
        from ArchDistribution.heritage_matching import (
            DESIGNATED_PARTS_JOIN,
            ROLE_LOCAL_DESIGNATED,
        )
        rows = [
            {"uid": "site", "role": self.designated,
             "name": "가상 가상산성", "wkt": square(0, 0, 100)},
            {"uid": "hall", "role": ROLE_LOCAL_DESIGNATED,
             "name": "가상산성 광복루", "wkt": square(10, 10, 2)},
        ]
        separate = self.make_plugin().apply_source_aware_matching(
            self.make_matching_layer(rows),
            decision_provider=self.accept_recommendations,
        )
        self.assertEqual(set(self.by_uid(separate["main"])), {"site", "hall"})
        joined = self.make_plugin().apply_source_aware_matching(
            self.make_matching_layer(rows),
            decision_provider=self.accept_recommendations,
            designated_parts=DESIGNATED_PARTS_JOIN,
        )
        self.assertEqual(set(self.by_uid(joined["main"])), {"site"})
        # The legal boundary of the joined part is still drawn.
        self.assertEqual(
            set(self.by_uid(joined["designation"])), {"site", "hall"}
        )

    def test_part_site_and_designation_chain_ends_on_one_number(self):
        layer = self.make_matching_layer([
            {"uid": "legal", "role": self.designated,
             "name": "가상리 고분군", "wkt": square(0, 0, 100)},
            {"uid": "site", "role": self.distribution,
             "name": "가상리 고분군", "wkt": square(0, 0, 100)},
            {"uid": "tomb", "role": self.distribution,
             "name": "가상리 고분군 제14호", "wkt": square(10, 10, 2)},
        ])
        result = self.make_plugin().apply_source_aware_matching(
            layer, decision_provider=self.accept_recommendations
        )
        main = self.by_uid(result["main"])
        suppressed = self.by_uid(result["suppressed"])
        self.assertEqual(set(main), {"legal"})
        self.assertEqual(set(suppressed), {"site", "tomb"})
        number = main["legal"]["NUMBER_KEY"]
        self.assertEqual(suppressed["site"]["NUMBER_KEY"], number)
        self.assertEqual(suppressed["tomb"]["NUMBER_KEY"], number)

    def test_spacing_variant_inside_one_register_is_one_number(self):
        layer = self.make_matching_layer([
            {"uid": "a", "role": self.distribution,
             "name": "가상리 고분군 3", "wkt": square(0, 0, 50)},
            {"uid": "b", "role": self.distribution,
             "name": "가상리고분군3", "wkt": square(0, 0, 50)},
            {"uid": "c", "role": self.distribution,
             "name": "가상리 고분군 4", "wkt": square(0, 0, 50)},
        ])
        result = self.make_plugin().apply_source_aware_matching(
            layer, decision_provider=self.accept_recommendations
        )
        main = self.by_uid(result["main"])
        suppressed = self.by_uid(result["suppressed"])
        # The spacing variant of "3" is the same record and is dissolved
        # into it; "4" is a different numbered site drawn on the same
        # footprint and stays separate until a reviewer groups it.
        self.assertEqual(set(main), {"a", "b", "c"})
        self.assertEqual(suppressed, {})
        self.assertEqual(main["a"]["NUMBER_KEY"], main["b"]["NUMBER_KEY"])
        self.assertEqual(main["a"]["GROUP_KEY"], main["b"]["GROUP_KEY"])
        self.assertNotEqual(main["a"]["NUMBER_KEY"], main["c"]["NUMBER_KEY"])

    def test_reviewed_survey_revision_keeps_both_footprints(self):
        layer = self.make_matching_layer([
            {"uid": "map", "role": self.surface_role("distribution"),
             "name": "가상리 유물산포지 4", "wkt": square(0, 0, 50)},
            {"uid": "survey", "role": self.surface_role("surface"),
             "name": "가상리 유물산포지4(범위확장)",
             "wkt": square(50, 0, 20)},
        ])
        offered = []

        def apply_recommended(candidates):
            offered.extend(candidates)
            return [
                {**candidate,
                 "decision": candidate["recommended_decision"],
                 "decision_source": "user"}
                for candidate in candidates
            ]

        result = self.make_plugin().apply_source_aware_matching(
            layer, decision_provider=apply_recommended
        )
        self.assertEqual(len(offered), 1)
        self.assertEqual(offered[0]["rule"], "survey_revision_same_site")
        self.assertFalse(offered[0]["auto_apply"])
        main = self.by_uid(result["main"])
        self.assertEqual(set(main), {"map", "survey"})
        self.assertEqual(
            main["map"]["NUMBER_KEY"], main["survey"]["NUMBER_KEY"]
        )
        self.assertEqual(main["map"]["GROUP_KEY"], main["survey"]["GROUP_KEY"])

    def surface_role(self, name):
        from ArchDistribution.heritage_matching import (
            ROLE_DISTRIBUTION,
            ROLE_SURFACE,
        )
        return ROLE_SURFACE if name == "surface" else ROLE_DISTRIBUTION

    def test_record_repeated_by_adjacent_downloads_is_not_reviewed(self):
        layer = self.make_matching_layer([
            {"uid": "same", "role": self.distribution,
             "name": "가상리 고분군", "wkt": square(0, 0, 30)},
            {"uid": "same", "role": self.distribution,
             "name": "가상리 고분군", "wkt": square(0, 0, 30)},
        ])
        offered = []

        def record_offers(candidates):
            offered.extend(candidates)
            return self.accept_recommendations(candidates)

        result = self.make_plugin().apply_source_aware_matching(
            layer, decision_provider=record_offers
        )
        self.assertEqual(offered, [])
        keys = {
            (feature["NUMBER_KEY"], feature["GROUP_KEY"])
            for feature in result["main"].getFeatures()
        }
        self.assertEqual(len(keys), 1)

    def test_designated_record_without_counterpart_is_numbered(self):
        layer = self.make_matching_layer([
            {"uid": "legal", "role": self.designated,
             "name": "가상산성", "wkt": square(0, 0, 40)},
        ])
        plugin = self.make_plugin()
        numbered = plugin.apply_source_aware_matching(layer)
        self.assertEqual(numbered["main"].featureCount(), 1)
        self.assertEqual(numbered["designation"].featureCount(), 1)
        legal_only = plugin.apply_source_aware_matching(
            self.make_matching_layer([
                {"uid": "legal", "role": self.designated,
                 "name": "가상산성", "wkt": square(0, 0, 40)},
            ]),
            number_designated=False,
        )
        self.assertEqual(legal_only["main"].featureCount(), 0)
        self.assertEqual(legal_only["designation"].featureCount(), 1)

    def test_legal_only_settings_disable_designated_numbering(self):
        decide = self.plugin_class._run_numbers_designated
        self.assertFalse(decide({
            "heritage_layer_ids": ["legal"],
            "legal_layer_roles": {"legal": self.designated},
        }))
        self.assertTrue(decide({
            "heritage_layer_ids": ["legal", "nearby"],
            "legal_layer_roles": {"legal": self.designated},
        }))
        self.assertTrue(decide({"heritage_layer_ids": ["nearby"]}))

    def make_survey_source(self):
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186", "synthetic_excavation", "memory"
        )
        layer.dataProvider().addAttributes([
            QgsField("유적명", QVariant.String),
            QgsField("사업명", QVariant.String),
            QgsField("유적유무", QVariant.String),
        ])
        layer.updateFields()
        rows = (
            ("가상 유적", "가상 개발사업", "유적있음", square(200100, 450100, 20)),
            ("나상 부지", "나상 개발사업", "유적없음", square(200300, 450300, 20)),
        )
        features = []
        for name, project, outcome, wkt in rows:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
            feature["유적명"] = name
            feature["사업명"] = project
            feature["유적유무"] = outcome
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        return layer

    def make_project_source(self):
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186", "synthetic_project", "memory"
        )
        layer.dataProvider().addAttributes([
            QgsField("유적명", QVariant.String),
            QgsField("사업명", QVariant.String),
        ])
        layer.updateFields()
        features = []
        for name, wkt in (
            ("가상 유물산포지 1", square(200100, 450100, 20)),
            ("가상 고분군", square(200600, 450600, 20)),
        ):
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
            feature["유적명"] = name
            feature["사업명"] = "가상 도로 개설사업"
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        return layer

    def project_number_keys(self, role):
        source = self.make_project_source()
        result = self.consolidate(source, roles={source.id(): role})
        return {
            feature["NUMBER_KEY"]
            for layer in result["main_layers"]
            for feature in layer.getFeatures()
        }

    def test_one_excavation_project_shares_a_number(self):
        self.assertEqual(len(self.project_number_keys(self.excavation)), 1)

    def test_survey_sites_of_one_project_keep_their_own_numbers(self):
        from ArchDistribution.heritage_matching import ROLE_SURFACE
        self.assertEqual(len(self.project_number_keys(ROLE_SURFACE)), 2)

    def consolidate(self, source, roles=None, **options):
        project = QgsProject.instance()
        study = QgsVectorLayer("Polygon?crs=EPSG:5186", "study", "memory")
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromRect(
            QgsRectangle(199900, 449900, 200000, 450000)
        ))
        study.dataProvider().addFeature(feature)
        study.updateExtents()
        project.addMapLayer(study)
        return self.make_plugin().consolidate_heritage_layers(
            [source.id()],
            QgsGeometry.fromRect(QgsRectangle(199000, 449000, 202000, 452000)),
            study,
            project.layerTreeRoot().addGroup("sources"),
            source_roles=roles or {source.id(): self.excavation},
            matching_decision_provider=self.accept_recommendations,
            **options,
        )

    def test_no_remains_investigation_is_excluded_but_preserved(self):
        result = self.consolidate(
            self.make_survey_source(), exclusion_rules=["no_remains"]
        )
        names = {
            feature["SRC_NAME"]
            for layer in result["main_layers"]
            for feature in layer.getFeatures()
        }
        self.assertEqual(names, {"가상 유적"})
        excluded = result["excluded_layers"]
        self.assertEqual(len(excluded), 1)
        record = next(excluded[0].getFeatures())
        self.assertEqual(record["EXCLUDE_RULE"], "no_remains")
        self.assertEqual(record["유적명"], "나상 부지")
        self.assertIn("유적없음", record["SRC_JSON"])

    def test_operator_excluded_name_is_preserved_for_audit(self):
        result = self.consolidate(
            self.make_survey_source(), exclusion_list=["나상부지"]
        )
        names = {
            feature["SRC_NAME"]
            for layer in result["main_layers"]
            for feature in layer.getFeatures()
        }
        self.assertEqual(names, {"가상 유적"})
        record = next(result["excluded_layers"][0].getFeatures())
        self.assertEqual(record["EXCLUDE_RULE"], "user_name")
        self.assertEqual(record["유적명"], "나상 부지")

    def test_default_rules_keep_no_remains_investigations(self):
        result = self.consolidate(self.make_survey_source())
        count = sum(layer.featureCount() for layer in result["main_layers"])
        self.assertEqual(count, 2)
        self.assertEqual(result["excluded_layers"], [])


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python runtime is not available")
class QgisSiteTableIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], False)
        cls.app.initQgis()
        plugin_parent = str(Path(__file__).resolve().parent.parent)
        if plugin_parent not in sys.path:
            sys.path.insert(0, plugin_parent)
        from ArchDistribution.arch_distribution import ArchDistribution

        cls.plugin_class = ArchDistribution

    def test_numbered_result_becomes_hwpx_and_csv_table(self):
        import csv
        import tempfile
        import zipfile

        project = QgsProject.instance()
        project.clear()
        group = project.layerTreeRoot().addGroup("ArchDistribution_결과물")
        study = QgsVectorLayer("Polygon?crs=EPSG:5186", "00_조사구역", "memory")
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromWkt(square(0, 0, 10)))
        study.dataProvider().addFeature(feature)
        project.addMapLayer(study, False)
        group.addLayer(study)

        sites = QgsVectorLayer(
            "Polygon?crs=EPSG:5186", "수집_및_병합된_주변유적", "memory"
        )
        sites.dataProvider().addAttributes([
            QgsField("번호", QVariant.Int),
            QgsField("유적명", QVariant.String),
            QgsField("주소", QVariant.String),
            QgsField("DIST_M", QVariant.Double),
            QgsField("LABEL_OK", QVariant.Int),
            QgsField("NUMBER_KEY", QVariant.String),
            QgsField("SOURCE_ROLE", QVariant.String),
            QgsField("SRC_JSON", QVariant.String),
        ])
        sites.updateFields()
        rows = (
            (1, "가상 유적", square(100, 100, 10), 120.0, "distribution:a",
             [{"명칭": "가상 유적", "시대": "0)고려시대,1)조선시대",
               "소재지": "가상도 가상시 가상동 1",
               "_source_uid": "distribution:code:a"}]),
            (2, "나상 고분군", square(-300, 0, 20), 280.0, "excavation:b",
             [{"유적명": "나상 고분군", "시대": "0)삼국시대",
               "소재지": "가상도 가상시 나상동 산 2", "조사기관": "가상연구원",
               "_source_uid": "excavation:code:b"}]),
        )
        features = []
        for number, name, wkt, distance, key, records in rows:
            item = QgsFeature(sites.fields())
            item.setGeometry(QgsGeometry.fromWkt(wkt))
            item["번호"] = number
            item["유적명"] = name
            item["주소"] = records[0]["소재지"]
            item["DIST_M"] = distance
            item["LABEL_OK"] = 1
            item["NUMBER_KEY"] = key
            item["SOURCE_ROLE"] = key.split(":")[0]
            item["SRC_JSON"] = json.dumps(records, ensure_ascii=False)
            features.append(item)
        sites.dataProvider().addFeatures(features)
        project.addMapLayer(sites, False)
        group.addLayer(sites)

        plugin = self.plugin_class(None)
        plugin.log = lambda _message: None
        with tempfile.TemporaryDirectory() as directory:
            paths = plugin._export_site_table(
                {"study_area_id": study.id(), "scale": 5000,
                 "buffers": [500, 1000]},
                group,
                directory,
                "synthetic",
            )
            self.assertEqual(len(paths), 2)
            hwpx = next(path for path in paths if path.endswith(".hwpx"))
            with zipfile.ZipFile(hwpx) as archive:
                section = archive.read("Contents/section0.xml").decode()
            self.assertIn("가상 유적", section)
            csv_path = next(path for path in paths if path.endswith(".csv"))
            with open(csv_path, encoding="utf-8-sig", newline="") as handle:
                table = list(csv.reader(handle))
        self.assertEqual([row[0] for row in table[1:]], ["1", "2"])
        self.assertEqual(table[1][2], "고려·조선")
        self.assertEqual(table[1][5], "북동 120m")
        self.assertEqual(table[2][5], "서 280m")
        self.assertEqual(table[2][6], "발굴조사(가상연구원)")
        self.assertEqual(table[2][4], "가상시 나상동 산 2")
