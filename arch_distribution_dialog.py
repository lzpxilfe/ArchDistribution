import os

from qgis.PyQt import uic, QtCore, QtGui
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QListWidgetItem, QColorDialog
from qgis.core import QgsProject

# This loads your .ui file so that PyQt can populate your plugin with the elements from Qt Designer
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'arch_distribution_dialog_base.ui'))

class ArchDistributionDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(ArchDistributionDialog, self).__init__(parent)
        self.setupUi(self)

        # Default colors
        self.heritage_stroke_color = QtGui.QColor(0, 0, 0)
        self.heritage_fill_color = QtGui.QColor(255, 0, 0)
        self.study_stroke_color = QtGui.QColor(255, 0, 0)
        
        self.update_button_colors()

        # Connect signals
        self.btnHeritageStrokeColor.clicked.connect(lambda: self.pick_color('heritage_stroke'))
        self.btnHeritageFillColor.clicked.connect(lambda: self.pick_color('heritage_fill'))
        self.btnStudyStrokeColor.clicked.connect(lambda: self.pick_color('study_stroke'))
        self.btnAddBuffer.clicked.connect(self.add_buffer_to_list)
        self.listBuffers.itemDoubleClicked.connect(self.remove_buffer_from_list)

        # Initialize layers
        self.populate_layers()

    def update_button_colors(self):
        self.btnHeritageStrokeColor.setStyleSheet(f"background-color: {self.heritage_stroke_color.name()};")
        self.btnHeritageFillColor.setStyleSheet(f"background-color: {self.heritage_fill_color.name()};")
        self.btnStudyStrokeColor.setStyleSheet(f"background-color: {self.study_stroke_color.name()};")

    def pick_color(self, target):
        color = QColorDialog.getColor()
        if color.isValid():
            if target == 'heritage_stroke': self.heritage_stroke_color = color
            elif target == 'heritage_fill': self.heritage_fill_color = color
            elif target == 'study_stroke': self.study_stroke_color = color
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

    def remove_buffer_from_list(self, item):
        self.listBuffers.takeItem(self.listBuffers.row(item))

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
            "paper_width": self.spinWidth.value(),
            "paper_height": self.spinHeight.value(),
            "scale": self.spinScale.value(),
            "sort_order": self.comboSortOrder.currentIndex()
        }
