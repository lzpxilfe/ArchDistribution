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
        QgsVectorLayer,
    )

    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python runtime is not available")
class QgisBufferIntegrationTests(unittest.TestCase):
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
        from ArchDistribution.arch_distribution import (
            ArchDistribution,
            format_buffer_label,
        )

        Processing.initialize()
        cls.plugin_class = ArchDistribution
        cls.format_buffer_label = staticmethod(format_buffer_label)

    def setUp(self):
        QgsProject.instance().clear()

    @staticmethod
    def make_study_layer():
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:5186",
            "study",
            "memory",
        )
        layer.dataProvider().addAttributes([
            QgsField("SITE_NAME", QVariant.String),
            QgsField("ADDRESS", QVariant.String),
        ])
        layer.updateFields()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(
            "POLYGON((0 0,100 0,100 100,0 100,0 0))"
        ))
        feature["SITE_NAME"] = "source name must not survive"
        feature["ADDRESS"] = "source address must not survive"
        layer.dataProvider().addFeature(feature)
        return layer

    def create_buffer(self, distance, format_km_labels):
        root = QgsProject.instance().layerTreeRoot()
        group = root.addGroup("buffers")
        return self.plugin_class(None).create_buffer(
            self.make_study_layer(),
            distance,
            group,
            {
                "color": "#ff0000",
                "style": 0,
                "width": 0.3,
                "format_km_labels": format_km_labels,
            },
        )

    def test_buffer_keeps_only_numeric_distance_and_adds_km_label(self):
        layer = self.create_buffer(1500, True)

        self.assertEqual(
            [field.name() for field in layer.fields()],
            ["DIST_M"],
        )
        feature = next(layer.getFeatures())
        self.assertEqual(feature["DIST_M"], 1500.0)
        self.assertEqual(layer.name(), "Buffer_1.5km")
        self.assertTrue(layer.labelsEnabled())
        settings = layer.labeling().settings()
        self.assertTrue(settings.isExpression)
        self.assertEqual(settings.fieldName, "'1.5km'")
        self.assertEqual(
            settings.placement,
            settings.PerimeterCurved,
        )

    def test_metre_label_is_retained_when_option_is_off(self):
        layer = self.create_buffer(1500, False)
        self.assertEqual(layer.name(), "Buffer_1500m")
        self.assertEqual(layer.labeling().settings().fieldName, "'1500m'")

    def test_label_formatter_uses_km_from_exactly_one_thousand(self):
        self.assertEqual(self.format_buffer_label(999, True), "999m")
        self.assertEqual(self.format_buffer_label(1000, True), "1km")
        self.assertEqual(self.format_buffer_label(1250, True), "1.25km")
        self.assertEqual(self.format_buffer_label(1000, False), "1000m")
        self.assertEqual(
            self.format_buffer_label(1234567, True),
            "1234.567km",
        )


if __name__ == "__main__":
    unittest.main()
