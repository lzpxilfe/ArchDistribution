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

from .attribute_classification import (
    ERA_FIELD_KEYWORDS,
    NAME_FIELD_KEYWORDS,
    TYPE_FIELD_KEYWORDS,
    build_reference_name_index,
    category_values,
    find_semantic_field,
    infer_categories_from_name,
    reference_info_for_name,
)
from .preservation_actions import (
    PRESERVATION_ACTION_FIELD_CANDIDATES,
    PRESERVATION_ACTION_STYLES,
    recognized_preservation_actions,
)
from .map_legend_styles import normalize_change_zone_code
from .local_reference_assets import resolve_local_reference_asset
from .shapefile_encoding import declared_shapefile_encoding
from .source_exclusion import (
    RULE_TOKEN_PREFIX,
    exclusion_reason,
    load_exclusion_rules,
    outcome_field_candidates,
    prepare_layer_plan,
    resolve_enabled_rules,
    rule_definitions,
)
from .heritage_matching import (
    DESIGNATED_PARTS_JOIN,
    DESIGNATED_PARTS_SEPARATE,
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
    "ko": ["위에서 아래로 (북→남)", "조사지역에서 가까운 순 (거리순)", "가나다 순 (유적명)", "북쪽부터 시계방향 (방위각순)"],
    "en": ["Top to bottom (N->S)", "Nearest to study area (distance)", "Alphabetical (site name)", "Clockwise from north (azimuth)"],
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
DESIGNATED_PARTS_PREF_KEY = "ArchDistribution/designated_parts"
INVESTIGATIONS_LAST_PREF_KEY = "ArchDistribution/investigations_last"
OUTPUT_DIRECTORY_PREF_KEY = "ArchDistribution/output_directory"
SAVE_GPKG_PREF_KEY = "ArchDistribution/save_gpkg_manifest"
EXPORT_JPG_PREF_KEY = "ArchDistribution/export_layout_jpg"
EXPORT_PDF_PREF_KEY = "ArchDistribution/export_layout_pdf"
EXPORT_TABLE_PREF_KEY = "ArchDistribution/export_site_table"
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
        self.groupLegalLayers.setCheckable(True)
        self.groupLegalLayers.setChecked(False)
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
        self._legalLayerWidgets = [
            self.lblZoneLayer,
            self.comboZoneLayer,
            self.lblZoneField,
            self.comboZoneField,
            self.lblNationalDesignatedLayer,
            self.comboNationalDesignatedLayer,
            self.lblNationalProtectionLayer,
            self.comboNationalProtectionLayer,
            self.lblLocalDesignatedLayer,
            self.comboLocalDesignatedLayer,
            self.lblLocalProtectionLayer,
            self.comboLocalProtectionLayer,
            self.chkClipZoneToBuffer,
        ]
        self.groupLegalLayers.toggled.connect(
            self._set_legal_layer_controls_visible
        )
        self._set_legal_layer_controls_visible(False)

        if hasattr(self, 'vTab1'):
            self.vTab1.insertWidget(1, self.groupLegalLayers)

        # Insert into the first tab layout (vTab1) before the Spec group (item index 1)
        if hasattr(self, 'vTab1'):
            self.vTab1.insertWidget(2, self.groupSmartFilter)  # Adjusted index

        self._build_duplicate_policy_controls()
        self._build_previous_result_controls()
        self._build_output_artifact_controls()
        self._build_numbering_controls()
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

        self._arrange_sections_by_workflow()

        # [NEW] Global Scroll Implementation
        # User requested: Title bar fixed, but Tabs + Logs + Run Button all scrollable together.
        self.make_global_scrollable()

    def _arrange_sections_by_workflow(self):
        """Order the sections in the order an operator decides them.

        Data tab: inputs, source roles and duplicates, legal layers,
        attribute classification and exclusions, then the print extent with
        its edge-fragment rule.  Style tab: symbols, labels, buffers with the
        outside-buffer rule, numbering, then follow-up renumbering.  Controls
        keep their objects, signals and saved settings; only their place in
        the layout changes (see UPDATE_GUARDRAILS.md, section 7).
        """
        if not (hasattr(self, "vTab1") and hasattr(self, "vTab2")):
            return
        data_sections = [
            getattr(self, name) for name in (
                "groupData", "groupDuplicatePolicy", "groupLegalLayers",
                "groupSmartFilter", "groupSpecs",
            ) if hasattr(self, name)
        ]
        style_sections = [
            getattr(self, name) for name in (
                "groupSym", "groupLabelStyle", "groupBuffer",
                "groupNumbering", "groupPreviousResult",
            ) if hasattr(self, name)
        ]
        loose = [
            getattr(self, name) for name in (
                "chkRestrictToBuffer", "chkExcludeExtentSlivers",
            ) if hasattr(self, name)
        ]
        for widget in data_sections + style_sections + loose:
            self.vTab1.removeWidget(widget)
            self.vTab2.removeWidget(widget)
        for index, widget in enumerate(data_sections):
            self.vTab1.insertWidget(index, widget)
        for index, widget in enumerate(style_sections):
            self.vTab2.insertWidget(index, widget)
        # Each rule sits with the setting it depends on.
        if hasattr(self, "gSpecs") and hasattr(self, "chkExcludeExtentSlivers"):
            self.gSpecs.addWidget(
                self.chkExcludeExtentSlivers,
                self.gSpecs.rowCount(), 0, 1,
                max(1, self.gSpecs.columnCount()),
            )
        if hasattr(self, "gBuffer") and hasattr(self, "chkRestrictToBuffer"):
            self.gBuffer.addWidget(
                self.chkRestrictToBuffer,
                self.gBuffer.rowCount(), 0, 1,
                max(1, self.gBuffer.columnCount()),
            )
        # The follow-up card lists only compatible result layers; the older
        # "renumber the active layer" button duplicated it.
        if hasattr(self, "btnRenumber"):
            self.btnRenumber.setVisible(False)

    def _build_numbering_controls(self):
        """Offer report-style numbering of previous investigations."""
        self.chkInvestigationsLast = QtWidgets.QCheckBox()
        saved = QtCore.QSettings().value(INVESTIGATIONS_LAST_PREF_KEY, False)
        if isinstance(saved, str):
            saved = saved.strip().casefold() in {"1", "true", "yes", "on"}
        self.chkInvestigationsLast.setChecked(bool(saved))
        self.chkInvestigationsLast.toggled.connect(
            lambda checked: QtCore.QSettings().setValue(
                INVESTIGATIONS_LAST_PREF_KEY, checked
            )
        )
        if hasattr(self, "gNum"):
            self.gNum.addWidget(
                self.chkInvestigationsLast,
                self.gNum.rowCount(), 0, 1,
                max(1, self.gNum.columnCount()),
            )

    def _populate_designated_parts_combo(self, selected=None):
        """Fill the designated-part choice in the current language."""
        if selected is None:
            selected = self.comboDesignatedParts.currentData()
        self.comboDesignatedParts.blockSignals(True)
        self.comboDesignatedParts.clear()
        self.comboDesignatedParts.addItem(
            self._t("따로 번호 (연결만)", "Own number (link only)"),
            DESIGNATED_PARTS_SEPARATE,
        )
        self.comboDesignatedParts.addItem(
            self._t("상위 유적 번호에 포함", "Join the site's number"),
            DESIGNATED_PARTS_JOIN,
        )
        self.comboDesignatedParts.setCurrentIndex(
            max(0, self.comboDesignatedParts.findData(selected))
        )
        self.comboDesignatedParts.blockSignals(False)

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

        # Reports differ on whether a designated pavilion or pagoda inside its
        # site gets its own number, so the operator chooses.
        parts_row = QtWidgets.QHBoxLayout()
        self.lblDesignatedParts = QtWidgets.QLabel()
        self.comboDesignatedParts = QtWidgets.QComboBox()
        self.comboDesignatedParts.setStyleSheet(STYLE_FORCE_VISIBLE)
        saved_parts = str(
            QtCore.QSettings().value(
                DESIGNATED_PARTS_PREF_KEY,
                DESIGNATED_PARTS_SEPARATE,
            )
        )
        self._populate_designated_parts_combo(saved_parts)
        self.comboDesignatedParts.currentIndexChanged.connect(
            lambda _index: QtCore.QSettings().setValue(
                DESIGNATED_PARTS_PREF_KEY,
                self.comboDesignatedParts.currentData(),
            )
        )
        parts_row.addWidget(self.lblDesignatedParts)
        parts_row.addWidget(self.comboDesignatedParts)
        parts_row.addStretch(1)
        duplicate_layout.addLayout(parts_row)

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
        self.chkExportSiteTable = QtWidgets.QCheckBox()
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
            (
                self.chkExportSiteTable,
                EXPORT_TABLE_PREF_KEY,
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
            self._t(
                "자동(DBF/.cpg/공급자)",
                "Automatic (DBF/.cpg/provider)",
            ),
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

    def _set_legal_layer_controls_visible(self, enabled):
        """Expand legal inputs only when the operator explicitly enables them."""
        for widget in getattr(self, "_legalLayerWidgets", []):
            widget.setVisible(bool(enabled))
        if hasattr(self, "groupLegalLayers"):
            self.groupLegalLayers.updateGeometry()

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
        if hasattr(self, "chkInvestigationsLast"):
            self.chkInvestigationsLast.setText(self._t(
                "발굴·지표조사 기록은 유적 다음에 이어서 번호 매기기",
                "Number excavation and survey records after the sites",
            ))
            self.chkInvestigationsLast.setToolTip(self._t(
                "지정·등록유산과 분포지도 유적에 먼저 번호를 매기고, 발굴·지표조사 "
                "기록만으로 된 번호는 그 뒤에 같은 정렬 순서로 이어 붙입니다. "
                "보고서에서 '주변 조사 현황'을 유적 뒤에 따로 싣는 방식입니다.",
                "Number designated, registered and distribution-map sites first; "
                "groups made only of excavation or survey records follow in the "
                "same order, as reports list previous investigations after sites.",
            ))
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
            self.lblDesignatedParts.setText(
                self._t(
                    "유적 안의 지정유산(누각·탑 등):",
                    "Designated parts inside a site (pavilion, pagoda):",
                )
            )
            parts_tip = self._t(
                "공산성 안의 광복루처럼 상위 유적 안에 있는 지정·등록유산을 "
                "어떻게 번호 매길지 고릅니다. '따로 번호'는 각각 번호를 주고 "
                "관계만 기록합니다. '상위 유적 번호에 포함'은 상위 유적 번호 "
                "하나로 묶습니다. 어느 쪽이든 지정구역 경계는 지정유산구역 "
                "레이어에 그대로 그려지고, 발굴조사 부분은 항상 따로 번호를 "
                "받습니다.",
                "How a designated or registered part inside its named site "
                "(a pavilion inside a fortress) is numbered. 'Own number' keeps "
                "both numbers and records the relation; 'Join' gives the part "
                "the site's number. The legal boundary is drawn in the "
                "designated-area layer either way, and excavated parts always "
                "keep their own number.",
            )
            self.lblDesignatedParts.setToolTip(parts_tip)
            self.comboDesignatedParts.setToolTip(parts_tip)
            self._populate_designated_parts_combo()
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
            self.chkExportSiteTable.setText(
                self._t(
                    "주변유적 현황표(HWPX·CSV)",
                    "Nearby-site table (HWPX, CSV)",
                )
            )
            self.chkExportSiteTable.setToolTip(
                self._t(
                    "번호·유적명·시대·성격·소재지·이격거리·출전·비고 열의 "
                    "표를 한글(HWPX)과 엑셀용 CSV로 저장합니다. 여러 기록을 "
                    "합친 칸은 규칙으로 요약한 초안이므로 검수가 필요합니다.",
                    "Saves a No./Site/Period/Character/Location/Distance/"
                    "Source/Remarks table as Hangul HWPX and CSV. Cells that "
                    "combine several records are rule-based drafts to review.",
                )
            )
            self.lblOutputArtifactHelp.setText(
                self._t(
                    "기본값은 꺼짐입니다. 선택하면 현재 도곽·용지·축척으로 "
                    "결과를 저장하며 원본 파일은 수정하지 않습니다. 현황표는 "
                    "지도에 번호가 붙은 유적만 담습니다.",
                    "Disabled by default. Selected outputs use the current "
                    "extent, paper size, and scale without modifying sources. "
                    "The table lists only sites numbered on the map.",
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
            self.groupSmartFilter.setTitle(self._t(
                "유적 속성 분류 및 제외",
                "Site Attributes and Exclusions",
            ))
        if hasattr(self, "lSmartDesc"):
            self.lSmartDesc.setWordWrap(True)
            self.lSmartDesc.setText(
                self._t(
                    "체크한 유적 레이어의 시대·성격 필드(없으면 명칭)로 목록을 "
                    "만듭니다. 체크를 해제한 시대·성격과, 아래 목록에서 체크한 "
                    "항목은 번호에서 빠지고 06_중복_검수/제외_기록에 남습니다. "
                    "[규칙] 항목은 무형·동산·유적없음·자연유산처럼 기록 유형 "
                    "전체에 적용됩니다.",
                    "Lists periods and characters from the source fields (names "
                    "as a fallback). Unchecked periods/characters and checked "
                    "rows below are left out of numbering and kept in "
                    "06_중복_검수/제외_기록. [Rule] rows apply to a whole record "
                    "type such as intangible, movable, no remains or natural.",
                )
            )
        if hasattr(self, "btnSmartScan"):
            self.btnSmartScan.setText(self._t("속성 분류 실행", "Run Attribute Scan"))
        if hasattr(self, "lblEra"):
            self.lblEra.setText(self._t("시대", "Era"))
        if hasattr(self, "lblType"):
            self.lblType.setText(self._t("성격", "Type"))
        if hasattr(self, "lblExclusion"):
            self.lblExclusion.setText(self._t(
                "제외 목록 (체크 = 번호에서 제외):",
                "Exclusions (checked = left out of numbering):",
            ))

        if hasattr(self, "groupLegalLayers"):
            self.groupLegalLayers.setTitle(self._t(
                "국가유산청 법정 레이어 사용 (체크 시 펼침)",
                "Use NHA legal layers (check to expand)",
            ))
            self.groupLegalLayers.setToolTip(self._t(
                "현상변경·지정유산·보호구역이 필요한 작업에서만 체크하고, 각 레이어는 사용자가 직접 선택합니다.",
                "Enable only when legal layers are needed; select every input manually.",
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
        generated_ids = set()
        root = QgsProject.instance().layerTreeRoot()
        for group_name in ("ArchDistribution_결과물", "ArchDistribution_작업중"):
            group = root.findGroup(group_name)
            if group is None:
                continue
            for node in group.findLayers():
                node_layer = node.layer()
                if node_layer is not None and not (
                    self._is_previous_distribution_result(node_layer)
                ):
                    generated_ids.add(node.layerId())
        for layer in layers:
            if layer.type() == 0:  # VectorLayer
                # A CP949 DBF must be reloaded before field inspection and
                # combo/list labels are constructed.  Waiting until the Run
                # button is pressed leaves already-decoded mojibake in the
                # field selector, which makes automatic zone detection fail.
                self._apply_automatic_shapefile_encoding(layer)
                # Skip this plugin's own outputs (they live in its result or
                # staging group) and processing intermediates.  A name test
                # alone hid users' own "조사구역"/"발굴조사구역" layers.
                l_name = layer.name()
                if layer.id() in generated_ids or any(
                    keyword in l_name
                    for keyword in ('_Copy', 'Consolidated', 'Dissolved')
                ):
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
        self._select_likely_study_area()
        self._populate_previous_result_layers()
        self._populate_layer_role_table()
        self._update_previous_result_guidance()

    def _select_likely_study_area(self):
        """Preselect a polygon layer whose name says it is the survey area.

        Only a convenience: the operator still confirms the choice.  Without
        a matching name the first polygon layer is preferred over a line
        layer, which can never be a study area.
        """
        keywords = ("조사지역", "조사구역", "조사대상", "사업부지", "사업지구",
                    "study", "survey area", "project area")
        best = None
        for index in range(self.comboStudyArea.count()):
            layer = QgsProject.instance().mapLayer(
                self.comboStudyArea.itemData(index)
            )
            if layer is None or layer.type() != 0 or layer.geometryType() != 2:
                continue
            name = layer.name().casefold()
            if any(keyword in name for keyword in keywords):
                best = index
                break
            if best is None:
                best = index
        if best is not None:
            self.comboStudyArea.setCurrentIndex(best)

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
                self._t(
                    "자동(DBF/.cpg/공급자)",
                    "Automatic (DBF/.cpg/provider)",
                ),
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
                "자동은 DBF 문자 바이트를 우선 확인하고 .cpg와 공급자 "
                "설정을 함께 사용합니다. 직접 선택은 예외 자료에만 "
                "사용하세요.",
                "Automatic checks DBF text bytes first, then .cpg and the "
                "provider setting. Use a manual choice only for exceptional "
                "sources.",
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

        allowed_filter_tags = self.get_checked_items(None)
        available_filter_tags = []
        for widget in (self.listEras, self.listTypes):
            for index in range(widget.count()):
                data = widget.item(index).data(QtCore.Qt.UserRole)
                if (
                    isinstance(data, str)
                    and data.startswith(("ERA:", "TYPE:"))
                ):
                    available_filter_tags.append(data)
        filter_items = (
            {
                "allowed": allowed_filter_tags,
                "available": available_filter_tags,
            }
            if available_filter_tags else None
        )

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
        legal_enabled = (
            self.groupLegalLayers.isChecked()
            if hasattr(self, "groupLegalLayers") else False
        )
        for setting_key, combo, role, protection_family in legal_inputs:
            layer = combo.currentLayer() if combo and legal_enabled else None
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
            "designated_parts": (
                self.comboDesignatedParts.currentData()
                if hasattr(self, "comboDesignatedParts")
                else DESIGNATED_PARTS_SEPARATE
            ),
            "investigations_last": (
                self.chkInvestigationsLast.isChecked()
                if hasattr(self, "chkInvestigationsLast")
                else False
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
            "export_site_table": (
                self.chkExportSiteTable.isChecked()
                if hasattr(self, "chkExportSiteTable")
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
            # Reviewed name exclusions and record-level rule choices share
            # one list; rule rows carry a "RULE:<id>" token.
            "exclusion_list": [
                data for data, checked in self._exclusion_list_entries()
                if checked and not str(data).startswith(RULE_TOKEN_PREFIX)
            ],
            "exclusion_rules": resolve_enabled_rules({
                str(data)[len(RULE_TOKEN_PREFIX):]: checked
                for data, checked in self._exclusion_list_entries()
                if str(data).startswith(RULE_TOKEN_PREFIX)
            }),
            # [NEW] Restrict Toggle
            "restrict_to_buffer": self.chkRestrictToBuffer.isChecked(),
            "exclude_extent_slivers": (
                self.chkExcludeExtentSlivers.isChecked()
                if hasattr(self, "chkExcludeExtentSlivers")
                else True
            ),
            # [NEW] Zone Layer ID
            "zone_layer_id": (
                self.comboZoneLayer.currentLayer().id()
                if legal_enabled and self.comboZoneLayer.currentLayer()
                else None
            ),
            "zone_field_name": (
                self.comboZoneField.currentData()
                if legal_enabled and hasattr(self, "comboZoneField")
                else None
            ),
            "clip_zone_to_buffer": (
                self.chkClipZoneToBuffer.isChecked()
                if legal_enabled and hasattr(self, "chkClipZoneToBuffer")
                else False
            ),
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
        """Load explicit or verified legacy-local classification assets."""
        plugin_dir = os.path.dirname(__file__)
        json_path, reference_source = resolve_local_reference_asset(
            plugin_dir,
            "reference_data.json",
        )
        if json_path:
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    loaded_reference = json.load(f)
                if not isinstance(loaded_reference, dict):
                    raise TypeError("reference_data.json root must be an object")
                self.reference_data = loaded_reference
                source_label = self._t(
                    "기존 로컬 백업" if reference_source == "legacy_backup" else "사용자 설치 파일",
                    "verified local backup" if reference_source == "legacy_backup" else "user-installed file",
                )
                self.log(self._t(
                    f"참조 데이터 로드 완료: {len(self.reference_data)}개 항목 ({source_label})",
                    f"Reference data loaded: {len(self.reference_data)} entries ({source_label})",
                ))
            except Exception as e:
                self.log(self._t(f"참조 데이터 로드 실패: {str(e)}", f"Failed to load reference data: {str(e)}"))
        else:
            self.log(self._t(
                "로컬 참조 데이터가 없어 원본 레이어의 시대·유형 필드와 명칭만 사용합니다.",
                "No local reference data; using source period/type fields and names only.",
            ))
        self.reference_data_normalized = build_reference_name_index(
            self.reference_data
        )

        # [NEW] Load Smart Patterns
        json_pattern_path, pattern_source = resolve_local_reference_asset(
            plugin_dir,
            "smart_patterns.json",
        )
        self.smart_patterns = {"noise": [], "artifacts": {}}
        if json_pattern_path:
            try:
                with open(json_pattern_path, "r", encoding="utf-8") as f:
                    loaded_patterns = json.load(f)
                if not isinstance(loaded_patterns, dict):
                    raise TypeError("smart_patterns.json root must be an object")
                self.smart_patterns = loaded_patterns
                source_label = self._t(
                    "기존 로컬 백업" if pattern_source == "legacy_backup" else "사용자 설치 파일",
                    "verified local backup" if pattern_source == "legacy_backup" else "user-installed file",
                )
                self.log(self._t(
                    f"스마트 필터 패턴 로드 완료 ({source_label}).",
                    f"Smart-filter patterns loaded ({source_label}).",
                ))
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
        exclusion_lexicon = load_exclusion_rules()
        rule_hits = {}

        total_feats = 0
        matched_feats = 0

        for lid in heritage_layer_ids:
            layer = QgsProject.instance().mapLayer(lid)
            if not layer:
                continue

            self.log(self._t(f"레이어 스캔 중: {layer.name()}", f"Scanning layer: {layer.name()}"))

            # Re-run source-byte detection at action time.  QGIS may have
            # opened a CP949 DBF as UTF-8 before this dialog existed, and a
            # provider can cache those damaged strings even after the layer
            # first appears in the list.  This reload changes interpretation
            # only and never rewrites the source files.
            detected_encoding = self._apply_automatic_shapefile_encoding(
                layer
            )
            if detected_encoding:
                self.log(self._t(
                    f"  - 속성 분류 전 문자 인코딩 자동 확인: "
                    f"{detected_encoding}",
                    f"  - Encoding verified automatically before scan: "
                    f"{detected_encoding}",
                ))

            # Detect damage but never mutate the provider implicitly.  The
            # automatic source-byte check above has already reloaded any
            # recoverable shapefile before this final validation.
            fields = [f.name() for f in layer.fields()]
            needs_encoding_fix = any('\ufffd' in f for f in fields)

            if needs_encoding_fix:
                self.log(self._t(
                    "  ⚠️ 원본 DBF 자동 재판독 후에도 필드명 손상이 "
                    "남았습니다. 원본 파일의 문자 바이트를 확인하세요.",
                    "  ⚠️ Field-name damage remains after automatic DBF "
                    "re-decoding. Check the source file's text bytes.",
                ))
            self.log(self._t(
                f"  - 필드 목록: {', '.join(fields)}",
                f"  - Fields: {', '.join(fields)}",
            ))

            name_field = find_semantic_field(fields, NAME_FIELD_KEYWORDS)
            era_field = find_semantic_field(fields, ERA_FIELD_KEYWORDS)
            type_field = find_semantic_field(fields, TYPE_FIELD_KEYWORDS)
            string_fields = [
                field.name() for field in layer.fields()
                if field.type() == QtCore.QVariant.String
            ]

            if not any((name_field, era_field, type_field, string_fields)):
                self.log(self._t(
                    "  ⚠️ 명칭·시대·유형 필드를 찾지 못해 건너뜁니다.",
                    "  ⚠️ No name, period, or type field found; skipping layer.",
                ))
                continue

            self.log(self._t(
                "  - 식별 필드: "
                f"명칭={name_field or '-'}, 시대={era_field or '-'}, "
                f"유형={type_field or '-'}",
                "  - Detected fields: "
                f"name={name_field or '-'}, period={era_field or '-'}, "
                f"type={type_field or '-'}",
            ))

            all_rule_ids = [
                rule_id for rule_id, _ko, _en, _default
                in rule_definitions(exclusion_lexicon)
            ]
            distinct_counts = {}
            outcome_limit = int(
                (exclusion_lexicon.get("outcome") or {}).get(
                    "max_distinct_values", 12
                )
            ) + 1
            for candidate_name in outcome_field_candidates(
                fields,
                exclusion_lexicon,
            ):
                distinct_counts[candidate_name] = len(layer.uniqueValues(
                    layer.fields().indexFromName(candidate_name),
                    outcome_limit,
                ))
            # Count every rule, including ones disabled by default, so the
            # operator sees what each rule would remove before running.
            exclusion_plan = prepare_layer_plan(
                fields,
                all_rule_ids,
                distinct_value_counts=distinct_counts,
                rules=exclusion_lexicon,
            )

            layer_feats = 0
            layer_matched = 0
            for feat in layer.getFeatures():
                layer_feats += 1
                total_feats += 1
                name = str(feat[name_field] or "") if name_field else ""
                rule_id = exclusion_reason(exclusion_plan, feat)
                if rule_id:
                    rule_hits[rule_id] = rule_hits.get(rule_id, 0) + 1

                # [NEW] Exclusion Logic with User Review
                # Instead of silently skipping, add to exclusion list
                noise_keywords = self.smart_patterns.get('noise', [])
                is_suspicious = bool(name) and any(
                    token in name for token in noise_keywords
                )

                if is_suspicious:
                    found_exclusions.add(name)
                    continue  # Do not classify this item yet

                matched = False

                # Prefer categories carried by the supplier itself.  This
                # works without the optional external reference assets.
                direct_eras = category_values(
                    feat[era_field] if era_field else None,
                    ignored=("시대미상",),
                )
                direct_types = category_values(
                    feat[type_field] if type_field else None,
                    ignored=("기타", "미분류"),
                )
                if direct_eras:
                    found_eras.update(direct_eras)
                    matched = True
                if direct_types:
                    found_types.update(direct_types)
                    matched = True

                # 1. Reference Data Lookup
                info = reference_info_for_name(
                    self.reference_data,
                    self.reference_data_normalized,
                    name,
                )
                if isinstance(info, dict):
                    matched = True
                    if (
                        not direct_eras
                        and info.get('e')
                        and info.get('e') != "시대미상"
                    ):
                        found_eras.add(info['e'])
                    if (
                        not direct_types
                        and info.get('t')
                        and info.get('t') != "기타"
                    ):
                        found_types.add(info['t'])

                # 2. Keyword Refinement (Overrides/Additions)
                refinements = self.smart_patterns.get('artifacts', {})
                for key, val in refinements.items():
                    if name and key in name:
                        found_types.add(val)
                        matched = True

                # Generic, auditable fallback: only terms visibly present in
                # the source name are used; nothing is guessed from a private
                # or unavailable lookup table.
                searchable_text = " ".join(
                    str(feat[field_name] or "")
                    for field_name in string_fields
                )
                inferred_eras, inferred_types = infer_categories_from_name(
                    searchable_text
                )
                if inferred_eras and not direct_eras:
                    found_eras.update(inferred_eras)
                    matched = True
                if inferred_types and not direct_types:
                    found_types.update(inferred_types)
                    matched = True

                if matched:
                    matched_feats += 1
                    layer_matched += 1

            self.log(self._t(
                f"  - {layer_feats}개 객체 중 {layer_matched}개 분류",
                f"  - {layer_matched} classified out of {layer_feats} features",
            ))

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
            self.listEras.addItem(self._t("(시대 정보 없음)", "(No period data)"))

        # Populate List - Type
        if found_types:
            for t in sorted(list(found_types)):
                item = QListWidgetItem(t)
                item.setData(QtCore.Qt.UserRole, f"TYPE:{t}")
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Checked)
                self.listTypes.addItem(item)
        else:
            self.listTypes.addItem(self._t("(유형 정보 없음)", "(No type data)"))

        # Record-level rules come first: they remove whole classes of
        # non-mappable records (no remains, intangible, movable) and are
        # reviewable here like any suggested name.
        for rule_id, label_ko, label_en, default in rule_definitions(
            exclusion_lexicon
        ):
            count = rule_hits.get(rule_id, 0)
            if not count:
                continue
            item = QListWidgetItem(self._t(
                f"[규칙] {label_ko} ({count:,}건)",
                f"[Rule] {label_en} ({count:,})",
            ))
            item.setData(QtCore.Qt.UserRole, f"{RULE_TOKEN_PREFIX}{rule_id}")
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.Checked if default else QtCore.Qt.Unchecked
            )
            item.setToolTip(self._t(
                "체크하면 해당 규칙에 걸린 기록을 번호에서 제외하고 "
                "06_중복_검수/제외_기록에 보존합니다.",
                "Checked records are left out of numbering and kept in "
                "06_중복_검수/제외_기록.",
            ))
            self.listExclusions.addItem(item)
        if rule_hits:
            self.log(self._t(
                "기록 제외 규칙 후보: " + ", ".join(
                    f"{label_ko} {rule_hits[rule_id]:,}건"
                    for rule_id, label_ko, _en, _d in rule_definitions(
                        exclusion_lexicon
                    )
                    if rule_hits.get(rule_id)
                ),
                "Record exclusion rule candidates: " + ", ".join(
                    f"{label_en} {rule_hits[rule_id]:,}"
                    for rule_id, _ko, label_en, _d in rule_definitions(
                        exclusion_lexicon
                    )
                    if rule_hits.get(rule_id)
                ),
            ))

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
        elif not rule_hits:
            self.listExclusions.addItem(self._t("(제외 대상 없음)", "(No exclusion candidates)"))

    def _exclusion_list_entries(self):
        """Return ``(data, checked)`` for every reviewable exclusion row."""
        entries = []
        for index in range(self.listExclusions.count()):
            item = self.listExclusions.item(index)
            data = item.data(QtCore.Qt.UserRole)
            if not data or not (item.flags() & QtCore.Qt.ItemIsUserCheckable):
                continue
            entries.append((data, item.checkState() == QtCore.Qt.Checked))
        return entries

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
<h2>How duplicates and parts are decided</h2>
<div class="lead">
<b>Overlap alone never merges records.</b> Every nearby pair is judged in
three steps: how the <b>names</b> relate, how the <b>footprints</b> relate,
and which <b>registers</b> the records come from. Nothing is deleted:
records left out of the label stay in <code>06_중복_검수</code> and in
<code>SRC_JSON</code>.
</div>

<h3>Step 1 — name relation (spelling-insensitive)</h3>
<p>Spacing, full-width characters, quotes, bracketed aliases, Roman versus
Arabic numerals and ordinal prefixes ("No. 12") are normalised first.</p>
<p>Each example compares two names: <b>=</b> same site, <b>⊂</b> part of
the site, <b>≠</b> different sites.</p>
<table>
<tr><th width="20%">Relation</th><th width="48%">Example pairs</th><th>Meaning</th></tr>
<tr><td>Equal / alias</td><td>Sungnyemun (Namdaemun) = Sungnyemun<br>Hadrian's Wall = Hadrians Wall</td><td>Same name</td></tr>
<tr><td>Omitted qualifier</td><td>Gyeongju Cheomseongdae = Cheomseongdae</td><td>Same place, prefix left out</td></tr>
<tr><td>More specific</td><td>Bulguksa Daeungjeon ⊂ Bulguksa<br>Jisandong tomb 44 ⊂ Jisandong tombs</td><td>A part of the site</td></tr>
<tr><td>Different numbers</td><td>Jisandong tomb 44 ≠ Jisandong tomb 45<br>Site X Area I ≠ Site X Area II</td><td>Siblings, never one site</td></tr>
<tr><td>Sibling</td><td>Bulguksa Dabotap ≠ Bulguksa Seokgatap</td><td>Different parts of one site; each keeps its number</td></tr>
<tr><td>Unrelated</td><td>Cheomseongdae ≠ Gyerim</td><td>Different sites, even when adjacent or on one footprint</td></tr>
</table>

<h3>Step 2 — footprint relation</h3>
<p>Identical (IoU ≥ 0.9) · similar · one inside the other (≥ 90% covered) ·
partial overlap · touching or within 50 m.</p>

<h3>The three choices in the review window</h3>
<table>
<tr><th>Choice</th><th>Map number</th><th>Source records</th></tr>
<tr><td><b>Keep separate</b></td><td>Each keeps its own number</td><td>All kept; no relation recorded</td></tr>
<tr><td><b>Link only</b></td><td>Each keeps its own number</td><td>All kept; recorded as related records</td></tr>
<tr><td><b>Merge numbering identity</b></td><td>One shared <code>NUMBER_KEY</code> and one label</td>
<td>Records left out of the label stay in the audit layer</td></tr>
</table>

<h3>Step 3 — decision (Balanced preset)</h3>
<table>
<tr><th>Situation</th><th>Initial choice</th><th>Map result</th></tr>
<tr><td>Same name inside one register (spacing/alias variants, split pieces)</td>
<td>Merge numbering identity (automatic)</td><td>One number; every piece stays drawn</td></tr>
<tr><td>A part (numbered tomb, building, item) inside its named site</td>
<td>Merge into the site (automatic)</td><td>The site keeps the number; the part is kept in the audit layer.
An excavated part is <b>linked</b> and keeps its number</td></tr>
<tr><td>A designated or registered part inside its site (a pavilion inside a fortress)</td>
<td>Your choice under <b>Designated parts inside a site</b></td><td><b>Own number</b> (default): both numbered, relation kept.
<b>Join the site's number</b>: one number. Its legal boundary stays in the designated-area layer either way</td></tr>
<tr><td>Differently named records drawn on one footprint</td><td>Review (link only)</td>
<td>Separate numbers; the shared footprint is recorded</td></tr>
<tr><td>Designated/registered or excavation ↔ distribution map, same name
(incl. aliases, omitted prefix) and overlapping</td><td>Merge (automatic)</td>
<td>Designated/excavation record represents the number</td></tr>
<tr><td>Designated/registered ↔ distribution map, same name (or prefix omitted),
not overlapping but within 50 m</td><td>Merge (automatic)</td>
<td>The same heritage drawn a few metres apart in two registers; the designated record represents it</td></tr>
<tr><td>Designated ↔ excavation</td><td>Link</td><td>Both numbered, relation kept</td></tr>
<tr><td>Surface survey revising a mapped site (same name, redrawn or extended)</td>
<td>Review (merge recommended)</td><td>One number; both outlines kept</td></tr>
<tr><td>Survey zone inside a site ("sampling area", "Area 1")</td>
<td>Review (merge recommended)</td><td>Joins the site number</td></tr>
<tr><td>Numbered siblings, or overlap with unrelated names</td><td>Not a candidate</td><td>Separate numbers</td></tr>
<tr><td>Same excavation project name</td><td>Always one number</td><td>Shared <code>NUMBER_KEY</code></td></tr>
<tr><td>Same surface-survey project name</td><td>Not merged</td><td>Each survey site keeps its own number; the project is kept as <code>INVESTIGATION_KEY</code></td></tr>
<tr><td>Protection zone</td><td>Not compared</td><td>Boundary only</td></tr>
</table>
<ul>
<li><b>Conservative:</b> nothing starts merged.</li>
<li><b>Automation-first:</b> also pre-selects close fuzzy names with ≥ 50% overlap; surveys are never automatic.</li>
<li>Village-level address equality is not identity evidence; a lot number is required.</li>
</ul>

<h3>Record exclusion rules</h3>
<p>After [Run Attribute Scan] the exclusion list shows <b>[Rule]</b> rows with
counts. Defaults follow published reports: intangible and location-less
movable heritage are excluded; "no remains" investigations and natural
heritage are kept unless you tick them. Excluded records are kept in
<code>06_중복_검수/제외_기록</code> with the rule that removed them, and so
are records you leave out by unticking a period/type or ticking a name.</p>

<div class="warning"><b>Renumbering is not duplicate re-analysis.</b>
Renumber-only keeps decisions and recalculates order, distance and label
anchors. To change a decision, re-run the original source layers.</div>

<h3>Other registers and countries</h3>
<p>All vocabulary is data: <code>matching_rules.json</code> (thresholds,
designator units, generic names), <code>exclusion_rules.json</code>
(outcome and class words) and <code>table_lexicon.json</code> (periods,
address levels). Edit these files instead of the code.</p>

<h3>Audit fields</h3>
<p><code>NUMBER_KEY</code> number unit · <code>IS_REP</code> representative ·
<code>RELATION_TYPE</code> same_entity / parent_child / co_located … ·
audit table <code>NAME_REL</code>, <code>GEOM_REL</code>, <code>RULE</code> ·
<code>SRC_JSON</code> preserved source attributes.</p>
"""

        return style + """
<h2>중복·부분 판정 기준</h2>
<div class="lead">
<b>도형이 겹친다는 이유만으로는 절대 합치지 않습니다.</b>
가까이 있는 두 기록마다 <b>① 명칭이 어떤 관계인지</b>, <b>② 범위가 어떤
관계인지</b>, <b>③ 어떤 자료끼리인지</b>를 차례로 봅니다. 대표에서 빠진
기록도 삭제하지 않고 <code>06_중복_검수</code>와 <code>SRC_JSON</code>에
남습니다.
</div>

<h3>① 명칭 관계 (표기 차이는 먼저 정리)</h3>
<p>띄어쓰기, 전각·반각, 따옴표, 괄호 속 한자·별칭, 로마숫자(Ⅰ·Ⅱ)와
아라비아숫자, ‘제12호’의 ‘제’를 먼저 같은 꼴로 맞춥니다.</p>
<p>예는 모두 두 이름을 비교한 것입니다. <b>=</b> 같은 유적, <b>⊂</b> 상위
유적의 일부, <b>≠</b> 다른 유적.</p>
<table>
<tr><th width="19%">관계</th><th width="50%">예(한 쌍씩)</th><th>뜻</th></tr>
<tr><td>같음·별칭</td><td>경주 첨성대 = 경주첨성대<br>서울 숭례문(崇禮門) = 서울 숭례문</td><td>같은 이름</td></tr>
<tr><td>앞말 생략</td><td>경주 첨성대 = 첨성대<br>서울 숭례문 = 숭례문</td><td>지역명 등을 뺀 같은 이름</td></tr>
<tr><td>더 구체적(부분)</td><td>경주 불국사 대웅전 ⊂ 경주 불국사<br>고령 지산동 44호분 ⊂ 고령 지산동 고분군</td><td>상위 유적의 일부</td></tr>
<tr><td>번호가 다름</td><td>고령 지산동 44호분 ≠ 고령 지산동 45호분<br>○○ 유적 I지역 ≠ ○○ 유적 II지역</td><td>번호만 다른 별개 유적</td></tr>
<tr><td>형제</td><td>경주 불국사 다보탑 ≠ 경주 불국사 삼층석탑</td><td>같은 유적 안의 서로 다른 부분, 각각 번호</td></tr>
<tr><td>무관</td><td>경주 첨성대 ≠ 경주 계림</td><td>다른 유적. 바로 옆에 있거나 범위가 같아도 각각 번호</td></tr>
</table>

<h3>② 범위 관계</h3>
<p>동일(겹친 면적 비율 IoU 0.9 이상) · 유사 · 한쪽이 다른 쪽 안에 있음(90% 이상)
· 일부 겹침 · 맞닿음 또는 50m 이내.</p>

<h3>검토창의 세 선택</h3>
<table>
<tr><th>선택</th><th>지도 번호</th><th>원본 기록</th></tr>
<tr><td><b>별도 유지</b></td><td>각각 번호</td><td>모두 보존, 관계 기록 없음</td></tr>
<tr><td><b>연결만</b></td><td>각각 번호</td><td>모두 보존, 서로 관련된 기록으로 연결</td></tr>
<tr><td><b>대표 번호로 묶기</b></td><td><code>NUMBER_KEY</code> 하나, 라벨 하나</td>
<td>대표에서 빠진 기록도 검수 레이어에 보존</td></tr>
</table>
<p>아래 표의 ‘묶기’는 <b>대표 번호로 묶기</b>를 줄여 쓴 말입니다.</p>

<h3>③ 판정 (균형형 기준)</h3>
<table>
<tr><th>상황</th><th>검토창 초기 선택</th><th>지도 결과</th></tr>
<tr><td>같은 자료 안의 같은 이름(띄어쓰기·괄호·숫자 표기 차이, 나뉜 조각)</td>
<td>묶기(자동)</td><td>번호 하나, 조각은 모두 그대로 표시</td></tr>
<tr><td>상위 유적 안의 부분(개별 호분·건물·전각·유구)</td>
<td>상위 번호로 묶기(자동)</td><td>상위 유적이 번호를 갖고 부분은 검수 레이어에 보존.
부분이 발굴조사이면 <b>연결만</b> 하고 자기 번호 유지</td></tr>
<tr><td>상위 유적 안의 지정·등록유산(예: 공산성 안의 광복루)</td>
<td><b>유적 안의 지정유산</b> 선택에 따름</td><td><b>따로 번호</b>(기본): 각각 번호, 관계만 기록.
<b>상위 유적 번호에 포함</b>: 번호 하나. 어느 쪽이든 지정구역 경계는 지정유산구역 레이어에 남음</td></tr>
<tr><td>이름이 다른 기록이 같은 범위에 그려진 경우(예: 고분군과 누정)</td><td>검토(연결만)</td><td>각각 번호, 같은 범위라는 관계만 기록</td></tr>
<tr><td>지정·등록유산 또는 발굴조사 ↔ 분포지도, 같은 이름(별칭·앞말 생략 포함)+겹침</td>
<td>묶기(자동)</td><td>지정·발굴 기록이 대표 번호</td></tr>
<tr><td>지정·등록유산 ↔ 분포지도, 같은 이름(앞말 생략 포함), 겹치지 않지만 50m 이내</td>
<td>묶기(자동)</td><td>같은 유산이 두 자료에 몇 m 어긋나게 그려진 경우. 지정 기록이 대표 번호</td></tr>
<tr><td>지정·등록유산 ↔ 발굴조사</td><td>연결만</td><td>각각 번호, 관계만 기록</td></tr>
<tr><td>지표조사가 분포지도 유적을 다시 그은 경우(같은 이름, 범위 수정·확장)</td>
<td>검토(묶기 권장)</td><td>번호 하나, 두 범위 모두 표시</td></tr>
<tr><td>유적 안의 지표조사 구역(표본조사 필요범위, 1지역 등)</td>
<td>검토(묶기 권장)</td><td>상위 유적 번호로 흡수</td></tr>
<tr><td>번호가 다른 형제, 이름이 무관한 단순 중첩</td><td>후보 아님</td><td>각각 번호</td></tr>
<tr><td>같은 발굴 사업명</td><td>항상 같은 번호</td><td><code>NUMBER_KEY</code> 공유</td></tr>
<tr><td>같은 지표조사 사업명</td><td>묶지 않음</td><td>지표조사에서 찾은 유적마다 번호, 사업은 <code>INVESTIGATION_KEY</code>로만 기록</td></tr>
<tr><td>지정유산 보호구역</td><td>비교 제외</td><td>경계만 표시, 번호 없음</td></tr>
</table>
<ul>
<li><b>보수형:</b> 모든 후보를 별도 유지로 시작합니다.</li>
<li><b>자동화 우선형:</b> 유사도 0.95 이상+중첩 50% 이상까지 묶기를 미리 선택합니다. 지표조사는 어느 모드에서도 자동 처리하지 않습니다.</li>
<li>같은 마을 주소만으로는 같은 유적의 근거로 쓰지 않습니다(지번까지 같아야 함).</li>
<li>지역별로 내려받은 자료에서 경계 유적이 두 번 들어와도, 같은 유산코드·명칭·범위면 같은 기록으로 처리합니다.</li>
</ul>

<h3>기록 제외 규칙</h3>
<p>[속성 분류 실행] 뒤 ‘제외 목록’에 <b>[규칙]</b> 항목이 건수와 함께
나옵니다. 기본값은 보고서 관행을 따릅니다. 무형유산과 위치 없는 동산유산은
제외하고, ‘유적없음’ 조사와 노거수 같은 자연유산은 체크하지 않으면
유지합니다(‘유적없음 유적분포가능지’는 항상 유지). 제외된 기록은
<code>06_중복_검수/제외_기록</code>에 이유와 함께 남습니다. 시대·성격 체크를
해제하거나 제외 목록에서 명칭을 체크해 뺀 기록도 같은 곳에 남습니다.</p>

<div class="warning"><b>번호 재정렬은 중복 재분석이 아닙니다.</b>
[번호만 다시 매기기]는 판정을 유지한 채 순서·이격거리·라벨 위치만 다시
계산합니다. 판정을 바꾸려면 원본 레이어로 다시 분석하세요.</div>

<h3>다른 자료·다른 나라에 쓸 때</h3>
<p>판정에 쓰는 어휘는 모두 데이터 파일에 있습니다.
<code>matching_rules.json</code>(기준값, ‘호·지점·지역’ 같은 번호 단위,
일반명), <code>exclusion_rules.json</code>(유적없음·무형·동산·자연 어휘),
<code>table_lexicon.json</code>(시대 순서·별칭, 주소 단위). 코드를 고치지
말고 이 파일을 바꾸면 됩니다.</p>

<h3>결과 필드 읽는 법</h3>
<p><code>NUMBER_KEY</code>=같은 번호 단위 · <code>IS_REP</code>=대표 형상 ·
<code>RELATION_TYPE</code>=same_entity(같은 유적)/parent_child(부분)/co_located(같은 범위) ·
검수표 <code>NAME_REL</code>·<code>GEOM_REL</code>·<code>RULE</code>=판정 근거 ·
<code>SRC_JSON</code>=보존된 전체 원본 속성</p>
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
        data = getattr(self, "smart_patterns", {})
        noise_keywords = data.get("noise", []) if isinstance(data, dict) else []
        if isinstance(noise_keywords, list):
            cleaned = [str(x).strip() for x in noise_keywords if str(x).strip()]
            if cleaned:
                return cleaned[:limit]
        return defaults[:limit]

    def show_help(self):
        """Display User Guide and Export Tips."""
        examples = self._get_noise_keyword_examples()
        noise_examples = ", ".join(f"<code>{kw}</code>" for kw in examples)
        if self.ui_lang == "en":
            help_text = """
<h3>User Guide</h3>
<hr>
<b>[Workflow — follow the screen from top to bottom]</b><br>
<ol>
<li><b>Load layers:</b> study area (polygon), topographic maps and heritage layers.
Regional downloads may be loaded together; a record repeated by two adjacent
downloads is recognised as one record.</li>
<li><b>Data tab ① Input layers:</b> choose the study area, topographic maps and nearby-heritage layers.</li>
<li><b>② Source roles and duplicates:</b> check each layer's role (designated, distribution map,
excavation, surface survey…) and the matching mode. <i>Balanced</i> is the recommended default.</li>
<li><b>③ Legal layers (optional):</b> change-zone, designated areas and protection zones as official legend layers.</li>
<li><b>④ Attribute scan and exclusions:</b> [Run Attribute Scan] lists periods and characters
from the source fields and proposes <b>[Rule]</b> exclusions with counts.</li>
<li><b>⑤ Print extent and scale:</b> paper size, scale, and the map-edge fragment rule.</li>
<li><b>Style tab:</b> symbols, label font, buffers (with "hide outside buffer"), numbering order.</li>
<li><b>Optional outputs:</b> GeoPackage + manifest, print layout JPG/PDF, and the
<b>nearby-site table (HWPX, CSV)</b>.</li>
<li><b>Run</b> and review the duplicate candidates. Filter by relation and use
"apply recommended" for a whole group.</li>
<li><b>Follow-up:</b> after edits, renumber in Style tab › Existing Result Follow-up.</li>
</ol>
<b>[How duplicates are judged]</b><br>
Names are compared after normalising spacing, brackets, Roman numerals and
omitted prefixes. Footprints are compared by containment and overlap. A part
(numbered tomb, building) inside its named site joins the site's number;
numbered siblings (tomb 1 / tomb 2) are never merged; overlap alone never
merges. See <b>Matching rules explained</b> for the full table.<br><br>
<b>[Surface surveys]</b><br>
Surveys redraw, extend or split mapped sites. Such revisions are classified
("survey revision", "survey zone in site") and recommended, but a survey record
is never removed automatically.<br><br>
<b>[Record exclusion rules]</b><br>
Intangible and location-less movable heritage are excluded by default;
"no remains" investigations and natural heritage are kept unless ticked.
Excluded records stay in <b>06_중복_검수/제외_기록</b>.<br><br>
<b>[Nearby-site table]</b><br>
Columns: No., site (designation in brackets), period, character, location,
distance/direction, source, remarks. Periods from several records are ordered
and unbroken runs become ranges (e.g. Three Kingdoms-Joseon); addresses are
merged to the shared regions and lots ("… 12 and 1 other lot"). The HWPX file
opens in Hangul and is a draft to check.<br><br>
<b>[Zone option]</b><br>
A change-zone layer is split and styled by code. "Clip to buffer" keeps only the largest buffer.<br><br>
<b>[Buried heritage preservation areas]</b><br>
Use the dedicated tab; action colours, width and opacity are saved.<br><br>
<b>[Name-based suggestions]</b><br>
With an approved <code>smart_patterns.json</code>, names containing noise words are suggested. Example: {noise_examples}<br><br>
<b>[Other registers and countries]</b><br>
Vocabulary lives in <code>matching_rules.json</code>, <code>exclusion_rules.json</code>
and <code>table_lexicon.json</code>; edit those files, not the code.<br><br>
<b>[Disclaimer]</b><br>
The plugin automates repetitive GIS work; final checking of positions,
attributes, numbers and table cells remains the user's responsibility.<br><br>
<b>[Cache/Reload]</b> If an update is not reflected, re-enable the plugin or restart QGIS.
<div style='color: #7f8c8d; font-size: 11px;'>ArchDistribution v{version}</div>
"""
        else:
            help_text = """
<h3>사용 가이드 및 유의사항</h3>
<hr>
<b>[작업 순서 — 화면 위에서 아래로]</b><br>
<ol>
<li><b>레이어 준비:</b> 조사지역(폴리곤), 수치지형도, 주변유적 레이어를 불러옵니다.
국가유산청 자료를 지역별로 여러 파일 받아 함께 불러와도 됩니다. 경계에 걸쳐 두
파일에 모두 들어 있는 유적은 같은 기록으로 처리합니다.</li>
<li><b>데이터 탭 ① 입력 레이어:</b> 조사지역, 수치지형도, 주변 유적 레이어를 고릅니다.</li>
<li><b>② 자료 역할 및 중복 판정:</b> 레이어마다 자동 판정된 역할(지정유산·분포지도·발굴·지표 등)과
판정 모드를 확인합니다. 처음에는 <b>균형형</b>을 권장합니다.</li>
<li><b>③ 국가유산청 법정 레이어(필요 시):</b> 현상변경·지정구역·보호구역을 공식 범례 레이어로 그립니다.</li>
<li><b>④ 유적 속성 분류·제외:</b> [속성 분류 실행]을 누르면 원본의 시대·성격 값으로 목록을 만들고,
번호에서 뺄 기록 유형을 <b>[규칙]</b> 항목으로 건수와 함께 제안합니다.</li>
<li><b>⑤ 출력 도곽 및 축척:</b> 판형·축척과 도곽 경계 미세 조각 제외를 정합니다.</li>
<li><b>스타일 탭:</b> 심볼, 라벨 글꼴, 버퍼(버퍼 밖 숨김 포함), 번호 부여 순서를 정합니다.</li>
<li><b>선택 저장:</b> GeoPackage+실행정보, 인쇄조판 JPG/PDF, <b>주변유적 현황표(HWPX·CSV)</b>.</li>
<li><b>실행</b> 후 중복 후보 검토창에서 관계별로 걸러 보고, 묶음 단위로 ‘권장 적용’을 쓸 수 있습니다.</li>
<li><b>후속 작업:</b> 결과를 고친 뒤에는 스타일 탭의 [기존 결과 후속 작업]에서 번호만 다시 매깁니다.</li>
</ol>
<b>[중복을 판단하는 방식]</b><br>
이름은 띄어쓰기·괄호 속 별칭·로마숫자·행정구역 생략을 정리한 뒤 비교하고,
범위는 포함·중첩 관계로 비교합니다. 상위 유적 안의 부분(개별 호분·건물·전각)은
상위 유적 번호로 묶고, 번호가 다른 형제(1호·2호, I·II지역)는 묶지 않으며,
겹침만으로는 절대 합치지 않습니다. 자세한 표는 <b>[판정 기준 쉽게 보기]</b>를 보세요.<br><br>
<b>[지표조사 자료]</b><br>
지표조사는 분포지도 유적을 바탕으로 범위를 다시 긋거나 넓히거나 나눕니다.
이런 관계를 ‘지표조사 재조사’, ‘유적 안의 조사구역’으로 분류해 권장안을 보여주지만,
지표조사 기록을 자동으로 빼지는 않습니다.<br><br>
<b>[기록 제외 규칙]</b><br>
무형유산과 위치 없는 동산유산은 기본 제외, ‘유적없음’ 조사와 노거수 같은
자연유산은 체크하지 않으면 유지합니다. 제외된 기록은
<b>06_중복_검수/제외_기록</b>에 이유와 함께 남습니다.<br><br>
<b>[주변유적 현황표]</b><br>
열: 번호 · 유적명(지정종목 괄호) · 시대 · 성격 · 소재지 · 이격거리(방위+거리) · 출전 · 비고.
여러 기록을 합친 칸은 규칙으로 요약합니다. 시대는 순서대로 정리하고 이어지는
시대는 범위로 씁니다(예: 삼국-조선). 소재지는 공통 행정구역과 지번으로
줄입니다(예: ○○리 12 외 1필지 일원). HWPX는 한글에서 열리는 초안이니 반드시 원자료와 대조하세요.<br><br>
<b>[현상변경허용기준(Zone)]</b><br>
코드별로 자동 분할·채색합니다. ‘버퍼 범위 내 자르기’는 가장 큰 버퍼 안만 남깁니다.<br><br>
<b>[매장유산 유존지역]</b><br>
상단의 전용 탭을 쓰세요. 보존조치별 색·두께·불투명도는 다음 실행에도 유지됩니다.<br><br>
<b>[이름 기반 제외 제안]</b><br>
출처가 확인된 <code>smart_patterns.json</code>이 있으면 그 키워드가 든 이름을 제안합니다. 예: {noise_examples}<br><br>
<b>[다른 자료·다른 나라에 쓸 때]</b><br>
판정 어휘는 <code>matching_rules.json</code>, <code>exclusion_rules.json</code>,
<code>table_lexicon.json</code>에 있습니다. 코드를 고치지 말고 이 파일을 바꾸면 됩니다.<br><br>
<b>[일러스트레이터 반출 팁]</b><br>
레이어(지형도·유적·버퍼)를 하나씩 켜서 각각 PDF로 저장한 뒤 합치면 편집이 수월합니다.<br><br>
<b>[유의사항]</b><br>
반복 작업을 자동화하는 도구입니다. 위치·속성·번호·표 내용의 최종 검수는 사용자 몫입니다.
<b style='color:red'>번호만 다시 매기기는 현재 축척·도곽·버퍼·정렬 기준으로 번호를 다시 붙입니다.</b><br><br>
<b>[업데이트/캐시]</b> 갱신이 반영되지 않으면 플러그인을 껐다 켜거나 QGIS를 다시 시작하세요.
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
