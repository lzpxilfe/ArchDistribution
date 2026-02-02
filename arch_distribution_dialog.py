import os

from qgis.PyQt import uic, QtCore, QtGui
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QListWidgetItem, QColorDialog
from qgis.core import QgsProject
from qgis.utils import iface # [CRITICAL FIX] Import global iface

# This loads your .ui file so that PyQt can populate your plugin with the elements from Qt Designer
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'arch_distribution_dialog_base.ui'))

def get_plugin_version():
    """Read version from metadata.txt"""
    try:
        metadata_path = os.path.join(os.path.dirname(__file__), 'metadata.txt')
        with open(metadata_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('version='):
                    return line.strip().split('=')[1]
    except:
        pass
    return "1.0.0"  # Fallback


class ArchDistributionDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(ArchDistributionDialog, self).__init__(parent)
        self.setupUi(self) # [CRITICAL FIX] Restore UI initialization

        # [MOVED FROM HERE]
        # make_tab_scrollable logic moved to end of __init__


        # [NEW] Programmatically add missing UI elements for Smart Filter
        self.groupSmartFilter = QtWidgets.QGroupBox("유적 속성 분류")
        self.vSmartLayout = QtWidgets.QVBoxLayout()
        
        self.lSmartDesc = QtWidgets.QLabel("체크된 유적 레이어의 명칭을 분석하여 시대와 성격을 자동 분류합니다.")
        self.lSmartDesc.setStyleSheet("color: #555; font-size: 10px;")
        
        self.btnSmartScan = QtWidgets.QPushButton("속성 분류 실행")
        self.btnSmartScan.setStyleSheet("background-color: #f39c12; color: white; font-weight: bold; padding: 5px;")
        
        # Split UI into two columns
        self.hSmartLists = QtWidgets.QHBoxLayout()
        
        # Era Column
        self.vEras = QtWidgets.QVBoxLayout()
        self.lblEra = QtWidgets.QLabel("시대")
        self.lblEra.setStyleSheet("font-weight: bold; color: #333;")
        self.listEras = QtWidgets.QListWidget()
        self.listEras.setMinimumHeight(130) # Reduced from 200
        self.vEras.addWidget(self.lblEra)
        self.vEras.addWidget(self.listEras)
        
        # Type Column
        self.vTypes = QtWidgets.QVBoxLayout()
        self.lblType = QtWidgets.QLabel("성격")
        self.lblType.setStyleSheet("font-weight: bold; color: #333;")
        self.listTypes = QtWidgets.QListWidget()
        self.listTypes.setMinimumHeight(130) # Reduced from 200
        self.vTypes.addWidget(self.lblType)
        self.vTypes.addWidget(self.listTypes)
        
        self.hSmartLists.addLayout(self.vEras)
        self.hSmartLists.addLayout(self.vTypes)
        
        self.vSmartLayout.addWidget(self.lSmartDesc)
        self.vSmartLayout.addWidget(self.btnSmartScan)
        self.vSmartLayout.addLayout(self.hSmartLists) # Add the horizontal layout
        
        # [NEW] Exclusion Candidates List
        self.lblExclusion = QtWidgets.QLabel("제외 제안 목록 (체크시 제외됨):")
        self.lblExclusion.setStyleSheet("font-weight: bold; color: #c0392b; margin-top: 10px;")
        self.listExclusions = QtWidgets.QListWidget()
        self.listExclusions.setMinimumHeight(80) # Reduced from 100
        self.listExclusions.setStyleSheet("color: #c0392b;") # Red text for danger
        
        self.vSmartLayout.addWidget(self.lblExclusion)
        self.vSmartLayout.addWidget(self.listExclusions)
        
        self.groupSmartFilter.setLayout(self.vSmartLayout)
        
        # Insert into the first tab layout (vTab1) before the Spec group (item index 1)
        if hasattr(self, 'vTab1'):
            self.vTab1.insertWidget(1, self.groupSmartFilter)

        # Default colors (Matching professional archaeological standards)
        self.heritage_stroke_color = QtGui.QColor(139, 69, 19) # SaddleBrown
        self.heritage_fill_color = QtGui.QColor(255, 178, 102) # Light Orange/Peach
        self.study_stroke_color = QtGui.QColor(255, 0, 0) # Red for Study Area
        self.topo_stroke_color = QtGui.QColor(0, 0, 0) # Black for Topo Maps
        self.buffer_color = QtGui.QColor(100, 100, 100) # Gray for Buffers
        
        # Set Default Values for SpinBoxes
        self.spinHeritageStrokeWidth.setValue(0.3)
        self.spinHeritageOpacity.setValue(40)
        self.spinStudyStrokeWidth.setValue(0.5)
        self.spinStudyStrokeWidth.setValue(0.5)
        self.spinTopoStrokeWidth.setValue(0.05) # Traditional topo line weight
        self.spinBufferWidth.setValue(0.3) # Default buffer width
        self.spinWidth.setValue(210) # A4 width
        self.spinHeight.setValue(297) # A4 height
        self.spinScale.setValue(5000)
        self.comboSortOrder.setCurrentIndex(0)
        self.tabWidget.setCurrentIndex(0)
        
        
        self.update_button_colors()

        # [CRITICAL FIX] Explicitly populate dropdowns in Python to guarantee items exist
        self.comboBufferStyle.clear()
        self.comboBufferStyle.addItems(["실선 (Solid)", "점선 (Dot)", "쇄선 (Dash)"])
        
        self.comboSortOrder.clear()
        self.comboSortOrder.addItems(["위에서 아래로 (북→남)", "조사지역에서 가까운 순 (거리순)", "가나다 순 (유적명)"])

        # [CRITICAL FIX] Force Style to ensure visibility
        STYLE_FORCE_VISIBLE = """
            QComboBox { 
                background-color: #ffffff; 
                color: #000000; 
                selection-background-color: #3498db;
                border: 1px solid #bdc3c7;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #000000;
                selection-background-color: #3498db;
                selection-color: #ffffff;
            }
        """
        self.comboBufferStyle.setStyleSheet(STYLE_FORCE_VISIBLE)
        self.comboSortOrder.setStyleSheet(STYLE_FORCE_VISIBLE)
        
        self.comboBufferStyle.setCurrentIndex(0)
        self.comboSortOrder.setCurrentIndex(0)
        self.btnHeritageStrokeColor.clicked.connect(lambda: self.pick_color('heritage_stroke'))
        self.btnHeritageFillColor.clicked.connect(lambda: self.pick_color('heritage_fill'))
        self.btnStudyStrokeColor.clicked.connect(lambda: self.pick_color('study_stroke'))
        self.btnTopoStrokeColor.clicked.connect(lambda: self.pick_color('topo_stroke'))
        self.btnBufferColor.clicked.connect(lambda: self.pick_color('buffer'))
        
        self.btnAddBuffer.clicked.connect(self.add_buffer_to_list)
        self.listBuffers.itemDoubleClicked.connect(self.remove_buffer_from_list)

        # Renumber signal
        self.btnRenumber.clicked.connect(self.renumber_current_layer)

        # Batch selection signals

        # Batch selection signals
        self.btnCheckTopo.clicked.connect(lambda: self.set_batch_check(self.listTopoLayers, True))
        self.btnUncheckTopo.clicked.connect(lambda: self.set_batch_check(self.listTopoLayers, False))
        self.btnCheckHeritage.clicked.connect(lambda: self.set_batch_check(self.listHeritageLayers, True))
        self.btnUncheckHeritage.clicked.connect(lambda: self.set_batch_check(self.listHeritageLayers, False))

        # Run signal
        self.btnRun.clicked.connect(self.emit_run_requested)
        self.buttonBox.rejected.connect(self.reject) # Close button
        
        # Help signal
        self.btnHelp.clicked.connect(self.show_help)
        
        # [NEW] Dynamic scale indicator update
        self.spinScale.valueChanged.connect(self.update_scale_indicator)
        self.update_scale_indicator()  # Initial update
        
        # [NEW] Global Scroll Implementation
        # User requested: Title bar fixed, but Tabs + Logs + Run Button all scrollable together.
        self.make_global_scrollable()
        
    def make_global_scrollable(self):
        """ Wraps the main content (Tabs, Logs, Buttons) in a single QScrollArea. """
        
        # 1. Create a ScrollArea and Container
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff) # Only vertical scroll
        
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0) # Tight fit
        
        # 2. Identify widgets to move (Tabs, Log, Buttons)
        # Note: 'vMain' layout contains: Header, TabWidget, GroupLog, hFinal (Layout)
        # We want to keep Header in vMain, but move the rest to container.
        
        # We need to access the layout items directly. 
        # vMain has: item0(Header), item1(TabWidget), item2(GroupLog), item3(hFinal)
        
        # CAUTION: 'hFinal' is a sub-layout, not a widget. 
        # We cannot 'move' a layout object easily to another widget using standard removal.
        # But we can re-add the widgets/layouts.
        
        # Strategy: 
        # Remove items from vMain starting from index 1 (Tabs).
        # Add them to container_layout.
        
        # Move TabWidget
        self.vMain.removeWidget(self.tabWidget)
        container_layout.addWidget(self.tabWidget)
        
        # Move GroupLog
        self.vMain.removeWidget(self.groupLog)
        container_layout.addWidget(self.groupLog)
        
        # Move hFinal Layout (Run Button Box)
        # We have to reparent the items inside hFinal or just add the layout?
        # Layouts can be nested.
        self.vMain.removeItem(self.hFinal)
        container_layout.addLayout(self.hFinal)
        
        # 3. Add Container to ScrollArea
        scroll.setWidget(container)
        
        # 4. Add ScrollArea to vMain (which now only has Header)
        self.vMain.addWidget(scroll)
        
        # [Adjust] Ensure ScrollArea expands
        # self.vMain is a VBoxLayout, it handles expansion.

        
        # Smart Scan signal [NEW]
        # [NEW] Smart Scan Signal
        self.btnSmartScan.clicked.connect(self.scan_categories)

        # Presets
        self.btnPresetReport.clicked.connect(lambda: self.apply_preset(160, 240))
        self.btnPresetA4.clicked.connect(lambda: self.apply_preset(210, 297))

        # Initialize layers
        self.populate_layers()
        
        # [NEW] Load Reference Data
        self.reference_data = {}
        self.load_reference_data()

    # Custom signal for execution
    run_requested = QtCore.pyqtSignal(dict)
    renumber_requested = QtCore.pyqtSignal(object) # Passing QgsVectorLayer
    scan_requested = QtCore.pyqtSignal(dict) # [NEW]

    def emit_run_requested(self):
        """Validates settings and emits the run signal."""
        settings = self.get_settings()
        if not settings['study_area_id']:
            QtWidgets.QMessageBox.warning(self, "입력 오류", "조사지역 레이어를 선택해 주세요.")
            return
        self.run_requested.emit(settings)

    def log(self, message):
        """Append a message to the log window and scroll to bottom."""
        self.txtLogs.appendPlainText(message)
        # Scroll to bottom
        cursor = self.txtLogs.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.txtLogs.setTextCursor(cursor)
        # Force UI update
        QtWidgets.QApplication.processEvents()

    def set_batch_check(self, list_widget, check_state):
        """Set check state for all currently selected items in the list widget."""
        selected_items = list_widget.selectedItems()
        target_state = QtCore.Qt.Checked if check_state else QtCore.Qt.Unchecked
        for item in selected_items:
            item.setCheckState(target_state)

    def update_button_colors(self):
        self.btnHeritageStrokeColor.setStyleSheet(f"background-color: {self.heritage_stroke_color.name()}; color: {'white' if self.heritage_stroke_color.lightness() < 128 else 'black'};")
        self.btnHeritageFillColor.setStyleSheet(f"background-color: {self.heritage_fill_color.name()}; color: {'white' if self.heritage_fill_color.lightness() < 128 else 'black'};")
        self.btnStudyStrokeColor.setStyleSheet(f"background-color: {self.study_stroke_color.name()}; color: {'white' if self.study_stroke_color.lightness() < 128 else 'black'};")
        self.btnTopoStrokeColor.setStyleSheet(f"background-color: {self.topo_stroke_color.name()}; color: {'white' if self.topo_stroke_color.lightness() < 128 else 'black'};")
        self.btnBufferColor.setStyleSheet(f"background-color: {self.buffer_color.name()}; color: {'white' if self.buffer_color.lightness() < 128 else 'black'};")

    def update_scale_indicator(self):
        """Update the scale indicator in the renumber section."""
        scale = self.spinScale.value()
        if hasattr(self, 'lblCurrentScale'):
            self.lblCurrentScale.setText(f"1:{scale} (유적 삭제 후 확인!)")

    def pick_color(self, target):
        color = QColorDialog.getColor()
        if color.isValid():
            if target == 'heritage_stroke': self.heritage_stroke_color = color
            elif target == 'heritage_fill': self.heritage_fill_color = color
            elif target == 'study_stroke': self.study_stroke_color = color
            elif target == 'topo_stroke': self.topo_stroke_color = color
            elif target == 'buffer': self.buffer_color = color
            self.update_button_colors()

    def add_buffer_to_list(self):
        dist = self.editBufferDistance.text().strip()
        if dist:
            try:
                float(dist)
                self.listBuffers.addItem(dist)
                self.editBufferDistance.clear()
            except ValueError:
                pass

    def apply_preset(self, w, h):
        self.spinWidth.setValue(w)
        self.spinHeight.setValue(h)
        self.log(f"판형 규격이 설정되었습니다: {w} x {h} mm")

    def remove_buffer_from_list(self, item):
        self.listBuffers.takeItem(self.listBuffers.row(item))

    def renumber_current_layer(self):
        """Renumber the features of the currently selected layer."""
        layer = iface.activeLayer() # [CRITICAL FIX] Use global iface
        if not layer or layer.type() != 0: # Check if vector layer
             QtWidgets.QMessageBox.warning(self, "선택 오류", "유적 레이어를 선택(활성화)한 후 실행해주세요.")
             return
             
        # Check for '번호' field
        if layer.fields().indexFromName("번호") == -1:
             QtWidgets.QMessageBox.warning(self, "호환 오류", "선택한 레이어에 '번호' 필드가 없습니다.\nArchDistribution으로 생성된 결과물인지 확인해주세요.")
             return

        # Get Study Area Centroid for Sorting
        study_layer_id = self.comboStudyArea.currentData()
        study_layer = QgsProject.instance().mapLayer(study_layer_id)
        
        centroid = None
        if study_layer:
             # Hacky way to access the helper method in the main logic class?
             # Actually, logic code is in 'ArchDistribution' class instance which holds 'dlg'.
             # 'dlg' doesn't hold 'ArchDistribution'.
             # So we should emit a signal to request renumbering, or move the logic here?
             # Cleanest: Emit a signal 'renumber_requested' with the layer.
             pass
        else:
             # If study layer is missing, we can't do distance sort, but others work.
             pass

        # Wait, the Dialog shouldn't do the heavy lifting.
        # Let's emit a signal sending the layer to the main plugin logic.
        self.renumber_requested.emit(layer)

    def populate_layers(self):
        self.comboStudyArea.clear()
        self.listTopoLayers.clear()
        self.listHeritageLayers.clear()

        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if layer.type() == 0:  # VectorLayer
                self.comboStudyArea.addItem(layer.name(), layer.id())
                
                item_topo = QListWidgetItem(layer.name())
                item_topo.setData(QtCore.Qt.UserRole, layer.id())
                item_topo.setFlags(item_topo.flags() | QtCore.Qt.ItemIsUserCheckable)
                item_topo.setCheckState(QtCore.Qt.Unchecked)
                self.listTopoLayers.addItem(item_topo)

                item_heritage = QListWidgetItem(layer.name())
                item_heritage.setData(QtCore.Qt.UserRole, layer.id())
                item_heritage.setFlags(item_heritage.flags() | QtCore.Qt.ItemIsUserCheckable)
                item_heritage.setCheckState(QtCore.Qt.Unchecked)
                self.listHeritageLayers.addItem(item_heritage)

    def get_settings(self):
        """Returns the current settings from the dialog."""
        topo_layer_ids = [self.listTopoLayers.item(i).data(QtCore.Qt.UserRole) 
                          for i in range(self.listTopoLayers.count()) 
                          if self.listTopoLayers.item(i).checkState() == QtCore.Qt.Checked]

        heritage_layer_ids = [self.listHeritageLayers.item(i).data(QtCore.Qt.UserRole) 
                             for i in range(self.listHeritageLayers.count()) 
                             if self.listHeritageLayers.item(i).checkState() == QtCore.Qt.Checked]
        
        buffers = [float(self.listBuffers.item(i).text()) for i in range(self.listBuffers.count())]
        
        return {
            "topo_layer_ids": topo_layer_ids,
            "heritage_layer_ids": heritage_layer_ids,
            "study_area_id": self.comboStudyArea.currentData(),
            "buffers": buffers,
            "buffer_style": {
                "color": self.buffer_color.name(),
                "style": self.comboBufferStyle.currentIndex(), # 0: Solid, 1: Dot, 2: Dash
                "width": self.spinBufferWidth.value()
            },
            "heritage_style": {
                "stroke_color": self.heritage_stroke_color.name(),
                "stroke_width": self.spinHeritageStrokeWidth.value(),
                "fill_color": self.heritage_fill_color.name(),
                "opacity": self.spinHeritageOpacity.value() / 100.0
            },
            "study_style": {
                "stroke_color": self.study_stroke_color.name(),
                "stroke_width": self.spinStudyStrokeWidth.value()
            },
            "topo_style": {
                "stroke_color": self.topo_stroke_color.name(),
                "stroke_width": self.spinTopoStrokeWidth.value()
            },
            "paper_width": self.spinWidth.value(),
            "paper_height": self.spinHeight.value(),
            "scale": self.spinScale.value(),
            "scale": self.spinScale.value(),
            "sort_order": self.comboSortOrder.currentIndex(),
            "filter_items": self.get_checked_items(None),
            # [NEW] Pass Exclusion List
            # We want to exclude items that are CHECKED in the listExclusions widget.
            "exclusion_list": [self.listExclusions.item(i).data(QtCore.Qt.UserRole) 
                               for i in range(self.listExclusions.count()) 
                               if self.listExclusions.item(i).checkState() == QtCore.Qt.Checked]
        }

    def load_reference_data(self):
        """Load reference data from JSON file."""
        import json
        json_path = os.path.join(os.path.dirname(__file__), 'reference_data.json')
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    self.reference_data = json.load(f)
                self.log(f"참조 데이터 로드 완료: {len(self.reference_data)}개 항목")
            except Exception as e:
                self.log(f"참조 데이터 로드 실패: {str(e)}")
        else:
            self.log("참조 데이터 파일이 없습니다. (reference_data.json)")
            
        # [NEW] Load Smart Patterns
        json_pattern_path = os.path.join(os.path.dirname(__file__), 'smart_patterns.json')
        self.smart_patterns = {"noise": [], "artifacts": {}}
        if os.path.exists(json_pattern_path):
            try:
                with open(json_pattern_path, 'r', encoding='utf-8') as f:
                    self.smart_patterns = json.load(f)
                self.log(f"스마트 필터 패턴 로드 완료.")
            except Exception as e:
                self.log(f"스마트 필터 패턴 로드 실패: {str(e)}")

    def scan_categories(self):
        """Identify categories and potential exclusions using Smart Patterns."""
        self.listEras.clear()
        self.listTypes.clear()
        self.listExclusions.clear()
        
        heritage_layer_ids = [self.listHeritageLayers.item(i).data(QtCore.Qt.UserRole) 
                             for i in range(self.listHeritageLayers.count()) 
                             if self.listHeritageLayers.item(i).checkState() == QtCore.Qt.Checked]
        
        if not heritage_layer_ids:
            QtWidgets.QMessageBox.warning(self, "선택 오류", "먼저 분석할 유적 레이어를 선택체크해주세요.")
            return

        found_eras = set()
        found_types = set()
        found_exclusions = set() # Store unique names to exclude
        
        total_feats = 0
        matched_feats = 0

        for lid in heritage_layer_ids:
            layer = QgsProject.instance().mapLayer(lid)
            if not layer: continue
            
            self.log(f"레이어 스캔 중: {layer.name()}")

            # [Auto-Fix] Check for Encoding Issues (Mojibake)
            fields = [f.name() for f in layer.fields()]
            needs_encoding_fix = any('\ufffd' in f or '' in f for f in fields)
            
            if needs_encoding_fix:
                self.log("  ⚠️ 인코딩 깨짐 감지됨. CP949(EUC-KR)로 자동 변환을 시도합니다.")
                layer.setProviderEncoding("CP949")
                layer.dataProvider().reloadData()
                fields = [f.name() for f in layer.fields()]
                self.log(f"  - 변환 후 필드 목록: {', '.join(fields)}")
            else:
                self.log(f"  - 필드 목록: {', '.join(fields)}")
            
            name_field = None
            keywords = ['유적명', '명칭', '명', '이름', 'NAME', 'SITE', 'TITLE']
            
            for f in fields:
                for k in keywords:
                    if k in f.upper():
                        name_field = f
                        break
                if name_field: break
            
            if not name_field: 
                self.log("  ⚠️ 경고: 유적 명칭 필드를 찾을 수 없어 건너뜁니다.")
                continue
                
            self.log(f"  - 명칭 필드 식별됨: {name_field}")
            
            layer_feats = 0
            for feat in layer.getFeatures():
                layer_feats += 1
                total_feats += 1
                name = feat[name_field] # [FIX] Ensure variable is defined
            
                # [NEW] Exclusion Logic with User Review
                # Instead of silently skipping, add to exclusion list
                noise_keywords = self.smart_patterns.get('noise', [])
                is_suspicious = any(b in name for b in noise_keywords)
                
                if is_suspicious:
                    found_exclusions.add(name)
                    continue # Do not classify this item yet

                matched = False
                
                # 1. Reference Data Lookup
                if name in self.reference_data:
                    matched = True
                    info = self.reference_data[name]
                    if info['e'] and info['e'] != "시대미상":
                        found_eras.add(info['e'])
                    if info['t'] and info['t'] != "기타":
                        found_types.add(info['t'])
                
                # 2. Keyword Refinement (Overrides/Additions)
                refinements = self.smart_patterns.get('artifacts', {})
                for key, val in refinements.items():
                    if key in name:
                        found_types.add(val)
                        matched = True
                
                if matched:
                    matched_feats += 1
            
            self.log(f"  - {layer_feats}개 객체 중 {matched_feats}개 매칭 성공")
        
        self.log(f"✅ 전체 스캔 완료: 총 {matched_feats}/{total_feats} 건 매칭됨.")
        
        # Populate List - Era
        if found_eras:
            # Sort Era? Custom sort order would be nice but alphabetical for now
            for era in sorted(list(found_eras)):
                item = QListWidgetItem(era)
                item.setData(QtCore.Qt.UserRole, f"ERA:{era}")
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Checked)
                self.listEras.addItem(item)
        else:
            self.listEras.addItem("식별실패")

        # Populate List - Type
        if found_types:
            for t in sorted(list(found_types)):
                item = QListWidgetItem(t)
                item.setData(QtCore.Qt.UserRole, f"TYPE:{t}")
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Checked)
                self.listTypes.addItem(item)
        else:
            self.listTypes.addItem("식별실패")
            
        # [NEW] Populate Exclusion List
        if found_exclusions:
            for exc in sorted(list(found_exclusions)):
                item = QListWidgetItem(exc)
                item.setData(QtCore.Qt.UserRole, exc) # Store exact name to exclude
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Checked) # Default to Checked (Exclude)
                self.listExclusions.addItem(item)
            self.log(f"⚠️ {len(found_exclusions)}개의 제외 의심 항목이 발견되었습니다. '제외 제안 목록'을 확인하세요.")
        else:
            self.listExclusions.addItem("(제외 대상 없음)")


    def get_checked_items(self, _ignored):
        """Return list of checked items data from both Era and Type lists."""
        checked = []
        # Check Eras
        for i in range(self.listEras.count()):
            item = self.listEras.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                checked.append(item.data(QtCore.Qt.UserRole))
        
        # Check Types
        for i in range(self.listTypes.count()):
            item = self.listTypes.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                checked.append(item.data(QtCore.Qt.UserRole))
                
        return checked

    def show_help(self):
        """Display User Guide and Export Tips."""
        help_text = """
<h3>📘 사용 가이드 및 유의사항 (User Guide)</h3>
<hr>
<b>[📋 작업 순서 (Workflow)]</b><br>
<ol>
<li><b>레이어 준비:</b> 조사지역(Polygon), 수치지형도, 주변유적 레이어를 불러옵니다.</li>
<li><b>레이어 선택:</b> [데이터 탭]에서 조사지역, 지형도, 유적 레이어를 선택합니다.</li>
<li><b>도곽/축척 설정:</b> 도면 가로/세로(mm)와 축척을 입력합니다. (프리셋 활용 추천)</li>
<li><b>스마트 분류:</b> [속성 분류 실행] 버튼으로 유적을 시대/유형별로 분류합니다.</li>
<li><b>분석 실행:</b> [▶ 분석 및 지도 생성 실행] 클릭으로 자동 처리합니다.</li>
<li><b>번호 새로고침:</b> 유적 삭제/수정 후 [스타일 탭 > 🔄 번호 새로고침]으로 번호 재정렬</li>
</ol>
<br>
<b>[일러스트레이터(AI) 반출 꿀팁]</b><br>
보고서 편집을 위해 결과물을 일러스트레이터로 가져가실 때 추천하는 방법입니다:
<ol>
<li>QGIS 상단 메뉴의 <b>'프로젝트 > 새 인쇄 조판'</b>을 엽니다.</li>
<li>생성된 분포지도를 추가하고, <b>PDF로 내보내기</b>를 합니다.</li>
<li><b>Tip:</b> 레이어(지형도, 유적, 버퍼 등)를 <u>하나씩만 켜서 각각 PDF로 저장</u>한 뒤,<br> 
일러스트레이터에서 합치면 레이어가 섞이지 않아 편집이 훨씬 수월합니다.</li>
</ol>
<br>
<b>[⚠️ 유의사항 (Disclaimer)]</b><br>
본 플러그인은 좌표계 변환 및 데이터 병합을 자동화하여 사용자의 편의를 돕는 도구입니다.<br>
<ul>
<li>사용자마다 QGIS 환경(좌표계 설정 등)이 다르므로, <b>반드시 결과물의 위치와 속성을 육안으로 검수</b>해주시기 바랍니다.</li>
<li>자동 생성된 유적 번호나 위치가 의도와 다를 수 있으므로, <b>[🔄 번호 새로고침]</b> 기능 등을 활용하여 최종 확인 후 사용하세요.</li>
<li><b style='color:red'>⚠ 번호 새로고침 시 현재 설정된 축척/도곽 범위에 맞춰 번호가 재할당됩니다. 반드시 축척을 확인하세요!</b></li>
</ul>
<br>
<div style='color: #7f8c8d; font-size: 11px;'>ArchDistribution v{version}</div>
"""
        help_text = help_text.format(version=get_plugin_version())
        QtWidgets.QMessageBox.information(self, "ArchDistribution 사용 가이드", help_text)
