from qgis.PyQt import QtCore
from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, QVariant, Qt
from qgis.PyQt.QtGui import QIcon, QColor, QFont
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QProgressDialog
from qgis.core import (QgsProject, QgsVectorLayer, QgsGeometry, QgsFeature, 
                       QgsField, QgsDistanceArea, QgsUnitTypes, QgsPointXY,
                       QgsLineSymbol, QgsSingleSymbolRenderer, QgsFeatureRequest,
                       QgsFillSymbol, QgsLayerTreeGroup, QgsLayerTreeLayer,
                       QgsPalLayerSettings, QgsTextFormat, QgsVectorLayerSimpleLabeling,
                       QgsCategorizedSymbolRenderer, QgsRendererCategory,
                       QgsCoordinateTransform, QgsWkbTypes)

import os.path
import processing
import datetime

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
            # Only add to our custom toolbar (not both)
            if self.toolbar:
                self.toolbar.addAction(action)
            else:
                self.iface.addToolBarIcon(action)  # Fallback to standard toolbar

        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)
        return action

    def run(self):
        """Run the plugin main dialog."""
        print("🚀 ArchDistribution Version 1.0.0 LOADED (Robust Mode with File Reload)")
        self.dlg = ArchDistributionDialog()
        # Connect the run signal to the processing method
        self.dlg.run_requested.connect(self.process_distribution_map)
        self.dlg.renumber_requested.connect(self.process_renumbering)
        self.dlg.scan_requested.connect(self.perform_scan) # [NEW]
        self.dlg.exec_()

    def log(self, message):
        """Log a message to the dialog log window, QGIS message bar, and file."""
        import datetime
        timestamp = datetime.datetime.now().strftime('%H:%M:%S')
        full_msg = f"[{timestamp}] {message}"
        
        # 1. Dialog Log
        if hasattr(self, 'dlg') and self.dlg:
            self.dlg.log(full_msg)
            
        # 2. QGIS Console/Message Bar
        print(f"ArchDistribution: {message}")
        
        # 3. File Log (New)
        try:
            log_path = os.path.join(self.plugin_dir, 'latest_log.txt')
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(full_msg + "\n")
        except Exception as e:
            print(f"Log file error: {e}")

    def process_distribution_map(self, settings):
        """Core logic with logging, progress, and heritage merging."""
        # Initialize Log File
        try:
            log_path = os.path.join(self.plugin_dir, 'latest_log.txt')
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(f"=== ArchDistribution Log Started: {QtCore.QDateTime.currentDateTime().toString(Qt.ISODate)} ===\n")
        except:
            pass
            
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
            
            # 1-1. Output Group: Clear and recreate
            existing_out = root.findGroup("ArchDistribution_결과물")
            if existing_out: root.removeChildNode(existing_out)
            out_group = root.insertGroup(0, "ArchDistribution_결과물")
            
            # Sub-groups in specific order (Top to Bottom)
            stu_group = out_group.addGroup("00_조사구역_및_표제")
            her_group = out_group.addGroup("01_유적_현황")
            ext_group = out_group.addGroup("02_도곽_및_영역")
            buf_group = out_group.addGroup("03_조사구역_버퍼")
            topo_merged_group = out_group.addGroup("04_수치지형도_병합")
            zone_merged_group = out_group.addGroup("05_현상변경허용기준")
            
            # 1-2. Source Group: Persist (don't delete original layers!)
            src_group = root.findGroup("ArchDistribution_원본_데이터")
            if not src_group:
                src_group = root.addGroup("ArchDistribution_원본_데이터")
            
            # Hide source group by default to focus on outputs
            src_group.setItemVisibilityChecked(False)
            current_step += 1
            progress.setValue(current_step)

            # Step 2: Study Area (Clone for display)
            self.log("조사구역 처리 중...")
            original_study_layer = QgsProject.instance().mapLayer(settings['study_area_id'])
            if not original_study_layer:
                self.log("오류: 조사지역 레이어를 찾을 수 없습니다.")
                return

            # CRS Validation
            if original_study_layer.crs().isGeographic():
                 self.log("경고: 지리좌표계(도 단위) 감지됨. 정밀 계산을 위해 투영좌표계 사용을 권장합니다.")
            
            # Create a clone in memory for the results group
            study_result_layer = QgsVectorLayer(f"{'Polygon' if original_study_layer.geometryType()==2 else 'LineString'}?crs={original_study_layer.crs().toWkt()}", "00_조사구역", "memory")
            study_result_pr = study_result_layer.dataProvider()
            
            # Copy all features
            new_feats = []
            for f in original_study_layer.getFeatures():
                nf = QgsFeature(f)
                new_feats.append(nf)
            study_result_pr.addFeatures(new_feats)
            study_result_layer.updateExtents()
            
            self.apply_study_style(study_result_layer, settings['study_style'])
            QgsProject.instance().addMapLayer(study_result_layer, False)
            stu_group.addLayer(study_result_layer)
            
            # Also keep original in source group (hidden)
            self.move_layer_to_group(original_study_layer, src_group)
            current_step += 1
            progress.setValue(current_step)

            # Step 3: Topo Merge
            if settings['topo_layer_ids']:
                self.log(f"수치지형도 병합 시작 ({len(settings['topo_layer_ids'])}매)...")
                try:
                    self.merge_and_style_topo(settings['topo_layer_ids'], topo_merged_group, src_group, settings['topo_style'])
                    self.log("수치지형도 병합 및 스타일 적용 완료.")
                except Exception as e:
                    self.log(f"경고: 지형도 병합 중 일부 데이터 건립 오류 발생 (계속 진행): {str(e)}")
            current_step += 1
            progress.setValue(current_step)

            # Step 4: Centroid & Extent
            self.log("도곽(Extent) 영역 계산 중...")
            centroid = self.get_study_area_centroid(original_study_layer)
            if not centroid:
                self.log("오류: 조사지역의 데이터가 비어있거나 중심점을 계산할 수 없습니다.")
                return
            
            self.log(f"중심점 기반 도곽 생성 중 (Scale 1:{settings['scale']})...")
            extent_geom = self.create_extent_polygon(centroid, settings['paper_width'], settings['paper_height'], settings['scale'], ext_group, original_study_layer.crs())
            self.log(f"도곽 생성 완료: {settings['paper_width']}x{settings['paper_height']} mm (1:{settings['scale']})")
            current_step += 1
            progress.setValue(current_step)

            # Step 5: Buffers
            if settings['buffers']:
                self.log(f"버퍼 생성 시작 ({len(settings['buffers'])}개)...")
                for distance in settings['buffers']:
                    if progress.wasCanceled(): break
                    self.create_buffer(original_study_layer, distance, buf_group, settings['buffer_style'])
                    self.log(f"{distance}m 버퍼 생성 완료.")
                current_step += 1
                progress.setValue(current_step)

            # Step 6: Heritage Consolidation & Numbering
            if settings['heritage_layer_ids']:
                self.log("주변 유적 데이터 수집 및 병합 시작...")

                # [FIX] Pre-fetch Zone Layer and fix encoding (CP949 default)
                # User reported that this layer often has encoding issues.
                zone_layer_obj = None
                if settings.get('zone_layer_id'):
                    zone_layer_obj = QgsProject.instance().mapLayer(settings.get('zone_layer_id'))
                    if zone_layer_obj:
                         self.fix_layer_encoding(zone_layer_obj, 'CP949')

                merged_heritage = self.consolidate_heritage_layers(
                    settings['heritage_layer_ids'], 
                    extent_geom, 
                    original_study_layer, 
                    src_group,
                    filter_categories=settings.get('filter_items', None),
                    exclusion_list=settings.get('exclusion_list', []),
                    zone_layer=zone_layer_obj 
                )
                
                if merged_heritage:
                    self.log(f"병합 완료 ({merged_heritage.featureCount()}개소).")
                    
                    # [NEW] Calculate Buffer Geometries for Tiered Numbering
                    buffer_geoms = []
                    if settings['buffers']:
                         # [UX Check] Warn if Sort Order is not 'Closest'
                         if settings['sort_order'] != 1:
                             self.log("주의: 버퍼가 설정되었으나 '정렬 기준'이 '거리순'이 아닙니다. 버퍼 구간별 번호 부여가 적용되지 않습니다.")
                         else:
                             # Combine study layer geometry for buffer generation
                             combined_study = QgsGeometry()
                             for f in original_study_layer.getFeatures():
                                 if combined_study.isNull(): combined_study = f.geometry()
                                 else: combined_study = combined_study.combine(f.geometry())
                             
                             if not combined_study.isNull():
                                 # Create list of (distance, geometry) tuples, sorted by distance
                                 sorted_buffers = sorted(settings['buffers'])
                                 for dist in sorted_buffers:
                                     bg = combined_study.buffer(dist, 20)
                                     buffer_geoms.append({'dist': dist, 'geom': bg})
                                 self.log(f"버퍼 구간별 번호 부여 준비 완료 ({len(buffer_geoms)}단계).")
                    # [NEW] Pass restrict_to_buffer setting
                    self.number_heritage_v4(
                        merged_heritage, 
                        original_study_layer, 
                        settings['sort_order'], 
                        extent_geom, 
                        original_study_layer.crs(), 
                        buffer_geoms, 
                        restrict_to_buffer=settings.get('restrict_to_buffer', True)
                    )
                    self.log("유적 번호 부여 완료. 스타일 및 라벨 적용 중...")
                    self.apply_heritage_style(
                        merged_heritage, 
                        settings['heritage_style'],
                        font_size=settings.get('label_font_size', 10),
                        font_family=settings.get('label_font_family', 'Malgun Gothic')
                    )
                    
                    QgsProject.instance().addMapLayer(merged_heritage, False)
                    her_group.addLayer(merged_heritage)
                    self.log("최종 결과 유적 레이어 등록 완료.")
                    
                    # [NEW] Check Zone Layer and Add/Style it if present
                    zone_id = settings.get('zone_layer_id')
                    if zone_id:
                        z_layer = QgsProject.instance().mapLayer(zone_id)
                        if z_layer:
                            self.log("현상변경 허용구간 레이어 분할 및 스타일 적용 중... (v1.2.0 Split Active)")
                            
                            # [FIX] Use the pre-created Group 05
                            # zone_group_name = "현상변경허용기준" 
                            # (handled in Step 1)
                            
                            # [NEW] Clip to Buffer Logic
                            buffer_limit_geom = None
                            if settings.get('clip_zone_to_buffer', False) and buffer_geoms:
                                buffer_limit_geom = buffer_geoms[-1]['geom'] # Use largest buffer
                            
                            # Call Split & Style Function (with optional buffer clip)
                            self.split_and_style_zone_layer(z_layer, zone_merged_group, extent_geom, buffer_limit_geom, source_crs=original_study_layer.crs())
                            
                else:
                    self.log("알림: 영역 내에 수집된 유적이 없습니다.")
            
            current_step = total_steps
            progress.setValue(current_step)
            
            # Zoom to extent
            self.iface.mapCanvas().setExtent(extent_geom.boundingBox())
            self.iface.mapCanvas().refresh()
            self.log("모든 작업이 성공적으로 완료되었습니다.")
            
            # Notify Log File
            self.log(f"로그 파일 저장됨: {os.path.join(self.plugin_dir, 'latest_log.txt')}")
            self.iface.messageBar().pushMessage("ArchDistribution", "작업 완료", level=0)

        except Exception as e:
            self.log(f"치명적 오류 발생: {str(e)}")
            import traceback
            tb = traceback.format_exc()
            self.log(tb)
            QMessageBox.critical(self.dlg, "오류", f"작업 중 오류 발생: {str(e)}")
        finally:
            self.dlg.btnRun.setEnabled(True)
            if 'progress' in locals():
                progress.close()

    def process_renumbering(self, layer):
        """Renumber the specific layer based on current UI settings."""
        self.log(f"레이어 '{layer.name()}' 번호 새로고침 중...")
        
        try:
            # 1. Get Settings (Sort Order & Study Area)
            settings = self.dlg.get_settings()
            sort_order = settings['sort_order']
            
            # 2. Get Centroid (if needed)
            centroid = None
            study_layer = None
            if settings['study_area_id']:
                study_layer = QgsProject.instance().mapLayer(settings['study_area_id'])
                if study_layer:
                    centroid = self.get_study_area_centroid(study_layer)
            
            # [FIX] If no study layer, use layer's own extent center as centroid for extent calculation
            if not centroid:
                layer_extent = layer.extent()
                if not layer_extent.isEmpty():
                    centroid = layer_extent.center()
                    self.log("조사지역 미선택 - 현재 레이어 범위 중심 사용")
            
            if sort_order == 1 and not centroid:
                 QMessageBox.warning(self.dlg, "설정 오류", "조사지역(기준) 레이어가 선택되지 않아 '가까운 순' 정렬을 할 수 없습니다.\n기준을 변경하거나 조사지역을 다시 선택하세요.")
                 return

            # [NEW] Calculate Extent Geometry for Exclusion
            extent_geom = self.calculate_extent_geometry(
                centroid, 
                settings['paper_width'], 
                settings['paper_height'], 
                settings['scale']
            )
            
            # [NEW] Calculate Buffer Geometries (Renumbering context)
            buffer_geoms = []
            if settings.get('buffers') and study_layer:
                combined_study = QgsGeometry()
                for f in study_layer.getFeatures():
                     if combined_study.isNull(): combined_study = f.geometry()
                     else: combined_study = combined_study.combine(f.geometry())
                
                if not combined_study.isNull():
                    sorted_buffers = sorted(settings['buffers'])
                    for dist in sorted_buffers:
                        bg = combined_study.buffer(dist, 20)
                        buffer_geoms.append({'dist': dist, 'geom': bg})
                    self.log(f"버퍼 구간 적용 ({len(buffer_geoms)}단계).")

            # 3. Call Numbering Logic
            # Pass study_layer.crs() if available, else layer.crs()
            extent_crs = study_layer.crs() if study_layer else layer.crs()
            # If study_layer is missing, pass centroid as fallback
            self.number_heritage_v4(
                layer, 
                study_layer if study_layer else centroid, 
                sort_order, 
                extent_geom, 
                extent_crs, 
                buffer_geoms,
                restrict_to_buffer=settings.get('restrict_to_buffer', True)
            )
            
            # 4. Refresh & Re-Apply Style (to update font/labels)
            self.log(f"레이어 '{layer.name()}' 번호 재정렬 완료. 스타일 적용 중...")
            self.apply_heritage_style(
                layer,
                settings['heritage_style'],
                font_size=settings.get('label_font_size', 10),
                font_family=settings.get('label_font_family', 'Malgun Gothic')
            )
            
            layer.triggerRepaint()
            self.iface.mapCanvas().refresh()
            self.log(f"레이어 '{layer.name()}' 번호가 {layer.featureCount()}개로 재정렬되었습니다.")
            QMessageBox.information(self.dlg, "완료", "번호 새로고침 및 스타일 적용이 완료되었습니다.")
            
        except Exception as e:
            self.log(f"오류 발생: {str(e)}")
            QMessageBox.critical(self.dlg, "오류", f"번호 부여 중 오류가 발생했습니다: {str(e)}")

    def perform_scan(self, settings):
        """Execute smart scan and update dialog."""
        self.log("스마트 스캔 시작...")
        try:
            categories = self.scan_smart_categories(settings)
            self.dlg.update_category_list(categories)
            self.log(f"스캔 완료: {len(categories)}개 분류 발견됨.")
        except Exception as e:
            self.log(f"스캔 오류: {str(e)}")
            QMessageBox.critical(self.dlg, "오류", f"스캔 중 오류: {str(e)}")

    def move_layer_to_group(self, layer, group):
        """Move an existing layer to a specific group and hide it."""
        root = QgsProject.instance().layerTreeRoot()
        layer_node = root.findLayer(layer.id())
        if layer_node:
            # Check if it's already in the target group
            if layer_node.parent() == group:
                layer_node.setItemVisibilityChecked(False)
                return
                
            clone = layer_node.clone()
            clone.setItemVisibilityChecked(False) # Hide the original layer
            group.addChildNode(clone)
            layer_node.parent().removeChildNode(layer_node)

    def fix_layer_encoding(self, layer, encoding='CP949'):
        """Force specific encoding to fix broken Korean characters."""
        if layer and layer.type() == 0: # VectorLayer
            layer.setProviderEncoding(encoding)
            layer.dataProvider().setEncoding(encoding)
            # Reload to apply
            layer.dataProvider().reloadData()
            layer.updateFields()
            layer.triggerRepaint()

    def merge_and_style_topo(self, layer_ids, target_group, src_group, style):
        """Merge selected topo layers and apply custom style."""
        layers = []
        for lid in layer_ids:
            layer = QgsProject.instance().mapLayer(lid)
            if layer:
                # [FIX] Filter for Line Layers Only (Topo is usually lines)
                if layer.geometryType() != 1: # 0:Point, 1:Line, 2:Polygon
                    self.log(f"  ⚠️ 지형도 병합 제외 (라인 레이어 아님): {layer.name()}")
                    continue
                    
                self.fix_layer_encoding(layer)
                layers.append(layer)
                self.move_layer_to_group(layer, src_group)
        
        if not layers:
            self.log("  ⚠️ 병합할 수치지형도(라인)가 없습니다.")
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
        symbol = QgsLineSymbol.createSimple({
            'color': style['stroke_color'], 
            'width': str(style['stroke_width']), 
            'width_unit': 'MM'
        })
        renderer = QgsSingleSymbolRenderer(symbol)
        merged_layer.setRenderer(renderer)
        merged_layer.triggerRepaint()

        QgsProject.instance().addMapLayer(merged_layer, False)
        target_group.addLayer(merged_layer)

    def create_buffer(self, layer, distance, group, style):
        params = {
            'INPUT': layer,
            'DISTANCE': distance,
            'SEGMENTS': 50,
            'DISSOLVE': False,
            'OUTPUT': 'memory:Buffer_' + str(distance)
        }
        result = processing.run("native:buffer", params)
        buffer_layer = result['OUTPUT']
        buffer_layer.setName(f"Buffer_{distance}m")
        
        # Apply outline-only style with custom color and dash pattern
        # User requested: Solid, Dot, Dash (indices 0, 1, 2)
        pen_styles = ['solid', 'dot', 'dash']
        target_style = pen_styles[style['style']] if style['style'] < len(pen_styles) else 'solid'
        
        symbol = QgsFillSymbol.createSimple({
            'color': '0,0,0,0', # Transparent fill
            'outline_color': style['color'],
            'outline_width': str(style['width']), # User defined width
            'outline_style': target_style
        })
        buffer_layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        
        QgsProject.instance().addMapLayer(buffer_layer, False)
        group.addLayer(buffer_layer)

    def get_study_area_centroid(self, layer):
        """Calculate the center of the study area layer extent (Fast and Robust)."""
        extent = layer.extent()
        if extent.isEmpty() or not extent.isFinite():
            # Try getting feature count
            if layer.featureCount() == 0:
                return None
            # Fallback to manual combine if extent is weird
            combined_geom = QgsGeometry()
            for feat in layer.getFeatures():
                if feat.hasGeometry():
                    if combined_geom.isNull(): combined_geom = feat.geometry()
                    else: combined_geom = combined_geom.combine(feat.geometry())
            if combined_geom.isNull(): return None
            return combined_geom.centroid().asPoint()
            
        return extent.center()

        return extent.center()

    def calculate_extent_geometry(self, centroid, width_mm, height_mm, scale):
        """Calculate the extent geometry (rectangle) without creating a layer."""
        if not centroid: return None
        
        # Real world dimensions in meters
        width_m = (width_mm / 1000.0) * scale
        height_m = (height_mm / 1000.0) * scale
        
        half_w = width_m / 2.0
        half_h = height_m / 2.0
        
        # Create corners
        p1 = QgsPointXY(centroid.x() - half_w, centroid.y() + half_h) # Top Left
        p2 = QgsPointXY(centroid.x() + half_w, centroid.y() + half_h) # Top Right
        p3 = QgsPointXY(centroid.x() + half_w, centroid.y() - half_h) # Bottom Right
        p4 = QgsPointXY(centroid.x() - half_w, centroid.y() - half_h) # Bottom Left
        
        return QgsGeometry.fromPolygonXY([[p1, p2, p3, p4, p1]])

    def create_extent_polygon(self, centroid, width_mm, height_mm, scale, group, crs):
        """Create a rectangle polygon based on paper size and scale."""
        rect_geom = self.calculate_extent_geometry(centroid, width_mm, height_mm, scale)
        if not rect_geom: return None

        # Create a memory layer for the extent using the study layer's CRS (use WKT for maximum compatibility)
        vl = QgsVectorLayer(f"Polygon?crs={crs.toWkt()}", "도곽_Extent", "memory") 
        if not vl.isValid():
            vl = QgsVectorLayer("Polygon?crs=EPSG:5186", "도곽_Extent", "memory")
        
        # Explicit outline-only styling
        symbol = QgsFillSymbol.createSimple({
            'color': '0,0,0,0', # No fill
            'outline_color': '0,0,0,255', # Black outline
            'outline_width': '0.3'
        })
        vl.setRenderer(QgsSingleSymbolRenderer(symbol))

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

    def load_reference_data(self):
        """Load reference data for filtering."""
        import json
        json_path = os.path.join(self.plugin_dir, 'reference_data.json')
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    self.reference_data = json.load(f)
            except:
                self.reference_data = {}
        else:
            self.reference_data = {}

        # [NEW] Load Smart Patterns for Override
        json_pattern_path = os.path.join(os.path.dirname(__file__), 'smart_patterns.json')
        self.smart_patterns = {"noise": [], "artifacts": {}}
        if os.path.exists(json_pattern_path):
            try:
                with open(json_pattern_path, 'r', encoding='utf-8') as f:
                    self.smart_patterns = json.load(f)
            except:
                pass

    def should_exclude(self, name, filter_items):
        """
        Check if feature should be excluded based on name look-up.
        filter_items: List of allowed strings e.g. ["ERA:고려", "TYPE:고분"]
        If filter_items is None, Allow all.
        """
        if filter_items is None: return False # No filtering
        
        # Load data if not loaded
        if not hasattr(self, 'reference_data'):
            self.load_reference_data()
            
        if name not in self.reference_data:
            return False # Unknown items are allowed by default (or denied? Let's allow for safety)
            
        info = self.reference_data[name]
        era_key = f"ERA:{info['e']}"
        type_key = f"TYPE:{info['t']}"
        
        # [NEW] Keyword Override Logic
        # Prioritize keyword inference over DB value if a match exists.
        # This solves the "Temple Site containing Stone Buddha" issue.
        effective_type = info['t']
        if hasattr(self, 'smart_patterns'):
            refinements = self.smart_patterns.get('artifacts', {})
            for key, val in refinements.items():
                if key in name:
                    effective_type = val
                    break # Use the first matching keyword
        
        type_key = f"TYPE:{effective_type}"
        
        # Logic: 
        # If the item has an Era, and that Era is NOT in the allowed list -> Exclude
        # If the item has a Type, and that Type is NOT in the allowed list -> Exclude
        # Wait, if I uncheck "Era: Goryeo", then Goryeo items should be gone.
        # But what if I uncheck "Type: Tomb"? Then Tomb items gone.
        # Basically, we need to check if the specific Era tag is present in filter_items (if applicable)
        # AND if the specific Type tag is present in filter_items (if applicable).
        
        # However, we only emitted tags that were found.
        # So we can just check: IS the ERA present in the allowed list?
        
        # Complication: filter_items contains only CHECKED items.
        # So if era_key is valid (not '时代未详') and NOT in filter_items -> Exclude.
        
        if info['e'] and info['e'] != "시대미상":
             # Does the user care about eras? (i.e. are there any ERA tags in the list?)
             # We can assume if filter_items provided, we enforce it.
             # We need to know if "ERA:Goryeo" was presented to the user?
             # Actually, simpler: if filter_items is passed, it represents the ALLOW LIST of properties.
             # But if "ERA:Goryeo" was never in the list (not found in scan), we shouldn't block it?
             # The Dialog only adds found items.
             # So if it was found, it must be in the list?
             # Correct. 
             
             # Optimization: We assume the Dialog passed ONLY the checked items.
             # But we also need to know if the Era was even *candidate* for filtering. 
             # If "Goryeo" wasn't in the input layers, it wouldn't be in the list.
             # But here we are processing features. If this feature is Goryeo, then "ERA:Goryeo" WOULD have been found by scan?
             # YES, because we scan the same layers.
             
             if era_key not in filter_items:
                 # Check if this era key was actually available to be unchecked?
                 # If we rely on the list containing ONLY checked items, then missing item = unchecked.
                 return True

        if info['t'] and info['t'] != "기타":
             if type_key not in filter_items:
                 return True
                 
        return False

    def keyword_inference(self, name):
        """Infer category from name."""
        if not name: return "기타"
        
        # Priority mapping
        if any(k in name for k in ["고분", "분묘", "묘", "총", "릉"]): return "분묘"
        if any(k in name for k in ["산성", "성", "진", "보", "루"]): return "성곽"
        if any(k in name for k in ["요지", "가마", "생산"]): return "생산유적"
        if any(k in name for k in ["주거", "취락", "마을", "생활"]): return "생활유적"
        if any(k in name for k in ["사지", "불상", "탑", "비", "당간"]): return "불교/장묘"
        
        return "기타"

    def consolidate_heritage_layers(self, heritage_layer_ids, extent_geom, study_layer, src_group, filter_categories=None, exclusion_list=[], zone_layer=None):
        """Merge selected heritage layers and filter by extent, study area, and user exclusions. Also tags Zone."""
        """Merge selected heritage layers and filter by extent, study area, and user exclusions."""
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
            # [FIX] Broaden search to include National/State Heritage naming conventions
            name_keywords = ['유적명', '명칭', 'NAME', 'SITE', 'TITLE', '문화재명', '지정명칭', '국가유산명', '등록명칭']
            name_field = self.find_field(layer, name_keywords)
            
            # [FIX] Skip invalid layers (e.g. Topo maps selected as Heritage)
            if not name_field:
                self.log(f"  ⚠️ 명칭 필드({name_keywords}) 미확인으로 병합 제외: {layer.name()}")
                continue
                
            heritage_name_field = self.find_field(layer, ['국가유산명', '문화재명', '지정명칭']) # Keep specific for attribute extraction
            project_name_field = self.find_field(layer, ['사업명', '조사명', '공사명', 'PROJECT']) 
            addr_field = self.find_field(layer, ['주소', '지번', '소재지', 'ADDR', 'LOC'])
            area_field = self.find_field(layer, ['면적', 'AREA', 'SHAPE_AREA'])

            # [NEW] Zone Field Logic preparation
            zone_name_field = None
            if zone_layer:
                zone_name_field = self.find_field(zone_layer, ['구역', '구역명', 'NAME', 'ZONENAME', 'ZONE', 'L3_CODE', 'A_L3_CODE', 'L2_CODE'])

            # Detect geometry type
            geom_type_str = ""
            if layer.geometryType() == 0: geom_type_str = "Point"
            elif layer.geometryType() == 1: geom_type_str = "LineString"
            elif layer.geometryType() == 2: geom_type_str = "Polygon"
            
            # Create a standardized subset layer
            subset_layer = QgsVectorLayer(f"{geom_type_str}?crs={target_crs.toWkt()}", f"Sub_{layer.name()}", "memory")
            if not subset_layer.isValid():
                subset_layer = QgsVectorLayer(f"{geom_type_str}?crs={target_crs.authid()}", f"Sub_{layer.name()}", "memory")
            subset_pr = subset_layer.dataProvider()
            
            # Define standard fields (번호 comes first for report readiness)
            # [NOTE] Warnings about QgsField constructor are harmless deprecation warnings in QGIS 3.x
            standard_fields = [
                QgsField("번호", QVariant.Int),
                QgsField("유적명", QVariant.String),
                QgsField("주소", QVariant.String),
                QgsField("면적_m2", QVariant.Double),
                QgsField("국가유산명", QVariant.String), # [NEW]
                QgsField("사업명", QVariant.String),     # [NEW]
                QgsField("허용기준", QVariant.String),   # [NEW] Zone Info
                QgsField("원본레이어", QVariant.String)
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
                if not feat.hasGeometry(): continue
                
                geom = feat.geometry()
                if do_reproject:
                    geom.transform(transform)
                
                # Retrieve Attributes for filtering
                val_name = feat[name_field] if name_field else ""

                # [NEW] Check Exclusion List (Specific Blacklist)
                # If the name is in the user's exclusion list, skip it.
                if exclusion_list and val_name in exclusion_list:
                    # Log removed item occasionally?
                    # self.log(f"  - 사용자 제외: {val_name}")
                    continue
                
                # Check Category Filters (Legacy Reference Data)
                if self.should_exclude(val_name, filter_categories):
                    continue
                
                # Check if heritage site intersects the map extent
                if geom.intersects(extent_geom):
                    # [NEW FIX] Clip geometry to extent bounds
                    # This handles MultiPolygon features where parts are outside the extent
                    clipped_geom = geom.intersection(extent_geom)
                    if clipped_geom.isEmpty():
                        continue  # No part inside extent
                    
                    # We exclude sites that are entirely within the study area (as they are 'internal')
                    # But we include ones that overlap or are outside
                    is_entirely_inside = clipped_geom.within(study_geom) if not study_geom.isNull() else False
                    
                    if not is_entirely_inside:
                        # [FIX] Included internal sites as well (User Request: Prevent aggressive data loss)
                        # Originally: if not is_entirely_inside:
                        # Now: Allow all (since we clipped to extent already)
                        pass
                    
                    if True: # Always proceed if it intersects extent
                        new_feat = QgsFeature(subset_layer.fields())
                        new_feat.setGeometry(clipped_geom)  # Use clipped geometry
                        
                        # [NEW] Attribute Extraction
                        val_name = feat[name_field] if name_field else ""
                        val_heritage = feat[heritage_name_field] if heritage_name_field else ""
                        val_project = feat[project_name_field] if project_name_field else ""
                        val_type = feat[self.find_field(layer, ['유적종류', '종류', '성격', '구분', 'TYPE'])] if self.find_field(layer, ['유적종류', '종류', '성격', '구분', 'TYPE']) else ""

                        # [NEW] Filtering Logic
                        # 1. Smart Filter (Era/Type from JSON)
                        if self.should_exclude(val_name, filter_categories): # filter_categories is actually 'filter_items' list
                            continue

                        # Determine category for filtering (Old Logic - Deprecated but kept for safety/fallback?)
                        # Actually we can skip the old logic if we rely on the new one.
                        # But for 'VIP' status, we might still want to mark it?
                        
                        current_cat = "기타"
                        is_vip = any(k in layer.name() for k in ["국가지정", "시도지정", "등록", "지정", "문화유산"])
                        if is_vip or val_heritage:
                             current_cat = "[필수] 지정문화유산 (VIP)"
                        elif val_type and len(str(val_type)) > 1:
                             current_cat = str(val_type)
                        else:
                             current_cat = self.keyword_inference(val_name)
                        
                        # [NEW] Smart Naming Logic
                        display_name = val_name
                        if val_heritage: # National Heritage takes precedence
                            display_name = val_heritage
                            if val_name and val_name not in display_name:
                                 display_name += f" ({val_name})"
                        elif val_project: # Project name context
                             display_name = val_project
                             if val_name and val_name not in display_name:
                                  display_name += f" {val_name}"

                        # Map attributes
                        new_feat["유적명"] = display_name if display_name else "N/A"
                        new_feat["주소"] = feat[addr_field] if addr_field else "N/A"
                        new_feat["국가유산명"] = val_heritage
                        # [NEW] Zone Intersection Check
                        val_zone = ""
                        if zone_layer and zone_name_field:
                            # Iterate zones
                            # Optimization: Use spatial index if large, but usually small.
                            for z_feat in zone_layer.getFeatures():
                                if z_feat.geometry().intersects(new_feat.geometry()): # Or clipped_geom
                                    z_name = z_feat[zone_name_field]
                                    if z_name:
                                        if val_zone: val_zone += ", " + str(z_name) # Handle overlap
                                        else: val_zone = str(z_name)
                                    # Usually features don't overlap much in zones, but lines might.
                        
                        # Map attributes
                        new_feat["유적명"] = display_name if display_name else "N/A"
                        new_feat["주소"] = feat[addr_field] if addr_field else "N/A"
                        new_feat["국가유산명"] = val_heritage
                        new_feat["사업명"] = val_project
                        new_feat["허용기준"] = val_zone if val_zone else None
                        
                        # Area logic
                        if area_field and feat[area_field]:
                            try:
                                new_feat["면적_m2"] = float(feat[area_field])
                            except:
                                new_feat["면적_m2"] = geom.area() if layer.geometryType() == 2 else 0.0
                        else:
                            new_feat["면적_m2"] = geom.area() if layer.geometryType() == 2 else 0.0
                        
                        new_feat["원본레이어"] = layer.name()
                        new_features.append(new_feat)
            
            if new_features:
                self.log(f"  -> {len(new_features)}개소 수집됨.")
                subset_pr.addFeatures(new_features)
                temp_layers.append(subset_layer)
            else:
                self.log("  -> 영역 내 수집된 유적 없음.")
            
            self.move_layer_to_group(layer, src_group)

        if not temp_layers: return None

        # Merge subsets grouped by geometry type (native:mergevectorlayers prefers uniform types)
        # We'll merge everything into one if possible, but separate results are safer for display
        # For simplicity and export-readiness, we'll try to merge all, but warn if mixed.
        
        self.log("최종 데이터 병합 처리 중...")
        params = {
            'LAYERS': temp_layers,
            'CRS': target_crs,
            'OUTPUT': 'memory:Consolidated_Heritage'
        }
        # In QGIS 3, this creates a layer with the type of the first layer.
        # To be safe, we'll just use it and rely on the fact that most are Polygons.
        result = processing.run("native:mergevectorlayers", params)
        merged_layer = result['OUTPUT']
        
        # [NEW] Dissolve by Name to prevent duplicate numbering for same-site polygons
        self.log("동일 유적 병합 처리 중 (Dissolve by Name)...")
        
        # 1. Identify Name Field in Merged Layer
        fields = [f.name() for f in merged_layer.fields()]
        name_field = None
        keywords = ['유적명', '명칭', '명', '이름', 'NAME', 'SITE', 'TITLE']
        for f in fields:
            for k in keywords:
                if k in f.upper():
                    name_field = f
                    break
            if name_field: break
        
        if not name_field:
            self.log("  ⚠️ 병합 레이어에서 명칭 필드를 찾을 수 없어 Dissolve를 건너뜁니다.")
            return merged_layer

        self.log(f"  - Dissolve 기준 필드: {name_field}")

        # [NEW] Normalize Names (Smart Cleaning) to ensure correct dissolving
        # 1. Strip Whitespace
        # 2. Extract real name if it contains "지표조사" or "발굴조사" (User feedback: long project name + site name)
        merged_layer.startEditing()
        name_idx = merged_layer.fields().indexOf(name_field)
        
        split_keywords = ["지표조사", "발굴조사", "시굴조사", "표본조사", "정밀조사", "입회조사"]
        
        # [FIX] Disabled Aggressive Name Cleaning (User Request)
        # Reason: "Site A (Survey)" and "Site A (Excavation)" were being merged into "Site A", causing data loss.
        # for f in merged_layer.getFeatures():
        #      val = f[name_idx]
        #      if isinstance(val, str):
        #          clean_val = val.strip()
        #          
        #          # Logic: Split by keyword, take the LAST part if length > 1
        #          # e.g., "Project A 지표조사 Site B" -> " Site B" -> "Site B"
        #          for kw in split_keywords:
        #              if kw in clean_val:
        #                  parts = clean_val.split(kw)
        #                  if len(parts) > 1:
        #                      candidate = parts[-1].strip()
        #                      # Check if candidate is valid (not empty and not just "2" or "1"?)
        #                      # Actually usually it is "Site Name 1", so it's fine.
        #                      if len(candidate) > 1:
        #                          clean_val = candidate
        #                          break # Stop after first keyword match
        #          
        #          if clean_val != val:
        #              merged_layer.changeAttributeValue(f.id(), name_idx, clean_val)
        merged_layer.commitChanges()
        merged_layer.commitChanges()

        try:
            dissolve_params = {
                'INPUT': merged_layer,
                'FIELD': [name_field], # Use dynamic name field
                'OUTPUT': 'memory:Dissolved_Heritage'
            }
            dissolve_result = processing.run("native:dissolve", dissolve_params)
            final_layer = dissolve_result['OUTPUT']
            final_layer.setName("수집_및_병합된_주변유적")
            
            # [CRITICAL] Ensure '유적명' field exists for later usage (numbering/labelling)
            # Rename the dynamic name field to '유적명' if it isn't already
            if name_field != '유적명':
                # We can't easily rename in memory layer without processing.
                # But our numbering logic looks for '유적명' or similar? 
                # Actually number_heritage_v4 doesn't read the name, it just writes ID.
                # But 'arch_distribution_dialog' scan might need it.
                pass

            self.log(f"Dissolve 완료: {merged_layer.featureCount()} -> {final_layer.featureCount()}개 유적")
        except Exception as e:
            self.log(f"Dissolve 실패 (원본 사용): {e}")
            final_layer = merged_layer
            final_layer.setName("수집_및_병합된_주변유적")

        return final_layer


    def number_heritage_v4(self, layer, study_layer_or_centroid, sort_order, extent_geom=None, extent_crs=None, buffer_geoms=[], restrict_to_buffer=True):
        """
        Sort features and assign numbers to '번호' field with Buffer Tiers.
        
        Args:
            study_layer_or_centroid: QgsVectorLayer of study area OR QgsPointXY (fallback).
            buffer_geoms: List of dicts [{'dist': 100, 'geom': QgsGeometry}, ...]. Sorted by distance.
            restrict_to_buffer (bool): If True, exclude features outside max buffer (set Number to NULL).
                                       If False, include them (Number them too), but buffer tiers still prioritize inners.
        """
        idx = layer.fields().indexFromName("번호")
        
        # [NEW] Check/Add Distance Field
        dist_field_name = "이격거리(m)"
        if layer.fields().indexFromName(dist_field_name) == -1:
            layer.dataProvider().addAttributes([QgsField(dist_field_name, QVariant.String)])
            
        # [NEW] Check/Add Note Field (For Human Verification)
        note_field_name = "비고"
        if layer.fields().indexFromName(note_field_name) == -1:
            layer.dataProvider().addAttributes([QgsField(note_field_name, QVariant.String)])
            
        layer.updateFields()
        dist_idx = layer.fields().indexFromName(dist_field_name)
        note_idx = layer.fields().indexFromName(note_field_name)

        # Prepare base geometry for precise distance calculation
        base_geom = None
        if isinstance(study_layer_or_centroid, QgsVectorLayer):
             # Merge study layer into one geometry
             combined = QgsGeometry()
             for f in study_layer_or_centroid.getFeatures():
                 if combined.isNull(): combined = f.geometry()
                 else: combined = combined.combine(f.geometry())
             # Transform if needed? usually assume same CRS if passed from main logic
             if combined and not combined.isNull():
                 base_geom = combined
        
        # Prepare transformation for Extent and Buffers
        target_extent = extent_geom
        transformed_buffers = []
        
        if extent_crs and layer.crs() != extent_crs:
            tr = QgsCoordinateTransform(extent_crs, layer.crs(), QgsProject.instance())
            try:
                if extent_geom:
                    target_extent = QgsGeometry(extent_geom)
                    target_extent.transform(tr)
                
                # Transform buffers
                for b in buffer_geoms:
                    bg = QgsGeometry(b['geom'])
                    bg.transform(tr)
                    
                    # Also transform base_geom if it came from study_layer (which is in extent_crs usually)
                    # Wait, study_layer is from project, likely same as extent_crs.
                    # We need base_geom in LAYER crs for distance calculation.
                    transformed_buffers.append({'dist': b['dist'], 'geom': bg})
                
                if base_geom:
                     # base_geom is from study_layer. Its CRS is study_layer.crs() which IS extent_crs.
                     # So we need to transform it to layer.crs()
                     base_geom.transform(tr)

                self.log(f"좌표 변환 적용됨: {extent_crs.authid()} -> {layer.crs().authid()}")
            except Exception as e:
                self.log(f"좌표 변환 오류 (무시됨): {e}")
        else:
            transformed_buffers = buffer_geoms # No transform needed

        # Determine Max Limit Geometry (Largest Buffer)
        limit_geom = None
        if transformed_buffers:
            limit_geom = transformed_buffers[-1]['geom'] # Last one is largest

        layer.startEditing()
        
        # Collect all features
        ids_to_delete = [] # [FIX] Initialize early to collect outside features
        all_features = []
        for feat in layer.getFeatures():
            geom = feat.geometry()
            
            # [FIX] Robust Geometry Check
            if not geom.isGeosValid():
                geom = geom.makeValid()
            
            # [CHECK 1] Extent Intersection
            if target_extent and not geom.intersects(target_extent):
                layer.changeAttributeValue(feat.id(), idx, None)
                layer.changeAttributeValue(feat.id(), dist_idx, None)
                continue
            
            # [CHECK 2] Limit Geometry (Max Buffer) Intersection
            # If buffers exist AND restriction is enabled
            if limit_geom and restrict_to_buffer: 
                if not geom.intersects(limit_geom):
                    layer.changeAttributeValue(feat.id(), idx, None)
                    layer.changeAttributeValue(feat.id(), dist_idx, None)
                    ids_to_delete.append(feat.id()) # [FIX] Mark for deletion
                    continue
            
            # If restriction is OFF, we keep it even if outside buffer.
            # However, if it's OUTSIDE buffer, it won't be in any "Tier", so it ends up in 'remaining' list.
            # That's exactly what we want.

            all_features.append(feat)
            
        if ids_to_delete:
            self.log(f"  -> 초기 스캔에서 범위 밖 유적 {len(ids_to_delete)}개 식별됨 (삭제 예정).")

        # Sorting Logic
        sorted_features = []
        
        if sort_order == 1: # Closest to Study Area (Buffer Tiered)
            # We will process in Tiers if buffers exist
            
            # Helper to calc distance
            def get_dist(feat_geom):
                if base_geom:
                    return feat_geom.distance(base_geom)
                elif isinstance(study_layer_or_centroid, QgsPointXY):
                    return feat_geom.centroid().asPoint().sqrDist(study_layer_or_centroid) # Fallback
                return 0

            # Calculate distances for ALL valid features first
            feat_dists = []
            for f in all_features:
                d = get_dist(f.geometry())
                feat_dists.append({'feat': f, 'dist': d, 'dist_str': f"{d:.1f}m"})
            
            if transformed_buffers:
                # Tiered Sorting
                # 1. Bucket features into rings
                # Ring 0: Inside Buffer 0
                # Ring 1: Inside Buffer 1 AND NOT Inside Buffer 0
                # ...
                # Actually, simpler:
                # Iterate buffers ascending. Assign feature to FIRST buffer it intersects.
                
                # Careful: 'intersects' checks geometry overlap. 
                # Distance based check is cleaner if we trust distance?
                # But polygon buffers might handle holes/islands better.
                # Let's use Geometry Intersection for robustness with complex shapes.
                
                remaining = feat_dists[:]
                tiered_result = []
                
                for b_info in transformed_buffers:
                    b_geom = b_info['geom']
                    in_this_tier = []
                    next_remaining = []
                    
                    for item in remaining:
                        # Check intersection
                        if item['feat'].geometry().intersects(b_geom):
                            in_this_tier.append(item)
                        else:
                            next_remaining.append(item)
                    
                    # Sort this tier by distance
                    in_this_tier.sort(key=lambda x: x['dist'])
                    tiered_result.extend(in_this_tier)
                    
                    remaining = next_remaining
                
                # If anything remains (shouldn't if limit_geom check worked, but floating point issues?)
                if remaining:
                    remaining.sort(key=lambda x: x['dist'])
                    tiered_result.extend(remaining)
                    
                sorted_features = tiered_result
                
            else:
                # No buffers, just pure distance sort
                feat_dists.sort(key=lambda x: x['dist'])
                sorted_features = feat_dists
                
        elif sort_order == 0: # Top-to-Bottom
             temp = [{'feat': f, 'sort_val': -f.geometry().centroid().asPoint().y(), 'dist_str': None} for f in all_features]
             temp.sort(key=lambda x: x['sort_val'])
             sorted_features = temp
             
        else: # Alphabetical
             temp = [{'feat': f, 'sort_val': f["유적명"], 'dist_str': None} for f in all_features]
             temp.sort(key=lambda x: x['sort_val'])
             sorted_features = temp

        # Assign Numbers
        # If restrict_to_buffer is True:
        #   Assign IDs 1..N to features that have a valid 'dist' (inside buffer).
        #   Assign NULL to features outside (dist is None or large, but here 'sorted_features' contains ALL).
        # Wait, sorted_features contains 'feat_dists' items.
        # If restrict_to_buffer was handled in previous logic (limit_geom check), 
        # then 'sorted_features' might still contain outside features if we didn't filter them out there.
        # Let's check `number_heritage_v4` logic:
        # It calculates distances for ALL features.
        # If buffers exist, it tiers them. 
        # But it doesn't seem to explicitly exclude outside features from 'sorted_features' list in the sorting block above, 
        # unless 'transformed_buffers' logic handles it.
        # 
        # Actually, let's look at how we handle 'restrict_to_buffer'.
        # Previously we just set a subset string.
        # To fix gaps (28, 30...), we must ensure that the sequence 1,2,3 is assigned ONLY to the visible subset.
        
        # Assign Numbers
        # [FIX] Continuous Numbering Logic
        # We must ensure that only features INSIDE the buffer (if restricted) get numbers,
        # and that the numbers are sequential (1, 2, 3...) with no gaps.
        
        # [FIX] Delete Outside Features instead of hiding
        # Collect IDs to delete
        # ids_to_delete already initialized above
        seen_names = set()
        
        # Identify Name Field for Soft Deduplication
        idx_name = layer.fields().indexOf("유적명")
        if idx_name == -1: idx_name = layer.fields().indexOf("명칭") # Fallback
        
        # 1. First Pass: Identify and Number Inside Features
        current_id = 1
        
        # [FIX] Use correctly transformed limit geometry determined above (lines 1073-1075)
        # Verify limit_geom validity with restrict_to_buffer flag
        target_limit_geom = None
        if restrict_to_buffer and limit_geom:
            target_limit_geom = limit_geom

        for item in sorted_features:
            feat = item['feat']
            
            # [REMOVED] Aggressive Name-based Deduplication
            # User reported excessive feature loss (250 -> 150).
            # We strictly trust the input layer (which may have spatial duplicates if dissolve failed, but safer to keep).

            is_inside = True
            
            if target_limit_geom:
                 if not feat.geometry().intersects(target_limit_geom):
                     is_inside = False
            
            if is_inside:
                layer.changeAttributeValue(feat.id(), idx, current_id)
                layer.changeAttributeValue(feat.id(), note_idx, None) # Clear note
                current_id += 1
            else:
                ids_to_delete.append(feat.id())
                # [FIX] Human Verification: Mark details instead of just deleting logic
                layer.changeAttributeValue(feat.id(), idx, None) # No Number
                layer.changeAttributeValue(feat.id(), note_idx, "범위_밖") # Mark reason

            if item.get('dist_str'):
                layer.changeAttributeValue(feat.id(), dist_idx, item['dist_str'])
            else:
                layer.changeAttributeValue(feat.id(), dist_idx, None)
                 
        layer.commitChanges()
        
        # 2. Hide Outside Features (Non-Destructive for Human Verification)
        if ids_to_delete:
            # removing 'delete logic'. Instead we apply filter.
            # layer.deleteFeatures(ids_to_delete)
            
            # Apply Filter to show only Numbered items
            layer.setSubsetString('"번호" IS NOT NULL')
            
            self.log(f"범위 밖 유적 {len(ids_to_delete)}개를 숨김 처리했습니다. (삭제 안함)")
            self.log(" -> 확인 방법: 레이어 우클릭 > 필터 설정 > 지우기")
        else:
             layer.setSubsetString("") # Clear any previous filter

    def apply_heritage_style(self, layer, style, font_size=10, font_family="Malgun Gothic"):
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
        # Use user-specified font
        font = QFont(font_family)
        if not font.exactMatch():
            font = QFont("Arial")
        font.setBold(True)
        font.setPointSize(font_size)
        
        text_format.setFont(font)
        text_format.setColor(QColor(0, 0, 0)) # Black text
        
        # Add a buffer (halo) - Removed for Illustrator compatibility as requested
        # (Halos often become separate complex paths in AI, solid black is easier to edit)
        from qgis.core import QgsTextBufferSettings
        buffer_settings = QgsTextBufferSettings()
        buffer_settings.setEnabled(False) # Now Disabled
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

    def apply_zone_categorical_style(self, layer):
        """Apply categorical style to Zone Layer based on '구역' or 'NAME' matching user legend."""
        field_name = self.find_field(layer, ['구역', '구역명', 'NAME', 'ZONENAME', 'ZONE', 'L3_CODE', 'A_L3_CODE', 'L2_CODE'])
        if not field_name: return

        # Exact Color Map based on User Image
        # 1, 2, 3, 4, 5, 6, 7, 8 -> Filled
        # 2-1, 2-2, 2-3, 2-4, 2-5, 2-6 -> Outline (No Brush)
        
    def split_and_style_zone_layer(self, layer, parent_group, extent_geom, limit_buffer_geom=None, source_crs=None):
        """
        Split Zone Layer into separate layers for each category, clip to extent (and buffer if requested), 
        and apply specific single-symbol style.
        """
        layer_name = layer.name()
        self.log(f"DEBUG: Zone Layer '{layer_name}' Processing Started.")
        
        # [FIX] Robust Reload: Ignore UI layer instance, reload effectively from source file
        source_path = layer.source().split("|")[0]
        
        # [FIX] Handle QGIS oddities (file.shx|layername=...) or wrong extensions
        if source_path:
            base, ext = os.path.splitext(source_path)
            if ext.lower() in ['.shx', '.dbf']:
                 source_path = base + '.shp'
        
        new_layer = None
        if source_path and os.path.exists(source_path):
             self.log(f"DEBUG: 원본 파일 경로 확인됨: {source_path}")
             # Create new layer instance strictly for processing
             layer_uri = f"{source_path}|encoding=CP949"
             new_layer = QgsVectorLayer(layer_uri, layer_name, "ogr")
             
             if new_layer.isValid():
                 self.log(f"DEBUG: 파일 재로딩 성공 (CP949). 객체 수: {new_layer.featureCount()}")
                 layer = new_layer # Replace variable
             else:
                 self.log(f"⚠️ 경고: CP949 옵션으로 불러오기 실패. 원본 레이어로 진행합니다.")
        else:
             self.log(f"⚠️ 경고: 원본 파일 경로를 찾을 수 없습니다 (Path: {source_path}). 메모리 레이어이거나 임시 파일일 수 있습니다.")
             self.log(" -> 기존 레이어에 인코딩 설정을 시도합니다.")
             self.fix_layer_encoding(layer, 'CP949')

        # 1. Identify Field
        field_name = self.find_field(layer, ['구역명', '구역', 'NAME', 'ZONENAME', 'ZONE', 'L3_CODE', 'A_L3_CODE', 'L2_CODE'])
        if not field_name: 
            self.log("❌ 오류: 구역 필드 찾기 실패.")
            self.log(f"   - 현재 인코딩: {layer.dataProvider().encoding()}")
            self.log(f"   - 발견된 필드 목록: {[f.name() for f in layer.fields()]}")
            return
        
        self.log(f"DEBUG: 타겟 필드 식별됨 -> '{field_name}'")

        # 2. Define Style Map (Updated based on User Legend)
        # 1구역 (Orange), 2구역 (Magenta) -> Filled
        # 2-X구역 -> Transparent Fill + Colored Outline
        base_map = {
            # Filled Types
            "1": {"fill": "#E67E22", "stroke": "#D35400", "width": 0.2, "style": "solid"}, # 1 (Orange)
            "2": {"fill": "#E056FD", "stroke": "#BE2EDD", "width": 0.2, "style": "solid"}, # 2 (Magenta)
            "3": {"fill": "#5D5FEF", "stroke": "#4834d4", "width": 0.2, "style": "solid"}, # 3 (Blue-Purple)
            "4": {"fill": "#C06C84", "stroke": "#A6586C", "width": 0.2, "style": "solid"}, # 4 (Rose)
            "5": {"fill": "#2ecc71", "stroke": "#27ae60", "width": 0.2, "style": "solid"}, # 5 (Green)
            "6": {"fill": "#e74c3c", "stroke": "#c0392b", "width": 0.2, "style": "solid"}, # 6 (Red)
            "7": {"fill": "#34D399", "stroke": "#1abc9c", "width": 0.2, "style": "solid"}, # 7 (Mint)
            "8": {"fill": "#f1c40f", "stroke": "#f39c12", "width": 0.2, "style": "solid"}, # 8 (Yellow)
            
            # Outline Types (2-X)
            "2-1": {"fill": "transparent", "stroke": "#0000FF", "width": 0.8, "style": "no_brush"}, # Blue
            "2-2": {"fill": "transparent", "stroke": "#008000", "width": 0.8, "style": "no_brush"}, # Green
            "2-3": {"fill": "transparent", "stroke": "#C71585", "width": 0.8, "style": "no_brush"}, # Magenta
            "2-4": {"fill": "transparent", "stroke": "#008080", "width": 0.8, "style": "no_brush"}, # Teal
            "2-5": {"fill": "transparent", "stroke": "#8B4513", "width": 0.8, "style": "no_brush"}, # Brown
            "2-6": {"fill": "transparent", "stroke": "#BDB76B", "width": 0.8, "style": "no_brush"}, # Olive
        }
        
        style_map = {}
        for k, v in base_map.items():
            style_map[k] = v
            style_map[f"{k}구역"] = v 
            style_map[f"제{k}구역"] = v
            # Handle "2-1" -> "2-1구역"
            if '-' in k:
                # Add explicit mappings if needed, though loop covers it
                pass

        # 3. Prepare Clipping Geometries
        project_crs = QgsProject.instance().crs()
        layer_crs = layer.crs()
        
        self.log(f"DEBUG: CRS Info - Zone Layer: {layer_crs.authid()}, Source (Study): {source_crs.authid()}")
        
        if not source_crs: source_crs = project_crs

        # Prepare Extent Mask
        local_extent = QgsGeometry(extent_geom)
        
        # [FIX] CRS Transformation: Transform Study Area to Zone Layer CRS if needed
        # Often user says Zone Layer is 5179 but Project is 4326/5186.
        if layer_crs != source_crs:
             self.log(f"DEBUG: CRS 불일치 감지. 변환 실행: {source_crs.authid()} -> {layer_crs.authid()}")
             xform = QgsCoordinateTransform(source_crs, layer_crs, QgsProject.instance())
             local_extent.transform(xform)
             
             # Also transform the buffer limit geometry if it exists
             if limit_buffer_geom:
                 limit_buffer_geom.transform(xform)
        else:
             self.log(f"DEBUG: CRS 일치 ({layer_crs.authid()}). 변환 건너뜀.")

        self.log(f"DEBUG: Before Transform - Extent BBox: {local_extent.boundingBox().toString()}")
        
        # Prepare Buffer Mask (Optional)
        local_buffer = None
        if limit_buffer_geom:
            local_buffer = QgsGeometry(limit_buffer_geom)
            self.log(f"DEBUG: Buffer Limit Exists.")

        # Transform both masks to Zone Layer CRS if needed
        if layer_crs != source_crs:
            try:
                tr = QgsCoordinateTransform(source_crs, layer_crs, QgsProject.instance())
                local_extent.transform(tr)
                self.log(f"DEBUG: Extent Transformed to Zone CRS.")
                if local_buffer:
                    local_buffer.transform(tr)
                    self.log(f"DEBUG: Buffer Transformed to Zone CRS.")
            except Exception as e:
                self.log(f"❌ DEBUG: 좌표계 변환 치명적 오류: {e}")
                return

        self.log(f"DEBUG: Clipping Mask Ready. Extent BBox: {local_extent.boundingBox().toString()}")

        # 4. Iterate and Split
        idx = layer.fields().indexFromName(field_name)
        if idx == -1:
             self.log(f"DEBUG: Field index error for {field_name}")
             return
             
        unique_vals = layer.uniqueValues(idx)
        self.log(f"DEBUG: Unique Values found: {len(unique_vals)}개")
        
        try:
            sorted_vals = sorted(unique_vals, key=lambda x: str(x))
        except:
            sorted_vals = unique_vals
            
        for val in sorted_vals:
            val_str = str(val).strip()
            
            # 4.1 Filter Features
            subset_feats = []
            # Optimization: Use getFeatures with expression for speed?
            # For debugging, loop is fine.
            # self.log(f"DEBUG: Processing group '{val_str}'...")
            
            for f in layer.getFeatures():
                 # Handle Nulls
                 v = f.attributes()[idx]
                 if v is None: continue
                 if str(v).strip() == val_str:
                     subset_feats.append(f)
            
            if not subset_feats: continue
            # self.log(f"   -> 원본 개수: {len(subset_feats)}")

            # 4.2 Clip Logic
            clipped_feats = []
            for f in subset_feats:
                geom = f.geometry()
                if not geom.isGeosValid(): geom = geom.makeValid()
                
                # Check Intersection with Extent First
                if geom.intersects(local_extent):
                    try:
                        res = geom.intersection(local_extent)
                        
                        # Sequential Clip: Intersect with Buffer if required
                        if not res.isEmpty() and local_buffer:
                            if res.intersects(local_buffer):
                                res = res.intersection(local_buffer)
                            else:
                                res = QgsGeometry() # Completely outside buffer

                        if not res.isEmpty():
                            # [FIX] Force MultiPolygon conversion to prevent data loss on complex clips
                            if not QgsWkbTypes.isMultiType(res.wkbType()):
                                 res.convertToMultiType()
                            
                            nf = QgsFeature(f)
                            nf.setGeometry(res)
                            clipped_feats.append(nf)
                    except Exception as e:
                         self.log(f"   -> Geometry Error: {e}")
            
            if clipped_feats:
                 self.log(f"DEBUG: Group '{val_str}' -> Clipped Final Count: {len(clipped_feats)}")
            else:
                 pass 
            
            if not clipped_feats: continue
            
            # Create Memory Layer
            # [FIX] Use authid() for safer memory layer creation if possible, to avoid WKT string issues
            crs_def = layer.crs().authid()
            if not crs_def: crs_def = layer.crs().toWkt()
            
            # [FIX] Use MultiPolygon to allow fragmented polygons (islands)
            vl = QgsVectorLayer(f"MultiPolygon?crs={crs_def}", val_str, "memory")
            if not vl.isValid():
                self.log(f"❌ 메모리 레이어 생성 실패: {val_str}")
                continue
                
            pr = vl.dataProvider()
            pr.addAttributes(layer.fields())
            vl.updateFields()
            pr.addFeatures(clipped_feats)
            vl.updateExtents()
            
            # 4.4 Apply Style
            # Find matching style
            norm_val = val_str.replace("구역", "").replace(" ", "").strip()
            style = None
            
            if val_str in style_map: style = style_map[val_str]
            elif norm_val in style_map: style = style_map[norm_val]
            else:
                 # Partial match
                 for k, v in style_map.items():
                     if k in val_str and len(k) > 1:
                         style = v; break
            
            if style:
                symbol_type = style.get('style', 'solid')
                if symbol_type == 'no_brush':
                    symbol = QgsFillSymbol.createSimple({'outline_style': 'solid', 'style': 'no_brush'})
                else:
                    symbol = QgsFillSymbol.createSimple({'outline_style': 'solid', 'style': 'solid'})
                    symbol.setColor(QColor(style['fill']))
                    # [UX] Set Opacity to 40% for better visibility of underlying map
                    symbol.setOpacity(0.4)
                
                symbol.symbolLayer(0).setStrokeColor(QColor(style['stroke']))
                symbol.symbolLayer(0).setStrokeWidth(style['width'])
                vl.setRenderer(QgsSingleSymbolRenderer(symbol))
            else:
                # Random/Default fallback
                pass 
            
            vl.triggerRepaint()
            
            # 4.5 Add to Group
            QgsProject.instance().addMapLayer(vl, False)
            parent_group.addLayer(vl)
            self.log(f"   -> 레이어 등록: {vl.name()} (ID: {vl.id()})")
            
        parent_group.setExpanded(True)
        parent_group.setItemVisibilityChecked(True)
        
        # [UX] Move original input layer to Source Group (if not already there)
        src_group = QgsProject.instance().layerTreeRoot().findGroup("ArchDistribution_원본_데이터")
        if src_group:
             self.move_layer_to_group(layer, src_group)
             self.log("   -> 원본 현상변경허용기준 레이어를 'ArchDistribution_원본_데이터' 그룹으로 이동했습니다.")

        self.log(f"  -> 현상변경 허용구간 레이어 분할 완료 ({parent_group.name()} 그룹 확인).")
