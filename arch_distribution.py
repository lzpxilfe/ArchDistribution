from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, QVariant
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import (QgsProject, QgsVectorLayer, QgsGeometry, QgsFeature, 
                       QgsField, QgsDistanceArea, QgsUnitTypes, QgsPointXY,
                       QgsLineSymbol, QgsSingleSymbolRenderer, QgsFeatureRequest,
                       QgsFillSymbol)

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
        self.iface.messageBar().pushMessage("ArchDistribution", "지표 작업 및 도면 생성을 시작합니다...", level=0)
        
        try:
            # 1. Load Study Area
            study_layer = QgsProject.instance().mapLayer(settings['study_area_id'])
            if not study_layer:
                QMessageBox.critical(None, "오류", "조사지역 레이어를 찾을 수 없습니다.")
                return

            # Apply Study Area Symbology
            self.apply_study_style(study_layer, settings['study_style'])

            # 2. Merge & Style Topo Maps
            if settings['topo_layer_ids']:
                self.merge_and_style_topo(settings['topo_layer_ids'])

            # 3. Generate Buffers
            for distance in settings['buffers']:
                self.create_buffer(study_layer, distance)

            # 4. Calculate Extent (Centered on Study Area)
            centroid = self.get_study_area_centroid(study_layer)
            if not centroid:
                QMessageBox.warning(None, "경고", "조사지역의 중심점을 계산할 수 없습니다.")
                return
            
            extent_geom = self.create_extent_polygon(centroid, settings['paper_width'], settings['paper_height'], settings['scale'])

            # 5. Style & Number Heritage Sites
            if settings['heritage_layer_ids']:
                self.process_heritage_numbering_v2(
                    settings['heritage_layer_ids'], 
                    extent_geom, 
                    centroid, 
                    settings['sort_order'],
                    study_layer,
                    settings['heritage_style']
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

    def merge_and_style_topo(self, layer_ids):
        """Merge selected topo layers and apply 0.05mm black style."""
        layers = [QgsProject.instance().mapLayer(lid) for lid in layer_ids if QgsProject.instance().mapLayer(lid)]
        if not layers:
            return

        # Merge
        params = {
            'LAYERS': layers,
            'CRS': layers[0].crs(),
            'OUTPUT': 'memory:Merged_Topo'
        }
        result = processing.run("native:mergevectorlayers", params)
        merged_layer = result['OUTPUT']
        merged_layer.setName("수치지형도_병합")

        # Boundary filtering (H0017334)
        boundary_code = "H0017334"
        fields = [f.name() for f in merged_layer.fields()]
        target_field = None
        for f in fields:
            if f.upper() in ['LAYER', 'REFNAME', 'NAME']:
                target_field = f
                break
        
        if target_field:
            expr = f"\"{target_field}\" = '{boundary_code}'"
            merged_layer.startEditing()
            ids_to_delete = [f.id() for f in merged_layer.getFeatures(QgsFeatureRequest().setFilterExpression(expr))]
            if ids_to_delete:
                merged_layer.deleteFeatures(ids_to_delete)
            merged_layer.commitChanges()

        # Styling
        symbol = QgsLineSymbol.createSimple({'color': '0,0,0,255', 'width': '0.05', 'width_unit': 'MM'})
        renderer = QgsSingleSymbolRenderer(symbol)
        merged_layer.setRenderer(renderer)
        merged_layer.triggerRepaint()

        QgsProject.instance().addMapLayer(merged_layer)

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
        vl = QgsVectorLayer("Polygon?crs=EPSG:5186", "Map_Extent", "memory") 
        
        pr = vl.dataProvider()
        feat = QgsFeature()
        feat.setGeometry(rect_geom)
        pr.addFeatures([feat])
        vl.updateExtents()
        
        QgsProject.instance().addMapLayer(vl)
        return rect_geom

    def apply_study_style(self, layer, style):
        """Apply outline style to study area."""
        symbol = None
        if layer.geometryType() == 2: # Polygon
            symbol = QgsFillSymbol.createSimple({
                'color': '0,0,0,0', # Transparent fill
                'outline_color': style['stroke_color'],
                'outline_width': str(style['stroke_width']),
                'outline_width_unit': 'MM'
            })
        elif layer.geometryType() == 1: # Line
            symbol = QgsLineSymbol.createSimple({
                'color': style['stroke_color'],
                'width': str(style['stroke_width']),
                'width_unit': 'MM'
            })
        
        if symbol:
            renderer = QgsSingleSymbolRenderer(symbol)
            layer.setRenderer(renderer)
            layer.triggerRepaint()

    def process_heritage_numbering_v2(self, heritage_layer_ids, extent_geom, centroid, sort_order, study_layer, style):
        """Number sites outside study area and apply symbology."""
        
        # Merge study area geometries for fast intersection check
        study_geom = QgsGeometry()
        for f in study_layer.getFeatures():
            if study_geom.isNull(): study_geom = f.geometry()
            else: study_geom = study_geom.combine(f.geometry())

        for lid in heritage_layer_ids:
            layer = QgsProject.instance().mapLayer(lid)
            if not layer or layer.type() != 0:
                continue
            
            # Apply Symbology
            self.apply_heritage_style(layer, style)

            # Add field
            if layer.fields().indexFromName("Dist_No") == -1:
                layer.startEditing()
                layer.addAttribute(QgsField("Dist_No", QVariant.Int))
                layer.commitChanges()
            
            idx = layer.fields().indexFromName("Dist_No")
            
            # Filter features: 1. Inside Extent, 2. Outside Study Area
            features_to_number = []
            for feat in layer.getFeatures():
                geom = feat.geometry()
                if geom.intersects(extent_geom):
                    # Check if IT IS NOT inside study area
                    # If heritage is a polygon, we check if it is NOT completely within study area
                    # or if its centroid is not in study area for simplicity
                    is_inside_study = geom.within(study_geom) if not study_geom.isNull() else False
                    
                    if not is_inside_study:
                        if sort_order == 0: # Proximity
                            val = geom.centroid().asPoint().sqrDist(centroid)
                        else: # Top to Bottom
                            val = -geom.centroid().asPoint().y()
                        
                        features_to_number.append({'feat': feat, 'sort_val': val})
            
            # Sort & Label
            features_to_number.sort(key=lambda x: x['sort_val'])
            
            layer.startEditing()
            for i, item in enumerate(features_to_number):
                layer.changeAttributeValue(item['feat'].id(), idx, i + 1)
            layer.commitChanges()

    def apply_heritage_style(self, layer, style):
        """Apply complex symbology to heritage layer."""
        rgb_fill = QColor(style['fill_color'])
        rgba_fill = f"{rgb_fill.red()},{rgb_fill.green()},{rgb_fill.blue()},{int(style['opacity'] * 255)}"
        
        symbol = None
        if layer.geometryType() == 2: # Polygon
            symbol = QgsFillSymbol.createSimple({
                'color': rgba_fill,
                'outline_color': style['stroke_color'],
                'outline_width': str(style['stroke_width']),
                'outline_width_unit': 'MM'
            })
        elif layer.geometryType() == 1: # Line
            symbol = QgsLineSymbol.createSimple({
                'color': style['stroke_color'],
                'width': str(style['stroke_width']),
                'width_unit': 'MM'
            })
        
        if symbol:
            renderer = QgsSingleSymbolRenderer(symbol)
            layer.setRenderer(renderer)
            layer.triggerRepaint()
