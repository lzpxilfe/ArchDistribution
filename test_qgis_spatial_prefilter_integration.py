import sys
import unittest
from pathlib import Path


try:
    from qgis.PyQt.QtCore import QVariant
    from qgis.core import (
        QgsApplication,
        QgsCoordinateTransform,
        QgsFeature,
        QgsFeatureRequest,
        QgsField,
        QgsGeometry,
        QgsProject,
        QgsRectangle,
        QgsVectorLayer,
    )

    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


if QGIS_AVAILABLE:
    class RequestRecordingVectorLayer(QgsVectorLayer):
        """Memory layer which records how callers request its features."""

        def __init__(self, uri, name):
            super().__init__(uri, name, "memory")
            self.feature_requests = []

        def getFeatures(self, request=QgsFeatureRequest()):
            rect = request.filterRect()
            self.feature_requests.append({
                "has_filter_rect": not rect.isNull(),
                "filter_type": int(request.filterType()),
            })
            return super().getFeatures(request)


    class SingleFullScanVectorLayer(RequestRecordingVectorLayer):
        """Reject repeated unfiltered scans while allowing indexed lookups."""

        def __init__(self, uri, name):
            super().__init__(uri, name)
            self.full_scan_count = 0

        def getFeatures(self, request=QgsFeatureRequest()):
            rect = request.filterRect()
            is_unfiltered = (
                rect.isNull()
                and request.filterType() == QgsFeatureRequest.FilterNone
            )
            if is_unfiltered:
                self.full_scan_count += 1
                if self.full_scan_count > 1:
                    raise AssertionError(
                        "The Zone layer was fully scanned more than once"
                    )
            return super().getFeatures(request)


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python runtime is not available")
class QgisSpatialPrefilterIntegrationTests(unittest.TestCase):
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
        from ArchDistribution.heritage_matching import ROLE_OTHER

        Processing.initialize()
        cls.plugin_class = ArchDistribution
        cls.other_role = ROLE_OTHER

    def setUp(self):
        QgsProject.instance().clear()

    def make_plugin(self):
        plugin = self.plugin_class.__new__(self.plugin_class)
        plugin.log = lambda _message: None
        return plugin

    @staticmethod
    def add_polygon_fields(layer, rows):
        layer.dataProvider().addAttributes([
            QgsField("NAME", QVariant.String),
            QgsField("PROJECT", QVariant.String),
        ])
        layer.updateFields()

        features = []
        for row in rows:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromWkt(row["wkt"]))
            feature["NAME"] = row["name"]
            feature["PROJECT"] = row.get("project", "")
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        return layer

    def make_source(self, rows, crs="EPSG:3857", recording=False):
        layer_class = (
            RequestRecordingVectorLayer if recording else QgsVectorLayer
        )
        if recording:
            layer = layer_class(
                f"Polygon?crs={crs}",
                "heritage_source",
            )
        else:
            layer = layer_class(
                f"Polygon?crs={crs}",
                "heritage_source",
                "memory",
            )
        return self.add_polygon_fields(layer, rows)

    @staticmethod
    def make_study(crs, bounds):
        layer = QgsVectorLayer(
            f"Polygon?crs={crs}",
            "study_area",
            "memory",
        )
        feature = QgsFeature(layer.fields())
        feature.setGeometry(
            QgsGeometry.fromRect(QgsRectangle(*bounds))
        )
        layer.dataProvider().addFeature(feature)
        layer.updateExtents()
        return layer

    def consolidate(self, source, extent, study, zone=None):
        project = QgsProject.instance()
        project.addMapLayer(study)
        project.addMapLayer(source)
        if zone is not None:
            project.addMapLayer(zone)
        source_group = project.layerTreeRoot().addGroup(
            f"source_{source.id()}"
        )

        result = self.make_plugin().consolidate_heritage_layers(
            [source.id()],
            extent,
            study,
            source_group,
            zone_layer=zone,
            source_roles={source.id(): self.other_role},
            matching_decision_provider=lambda candidates: candidates,
        )
        self.assertIsNotNone(result)
        return result["main"]

    def test_extent_prefilter_excludes_many_outside_features(self):
        rows = [
            {
                "name": f"outside-{index}",
                "wkt": (
                    f"POLYGON(({10000 + index * 2} 10000,"
                    f"{10001 + index * 2} 10000,"
                    f"{10001 + index * 2} 10001,"
                    f"{10000 + index * 2} 10001,"
                    f"{10000 + index * 2} 10000))"
                ),
            }
            for index in range(1000)
        ]
        rows.extend([
            {
                "name": "inside-a",
                "wkt": "POLYGON((10 10,20 10,20 20,10 20,10 10))",
            },
            {
                "name": "inside-b",
                "wkt": "POLYGON((70 70,80 70,80 80,70 80,70 70))",
            },
        ])
        source = self.make_source(rows, recording=True)
        study = self.make_study("EPSG:3857", (40, 40, 60, 60))
        extent = QgsGeometry.fromRect(QgsRectangle(0, 0, 100, 100))

        output = self.consolidate(source, extent, study)

        self.assertEqual(output.featureCount(), 2)
        self.assertEqual(
            {feature["SRC_NAME"] for feature in output.getFeatures()},
            {"inside-a", "inside-b"},
        )
        self.assertTrue(
            any(
                request["has_filter_rect"]
                for request in source.feature_requests
            ),
            "The source layer must be queried with the map extent rectangle",
        )
        self.assertTrue(
            all(
                request["has_filter_rect"]
                for request in source.feature_requests
            ),
            "The source layer must not also be scanned without an extent",
        )

    def test_equivalent_source_in_different_crs_has_same_result(self):
        source_geometry = QgsGeometry.fromWkt(
            "POLYGON((-0.0005 -0.0005,0.0005 -0.0005,"
            "0.0005 0.0005,-0.0005 0.0005,-0.0005 -0.0005))"
        )
        transform = QgsCoordinateTransform(
            QgsProject.instance().crs().fromEpsgId(4326),
            QgsProject.instance().crs().fromEpsgId(3857),
            QgsProject.instance(),
        )
        transformed_geometry = QgsGeometry(source_geometry)
        transformed_geometry.transform(transform)

        geographic = self.make_source(
            [{"name": "same-site", "wkt": source_geometry.asWkt()}],
            crs="EPSG:4326",
        )
        projected = self.make_source(
            [{"name": "same-site", "wkt": transformed_geometry.asWkt()}],
            crs="EPSG:3857",
        )
        study = self.make_study("EPSG:3857", (-10, -10, 10, 10))
        extent = QgsGeometry.fromRect(
            QgsRectangle(-100, -100, 100, 100)
        )

        geographic_output = self.consolidate(
            geographic,
            extent,
            study,
        )
        projected_output = self.consolidate(
            projected,
            extent,
            study,
        )

        self.assertEqual(geographic_output.crs().authid(), "EPSG:3857")
        self.assertEqual(projected_output.crs().authid(), "EPSG:3857")
        self.assertEqual(geographic_output.featureCount(), 1)
        self.assertEqual(projected_output.featureCount(), 1)
        geographic_result = next(geographic_output.getFeatures()).geometry()
        projected_result = next(projected_output.getFeatures()).geometry()
        symmetric_difference = geographic_result.symDifference(
            projected_result
        )
        self.assertLess(symmetric_difference.area(), 1e-4)

    def test_feature_crossing_extent_boundary_is_clipped_and_kept(self):
        source = self.make_source([
            {
                "name": "inside",
                "wkt": "POLYGON((10 10,20 10,20 20,10 20,10 10))",
            },
            {
                "name": "crossing",
                "wkt": "POLYGON((90 40,110 40,110 60,90 60,90 40))",
            },
            {
                "name": "outside",
                "wkt": "POLYGON((101 10,111 10,111 20,101 20,101 10))",
            },
        ])
        study = self.make_study("EPSG:3857", (40, 40, 60, 60))
        extent = QgsGeometry.fromRect(QgsRectangle(0, 0, 100, 100))

        output = self.consolidate(source, extent, study)

        by_name = {
            feature["SRC_NAME"]: feature
            for feature in output.getFeatures()
        }
        self.assertEqual(set(by_name), {"inside", "crossing"})
        crossing = by_name["crossing"].geometry()
        self.assertAlmostEqual(crossing.boundingBox().xMaximum(), 100.0)
        self.assertAlmostEqual(crossing.area(), 200.0)

    def test_zone_index_preserves_overlap_values_without_rescanning(self):
        source = self.make_source([
            {
                "name": "site-a",
                "wkt": "POLYGON((0 0,10 0,10 10,0 10,0 0))",
            },
            {
                "name": "site-b",
                "wkt": "POLYGON((20 0,30 0,30 10,20 10,20 0))",
            },
            {
                "name": "site-c",
                "wkt": "POLYGON((40 0,50 0,50 10,40 10,40 0))",
            },
        ])
        zone = SingleFullScanVectorLayer(
            "Polygon?crs=EPSG:3857",
            "zone_layer",
        )
        self.add_polygon_fields(zone, [
            {
                "name": "A",
                "wkt": "POLYGON((-2 -2,6 -2,6 12,-2 12,-2 -2))",
            },
            {
                "name": "B",
                "wkt": "POLYGON((5 -2,12 -2,12 12,5 12,5 -2))",
            },
            {
                "name": "C",
                "wkt": "POLYGON((18 -2,32 -2,32 12,18 12,18 -2))",
            },
            {
                "name": "far-away",
                "wkt": (
                    "POLYGON((1000 1000,1010 1000,1010 1010,"
                    "1000 1010,1000 1000))"
                ),
            },
        ])
        study = self.make_study("EPSG:3857", (60, 60, 70, 70))
        extent = QgsGeometry.fromRect(QgsRectangle(-5, -5, 55, 15))

        output = self.consolidate(source, extent, study, zone=zone)

        zone_field = output.fields().at(6).name()
        values_by_name = {
            feature["SRC_NAME"]: feature[zone_field]
            for feature in output.getFeatures()
        }
        self.assertEqual(values_by_name["site-a"], "A, B")
        self.assertEqual(values_by_name["site-b"], "C")
        self.assertFalse(values_by_name["site-c"])
        self.assertEqual(zone.full_scan_count, 1)


if __name__ == "__main__":
    unittest.main()
