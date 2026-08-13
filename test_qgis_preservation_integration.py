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
        QgsPointXY,
        QgsProject,
        QgsRectangle,
        QgsVectorLayer,
    )

    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python runtime is not available")
class QgisPreservationIntegrationTests(unittest.TestCase):
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

        Processing.initialize()
        cls.plugin_class = ArchDistribution

    def setUp(self):
        QgsProject.instance().clear()

    def make_plugin(self):
        plugin = self.plugin_class.__new__(self.plugin_class)
        plugin.log = lambda _message: None
        return plugin

    def test_same_site_actions_share_number_and_render_four_colors(self):
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "매장유산유존지역",
            "memory",
        )
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("번호", QVariant.Int),
            QgsField("유적명", QVariant.String),
            QgsField("보존조치", QVariant.String),
            QgsField("NUMBER_KEY", QVariant.String),
            QgsField("GROUP_KEY", QVariant.String),
        ])
        layer.updateFields()

        actions = [
            ("현상보존", "POLYGON((0 0,10 0,10 10,0 10,0 0))"),
            ("정밀발굴조사", "POLYGON((10 0,30 0,30 20,10 20,10 0))"),
            ("시굴조사", "POLYGON((30 0,60 0,60 30,30 30,30 0))"),
            ("표본조사", "POLYGON((60 0,100 0,100 40,60 40,60 0))"),
        ]
        features = []
        for action, wkt in actions:
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromWkt(wkt))
            feat["유적명"] = "통합 테스트 유적"
            feat["보존조치"] = action
            feat["NUMBER_KEY"] = "site:통합테스트유적"
            feat["GROUP_KEY"] = f"site:통합테스트유적|action:{action}"
            features.append(feat)
        provider.addFeatures(features)
        layer.updateExtents()

        plugin = self.make_plugin()
        plugin.number_heritage_v4(
            layer,
            QgsPointXY(0, 0),
            sort_order=0,
            extent_geom=QgsGeometry.fromRect(QgsRectangle(-1, -1, 101, 41)),
            extent_crs=layer.crs(),
            buffer_geoms=[],
            restrict_to_buffer=False,
        )

        numbered = list(layer.getFeatures())
        self.assertEqual({feat["번호"] for feat in numbered}, {1})
        self.assertEqual(sum(feat["LABEL_OK"] for feat in numbered), 1)
        largest = max(numbered, key=lambda feat: feat.geometry().area())
        self.assertEqual(largest["LABEL_OK"], 1)

        renderer = plugin.create_preservation_action_renderer(layer, 0.3)
        self.assertIsNotNone(renderer)
        categories = {category.label(): category for category in renderer.categories()}
        expected = {
            "현상보존": "#b9f8ff",
            "정밀발굴조사": "#e7d6ff",
            "시굴조사": "#f5ffd2",
            "표본조사": "#ffdfdf",
        }
        self.assertEqual(set(categories), set(expected))
        for label, fill_color in expected.items():
            symbol = categories[label].symbol()
            self.assertEqual(symbol.color().name(), fill_color)
            self.assertEqual(
                symbol.symbolLayer(0).strokeColor().name(),
                "#ff0000",
            )

    def test_renumber_keeps_match_decisions_and_number_groups(self):
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "대표결과",
            "memory",
        )
        invariant_fields = (
            "SOURCE_ROLE",
            "ENTITY_KEY",
            "RELATION_KEY",
            "MATCH_STATUS",
            "MATCH_RULE",
            "REP_SOURCE",
            "LINKED_IDS",
            "IS_REP",
            "NUMBER_KEY",
            "GROUP_KEY",
            "SRC_JSON",
        )
        fields = [
            QgsField("번호", QVariant.Int),
            QgsField("유적명", QVariant.String),
        ]
        fields.extend(
            QgsField(name, QVariant.Int if name == "IS_REP" else QVariant.String)
            for name in invariant_fields
        )
        layer.dataProvider().addAttributes(fields)
        layer.updateFields()

        rows = (
            (
                "A유적",
                "site:a",
                "POLYGON((0 30,10 30,10 40,0 40,0 30))",
            ),
            (
                "A유적",
                "site:a",
                "POLYGON((0 20,5 20,5 25,0 25,0 20))",
            ),
            (
                "B유적",
                "site:b",
                "POLYGON((0 0,8 0,8 8,0 8,0 0))",
            ),
        )
        features = []
        for index, (name, number_key, wkt) in enumerate(rows):
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
            feature["번호"] = 99 - index
            feature["유적명"] = name
            feature["SOURCE_ROLE"] = "excavation"
            feature["ENTITY_KEY"] = f"entity:{index}"
            feature["RELATION_KEY"] = "rel:kept"
            feature["MATCH_STATUS"] = "USER_MERGED"
            feature["MATCH_RULE"] = "exact_name_and_overlap"
            feature["REP_SOURCE"] = "excavation"
            feature["LINKED_IDS"] = "distribution:1"
            feature["IS_REP"] = 1
            feature["NUMBER_KEY"] = number_key
            feature["GROUP_KEY"] = f"{number_key}:part:{index}"
            feature["SRC_JSON"] = json.dumps({"row": index})
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()

        before = {
            feature.id(): tuple(feature[name] for name in invariant_fields)
            for feature in layer.getFeatures()
        }
        summary = self.make_plugin().number_heritage_v4(
            layer,
            QgsPointXY(0, 0),
            sort_order=0,
            extent_geom=QgsGeometry.fromRect(
                QgsRectangle(-1, -1, 11, 41)
            ),
            extent_crs=layer.crs(),
            buffer_geoms=[],
            restrict_to_buffer=False,
        )

        after = list(layer.getFeatures())
        self.assertEqual(summary["number_group_count"], 2)
        self.assertEqual(summary["numbered_feature_count"], 3)
        numbers_by_key = {}
        for feature in after:
            numbers_by_key.setdefault(
                feature["NUMBER_KEY"],
                set(),
            ).add(feature["번호"])
            self.assertEqual(
                tuple(feature[name] for name in invariant_fields),
                before[feature.id()],
            )
        self.assertEqual(len(numbers_by_key["site:a"]), 1)
        self.assertEqual(len(numbers_by_key["site:b"]), 1)
        self.assertNotEqual(
            next(iter(numbers_by_key["site:a"])),
            next(iter(numbers_by_key["site:b"])),
        )
        for number_key in numbers_by_key:
            self.assertEqual(
                sum(
                    feature["LABEL_OK"]
                    for feature in after
                    if feature["NUMBER_KEY"] == number_key
                ),
                1,
            )

    def test_renumber_hides_extent_outside_features_and_reconsiders_them(self):
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "재번호_도곽_검증",
            "memory",
        )
        layer.dataProvider().addAttributes([
            QgsField("번호", QVariant.Int),
            QgsField("유적명", QVariant.String),
        ])
        layer.updateFields()

        rows = (
            (
                1,
                "도곽 안",
                "POLYGON((0 0,10 0,10 10,0 10,0 0))",
            ),
            (
                2,
                "도곽 밖",
                "POLYGON((200 200,210 200,210 210,200 210,200 200))",
            ),
            (
                3,
                "도곽 접촉",
                "POLYGON((20 0,30 0,30 10,20 10,20 0))",
            ),
        )
        features = []
        for number, name, wkt in rows:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
            feature["번호"] = number
            feature["유적명"] = name
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        layer.setSubsetString('"번호" IS NOT NULL')

        plugin = self.make_plugin()
        first_summary = plugin.number_heritage_v4(
            layer,
            QgsPointXY(0, 0),
            sort_order=0,
            extent_geom=QgsGeometry.fromRect(
                QgsRectangle(-1, -1, 20, 20)
            ),
            extent_crs=layer.crs(),
            buffer_geoms=[],
            restrict_to_buffer=False,
        )

        self.assertEqual(first_summary["numbered_feature_count"], 1)
        self.assertEqual(layer.subsetString(), '"번호" IS NOT NULL')
        self.assertEqual(
            [feature["유적명"] for feature in layer.getFeatures()],
            ["도곽 안"],
        )

        layer.setSubsetString("")
        all_features = {
            feature["유적명"]: feature
            for feature in layer.getFeatures()
        }
        self.assertIsNone(all_features["도곽 밖"]["번호"])
        self.assertEqual(all_features["도곽 밖"]["비고"], "도곽_밖")
        self.assertIsNone(all_features["도곽 접촉"]["번호"])
        self.assertEqual(all_features["도곽 접촉"]["비고"], "도곽_밖")

        # Simulate a later renumber run which starts with the plugin-managed
        # visibility filter still applied. Expanding the extent must restore
        # the previously hidden record instead of losing it permanently.
        layer.setSubsetString('"번호" IS NOT NULL')
        second_summary = plugin.number_heritage_v4(
            layer,
            QgsPointXY(0, 0),
            sort_order=0,
            extent_geom=QgsGeometry.fromRect(
                QgsRectangle(-1, -1, 220, 220)
            ),
            extent_crs=layer.crs(),
            buffer_geoms=[],
            restrict_to_buffer=False,
        )

        self.assertEqual(second_summary["numbered_feature_count"], 3)
        self.assertEqual(layer.subsetString(), "")
        restored = list(layer.getFeatures())
        self.assertEqual({feature["유적명"] for feature in restored}, {
            "도곽 안",
            "도곽 밖",
            "도곽 접촉",
        })
        self.assertTrue(all(feature["번호"] is not None for feature in restored))

    def test_renumber_preserves_user_subset_filter(self):
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "재번호_사용자_필터",
            "memory",
        )
        layer.dataProvider().addAttributes([
            QgsField("번호", QVariant.Int),
            QgsField("유적명", QVariant.String),
        ])
        layer.updateFields()

        rows = (
            (
                1,
                "유지_안",
                "POLYGON((0 0,10 0,10 10,0 10,0 0))",
            ),
            (
                2,
                "유지_밖",
                "POLYGON((200 200,210 200,210 210,200 210,200 200))",
            ),
            (
                3,
                "사용자숨김",
                "POLYGON((5 5,8 5,8 8,5 8,5 5))",
            ),
        )
        features = []
        for number, name, wkt in rows:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
            feature["번호"] = number
            feature["유적명"] = name
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()

        user_subset = "\"유적명\" LIKE '유지_%'"
        layer.setSubsetString(user_subset)
        plugin = self.make_plugin()
        plugin.number_heritage_v4(
            layer,
            QgsPointXY(0, 0),
            sort_order=0,
            extent_geom=QgsGeometry.fromRect(
                QgsRectangle(-1, -1, 20, 20)
            ),
            extent_crs=layer.crs(),
            buffer_geoms=[],
            restrict_to_buffer=False,
        )

        managed_subset = (
            f'({user_subset}) AND ("번호" IS NOT NULL)'
        )
        self.assertEqual(layer.subsetString(), managed_subset)
        self.assertEqual(
            [feature["유적명"] for feature in layer.getFeatures()],
            ["유지_안"],
        )

        plugin.number_heritage_v4(
            layer,
            QgsPointXY(0, 0),
            sort_order=0,
            extent_geom=QgsGeometry.fromRect(
                QgsRectangle(-1, -1, 220, 220)
            ),
            extent_crs=layer.crs(),
            buffer_geoms=[],
            restrict_to_buffer=False,
        )

        self.assertEqual(layer.subsetString(), user_subset)
        self.assertEqual(
            {feature["유적명"] for feature in layer.getFeatures()},
            {"유지_안", "유지_밖"},
        )

    def test_source_json_is_aggregated_for_every_action_part(self):
        layer = QgsVectorLayer("Point?crs=EPSG:5186", "source-audit", "memory")
        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("NUMBER_KEY", QVariant.String),
            QgsField("SRC_COUNT", QVariant.Int),
            QgsField("SRC_JSON", QVariant.String),
        ])
        layer.updateFields()

        features = []
        for source_id in (1, 2):
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(source_id, 0)))
            feat["NUMBER_KEY"] = "site:동일유적"
            feat["SRC_COUNT"] = 1
            feat["SRC_JSON"] = json.dumps(
                [{"RNUM": source_id}],
                ensure_ascii=False,
            )
            features.append(feat)
        provider.addFeatures(features)

        self.make_plugin().aggregate_source_metadata(layer)

        for feat in layer.getFeatures():
            self.assertEqual(feat["SRC_COUNT"], 2)
            self.assertEqual(
                {item["RNUM"] for item in json.loads(feat["SRC_JSON"])},
                {1, 2},
            )

    def test_generic_action_field_is_not_misidentified(self):
        unrelated = QgsVectorLayer("Polygon?crs=EPSG:5186", "unrelated", "memory")
        unrelated.dataProvider().addAttributes([
            QgsField("ACTION", QVariant.String),
        ])
        unrelated.updateFields()
        feature = QgsFeature(unrelated.fields())
        feature.setGeometry(QgsGeometry.fromWkt(
            "POLYGON((0 0,1 0,1 1,0 1,0 0))"
        ))
        feature["ACTION"] = "승인"
        unrelated.dataProvider().addFeature(feature)

        self.assertIsNone(
            self.make_plugin().find_preservation_action_field(unrelated)
        )

    def test_preservation_site_id_field_requires_exact_semantics(self):
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "identifier-policy",
            "memory",
        )
        layer.dataProvider().addAttributes([
            QgsField("CODE", QVariant.String),
            QgsField("ACTION_CODE", QVariant.String),
            QgsField("SITE_ID", QVariant.String),
        ])
        layer.updateFields()

        plugin = self.make_plugin()
        self.assertEqual(
            plugin.find_preservation_site_id_field(layer),
            "SITE_ID",
        )

        generic_only = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "generic-code-only",
            "memory",
        )
        generic_only.dataProvider().addAttributes([
            QgsField("CODE", QVariant.String),
            QgsField("ACTION_CODE", QVariant.String),
        ])
        generic_only.updateFields()
        self.assertIsNone(
            plugin.find_preservation_site_id_field(generic_only)
        )

    def test_preservation_number_scope_rejects_unsafe_fallbacks(self):
        first = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "renamed-a",
            "memory",
        )
        second = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "renamed-b",
            "memory",
        )
        plugin = self.make_plugin()

        self.assertEqual(
            plugin._preservation_number_scope(
                first,
                supplier_site_id="SITE-42",
                supplier_id_field="SITE_ID",
                site_name="유적",
                address="",
            ),
            "supplier:siteid:site-42",
        )
        self.assertIsNone(
            plugin._preservation_number_scope(
                first,
                supplier_site_id="ACTION-1",
                supplier_id_field="CODE",
                site_name="유적",
                address="공주시 가상동 1-1",
            )
        )
        self.assertIsNone(
            plugin._preservation_number_scope(
                first,
                site_name="공주 신관동 유적",
                address="미상",
            )
        )
        self.assertIsNone(
            plugin._preservation_number_scope(
                first,
                site_name="유적",
                address="공주시 가상동 1-1",
            )
        )

        first_scope = plugin._preservation_number_scope(
            first,
            site_name="공주 신관동 유적",
            address="공주시 가상동 1-1",
        )
        second_scope = plugin._preservation_number_scope(
            second,
            site_name="공주 신관동 유적",
            address="공주시 가상동 1-1",
        )
        self.assertEqual(first_scope, second_scope)
        self.assertTrue(first_scope.startswith("name_address:"))

    def test_result_content_hash_normalizes_equivalent_polygon_rings(self):
        layers = []
        wkts = (
            "POLYGON((0 0,10 0,10 10,0 10,0 0))",
            "POLYGON((10 10,10 0,0 0,0 10,10 10))",
        )
        for index, wkt in enumerate(wkts):
            layer = QgsVectorLayer(
                "Polygon?crs=EPSG:5186",
                f"normalized-{index}",
                "memory",
            )
            layer.dataProvider().addAttributes([
                QgsField("VALUE", QVariant.String),
            ])
            layer.updateFields()
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
            feature["VALUE"] = "same"
            layer.dataProvider().addFeature(feature)
            layers.append(layer)

        plugin = self.make_plugin()
        self.assertEqual(
            plugin._artifact_layer_content_hash(layers[0]),
            plugin._artifact_layer_content_hash(layers[1]),
        )

    def test_dedicated_workflow_keeps_all_features_and_custom_styles(self):
        source = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "전용작업입력",
            "memory",
        )
        source.dataProvider().addAttributes([
            QgsField("사업명", QVariant.String),
            QgsField("임의분류", QVariant.String),
            QgsField("원본코드", QVariant.String),
        ])
        source.updateFields()

        features = []
        for index, action in enumerate(("현상보존", "시굴조사")):
            feature = QgsFeature(source.fields())
            left = index * 20
            feature.setGeometry(QgsGeometry.fromWkt(
                f"POLYGON(({left} 0,{left + 10} 0,"
                f"{left + 10} 10,{left} 10,{left} 0))"
            ))
            feature["사업명"] = "같은 사업"
            feature["임의분류"] = action
            feature["원본코드"] = f"SRC-{index}"
            features.append(feature)
        source.dataProvider().addFeatures(features)
        source.updateExtents()

        project = QgsProject.instance()
        project.addMapLayer(source)
        source_group = project.layerTreeRoot().addGroup("원본")
        plugin = self.make_plugin()
        output = plugin.consolidate_heritage_layers(
            [source.id()],
            None,
            None,
            source_group,
            preservation_only=True,
            preservation_action_fields={source.id(): "임의분류"},
        )

        self.assertIsNotNone(output)
        self.assertEqual(output.featureCount(), 2)
        self.assertIn("원본코드", {field.name() for field in output.fields()})
        self.assertEqual(
            {feature["보존조치"] for feature in output.getFeatures()},
            {"현상보존", "시굴조사"},
        )

        plugin.number_heritage_v4(
            output,
            output.extent().center(),
            sort_order=0,
            extent_geom=None,
            extent_crs=output.crs(),
            buffer_geoms=[],
            restrict_to_buffer=False,
        )
        self.assertEqual(
            {feature["번호"] for feature in output.getFeatures()},
            {1},
        )

        renderer = plugin.create_preservation_action_renderer(
            output,
            0.7,
            action_styles={
                "현상보존": {
                    "fill_color": "#123456",
                    "outline_color": "#654321",
                },
            },
            opacity=0.5,
            field_name="보존조치",
        )
        categories = {
            category.label(): category for category in renderer.categories()
        }
        custom_symbol = categories["현상보존"].symbol()
        self.assertEqual(custom_symbol.color().name(), "#123456")
        self.assertEqual(
            custom_symbol.symbolLayer(0).strokeColor().name(),
            "#654321",
        )
        self.assertIn(custom_symbol.color().alpha(), (127, 128))

    def test_extent_sliver_filter_keeps_complete_small_site(self):
        source = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "주변유적",
            "memory",
        )
        source.dataProvider().addAttributes([
            QgsField("유적명", QVariant.String),
            QgsField("보존조치", QVariant.String),
        ])
        source.updateFields()

        edge_sliver = QgsFeature(source.fields())
        edge_sliver.setGeometry(QgsGeometry.fromWkt(
            "POLYGON((-1000 0,1 0,1 100,-1000 100,-1000 0))"
        ))
        edge_sliver["유적명"] = "도곽 바깥 대형 유적"
        edge_sliver["보존조치"] = "시굴조사"

        complete_small = QgsFeature(source.fields())
        complete_small.setGeometry(QgsGeometry.fromWkt(
            "POLYGON((10 10,11 10,11 11,10 11,10 10))"
        ))
        complete_small["유적명"] = "도곽 안 소형 유적"
        complete_small["보존조치"] = "표본조사"
        source.dataProvider().addFeatures([edge_sliver, complete_small])
        source.updateExtents()

        study = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "조사구역",
            "memory",
        )
        study_feature = QgsFeature(study.fields())
        study_feature.setGeometry(QgsGeometry.fromWkt(
            "POLYGON((500 500,501 500,501 501,500 501,500 500))"
        ))
        study.dataProvider().addFeature(study_feature)
        study.updateExtents()

        project = QgsProject.instance()
        project.addMapLayer(source)
        project.addMapLayer(study)
        source_group = project.layerTreeRoot().addGroup("원본")
        plugin = self.make_plugin()
        output = plugin.consolidate_heritage_layers(
            [source.id()],
            QgsGeometry.fromRect(QgsRectangle(0, 0, 1000, 1000)),
            study,
            source_group,
            exclude_extent_slivers=True,
            paper_size_mm=(200, 200),
        )

        self.assertIsNotNone(output)
        self.assertIsInstance(output, dict)
        self.assertEqual(output["suppressed"].featureCount(), 0)
        self.assertEqual(output["protection"].featureCount(), 0)
        output = output["main"]
        self.assertEqual(output.featureCount(), 1)
        self.assertEqual(
            next(output.getFeatures())["유적명"],
            "도곽 안 소형 유적",
        )

        preservation_output = plugin.consolidate_heritage_layers(
            [source.id()],
            QgsGeometry.fromRect(QgsRectangle(0, 0, 1000, 1000)),
            study,
            source_group,
            preservation_only=True,
            preservation_action_fields={source.id(): "보존조치"},
            exclude_extent_slivers=True,
            paper_size_mm=(200, 200),
        )
        self.assertIsNotNone(preservation_output)
        self.assertEqual(preservation_output.featureCount(), 1)
        self.assertEqual(
            next(preservation_output.getFeatures())["유적명"],
            "도곽 안 소형 유적",
        )


if __name__ == "__main__":
    unittest.main()
