import json
import sys
import unittest
from pathlib import Path


try:
    from .metric_context import (
        MetricContext,
        MetricContextError,
        QGIS_AVAILABLE,
        local_utm_authid,
        local_utm_epsg,
        utm_zone_for_longitude,
    )
except ImportError:
    from metric_context import (
        MetricContext,
        MetricContextError,
        QGIS_AVAILABLE,
        local_utm_authid,
        local_utm_epsg,
        utm_zone_for_longitude,
    )


class LocalUtmSelectionTests(unittest.TestCase):
    def test_selects_northern_and_southern_utm_codes(self):
        self.assertEqual(local_utm_epsg(127.1, 36.45), 32652)
        self.assertEqual(local_utm_authid(151.2, -33.9), "EPSG:32756")

    def test_handles_antimeridian_zone_boundaries(self):
        self.assertEqual(utm_zone_for_longitude(-180), 1)
        self.assertEqual(utm_zone_for_longitude(180), 60)
        self.assertEqual(utm_zone_for_longitude(0), 31)

    def test_uses_conventional_norway_and_svalbard_zones(self):
        self.assertEqual(local_utm_epsg(6.0, 60.0), 32632)
        self.assertEqual(local_utm_epsg(15.0, 78.0), 32633)
        self.assertEqual(local_utm_epsg(27.0, 78.0), 32635)

    def test_rejects_non_finite_and_polar_coordinates(self):
        for longitude, latitude in ((181, 0), (0, 85), (0, -81), (float("nan"), 0)):
            with self.subTest(longitude=longitude, latitude=latitude):
                with self.assertRaises(MetricContextError):
                    local_utm_epsg(longitude, latitude)


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python runtime is not available")
class MetricContextQgisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from qgis.core import QgsApplication

        cls.app = QgsApplication.instance() or QgsApplication([], False)
        cls.app.initQgis()

    def setUp(self):
        from qgis.core import QgsProject

        QgsProject.instance().clear()

    def test_keeps_valid_projected_metre_source_unchanged(self):
        from qgis.core import QgsCoordinateReferenceSystem

        source = QgsCoordinateReferenceSystem("EPSG:5186")
        context = MetricContext.create(source)

        self.assertEqual(context.source_crs.authid(), "EPSG:5186")
        self.assertEqual(context.analysis_crs.authid(), "EPSG:5186")
        self.assertEqual(context.output_crs.authid(), "EPSG:5186")
        self.assertEqual(context.selection_method, "source_projected_metre_crs")

    def test_derives_local_utm_for_geographic_source(self):
        context = MetricContext.create("EPSG:4326", (127.1, 36.45))

        self.assertEqual(context.analysis_crs.authid(), "EPSG:32652")
        self.assertEqual(context.output_crs.authid(), "EPSG:4326")
        self.assertEqual(context.selection_method, "centroid_local_utm")
        self.assertAlmostEqual(context.centroid_wgs84[0], 127.1, places=7)
        self.assertAlmostEqual(context.centroid_wgs84[1], 36.45, places=7)

    def test_derives_utm_for_non_metric_projected_source(self):
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsPointXY,
            QgsProject,
            QgsUnitTypes,
        )

        source = QgsCoordinateReferenceSystem("EPSG:2263")
        self.assertNotEqual(source.mapUnits(), QgsUnitTypes.DistanceMeters)
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        point = QgsCoordinateTransform(
            wgs84,
            source,
            QgsProject.instance().transformContext(),
        ).transform(QgsPointXY(-74.0, 40.7))

        context = MetricContext.create(source, point)

        self.assertEqual(context.analysis_crs.authid(), "EPSG:32618")

    def test_from_single_point_layer_uses_its_zero_area_extent(self):
        from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

        layer = QgsVectorLayer("Point?crs=EPSG:4326", "single point", "memory")
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt("POINT(127.1 36.45)"))
        layer.dataProvider().addFeature(feature)
        layer.updateExtents()

        context = MetricContext.from_layer(layer)

        self.assertEqual(context.analysis_crs.authid(), "EPSG:32652")

    def test_invalid_or_nonmetric_analysis_crs_is_rejected(self):
        from qgis.core import QgsCoordinateReferenceSystem

        with self.assertRaises(MetricContextError):
            MetricContext.create(QgsCoordinateReferenceSystem())
        with self.assertRaises(MetricContextError):
            MetricContext.create("EPSG:4326")
        with self.assertRaises(MetricContextError):
            MetricContext.create(
                "EPSG:5186",
                analysis_crs="EPSG:4326",
            )

    def test_distance_area_extent_and_buffer_are_metric(self):
        from qgis.core import QgsGeometry, QgsPointXY, QgsRectangle

        context = MetricContext.create("EPSG:5186")
        rectangle = QgsRectangle(200000, 450000, 200100, 450050)
        geometry = QgsGeometry.fromRect(rectangle)

        self.assertAlmostEqual(
            context.distance_m(
                QgsPointXY(200000, 450000),
                QgsPointXY(200003, 450004),
            ),
            5.0,
            places=6,
        )
        self.assertAlmostEqual(context.area_m2(geometry), 5000.0, places=6)
        self.assertEqual(context.extent_dimensions_m(rectangle), (100.0, 50.0))

        buffered = context.buffer_m(geometry, 10, segments=8)
        self.assertTrue(buffered.contains(geometry))
        self.assertGreater(buffered.area(), geometry.area())
        # QgsGeometry is implicitly shared; the source geometry must not change.
        self.assertAlmostEqual(geometry.area(), 5000.0, places=6)

    def test_geographic_geometry_is_transformed_before_measurement(self):
        from qgis.core import QgsGeometry, QgsPointXY

        context = MetricContext.create("EPSG:4326", (127.1, 36.45))
        first = QgsPointXY(127.1, 36.45)
        second = QgsPointXY(127.101, 36.45)

        distance = context.distance_m(first, second)
        self.assertGreater(distance, 80.0)
        self.assertLess(distance, 100.0)
        polygon = QgsGeometry.fromWkt(
            "POLYGON((127.1 36.45,127.101 36.45,127.101 36.451,"
            "127.1 36.451,127.1 36.45))"
        )
        self.assertGreater(context.area_m2(polygon), 9000.0)
        self.assertLess(context.area_m2(polygon), 11000.0)

    def test_same_real_world_geometry_has_stable_metric_results_across_crs(self):
        """Lock the JOSS cross-CRS measurement acceptance tolerances.

        All source representations are measured in one explicit analysis CRS.
        This isolates coordinate/unit conversion accuracy from the legitimate
        scale and axis-convergence differences between projected CRSs.
        """
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsGeometry,
            QgsProject,
            QgsUnitTypes,
        )

        analysis_crs = QgsCoordinateReferenceSystem("EPSG:32652")
        canonical = QgsGeometry.fromWkt(
            "POLYGON((331950 4035950,332150 4035950,"
            "332150 4036070,331950 4036070,331950 4035950))"
        )
        foot_crs = QgsCoordinateReferenceSystem()
        self.assertTrue(
            foot_crs.createFromProj(
                "+proj=utm +zone=52 +datum=WGS84 +units=ft "
                "+no_defs +type=crs"
            )
        )
        self.assertTrue(foot_crs.isValid())
        self.assertEqual(foot_crs.mapUnits(), QgsUnitTypes.DistanceFeet)

        source_crs_by_name = {
            "EPSG:4326": QgsCoordinateReferenceSystem("EPSG:4326"),
            "EPSG:5179": QgsCoordinateReferenceSystem("EPSG:5179"),
            "EPSG:5186": QgsCoordinateReferenceSystem("EPSG:5186"),
            "custom projected feet": foot_crs,
        }
        transform_context = QgsProject.instance().transformContext()
        measurements = {}

        for name, source_crs in source_crs_by_name.items():
            with self.subTest(source_crs=name):
                source_geometry = QgsGeometry(canonical)
                source_geometry.transform(
                    QgsCoordinateTransform(
                        analysis_crs,
                        source_crs,
                        transform_context,
                    )
                )
                context = MetricContext.create(
                    source_crs,
                    analysis_crs=analysis_crs,
                    transform_context=transform_context,
                )
                metric_geometry = context.to_analysis_geometry(source_geometry)
                width_m, height_m = context.extent_dimensions_m(source_geometry)
                buffered = context.buffer_m(
                    source_geometry,
                    100.0,
                    segments=32,
                )
                source_bounds = metric_geometry.boundingBox()
                buffer_bounds = buffered.boundingBox()
                measured_buffer_distances = (
                    source_bounds.xMinimum() - buffer_bounds.xMinimum(),
                    buffer_bounds.xMaximum() - source_bounds.xMaximum(),
                    source_bounds.yMinimum() - buffer_bounds.yMinimum(),
                    buffer_bounds.yMaximum() - source_bounds.yMaximum(),
                )

                self.assertLessEqual(abs(width_m - 200.0), 0.01)
                self.assertLessEqual(abs(height_m - 120.0), 0.01)
                for measured_distance in measured_buffer_distances:
                    self.assertLessEqual(
                        abs(measured_distance - 100.0),
                        0.1,
                    )
                measurements[name] = {
                    "width_m": width_m,
                    "height_m": height_m,
                    "buffer_distances_m": measured_buffer_distances,
                    "buffer_area_m2": buffered.area(),
                }

        buffer_areas = [
            values["buffer_area_m2"]
            for values in measurements.values()
        ]
        relative_area_difference = (
            max(buffer_areas) - min(buffer_areas)
        ) / min(buffer_areas)
        self.assertLessEqual(relative_area_difference, 0.005)

    def test_output_transform_and_provenance_are_explicit(self):
        from qgis.core import QgsGeometry

        context = MetricContext.create(
            "EPSG:4326",
            (127.1, 36.45),
            output_crs="EPSG:5179",
        )
        source = QgsGeometry.fromWkt("POINT(127.1 36.45)")
        metric = context.to_analysis_geometry(source)
        output = context.to_output_geometry(source)
        self.assertGreater(metric.asPoint().x(), 100000.0)
        self.assertGreater(output.asPoint().x(), 100000.0)

        provenance = context.provenance()
        json.dumps(provenance)
        self.assertEqual(provenance["source_crs"]["authid"], "EPSG:4326")
        self.assertEqual(provenance["analysis_crs"]["authid"], "EPSG:32652")
        self.assertEqual(provenance["output_crs"]["authid"], "EPSG:5179")
        self.assertEqual(
            provenance["analysis_selection"]["method"],
            "centroid_local_utm",
        )
        self.assertTrue(
            provenance["analysis_selection"]["metric_guarantee"]
        )


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python runtime is not available")
class MetricContextDialogQgisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from qgis.core import QgsApplication

        cls.app = QgsApplication.instance() or QgsApplication([], False)
        cls.app.initQgis()
        plugin_parent = str(Path(__file__).resolve().parent.parent)
        if plugin_parent not in sys.path:
            sys.path.insert(0, plugin_parent)

        from ArchDistribution.arch_distribution_dialog import (
            ANALYSIS_CRS_DEFINITION_PREF_KEY,
            ANALYSIS_CRS_OVERRIDE_PREF_KEY,
            ArchDistributionDialog,
        )

        cls.dialog_class = ArchDistributionDialog
        cls.preference_keys = (
            ANALYSIS_CRS_OVERRIDE_PREF_KEY,
            ANALYSIS_CRS_DEFINITION_PREF_KEY,
        )

    def setUp(self):
        from qgis.PyQt.QtCore import QSettings
        from qgis.core import QgsProject

        QgsProject.instance().clear()
        settings = QSettings()
        self.saved_preferences = {
            key: (settings.contains(key), settings.value(key))
            for key in self.preference_keys
        }
        for key in self.preference_keys:
            settings.remove(key)

    def tearDown(self):
        from qgis.PyQt.QtCore import QSettings
        from qgis.core import QgsProject

        settings = QSettings()
        for key, (existed, value) in self.saved_preferences.items():
            if existed:
                settings.setValue(key, value)
            else:
                settings.remove(key)
        QgsProject.instance().clear()

    def test_automatic_metric_crs_is_default_for_both_workflows(self):
        dialog = self.dialog_class()
        self.addCleanup(dialog.close)

        self.assertFalse(dialog.chkOverrideAnalysisCrs.isChecked())
        self.assertFalse(dialog.projectionAnalysisCrs.isEnabled())
        dialog.workflowTabs.setCurrentIndex(0)
        self.assertIsNone(dialog.get_settings()["analysis_crs_authid"])
        dialog.workflowTabs.setCurrentIndex(1)
        self.assertIsNone(dialog.get_settings()["analysis_crs_authid"])

    def test_projected_metre_override_is_returned_in_settings(self):
        from qgis.core import QgsCoordinateReferenceSystem

        dialog = self.dialog_class()
        self.addCleanup(dialog.close)
        dialog.chkOverrideAnalysisCrs.setChecked(True)
        dialog.projectionAnalysisCrs.setCrs(
            QgsCoordinateReferenceSystem("EPSG:5186")
        )

        self.assertTrue(dialog.projectionAnalysisCrs.isEnabled())
        self.assertEqual(
            dialog.get_settings()["analysis_crs_authid"],
            "EPSG:5186",
        )
        self.assertIsNone(dialog._analysis_crs_override_error())

    def test_geographic_override_is_rejected_before_processing(self):
        from qgis.core import QgsCoordinateReferenceSystem

        dialog = self.dialog_class()
        self.addCleanup(dialog.close)
        dialog.chkOverrideAnalysisCrs.setChecked(True)
        dialog.projectionAnalysisCrs.setCrs(
            QgsCoordinateReferenceSystem("EPSG:4326")
        )

        self.assertEqual(
            dialog.get_settings()["analysis_crs_authid"],
            "EPSG:4326",
        )
        self.assertIsNotNone(dialog._analysis_crs_override_error())


if __name__ == "__main__":
    unittest.main()
