from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

import os.path

class ArchDistribution:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = QCoreApplication.translate('ArchDistribution', '&ArchDistribution')
        self.toolbar = self.iface.addToolBar('ArchDistribution')
        self.toolbar.setObjectName('ArchDistribution')

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.add_action(
            icon_path,
            text=QCoreApplication.translate('ArchDistribution', 'Cultural Heritage Distribution Map'),
            callback=self.run,
            parent=self.iface.mainWindow())

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(
                QCoreApplication.translate('ArchDistribution', '&ArchDistribution'),
                action)
            self.iface.removeToolBarIcon(action)

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
        self.iface.messageBar().pushMessage("ArchDistribution", "Plugin Started!", level=0)
