from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, QVariant
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import (QgsProject, QgsVectorLayer, QgsGeometry, QgsFeature, 
                       QgsField, QgsDistanceArea, QgsUnitTypes, QgsPointXY)

import os.path
import processing

from .arch_distribution_dialog import ArchDistributionDialog

class ArchDistribution:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = QCoreApplication.translate('ArchDistribution', '&ArchDistribution')
        self.toolbar = None

    def initGui(self):
        # Create toolbar if it doesn't exist
        if not self.toolbar:
            self.toolbar = self.iface.addToolBar('ArchDistribution')
            self.toolbar.setObjectName('ArchDistribution')

        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.add_action(
            icon_path,
            text=QCoreApplication.translate('ArchDistribution', 'Cultural Heritage Distribution Map'),
            callback=self.run,
            parent=self.iface.mainWindow())

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
        
        # Remove toolbar
        if self.toolbar:
            del self.toolbar

    def add_action(self, icon_path, text, callback, enabled_flag=True, add_to_menu=True, add_to_toolbar=True, status_tip=None, parent=None):
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip:
            action.setStatusTip(status_tip)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)
        return action

    def run(self):
        """Run the plugin main dialog."""
        dlg = ArchDistributionDialog()
        if dlg.exec_():
            settings = dlg.get_settings()
            self.process_distribution_map(settings)

    def process_distribution_map(self, settings):
        """Core logic to process layers, buffers, and numbering."""
        self.iface.messageBar().pushMessage("ArchDistribution", "작업을 시작합니다...", level=0)
        
        try:
            # 1. Load Study Area
            study_layer = QgsProject.instance().mapLayer(settings['study_area_id'])
            if not study_layer:
                QMessageBox.critical(None, "오류", "조사지역 레이어를 찾을 수 없습니다.")
                return

            # 2. Load Topo Maps
            for topo_path in settings['topo_files']:
                layer = QgsVectorLayer(topo_path, os.path.basename(topo_path), "ogr")
                if layer.isValid():
                    QgsProject.instance().addMapLayer(layer)

            # 3. Generate Buffers
            for distance in settings['buffers']:
                self.create_buffer(study_layer, distance)

            # 4. Calculate Extent (Centered on Study Area)
            centroid = self.get_study_area_centroid(study_layer)
            if not centroid:
                QMessageBox.warning(None, "경고", "조사지역의 중심점을 계산할 수 없습니다.")
                return
            
            extent_geom = self.create_extent_polygon(centroid, settings['paper_width'], settings['paper_height'], settings['scale'])

            # 5. Load & Number Heritage Sites
            if settings['heritage_files']:
                self.process_heritage_numbering(
                    settings['heritage_files'], 
                    extent_geom, 
                    centroid, 
                    settings['sort_order']
                )
            
            self.iface.messageBar().pushMessage("ArchDistribution", "작업이 완료되었습니다.", level=0)
            
            # Zoom to extent
            if extent_geom:
                self.iface.mapCanvas().setExtent(extent_geom.boundingBox())
                self.iface.mapCanvas().refresh()

        except Exception as e:
            QMessageBox.critical(None, "오류", f"작업 중 오류 발생: {str(e)}")
            import traceback
            print(traceback.format_exc())

    def create_buffer(self, layer, distance):
        params = {
            'INPUT': layer,
            'DISTANCE': distance,
            'SEGMENTS': 50,
            'END_CAP_STYLE': 0,
            'JOIN_STYLE': 0,
            'MITER_LIMIT': 2,
            'DISSOLVE': False,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }
        result = processing.run("native:buffer", params)
        buffer_layer = result['OUTPUT']
        buffer_layer.setName(f"Buffer_{distance}m")
        QgsProject.instance().addMapLayer(buffer_layer)

    def get_study_area_centroid(self, layer):
        """Calculate the unified centroid of the study area layer."""
        features = list(layer.getFeatures())
        if not features:
            return None
        
        # Merge all geometries to find the center of the whole study area
        combined_geom = QgsGeometry()
        for feat in features:
            if combined_geom.isNull():
                combined_geom = feat.geometry()
            else:
                combined_geom = combined_geom.combine(feat.geometry())
        
        return combined_geom.centroid().asPoint()

    def create_extent_polygon(self, centroid, width_mm, height_mm, scale):
        """Create a rectangle polygon based on paper size and scale."""
        if not centroid:
            return None
            
        # Real world dimensions in meters
        width_m = (width_mm / 1000.0) * scale
        height_m = (height_mm / 1000.0) * scale
        
        half_w = width_m / 2.0
        half_h = height_m / 2.0
        
        # Create corners
        p1 = (centroid.x() - half_w, centroid.y() + half_h) # Top Left
        p2 = (centroid.x() + half_w, centroid.y() + half_h) # Top Right
        p3 = (centroid.x() + half_w, centroid.y() - half_h) # Bottom Right
        p4 = (centroid.x() - half_w, centroid.y() - half_h) # Bottom Left
        
        rect_geom = QgsGeometry.fromPolygonXY([[
            QgsPointXY(p1[0], p1[1]),
            QgsPointXY(p2[0], p2[1]),
            QgsPointXY(p3[0], p3[1]),
            QgsPointXY(p4[0], p4[1]),
            QgsPointXY(p1[0], p1[1])
        ]])

        # Create a memory layer for the extent
        vl = QgsVectorLayer("Polygon?crs=EPSG:5186", "Map_Extent", "memory") # Using common Korean CRS as default, should ideally match project
        # In a real tool, we would detect CRS from study area
        
        pr = vl.dataProvider()
        feat = QgsFeature()
        feat.setGeometry(rect_geom)
        pr.addFeatures([feat])
        vl.updateExtents()
        
        QgsProject.instance().addMapLayer(vl)
        return rect_geom

    def process_heritage_numbering(self, heritage_layer_paths, extent_geom, centroid, sort_order):
        """Load heritage layers and number sites within extent."""
        for path in heritage_layer_paths:
            layer = QgsVectorLayer(path, os.path.basename(path), "ogr")
            if not layer.isValid():
                continue
            
            # Add a field for numbering if it doesn't exist
            res = layer.dataProvider().addAttributes([QgsField("Dist_No", QVariant.Int)])
            layer.updateFields()
            
            idx = layer.fields().indexFromName("Dist_No")
            
            # Collect features within extent
            features_to_number = []
            for feat in layer.getFeatures():
                if feat.geometry().intersects(extent_geom):
                    # Calculate metric for sorting
                    if sort_order == 0: # Proximity
                        val = feat.geometry().centroid().asPoint().sqrDist(centroid)
                    else: # Top to Bottom
                        val = -feat.geometry().centroid().asPoint().y() # Negative Y for descending
                    
                    features_to_number.append({'feat': feat, 'sort_val': val})
            
            # Sort
            features_to_number.sort(key=lambda x: x['sort_val'])
            
            # Apply numbers
            layer.startEditing()
            for i, item in enumerate(features_to_number):
                feat_id = item['feat'].id()
                layer.changeAttributeValue(feat_id, idx, i + 1)
            layer.commitChanges()
            
            QgsProject.instance().addMapLayer(layer)
