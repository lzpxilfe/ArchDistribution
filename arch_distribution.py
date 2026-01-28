from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, QVariant, Qt
from qgis.PyQt.QtGui import QIcon, QColor, QFont
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QProgressDialog
from qgis.core import (QgsProject, QgsVectorLayer, QgsGeometry, QgsFeature, 
                       QgsField, QgsDistanceArea, QgsUnitTypes, QgsPointXY,
                       QgsLineSymbol, QgsSingleSymbolRenderer, QgsFeatureRequest,
                       QgsFillSymbol, QgsLayerTreeGroup, QgsLayerTreeLayer,
                       QgsPalLayerSettings, QgsTextFormat, QgsVectorLayerSimpleLabeling)

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
        """Core logic to process layers, multi-layer, and numbering with progress bar."""
        
        # 0. Setup Progress Dialog
        total_steps = 1 + len(settings['buffers']) + 2 + (len(settings['heritage_layer_ids']) if settings['heritage_layer_ids'] else 0)
        progress = QProgressDialog("데이터를 처리하는 중입니다...", "중단", 0, total_steps, self.iface.mainWindow())
        progress.setWindowModality(Qt.WindowModal)
        progress.setWindowTitle("ArchDistribution 진행률")
        progress.setMinimumDuration(0)
        progress.setValue(0)
        
        try:
            current_step = 0
            
            # Step 1: Groups
            progress.setLabelText("레이어 그룹을 생성하고 있습니다...")
            root = QgsProject.instance().layerTreeRoot()
            
            # Remove existing groups if they exist
            existing_out = root.findGroup("ArchDistribution_결과물")
            if existing_out: root.removeChildNode(existing_out)
            existing_src = root.findGroup("ArchDistribution_원본_데이터")
            if existing_src: root.removeChildNode(existing_src)

            out_group = root.insertGroup(0, "ArchDistribution_결과물")
            ext_group = out_group.addGroup("01_도곽_및_영역")
            her_group = out_group.addGroup("02_유적_현황")
            buf_group = out_group.addGroup("03_조사구역_버퍼")
            topo_merged_group = out_group.addGroup("04_수치지형도_병합")
            src_group = root.addGroup("ArchDistribution_원본_데이터")
            current_step += 1
            progress.setValue(current_step)

            # Step 2: Study Area
            progress.setLabelText("조사구역 정보를 읽어오고 있습니다...")
            study_layer = QgsProject.instance().mapLayer(settings['study_area_id'])
            if not study_layer:
                QMessageBox.critical(None, "오류", "조사지역 레이어를 찾을 수 없습니다.")
                return

            self.fix_layer_encoding(study_layer)
            self.apply_study_style(study_layer, settings['study_style'])
            self.move_layer_to_group(study_layer, src_group)
            current_step += 1
            progress.setValue(current_step)

            # Step 3: Topo Merge
            if settings['topo_layer_ids']:
                progress.setLabelText(f"수치지형도 {len(settings['topo_layer_ids'])}매를 병합하고 있습니다...")
                try:
                    self.merge_and_style_topo(settings['topo_layer_ids'], topo_merged_group, src_group)
                except Exception as e:
                    self.iface.messageBar().pushMessage("ArchDistribution", f"지형도 병합 중 오류(데이터 부족 등)가 발생했으나 계속 진행합니다: {str(e)}", level=1)
            current_step += 1
            progress.setValue(current_step)

            # Step 4: Buffers
            for distance in settings['buffers']:
                if progress.wasCanceled(): break
                progress.setLabelText(f"{distance}m 버퍼를 생성하고 있습니다...")
                self.create_buffer(study_layer, distance, buf_group)
                current_step += 1
                progress.setValue(current_step)

            # Step 5: Extent
            progress.setLabelText("도각 및 출력이미지 영역을 계산하고 있습니다...")
            centroid = self.get_study_area_centroid(study_layer)
            if centroid:
                extent_geom = self.create_extent_polygon(centroid, settings['paper_width'], settings['paper_height'], settings['scale'], ext_group)
                
                # Step 6: Heritage Numbering
                if settings['heritage_layer_ids']:
                    for i, lid in enumerate(settings['heritage_layer_ids']):
                        if progress.wasCanceled(): break
                        progress.setLabelText(f"유적 레이어({i+1}/{len(settings['heritage_layer_ids'])}) 정보를 처리하고 있습니다...")
                        self.process_heritage_numbering_v3(
                            [lid], 
                            extent_geom, 
                            centroid, 
                            settings['sort_order'],
                            study_layer,
                            settings['heritage_style'],
                            her_group,
                            src_group
                        )
                        current_step += 1
                        progress.setValue(current_step)
                
                # Zoom to extent
                self.iface.mapCanvas().setExtent(extent_geom.boundingBox())
                self.iface.mapCanvas().refresh()
            
            progress.setValue(total_steps)
            self.iface.messageBar().pushMessage("ArchDistribution", "모든 작업이 완료되었습니다.", level=0)

        except Exception as e:
            QMessageBox.critical(None, "오류", f"작업 중 오류 발생: {str(e)}")
            import traceback
            print(traceback.format_exc())
        finally:
            progress.close()

    def move_layer_to_group(self, layer, group):
        """Move an existing layer to a specific group."""
        root = QgsProject.instance().layerTreeRoot()
        layer_node = root.findLayer(layer.id())
        if layer_node:
            clone = layer_node.clone()
            group.addChildNode(clone)
            layer_node.parent().removeChildNode(layer_node)

    def fix_layer_encoding(self, layer, encoding='CP949'):
        """Force specific encoding to fix broken Korean characters."""
        if layer and layer.type() == 0: # VectorLayer
            layer.setProviderEncoding(encoding)
            layer.dataProvider().setEncoding(encoding)
            # Reload to apply
            layer.triggerRepaint()

    def merge_and_style_topo(self, layer_ids, target_group, src_group):
        """Merge selected topo layers and apply 0.05mm black style."""
        layers = []
        for lid in layer_ids:
            layer = QgsProject.instance().mapLayer(lid)
            if layer:
                self.fix_layer_encoding(layer)
                layers.append(layer)
                self.move_layer_to_group(layer, src_group)
        
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

        QgsProject.instance().addMapLayer(merged_layer, False)
        target_group.addLayer(merged_layer)

    def create_buffer(self, layer, distance, group):
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
        QgsProject.instance().addMapLayer(buffer_layer, False)
        group.addLayer(buffer_layer)

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

    def create_extent_polygon(self, centroid, width_mm, height_mm, scale, group):
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
        vl = QgsVectorLayer("Polygon?crs=EPSG:5186", "도곽_Extent", "memory") 
        
        pr = vl.dataProvider()
        feat = QgsFeature()
        feat.setGeometry(rect_geom)
        pr.addFeatures([feat])
        vl.updateExtents()
        
        QgsProject.instance().addMapLayer(vl, False)
        group.addLayer(vl)
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

    def process_heritage_numbering_v3(self, heritage_layer_ids, extent_geom, centroid, sort_order, study_layer, style, target_group, src_group):
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
            
            # Fix Encoding
            self.fix_layer_encoding(layer)

            # Move to source group (we might use a copy instead if user wants, but request says "group old ones")
            # Let's clone for the result group and move original to source group
            # Actually, per user request "묶어두면 좋겠어" for old ones.
            self.move_layer_to_group(layer, target_group) # Move to top results for now as it's modified

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
        """Apply complex symbology and labeling to heritage layer."""
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

        # Labeling for Dist_No
        label_settings = QgsPalLayerSettings()
        label_settings.fieldName = "Dist_No"
        label_settings.enabled = True
        
        text_format = QgsTextFormat()
        text_format.setFont(QFont("Arial", 10, QFont.Bold))
        text_format.setColor(QColor(0, 0, 0)) # Black text
        
        # Add a buffer (halo) to labels for readability
        from qgis.core import QgsTextBufferSettings
        buffer_settings = QgsTextBufferSettings()
        buffer_settings.setEnabled(True)
        buffer_settings.setSize(0.7)
        buffer_settings.setColor(QColor(255, 255, 255)) # White halo
        text_format.setBuffer(buffer_settings)
        
        label_settings.setFormat(text_format)
        
        # Placement
        if layer.geometryType() == 2: # Polygon
            label_settings.placement = QgsPalLayerSettings.Horizontal
        else:
            label_settings.placement = QgsPalLayerSettings.AroundPoint
            
        layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
        layer.setLabelsEnabled(True)
        
        layer.triggerRepaint()
