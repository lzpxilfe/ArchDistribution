import os

from qgis.PyQt import uic, QtCore, QtGui
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QListWidgetItem, QColorDialog
from qgis.core import QgsProject
from qgis.utils import iface # [CRITICAL FIX] Import global iface

# This loads your .ui file so that PyQt can populate your plugin with the elements from Qt Designer
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'arch_distribution_dialog_base.ui'))

class ArchDistributionDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(ArchDistributionDialog, self).__init__(parent)
        self.setupUi(self)

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

        # Presets
        self.btnPresetReport.clicked.connect(lambda: self.apply_preset(160, 240))
        self.btnPresetA4.clicked.connect(lambda: self.apply_preset(210, 297))

        # Initialize layers
        self.populate_layers()

    # Custom signal for execution
    run_requested = QtCore.pyqtSignal(dict)
    renumber_requested = QtCore.pyqtSignal(object) # Passing QgsVectorLayer

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
            "sort_order": self.comboSortOrder.currentIndex()
        }
