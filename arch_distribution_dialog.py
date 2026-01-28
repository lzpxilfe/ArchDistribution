import os

from qgis.PyQt import uic, QtCore
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QListWidgetItem
from qgis.core import QgsProject

# This loads your .ui file so that PyQt can populate your plugin with the elements from Qt Designer
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'arch_distribution_dialog_base.ui'))

class ArchDistributionDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(ArchDistributionDialog, self).__init__(parent)
        self.setupUi(self)

        # Initialize Study Area combo with vector layers
        self.populate_layers()

    def populate_layers(self):
        self.comboStudyArea.clear()
        self.listTopoLayers.clear()
        self.listHeritageLayers.clear()

        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if layer.type() == 0:  # VectorLayer
                # Add to Study Area combo
                self.comboStudyArea.addItem(layer.name(), layer.id())
                
                # Add to Topo Map List (Checkable)
                item_topo = QListWidgetItem(layer.name())
                item_topo.setData(QtCore.Qt.UserRole, layer.id())
                item_topo.setFlags(item_topo.flags() | QtCore.Qt.ItemIsUserCheckable)
                item_topo.setCheckState(QtCore.Qt.Unchecked)
                self.listTopoLayers.addItem(item_topo)

                # Add to Heritage Map List (Checkable)
                item_heritage = QListWidgetItem(layer.name())
                item_heritage.setData(QtCore.Qt.UserRole, layer.id())
                item_heritage.setFlags(item_heritage.flags() | QtCore.Qt.ItemIsUserCheckable)
                item_heritage.setCheckState(QtCore.Qt.Unchecked)
                self.listHeritageLayers.addItem(item_heritage)

    def get_settings(self):
        """Returns the current settings from the dialog."""
        topo_layer_ids = []
        for i in range(self.listTopoLayers.count()):
            item = self.listTopoLayers.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                topo_layer_ids.append(item.data(QtCore.Qt.UserRole))

        heritage_layer_ids = []
        for i in range(self.listHeritageLayers.count()):
            item = self.listHeritageLayers.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                heritage_layer_ids.append(item.data(QtCore.Qt.UserRole))
        
        study_area_id = self.comboStudyArea.currentData()
        buffer_str = self.editBuffers.text()
        buffers = []
        try:
            buffers = [float(b.strip()) for b in buffer_str.split(',') if b.strip()]
        except ValueError:
            pass
        
        return {
            "topo_layer_ids": topo_layer_ids,
            "heritage_layer_ids": heritage_layer_ids,
            "study_area_id": study_area_id,
            "buffers": buffers,
            "paper_width": self.spinWidth.value(),
            "paper_height": self.spinHeight.value(),
            "scale": self.spinScale.value(),
            "sort_order": self.comboSortOrder.currentIndex()
        }
