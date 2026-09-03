import html
import json
import os
from pathlib import Path

from qgis.PyQt import uic, QtCore, QtGui
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QListWidgetItem, QColorDialog
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsMapLayerProxyModel,
    QgsProject,
    QgsUnitTypes,
)
from qgis.gui import (
    QgsMapLayerComboBox,
    QgsProjectionSelectionWidget,
)  # [NEW] Import
from qgis.utils import iface  # [CRITICAL FIX] Import global iface

from .preservation_actions import (
    PRESERVATION_ACTION_FIELD_CANDIDATES,
    PRESERVATION_ACTION_STYLES,
    recognized_preservation_actions,
)
from .map_legend_styles import normalize_change_zone_code
from .shapefile_encoding import declared_shapefile_encoding
from .heritage_matching import (
    MATCH_PRESET_LABELS,
    MATCH_PRESET_LABELS_EN,
    PRESET_BALANCED,
    ROLE_LOCAL_DESIGNATED,
    ROLE_NATIONAL_DESIGNATED,
    ROLE_PROTECTION_ZONE,
    SOURCE_ROLE_LABELS,
    SOURCE_ROLE_ORDER,
    detect_source_role,
    source_role_label,
)

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
    except (OSError, ValueError):
        return "unknown"
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
LANG_PREF_KEY = "ArchDistribution/ui_language"
LANG_PREF_OPTIONS = ("auto", "ko", "en")
PRESERVATION_STYLE_PREF_KEY = "ArchDistribution/preservation_action_styles"
MATCH_PRESET_PREF_KEY = "ArchDistribution/match_preset"
REUSE_REVIEW_PREF_KEY = "ArchDistribution/reuse_review_decisions"
OUTPUT_DIRECTORY_PREF_KEY = "ArchDistribution/output_directory"
SAVE_GPKG_PREF_KEY = "ArchDistribution/save_gpkg_manifest"
EXPORT_JPG_PREF_KEY = "ArchDistribution/export_layout_jpg"
EXPORT_PDF_PREF_KEY = "ArchDistribution/export_layout_pdf"
ANALYSIS_CRS_OVERRIDE_PREF_KEY = "ArchDistribution/analysis_crs_override"
ANALYSIS_CRS_DEFINITION_PREF_KEY = "ArchDistribution/analysis_crs_definition"
PRESERVATION_STYLE_ORDER = tuple(PRESERVATION_ACTION_STYLES)


def get_ui_language_preference():
    """Read persisted UI language preference."""
    pref = str(QtCore.QSettings().value(LANG_PREF_KEY, "auto")).strip().lower()
    return pref if pref in LANG_PREF_OPTIONS else "auto"


def detect_ui_language():
    """Detect UI language from QGIS locale or optional environment override."""
    forced = os.environ.get("ARCHDISTRIBUTION_LANG", "").strip().lower()
    if forced in ("ko", "en"):
        return forced

    pref = get_ui_language_preference()
    if pref in ("ko", "en"):
        return pref

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
        self.setupUi(self)  # [CRITICAL FIX] Restore UI initialization
        self._apply_static_ui_translation()
        self._add_language_selector()
        self._stabilize_data_panel_layout()

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
        self.listEras.setMinimumHeight(130)  # Reduced from 200
        self.vEras.addWidget(self.lblEra)
        self.vEras.addWidget(self.listEras)

        # Type Column
        self.vTypes = QtWidgets.QVBoxLayout()
        self.lblType = QtWidgets.QLabel(self._t("성격", "Type"))
        self.lblType.setStyleSheet("font-weight: bold; color: #333;")
        self.listTypes = QtWidgets.QListWidget()
        self.listTypes.setMinimumHeight(130)  # Reduced from 200
        self.vTypes.addWidget(self.lblType)
        self.vTypes.addWidget(self.listTypes)

        self.hSmartLists.addLayout(self.vEras)
        self.hSmartLists.addLayout(self.vTypes)

        self.vSmartLayout.addWidget(self.lSmartDesc)
        self.vSmartLayout.addWidget(self.btnSmartScan)
        self.vSmartLayout.addLayout(self.hSmartLists)  # Add the horizontal layout

        # [NEW] Exclusion Candidates List
        self.lblExclusion = QtWidgets.QLabel(self._t("제외 제안 목록 (체크시 제외됨):", "Suggested Exclusions (checked = exclude):"))
        self.lblExclusion.setStyleSheet("font-weight: bold; color: #c0392b; margin-top: 10px;")
        self.listExclusions = QtWidgets.QListWidget()
        self.listExclusions.setMinimumHeight(80)  # Reduced from 100
        self.listExclusions.setStyleSheet("color: #c0392b;")  # Red text for danger

        self.vSmartLayout.addWidget(self.lblExclusion)
        self.vSmartLayout.addWidget(self.listExclusions)

        self.groupSmartFilter.setLayout(self.vSmartLayout)

        # National Heritage Administration legal-map inputs are independent
        # from the archaeological "nearby heritage" list.  A current-change
        # check should never require the operator to feed those legal layers
        # through a general-purpose duplicate/numbering list.
        self.groupLegalLayers = QtWidgets.QGroupBox()
        legal_layout = QtWidgets.QFormLayout(self.groupLegalLayers)
        legal_layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow
        )

        def legal_layer_combo():
            combo = QgsMapLayerComboBox()
            combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
            combo.setAllowEmptyLayer(True)
            combo.setLayer(None)
            return combo

        self.lblZoneLayer = QtWidgets.QLabel()
        self.comboZoneLayer = legal_layer_combo()
        self.lblZoneField = QtWidgets.QLabel()
        self.comboZoneField = QtWidgets.QComboBox()
        self.comboZoneField.setStyleSheet(STYLE_FORCE_VISIBLE)
        self.comboZoneField.addItem(self._t("자동 감지", "Auto detect"), None)
        self.lblNationalDesignatedLayer = QtWidgets.QLabel()
        self.comboNationalDesignatedLayer = legal_layer_combo()
        self.lblNationalProtectionLayer = QtWidgets.QLabel()
        self.comboNationalProtectionLayer = legal_layer_combo()
        self.lblLocalDesignatedLayer = QtWidgets.QLabel()
        self.comboLocalDesignatedLayer = legal_layer_combo()
        self.lblLocalProtectionLayer = QtWidgets.QLabel()
        self.comboLocalProtectionLayer = legal_layer_combo()

        legal_layout.addRow(self.lblZoneLayer, self.comboZoneLayer)
        legal_layout.addRow(self.lblZoneField, self.comboZoneField)
        legal_layout.addRow(
            self.lblNationalDesignatedLayer,
            self.comboNationalDesignatedLayer,
        )
        legal_layout.addRow(
            self.lblNationalProtectionLayer,
            self.comboNationalProtectionLayer,
        )
        legal_layout.addRow(
            self.lblLocalDesignatedLayer,
            self.comboLocalDesignatedLayer,
        )
        legal_layout.addRow(
            self.lblLocalProtectionLayer,
            self.comboLocalProtectionLayer,
        )

        self.chkClipZoneToBuffer = QtWidgets.QCheckBox()
        self.chkClipZoneToBuffer.setChecked(False)
        legal_layout.addRow("", self.chkClipZoneToBuffer)
        self.comboZoneLayer.layerChanged.connect(self._refresh_zone_fields)

        if hasattr(self, 'vTab1'):
            self.vTab1.insertWidget(1, self.groupLegalLayers)

        # Insert into the first tab layout (vTab1) before the Spec group (item index 1)
        if hasattr(self, 'vTab1'):
            self.vTab1.insertWidget(2, self.groupSmartFilter)  # Adjusted index

        self._build_duplicate_policy_controls()
        self._build_previous_result_controls()
        self._build_output_artifact_controls()
        self._build_metric_crs_controls()

        # Default colors (Matching professional archaeological standards)
        self.heritage_stroke_color = QtGui.QColor(DEFAULT_COLORS["heritage_stroke"])
        self.heritage_fill_color = QtGui.QColor(DEFAULT_COLORS["heritage_fill"])
        self.study_stroke_color = QtGui.QColor(DEFAULT_COLORS["study_stroke"])
        self.topo_stroke_color = QtGui.QColor(DEFAULT_COLORS["topo_stroke"])
        self.buffer_color = QtGui.QColor(DEFAULT_COLORS["buffer"])
        self.preservation_action_colors = {
            action: {
                "fill_color": QtGui.QColor(style["fill_color"]),
                "outline_color": QtGui.QColor(style["outline_color"]),
            }
            for action, style in PRESERVATION_ACTION_STYLES.items()
        }
        self.preservation_stroke_width = DEFAULT_SPIN_VALUES[
            "heritage_stroke_width"
        ]
        self.preservation_opacity = 100
        self._load_preservation_style_preferences()

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
        self._build_workflow_tabs()

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

        self.chkBufferKmLabels = QtWidgets.QCheckBox()
        self.chkBufferKmLabels.setChecked(False)
        if hasattr(self, "gBuffer"):
            self.gBuffer.addWidget(
                self.chkBufferKmLabels,
                2,
                1,
                1,
                3,
            )

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
        self.chkRestrictToBuffer.setChecked(False)  # [FIX] Default to Unchecked (User Request)
        self.chkRestrictToBuffer.setStyleSheet("font-weight: bold; color: #d35400;")

        # Insert into vTab1 at index 1
        if hasattr(self, 'vTab1'):
            self.vTab1.insertWidget(1, self.chkRestrictToBuffer)

        self.chkExcludeExtentSlivers = QtWidgets.QCheckBox()
        self.chkExcludeExtentSlivers.setChecked(True)
        self.chkExcludeExtentSlivers.setStyleSheet(
            "font-weight: bold; color: #8e5b00;"
        )
        if hasattr(self, "vTab1"):
            self.vTab1.insertWidget(2, self.chkExcludeExtentSlivers)

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
        self.listExclusions.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)  # Allow Shift-Select

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

        # Ensure all UI texts are synchronized after dynamic widgets are created.
        self._retranslate_dynamic_widgets()

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
        self.buttonBox.rejected.connect(self.reject)  # Close button

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

    def _build_duplicate_policy_controls(self):
        """Add source-role overrides and duplicate matching preset controls."""
        self.groupDuplicatePolicy = QtWidgets.QGroupBox()
        duplicate_layout = QtWidgets.QVBoxLayout()

        self.lblMatchingSummary = QtWidgets.QLabel()
        self.lblMatchingSummary.setWordWrap(True)
        self.lblMatchingSummary.setTextFormat(QtCore.Qt.RichText)
        self.lblMatchingSummary.setStyleSheet(
            "background:#eef7ff; border:1px solid #9ec9e8; "
            "padding:8px; color:#234;"
        )
        duplicate_layout.addWidget(self.lblMatchingSummary)

        matching_help_row = QtWidgets.QHBoxLayout()
        matching_help_row.addStretch(1)
        self.btnMatchingRulesHelp = QtWidgets.QPushButton()
        self.btnMatchingRulesHelp.clicked.connect(
            self.show_matching_rules_help
        )
        matching_help_row.addWidget(self.btnMatchingRulesHelp)
        duplicate_layout.addLayout(matching_help_row)

        self.lblPreviousResultInputWarning = QtWidgets.QLabel()
        self.lblPreviousResultInputWarning.setWordWrap(True)
        self.lblPreviousResultInputWarning.setTextFormat(
            QtCore.Qt.RichText
        )
        self.lblPreviousResultInputWarning.setStyleSheet(
            "background:#fff4d6; border:1px solid #e0ad42; "
            "padding:8px; color:#5b3b00;"
        )
        self.lblPreviousResultInputWarning.hide()
        duplicate_layout.addWidget(self.lblPreviousResultInputWarning)

        preset_row = QtWidgets.QHBoxLayout()
        self.lblMatchPreset = QtWidgets.QLabel()
        self.comboMatchPreset = QtWidgets.QComboBox()
        self.comboMatchPreset.setStyleSheet(STYLE_FORCE_VISIBLE)
        for key, label in MATCH_PRESET_LABELS.items():
            self.comboMatchPreset.addItem(label, key)
        saved_preset = str(
            QtCore.QSettings().value(
                MATCH_PRESET_PREF_KEY,
                PRESET_BALANCED,
            )
        )
        saved_index = self.comboMatchPreset.findData(saved_preset)
        self.comboMatchPreset.setCurrentIndex(
            max(0, saved_index)
        )
        self.comboMatchPreset.currentIndexChanged.connect(
            lambda _index: QtCore.QSettings().setValue(
                MATCH_PRESET_PREF_KEY,
                self.comboMatchPreset.currentData(),
            )
        )
        preset_row.addWidget(self.lblMatchPreset)
        preset_row.addWidget(self.comboMatchPreset)
        preset_row.addStretch(1)
        duplicate_layout.addLayout(preset_row)

        self.chkReuseReviewDecisions = QtWidgets.QCheckBox()
        saved_reuse = QtCore.QSettings().value(
            REUSE_REVIEW_PREF_KEY,
            True,
        )
        if isinstance(saved_reuse, str):
            saved_reuse = saved_reuse.strip().casefold() not in {
                "0",
                "false",
                "no",
                "off",
            }
        self.chkReuseReviewDecisions.setChecked(bool(saved_reuse))
        self.chkReuseReviewDecisions.toggled.connect(
            lambda checked: QtCore.QSettings().setValue(
                REUSE_REVIEW_PREF_KEY,
                checked,
            )
        )
        duplicate_layout.addWidget(self.chkReuseReviewDecisions)

        self.lblRoleHelp = QtWidgets.QLabel()
        self.lblRoleHelp.setWordWrap(True)
        self.lblRoleHelp.setStyleSheet("color:#555; font-size:10px;")
        duplicate_layout.addWidget(self.lblRoleHelp)

        self.tableLayerRoles = QtWidgets.QTableWidget(0, 3)
        self.tableLayerRoles.verticalHeader().setVisible(False)
        self.tableLayerRoles.setAlternatingRowColors(True)
        self.tableLayerRoles.setMinimumHeight(150)
        role_header = self.tableLayerRoles.horizontalHeader()
        role_header.setSectionResizeMode(
            0,
            QtWidgets.QHeaderView.Stretch,
        )
        role_header.setSectionResizeMode(
            1,
            QtWidgets.QHeaderView.ResizeToContents,
        )
        role_header.setSectionResizeMode(
            2,
            QtWidgets.QHeaderView.ResizeToContents,
        )
        duplicate_layout.addWidget(self.tableLayerRoles)
        self.groupDuplicatePolicy.setLayout(duplicate_layout)
        self.layerRoleCombos = {}
        self.layerEncodingCombos = {}
        self.listHeritageLayers.itemChanged.connect(
            self._update_previous_result_guidance
        )

        if hasattr(self, "vTab1"):
            self.vTab1.insertWidget(1, self.groupDuplicatePolicy)

    def _build_previous_result_controls(self):
        """Add a dedicated, safe path for renumbering an existing result."""
        self.groupPreviousResult = QtWidgets.QGroupBox()
        layout = QtWidgets.QVBoxLayout()

        self.lblPreviousResultHelp = QtWidgets.QLabel()
        self.lblPreviousResultHelp.setWordWrap(True)
        self.lblPreviousResultHelp.setTextFormat(QtCore.Qt.RichText)
        self.lblPreviousResultHelp.setStyleSheet(
            "background:#f4f8f4; border:1px solid #a9c6a9; "
            "padding:8px; color:#243b24;"
        )
        layout.addWidget(self.lblPreviousResultHelp)

        selector_row = QtWidgets.QHBoxLayout()
        self.lblPreviousResultLayer = QtWidgets.QLabel()
        self.comboPreviousResultLayer = QtWidgets.QComboBox()
        self.comboPreviousResultLayer.setStyleSheet(STYLE_FORCE_VISIBLE)
        self.comboPreviousResultLayer.currentIndexChanged.connect(
            self._update_previous_result_status
        )
        self.btnRenumberPreviousResult = QtWidgets.QPushButton()
        self.btnRenumberPreviousResult.clicked.connect(
            self.renumber_previous_result
        )
        selector_row.addWidget(self.lblPreviousResultLayer)
        selector_row.addWidget(self.comboPreviousResultLayer, 1)
        selector_row.addWidget(self.btnRenumberPreviousResult)
        layout.addLayout(selector_row)

        self.lblPreviousResultStatus = QtWidgets.QLabel()
        self.lblPreviousResultStatus.setWordWrap(True)
        self.lblPreviousResultStatus.setStyleSheet(
            "color:#486048; font-size:10px;"
        )
        layout.addWidget(self.lblPreviousResultStatus)
        self.groupPreviousResult.setLayout(layout)

        if hasattr(self, "vTab2"):
            numbering_index = (
                self.vTab2.indexOf(self.groupNumbering)
                if hasattr(self, "groupNumbering")
                else -1
            )
            self.vTab2.insertWidget(
                numbering_index if numbering_index >= 0 else 0,
                self.groupPreviousResult,
            )

    @staticmethod
    def _saved_bool(key, default=False):
        value = QtCore.QSettings().value(key, default)
        if isinstance(value, str):
            return value.strip().casefold() not in {
                "0",
                "false",
                "no",
                "off",
                "",
            }
        return bool(value)

    def _build_output_artifact_controls(self):
        """Add optional archival and print-layout outputs without changing defaults."""
        self.groupOutputArtifacts = QtWidgets.QGroupBox()
        layout = QtWidgets.QVBoxLayout()

        directory_row = QtWidgets.QHBoxLayout()
        self.lblOutputDirectory = QtWidgets.QLabel()
        self.lineOutputDirectory = QtWidgets.QLineEdit()
        default_directory = os.path.join(
            QtCore.QStandardPaths.writableLocation(
                QtCore.QStandardPaths.DesktopLocation
            ),
            "ArchDistribution_Output",
        )
        saved_directory = str(
            QtCore.QSettings().value(
                OUTPUT_DIRECTORY_PREF_KEY,
                default_directory,
            )
            or default_directory
        )
        self.lineOutputDirectory.setText(saved_directory)
        self.lineOutputDirectory.editingFinished.connect(
            lambda: QtCore.QSettings().setValue(
                OUTPUT_DIRECTORY_PREF_KEY,
                self.lineOutputDirectory.text().strip(),
            )
        )
        self.btnBrowseOutputDirectory = QtWidgets.QPushButton()
        self.btnBrowseOutputDirectory.clicked.connect(
            self._browse_output_directory
        )
        directory_row.addWidget(self.lblOutputDirectory)
        directory_row.addWidget(self.lineOutputDirectory, 1)
        directory_row.addWidget(self.btnBrowseOutputDirectory)
        layout.addLayout(directory_row)

        options_row = QtWidgets.QHBoxLayout()
        self.chkSaveGpkgManifest = QtWidgets.QCheckBox()
        self.chkExportLayoutJpg = QtWidgets.QCheckBox()
        self.chkExportLayoutPdf = QtWidgets.QCheckBox()
        preferences = (
            (
                self.chkSaveGpkgManifest,
                SAVE_GPKG_PREF_KEY,
            ),
            (
                self.chkExportLayoutJpg,
                EXPORT_JPG_PREF_KEY,
            ),
            (
                self.chkExportLayoutPdf,
                EXPORT_PDF_PREF_KEY,
            ),
        )
        for checkbox, key in preferences:
            checkbox.setChecked(self._saved_bool(key, False))
            checkbox.toggled.connect(
                lambda checked, setting_key=key: QtCore.QSettings().setValue(
                    setting_key,
                    checked,
                )
            )
            options_row.addWidget(checkbox)
        options_row.addStretch(1)
        layout.addLayout(options_row)

        self.lblOutputArtifactHelp = QtWidgets.QLabel()
        self.lblOutputArtifactHelp.setWordWrap(True)
        self.lblOutputArtifactHelp.setStyleSheet(
            "color:#555; font-size:10px;"
        )
        layout.addWidget(self.lblOutputArtifactHelp)
        self.groupOutputArtifacts.setLayout(layout)

        if hasattr(self, "vMain") and hasattr(self, "tabWidget"):
            tab_index = self.vMain.indexOf(self.tabWidget)
            self.vMain.insertWidget(
                max(0, tab_index + 1),
                self.groupOutputArtifacts,
            )

    def _browse_output_directory(self):
        start_directory = self.lineOutputDirectory.text().strip()
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self._t("결과 저장 폴더 선택", "Select output folder"),
            start_directory,
        )
        if not selected:
            return
        self.lineOutputDirectory.setText(selected)
        QtCore.QSettings().setValue(OUTPUT_DIRECTORY_PREF_KEY, selected)

    def _build_metric_crs_controls(self):
        """Add one metric-analysis CRS control shared by both workflows."""
        self.groupMetricCrs = QtWidgets.QGroupBox()
        layout = QtWidgets.QVBoxLayout()

        self.lblMetricCrsHelp = QtWidgets.QLabel()
        self.lblMetricCrsHelp.setWordWrap(True)
        self.lblMetricCrsHelp.setTextFormat(QtCore.Qt.RichText)
        self.lblMetricCrsHelp.setStyleSheet(
            "background:#f4f8fb; border:1px solid #b8cad8; "
            "padding:7px; color:#234;"
        )
        layout.addWidget(self.lblMetricCrsHelp)

        self.chkOverrideAnalysisCrs = QtWidgets.QCheckBox()
        layout.addWidget(self.chkOverrideAnalysisCrs)

        selector_row = QtWidgets.QHBoxLayout()
        self.lblAnalysisCrs = QtWidgets.QLabel()
        self.projectionAnalysisCrs = QgsProjectionSelectionWidget()
        selector_row.addWidget(self.lblAnalysisCrs)
        selector_row.addWidget(self.projectionAnalysisCrs, 1)
        layout.addLayout(selector_row)
        self.groupMetricCrs.setLayout(layout)

        saved_definition = str(
            QtCore.QSettings().value(
                ANALYSIS_CRS_DEFINITION_PREF_KEY,
                "",
            )
            or ""
        ).strip()
        saved_crs = QgsCoordinateReferenceSystem()
        if saved_definition:
            saved_crs.createFromString(saved_definition)
        if not saved_crs.isValid():
            project_crs = QgsProject.instance().crs()
            saved_crs = (
                QgsCoordinateReferenceSystem(project_crs)
                if project_crs.isValid()
                else QgsCoordinateReferenceSystem("EPSG:5186")
            )
        self.projectionAnalysisCrs.setCrs(saved_crs)

        override_enabled = self._saved_bool(
            ANALYSIS_CRS_OVERRIDE_PREF_KEY,
            False,
        )
        self.chkOverrideAnalysisCrs.setChecked(override_enabled)
        self.projectionAnalysisCrs.setEnabled(override_enabled)
        self.lblAnalysisCrs.setEnabled(override_enabled)
        self.chkOverrideAnalysisCrs.toggled.connect(
            self._set_analysis_crs_override_enabled
        )
        self.projectionAnalysisCrs.crsChanged.connect(
            self._save_analysis_crs_definition
        )

        if hasattr(self, "vMain") and hasattr(self, "groupOutputArtifacts"):
            output_index = self.vMain.indexOf(self.groupOutputArtifacts)
            self.vMain.insertWidget(
                max(0, output_index),
                self.groupMetricCrs,
            )

    def _set_analysis_crs_override_enabled(self, enabled):
        """Toggle and persist the optional advanced CRS override."""
        enabled = bool(enabled)
        self.projectionAnalysisCrs.setEnabled(enabled)
        self.lblAnalysisCrs.setEnabled(enabled)
        QtCore.QSettings().setValue(
            ANALYSIS_CRS_OVERRIDE_PREF_KEY,
            enabled,
        )
        if enabled:
            self._save_analysis_crs_definition(
                self.projectionAnalysisCrs.crs()
            )

    @staticmethod
    def _crs_definition(crs):
        """Return a stable authority id, or WKT for a valid custom CRS."""
        if crs is None or not crs.isValid():
            return None
        return crs.authid() or crs.toWkt()

    def _save_analysis_crs_definition(self, crs):
        definition = self._crs_definition(crs)
        if definition:
            QtCore.QSettings().setValue(
                ANALYSIS_CRS_DEFINITION_PREF_KEY,
                definition,
            )

    def _analysis_crs_override_definition(self):
        """Return ``None`` for automatic selection, otherwise auth id/WKT."""
        if not self.chkOverrideAnalysisCrs.isChecked():
            return None
        return self._crs_definition(self.projectionAnalysisCrs.crs())

    def _analysis_crs_override_error(self):
        """Validate that an explicit analysis CRS measures in metres."""
        if not self.chkOverrideAnalysisCrs.isChecked():
            return None
        crs = self.projectionAnalysisCrs.crs()
        if crs is None or not crs.isValid():
            return self._t(
                "고급 분석 좌표계를 선택해 주세요.",
                "Select an advanced analysis CRS.",
            )
        if crs.isGeographic() or crs.mapUnits() != QgsUnitTypes.DistanceMeters:
            return self._t(
                "분석 좌표계는 미터 단위의 투영좌표계여야 합니다. "
                "잘 모르겠으면 고급 설정을 해제해 자동 선택을 사용하세요.",
                "The analysis CRS must be a projected CRS measured in metres. "
                "If unsure, disable the override and use automatic selection.",
            )
        return None

    def _load_preservation_style_preferences(self):
        """Load saved preservation-action colors without changing defaults on errors."""
        raw = QtCore.QSettings().value(PRESERVATION_STYLE_PREF_KEY, "")
        if not raw:
            return
        try:
            saved = json.loads(str(raw))
        except (TypeError, ValueError):
            return

        for action in PRESERVATION_STYLE_ORDER:
            action_style = saved.get("actions", {}).get(action, {})
            for key in ("fill_color", "outline_color"):
                color = QtGui.QColor(action_style.get(key, ""))
                if color.isValid():
                    self.preservation_action_colors[action][key] = color

        try:
            width = float(saved.get("stroke_width", self.preservation_stroke_width))
            self.preservation_stroke_width = min(5.0, max(0.05, width))
        except (TypeError, ValueError):
            pass
        try:
            opacity = int(saved.get("opacity", self.preservation_opacity))
            self.preservation_opacity = min(100, max(0, opacity))
        except (TypeError, ValueError):
            pass

    def _save_preservation_style_preferences(self):
        """Persist the dedicated workflow style so it survives QGIS restarts."""
        if not hasattr(self, "preservation_action_colors"):
            return
        payload = {
            "actions": {
                action: {
                    key: color.name()
                    for key, color in colors.items()
                }
                for action, colors in self.preservation_action_colors.items()
            },
            "stroke_width": (
                self.spinPreservationStrokeWidth.value()
                if hasattr(self, "spinPreservationStrokeWidth")
                else self.preservation_stroke_width
            ),
            "opacity": (
                self.spinPreservationOpacity.value()
                if hasattr(self, "spinPreservationOpacity")
                else self.preservation_opacity
            ),
        }
        QtCore.QSettings().setValue(
            PRESERVATION_STYLE_PREF_KEY,
            json.dumps(payload, ensure_ascii=False),
        )

    def _build_workflow_tabs(self):
        """Wrap the legacy map workflow and add a dedicated preservation workflow."""
        if not hasattr(self, "vMain") or not hasattr(self, "tabWidget"):
            return

        original_index = self.vMain.indexOf(self.tabWidget)
        if original_index < 0:
            return

        self.vMain.removeWidget(self.tabWidget)
        self.workflowTabs = QtWidgets.QTabWidget()

        self.distributionWorkflowPage = QtWidgets.QWidget()
        distribution_layout = QtWidgets.QVBoxLayout(
            self.distributionWorkflowPage
        )
        distribution_layout.setContentsMargins(0, 0, 0, 0)
        distribution_layout.addWidget(self.tabWidget)
        self.workflowTabs.addTab(self.distributionWorkflowPage, "")

        self.preservationWorkflowPage = QtWidgets.QWidget()
        preservation_layout = QtWidgets.QVBoxLayout(
            self.preservationWorkflowPage
        )

        self.lblPreservationIntro = QtWidgets.QLabel()
        self.lblPreservationIntro.setWordWrap(True)
        self.lblPreservationIntro.setStyleSheet(
            "background:#eef7ff; border:1px solid #9ec9e8; "
            "padding:8px; color:#234;"
        )
        preservation_layout.addWidget(self.lblPreservationIntro)

        self.groupPreservationInput = QtWidgets.QGroupBox()
        preservation_input_layout = QtWidgets.QFormLayout()
        self.comboPreservationLayer = QgsMapLayerComboBox()
        self.comboPreservationLayer.setFilters(
            QgsMapLayerProxyModel.PolygonLayer
        )
        self.comboPreservationLayer.setAllowEmptyLayer(True)
        self.comboPreservationLayer.setLayer(None)
        self.lblPreservationLayer = QtWidgets.QLabel()
        preservation_input_layout.addRow(
            self.lblPreservationLayer,
            self.comboPreservationLayer,
        )

        self.lblPreservationEncoding = QtWidgets.QLabel()
        self.comboPreservationEncoding = QtWidgets.QComboBox()
        self.comboPreservationEncoding.addItem(
            self._t("자동(.cpg/공급자)", "Automatic (.cpg/provider)"),
            "",
        )
        self.comboPreservationEncoding.addItem("UTF-8", "UTF-8")
        self.comboPreservationEncoding.addItem("CP949 (EUC-KR)", "CP949")
        self.comboPreservationEncoding.currentIndexChanged.connect(
            self._save_preservation_encoding_override
        )
        preservation_input_layout.addRow(
            self.lblPreservationEncoding,
            self.comboPreservationEncoding,
        )

        self.comboPreservationActionField = QtWidgets.QComboBox()
        self.comboPreservationActionField.setStyleSheet(STYLE_FORCE_VISIBLE)
        self.lblPreservationActionField = QtWidgets.QLabel()
        preservation_input_layout.addRow(
            self.lblPreservationActionField,
            self.comboPreservationActionField,
        )

        self.lblPreservationDetection = QtWidgets.QLabel()
        self.lblPreservationDetection.setWordWrap(True)
        preservation_input_layout.addRow("", self.lblPreservationDetection)
        self.groupPreservationInput.setLayout(preservation_input_layout)
        preservation_layout.addWidget(self.groupPreservationInput)

        self.groupPreservationExtent = QtWidgets.QGroupBox()
        preservation_extent_layout = QtWidgets.QFormLayout()

        self.lblPreservationStudyArea = QtWidgets.QLabel()
        self.comboPreservationStudyArea = QgsMapLayerComboBox()
        self.comboPreservationStudyArea.setFilters(
            QgsMapLayerProxyModel.PolygonLayer
        )
        self.comboPreservationStudyArea.setAllowEmptyLayer(True)
        self.comboPreservationStudyArea.setLayer(None)
        preservation_extent_layout.addRow(
            self.lblPreservationStudyArea,
            self.comboPreservationStudyArea,
        )

        self.lblPreservationPaperSize = QtWidgets.QLabel()
        paper_size_widget = QtWidgets.QWidget()
        paper_size_layout = QtWidgets.QHBoxLayout(paper_size_widget)
        paper_size_layout.setContentsMargins(0, 0, 0, 0)
        self.spinPreservationPaperWidth = QtWidgets.QSpinBox()
        self.spinPreservationPaperWidth.setRange(10, 2000)
        self.spinPreservationPaperWidth.setSuffix(" mm")
        self.spinPreservationPaperWidth.setValue(
            DEFAULT_SPIN_VALUES["paper_width"]
        )
        self.lblPreservationPaperSeparator = QtWidgets.QLabel("×")
        self.spinPreservationPaperHeight = QtWidgets.QSpinBox()
        self.spinPreservationPaperHeight.setRange(10, 2000)
        self.spinPreservationPaperHeight.setSuffix(" mm")
        self.spinPreservationPaperHeight.setValue(
            DEFAULT_SPIN_VALUES["paper_height"]
        )
        self.btnPreservationPresetReport = QtWidgets.QPushButton()
        self.btnPreservationPresetA4 = QtWidgets.QPushButton()
        paper_size_layout.addWidget(self.spinPreservationPaperWidth)
        paper_size_layout.addWidget(self.lblPreservationPaperSeparator)
        paper_size_layout.addWidget(self.spinPreservationPaperHeight)
        paper_size_layout.addWidget(self.btnPreservationPresetReport)
        paper_size_layout.addWidget(self.btnPreservationPresetA4)
        preservation_extent_layout.addRow(
            self.lblPreservationPaperSize,
            paper_size_widget,
        )

        self.lblPreservationScale = QtWidgets.QLabel()
        self.spinPreservationScale = QtWidgets.QSpinBox()
        self.spinPreservationScale.setRange(100, 1000000)
        self.spinPreservationScale.setSingleStep(
            DEFAULT_SPIN_VALUES["scale_step"]
        )
        self.spinPreservationScale.setPrefix("1 : ")
        self.spinPreservationScale.setValue(DEFAULT_SPIN_VALUES["scale"])
        preservation_extent_layout.addRow(
            self.lblPreservationScale,
            self.spinPreservationScale,
        )

        self.chkPreservationExcludeExtentSlivers = QtWidgets.QCheckBox()
        self.chkPreservationExcludeExtentSlivers.setChecked(True)
        self.chkPreservationExcludeExtentSlivers.setStyleSheet(
            "font-weight:bold; color:#8e5b00;"
        )
        preservation_extent_layout.addRow(
            "",
            self.chkPreservationExcludeExtentSlivers,
        )
        self.groupPreservationExtent.setLayout(preservation_extent_layout)
        preservation_layout.addWidget(self.groupPreservationExtent)

        self.groupPreservationStyle = QtWidgets.QGroupBox()
        preservation_style_layout = QtWidgets.QGridLayout()
        self.lblPreservationActionHeader = QtWidgets.QLabel()
        self.lblPreservationFillHeader = QtWidgets.QLabel()
        self.lblPreservationOutlineHeader = QtWidgets.QLabel()
        for label in (
            self.lblPreservationActionHeader,
            self.lblPreservationFillHeader,
            self.lblPreservationOutlineHeader,
        ):
            label.setStyleSheet("font-weight:bold;")
        preservation_style_layout.addWidget(
            self.lblPreservationActionHeader, 0, 0
        )
        preservation_style_layout.addWidget(
            self.lblPreservationFillHeader, 0, 1
        )
        preservation_style_layout.addWidget(
            self.lblPreservationOutlineHeader, 0, 2
        )

        self.preservationColorButtons = {}
        for row, action in enumerate(PRESERVATION_STYLE_ORDER, start=1):
            action_label = QtWidgets.QLabel(action)
            fill_button = QtWidgets.QPushButton()
            outline_button = QtWidgets.QPushButton()
            fill_button.setMinimumWidth(115)
            outline_button.setMinimumWidth(115)
            fill_button.clicked.connect(
                lambda _checked=False, current=action:
                self.pick_preservation_color(current, "fill_color")
            )
            outline_button.clicked.connect(
                lambda _checked=False, current=action:
                self.pick_preservation_color(current, "outline_color")
            )
            self.preservationColorButtons[action] = {
                "fill_color": fill_button,
                "outline_color": outline_button,
            }
            preservation_style_layout.addWidget(action_label, row, 0)
            preservation_style_layout.addWidget(fill_button, row, 1)
            preservation_style_layout.addWidget(outline_button, row, 2)

        self.lblPreservationStrokeWidth = QtWidgets.QLabel()
        self.spinPreservationStrokeWidth = QtWidgets.QDoubleSpinBox()
        self.spinPreservationStrokeWidth.setRange(0.05, 5.0)
        self.spinPreservationStrokeWidth.setDecimals(2)
        self.spinPreservationStrokeWidth.setSingleStep(0.05)
        self.spinPreservationStrokeWidth.setSuffix(" mm")
        self.spinPreservationStrokeWidth.setValue(
            self.preservation_stroke_width
        )

        self.lblPreservationOpacity = QtWidgets.QLabel()
        self.spinPreservationOpacity = QtWidgets.QSpinBox()
        self.spinPreservationOpacity.setRange(0, 100)
        self.spinPreservationOpacity.setSuffix("%")
        self.spinPreservationOpacity.setValue(self.preservation_opacity)

        options_row = len(PRESERVATION_STYLE_ORDER) + 1
        preservation_style_layout.addWidget(
            self.lblPreservationStrokeWidth, options_row, 0
        )
        preservation_style_layout.addWidget(
            self.spinPreservationStrokeWidth, options_row, 1
        )
        preservation_style_layout.addWidget(
            self.lblPreservationOpacity, options_row + 1, 0
        )
        preservation_style_layout.addWidget(
            self.spinPreservationOpacity, options_row + 1, 1
        )

        self.btnResetPreservationStyles = QtWidgets.QPushButton()
        preservation_style_layout.addWidget(
            self.btnResetPreservationStyles,
            options_row + 2,
            0,
            1,
            3,
        )
        self.groupPreservationStyle.setLayout(preservation_style_layout)
        preservation_layout.addWidget(self.groupPreservationStyle)

        self.groupPreservationNumbering = QtWidgets.QGroupBox()
        preservation_numbering_layout = QtWidgets.QFormLayout()
        self.comboPreservationSortOrder = QtWidgets.QComboBox()
        self.comboPreservationSortOrder.setStyleSheet(STYLE_FORCE_VISIBLE)
        self.comboPreservationSortOrder.addItems(
            SORT_ORDER_OPTIONS[self.ui_lang]
        )
        self.lblPreservationSortOrder = QtWidgets.QLabel()
        preservation_numbering_layout.addRow(
            self.lblPreservationSortOrder,
            self.comboPreservationSortOrder,
        )
        self.spinPreservationLabelFontSize = QtWidgets.QSpinBox()
        self.spinPreservationLabelFontSize.setRange(6, 72)
        self.spinPreservationLabelFontSize.setValue(
            DEFAULT_SPIN_VALUES["label_font_size"]
        )
        self.lblPreservationLabelFontSize = QtWidgets.QLabel()
        preservation_numbering_layout.addRow(
            self.lblPreservationLabelFontSize,
            self.spinPreservationLabelFontSize,
        )
        self.comboPreservationLabelFont = QtWidgets.QFontComboBox()
        self.comboPreservationLabelFont.setCurrentFont(
            QtGui.QFont(DEFAULT_LABEL_FONT_FAMILY[self.ui_lang])
        )
        self.lblPreservationLabelFont = QtWidgets.QLabel()
        preservation_numbering_layout.addRow(
            self.lblPreservationLabelFont,
            self.comboPreservationLabelFont,
        )
        self.lblPreservationGrouping = QtWidgets.QLabel()
        self.lblPreservationGrouping.setWordWrap(True)
        preservation_numbering_layout.addRow(
            "", self.lblPreservationGrouping
        )
        self.groupPreservationNumbering.setLayout(
            preservation_numbering_layout
        )
        preservation_layout.addWidget(self.groupPreservationNumbering)
        preservation_layout.addStretch(1)

        self.workflowTabs.addTab(self.preservationWorkflowPage, "")
        self.vMain.insertWidget(original_index, self.workflowTabs)

        self.comboPreservationLayer.layerChanged.connect(
            self._refresh_preservation_fields
        )
        self.btnResetPreservationStyles.clicked.connect(
            self.reset_preservation_styles
        )
        self.btnPreservationPresetReport.clicked.connect(
            lambda: self._apply_preservation_preset(*PRESET_REPORT)
        )
        self.btnPreservationPresetA4.clicked.connect(
            lambda: self._apply_preservation_preset(*PRESET_A4)
        )
        self.spinPreservationStrokeWidth.valueChanged.connect(
            self._save_preservation_style_preferences
        )
        self.spinPreservationOpacity.valueChanged.connect(
            self._save_preservation_style_preferences
        )
        self.workflowTabs.currentChanged.connect(
            self._on_workflow_changed
        )
        self._refresh_preservation_fields(
            self.comboPreservationLayer.currentLayer()
        )
        self.update_preservation_button_colors()
        self._retranslate_workflow_widgets()
        self._on_workflow_changed(0)

    def _detect_preservation_field(self, layer):
        """Return a schema-and-value verified action field for the selected layer."""
        if not layer or layer.type() != 0 or layer.geometryType() != 2:
            return None
        field_names = [field.name() for field in layer.fields()]
        for keyword in PRESERVATION_ACTION_FIELD_CANDIDATES:
            for field_name in field_names:
                if keyword.casefold() not in field_name.casefold():
                    continue
                field_idx = layer.fields().indexFromName(field_name)
                if field_idx >= 0 and recognized_preservation_actions(
                    layer.uniqueValues(field_idx)
                ):
                    return field_name
        return None

    def _refresh_zone_fields(self, layer):
        """Populate the explicit current-change category-field selector."""
        if not hasattr(self, "comboZoneField"):
            return
        previous = self.comboZoneField.currentData()
        self.comboZoneField.blockSignals(True)
        self.comboZoneField.clear()
        self.comboZoneField.addItem(
            self._t("자동 감지", "Auto detect"),
            None,
        )
        if layer:
            for field in layer.fields():
                self.comboZoneField.addItem(field.name(), field.name())
            # Schema labels in legacy CP949 shapefiles are not reliable on
            # their own.  Prefer the field whose actual values most often
            # match the official 1–8 / 2-x / 3-x zone vocabulary.
            zone_counts = {}
            for feature_index, feature in enumerate(layer.getFeatures()):
                if feature_index >= 250:
                    break
                for field in layer.fields():
                    name = field.name()
                    if normalize_change_zone_code(feature[name]):
                        zone_counts[name] = zone_counts.get(name, 0) + 1
            value_verified = (
                max(zone_counts, key=zone_counts.get)
                if zone_counts else None
            )
            preferred_names = (
                "L3_CODE", "A_L3_CODE", "L2_CODE", "구역코드",
                "구역명", "구역", "ZONENAME", "ZONE",
            )
            field_names = {field.name().casefold(): field.name()
                           for field in layer.fields()}
            preferred = next(
                (
                    field_names[name.casefold()]
                    for name in preferred_names
                    if name.casefold() in field_names
                ),
                None,
            )
            target = (
                previous if previous in field_names.values()
                else value_verified or preferred
            )
            if target:
                self.comboZoneField.setCurrentIndex(
                    max(0, self.comboZoneField.findData(target))
                )
        self.comboZoneField.blockSignals(False)

    def _refresh_preservation_fields(self, layer):
        """Populate the explicit field picker and preselect a verified field."""
        if not hasattr(self, "comboPreservationActionField"):
            return
        self.comboPreservationEncoding.blockSignals(True)
        selected_encoding = (
            str(layer.customProperty(
                "ArchDistribution/encoding_override", ""
            ) or "").strip()
            if layer else ""
        )
        self.comboPreservationEncoding.setCurrentIndex(max(
            0,
            self.comboPreservationEncoding.findData(selected_encoding),
        ))
        self.comboPreservationEncoding.blockSignals(False)
        self.comboPreservationActionField.blockSignals(True)
        self.comboPreservationActionField.clear()
        self.comboPreservationActionField.addItem(
            self._t("자동 인식", "Auto detect"),
            None,
        )
        detected = self._detect_preservation_field(layer)
        if layer:
            for field in layer.fields():
                self.comboPreservationActionField.addItem(
                    field.name(),
                    field.name(),
                )
        if detected:
            detected_index = self.comboPreservationActionField.findData(
                detected
            )
            self.comboPreservationActionField.setCurrentIndex(
                max(0, detected_index)
            )
            actions = recognized_preservation_actions(
                layer.uniqueValues(layer.fields().indexFromName(detected))
            )
            self.lblPreservationDetection.setText(
                self._t(
                    f"✓ 자동 확인: {detected} "
                    f"({', '.join(sorted(actions))})",
                    f"Verified automatically: {detected} "
                    f"({', '.join(sorted(actions))})",
                )
            )
            self.lblPreservationDetection.setStyleSheet("color:#188038;")
        elif layer:
            self.lblPreservationDetection.setText(
                self._t(
                    "자동 확인되지 않았습니다. 실제 보존조치 값이 들어 있는 "
                    "필드를 직접 선택하세요.",
                    "Not verified automatically. Select the field containing "
                    "the actual preservation-action values.",
                )
            )
            self.lblPreservationDetection.setStyleSheet("color:#b06000;")
        else:
            self.lblPreservationDetection.setText(
                self._t(
                    "먼저 폴리곤 레이어를 선택하세요.",
                    "Select a polygon layer first.",
                )
            )
            self.lblPreservationDetection.setStyleSheet("color:#666;")
        self.comboPreservationActionField.blockSignals(False)

    def _save_preservation_encoding_override(self, _index):
        layer = self.comboPreservationLayer.currentLayer()
        if not layer:
            return
        selected = str(
            self.comboPreservationEncoding.currentData() or ""
        ).strip()
        if selected:
            layer.setCustomProperty(
                "ArchDistribution/encoding_override", selected
            )
        else:
            layer.removeCustomProperty(
                "ArchDistribution/encoding_override"
            )

    def pick_preservation_color(self, action, key):
        current = self.preservation_action_colors[action][key]
        color = QColorDialog.getColor(current, self)
        if not color.isValid():
            return
        self.preservation_action_colors[action][key] = color
        self.update_preservation_button_colors()
        self._save_preservation_style_preferences()

    def update_preservation_button_colors(self):
        for action, buttons in getattr(
            self, "preservationColorButtons", {}
        ).items():
            for key, button in buttons.items():
                color = self.preservation_action_colors[action][key]
                text_color = "white" if color.lightness() < 128 else "black"
                button.setText(color.name().upper())
                button.setStyleSheet(
                    f"background-color:{color.name()}; color:{text_color}; "
                    "font-weight:bold;"
                )

    def reset_preservation_styles(self):
        self.preservation_action_colors = {
            action: {
                "fill_color": QtGui.QColor(style["fill_color"]),
                "outline_color": QtGui.QColor(style["outline_color"]),
            }
            for action, style in PRESERVATION_ACTION_STYLES.items()
        }
        self.spinPreservationStrokeWidth.setValue(
            DEFAULT_SPIN_VALUES["heritage_stroke_width"]
        )
        self.spinPreservationOpacity.setValue(100)
        self.update_preservation_button_colors()
        self._save_preservation_style_preferences()

    def _apply_preservation_preset(self, width, height):
        self.spinPreservationPaperWidth.setValue(width)
        self.spinPreservationPaperHeight.setValue(height)

    def _retranslate_workflow_widgets(self):
        if not hasattr(self, "workflowTabs"):
            return
        self.workflowTabs.setTabText(
            0,
            self._t(
                "문화유적분포지도",
                "Cultural Heritage Distribution Map",
            ),
        )
        self.workflowTabs.setTabText(
            1,
            self._t(
                "매장유산 유존지역",
                "Buried Heritage Preservation Areas",
            ),
        )
        self.lblPreservationIntro.setText(
            self._t(
                "매장유산 유존지역 전용 작업입니다. 사용자가 선택한 "
                "폴리곤만 처리하며, 원본 속성을 모두 보존한 채 같은 사업명은 "
                "하나의 번호로 묶고 보존조치별 도형은 따로 유지합니다.",
                "Dedicated preservation-area workflow. It processes only the "
                "selected polygon, preserves all source attributes, assigns one "
                "number per project name, and keeps action geometries separate.",
            )
        )
        self.groupPreservationInput.setTitle(
            self._t("전용 입력", "Dedicated Input")
        )
        self.lblPreservationLayer.setText(
            self._t("유존지역 폴리곤:", "Preservation polygon:")
        )
        self.lblPreservationEncoding.setText(
            self._t("문자 인코딩:", "Text encoding:")
        )
        self.lblPreservationActionField.setText(
            self._t("보존조치 필드:", "Action field:")
        )
        self.groupPreservationExtent.setTitle(
            self._t("도곽 기준", "Map Extent")
        )
        self.lblPreservationStudyArea.setText(
            self._t(
                "기준 조사구역:",
                "Study-area baseline:",
            )
        )
        self.comboPreservationStudyArea.setToolTip(
            self._t(
                "지도 중심과 도곽을 계산할 조사구역 폴리곤입니다.",
                "Study-area polygon used to calculate map center and extent.",
            )
        )
        self.lblPreservationPaperSize.setText(
            self._t("도면 크기:", "Paper size:")
        )
        self.btnPreservationPresetReport.setText(
            self._t("보고서", "Report")
        )
        self.btnPreservationPresetA4.setText("A4")
        self.lblPreservationScale.setText(
            self._t("축척:", "Scale:")
        )
        self.chkPreservationExcludeExtentSlivers.setText(
            self._t(
                "도곽 경계의 미세 절단 조각 제외 (권장)",
                "Exclude tiny map-edge clip fragments (recommended)",
            )
        )
        self.chkPreservationExcludeExtentSlivers.setToolTip(
            self._t(
                "문화유적분포지도와 동일한 기준으로, 도곽에서 잘린 "
                "미세 폴리곤만 제외합니다.",
                "Uses the same rule as the distribution workflow to exclude "
                "only tiny polygons clipped at the map edge.",
            )
        )
        self.groupPreservationStyle.setTitle(
            self._t("보존조치 4종 스타일", "Four Action Styles")
        )
        self.lblPreservationActionHeader.setText(
            self._t("보존조치", "Action")
        )
        self.lblPreservationFillHeader.setText(
            self._t("채움색", "Fill")
        )
        self.lblPreservationOutlineHeader.setText(
            self._t("외곽선색", "Outline")
        )
        self.lblPreservationStrokeWidth.setText(
            self._t("외곽선 두께:", "Outline width:")
        )
        self.lblPreservationOpacity.setText(
            self._t("채움 불투명도:", "Fill opacity:")
        )
        self.btnResetPreservationStyles.setText(
            self._t("공식 범례 기본색으로 복원", "Restore supplied legend colors")
        )
        self.groupPreservationNumbering.setTitle(
            self._t("번호 및 라벨", "Numbering and Labels")
        )
        self.lblPreservationSortOrder.setText(
            self._t("번호 순서:", "Numbering order:")
        )
        self.lblPreservationLabelFontSize.setText(
            self._t("번호 글자 크기:", "Number font size:")
        )
        self.lblPreservationLabelFont.setText(
            self._t("번호 글씨체:", "Number font:")
        )
        self.lblPreservationGrouping.setText(
            self._t(
                "※ 같은 사업명은 하나의 번호를 공유합니다. 현상보존·정밀발굴조사·"
                "시굴조사·표본조사 경계는 합치지 않아 각각의 색을 유지합니다.",
                "* Records with the same project name share one number. Action "
                "boundaries remain separate so each category keeps its color.",
            )
        )

        current_sort = self.comboPreservationSortOrder.currentIndex()
        self.comboPreservationSortOrder.blockSignals(True)
        self.comboPreservationSortOrder.clear()
        self.comboPreservationSortOrder.addItems(
            SORT_ORDER_OPTIONS[self.ui_lang]
        )
        self.comboPreservationSortOrder.setCurrentIndex(
            max(
                0,
                min(
                    current_sort,
                    self.comboPreservationSortOrder.count() - 1,
                ),
            )
        )
        self.comboPreservationSortOrder.blockSignals(False)

    def _on_workflow_changed(self, index):
        if not hasattr(self, "btnRun"):
            return
        if index == 1:
            self.btnRun.setText(
                self._t(
                    "▶ 매장유산 유존지역 생성",
                    "Generate Preservation Areas",
                )
            )
        else:
            self.btnRun.setText(
                self._t(
                    "▶ 분석 및 지도 생성 실행",
                    "Run Analysis / Generate Map",
                )
            )

    def make_global_scrollable(self):
        """ Wraps the main content (Tabs, Logs, Buttons) in a single QScrollArea. """

        # 1. Create a ScrollArea and Container
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)  # Only vertical scroll

        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)  # Tight fit

        # 2. Identify widgets to move (Tabs, Log, Buttons)
        # Note: 'vMain' layout contains: Header, TabWidget, GroupLog, hFinal (Layout)
        # We want to keep Header in vMain, but move the rest to container.

        if not hasattr(self, 'vMain'):
            return

        # Move the outer workflow tabs (or the legacy inner tabs as fallback).
        content_tabs = (
            self.workflowTabs
            if hasattr(self, "workflowTabs")
            else self.tabWidget
        )
        self.vMain.removeWidget(content_tabs)
        container_layout.addWidget(content_tabs)

        if hasattr(self, "groupMetricCrs"):
            self.vMain.removeWidget(self.groupMetricCrs)
            container_layout.addWidget(self.groupMetricCrs)

        if hasattr(self, "groupOutputArtifacts"):
            self.vMain.removeWidget(self.groupOutputArtifacts)
            container_layout.addWidget(self.groupOutputArtifacts)

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

    def _stabilize_data_panel_layout(self):
        """Keep the layer-selection lists wide and hide the optional study-area hint."""
        if hasattr(self, "ld1u"):
            self.ld1u.clear()
            self.ld1u.setToolTip("")
            self.ld1u.hide()

    def _apply_compact_selection_buttons(self):
        """Keep list action buttons compact without changing base layout behavior."""
        compact_buttons = [
            "btnCheckTopo",
            "btnUncheckTopo",
            "btnCheckHeritage",
            "btnUncheckHeritage",
        ]
        for name in compact_buttons:
            if not hasattr(self, name):
                continue
            btn = getattr(self, name)
            btn.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            btn.setMaximumWidth(140)

        if hasattr(self, "vTopoButtons"):
            self.vTopoButtons.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        if hasattr(self, "vHeritageButtons"):
            self.vHeritageButtons.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)

    def _apply_static_ui_translation(self):
        """Translate Qt-Designer widgets at runtime while keeping .ui structure intact."""
        self.setWindowTitle(
            self._t(
                "ArchDistribution - 프리미엄 분포지도 엔진",
                "ArchDistribution - Premium Distribution Map Engine",
            )
        )
        if hasattr(self, "lSub"):
            self.lSub.setText(
                self._t(
                    "고고학 분포지도 제작 최적화 솔루션",
                    "Optimized solution for archaeological distribution mapping",
                )
            )

        if hasattr(self, "tabWidget"):
            if self.tabWidget.count() > 0:
                self.tabWidget.setTabText(0, self._t("1. 데이터 및 구획(Spec)", "1. Data & Layout (Spec)"))
            if self.tabWidget.count() > 1:
                self.tabWidget.setTabText(1, self._t("2. 스타일 및 분석(Style)", "2. Style & Analysis (Style)"))

        if hasattr(self, "groupData"):
            self.groupData.setTitle(self._t("입력 레이어 제어 (Input Layers)", "Input Layer Controls"))
        if hasattr(self, "groupSpecs"):
            self.groupSpecs.setTitle(self._t("출력 도곽 및 축척 (Print Specifications)", "Output Extent / Scale"))
        if hasattr(self, "groupSym"):
            self.groupSym.setTitle(self._t("레이어별 정밀 심볼 제어 (Detailed Symbology)", "Detailed Symbology"))
        if hasattr(self, "groupBuffer"):
            self.groupBuffer.setTitle(self._t("버퍼 정밀 스타일 (Buffer Analysis)", "Buffer Analysis"))
        if hasattr(self, "groupNumbering"):
            self.groupNumbering.setTitle(self._t("유적 번호 매기기 기준 (Numbering Rules)", "Numbering Rules"))
        if hasattr(self, "groupLog"):
            self.groupLog.setTitle(self._t("🚀 진행 상태 로그", "🚀 Progress Log"))

        if hasattr(self, "ld1"):
            self.ld1.setText(self._t("① 조사지역 선택 (기준):", "① Study area:"))
            self.ld1.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
            self.ld1.setMinimumWidth(160)
            self.ld1.setMaximumWidth(160)
            self.ld1.setToolTip(
                self._t(
                    "지도 중심 및 도곽 설정의 기준이 되는 레이어입니다.",
                    "This layer is used as the baseline for map center and layout extent.",
                )
            )
        if hasattr(self, "ld1u"):
            self.ld1u.clear()
        if hasattr(self, "ld2"):
            self.ld2.setText(self._t("② 수치지형도 (배경):", "② Topographic layers:"))
            self.ld2.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
            self.ld2.setMinimumWidth(160)
            self.ld2.setMaximumWidth(160)
        if hasattr(self, "ld3"):
            self.ld3.setText(self._t("③ 주변 유적 (분석):", "③ Heritage layers:"))
            self.ld3.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
            self.ld3.setMinimumWidth(160)
            self.ld3.setMaximumWidth(160)

        if hasattr(self, "comboStudyArea"):
            self.comboStudyArea.setToolTip(
                self._t(
                    "분석의 기준이 되는 조사범위 폴리곤 레이어를 선택하세요.",
                    "Select the study-area polygon layer used as analysis baseline.",
                )
            )
        if hasattr(self, "listTopoLayers"):
            self.listTopoLayers.setToolTip(
                self._t(
                    "배경으로 깔릴 수치지형도를 모두 선택하세요 (Shift/Ctrl 드래그 가능).",
                    "Select all topo layers for background (Shift/Ctrl multi-select supported).",
                )
            )
        if hasattr(self, "listHeritageLayers"):
            self.listHeritageLayers.setToolTip(
                self._t(
                    "분포지도에 표시할 유적 레이어를 모두 선택하세요.",
                    "Select heritage layers to include in the distribution map.",
                )
            )

        if hasattr(self, "btnCheckTopo"):
            self.btnCheckTopo.setText(self._t("선택 설정(V)", "Check selected"))
            self.btnCheckTopo.setToolTip(
                self._t(
                    "목록에서 선택(음영표시)된 항목의 체크박스를 활성화합니다.",
                    "Check selected items in the list.",
                )
            )
        if hasattr(self, "btnUncheckTopo"):
            self.btnUncheckTopo.setText(self._t("선택 해제", "Uncheck selected"))
        if hasattr(self, "btnCheckHeritage"):
            self.btnCheckHeritage.setText(self._t("선택 설정(V)", "Check selected"))
            self.btnCheckHeritage.setToolTip(
                self._t(
                    "목록에서 선택(음영표시)된 항목의 체크박스를 활성화합니다.",
                    "Check selected items in the list.",
                )
            )
        if hasattr(self, "btnUncheckHeritage"):
            self.btnUncheckHeritage.setText(self._t("선택 해제", "Uncheck selected"))

        if hasattr(self, "btnPresetReport"):
            self.btnPresetReport.setText(self._t("보고서 (160x240)", "Report (160x240)"))
            self.btnPresetReport.setToolTip(
                self._t(
                    "표준 보고서 사이즈로 가로/세로 길이를 자동 설정합니다.",
                    "Apply report-size preset for width/height.",
                )
            )
        if hasattr(self, "btnPresetA4"):
            self.btnPresetA4.setText("A4 (210x297)")
            self.btnPresetA4.setToolTip(
                self._t(
                    "A4 사이즈로 가로/세로 길이를 자동 설정합니다.",
                    "Apply A4 preset for width/height.",
                )
            )

        if hasattr(self, "lp1"):
            self.lp1.setText(self._t("도면 가로(W):", "Paper width (W):"))
        if hasattr(self, "lp1u"):
            self.lp1u.setText(self._t("mm (밀리미터)", "mm (millimeter)"))
        if hasattr(self, "lp2"):
            self.lp2.setText(self._t("도면 세로(H):", "Paper height (H):"))
        if hasattr(self, "lp2u"):
            self.lp2u.setText(self._t("mm (밀리미터)", "mm (millimeter)"))
        if hasattr(self, "lp3"):
            self.lp3.setText(self._t("축척(Scale):", "Scale:"))
        if hasattr(self, "lp3u"):
            self.lp3u.setText(self._t("1 : [입력값]", "1 : [value]"))

        if hasattr(self, "ls1"):
            self.ls1.setText(self._t("① 주변 유적 스타일:", "① Heritage style:"))
        if hasattr(self, "spinHeritageStrokeWidth"):
            self.spinHeritageStrokeWidth.setToolTip(
                self._t(
                    "유적 폴리곤의 외곽선 두께(mm)를 설정합니다.",
                    "Set heritage polygon stroke width in mm.",
                )
            )
        if hasattr(self, "spinHeritageOpacity"):
            self.spinHeritageOpacity.setToolTip(
                self._t(
                    "유적 내부 채움 색상의 투명도입니다 (0% = 투명, 100% = 불투명).",
                    "Opacity of heritage fill color (0% transparent, 100% opaque).",
                )
            )
        if hasattr(self, "ls2"):
            self.ls2.setText(self._t("② 조사지역 스타일:", "② Study area style:"))
        if hasattr(self, "ls3"):
            self.ls3.setText(self._t("③ 수치지형도 스타일:", "③ Topographic style:"))
        if hasattr(self, "lStudyInfo"):
            self.lStudyInfo.setText(
                self._t(
                    "※ 조사지역은 내부를 비우고 외곽선만 표시합니다.",
                    "* Study area is rendered as outline only (no fill).",
                )
            )
        if hasattr(self, "lTopoInfo"):
            self.lTopoInfo.setText(
                self._t(
                    "※ 수치지형도의 모든 라인을 병합하여 단일 색상으로 표현합니다.",
                    "* Topographic lines are merged and rendered in one color.",
                )
            )

        if hasattr(self, "btnHeritageStrokeColor"):
            self.btnHeritageStrokeColor.setText(self._t("테두리 색상", "Stroke color"))
        if hasattr(self, "btnHeritageFillColor"):
            self.btnHeritageFillColor.setText(self._t("채움(면) 색상", "Fill color"))
        if hasattr(self, "btnStudyStrokeColor"):
            self.btnStudyStrokeColor.setText(self._t("테두리 색상", "Stroke color"))
        if hasattr(self, "btnTopoStrokeColor"):
            self.btnTopoStrokeColor.setText(self._t("수치지형도 색상", "Topo color"))

        if hasattr(self, "lb1"):
            self.lb1.setText(self._t("① 조사구역 버퍼 거리(m):", "① Study-area buffer distance (m):"))
        if hasattr(self, "editBufferDistance"):
            self.editBufferDistance.setToolTip(
                self._t(
                    "조사구역 주변으로 그릴 반경(미터)을 입력하세요 (예: 500).",
                    "Enter buffer distance in meters (e.g., 500).",
                )
            )
            self.editBufferDistance.setPlaceholderText(
                self._t("숫자 입력 (예: 500)", "Enter number (e.g., 500)")
            )
        if hasattr(self, "btnAddBuffer"):
            self.btnAddBuffer.setText(self._t("추가 (+)", "Add (+)"))
        if hasattr(self, "listBuffers"):
            self.listBuffers.setToolTip(
                self._t(
                    "추가된 버퍼 목록입니다. 더블클릭하면 삭제할 수 있습니다.",
                    "Added buffer list. Double-click an item to remove.",
                )
            )
        if hasattr(self, "lb2"):
            self.lb2.setText(self._t("② 버퍼 라인 스타일:", "② Buffer line style:"))
        if hasattr(self, "chkBufferKmLabels"):
            self.chkBufferKmLabels.setText(
                self._t(
                    "1,000m 이상은 km로 표시",
                    "Show 1,000m and above in km",
                )
            )
            self.chkBufferKmLabels.setToolTip(
                self._t(
                    "버퍼 속성은 DIST_M 한 개만 남기고 항상 미터로 저장합니다. "
                    "체크하면 지도 라벨만 1km, 1.5km처럼 표시합니다.",
                    "Keep only DIST_M in the buffer attributes and always store "
                    "it in metres. When checked, map labels use 1km, 1.5km, "
                    "and similar formatting.",
                )
            )
        if hasattr(self, "spinBufferWidth"):
            self.spinBufferWidth.setToolTip(
                self._t(
                    "버퍼 라인의 두께(mm)를 설정합니다.",
                    "Set buffer line width in mm.",
                )
            )
        if hasattr(self, "lbWidthUnit"):
            self.lbWidthUnit.setText(self._t("mm (두께)", "mm (width)"))
        if hasattr(self, "btnBufferColor"):
            self.btnBufferColor.setText(self._t("라인 색상 설정", "Line color"))

        if hasattr(self, "ln1"):
            self.ln1.setText(self._t("번호 부여 질서(목록):", "Numbering order:"))
        if hasattr(self, "btnRenumber"):
            self.btnRenumber.setText(
                self._t(
                    "🔄 번호만 다시 매기기 (중복·대표 판정 유지)",
                    "Renumber active result (keep match decisions)",
                )
            )
            self.btnRenumber.setToolTip(
                self._t(
                    "활성화한 ArchDistribution 결과의 NUMBER_KEY와 대표 판정을 "
                    "유지한 채, 현재 도곽·버퍼·정렬 기준으로 번호 순서, "
                    "이격거리, 대표 라벨 위치(LABEL_OK)만 다시 계산합니다. "
                    "중복 후보를 다시 판정하지 않습니다.",
                    "Keep the active ArchDistribution result's NUMBER_KEY "
                    "groups and representative decisions, then recalculate "
                    "only number order, distance, and label anchors (LABEL_OK) "
                    "from the current extent, buffers, and sort order. "
                    "Duplicate candidates are not re-evaluated.",
                )
            )
        if hasattr(self, "ln1u"):
            self.ln1u.setText(self._t("(자동 번호 부여)", "(auto numbering)"))
        if hasattr(self, "lnScaleInfo"):
            self.lnScaleInfo.setText(self._t("⚠ 현재 축척:", "⚠ Current scale:"))

        if hasattr(self, "btnRun"):
            self.btnRun.setText(self._t("▶ 분석 및 지도 생성 실행", "Run Analysis / Generate Map"))

        if hasattr(self, "btnHelp"):
            self.btnHelp.setToolTip(self._t("사용 가이드 및 PDF 반출 도움말", "User guide and export tips"))

        self._apply_compact_selection_buttons()

    def _add_language_selector(self):
        """Add manual UI language selector without modifying the .ui layout file."""
        if not hasattr(self, "hHeader"):
            return

        self.lblUiLang = QtWidgets.QLabel("Language:")
        self.comboUiLang = QtWidgets.QComboBox()
        self.comboUiLang.setToolTip(
            self._t(
                "UI 언어를 수동 선택합니다. 즉시 반영됩니다.",
                "Manually choose UI language. Applies immediately.",
            )
        )
        self.comboUiLang.setMinimumWidth(125)
        self._populate_language_selector_items()

        self.comboUiLang.currentIndexChanged.connect(self._on_language_combo_changed)

        # hHeader order: title, spacer, help, subtitle. Insert selector before help.
        self.hHeader.insertWidget(2, self.lblUiLang)
        self.hHeader.insertWidget(3, self.comboUiLang)

    def _populate_language_selector_items(self):
        """Populate language selector options and keep the persisted selection."""
        if not hasattr(self, "comboUiLang"):
            return

        pref = get_ui_language_preference()
        self.comboUiLang.blockSignals(True)
        self.comboUiLang.clear()
        self.comboUiLang.addItem("Auto (QGIS)", "auto")
        self.comboUiLang.addItem("Korean", "ko")
        self.comboUiLang.addItem("English", "en")

        idx = self.comboUiLang.findData(pref)
        if idx < 0:
            idx = 0
        self.comboUiLang.setCurrentIndex(idx)
        self.comboUiLang.blockSignals(False)

    def _retranslate_dynamic_widgets(self):
        """Update programmatically created widgets when language preference changes."""
        # Update combo options while preserving current selection index
        if hasattr(self, "comboBufferStyle"):
            idx = self.comboBufferStyle.currentIndex()
            self.comboBufferStyle.blockSignals(True)
            self.comboBufferStyle.clear()
            self.comboBufferStyle.addItems(BUFFER_STYLE_OPTIONS[self.ui_lang])
            self.comboBufferStyle.setCurrentIndex(max(0, min(idx, self.comboBufferStyle.count() - 1)))
            self.comboBufferStyle.blockSignals(False)

        if hasattr(self, "comboSortOrder"):
            idx = self.comboSortOrder.currentIndex()
            self.comboSortOrder.blockSignals(True)
            self.comboSortOrder.clear()
            self.comboSortOrder.addItems(SORT_ORDER_OPTIONS[self.ui_lang])
            self.comboSortOrder.setCurrentIndex(max(0, min(idx, self.comboSortOrder.count() - 1)))
            self.comboSortOrder.blockSignals(False)
        if hasattr(self, "groupDuplicatePolicy"):
            self.groupDuplicatePolicy.setTitle(
                self._t(
                    "자료 역할 및 중복 판정",
                    "Source Roles and Duplicate Matching",
                )
            )
            self.lblMatchingSummary.setText(
                self._t(
                    "<b>중복 판정과 번호 재정렬은 다른 작업입니다.</b><br>"
                    "대표화는 원본 삭제가 아니라 지도에서 사용할 번호와 대표 "
                    "라벨만 하나로 정하는 작업입니다. 중복·대표 결정을 바꾸려면 "
                    "<b>지정·분포·발굴·지표 원본 레이어</b>로 다시 분석하고, "
                    "현재 결정을 유지한 채 순서만 바꾸려면 스타일 탭의 "
                    "<b>[번호만 다시 매기기]</b>를 사용하세요.",
                    "<b>Duplicate review and renumbering are different "
                    "operations.</b><br>Representative merging never deletes "
                    "source data; it only selects one numbering identity and "
                    "map label. Re-run the <b>original designated, "
                    "distribution, excavation, and surface-survey layers</b> "
                    "to change a decision. To keep decisions and change only "
                    "the order, use <b>[Renumber active result]</b> on the "
                    "Style tab.",
                )
            )
            self.btnMatchingRulesHelp.setText(
                self._t(
                    "ⓘ 판정 기준 쉽게 보기",
                    "ⓘ View matching rules",
                )
            )
            self.lblMatchPreset.setText(
                self._t("판정 모드:", "Matching preset:")
            )
            self.chkReuseReviewDecisions.setText(
                self._t(
                    "이전 검토 결정을 저장·재사용 (권장)",
                    "Save and reuse prior review decisions (recommended)",
                )
            )
            self.chkReuseReviewDecisions.setToolTip(
                self._t(
                    "원본 내용과 판정 규칙이 모두 같을 때만 자동 재사용합니다. "
                    "자료가 바뀌면 다시 검토창에 표시됩니다.",
                    "A decision is reused only when source content and the "
                    "matching policy are unchanged. Changed data is reviewed again.",
                )
            )
            self.lblRoleHelp.setText(
                self._t(
                    "레이어명과 필드로 자동 판정합니다. 잘못 판정된 "
                    "자료만 역할을 직접 바꾸세요. 실제 처리는 위의 "
                    "주변 유적 목록에서 체크한 레이어에만 적용됩니다.",
                    "Roles are inferred from layer names and fields. "
                    "Override only incorrect roles; processing still applies "
                    "only to layers checked in the heritage list above.",
                )
            )
            self.tableLayerRoles.setHorizontalHeaderLabels([
                self._t("레이어", "Layer"),
                self._t("자료 역할", "Source role"),
                self._t("문자 인코딩", "Text encoding"),
            ])
            preset_value = self.comboMatchPreset.currentData()
            self.comboMatchPreset.blockSignals(True)
            self.comboMatchPreset.clear()
            preset_labels = (
                MATCH_PRESET_LABELS_EN
                if self.ui_lang == "en"
                else MATCH_PRESET_LABELS
            )
            for key, label in preset_labels.items():
                self.comboMatchPreset.addItem(label, key)
            self.comboMatchPreset.setCurrentIndex(
                max(0, self.comboMatchPreset.findData(preset_value))
            )
            self.comboMatchPreset.blockSignals(False)

            for combo in self.layerRoleCombos.values():
                role_value = combo.currentData()
                combo.blockSignals(True)
                combo.clear()
                for role in SOURCE_ROLE_ORDER:
                    combo.addItem(
                        source_role_label(role, self.ui_lang),
                        role,
                    )
                combo.setCurrentIndex(
                    max(0, combo.findData(role_value))
                )
                combo.blockSignals(False)

            self._update_previous_result_guidance()

        if hasattr(self, "groupPreviousResult"):
            self.groupPreviousResult.setTitle(
                self._t(
                    "기존 결과 후속 작업 — 번호만 다시 매기기",
                    "Existing Result Follow-up — Renumber Only",
                )
            )
            self.lblPreviousResultHelp.setText(
                self._t(
                    "<b>중복·대표 판정은 유지하고 번호만 정리합니다.</b><br>"
                    "편집·삭제한 ArchDistribution 대표 결과를 고르면 "
                    "<code>NUMBER_KEY</code> 묶음과 판정 필드는 그대로 두고, "
                    "현재 도곽·버퍼·정렬 기준에 맞춰 번호, 이격거리와 "
                    "대표 라벨 위치(<code>LABEL_OK</code>)만 다시 계산합니다. "
                    "중복 후보는 다시 비교하지 않습니다.",
                    "<b>Keep match decisions and reorder numbers only.</b><br>"
                    "Choose an edited ArchDistribution representative result. "
                    "Its <code>NUMBER_KEY</code> groups and match fields stay "
                    "unchanged; only numbers, distance, and representative "
                    "label anchors (<code>LABEL_OK</code>) are recalculated "
                    "from the current extent, buffers, and sort order. "
                    "Duplicate candidates are not compared again.",
                )
            )
            self.lblPreviousResultLayer.setText(
                self._t("대표 결과:", "Representative result:")
            )
            self.btnRenumberPreviousResult.setText(
                self._t(
                    "번호만 다시 매기기",
                    "Renumber this result",
                )
            )
            self.btnRenumberPreviousResult.setToolTip(
                self._t(
                    "선택한 대표 결과를 활성 레이어로 바꿀 필요 없이 바로 "
                    "재번호합니다. 중복·대표 판정은 유지됩니다.",
                    "Renumber the selected representative result without "
                    "first activating it. Match and representative decisions "
                    "are retained.",
                )
            )
            self._update_previous_result_status()

        if hasattr(self, "groupOutputArtifacts"):
            self.groupOutputArtifacts.setTitle(
                self._t(
                    "선택 저장 및 인쇄조판 출력",
                    "Optional Archive and Print Outputs",
                )
            )
            self.lblOutputDirectory.setText(
                self._t("저장 폴더:", "Output folder:")
            )
            self.btnBrowseOutputDirectory.setText(
                self._t("찾아보기…", "Browse…")
            )
            self.chkSaveGpkgManifest.setText(
                self._t(
                    "GeoPackage + 실행정보(JSON)",
                    "GeoPackage + run manifest (JSON)",
                )
            )
            self.chkExportLayoutJpg.setText(
                self._t(
                    "인쇄조판 JPG",
                    "Print-layout JPG",
                )
            )
            self.chkExportLayoutPdf.setText(
                self._t(
                    "인쇄조판 PDF",
                    "Print-layout PDF",
                )
            )
            self.lblOutputArtifactHelp.setText(
                self._t(
                    "기본값은 꺼짐입니다. 선택하면 현재 도곽·용지·축척으로 "
                    "결과를 저장하며 원본 파일은 수정하지 않습니다.",
                    "Disabled by default. Selected outputs use the current "
                    "extent, paper size, and scale without modifying sources.",
                )
            )

        if hasattr(self, "groupMetricCrs"):
            self.groupMetricCrs.setTitle(
                self._t(
                    "고급 측정 좌표계 (두 작업 공통)",
                    "Advanced Measurement CRS (Both Workflows)",
                )
            )
            self.lblMetricCrsHelp.setText(
                self._t(
                    "<b>기본값: 자동 선택.</b> 미터 투영 원본은 그대로 쓰고, "
                    "경위도·피트 자료는 조사 중심의 지역 UTM으로 측정합니다. "
                    "도곽·버퍼·거리·면적·미세조각 기준에 공통 적용됩니다.",
                    "<b>Default: automatic.</b> A projected-metre source is kept; "
                    "geographic or foot-based data use local UTM at the study "
                    "centroid. This applies to extent, buffer, distance, area, "
                    "and micro-fragment measurements.",
                )
            )
            self.chkOverrideAnalysisCrs.setText(
                self._t(
                    "전문가용: 분석 좌표계를 직접 지정",
                    "Expert: choose the analysis CRS manually",
                )
            )
            self.chkOverrideAnalysisCrs.setToolTip(
                self._t(
                    "특별한 투영이 필요한 경우에만 사용합니다. 선택 좌표계는 "
                    "미터 단위 투영좌표계여야 합니다.",
                    "Use only when a specific projection is required. The "
                    "selected CRS must be projected and measured in metres.",
                )
            )
            self.lblAnalysisCrs.setText(
                self._t("분석 좌표계:", "Analysis CRS:")
            )

        if hasattr(self, "groupSmartFilter"):
            self.groupSmartFilter.setTitle(self._t("유적 속성 분류", "Site Attribute Classification"))
        if hasattr(self, "lSmartDesc"):
            self.lSmartDesc.setText(
                self._t(
                    "체크된 유적 레이어의 명칭을 분석하여 시대와 성격을 자동 분류합니다.",
                    "Analyze selected heritage-layer names and classify period/type automatically.",
                )
            )
        if hasattr(self, "btnSmartScan"):
            self.btnSmartScan.setText(self._t("속성 분류 실행", "Run Attribute Scan"))
        if hasattr(self, "lblEra"):
            self.lblEra.setText(self._t("시대", "Era"))
        if hasattr(self, "lblType"):
            self.lblType.setText(self._t("성격", "Type"))
        if hasattr(self, "lblExclusion"):
            self.lblExclusion.setText(self._t("제외 제안 목록 (체크시 제외됨):", "Suggested Exclusions (checked = exclude):"))

        if hasattr(self, "groupLegalLayers"):
            self.groupLegalLayers.setTitle(self._t(
                "국가유산청 법정 레이어 (주변유적 선택 불필요)",
                "National Heritage Administration legal layers (independent of nearby heritage)",
            ))
        if hasattr(self, "lblZoneLayer"):
            self.lblZoneLayer.setText(self._t(
                "현상변경 허용기준 레이어:",
                "Current-change standard layer:",
            ))
        if hasattr(self, "lblZoneField"):
            self.lblZoneField.setText(self._t(
                "구역 분류 필드:",
                "Zone category field:",
            ))
            self.comboZoneField.setToolTip(self._t(
                "반드시 1구역, 2-1구역, 3-4구역 같은 값이 실제로 들어 있는 필드를 선택하세요. NAME 등 설명 필드를 고르면 단색으로 보일 수 있습니다.",
                "Select the field that actually contains values such as Zone 1, 2-1, or 3-4. Selecting a descriptive NAME field can produce a single colour.",
            ))
        if hasattr(self, "lblNationalDesignatedLayer"):
            self.lblNationalDesignatedLayer.setText(self._t(
                "국가지정유산 레이어:", "Nationally designated heritage:",
            ))
        if hasattr(self, "lblNationalProtectionLayer"):
            self.lblNationalProtectionLayer.setText(self._t(
                "국가지정유산 보호구역:", "National protection zone:",
            ))
        if hasattr(self, "lblLocalDesignatedLayer"):
            self.lblLocalDesignatedLayer.setText(self._t(
                "시도지정유산 레이어:", "Provincially designated heritage:",
            ))
        if hasattr(self, "lblLocalProtectionLayer"):
            self.lblLocalProtectionLayer.setText(self._t(
                "시도지정유산 보호구역:", "Provincial protection zone:",
            ))
        if hasattr(self, "chkClipZoneToBuffer"):
            self.chkClipZoneToBuffer.setText(self._t("버퍼 범위 내 자르기 (반경 내만 표시)", "Clip to buffer extent (inside radius only)"))
            self.chkClipZoneToBuffer.setToolTip(
                self._t(
                    "체크 시, 도곽 전체가 아닌 조사 반경(가장 큰 버퍼) 내의 현상변경허용기준만 남기고 나머지는 잘라냅니다.",
                    "Keep only zone features inside the largest survey buffer (instead of full extent).",
                )
            )
        if hasattr(self, "chkRestrictToBuffer"):
            self.chkRestrictToBuffer.setText(self._t("버퍼 범위 외 유적 제외 (감추기)", "Exclude sites outside buffer (hide)"))
            self.chkRestrictToBuffer.setToolTip(
                self._t(
                    "체크 시: 최외곽 버퍼 바깥의 유적은 번호를 매기지 않고 지도에서 숨깁니다. (지표조사 등)\n체크 해제 시: 모든 유적에 번호를 매깁니다. (일반조사 등)",
                    "Checked: hide/unnumber sites outside the outermost buffer.\nUnchecked: number all sites.",
                )
            )
        if hasattr(self, "chkExcludeExtentSlivers"):
            self.chkExcludeExtentSlivers.setText(
                self._t(
                    "도곽 경계의 미세 절단 조각 제외 (권장)",
                    "Exclude tiny map-edge clip fragments (recommended)",
                )
            )
            self.chkExcludeExtentSlivers.setToolTip(
                self._t(
                    "도곽에 걸쳐 잘린 폴리곤 중 인쇄상 거의 보이지 않는 "
                    "미세 조각만 제외합니다. 도곽 안에 온전히 들어온 작은 "
                    "유적은 제외하지 않습니다.",
                    "Exclude only nearly invisible polygon slivers produced at "
                    "the map edge. Complete small sites inside the extent are kept.",
                )
            )

        if hasattr(self, "groupLabelStyle"):
            self.groupLabelStyle.setTitle(self._t("라벨 스타일", "Label Style"))
        if hasattr(self, "lblFontSize"):
            self.lblFontSize.setText(self._t("글자 크기:", "Font size:"))
        if hasattr(self, "spinLabelFontSize"):
            self.spinLabelFontSize.setToolTip(self._t("유적 번호 라벨의 글자 크기 (pt)", "Label font size (pt) for site number"))
        if hasattr(self, "lblFontFamily"):
            self.lblFontFamily.setText(self._t("글씨체:", "Font family:"))
        if hasattr(self, "comboLabelFont"):
            self.comboLabelFont.setToolTip(self._t("유적 번호 라벨의 글씨체", "Label font family for site number"))

        if hasattr(self, "btnExcludeSel"):
            self.btnExcludeSel.setText(self._t("선택 항목 제외 (체크)", "Exclude selected (check)"))
            self.btnExcludeSel.setToolTip(self._t("선택한 항목들을 리스트에서 체크합니다. (지도에서 제외됨)", "Check selected items (excluded on map)"))
        if hasattr(self, "btnIncludeSel"):
            self.btnIncludeSel.setText(self._t("선택 항목 포함 (해제)", "Include selected (uncheck)"))
            self.btnIncludeSel.setToolTip(self._t("선택한 항목들의 체크를 해제합니다. (지도에 포함됨)", "Uncheck selected items (included on map)"))

        if hasattr(self, "lblUiLang"):
            self.lblUiLang.setText("Language:")
        if hasattr(self, "comboUiLang"):
            self.comboUiLang.setToolTip(
                self._t(
                    "UI 언어를 수동 선택합니다. 즉시 반영됩니다.",
                    "Manually choose UI language. Applies immediately.",
                )
            )
            self._populate_language_selector_items()

        self._apply_static_ui_translation()
        self._stabilize_data_panel_layout()
        self.update_scale_indicator()
        self._retranslate_workflow_widgets()
        if hasattr(self, "workflowTabs"):
            self._on_workflow_changed(self.workflowTabs.currentIndex())

    def _on_language_combo_changed(self, _index):
        selected = str(self.comboUiLang.currentData())
        if not selected:
            return

        current_pref = get_ui_language_preference()
        if selected == current_pref:
            return

        QtCore.QSettings().setValue(LANG_PREF_KEY, selected)
        self.ui_lang = detect_ui_language()
        self._retranslate_dynamic_widgets()
        QtWidgets.QMessageBox.information(
            self,
            self._t("언어 설정", "Language Setting"),
            self._t(
                "언어 설정이 저장되었습니다.\n현재 창에 즉시 반영됩니다.",
                "Language preference has been saved.\nIt has been applied to the current dialog.",
            ),
        )

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
        analysis_crs_error = self._analysis_crs_override_error()
        if analysis_crs_error:
            QtWidgets.QMessageBox.warning(
                self,
                self._t("좌표계 오류", "CRS Error"),
                analysis_crs_error,
            )
            return
        if settings["workflow_mode"] == "preservation":
            if not settings["preservation_layer_id"]:
                QtWidgets.QMessageBox.warning(
                    self,
                    self._t("입력 오류", "Input Error"),
                    self._t(
                        "매장유산 유존지역 폴리곤 레이어를 선택해 주세요.",
                        "Select a buried-heritage preservation polygon layer.",
                    ),
                )
                return
            if not settings["preservation_study_area_id"]:
                QtWidgets.QMessageBox.warning(
                    self,
                    self._t("입력 오류", "Input Error"),
                    self._t(
                        "도곽 기준이 될 조사구역 폴리곤을 선택해 주세요.",
                        "Select a study-area polygon for the map extent.",
                    ),
                )
                return
            self.run_requested.emit(settings)
            return

        if not settings['study_area_id']:
            QtWidgets.QMessageBox.warning(
                self,
                self._t("입력 오류", "Input Error"),
                self._t("조사지역 레이어를 선택해 주세요.", "Please select a study-area layer."),
            )
            return
        previous_results = self._checked_previous_result_layers()
        if (
            previous_results
            and not self._confirm_previous_result_reprocessing(
                previous_results
            )
        ):
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
            if target == 'heritage_stroke':
                self.heritage_stroke_color = color
            elif target == 'heritage_fill':
                self.heritage_fill_color = color
            elif target == 'study_stroke':
                self.study_stroke_color = color
            elif target == 'topo_stroke':
                self.topo_stroke_color = color
            elif target == 'buffer':
                self.buffer_color = color
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

    @staticmethod
    def _result_field_map(layer):
        if not layer or layer.type() != 0:
            return {}
        return {
            field.name().casefold(): field.name()
            for field in layer.fields()
        }

    @staticmethod
    def _result_value_is_empty(value):
        if value is None:
            return True
        return str(value).strip().casefold() in {
            "",
            "null",
            "none",
            "<null>",
        }

    def _classify_result_layer(self, layer):
        """Classify current/legacy ArchDistribution outputs conservatively."""
        result = {
            "kind": "not_result",
            "current_schema": False,
            "feature_count": 0,
        }
        if not layer or layer.type() != 0:
            return result

        result["feature_count"] = max(0, int(layer.featureCount()))
        field_map = self._result_field_map(layer)
        layer_name = str(layer.name() or "")
        compact_name = layer_name.replace(" ", "").casefold()

        if "중복_판정_검수표" in compact_name:
            result["kind"] = "audit"
            return result
        if "중복_보존" in compact_name:
            result["kind"] = "suppressed"
            return result
        if (
            "지정유산_보호구역" in compact_name
            or "보호구역" in compact_name
            and "유적" not in compact_name
        ):
            result["kind"] = "protection"
            return result

        current_core = {
            "번호",
            "src_uid",
            "number_key",
            "group_key",
            "is_rep",
            "src_json",
        }
        has_current_core = current_core.issubset(field_map)
        result["current_schema"] = has_current_core

        if not has_current_core:
            legacy_name_hint = any(
                marker in compact_name
                for marker in (
                    "수집_및_병합된_주변유적",
                    "병합된_주변유적",
                    "archdistribution",
                )
            )
            if "번호" in field_map and legacy_name_hint:
                result["kind"] = "legacy"
            return result

        rep_values = set()
        protection_signal = False
        rep_name = field_map.get("is_rep")
        if rep_name:
            rep_index = layer.fields().indexFromName(rep_name)
            for raw_rep in layer.uniqueValues(rep_index, 4):
                if self._result_value_is_empty(raw_rep):
                    continue
                try:
                    rep_values.add(1 if int(float(raw_rep)) else 0)
                except (TypeError, ValueError):
                    text_value = str(raw_rep).strip().casefold()
                    if text_value in {"true", "yes", "y"}:
                        rep_values.add(1)
                    elif text_value in {"false", "no", "n"}:
                        rep_values.add(0)

        number_key_name = field_map.get("number_key")
        has_number_key = False
        if number_key_name:
            number_key_index = layer.fields().indexFromName(number_key_name)
            has_number_key = any(
                not self._result_value_is_empty(value)
                for value in layer.uniqueValues(number_key_index, 10)
            )

        for key in ("source_role", "match_status"):
            actual_name = field_map.get(key)
            if not actual_name:
                continue
            field_index = layer.fields().indexFromName(actual_name)
            protection_signal = protection_signal or any(
                str(value or "").strip().casefold() == "protection_zone"
                for value in layer.uniqueValues(field_index, 10)
            )

        if protection_signal and 1 not in rep_values:
            result["kind"] = "protection"
        elif rep_values == {0, 1}:
            result["kind"] = "mixed"
        elif rep_values == {0}:
            result["kind"] = "suppressed" if has_number_key else "protection"
        elif rep_values == {1} and has_number_key:
            result["kind"] = "main"
        elif (
            not rep_values
            and has_number_key
            and "수집_및_병합된_주변유적" in compact_name
        ):
            result["kind"] = "main"
        else:
            result["kind"] = "unknown_result"
        return result

    def _is_previous_distribution_result(self, layer):
        if (
            not layer
            or self._detect_preservation_field(layer)
        ):
            return False
        return self._classify_result_layer(layer)["kind"] == "main"

    def _checked_previous_result_layers(self):
        layers = []
        for index in range(self.listHeritageLayers.count()):
            item = self.listHeritageLayers.item(index)
            if item.checkState() != QtCore.Qt.Checked:
                continue
            if not bool(item.data(QtCore.Qt.UserRole + 1)):
                continue
            layer = QgsProject.instance().mapLayer(
                item.data(QtCore.Qt.UserRole)
            )
            if layer:
                layers.append(layer)
        return layers

    def _update_previous_result_guidance(self, _item=None):
        if not hasattr(self, "lblPreviousResultInputWarning"):
            return
        layers = self._checked_previous_result_layers()
        if not layers:
            self.lblPreviousResultInputWarning.hide()
            return

        displayed_names = ", ".join(
            html.escape(layer.name()) for layer in layers[:3]
        )
        if len(layers) > 3:
            displayed_names += self._t(
                f" 외 {len(layers) - 3}개",
                f" and {len(layers) - 3} more",
            )
        self.lblPreviousResultInputWarning.setText(
            self._t(
                "<b>⚠ 이전 ArchDistribution 대표 결과가 원본 목록에 "
                f"선택되었습니다: {displayed_names}</b><br>"
                "번호 순서만 정리하려면 이 레이어를 원본으로 다시 넣지 말고 "
                "스타일 탭의 <b>[기존 결과 후속 작업]</b>을 사용하세요. "
                "대표 결과만 재입력하면 숨겨진 중복_보존 자료와 원래 후보 "
                "관계를 모두 복원할 수 없고, 행별 자료 역할도 단일 레이어로 "
                "다시 해석될 수 있습니다. 중복·대표 결정을 바꾸려면 각 "
                "출처의 원본 레이어를 선택해야 합니다.",
                "<b>⚠ An existing ArchDistribution representative result is "
                f"selected as source data: {displayed_names}</b><br>"
                "To reorder numbers only, do not feed this layer back as a "
                "source. Use <b>[Existing Result Follow-up]</b> on the Style "
                "tab. A representative result alone cannot restore suppressed "
                "sources or original candidate relations, and its per-record "
                "roles may be reinterpreted as one layer role. Select the "
                "original source layers to change duplicate or representative "
                "decisions.",
            )
        )
        self.lblPreviousResultInputWarning.show()

    def _populate_previous_result_layers(self):
        if not hasattr(self, "comboPreviousResultLayer"):
            return
        previous_id = self.comboPreviousResultLayer.currentData()
        self.comboPreviousResultLayer.blockSignals(True)
        self.comboPreviousResultLayer.clear()

        result_layers = [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if self._is_previous_distribution_result(layer)
        ]
        result_layers.sort(key=lambda layer: layer.name().casefold())
        for layer in result_layers:
            self.comboPreviousResultLayer.addItem(
                self._t(
                    f"{layer.name()} ({layer.featureCount():,}개 도형)",
                    f"{layer.name()} ({layer.featureCount():,} features)",
                ),
                layer.id(),
            )
        if previous_id:
            previous_index = self.comboPreviousResultLayer.findData(
                previous_id
            )
            if previous_index >= 0:
                self.comboPreviousResultLayer.setCurrentIndex(previous_index)
        self.comboPreviousResultLayer.blockSignals(False)
        self._update_previous_result_status()

    def _update_previous_result_status(self, _index=None):
        if not hasattr(self, "comboPreviousResultLayer"):
            return
        layer = QgsProject.instance().mapLayer(
            self.comboPreviousResultLayer.currentData()
        )
        enabled = bool(layer)
        self.btnRenumberPreviousResult.setEnabled(enabled)
        if not layer:
            self.lblPreviousResultStatus.setText(
                self._t(
                    "프로젝트에서 호환되는 대표 결과를 찾지 못했습니다. "
                    "ArchDistribution 1.0.5 결과 레이어를 불러오면 자동으로 "
                    "표시됩니다.",
                    "No compatible representative result was found. Load an "
                    "ArchDistribution 1.0.5 result layer and it will appear "
                    "here automatically.",
                )
            )
            return

        field_map = self._result_field_map(layer)
        number_key_name = field_map.get("number_key")
        group_count = 0
        if number_key_name:
            index = layer.fields().indexFromName(number_key_name)
            group_count = len({
                str(value).strip()
                for value in layer.uniqueValues(index)
                if not self._result_value_is_empty(value)
            })
        self.lblPreviousResultStatus.setText(
            self._t(
                f"ArchDistribution 대표 결과 감지 · {group_count:,}개 번호 "
                f"묶음 / {layer.featureCount():,}개 도형 · 중복·대표 판정 유지",
                f"ArchDistribution representative result detected · "
                f"{group_count:,} numbering groups / "
                f"{layer.featureCount():,} features · match decisions kept",
            )
        )

    def _request_renumber(self, layer):
        if not layer or layer.type() != 0:
            QtWidgets.QMessageBox.warning(
                self,
                self._t("선택 오류", "Selection Error"),
                self._t("유적 레이어를 선택(활성화)한 후 실행해주세요.", "Select/activate a heritage layer first."),
            )
            return

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

        result_kind = self._classify_result_layer(layer)["kind"]
        if result_kind in {"suppressed", "protection", "mixed", "audit"}:
            messages = {
                "suppressed": self._t(
                    "이 레이어는 대표 번호에서 제외된 형상을 보존하는 "
                    "중복_보존 검수 레이어입니다. 번호를 부여하면 같은 유적의 "
                    "라벨이 중복될 수 있어 실행하지 않습니다.",
                    "This is an audit layer that preserves geometry suppressed "
                    "from representative numbering. Renumbering it could create "
                    "duplicate labels, so the operation was blocked.",
                ),
                "protection": self._t(
                    "지정유산 보호구역은 경계 전용 무번호 레이어이므로 번호를 "
                    "부여하지 않습니다.",
                    "Heritage protection zones are boundary-only, unnumbered "
                    "layers and cannot be renumbered.",
                ),
                "mixed": self._t(
                    "대표 형상과 중복 보존 형상이 섞인 레이어입니다. 중복 "
                    "라벨을 막기 위해 재번호하지 않습니다. 대표 결과 레이어만 "
                    "선택해 주세요.",
                    "This layer mixes representative and suppressed geometry. "
                    "Choose the representative result layer only.",
                ),
                "audit": self._t(
                    "중복 판정 검수표는 번호를 매기는 지도 레이어가 아닙니다.",
                    "The duplicate audit table is not a map layer to renumber.",
                ),
            }
            QtWidgets.QMessageBox.warning(
                self,
                self._t("재번호 불가", "Cannot Renumber"),
                messages[result_kind],
            )
            return

        self.renumber_requested.emit(layer)

    def renumber_current_layer(self):
        """Renumber the currently active layer without re-running matching."""
        layer = iface.activeLayer() if iface else None
        self._request_renumber(layer)

    def renumber_previous_result(self):
        """Renumber the representative result selected in the dedicated card."""
        layer = QgsProject.instance().mapLayer(
            self.comboPreviousResultLayer.currentData()
        )
        self._request_renumber(layer)

    def _confirm_previous_result_reprocessing(self, layers):
        """Warn before treating a representative result as original input."""
        names = ", ".join(layer.name() for layer in layers[:3])
        if len(layers) > 3:
            names += self._t(
                f" 외 {len(layers) - 3}개",
                f" and {len(layers) - 3} more",
            )

        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle(
            self._t(
                "이전 결과 재입력 확인",
                "Confirm Result Reprocessing",
            )
        )
        box.setText(
            self._t(
                "<b>이전 대표 결과를 원본 자료처럼 다시 분석하려고 합니다.</b>",
                "<b>An existing representative result is about to be "
                "reprocessed as source data.</b>",
            )
        )
        box.setInformativeText(
            self._t(
                f"선택 레이어: {names}\n\n"
                "이 경로는 숨겨진 중복_보존 자료와 원래 후보 관계를 복원하지 "
                "못합니다. 번호 순서만 바꾸려면 '번호만 다시 매기기로 이동'을 "
                "선택하세요. 중복·대표 결정을 바꾸려면 취소한 뒤 원본 "
                "레이어들을 선택하세요. 새 도곽으로 결과를 의도적으로 "
                "재처리할 때만 계속 진행하세요.",
                f"Selected layers: {names}\n\n"
                "This path cannot restore suppressed sources or original "
                "candidate relations. Choose 'Go to renumber only' to change "
                "number order. To change duplicate or representative "
                "decisions, cancel and select the original layers. Continue "
                "only when intentionally reprocessing a result for a new "
                "extent.",
            )
        )
        renumber_button = box.addButton(
            self._t(
                "번호만 다시 매기기로 이동",
                "Go to renumber only",
            ),
            QtWidgets.QMessageBox.ActionRole,
        )
        continue_button = box.addButton(
            self._t("그래도 재처리", "Reprocess anyway"),
            QtWidgets.QMessageBox.DestructiveRole,
        )
        cancel_button = box.addButton(QtWidgets.QMessageBox.Cancel)
        cancel_button.setText(self._t("취소", "Cancel"))
        box.setDefaultButton(cancel_button)
        exec_fn = getattr(box, "exec", None) or getattr(box, "exec_", None)
        if exec_fn:
            exec_fn()

        clicked = box.clickedButton()
        if clicked is renumber_button:
            if hasattr(self, "tabWidget"):
                self.tabWidget.setCurrentIndex(1)
            if layers:
                index = self.comboPreviousResultLayer.findData(
                    layers[0].id()
                )
                if index >= 0:
                    self.comboPreviousResultLayer.setCurrentIndex(index)
            self.btnRenumberPreviousResult.setFocus()
            return False
        if clicked is continue_button:
            self.log(
                self._t(
                    "⚠ 이전 대표 결과를 원본 입력으로 강제 재처리합니다.",
                    "⚠ Reprocessing an existing representative result as "
                    "source data by explicit user choice.",
                )
            )
            return True
        return False

    def populate_layers(self):
        self.comboStudyArea.clear()
        self.listTopoLayers.clear()
        self.listHeritageLayers.clear()

        layers = list(QgsProject.instance().mapLayers().values())
        for layer in layers:
            if layer.type() == 0:  # VectorLayer
                # A CP949 DBF must be reloaded before field inspection and
                # combo/list labels are constructed.  Waiting until the Run
                # button is pressed leaves already-decoded mojibake in the
                # field selector, which makes automatic zone detection fail.
                self._apply_automatic_shapefile_encoding(layer)
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

                # Keep confidently detected preservation datasets out of the
                # legacy heritage list. They remain available in the dedicated
                # polygon selector, preventing accidental workflow mixing.
                if not self._detect_preservation_field(layer):
                    item_heritage = QListWidgetItem(layer.name())
                    item_heritage.setData(QtCore.Qt.UserRole, layer.id())
                    is_previous_result = (
                        self._is_previous_distribution_result(layer)
                    )
                    item_heritage.setData(
                        QtCore.Qt.UserRole + 1,
                        is_previous_result,
                    )
                    if is_previous_result:
                        item_heritage.setText(
                            self._t(
                                f"{layer.name()}  [이전 대표 결과]",
                                f"{layer.name()}  [existing representative result]",
                            )
                        )
                        item_heritage.setToolTip(
                            self._t(
                                "번호 정리만 필요하면 원본 입력으로 체크하지 말고 "
                                "스타일 탭의 '기존 결과 후속 작업'을 사용하세요.",
                                "For number cleanup only, do not select this as "
                                "source data; use Existing Result Follow-up on "
                                "the Style tab.",
                            )
                        )
                    item_heritage.setFlags(
                        item_heritage.flags()
                        | QtCore.Qt.ItemIsUserCheckable
                    )
                    item_heritage.setCheckState(QtCore.Qt.Unchecked)
                    self.listHeritageLayers.addItem(item_heritage)
        self._auto_assign_legal_layers(layers)
        self._populate_previous_result_layers()
        self._populate_layer_role_table()
        self._update_previous_result_guidance()

    def _auto_assign_legal_layers(self, layers):
        """Preselect the four NHA legal layers by their source-layer names.

        The controls remain editable, but a project already containing the
        standard Korean layer names should not require the user to rediscover
        and select each layer on every run.  Memory outputs are deliberately
        excluded so a prior result can never become the next input.
        """
        targets = (
            ("zone", self.comboZoneLayer),
            ("national_protection", self.comboNationalProtectionLayer),
            ("local_protection", self.comboLocalProtectionLayer),
            ("national_designated", self.comboNationalDesignatedLayer),
            ("local_designated", self.comboLocalDesignatedLayer),
        )
        empty_targets = {
            key: combo for key, combo in targets
            if combo.currentLayer() is None
        }
        if not empty_targets:
            return
        for layer in layers:
            if (
                not layer
                or layer.type() != 0
                or layer.geometryType() != 2
                or str(layer.providerType() or "").casefold() == "memory"
            ):
                continue
            name = str(layer.name() or "").replace(" ", "")
            if "현상변경" in name and "허용" in name:
                key = "zone"
            elif "보호구역" in name and "국가" in name:
                key = "national_protection"
            elif "보호구역" in name and ("시도" in name or "도지정" in name):
                key = "local_protection"
            elif "국가" in name and "지정" in name:
                key = "national_designated"
            elif ("시도" in name or "도지정" in name) and "지정" in name:
                key = "local_designated"
            else:
                continue
            combo = empty_targets.get(key)
            if combo is not None:
                combo.setLayer(layer)
                empty_targets.pop(key, None)

    @staticmethod
    def _apply_automatic_shapefile_encoding(layer):
        """Reload a CP949 shapefile before any UI reads its attributes.

        This changes QGIS's provider interpretation only; it never rewrites
        the user's SHP/DBF files.  A saved per-layer choice remains stronger
        than automatic detection.
        """
        if not layer or layer.type() != 0:
            return None
        override = str(
            layer.customProperty("ArchDistribution/encoding_override", "")
            or ""
        ).strip()
        selected = override
        if not selected:
            source = str(layer.source() or "").split("|", 1)[0]
            if source.casefold().startswith("file://"):
                source = source[7:]
            selected, _basis = declared_shapefile_encoding(Path(source))
        if not selected:
            return None
        try:
            provider = layer.dataProvider()
            # Set both layer and provider encodings before reload.  Calling
            # only one API can leave old DBF strings cached in QGIS.
            layer.setProviderEncoding(selected)
            provider.setEncoding(selected)
            provider.reloadData()
            layer.updateFields()
            layer.triggerRepaint()
            return selected
        except (AttributeError, RuntimeError):
            return None

    def _populate_layer_role_table(self):
        """Populate editable role overrides for heritage-capable layers."""
        if not hasattr(self, "tableLayerRoles"):
            return
        self.tableLayerRoles.setRowCount(0)
        self.layerRoleCombos = {}
        self.layerEncodingCombos = {}

        heritage_ids = {
            self.listHeritageLayers.item(index).data(QtCore.Qt.UserRole)
            for index in range(self.listHeritageLayers.count())
        }
        for layer_id in sorted(
            heritage_ids,
            key=lambda value: (
                QgsProject.instance().mapLayer(value).name()
                if QgsProject.instance().mapLayer(value)
                else ""
            ),
        ):
            layer = QgsProject.instance().mapLayer(layer_id)
            if not layer:
                continue
            row = self.tableLayerRoles.rowCount()
            self.tableLayerRoles.insertRow(row)
            name_item = QtWidgets.QTableWidgetItem(layer.name())
            name_item.setData(QtCore.Qt.UserRole, layer_id)
            name_item.setFlags(
                name_item.flags() & ~QtCore.Qt.ItemIsEditable
            )
            self.tableLayerRoles.setItem(row, 0, name_item)

            detected = detect_source_role(
                layer.name(),
                [field.name() for field in layer.fields()],
            )
            combo = QtWidgets.QComboBox()
            for role in SOURCE_ROLE_ORDER:
                combo.addItem(source_role_label(role, self.ui_lang), role)
            combo.setCurrentIndex(max(0, combo.findData(detected)))
            combo.setToolTip(
                self._t(
                    f"자동 판정: {SOURCE_ROLE_LABELS[detected]}",
                    f"Detected: {source_role_label(detected, 'en')}",
                )
            )
            self.tableLayerRoles.setCellWidget(row, 1, combo)
            self.layerRoleCombos[layer_id] = combo

            encoding_combo = QtWidgets.QComboBox()
            encoding_combo.addItem(
                self._t("자동(.cpg/공급자)", "Automatic (.cpg/provider)"),
                "",
            )
            encoding_combo.addItem("UTF-8", "UTF-8")
            encoding_combo.addItem("CP949 (EUC-KR)", "CP949")
            saved_encoding = str(
                layer.customProperty(
                    "ArchDistribution/encoding_override", ""
                ) or ""
            ).strip()
            encoding_combo.setCurrentIndex(
                max(0, encoding_combo.findData(saved_encoding))
            )

            def save_encoding(_index, target_layer=layer, widget=encoding_combo):
                selected = str(widget.currentData() or "").strip()
                if selected:
                    target_layer.setCustomProperty(
                        "ArchDistribution/encoding_override", selected
                    )
                else:
                    target_layer.removeCustomProperty(
                        "ArchDistribution/encoding_override"
                    )

            encoding_combo.currentIndexChanged.connect(save_encoding)
            encoding_combo.setToolTip(self._t(
                "글자가 깨질 때만 이 레이어의 UTF-8 또는 CP949를 "
                "직접 선택하세요. 자동은 .cpg와 공급자 설정을 따릅니다.",
                "Choose UTF-8 or CP949 for this layer only when text is "
                "misread. Automatic follows .cpg and provider settings.",
            ))
            self.tableLayerRoles.setCellWidget(row, 2, encoding_combo)
            self.layerEncodingCombos[layer_id] = encoding_combo

    def get_settings(self):
        """Returns the current settings from the dialog."""
        self._save_preservation_style_preferences()
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

        workflow_mode = (
            "preservation"
            if hasattr(self, "workflowTabs")
            and self.workflowTabs.currentIndex() == 1
            else "distribution"
        )
        preservation_layer = (
            self.comboPreservationLayer.currentLayer()
            if hasattr(self, "comboPreservationLayer")
            else None
        )
        preservation_study_area = (
            self.comboPreservationStudyArea.currentLayer()
            if hasattr(self, "comboPreservationStudyArea")
            else None
        )
        source_roles = {
            layer_id: (
                self.layerRoleCombos[layer_id].currentData()
                if layer_id in self.layerRoleCombos
                else None
            )
            for layer_id in heritage_layer_ids
        }
        legal_layer_roles = {}
        legal_inputs = (
            ("national_designated_layer_id",
             getattr(self, "comboNationalDesignatedLayer", None),
             ROLE_NATIONAL_DESIGNATED, None),
            ("national_protection_layer_id",
             getattr(self, "comboNationalProtectionLayer", None),
             ROLE_PROTECTION_ZONE, "national"),
            ("local_designated_layer_id",
             getattr(self, "comboLocalDesignatedLayer", None),
             ROLE_LOCAL_DESIGNATED, None),
            ("local_protection_layer_id",
             getattr(self, "comboLocalProtectionLayer", None),
             ROLE_PROTECTION_ZONE, "local"),
        )
        legal_layer_ids = {}
        protection_families = {}
        for setting_key, combo, role, protection_family in legal_inputs:
            layer = combo.currentLayer() if combo else None
            layer_id = layer.id() if layer else None
            legal_layer_ids[setting_key] = layer_id
            if layer_id:
                legal_layer_roles[layer_id] = role
                if layer_id not in heritage_layer_ids:
                    heritage_layer_ids.append(layer_id)
                # Dedicated legal inputs must win over a generic layer-role
                # guess from the nearby-heritage table.
                source_roles[layer_id] = role
                if protection_family:
                    protection_families[layer_id] = protection_family

        return {
            "workflow_mode": workflow_mode,
            # None means MetricContext chooses a safe projected-metre CRS:
            # retain a metric source, otherwise derive local UTM at the study
            # centroid.  This one global setting applies to both workflows.
            "analysis_crs_authid": self._analysis_crs_override_definition(),
            "topo_layer_ids": topo_layer_ids,
            "heritage_layer_ids": heritage_layer_ids,
            "source_roles": source_roles,
            "legal_layer_roles": legal_layer_roles,
            "protection_families": protection_families,
            **legal_layer_ids,
            "source_encodings": {
                layer_id: str(
                    self.layerEncodingCombos[layer_id].currentData() or ""
                )
                for layer_id in heritage_layer_ids
                if layer_id in self.layerEncodingCombos
            },
            "match_preset": (
                self.comboMatchPreset.currentData()
                if hasattr(self, "comboMatchPreset")
                else PRESET_BALANCED
            ),
            "reuse_review_decisions": (
                self.chkReuseReviewDecisions.isChecked()
                if hasattr(self, "chkReuseReviewDecisions")
                else True
            ),
            "output_directory": (
                self.lineOutputDirectory.text().strip()
                if hasattr(self, "lineOutputDirectory")
                else ""
            ),
            "save_gpkg_manifest": (
                self.chkSaveGpkgManifest.isChecked()
                if hasattr(self, "chkSaveGpkgManifest")
                else False
            ),
            "export_layout_jpg": (
                self.chkExportLayoutJpg.isChecked()
                if hasattr(self, "chkExportLayoutJpg")
                else False
            ),
            "export_layout_pdf": (
                self.chkExportLayoutPdf.isChecked()
                if hasattr(self, "chkExportLayoutPdf")
                else False
            ),
            "study_area_id": self.comboStudyArea.currentData(),
            "buffers": buffers,
            "buffer_style": {
                "color": self.buffer_color.name(),
                "style": self.comboBufferStyle.currentIndex(),  # 0: Solid, 1: Dot, 2: Dash
                "width": self.spinBufferWidth.value(),
                "format_km_labels": self.chkBufferKmLabels.isChecked(),
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
            "exclude_extent_slivers": (
                self.chkExcludeExtentSlivers.isChecked()
                if hasattr(self, "chkExcludeExtentSlivers")
                else True
            ),
            # [NEW] Zone Layer ID
            "zone_layer_id": self.comboZoneLayer.currentLayer().id() if self.comboZoneLayer.currentLayer() else None,
            "zone_field_name": (
                self.comboZoneField.currentData()
                if hasattr(self, "comboZoneField")
                else None
            ),
            "clip_zone_to_buffer": self.chkClipZoneToBuffer.isChecked() if hasattr(self, "chkClipZoneToBuffer") else False,
            # [NEW] Label Style
            "label_font_size": self.spinLabelFontSize.value(),
            "label_font_family": self.comboLabelFont.currentFont().family(),
            "preservation_layer_id": (
                preservation_layer.id() if preservation_layer else None
            ),
            "preservation_encoding": str(
                self.comboPreservationEncoding.currentData() or ""
            ),
            "preservation_study_area_id": (
                preservation_study_area.id()
                if preservation_study_area
                else None
            ),
            "preservation_paper_width": (
                self.spinPreservationPaperWidth.value()
                if hasattr(self, "spinPreservationPaperWidth")
                else DEFAULT_SPIN_VALUES["paper_width"]
            ),
            "preservation_paper_height": (
                self.spinPreservationPaperHeight.value()
                if hasattr(self, "spinPreservationPaperHeight")
                else DEFAULT_SPIN_VALUES["paper_height"]
            ),
            "preservation_scale": (
                self.spinPreservationScale.value()
                if hasattr(self, "spinPreservationScale")
                else DEFAULT_SPIN_VALUES["scale"]
            ),
            "preservation_exclude_extent_slivers": (
                self.chkPreservationExcludeExtentSlivers.isChecked()
                if hasattr(
                    self,
                    "chkPreservationExcludeExtentSlivers",
                )
                else True
            ),
            "preservation_action_field": (
                self.comboPreservationActionField.currentData()
                if hasattr(self, "comboPreservationActionField")
                else None
            ),
            "preservation_action_styles": {
                action: {
                    key: color.name()
                    for key, color in colors.items()
                }
                for action, colors in self.preservation_action_colors.items()
            },
            "preservation_stroke_width": (
                self.spinPreservationStrokeWidth.value()
                if hasattr(self, "spinPreservationStrokeWidth")
                else DEFAULT_SPIN_VALUES["heritage_stroke_width"]
            ),
            "preservation_opacity": (
                self.spinPreservationOpacity.value() / 100.0
                if hasattr(self, "spinPreservationOpacity")
                else 1.0
            ),
            "preservation_sort_order": (
                self.comboPreservationSortOrder.currentIndex()
                if hasattr(self, "comboPreservationSortOrder")
                else 0
            ),
            "preservation_label_font_size": (
                self.spinPreservationLabelFontSize.value()
                if hasattr(self, "spinPreservationLabelFontSize")
                else DEFAULT_SPIN_VALUES["label_font_size"]
            ),
            "preservation_label_font_family": (
                self.comboPreservationLabelFont.currentFont().family()
                if hasattr(self, "comboPreservationLabelFont")
                else DEFAULT_LABEL_FONT_FAMILY[self.ui_lang]
            ),
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
        found_exclusions = set()  # Store unique names to exclude

        total_feats = 0
        matched_feats = 0

        for lid in heritage_layer_ids:
            layer = QgsProject.instance().mapLayer(lid)
            if not layer:
                continue

            self.log(self._t(f"레이어 스캔 중: {layer.name()}", f"Scanning layer: {layer.name()}"))

            # Detect damage but never mutate the provider implicitly.  The
            # per-layer selector above gives the operator an auditable choice.
            fields = [f.name() for f in layer.fields()]
            needs_encoding_fix = any('\ufffd' in f for f in fields)

            if needs_encoding_fix:
                self.log(self._t(
                    "  ⚠️ 인코딩 깨짐이 감지되었습니다. 자료 역할 표의 "
                    "문자 인코딩에서 이 레이어만 UTF-8 또는 CP949로 "
                    "지정한 뒤 다시 스캔하세요.",
                    "  ⚠️ Text decoding damage was detected. Choose UTF-8 "
                    "or CP949 for this layer in the source-role table, then "
                    "scan again.",
                ))
            self.log(self._t(
                f"  - 필드 목록: {', '.join(fields)}",
                f"  - Fields: {', '.join(fields)}",
            ))

            name_field = None
            keywords = ['유적명', '명칭', '명', '이름', 'NAME', 'SITE', 'TITLE']

            for f in fields:
                for k in keywords:
                    if k in f.upper():
                        name_field = f
                        break
                if name_field:
                    break

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
                    continue  # Do not classify this item yet

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
                item.setData(QtCore.Qt.UserRole, exc)  # Store exact name to exclude
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Checked)  # Default to Checked (Exclude)
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

    def _matching_rules_help_html(self):
        """Return a plain-language explanation of the implemented policy."""
        style = """
<style>
body { font-family: sans-serif; color: #24313a; }
.lead { background:#eef7ff; border:1px solid #9ec9e8; padding:10px; }
.warning { background:#fff4d6; border:1px solid #e0ad42; padding:10px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 16px 0; }
th { background:#edf1f4; text-align:left; }
th, td { border:1px solid #b8c1c8; padding:7px; vertical-align:top; }
code { color:#7b2d2d; }
</style>
"""
        if self.ui_lang == "en":
            return style + """
<h2>Duplicate and Representative Numbering Rules</h2>
<div class="lead">
<b>Overlap alone never merges records.</b> ArchDistribution combines source
roles with names, overlap, addresses, and distance to create candidates.
Representative merging does not delete legal status, survey history, source
geometry, or source attributes. Overlap means intersection area divided by
the smaller polygon's area. Confidence describes rule strength, not legal
certainty or source accuracy.
</div>

<h3>What each decision means</h3>
<table>
<tr><th>Decision</th><th>Map result</th><th>Preservation</th></tr>
<tr><td><b>Keep separate</b></td><td>Both records keep separate numbers.</td>
<td>The candidate evidence remains in the audit table.</td></tr>
<tr><td><b>Link only</b></td><td>Both records keep separate numbers, but their
relationship is recorded.</td><td><code>RELATION_KEY</code> and
<code>LINKED_IDS</code> retain the link.</td></tr>
<tr><td><b>Merge numbering identity</b></td><td>One number and one
representative map label.</td><td>Suppressed geometry and attributes remain
under <code>06_중복_검수</code> and in <code>SRC_JSON</code>.</td></tr>
</table>

<h3>Balanced-mode relation rules</h3>
<table>
<tr><th>Relation</th><th>Main candidate conditions</th>
<th>Initial choice</th><th>Number / representative result</th></tr>
<tr><td>Designated/registered ↔ Distribution map</td>
<td>Exact normalized name + actual area overlap is high confidence. Exact name
within 50 m; similarity ≥0.90 or name containment + ≥25% overlap; or ≥80%
overlap + same address are review candidates.</td>
<td>High confidence: <b>Merge</b>. Other candidates start as
<b>Keep separate</b>.</td>
<td>When merged, designated/registered heritage represents one number and
label. The distribution source remains in the audit output.</td></tr>
<tr><td>Excavation ↔ Distribution map</td>
<td>The same name/space/address rules apply. A related excavation project name
+ ≥25% overlap is also a review candidate.</td>
<td>Exact site name + actual overlap: <b>Merge</b>. Project-name/fuzzy
candidates start as <b>Keep separate</b>.</td>
<td>When merged, excavation represents the group; the distribution source is
preserved.</td></tr>
<tr><td>Designated/registered ↔ Excavation</td>
<td>Name, space, address, or distance evidence suggests the same place.</td>
<td>Exact name + overlap: <b>Link only</b>. Other candidates start separate.</td>
<td>Each keeps its own number; the relation is recorded.</td></tr>
<tr><td>Surface survey ↔ Any source</td>
<td>Only when the normal name/space/address/distance rules create a candidate.</td>
<td>Always <b>Keep separate</b>; never automatically merged by a preset.</td>
<td>Survey history remains independently numbered unless the user explicitly
changes the choice.</td></tr>
<tr><td>Heritage protection zone</td>
<td>Excluded from ordinary duplicate comparison.</td><td>Not applicable.</td>
<td>Boundary only; no number.</td></tr>
<tr><td>Split areas of the same excavation project</td>
<td>Non-empty project names are exactly equal after normalization.</td>
<td>Always one numbering group.</td>
<td>One <code>NUMBER_KEY</code>. Different project names remain separate
survey events and numbers.</td></tr>
</table>

<h3>Matching presets</h3>
<ul>
<li><b>Balanced:</b> only the strongest exact-name + actual-overlap relation
starts as merge/link. Fuzzy, containment, address, and project-name candidates
start separate.</li>
<li><b>Conservative:</b> every candidate starts separate and needs an explicit
user choice.</li>
<li><b>Automation-first:</b> designated/registered ↔ distribution and
excavation ↔ distribution may start merged at name similarity ≥0.95 and
overlap ≥50%. Containment-only and surface-survey candidates are excluded.</li>
</ul>

<div class="warning"><b>Renumbering is not duplicate re-analysis.</b><br>
Use <b>Existing Result Follow-up — Renumber Only</b> to keep
<code>NUMBER_KEY</code> groups and decisions while recalculating number order,
distance, and <code>LABEL_OK</code>. To change a duplicate/representative
decision, re-run the original source layers. Feeding only the representative
result back as source cannot reconstruct suppressed sources or candidate
relations.</div>

<h3>Reading result fields</h3>
<p><code>NUMBER_KEY</code> = one numbering identity · <code>IS_REP=1</code> =
representative geometry · <code>RELATION_KEY/LINKED_IDS</code> = related
records that may retain separate numbers · <code>MATCH_STATUS</code> =
decision outcome · <code>REP_SOURCE</code> = representative source role ·
<code>SRC_JSON</code> = preserved source attributes.</p>
"""

        return style + """
<h2>중복·대표 번호 판정 기준</h2>
<div class="lead">
<b>도형이 겹친다는 이유만으로는 절대 자동 병합하지 않습니다.</b>
ArchDistribution은 자료 역할과 함께 명칭·중첩·주소·거리를 보고 후보를
만듭니다. 대표화하더라도 법적 지위, 조사 이력, 원본 형상과 속성을 삭제하지
않습니다. 중첩률은 ‘교차 면적 ÷ 두 도형 중 작은 도형의 면적’입니다.
신뢰도는 판정 규칙의 강도이며 자료의 정확도나 법적 확실성을 뜻하지 않습니다.
</div>

<h3>검토창의 세 선택</h3>
<table>
<tr><th>선택</th><th>지도 번호·라벨 결과</th><th>자료 보존</th></tr>
<tr><td><b>별도 유지</b></td><td>서로 다른 대상으로 보고 각각 번호를
부여합니다.</td><td>후보였다는 근거는 검수표에 남습니다.</td></tr>
<tr><td><b>연결만</b></td><td>관련 장소·이력으로 연결하되 각각 번호를
유지합니다.</td><td><code>RELATION_KEY</code>와
<code>LINKED_IDS</code>에 관계를 기록합니다.</td></tr>
<tr><td><b>대표 번호로 묶기</b></td><td>번호 하나와 대표 라벨 하나만
사용합니다.</td><td>대표에서 제외된 형상·속성은
<code>06_중복_검수</code>와 <code>SRC_JSON</code>에 남습니다.</td></tr>
</table>

<h3>균형형의 관계별 기준</h3>
<table>
<tr><th>자료 관계</th><th>후보가 되는 주요 조건</th>
<th>검토창 초기 선택</th><th>번호·대표 결과</th></tr>
<tr><td>지정·등록유산 ↔ 문화유적분포지도</td>
<td>정규화 명칭 동일+실제 면적 중첩은 높은 신뢰도입니다. 동일명칭 50m
이내, 명칭 유사도 0.90 이상/포함관계+작은 도형 기준 중첩률 25% 이상,
또는 중첩률 80% 이상+동일 주소는 검토 후보입니다.</td>
<td>높은 신뢰도는 <b>대표 번호로 묶기</b>, 나머지는
<b>별도 유지</b>로 시작합니다.</td>
<td>묶으면 지정·등록유산이 대표가 되고 번호·라벨은 하나입니다. 분포지도
원본은 검수 자료에 보존됩니다.</td></tr>
<tr><td>발굴조사 ↔ 문화유적분포지도</td>
<td>위의 명칭·공간·주소 조건을 적용합니다. 발굴 사업명이 분포지도 명칭과
관련되고 중첩률이 25% 이상인 경우도 검토 후보입니다.</td>
<td>동일 유적명+실제 중첩은 <b>대표 번호로 묶기</b>, 사업명·유사명칭
후보는 <b>별도 유지</b>로 시작합니다.</td>
<td>묶으면 발굴조사가 대표가 되고 분포지도 원본은 보존됩니다.</td></tr>
<tr><td>지정·등록유산 ↔ 발굴조사</td>
<td>명칭·공간·주소·거리 근거로 같은 장소 가능성을 제시합니다.</td>
<td>동일명칭+실제 중첩은 <b>연결만</b>, 그 밖은 별도 유지입니다.</td>
<td>법적 지위와 조사 사건은 각각 번호를 유지하고 관계만 기록합니다.</td></tr>
<tr><td>지표조사 ↔ 모든 자료</td>
<td>일반 명칭·공간·주소·거리 조건을 만족할 때만 후보가 됩니다.</td>
<td>항상 <b>별도 유지</b>. 어떤 프리셋도 자동 병합하지 않습니다.</td>
<td>조사 이력을 독립적으로 보존합니다. 사용자가 검토창에서 명시적으로
선택한 경우에만 연결하거나 묶습니다.</td></tr>
<tr><td>지정유산 보호구역</td><td>일반 중복 후보 비교에서 제외됩니다.</td>
<td>해당 없음</td><td>경계만 유지하고 번호를 부여하지 않습니다.</td></tr>
<tr><td>같은 발굴 사업명의 분할구역</td>
<td>비어 있지 않은 사업명이 정규화 후 정확히 같은 경우입니다.</td>
<td>항상 같은 번호 묶음</td>
<td>I지역·II-1·2·3지역처럼 나뉘어도 <code>NUMBER_KEY</code> 하나를
공유합니다. 사업명이 다르면 같은 유적 안에서도 별도 번호입니다.</td></tr>
</table>

<h3>판정 모드</h3>
<ul>
<li><b>균형형:</b> 가장 확실한 동일명칭+실제 중첩 관계만 대표화/연결로
미리 선택합니다. 유사·포함·주소·사업명 후보는 별도 유지로 시작합니다.</li>
<li><b>보수형:</b> 모든 후보를 별도 유지로 시작하며 사용자가 직접
결정합니다.</li>
<li><b>자동화 우선형:</b> 지정·등록↔분포 및 발굴↔분포에 한해 명칭
유사도 0.95 이상+중첩률 50% 이상까지 대표화 초기 선택을 넓힙니다.
단순 포함관계와 지표조사는 제외합니다.</li>
</ul>

<div class="warning"><b>번호 재정렬은 중복 재분석이 아닙니다.</b><br>
<b>[기존 결과 후속 작업 — 번호만 다시 매기기]</b>는
<code>NUMBER_KEY</code>와 판정을 유지하고 번호 순서, 이격거리,
<code>LABEL_OK</code>만 다시 계산합니다. 중복·대표 결정을 바꾸려면 각
출처의 원본 레이어로 다시 분석하세요. 대표 결과만 원본으로 재입력하면
숨겨진 자료와 후보 관계를 복원할 수 없습니다.</div>

<h3>결과 필드 읽는 법</h3>
<p><code>NUMBER_KEY</code>=같은 번호 단위 · <code>IS_REP=1</code>=대표
형상 · <code>RELATION_KEY/LINKED_IDS</code>=번호는 다를 수 있지만 연결된
자료 · <code>MATCH_STATUS</code>=판정 결과 · <code>REP_SOURCE</code>=대표
출처 · <code>SRC_JSON</code>=보존된 전체 원본 속성</p>
"""

    def show_matching_rules_help(self):
        self.show_scrollable_help_dialog(
            self._t(
                "중복·대표 번호 판정 기준",
                "Duplicate and Representative Numbering Rules",
            ),
            self._matching_rules_help_html(),
        )

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
        except (OSError, json.JSONDecodeError, TypeError):
            return defaults[:limit]
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
<li><b>Confirm source roles:</b> Review detected roles and the duplicate-matching preset.</li>
<li><b>Set extent/scale:</b> Input paper size and scale (report/A4 presets available).</li>
<li><b>Smart scan:</b> Click [Run Attribute Scan] to classify era/type candidates.</li>
<li><b>Run:</b> Click [Run Analysis / Generate Map], then review duplicate candidates.</li>
<li><b>Renumber:</b> After edits/deletions, choose the representative result under [Existing Result Follow-up — Renumber Only] on the Style tab.</li>
</ol>
<br>
<b>[View results]</b><br>
When processing completes, map canvas auto-zooms to extent.<br>
The canvas includes viewing padding. Automatic print layouts use the study/extent CRS even when the project CRS differs.<br>
For a manually created print layout, set the map item's CRS to the same CRS as <b>도곽_Extent</b> so paper size, scale, and collection footprint remain identical.<br>
If nothing appears, check visibility of <b>ArchDistribution_결과물</b> and try <b>Zoom to Layer</b>.<br><br>
<b>[Zone option]</b><br>
If a Zone layer is selected, features are automatically split/styled by zone code.<br>
Option <b>Clip to buffer extent</b> keeps only features inside the largest buffer (Extent ∩ Buffer).<br><br>
<b>[Source-aware duplicate review]</b><br>
Balanced mode auto-recommends only exact-name overlaps between designated/registered heritage and distribution maps, or excavation and distribution maps.<br>
Spatial overlap alone never merges records. Designated heritage and excavation remain separately numbered, and surface surveys are kept separate by default.<br>
Suppressed lower-priority geometry is retained under <b>06_중복_검수</b> with a complete audit table and source JSON.<br><br>
<b>[Duplicate re-analysis vs. renumber-only]</b><br>
Renumber-only keeps <code>NUMBER_KEY</code> groups and match/representative decisions, then recalculates number order, distance, and <code>LABEL_OK</code> from the current settings.<br>
To change a duplicate or representative decision, re-run the original source layers. Feeding only a representative result back as source cannot reconstruct suppressed sources or original candidate relations.<br><br>
<b>[Buried heritage preservation areas]</b><br>
Open the dedicated <b>Buried Heritage Preservation Areas</b> workflow tab, select the preservation polygon and study-area baseline, then confirm the paper size, scale, and action field.<br>
The fill/outline colors, width, and opacity for 현상보존, 정밀발굴조사, 시굴조사, and 표본조사 are configurable and saved.<br>
Tiny polygons clipped at the extent use the same scale-aware exclusion rule as the distribution-map workflow.<br>
Action boundaries remain separate, while records with the same project name share one number. All source fields and grouped records are retained; save as GeoPackage to avoid Shapefile truncation.<br><br>
<b>[Numbering tips]</b><br>
<ul>
<li>Buffer-tier numbering is applied only when sort order is distance-based.</li>
<li>If "Exclude outside buffer" is checked, features outside max buffer may stay unnumbered.</li>
</ul>
<br>
<b>[Suggested Exclusions]</b><br>
When an approved user-supplied <code>smart_patterns.json</code> is installed,
exclusion suggestions use its <code>noise</code> keywords; otherwise conservative
built-in examples are shown.<br>
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
<li><b>자료 역할 확인:</b> 자동 판정된 자료 역할과 중복 판정 모드를 확인합니다.</li>
<li><b>도곽/축척 설정:</b> 도면 가로/세로(mm)와 축척을 입력합니다. (프리셋 활용 추천)</li>
<li><b>스마트 분류:</b> [속성 분류 실행] 버튼으로 유적을 시대/유형별로 분류합니다.</li>
<li><b>분석 실행:</b> [▶ 분석 및 지도 생성 실행] 후 중복 후보 처리 방식을 검토합니다.</li>
<li><b>번호만 다시 매기기:</b> 유적 삭제/수정 후 [스타일 탭 > 기존 결과 후속 작업]에서 대표 결과를 골라 번호 재정렬</li>
</ol>
<br>
<b>[결과 확인 (View)]</b><br>
작업이 끝나면 <b>도곽(Extent) 범위로 화면이 자동 확대(여백 포함)</b>되어 결과물을 바로 확인할 수 있습니다.<br>
프로젝트 CRS가 조사구역과 달라도 자동 인쇄조판은 조사구역·도곽 CRS를 사용합니다.<br>
인쇄조판을 직접 만들 때에는 지도 항목 CRS를 <b>도곽_Extent와 같은 CRS</b>로 설정해야 판형·축척·유적 수집 범위가 정확히 일치합니다.<br>
만약 화면이 비어 보이면 레이어 패널에서 <b>ArchDistribution_결과물</b> 그룹의 체크(가시성)를 확인하고,<br>
개별 레이어 우클릭 → <b>레이어로 확대(Zoom to Layer)</b>를 시도해 주세요.
<br><br>
<b>[현상변경허용기준(Zone) 옵션]</b><br>
현상변경허용기준 레이어를 선택하면, 도곽 내에서 자동 분할/스타일링을 수행합니다.<br>
<ul>
<li><b>버퍼 범위 내 자르기</b>: 가장 큰 버퍼(최대 반경) 범위 안에 포함되는 구역만 남깁니다. (도곽 ∩ 버퍼)</li>
</ul>
<br>
<b>[자료 역할 및 중복 검토]</b><br>
기본 균형형은 지정·등록유산과 분포지도, 발굴조사와 분포지도의 명칭이 같고 실제 면적이 겹칠 때만 대표화를 추천합니다.<br>
공간 중첩만으로는 합치지 않으며, 지정유산과 발굴조사는 각각 번호를 유지하고 지표조사는 기본적으로 별도 유지합니다.<br>
대표에서 제외된 자료는 삭제하지 않고 <b>06_중복_검수</b> 그룹의 숨김 레이어와 검수표, <code>SRC_JSON</code>에 보존합니다.<br>
<b>중복 재분석과 번호 재정렬은 다릅니다.</b> 번호만 다시 매기기는 <code>NUMBER_KEY</code>와 중복·대표 판정을 유지하고 현재 설정에 맞춰 번호 순서, 이격거리와 <code>LABEL_OK</code>만 다시 계산합니다.<br>
중복·대표 결정을 바꾸려면 각 출처의 원본 레이어로 다시 분석해야 합니다. 대표 결과만 원본 목록에 재입력하면 숨겨진 자료와 원래 후보 관계를 복원할 수 없습니다.<br>
<br>
<b>[매장유산 유존지역]</b><br>
상단의 <b>매장유산 유존지역</b> 전용 작업 탭에서 유존지역 폴리곤과 도곽 기준 조사구역을 선택하고, 판형·축척 및 자동 추천된 보존조치 필드를 확인하거나 직접 지정합니다.<br>
현상보존·정밀발굴조사·시굴조사·표본조사의 채움색, 외곽선색, 두께, 불투명도를 직접 설정할 수 있으며 다음 실행에도 유지됩니다.<br>
도곽에서 잘린 미세 폴리곤은 문화유적분포지도와 동일한 축척 기반 기준으로 제외합니다.<br>
조치별 경계는 따로 유지하지만 같은 사업명은 번호 하나를 공유합니다. 모든 원본 필드와 그룹 구성원 정보도 보존하며, 필드 잘림 방지를 위해 GeoPackage 저장을 권장합니다.<br>
<br>
<b>[번호 부여 팁]</b><br>
<ul>
<li><b>버퍼 구간별 번호 부여</b>는 정렬 기준이 <b>거리순</b>일 때만 적용됩니다.</li>
<li><b>버퍼 밖 제외</b> 옵션을 켜면, 최대 버퍼 밖 유적은 번호가 비워질 수 있습니다.</li>
</ul>
<br>
<b>[제외 제안 목록 안내]</b><br>
출처·라이선스가 확인된 사용자 공급 <code>smart_patterns.json</code>이 설치된
경우에만 그 파일의 <code>noise</code> 키워드로 제외 제안을 만들며, 없으면
보수적인 내장 예시만 표시합니다.<br>
예: {noise_examples}<br>
이 목록은 자동 확정이 아니라 제안이므로, 현장 판단에 따라 체크를 해제해 포함할 수 있습니다.<br>
최종 결과는 작업 마지막에 [기존 결과 후속 작업 > 번호만 다시 매기기]로 정리하는 것을 권장합니다.
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
<li>자동 생성된 유적 번호나 위치가 의도와 다를 수 있으므로, <b>[기존 결과 후속 작업 > 번호만 다시 매기기]</b>로 최종 확인 후 사용하세요.</li>
<li><b style='color:red'>번호만 다시 매기기는 중복·대표 판정을 유지하지만 현재 설정된 축척·도곽·버퍼·정렬 기준으로 번호를 재할당합니다. 실행 전 설정을 확인하세요.</b></li>
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
