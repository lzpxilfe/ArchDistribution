from qgis.PyQt import QtCore
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
        self.dlg = ArchDistributionDialog()
        # Connect the run signal to the processing method
        self.dlg.run_requested.connect(self.process_distribution_map)
        self.dlg.exec_()

    def log(self, message):
        """Log a message to the dialog log window and QGIS message bar."""
        if hasattr(self, 'dlg') and self.dlg:
            self.dlg.log(f"[{QtCore.QDateTime.currentDateTime().toString('hh:mm:ss')}] {message}")
        print(f"ArchDistribution: {message}")

    def process_distribution_map(self, settings):
        """Core logic with logging, progress, and heritage merging."""
        # Disable button to prevent double execution
        self.dlg.btnRun.setEnabled(False)
        self.log("작업을 시작합니다...")
        
        # 0. Setup Progress Dialog
        total_steps = 10 
        progress = QProgressDialog("데이터를 처리하는 중입니다...", "중단", 0, total_steps, self.iface.mainWindow())
        progress.setWindowModality(Qt.WindowModal)
        progress.setWindowTitle("ArchDistribution 진행률")
        progress.setMinimumDuration(0)
        progress.setValue(0)
        
        try:
            current_step = 0
            
            # Step 1: Groups
            self.log("레이어 그룹 설정 중...")
            root = QgsProject.instance().layerTreeRoot()
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
            self.log("조사구역 레이어 로드 중...")
            study_layer = QgsProject.instance().mapLayer(settings['study_area_id'])
            if not study_layer:
                self.log("오류: 조사지역 레이어를 찾을 수 없습니다.")
                return

            self.fix_layer_encoding(study_layer)
            self.apply_study_style(study_layer, settings['study_style'])
            self.move_layer_to_group(study_layer, src_group)
            current_step += 1
            progress.setValue(current_step)

            # Step 3: Topo Merge
            if settings['topo_layer_ids']:
                self.log(f"수치지형도 병합 시작 ({len(settings['topo_layer_ids'])}매)...")
                try:
                    self.merge_and_style_topo(settings['topo_layer_ids'], topo_merged_group, src_group)
                    self.log("수치지형도 병합 및 스타일 적용 완료.")
                except Exception as e:
                    self.log(f"경고: 지형도 병합 중 일부 데이터 건립 오류 발생 (계속 진행): {str(e)}")
            current_step += 1
            progress.setValue(current_step)

            # Step 4: Centroid & Extent
            self.log("중심점 및 도곽 영역 계산 중...")
            centroid = self.get_study_area_centroid(study_layer)
            if not centroid:
                self.log("오류: 조사지역의 중심점을 계산할 수 없습니다.")
                return
            
            extent_geom = self.create_extent_polygon(centroid, settings['paper_width'], settings['paper_height'], settings['scale'], ext_group)
            self.log(f"도곽 생성 완료: {settings['paper_width']}x{settings['paper_height']} mm (1:{settings['scale']})")
            current_step += 1
            progress.setValue(current_step)

            # Step 5: Buffers
            if settings['buffers']:
                self.log(f"버퍼 생성 시작 ({len(settings['buffers'])}개)...")
                for distance in settings['buffers']:
                    if progress.wasCanceled(): break
                    self.create_buffer(study_layer, distance, buf_group)
                    self.log(f"{distance}m 버퍼 생성 완료.")
                current_step += 1
                progress.setValue(current_step)

            # Step 6: Heritage Consolidation & Numbering
            if settings['heritage_layer_ids']:
                self.log("주변 유적 데이터 수집 및 병합 시작...")
                merged_heritage = self.consolidate_heritage_layers(
                    settings['heritage_layer_ids'], 
                    extent_geom, 
                    study_layer, 
                    src_group
                )
                
                if merged_heritage:
                    self.log(f"유적 병합 완료 ({merged_heritage.featureCount()}개소). 번호 부여 중...")
                    self.number_heritage_v4(merged_heritage, centroid, settings['sort_order'])
                    self.log("유적 번호 부여 완료. 스타일 및 라벨 적용 중...")
                    self.apply_heritage_style(merged_heritage, settings['heritage_style'])
                    
                    QgsProject.instance().addMapLayer(merged_heritage, False)
                    her_group.addLayer(merged_heritage)
                    self.log("최종 결과 유적 레이어 등록 완료.")
                else:
                    self.log("알림: 영역 내에 수집된 유적이 없습니다.")
            
            current_step = total_steps
            progress.setValue(current_step)
            
            # Zoom to extent
            self.iface.mapCanvas().setExtent(extent_geom.boundingBox())
            self.iface.mapCanvas().refresh()
            self.log("모든 작업이 성공적으로 완료되었습니다.")
            self.iface.messageBar().pushMessage("ArchDistribution", "작업 완료", level=0)

        except Exception as e:
            self.log(f"치명적 오류 발생: {str(e)}")
            import traceback
            self.log(traceback.format_exc())
            QMessageBox.critical(self.dlg, "오류", f"작업 중 오류 발생: {str(e)}")
        finally:
            self.dlg.btnRun.setEnabled(True)
            if 'progress' in locals():
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

    def find_field(self, layer, keywords):
        """Find a field name by looking for keywords (case-insensitive fuzzy match)."""
        fields = [f.name() for f in layer.fields()]
        for k in keywords:
            for f in fields:
                if k.upper() in f.upper():
                    return f
        return None

    def consolidate_heritage_layers(self, heritage_layer_ids, extent_geom, study_layer, src_group):
        """Merge selected heritage layers and filter by extent and study area."""
        temp_layers = []
        
        # Merge study area geometries for fast intersection check
        study_geom = QgsGeometry()
        for f in study_layer.getFeatures():
            if study_geom.isNull(): study_geom = f.geometry()
            else: study_geom = study_geom.combine(f.geometry())

        target_crs = study_layer.crs()

        for lid in heritage_layer_ids:
            layer = QgsProject.instance().mapLayer(lid)
            if not layer or layer.type() != 0: continue
            
            self.log(f"데이터 수취 및 필드 맵핑 중: {layer.name()}")
            self.fix_layer_encoding(layer)
            
            # Identify fields (Fuzzy matching)
            name_field = self.find_field(layer, ['유적명', '명칭', 'NAME', 'SITE', 'TITLE'])
            addr_field = self.find_field(layer, ['주소', '지번', '소재지', 'ADDR', 'LOC'])
            area_field = self.find_field(layer, ['면적', 'AREA', 'SHAPE_AREA'])

            # Detect geometry type
            geom_type_str = ""
            if layer.geometryType() == 0: geom_type_str = "Point"
            elif layer.geometryType() == 1: geom_type_str = "LineString"
            elif layer.geometryType() == 2: geom_type_str = "Polygon"
            
            # Create a standardized subset layer
            subset_layer = QgsVectorLayer(f"{geom_type_str}?crs={target_crs.authid()}", f"Sub_{layer.name()}", "memory")
            subset_pr = subset_layer.dataProvider()
            
            # Define standard fields
            standard_fields = [
                QgsField("유적명", QVariant.String),
                QgsField("주소", QVariant.String),
                QgsField("면적_m2", QVariant.Double),
                QgsField("원본레이어", QVariant.String) # Source layer name
            ]
            subset_pr.addAttributes(standard_fields)
            subset_layer.updateFields()
            
            # Reproject if necessary
            do_reproject = layer.crs() != target_crs
            if do_reproject:
                from qgis.core import QgsCoordinateTransform
                transform = QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance())

            new_features = []
            for feat in layer.getFeatures():
                geom = feat.geometry()
                if do_reproject:
                    geom.transform(transform)
                
                if geom.intersects(extent_geom):
                    is_inside_study = geom.within(study_geom) if not study_geom.isNull() else False
                    if not is_inside_study:
                        new_feat = QgsFeature(subset_layer.fields())
                        new_feat.setGeometry(geom)
                        
                        # Map attributes
                        new_feat["유적명"] = feat[name_field] if name_field else "N/A"
                        new_feat["주소"] = feat[addr_field] if addr_field else "N/A"
                        
                        # Area logic: if source has area use it, otherwise calculate from geometry
                        if area_field and feat[area_field]:
                            new_feat["면적_m2"] = float(feat[area_field])
                        else:
                            new_feat["면적_m2"] = geom.area() if layer.geometryType() == 2 else 0.0
                        
                        new_feat["원본레이어"] = layer.name()
                        new_features.append(new_feat)
            
            if new_features:
                subset_pr.addFeatures(new_features)
                temp_layers.append(subset_layer)
            
            self.move_layer_to_group(layer, src_group)

        if not temp_layers: return None

        # Merge all subsets
        self.log("최종 데이터 병합 처리 중...")
        params = {
            'LAYERS': temp_layers,
            'CRS': target_crs,
            'OUTPUT': 'memory:Consolidated_Heritage'
        }
        result = processing.run("native:mergevectorlayers", params)
        final_layer = result['OUTPUT']
        final_layer.setName("수집_및_병합된_주변유적")

        # Add No field for numbering
        if final_layer.fields().indexFromName("번호") == -1:
            final_layer.startEditing()
            final_layer.addAttribute(QgsField("번호", QVariant.Int))
            final_layer.commitChanges()

        return final_layer

    def number_heritage_v4(self, layer, centroid, sort_order):
        """Sort features and assign numbers to '번호' field."""
        idx = layer.fields().indexFromName("번호")
        features_to_sort = []
        for feat in layer.getFeatures():
            geom = feat.geometry()
            if sort_order == 0: # Proximity
                val = geom.centroid().asPoint().sqrDist(centroid)
            else: # Top to Bottom
                val = -geom.centroid().asPoint().y()
            features_to_sort.append({'feat': feat, 'sort_val': val})
        
        features_to_sort.sort(key=lambda x: x['sort_val'])
        
        layer.startEditing()
        for i, item in enumerate(features_to_sort):
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
            layer.triggerRepaint()

        # Labeling for '번호'
        label_settings = QgsPalLayerSettings()
        label_settings.fieldName = "번호"
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
