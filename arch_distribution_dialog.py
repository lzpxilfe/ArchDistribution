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
    except:
        pass
    return "1.0.1"  # Fallback


class ArchDistributionDialog(QtWidgets.QDialog, FORM_CLASS):
    # Define signals
    run_requested = QtCore.pyqtSignal(dict)
    renumber_requested = QtCore.pyqtSignal(dict)
    scan_requested = QtCore.pyqtSignal(dict)

    def __init__(self, parent=None):
        """Constructor."""
        super(ArchDistributionDialog, self).__init__(parent)
        self.setupUi(self) # [CRITICAL FIX] Restore UI initialization

        # [MOVED FROM HERE]
        # make_tab_scrollable logic moved to end of __init__


        # [NEW] Programmatically add missing UI elements for Smart Filter
        self.groupSmartFilter = QtWidgets.QGroupBox(self.tr("Heritage Attribute Classification"))
        self.vSmartLayout = QtWidgets.QVBoxLayout()
        
        self.lSmartDesc = QtWidgets.QLabel(self.tr("Analyzes names of checked heritage layers to auto-classify era and type."))
        self.lSmartDesc.setStyleSheet("color: #555; font-size: 10px;")
        
        self.btnSmartScan = QtWidgets.QPushButton(self.tr("Run Attribute Classification"))
        self.btnSmartScan.setStyleSheet("background-color: #f39c12; color: white; font-weight: bold; padding: 5px;")
        
        # Split UI into two columns
        self.hSmartLists = QtWidgets.QHBoxLayout()
        
        # Era Column
        self.vEras = QtWidgets.QVBoxLayout()
        self.lblEra = QtWidgets.QLabel(self.tr("Era"))
        self.lblEra.setStyleSheet("font-weight: bold; color: #333;")
        self.listEras = QtWidgets.QListWidget()
        self.listEras.setMinimumHeight(130) # Reduced from 200
        self.vEras.addWidget(self.lblEra)
        self.vEras.addWidget(self.listEras)
        
        # Type Column
        self.vTypes = QtWidgets.QVBoxLayout()
        self.lblType = QtWidgets.QLabel(self.tr("Type"))
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
        self.lblExclusion = QtWidgets.QLabel(self.tr("Exclusion Candidates (checked items excluded):"))
        self.lblExclusion.setStyleSheet("font-weight: bold; color: #c0392b; margin-top: 10px;")
        self.listExclusions = QtWidgets.QListWidget()
        self.listExclusions.setMinimumHeight(80) # Reduced from 100
        self.listExclusions.setStyleSheet("color: #c0392b;") # Red text for danger
        
        self.vSmartLayout.addWidget(self.lblExclusion)
        self.vSmartLayout.addWidget(self.listExclusions)
        
        self.groupSmartFilter.setLayout(self.vSmartLayout)
        
        # [NEW] Zone Layer Selection (Optional)
        self.lblZoneLayer = QtWidgets.QLabel(self.tr("Zone Boundary Layer (Optional):"))
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
            self.chkClipZoneToBuffer = QtWidgets.QCheckBox(self.tr("Clip to buffer range (show within radius only)"))
            self.chkClipZoneToBuffer.setToolTip(self.tr("When checked, only zone boundaries within the largest buffer radius are kept."))
            self.chkClipZoneToBuffer.setChecked(False) # Default Off
            self.vZoneLayout.addWidget(self.chkClipZoneToBuffer)
            
            # Convert layout to widget to insert? No, insertLayout works for Box Layouts usually.
            # QLayout.insertLayout(index, layout)
            self.vTab1.insertLayout(1, self.vZoneLayout)
            
        # Insert into the first tab layout (vTab1) before the Spec group (item index 1)
        if hasattr(self, 'vTab1'):
            self.vTab1.insertWidget(2, self.groupSmartFilter) # Adjusted index

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
        self.spinTopoStrokeWidth.setValue(0.05) # Traditional topo line weight
        self.spinBufferWidth.setValue(0.3) # Default buffer width
        self.spinWidth.setValue(210) # A4 width
        self.spinHeight.setValue(297) # A4 height
        self.spinScale.setValue(5000)
        self.spinScale.setSingleStep(500) # [FIX] User Request: 500 unit step
        self.comboSortOrder.setCurrentIndex(0)
        self.tabWidget.setCurrentIndex(0)
        
        
        self.update_button_colors()

        # [CRITICAL FIX] Explicitly populate dropdowns in Python to guarantee items exist
        self.comboBufferStyle.clear()
        self.comboBufferStyle.addItems([self.tr("Solid"), self.tr("Dot"), self.tr("Dash")])
        
        self.comboSortOrder.clear()
        self.comboSortOrder.addItems([self.tr("Top to Bottom (N to S)"), self.tr("Closest to Study Area (Distance)"), self.tr("Alphabetical (Site Name)")])

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
        
        self.chkRestrictToBuffer = QtWidgets.QCheckBox(self.tr("Exclude heritage outside buffer (hide)"))
        self.chkRestrictToBuffer.setToolTip(self.tr("Checked: Heritage sites outside the outermost buffer are hidden.\nUnchecked: All heritage sites are numbered."))
        self.chkRestrictToBuffer.setChecked(False) # [FIX] Default to Unchecked (User Request)
        self.chkRestrictToBuffer.setStyleSheet("font-weight: bold; color: #d35400;")
        
        # Insert into vTab1 at index 1
        if hasattr(self, 'vTab1'):
             self.vTab1.insertWidget(1, self.chkRestrictToBuffer)

        self.btnRun.clicked.connect(self.run_analysis) # [FIX] Connect logic

        # [NEW] Label Font Controls
        self.groupLabelStyle = QtWidgets.QGroupBox(self.tr("Label Style"))
        self.hLabelLayout = QtWidgets.QHBoxLayout()
        
        self.lblFontSize = QtWidgets.QLabel(self.tr("Font Size:"))
        self.spinLabelFontSize = QtWidgets.QSpinBox()
        self.spinLabelFontSize.setRange(6, 72)
        self.spinLabelFontSize.setValue(10)
        self.spinLabelFontSize.setToolTip(self.tr("Heritage number label font size (pt)"))
        
        self.lblFontFamily = QtWidgets.QLabel(self.tr("Font Family:"))
        self.comboLabelFont = QtWidgets.QFontComboBox()
        self.comboLabelFont.setCurrentFont(QtGui.QFont("맑은 고딕"))
        self.comboLabelFont.setToolTip(self.tr("Heritage number label font family"))
        
        self.hLabelLayout.addWidget(self.lblFontSize)
        self.hLabelLayout.addWidget(self.spinLabelFontSize)
        self.hLabelLayout.addWidget(self.lblFontFamily)
        self.hLabelLayout.addWidget(self.comboLabelFont)
        self.groupLabelStyle.setLayout(self.hLabelLayout)
        
        if hasattr(self, 'vTab1'):
             self.vTab1.insertWidget(2, self.groupLabelStyle) 

        # [NEW] Enable Extended Selection for Lists
        self.listHeritageLayers.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.listTopoLayers.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.listEras.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.listTypes.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.listExclusions.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection) # Allow Shift-Select
        
        # [NEW] Add Batch Buttons for Exclusion List
        # We'll insert this into the layout that holds listExclusions (which is likely inside groupSmartFilter).
        # Since we don't have direct access to that auto-generated layout object easily, 
        # we'll create a new layout and insert it into the groupSmartFilter layout.
        if hasattr(self, 'groupSmartFilter') and self.groupSmartFilter.layout():
             self.hExclusionBtns = QtWidgets.QHBoxLayout()
             self.btnExcludeSel = QtWidgets.QPushButton(self.tr("Exclude Selected (Check)"))
             self.btnIncludeSel = QtWidgets.QPushButton(self.tr("Include Selected (Uncheck)"))
             self.btnExcludeSel.setToolTip(self.tr("Check selected items in the list (excluded from map)."))
             self.btnIncludeSel.setToolTip(self.tr("Uncheck selected items (included in map)."))
             
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
        self.btnPresetReport.clicked.connect(lambda: self.apply_preset(160, 240))
        self.btnPresetA4.clicked.connect(lambda: self.apply_preset(210, 297))

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
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff) # Only vertical scroll
        
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

    def set_list_check_state(self, list_widget, checked):
        """Batch set check state for selected items in a list widget."""
        for item in list_widget.selectedItems():
            item.setCheckState(QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked)

    def set_batch_check(self, list_widget, checked):
        """Legacy helper for Topo/Heritage layers."""
        for i in range(list_widget.count()):
            list_widget.item(i).setCheckState(QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked)


    # Custom signal for execution
    run_requested = QtCore.pyqtSignal(dict)
    renumber_requested = QtCore.pyqtSignal(object) # Passing QgsVectorLayer
    scan_requested = QtCore.pyqtSignal(dict) # [NEW]

    # [FIX] Batch Check Implementation with Selection Support
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
            
        state = QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked
        for item in items_to_process:
            item.setCheckState(state)

    def emit_run_requested(self):
        """Validates settings and emits the run signal."""
        settings = self.get_settings()
        if not settings['study_area_id']:
            QtWidgets.QMessageBox.warning(self, self.tr("Input Error"), self.tr("Please select a study area layer."))
            return
        self.run_requested.emit(settings)

    def log(self, message):
        """Append a message to the log window and scroll to bottom."""
        self.txtLogs.appendPlainText(message)
        # Scroll to bottom
        cursor = self.txtLogs.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
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
            self.lblCurrentScale.setText(self.tr("1:{scale} (verify after deleting sites!)").format(scale=scale))

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
        self.log(self.tr("Paper size set: {w} x {h} mm").format(w=w, h=h))

    def remove_buffer_from_list(self, item):
        self.listBuffers.takeItem(self.listBuffers.row(item))

    def renumber_current_layer(self):
        """Renumber the features of the currently selected layer."""
        layer = iface.activeLayer() # [CRITICAL FIX] Use global iface
        if not layer or layer.type() != 0: # Check if vector layer
             QtWidgets.QMessageBox.warning(self, self.tr("Selection Error"), self.tr("Please select (activate) a heritage layer before running."))
             return
             
        # Check for '번호' field
        if layer.fields().indexFromName("번호") == -1:
             QtWidgets.QMessageBox.warning(self, self.tr("Compatibility Error"), self.tr("Selected layer does not have a '번호' field.\nPlease verify it was generated by ArchDistribution."))
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
                item_topo.setData(QtCore.Qt.ItemDataRole.UserRole, layer.id())
                item_topo.setFlags(item_topo.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item_topo.setCheckState(QtCore.Qt.CheckState.Unchecked)
                self.listTopoLayers.addItem(item_topo)

                item_heritage = QListWidgetItem(layer.name())
                item_heritage.setData(QtCore.Qt.ItemDataRole.UserRole, layer.id())
                item_heritage.setFlags(item_heritage.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item_heritage.setCheckState(QtCore.Qt.CheckState.Unchecked)
                self.listHeritageLayers.addItem(item_heritage)

    def get_settings(self):
        """Returns the current settings from the dialog."""
        topo_layer_ids = [self.listTopoLayers.item(i).data(QtCore.Qt.ItemDataRole.UserRole) 
                          for i in range(self.listTopoLayers.count()) 
                          if self.listTopoLayers.item(i).checkState() == QtCore.Qt.CheckState.Checked]

        heritage_layer_ids = [self.listHeritageLayers.item(i).data(QtCore.Qt.ItemDataRole.UserRole) 
                             for i in range(self.listHeritageLayers.count()) 
                             if self.listHeritageLayers.item(i).checkState() == QtCore.Qt.CheckState.Checked]
        
        buffers = [float(self.listBuffers.item(i).text()) for i in range(self.listBuffers.count())]
        
        filter_items = self.get_checked_items(None)
        has_filter_tags = False
        for i in range(self.listEras.count()):
            data = self.listEras.item(i).data(QtCore.Qt.ItemDataRole.UserRole)
            if isinstance(data, str) and data.startswith("ERA:"):
                has_filter_tags = True
                break
        if not has_filter_tags:
            for i in range(self.listTypes.count()):
                data = self.listTypes.item(i).data(QtCore.Qt.ItemDataRole.UserRole)
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
            "exclusion_list": [self.listExclusions.item(i).data(QtCore.Qt.ItemDataRole.UserRole) 
                               for i in range(self.listExclusions.count()) 
                               if self.listExclusions.item(i).checkState() == QtCore.Qt.CheckState.Checked],
            # [NEW] Restrict Toggle
            "restrict_to_buffer": self.chkRestrictToBuffer.isChecked(),
            # [NEW] Zone Layer ID
            "zone_layer_id": self.comboZoneLayer.currentLayer().id() if self.comboZoneLayer.currentLayer() else None,
            "clip_zone_to_buffer": self.chkClipZoneToBuffer.isChecked() if hasattr(self, "chkClipZoneToBuffer") else False,
            # [NEW] Label Style
            "label_font_size": self.spinLabelFontSize.value(),
            "label_font_family": self.comboLabelFont.currentFont().family()
        }

    def load_reference_data(self):
        """Load reference data from JSON file."""
        import json
        json_path = os.path.join(os.path.dirname(__file__), 'reference_data.json')
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    self.reference_data = json.load(f)
                self.log(self.tr("Reference data loaded: {count} entries").format(count=len(self.reference_data)))
            except Exception as e:
                self.log(self.tr("Reference data load failed: {e}").format(e=str(e)))
        else:
            self.log(self.tr("Reference data file not found. (reference_data.json)"))
            
        # [NEW] Load Smart Patterns
        json_pattern_path = os.path.join(os.path.dirname(__file__), 'smart_patterns.json')
        self.smart_patterns = {"noise": [], "artifacts": {}}
        if os.path.exists(json_pattern_path):
            try:
                with open(json_pattern_path, 'r', encoding='utf-8') as f:
                    self.smart_patterns = json.load(f)
                self.log(self.tr("Smart filter patterns loaded."))
            except Exception as e:
                self.log(self.tr("Smart filter pattern load failed: {e}").format(e=str(e)))

    def scan_categories(self):
        """Identify categories and potential exclusions using Smart Patterns."""
        self.listEras.clear()
        self.listTypes.clear()
        self.listExclusions.clear()
        
        heritage_layer_ids = [self.listHeritageLayers.item(i).data(QtCore.Qt.ItemDataRole.UserRole) 
                             for i in range(self.listHeritageLayers.count()) 
                             if self.listHeritageLayers.item(i).checkState() == QtCore.Qt.CheckState.Checked]
        
        if not heritage_layer_ids:
            QtWidgets.QMessageBox.warning(self, self.tr("Selection Error"), self.tr("Please check heritage layers to analyze first."))
            return

        found_eras = set()
        found_types = set()
        found_exclusions = set() # Store unique names to exclude
        
        total_feats = 0
        matched_feats = 0

        for lid in heritage_layer_ids:
            layer = QgsProject.instance().mapLayer(lid)
            if not layer: continue
            
            self.log(self.tr("Scanning layer: {name}").format(name=layer.name()))

            # [Auto-Fix] Check for Encoding Issues (Mojibake)
            fields = [f.name() for f in layer.fields()]
            needs_encoding_fix = any('\ufffd' in f for f in fields)
            
            if needs_encoding_fix:
                self.log(self.tr("  Warning: Encoding corruption detected. Attempting CP949 auto-conversion."))
                layer.setProviderEncoding("CP949")
                layer.dataProvider().reloadData()
                fields = [f.name() for f in layer.fields()]
                self.log(self.tr("  - Fields after conversion: {fields}").format(fields=', '.join(fields)))
            else:
                self.log(self.tr("  - Fields: {fields}").format(fields=', '.join(fields)))
            
            name_field = None
            keywords = ['유적명', '명칭', '명', '이름', 'NAME', 'SITE', 'TITLE']
            
            for f in fields:
                for k in keywords:
                    if k in f.upper():
                        name_field = f
                        break
                if name_field: break
            
            if not name_field: 
                self.log(self.tr("  Warning: Heritage name field not found, skipping."))
                continue
                
            self.log(self.tr("  - Name field identified: {field}").format(field=name_field))
            
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
            
            self.log(f"  - {layer_feats}개 객체 중 {matched_feats}개 매칭 성공")
        
        self.log(self.tr("Scan complete: {matched}/{total} features matched.").format(matched=matched_feats, total=total_feats))
        
        # Populate List - Era
        if found_eras:
            # Sort Era? Custom sort order would be nice but alphabetical for now
            for era in sorted(list(found_eras)):
                item = QListWidgetItem(era)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, f"ERA:{era}")
                item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.CheckState.Checked)
                self.listEras.addItem(item)
        else:
            self.listEras.addItem(self.tr("Identification failed"))

        # Populate List - Type
        if found_types:
            for t in sorted(list(found_types)):
                item = QListWidgetItem(t)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, f"TYPE:{t}")
                item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.CheckState.Checked)
                self.listTypes.addItem(item)
        else:
            self.listTypes.addItem(self.tr("Identification failed"))
            
        # [NEW] Populate Exclusion List
        if found_exclusions:
            for exc in sorted(list(found_exclusions)):
                item = QListWidgetItem(exc)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, exc) # Store exact name to exclude
                item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.CheckState.Checked) # Default to Checked (Exclude)
                self.listExclusions.addItem(item)
            self.log(self.tr("{count} suspected exclusion items found. Check the exclusion list.").format(count=len(found_exclusions)))
        else:
            self.listExclusions.addItem(self.tr("(No exclusion candidates)"))


    def get_checked_items(self, _ignored):
        """Return list of checked items data from both Era and Type lists."""
        checked = []
        # Check Eras
        for i in range(self.listEras.count()):
            item = self.listEras.item(i)
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                checked.append(item.data(QtCore.Qt.ItemDataRole.UserRole))
        
        # Check Types
        for i in range(self.listTypes.count()):
            item = self.listTypes.item(i)
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                checked.append(item.data(QtCore.Qt.ItemDataRole.UserRole))
                
        return checked

    def show_help(self):
        """Display User Guide and Export Tips."""
        help_text = self.tr("""
<h3>User Guide & Notes</h3>
<hr>
<b>[Workflow]</b><br>
<ol>
<li><b>Prepare Layers:</b> Load study area (polygon), topo maps, and heritage site layers.</li>
<li><b>Select Layers:</b> In the [Data] tab, select study area, topo, and heritage layers.</li>
<li><b>Set Extent/Scale:</b> Enter paper width/height (mm) and scale. (Presets recommended)</li>
<li><b>Smart Classification:</b> Click [Run Attribute Classification] to auto-classify heritage by era/type.</li>
<li><b>Run Analysis:</b> Click [Run Analysis & Map Generation] for automated processing.</li>
<li><b>Refresh Numbering:</b> After editing sites, use [Style tab > Refresh Numbering] to reorder.</li>
</ol>
<br>
<b>[View Results]</b><br>
After processing, the map canvas <b>auto-zooms to the extent (with padding)</b> to display results.<br>
If the view appears empty, check the <b>ArchDistribution_Results</b> group visibility in the Layers panel,<br>
and try right-clicking individual layers > <b>Zoom to Layer</b>.
<br><br>
<b>[Zone Boundary Options]</b><br>
When a zone boundary layer is selected, it is automatically split and styled within the extent.<br>
<ul>
<li><b>Clip to Buffer:</b> Keeps only zones within the largest buffer radius. (Extent intersect Buffer)</li>
</ul>
<br>
<b>[Numbering Tips]</b><br>
<ul>
<li><b>Buffer-tiered numbering</b> only applies when sort order is set to <b>Distance</b>.</li>
<li><b>Exclude outside buffer</b> option hides sites beyond the maximum buffer.</li>
</ul>
<br>
<b>[Illustrator (AI) Export Tips]</b><br>
To bring results into Illustrator for report editing:
<ol>
<li>Open QGIS menu <b>Project > New Print Layout</b>.</li>
<li>Add the distribution map and <b>export as PDF</b>.</li>
<li><b>Tip:</b> Export each layer (topo, heritage, buffer) as <u>separate PDFs</u>,<br>
then combine in Illustrator for easier editing.</li>
</ol>
<br>
<b>[Disclaimer]</b><br>
This plugin automates CRS transforms and data merging for convenience.<br>
<ul>
<li>QGIS environments vary. <b>Always visually verify result positions and attributes.</b></li>
<li>Auto-generated numbering may differ from expectations. Use <b>[Refresh Numbering]</b> to verify.</li>
<li><b style='color:red'>Warning: Refreshing numbers reassigns based on current scale/extent. Verify scale first!</b></li>
</ul>
<br>
<b>[Updates/Cache]</b><br>
If behavior doesn't change after code updates, <b>disable/enable the plugin</b> or <b>restart QGIS</b>.
<br>
<div style='color: #7f8c8d; font-size: 11px;'>ArchDistribution v{version}</div>
""")
        help_text = help_text.format(version=get_plugin_version())
        QtWidgets.QMessageBox.information(self, self.tr("ArchDistribution User Guide"), help_text)

    def run_analysis(self):
        """Collect settings and emit run signal."""
        # Validation
        if self.comboStudyArea.currentIndex() == -1:
             QtWidgets.QMessageBox.warning(self, self.tr("Warning"), self.tr("Please select a study area layer."))
             return
             
        # Collection
        # Helper to get IDs from QListWidget
        def get_checked_ids(list_widget):
            ids = []
            for item in list_widget.selectedItems():
                val = item.data(QtCore.Qt.ItemDataRole.UserRole)
                if val: ids.append(val)
            return ids

        settings = {
            'study_area_id': self.comboStudyArea.currentData(),
            'topo_layer_ids': get_checked_ids(self.listTopoLayers),
            'heritage_layer_ids': get_checked_ids(self.listHeritageLayers),
            'paper_width': self.spinWidth.value(),
            'paper_height': self.spinHeight.value(),
            'scale': self.spinScale.value(),
            'buffers': [],
            # Styles
            'study_style': {
                'stroke_color': self.study_stroke_color.name(),
                'stroke_width': self.spinStudyStrokeWidth.value()
            },
            'topo_style': {
                'stroke_color': self.topo_stroke_color.name(),
                 'stroke_width': self.spinTopoStrokeWidth.value()
            },
            'buffer_style': {
                'color': self.buffer_color.name(),
                'width': self.spinBufferWidth.value(),
                'style': self.comboBufferStyle.currentIndex()
            },
            'heritage_style': {
                'stroke_color': self.heritage_stroke_color.name(),
                'fill_color': self.heritage_fill_color.name(),
                'stroke_width': self.spinHeritageStrokeWidth.value(),
                'opacity': self.spinHeritageOpacity.value() / 100.0,
                # [NEW] Font Settings
                'font_size': self.spinLabelFontSize.value(),
                'font_family': self.comboLabelFont.currentFont().family() # Using QFontComboBox
            },
            # Options
            'sort_order': self.comboSortOrder.currentIndex(),
            
            # [NEW] Zone Layer
            'zone_layer_id': self.comboZoneLayer.currentLayer().id() if self.comboZoneLayer.currentLayer() else None,
            
            # [NEW] Restrictions
            'restrict_to_buffer': self.chkRestrictToBuffer.isChecked(),
            'clip_zone_to_buffer': self.chkClipZoneToBuffer.isChecked(), # [NEW CHECKBOX]
            
            # Filter Lists
            'filter_eras': self.get_checked_items(self.listEras),
            'filter_types': self.get_checked_items(self.listTypes),
            'exclusion_list': [item.data(QtCore.Qt.ItemDataRole.UserRole) for item in self.listExclusions.findItems("*", QtCore.Qt.MatchFlag.MatchWildcard)]
        }
        
        # Collect Buffers
        for i in range(self.listBuffers.count()):
            item = self.listBuffers.item(i)
            try:
                val = float(item.text().replace("m", ""))
                settings['buffers'].append(val)
            except: pass
            
        settings['buffers'].sort(reverse=True) # Largest first
        
        self.run_requested.emit(settings)
        self.accept()
