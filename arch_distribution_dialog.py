import json
import os

from qgis.PyQt import uic, QtCore, QtGui
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QListWidgetItem, QColorDialog
from qgis.core import QgsProject, QgsMapLayerProxyModel
from qgis.gui import QgsMapLayerComboBox # [NEW] Import
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
    except Exception:
        pass
    return "unknown"  # Fallback


DEFAULT_COLORS = {
    "heritage_stroke": QtGui.QColor(139, 69, 19),
    "heritage_fill": QtGui.QColor(255, 178, 102),
    "study_stroke": QtGui.QColor(255, 0, 0),
    "topo_stroke": QtGui.QColor(0, 0, 0),
    "buffer": QtGui.QColor(100, 100, 100),
}

DEFAULT_SPIN_VALUES = {
    "heritage_stroke_width": 0.3,
    "heritage_opacity": 40,
    "study_stroke_width": 0.5,
    "topo_stroke_width": 0.05,
    "buffer_width": 0.3,
    "paper_width": 210,
    "paper_height": 297,
    "scale": 5000,
    "scale_step": 500,
    "label_font_size": 10,
}

BUFFER_STYLE_OPTIONS = {
    "ko": ["실선 (Solid)", "점선 (Dot)", "쇄선 (Dash)"],
    "en": ["Solid", "Dot", "Dash"],
}
SORT_ORDER_OPTIONS = {
    "ko": ["위에서 아래로 (북→남)", "조사지역에서 가까운 순 (거리순)", "가나다 순 (유적명)"],
    "en": ["Top to bottom (N->S)", "Nearest to study area (distance)", "Alphabetical (site name)"],
}
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
DEFAULT_LABEL_FONT_FAMILY = {"ko": "맑은 고딕", "en": "Arial"}
PRESET_REPORT = (160, 240)
PRESET_A4 = (210, 297)


def detect_ui_language():
    """Detect UI language from QGIS locale or optional environment override."""
    forced = os.environ.get("ARCHDISTRIBUTION_LANG", "").strip().lower()
    if forced in ("ko", "en"):
        return forced

    locale = str(QtCore.QSettings().value("locale/userLocale", "ko")).lower()
    return "en" if locale.startswith("en") else "ko"


class ArchDistributionDialog(QtWidgets.QDialog, FORM_CLASS):
    # Define signals
    run_requested = QtCore.pyqtSignal(dict)
    renumber_requested = QtCore.pyqtSignal(object)
    scan_requested = QtCore.pyqtSignal(dict)

    def __init__(self, parent=None):
        """Constructor."""
        super(ArchDistributionDialog, self).__init__(parent)
        self.ui_lang = detect_ui_language()
        self.setupUi(self) # [CRITICAL FIX] Restore UI initialization
        self._apply_static_ui_translation()

        # [MOVED FROM HERE]
        # make_tab_scrollable logic moved to end of __init__


        # [NEW] Programmatically add missing UI elements for Smart Filter
        self.groupSmartFilter = QtWidgets.QGroupBox(self._t("유적 속성 분류", "Site Attribute Classification"))
        self.vSmartLayout = QtWidgets.QVBoxLayout()
        
        self.lSmartDesc = QtWidgets.QLabel(
            self._t(
                "체크된 유적 레이어의 명칭을 분석하여 시대와 성격을 자동 분류합니다.",
                "Analyze selected heritage-layer names and classify period/type automatically.",
            )
        )
        self.lSmartDesc.setStyleSheet("color: #555; font-size: 10px;")
        
        self.btnSmartScan = QtWidgets.QPushButton(self._t("속성 분류 실행", "Run Attribute Scan"))
        self.btnSmartScan.setStyleSheet("background-color: #f39c12; color: white; font-weight: bold; padding: 5px;")
        
        # Split UI into two columns
        self.hSmartLists = QtWidgets.QHBoxLayout()
        
        # Era Column
        self.vEras = QtWidgets.QVBoxLayout()
        self.lblEra = QtWidgets.QLabel(self._t("시대", "Era"))
        self.lblEra.setStyleSheet("font-weight: bold; color: #333;")
        self.listEras = QtWidgets.QListWidget()
        self.listEras.setMinimumHeight(130) # Reduced from 200
        self.vEras.addWidget(self.lblEra)
        self.vEras.addWidget(self.listEras)
        
        # Type Column
        self.vTypes = QtWidgets.QVBoxLayout()
        self.lblType = QtWidgets.QLabel(self._t("성격", "Type"))
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
        self.lblExclusion = QtWidgets.QLabel(self._t("제외 제안 목록 (체크시 제외됨):", "Suggested Exclusions (checked = exclude):"))
        self.lblExclusion.setStyleSheet("font-weight: bold; color: #c0392b; margin-top: 10px;")
        self.listExclusions = QtWidgets.QListWidget()
        self.listExclusions.setMinimumHeight(80) # Reduced from 100
        self.listExclusions.setStyleSheet("color: #c0392b;") # Red text for danger
        
        self.vSmartLayout.addWidget(self.lblExclusion)
        self.vSmartLayout.addWidget(self.listExclusions)
        
        self.groupSmartFilter.setLayout(self.vSmartLayout)
        
        # [NEW] Zone Layer Selection (Optional)
        self.lblZoneLayer = QtWidgets.QLabel(self._t("현상변경 허용구간 레이어 (선택):", "Zone Layer (optional):"))
        self.comboZoneLayer = QgsMapLayerComboBox()
        self.comboZoneLayer.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.comboZoneLayer.setAllowEmptyLayer(True) # Optional
        self.comboZoneLayer.setLayer(None) # [FIX] Default to Empty Selection
        
        # Insert into vTab1 (index 0 is groupBuffer, 1 is SmartFilter... let's check)
        if hasattr(self, 'vTab1'):
            # Insert before Smart Filter? Or after?
            # Heritage List is likely index 0 in .ui or so.
            # Smart Filter was inserted at 1.
            # Buffer Toggle was inserted at 1.
            # So order: 0(Original), 1(Toggle), 2(Smart).
            # Let's put Zone Layer at index 0 (Top) or after Heritage List (which is inside 0).
            # Since we can't easily put it *inside* the existing GroupBox (unless we find it),
            # Putting it at the top of Tab1 or simply appending might be safest.
            # But the user wants it with the inputs.
            # Let's try adding it at index 1 (pushing others down).
            
            # Create a container HBox or VBox for it?
            self.vZoneLayout = QtWidgets.QVBoxLayout()
            self.vZoneLayout.addWidget(self.lblZoneLayer)
            self.vZoneLayout.addWidget(self.comboZoneLayer)

            # [NEW] Clip to Buffer Checkbox
            self.chkClipZoneToBuffer = QtWidgets.QCheckBox(self._t("버퍼 범위 내 자르기 (반경 내만 표시)", "Clip to buffer extent (inside radius only)"))
            self.chkClipZoneToBuffer.setToolTip(
                self._t(
                    "체크 시, 도곽 전체가 아닌 조사 반경(가장 큰 버퍼) 내의 현상변경허용기준만 남기고 나머지는 잘라냅니다.",
                    "Keep only zone features inside the largest survey buffer (instead of full extent).",
                )
            )
            self.chkClipZoneToBuffer.setChecked(False) # Default Off
            self.vZoneLayout.addWidget(self.chkClipZoneToBuffer)
            
            # Convert layout to widget to insert? No, insertLayout works for Box Layouts usually.
            # QLayout.insertLayout(index, layout)
            self.vTab1.insertLayout(1, self.vZoneLayout)
            
        # Insert into the first tab layout (vTab1) before the Spec group (item index 1)
        if hasattr(self, 'vTab1'):
            self.vTab1.insertWidget(2, self.groupSmartFilter) # Adjusted index

        # Default colors (Matching professional archaeological standards)
        self.heritage_stroke_color = QtGui.QColor(DEFAULT_COLORS["heritage_stroke"])
        self.heritage_fill_color = QtGui.QColor(DEFAULT_COLORS["heritage_fill"])
        self.study_stroke_color = QtGui.QColor(DEFAULT_COLORS["study_stroke"])
        self.topo_stroke_color = QtGui.QColor(DEFAULT_COLORS["topo_stroke"])
        self.buffer_color = QtGui.QColor(DEFAULT_COLORS["buffer"])
        
        # Set Default Values for SpinBoxes
        self.spinHeritageStrokeWidth.setValue(DEFAULT_SPIN_VALUES["heritage_stroke_width"])
        self.spinHeritageOpacity.setValue(DEFAULT_SPIN_VALUES["heritage_opacity"])
        self.spinStudyStrokeWidth.setValue(DEFAULT_SPIN_VALUES["study_stroke_width"])
        self.spinTopoStrokeWidth.setValue(DEFAULT_SPIN_VALUES["topo_stroke_width"])
        self.spinBufferWidth.setValue(DEFAULT_SPIN_VALUES["buffer_width"])
        self.spinWidth.setValue(DEFAULT_SPIN_VALUES["paper_width"])
        self.spinHeight.setValue(DEFAULT_SPIN_VALUES["paper_height"])
        self.spinScale.setValue(DEFAULT_SPIN_VALUES["scale"])
        self.spinScale.setSingleStep(DEFAULT_SPIN_VALUES["scale_step"])
        self.comboSortOrder.setCurrentIndex(0)
        self.tabWidget.setCurrentIndex(0)
        
        
        self.update_button_colors()

        # [CRITICAL FIX] Explicitly populate dropdowns in Python to guarantee items exist
        self.comboBufferStyle.clear()
        self.comboBufferStyle.addItems(BUFFER_STYLE_OPTIONS[self.ui_lang])
        
        self.comboSortOrder.clear()
        self.comboSortOrder.addItems(SORT_ORDER_OPTIONS[self.ui_lang])

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

        # [NEW] Add RESTRICT checkbox programmatically below Buffer list
        # Find the layout that holds listBuffers. It's likely in a layout with btnAddBuffer.
        # Actually, let's just add it to vTab1 (index 0 is groupBuffer?)
        # For safety and visibility, we'll create a new GroupBox or just add it to vSmartLayout?
        # No, it belongs to Buffer settings.
        
        # Let's search for groupBuffer in the .ui file logic (via FindChild or just use vTab1 insertion)
        # We can insert it right after the buffer group.
        # But 'groupBuffer' is not explicitly defined here, it's in .ui.
        
        # Alternative: Add it to the existing `groupSmartFilter` since we are touching python code?
        # Or create a new clean checkbox and insert it into the main tab layout.
        
        self.chkRestrictToBuffer = QtWidgets.QCheckBox(self._t("버퍼 범위 외 유적 제외 (감추기)", "Exclude sites outside buffer (hide)"))
        self.chkRestrictToBuffer.setToolTip(
            self._t(
                "체크 시: 최외곽 버퍼 바깥의 유적은 번호를 매기지 않고 지도에서 숨깁니다. (지표조사 등)\n체크 해제 시: 모든 유적에 번호를 매깁니다. (일반조사 등)",
                "Checked: hide/unnumber sites outside the outermost buffer.\nUnchecked: number all sites.",
            )
        )
        self.chkRestrictToBuffer.setChecked(False) # [FIX] Default to Unchecked (User Request)
        self.chkRestrictToBuffer.setStyleSheet("font-weight: bold; color: #d35400;")
        
        # Insert into vTab1 at index 1
        if hasattr(self, 'vTab1'):
             self.vTab1.insertWidget(1, self.chkRestrictToBuffer)

        # [NEW] Label Font Controls
        self.groupLabelStyle = QtWidgets.QGroupBox(self._t("라벨 스타일", "Label Style"))
        self.hLabelLayout = QtWidgets.QHBoxLayout()
        
        self.lblFontSize = QtWidgets.QLabel(self._t("글자 크기:", "Font size:"))
        self.spinLabelFontSize = QtWidgets.QSpinBox()
        self.spinLabelFontSize.setRange(6, 72)
        self.spinLabelFontSize.setValue(DEFAULT_SPIN_VALUES["label_font_size"])
        self.spinLabelFontSize.setToolTip(self._t("유적 번호 라벨의 글자 크기 (pt)", "Label font size (pt) for site number"))
        
        self.lblFontFamily = QtWidgets.QLabel(self._t("글씨체:", "Font family:"))
        self.comboLabelFont = QtWidgets.QFontComboBox()
        self.comboLabelFont.setCurrentFont(QtGui.QFont(DEFAULT_LABEL_FONT_FAMILY[self.ui_lang]))
        self.comboLabelFont.setToolTip(self._t("유적 번호 라벨의 글씨체", "Label font family for site number"))
        
        self.hLabelLayout.addWidget(self.lblFontSize)
        self.hLabelLayout.addWidget(self.spinLabelFontSize)
        self.hLabelLayout.addWidget(self.lblFontFamily)
        self.hLabelLayout.addWidget(self.comboLabelFont)
        self.groupLabelStyle.setLayout(self.hLabelLayout)
        
        if hasattr(self, 'vTab1'):
             self.vTab1.insertWidget(2, self.groupLabelStyle) 

        # [NEW] Enable Extended Selection for Lists
        self.listHeritageLayers.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.listTopoLayers.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.listEras.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.listTypes.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.listExclusions.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection) # Allow Shift-Select
        
        # [NEW] Add Batch Buttons for Exclusion List
        # We'll insert this into the layout that holds listExclusions (which is likely inside groupSmartFilter).
        # Since we don't have direct access to that auto-generated layout object easily, 
        # we'll create a new layout and insert it into the groupSmartFilter layout.
        if hasattr(self, 'groupSmartFilter') and self.groupSmartFilter.layout():
             self.hExclusionBtns = QtWidgets.QHBoxLayout()
             self.btnExcludeSel = QtWidgets.QPushButton(self._t("선택 항목 제외 (체크)", "Exclude selected (check)"))
             self.btnIncludeSel = QtWidgets.QPushButton(self._t("선택 항목 포함 (해제)", "Include selected (uncheck)"))
             self.btnExcludeSel.setToolTip(self._t("선택한 항목들을 리스트에서 체크합니다. (지도에서 제외됨)", "Check selected items (excluded on map)"))
             self.btnIncludeSel.setToolTip(self._t("선택한 항목들의 체크를 해제합니다. (지도에 포함됨)", "Uncheck selected items (included on map)"))
             
             self.btnExcludeSel.clicked.connect(lambda: self.set_list_check_state(self.listExclusions, True))
             self.btnIncludeSel.clicked.connect(lambda: self.set_list_check_state(self.listExclusions, False))
             
             self.hExclusionBtns.addWidget(self.btnExcludeSel)
             self.hExclusionBtns.addWidget(self.btnIncludeSel)
             
             self.groupSmartFilter.layout().addLayout(self.hExclusionBtns)

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
        
        # [NEW] Smart Scan Signal
        self.btnSmartScan.clicked.connect(self.scan_categories)

        # Presets
        self.btnPresetReport.clicked.connect(lambda: self.apply_preset(*PRESET_REPORT))
        self.btnPresetA4.clicked.connect(lambda: self.apply_preset(*PRESET_A4))

        # Initialize layers
        self.populate_layers()
        
        # [NEW] Load Reference Data
        self.reference_data = {}
        self.load_reference_data()

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
        
        if not hasattr(self, 'vMain'): return

        # Move TabWidget
        if hasattr(self, 'tabWidget'):
            self.vMain.removeWidget(self.tabWidget)
            container_layout.addWidget(self.tabWidget)
        
        # Move GroupLog
        if hasattr(self, 'groupLog'):
            self.vMain.removeWidget(self.groupLog)
            container_layout.addWidget(self.groupLog)
        
        # Move hFinal Layout (Run Button Box)
        if hasattr(self, 'hFinal'):
            self.vMain.removeItem(self.hFinal)
            container_layout.addLayout(self.hFinal)
        
        # 3. Add Container to ScrollArea
        scroll.setWidget(container)
        
        # 4. Add ScrollArea to vMain
        self.vMain.addWidget(scroll)

    def _t(self, ko_text, en_text):
        """Small runtime translator for KR/EN without changing UI layout."""
        return en_text if self.ui_lang == "en" else ko_text

    def _apply_static_ui_translation(self):
        """Translate Qt-Designer widgets at runtime while keeping .ui structure intact."""
        if self.ui_lang != "en":
            return

        if hasattr(self, "groupData"):
            self.groupData.setTitle("Input Layer Controls")
        if hasattr(self, "groupSpecs"):
            self.groupSpecs.setTitle("Output Extent / Scale")
        if hasattr(self, "groupSym"):
            self.groupSym.setTitle("Detailed Symbology")
        if hasattr(self, "groupBuffer"):
            self.groupBuffer.setTitle("Buffer Analysis")
        if hasattr(self, "groupNumbering"):
            self.groupNumbering.setTitle("Numbering Rules")
        if hasattr(self, "groupLog"):
            self.groupLog.setTitle("Progress Log")

        if hasattr(self, "btnCheckTopo"):
            self.btnCheckTopo.setText("Check selected")
            self.btnCheckTopo.setToolTip("Check selected items in the list.")
        if hasattr(self, "btnUncheckTopo"):
            self.btnUncheckTopo.setText("Uncheck selected")
        if hasattr(self, "btnCheckHeritage"):
            self.btnCheckHeritage.setText("Check selected")
            self.btnCheckHeritage.setToolTip("Check selected items in the list.")
        if hasattr(self, "btnUncheckHeritage"):
            self.btnUncheckHeritage.setText("Uncheck selected")

        if hasattr(self, "btnPresetReport"):
            self.btnPresetReport.setText("Report (160x240)")
            self.btnPresetReport.setToolTip("Apply report-size preset.")
        if hasattr(self, "btnPresetA4"):
            self.btnPresetA4.setText("A4 (210x297)")
            self.btnPresetA4.setToolTip("Apply A4-size preset.")

        if hasattr(self, "btnHeritageStrokeColor"):
            self.btnHeritageStrokeColor.setText("Stroke color")
        if hasattr(self, "btnHeritageFillColor"):
            self.btnHeritageFillColor.setText("Fill color")
        if hasattr(self, "btnStudyStrokeColor"):
            self.btnStudyStrokeColor.setText("Stroke color")
        if hasattr(self, "btnTopoStrokeColor"):
            self.btnTopoStrokeColor.setText("Topo color")
        if hasattr(self, "btnBufferColor"):
            self.btnBufferColor.setText("Line color")
        if hasattr(self, "btnAddBuffer"):
            self.btnAddBuffer.setText("Add (+)")
        if hasattr(self, "btnRenumber"):
            self.btnRenumber.setText("Refresh numbering (active layer)")
            self.btnRenumber.setToolTip("Renumber features from 1 in the current active layer.")
        if hasattr(self, "btnRun"):
            self.btnRun.setText("Run Analysis / Generate Map")

        if hasattr(self, "btnHelp"):
            self.btnHelp.setToolTip("User guide and export tips")

    def set_list_check_state(self, list_widget, checked):
        """Batch set check state for selected items in a list widget."""
        for item in list_widget.selectedItems():
            item.setCheckState(QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked)

    def set_batch_check(self, list_widget, checked):
        """
        Check/Uncheck items. 
        If items are selected (highlighted), only apply to them.
        If no items selected, apply to all.
        """
        items_to_process = list_widget.selectedItems()
        if not items_to_process:
            # Fallback: All items
            items_to_process = [list_widget.item(i) for i in range(list_widget.count())]
            
        state = QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked
        for item in items_to_process:
            item.setCheckState(state)

    def emit_run_requested(self):
        """Validates settings and emits the run signal."""
        settings = self.get_settings()
        if not settings['study_area_id']:
            QtWidgets.QMessageBox.warning(
                self,
                self._t("입력 오류", "Input Error"),
                self._t("조사지역 레이어를 선택해 주세요.", "Please select a study-area layer."),
            )
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
            self.lblCurrentScale.setText(
                self._t(
                    f"1:{scale} (유적 삭제 후 확인!)",
                    f"1:{scale} (verify after deleting features)",
                )
            )

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
            parsed = self._parse_buffer_value(dist)
            if parsed is not None:
                self.listBuffers.addItem(str(parsed))
                self.editBufferDistance.clear()

    def apply_preset(self, w, h):
        self.spinWidth.setValue(w)
        self.spinHeight.setValue(h)
        self.log(self._t(f"판형 규격이 설정되었습니다: {w} x {h} mm", f"Preset applied: {w} x {h} mm"))

    def remove_buffer_from_list(self, item):
        self.listBuffers.takeItem(self.listBuffers.row(item))

    def renumber_current_layer(self):
        """Renumber the features of the currently selected layer."""
        layer = iface.activeLayer() # [CRITICAL FIX] Use global iface
        if not layer or layer.type() != 0: # Check if vector layer
             QtWidgets.QMessageBox.warning(
                 self,
                 self._t("선택 오류", "Selection Error"),
                 self._t("유적 레이어를 선택(활성화)한 후 실행해주세요.", "Select/activate a heritage layer first."),
             )
             return
             
        # Check for '번호' field
        if layer.fields().indexFromName("번호") == -1:
             QtWidgets.QMessageBox.warning(
                 self,
                 self._t("호환 오류", "Compatibility Error"),
                 self._t(
                     "선택한 레이어에 '번호' 필드가 없습니다.\nArchDistribution으로 생성된 결과물인지 확인해주세요.",
                     "Selected layer has no '번호' field.\nPlease choose a result layer created by ArchDistribution.",
                 ),
             )
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
                # [FIX] Filter out generated/output layers to prevent feedback loops
                l_name = layer.name()
                keywords_to_skip = ['_Copy', 'Consolidated', 'Dissolved', 'Buffer', '도곽', '조사구역']
                if any(k in l_name for k in keywords_to_skip):
                     continue

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
        
        buffers = []
        for i in range(self.listBuffers.count()):
            parsed = self._parse_buffer_value(self.listBuffers.item(i).text())
            if parsed is not None:
                buffers.append(parsed)
        
        filter_items = self.get_checked_items(None)
        has_filter_tags = False
        for i in range(self.listEras.count()):
            data = self.listEras.item(i).data(QtCore.Qt.UserRole)
            if isinstance(data, str) and data.startswith("ERA:"):
                has_filter_tags = True
                break
        if not has_filter_tags:
            for i in range(self.listTypes.count()):
                data = self.listTypes.item(i).data(QtCore.Qt.UserRole)
                if isinstance(data, str) and data.startswith("TYPE:"):
                    has_filter_tags = True
                    break
        if not has_filter_tags:
            filter_items = None

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
            "sort_order": self.comboSortOrder.currentIndex(),
            "filter_items": filter_items,
            # [NEW] Pass Exclusion List
            "exclusion_list": [self.listExclusions.item(i).data(QtCore.Qt.UserRole) 
                               for i in range(self.listExclusions.count()) 
                               if self.listExclusions.item(i).checkState() == QtCore.Qt.Checked],
            # [NEW] Restrict Toggle
            "restrict_to_buffer": self.chkRestrictToBuffer.isChecked(),
            # [NEW] Zone Layer ID
            "zone_layer_id": self.comboZoneLayer.currentLayer().id() if self.comboZoneLayer.currentLayer() else None,
            "clip_zone_to_buffer": self.chkClipZoneToBuffer.isChecked() if hasattr(self, "chkClipZoneToBuffer") else False,
            # [NEW] Label Style
            "label_font_size": self.spinLabelFontSize.value(),
            "label_font_family": self.comboLabelFont.currentFont().family()
        }

    def _parse_buffer_value(self, raw_value):
        """Parse user-entered buffer value and normalize optional 'm' suffix."""
        if raw_value is None:
            return None
        text = str(raw_value).strip().lower()
        if text.endswith("m"):
            text = text[:-1].strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def load_reference_data(self):
        """Load reference data from JSON file."""
        import json
        json_path = os.path.join(os.path.dirname(__file__), 'reference_data.json')
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    self.reference_data = json.load(f)
                self.log(self._t(f"참조 데이터 로드 완료: {len(self.reference_data)}개 항목", f"Reference data loaded: {len(self.reference_data)} entries"))
            except Exception as e:
                self.log(self._t(f"참조 데이터 로드 실패: {str(e)}", f"Failed to load reference data: {str(e)}"))
        else:
            self.log(self._t("참조 데이터 파일이 없습니다. (reference_data.json)", "Reference file not found (reference_data.json)."))
            
        # [NEW] Load Smart Patterns
        json_pattern_path = os.path.join(os.path.dirname(__file__), 'smart_patterns.json')
        self.smart_patterns = {"noise": [], "artifacts": {}}
        if os.path.exists(json_pattern_path):
            try:
                with open(json_pattern_path, 'r', encoding='utf-8') as f:
                    self.smart_patterns = json.load(f)
                self.log(self._t("스마트 필터 패턴 로드 완료.", "Smart-filter patterns loaded."))
            except Exception as e:
                self.log(self._t(f"스마트 필터 패턴 로드 실패: {str(e)}", f"Failed to load smart-filter patterns: {str(e)}"))

    def scan_categories(self):
        """Identify categories and potential exclusions using Smart Patterns."""
        self.listEras.clear()
        self.listTypes.clear()
        self.listExclusions.clear()
        
        heritage_layer_ids = [self.listHeritageLayers.item(i).data(QtCore.Qt.UserRole) 
                             for i in range(self.listHeritageLayers.count()) 
                             if self.listHeritageLayers.item(i).checkState() == QtCore.Qt.Checked]
        
        if not heritage_layer_ids:
            QtWidgets.QMessageBox.warning(
                self,
                self._t("선택 오류", "Selection Error"),
                self._t("먼저 분석할 유적 레이어를 선택체크해주세요.", "Please check at least one heritage layer to scan."),
            )
            return

        found_eras = set()
        found_types = set()
        found_exclusions = set() # Store unique names to exclude
        
        total_feats = 0
        matched_feats = 0

        for lid in heritage_layer_ids:
            layer = QgsProject.instance().mapLayer(lid)
            if not layer: continue
            
            self.log(self._t(f"레이어 스캔 중: {layer.name()}", f"Scanning layer: {layer.name()}"))

            # [Auto-Fix] Check for Encoding Issues (Mojibake)
            fields = [f.name() for f in layer.fields()]
            needs_encoding_fix = any('\ufffd' in f for f in fields)
            
            if needs_encoding_fix:
                self.log(self._t("  ⚠️ 인코딩 깨짐 감지됨. CP949(EUC-KR)로 자동 변환을 시도합니다.", "  ⚠️ Encoding issue detected. Trying CP949(EUC-KR)."))
                layer.setProviderEncoding("CP949")
                layer.dataProvider().reloadData()
                fields = [f.name() for f in layer.fields()]
                self.log(self._t(f"  - 변환 후 필드 목록: {', '.join(fields)}", f"  - Fields after conversion: {', '.join(fields)}"))
            else:
                self.log(self._t(f"  - 필드 목록: {', '.join(fields)}", f"  - Fields: {', '.join(fields)}"))
            
            name_field = None
            keywords = ['유적명', '명칭', '명', '이름', 'NAME', 'SITE', 'TITLE']
            
            for f in fields:
                for k in keywords:
                    if k in f.upper():
                        name_field = f
                        break
                if name_field: break
            
            if not name_field: 
                self.log(self._t("  ⚠️ 경고: 유적 명칭 필드를 찾을 수 없어 건너뜁니다.", "  ⚠️ Name field not found, skipping layer."))
                continue
                
            self.log(self._t(f"  - 명칭 필드 식별됨: {name_field}", f"  - Name field detected: {name_field}"))
            
            layer_feats = 0
            for feat in layer.getFeatures():
                layer_feats += 1
                total_feats += 1
                name = feat[name_field]
                if name is None:
                    continue
                name = str(name)

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
            
            self.log(self._t(f"  - {layer_feats}개 객체 중 {matched_feats}개 매칭 성공", f"  - {matched_feats} matched out of {layer_feats} features"))
        
        self.log(self._t(f"✅ 전체 스캔 완료: 총 {matched_feats}/{total_feats} 건 매칭됨.", f"✅ Scan complete: {matched_feats}/{total_feats} matched."))
        
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
            self.listEras.addItem(self._t("식별실패", "No match"))

        # Populate List - Type
        if found_types:
            for t in sorted(list(found_types)):
                item = QListWidgetItem(t)
                item.setData(QtCore.Qt.UserRole, f"TYPE:{t}")
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Checked)
                self.listTypes.addItem(item)
        else:
            self.listTypes.addItem(self._t("식별실패", "No match"))
            
        # [NEW] Populate Exclusion List
        if found_exclusions:
            for exc in sorted(list(found_exclusions)):
                item = QListWidgetItem(exc)
                item.setData(QtCore.Qt.UserRole, exc) # Store exact name to exclude
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Checked) # Default to Checked (Exclude)
                self.listExclusions.addItem(item)
            self.log(
                self._t(
                    f"⚠️ {len(found_exclusions)}개의 제외 의심 항목이 발견되었습니다. '제외 제안 목록'을 확인하세요.",
                    f"⚠️ {len(found_exclusions)} suspicious exclusion items found. Check 'Suggested Exclusions'.",
                )
            )
        else:
            self.listExclusions.addItem(self._t("(제외 대상 없음)", "(No exclusion candidates)"))


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

    def show_scrollable_help_dialog(self, title, html_text):
        """Show long help text in a scrollable dialog."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(860, 700)

        layout = QtWidgets.QVBoxLayout(dialog)
        browser = QtWidgets.QTextBrowser(dialog)
        browser.setOpenExternalLinks(True)
        browser.setHtml(html_text)
        layout.addWidget(browser)

        close_btn = QtWidgets.QPushButton(self._t("닫기", "Close"), dialog)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=QtCore.Qt.AlignRight)

        exec_fn = getattr(dialog, "exec", None) or getattr(dialog, "exec_", None)
        if exec_fn:
            exec_fn()

    def _get_noise_keyword_examples(self, limit=6):
        """Return exclusion keyword examples from smart_patterns.json."""
        defaults = (
            ["지표", "참관", "수습", "현상변경", "배수로", "보호수"]
            if self.ui_lang == "ko"
            else ["surface", "attendance", "collection", "permit", "drain", "protected tree"]
        )
        patterns_path = os.path.join(os.path.dirname(__file__), "smart_patterns.json")
        try:
            with open(patterns_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            noise_keywords = data.get("noise", [])
            if isinstance(noise_keywords, list):
                cleaned = [str(x).strip() for x in noise_keywords if str(x).strip()]
                if cleaned:
                    return cleaned[:limit]
        except Exception:
            pass
        return defaults[:limit]

    def show_help(self):
        """Display User Guide and Export Tips."""
        examples = self._get_noise_keyword_examples()
        noise_examples = ", ".join(f"<code>{kw}</code>" for kw in examples)
        if self.ui_lang == "en":
            help_text = """
<h3>User Guide & Notes</h3>
<hr>
<b>[Workflow]</b><br>
<ol>
<li><b>Prepare layers:</b> Load study area (Polygon), topographic layers, and heritage layers.</li>
<li><b>Select layers:</b> In the Data tab, choose study area, topo, heritage, and optional zone layer.</li>
<li><b>Set extent/scale:</b> Input paper size and scale (report/A4 presets available).</li>
<li><b>Smart scan:</b> Click [Run Attribute Scan] to classify era/type candidates.</li>
<li><b>Run:</b> Click [Run Analysis / Generate Map].</li>
<li><b>Renumber:</b> After edits/deletions, use [Refresh numbering] in Style tab.</li>
</ol>
<br>
<b>[View results]</b><br>
When processing completes, map canvas auto-zooms to extent.<br>
If nothing appears, check visibility of <b>ArchDistribution_결과물</b> and try <b>Zoom to Layer</b>.<br><br>
<b>[Zone option]</b><br>
If a Zone layer is selected, features are automatically split/styled by zone code.<br>
Option <b>Clip to buffer extent</b> keeps only features inside the largest buffer (Extent ∩ Buffer).<br><br>
<b>[Numbering tips]</b><br>
<ul>
<li>Buffer-tier numbering is applied only when sort order is distance-based.</li>
<li>If "Exclude outside buffer" is checked, features outside max buffer may stay unnumbered.</li>
</ul>
<br>
<b>[Suggested Exclusions]</b><br>
Exclusion suggestions are generated from <code>smart_patterns.json</code> <code>noise</code> keywords.<br>
Example: {noise_examples}<br>
These are suggestions only. You can uncheck to include features.<br><br>
<b>[Export tip]</b><br>
For Illustrator workflows, export separate PDFs by layer visibility and combine later for cleaner editing.<br><br>
<b>[Disclaimer]</b><br>
This plugin automates repetitive GIS tasks but final QA remains user's responsibility.<br>
Please verify geometry/attributes before reporting or legal use.<br><br>
<b>[Cache/Reload]</b><br>
If updates are not reflected, disable/enable the plugin or restart QGIS.<br>
<div style='color: #7f8c8d; font-size: 11px;'>ArchDistribution v{version}</div>
"""
        else:
            help_text = """
<h3>사용 가이드 및 유의사항 (User Guide)</h3>
<hr>
<b>[작업 순서 (Workflow)]</b><br>
<ol>
<li><b>레이어 준비:</b> 조사지역(Polygon), 수치지형도, 주변유적 레이어를 불러옵니다.</li>
<li><b>레이어 선택:</b> [데이터 탭]에서 조사지역, 지형도, 유적 레이어를 선택합니다.</li>
<li><b>도곽/축척 설정:</b> 도면 가로/세로(mm)와 축척을 입력합니다. (프리셋 활용 추천)</li>
<li><b>스마트 분류:</b> [속성 분류 실행] 버튼으로 유적을 시대/유형별로 분류합니다.</li>
<li><b>분석 실행:</b> [▶ 분석 및 지도 생성 실행] 클릭으로 자동 처리합니다.</li>
<li><b>번호 새로고침:</b> 유적 삭제/수정 후 [스타일 탭 > 번호 새로고침]으로 번호 재정렬</li>
</ol>
<br>
<b>[결과 확인 (View)]</b><br>
작업이 끝나면 <b>도곽(Extent) 범위로 화면이 자동 확대(여백 포함)</b>되어 결과물을 바로 확인할 수 있습니다.<br>
만약 화면이 비어 보이면 레이어 패널에서 <b>ArchDistribution_결과물</b> 그룹의 체크(가시성)를 확인하고,<br>
개별 레이어 우클릭 → <b>레이어로 확대(Zoom to Layer)</b>를 시도해 주세요.
<br><br>
<b>[현상변경허용기준(Zone) 옵션]</b><br>
현상변경허용기준 레이어를 선택하면, 도곽 내에서 자동 분할/스타일링을 수행합니다.<br>
<ul>
<li><b>버퍼 범위 내 자르기</b>: 가장 큰 버퍼(최대 반경) 범위 안에 포함되는 구역만 남깁니다. (도곽 ∩ 버퍼)</li>
</ul>
<br>
<b>[번호 부여 팁]</b><br>
<ul>
<li><b>버퍼 구간별 번호 부여</b>는 정렬 기준이 <b>거리순</b>일 때만 적용됩니다.</li>
<li><b>버퍼 밖 제외</b> 옵션을 켜면, 최대 버퍼 밖 유적은 번호가 비워질 수 있습니다.</li>
</ul>
<br>
<b>[제외 제안 목록 안내]</b><br>
제외 제안 목록은 <code>smart_patterns.json</code>의 <code>noise</code> 키워드를 기준으로 자동 표시됩니다.<br>
예: {noise_examples}<br>
이 목록은 자동 확정이 아니라 제안이므로, 현장 판단에 따라 체크를 해제해 포함할 수 있습니다.<br>
최종 결과는 작업 마지막에 [번호 새로고침]으로 정리하는 것을 권장합니다.
<br><br>
<b>[일러스트레이터(AI) 반출 꿀팁]</b><br>
보고서 편집을 위해 결과물을 일러스트레이터로 가져가실 때 추천하는 방법입니다:
<ol>
<li>QGIS 상단 메뉴의 <b>'프로젝트 > 새 인쇄 조판'</b>을 엽니다.</li>
<li>생성된 분포지도를 추가하고, <b>PDF로 내보내기</b>를 합니다.</li>
<li><b>Tip:</b> 레이어(지형도, 유적, 버퍼 등)를 <u>하나씩만 켜서 각각 PDF로 저장</u>한 뒤,<br> 
일러스트레이터에서 합치면 레이어가 섞이지 않아 편집이 훨씬 수월합니다.</li>
</ol>
<br>
<b>[유의사항 (Disclaimer)]</b><br>
본 플러그인은 좌표계 변환 및 데이터 병합을 자동화하여 사용자의 편의를 돕는 도구입니다.<br>
<ul>
<li>사용자마다 QGIS 환경(좌표계 설정 등)이 다르므로, <b>반드시 결과물의 위치와 속성을 육안으로 검수</b>해주시기 바랍니다.</li>
<li>자동 생성된 유적 번호나 위치가 의도와 다를 수 있으므로, <b>[번호 새로고침]</b> 기능 등을 활용하여 최종 확인 후 사용하세요.</li>
<li><b style='color:red'>번호 새로고침 시 현재 설정된 축척/도곽 범위에 맞춰 번호가 재할당됩니다. 반드시 축척을 확인하세요.</b></li>
</ul>
<br>
<b>[업데이트/캐시]</b><br>
코드가 갱신되었는데도 동작이 예전과 같다면, <b>플러그인 관리자에서 비활성화→활성화</b> 또는 <b>QGIS 재시작</b>을 해주세요.
<br>
<div style='color: #7f8c8d; font-size: 11px;'>ArchDistribution v{version}</div>
"""
        help_text = help_text.format(
            version=get_plugin_version(),
            noise_examples=noise_examples,
        )
        self.show_scrollable_help_dialog(self._t("ArchDistribution 사용 가이드", "ArchDistribution User Guide"), help_text)

    def run_analysis(self):
        """Backward-compatible wrapper for older signal connections."""
        self.emit_run_requested()
