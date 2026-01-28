import os

from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QFileDialog, QListWidgetItem
from qgis.core import QgsProject, QgsMapLayerProxyModel

# This loads your .ui file so that PyQt can populate your plugin with the elements from Qt Designer
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'arch_distribution_dialog_base.ui'))

class ArchDistributionDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(ArchDistributionDialog, self).__init__(parent)
        self.setupUi(self)

        # Connect signals
        self.btnAddTopo.clicked.connect(self.select_topo_files)
        self.btnRemoveTopo.clicked.connect(self.remove_selected_topo)
        self.btnAddHeritage.clicked.connect(self.select_heritage_files)
        self.btnRemoveHeritage.clicked.connect(self.remove_selected_heritage)

        # Initialize Study Area combo with vector layers
        self.populate_layers()

    def populate_layers(self):
        self.comboStudyArea.clear()
        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if layer.type() == 0:  # VectorLayer
                self.comboStudyArea.addItem(layer.name(), layer.id())

    def select_topo_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "수치지형도 선택", "", "DXF Files (*.dxf);;SHP Files (*.shp);;All Files (*)")
        if files:
            for f in files:
                self.listTopoMaps.addItem(f)

    def remove_selected_topo(self):
        for item in self.listTopoMaps.selectedItems():
            self.listTopoMaps.takeItem(self.listTopoMaps.row(item))

    def select_heritage_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "문화유산 SHP 선택", "", "SHP Files (*.shp);;All Files (*)")
        if files:
            for f in files:
                self.listHeritageMaps.addItem(f)

    def remove_selected_heritage(self):
        for item in self.listHeritageMaps.selectedItems():
            self.listHeritageMaps.takeItem(self.listHeritageMaps.row(item))

    def get_settings(self):
        """Returns the current settings from the dialog."""
        topo_files = [self.listTopoMaps.item(i).text() for i in range(self.listTopoMaps.count())]
        heritage_files = [self.listHeritageMaps.item(i).text() for i in range(self.listHeritageMaps.count())]
        
        study_area_id = self.comboStudyArea.currentData()
        buffer_str = self.editBuffers.text()
        buffers = [float(b.strip()) for b in buffer_str.split(',') if b.strip()]
        
        return {
            "topo_files": topo_files,
            "heritage_files": heritage_files,
            "study_area_id": study_area_id,
            "buffers": buffers,
            "paper_width": self.spinWidth.value(),
            "paper_height": self.spinHeight.value(),
            "scale": self.spinScale.value(),
            "sort_order": self.comboSortOrder.currentIndex()
        }
