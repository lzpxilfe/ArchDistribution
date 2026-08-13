from qgis.PyQt import QtCore
from qgis.PyQt.QtCore import QCoreApplication, QVariant, Qt
from qgis.PyQt.QtGui import QIcon, QColor, QFont
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QProgressDialog
from qgis.core import (QgsProject, QgsVectorLayer, QgsGeometry, QgsFeature,
                       QgsField, QgsPointXY,
                       QgsLineSymbol, QgsSingleSymbolRenderer, QgsFeatureRequest,
                       QgsCategorizedSymbolRenderer, QgsRendererCategory,
                       QgsFillSymbol,
                       QgsPalLayerSettings, QgsTextFormat, QgsVectorLayerSimpleLabeling,
                       QgsCoordinateTransform, QgsWkbTypes, QgsRectangle,
                       QgsSpatialIndex, QgsDistanceArea, QgsVectorFileWriter,
                       QgsApplication, Qgis,
                       QgsPrintLayout, QgsLayoutItemMap, QgsLayoutPoint,
                       QgsLayoutSize, QgsUnitTypes, QgsLayoutExporter)

import json
import hashlib
import os.path
import processing
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .cartographic_filtering import is_insignificant_extent_fragment
from .arch_distribution_dialog import ArchDistributionDialog, get_plugin_version
from .heritage_grouping import (
    canonical_heritage_text,
    resolve_heritage_group,
    strip_trailing_area_designator,
)
from .heritage_matching import (
    DECISION_KEEP,
    DECISION_LINK,
    DECISION_MERGE,
    PRESET_BALANCED,
    ROLE_OTHER,
    ROLE_PROTECTION_ZONE,
    SOURCE_ROLE_LABELS,
    STATUS_AUTO_MERGED,
    STATUS_KEPT_SEPARATE,
    STATUS_LINKED,
    STATUS_PROTECTION_ZONE,
    STATUS_UNIQUE,
    STATUS_USER_MERGED,
    detect_source_role,
    canonical_name,
    evaluate_candidate,
    is_designated_role,
    is_generic_name,
    load_matching_rules,
    matching_rules_metadata,
    selected_content_fingerprint,
    source_priority,
)
from .heritage_matching_dialog import DuplicateReviewDialog
from .heritage_identity_store import DecisionStore, build_source_identity
from .metric_context import MetricContext, MetricContextError
from .preservation_actions import (
    PRESERVATION_ACTION_FIELD_CANDIDATES,
    PRESERVATION_ACTION_STYLES,
    normalize_preservation_action,
    recognized_preservation_actions,
)
from .run_artifacts import (
    build_run_manifest,
    deterministic_content_hash,
    normalize_filename,
    prepare_artifact_paths,
    prepare_output_path,
    python_runtime_environment,
    read_build_info,
    save_manifest_atomic,
    sha256_file,
    sha256_file_bundle,
)

LEGACY_KOREAN_ENCODING = "CP949"
ENCODING_OVERRIDE_PROPERTY = "ArchDistribution/encoding_override"
DEFAULT_LABEL_FONT_FAMILY = "Malgun Gothic"
DEFAULT_LABEL_FONT_SIZE = 10
DEFAULT_ZOOM_PADDING_RATIO = 0.08
DEFAULT_PROGRESS_STEPS = 10
DEGENERATE_PAD_GEOGRAPHIC = 1
DEGENERATE_PAD_PROJECTED = 10
STUDY_BUFFER_SEGMENTS = 20
PROCESSING_BUFFER_SEGMENTS = 50
TOPO_BOUNDARY_EXCLUDE_CODE = "H0017334"
SAFE_BUFFER_DIST_GEOGRAPHIC = 0.000001
SAFE_BUFFER_DIST_PROJECTED = 0.01
MATCH_POLICY_VERSION = "source-aware-v2"


class DuplicateReviewCancelled(Exception):
    """Raised when the user cancels the pre-run duplicate review."""


class ProcessingCancelled(Exception):
    """Raised when the main progress dialog is cancelled."""


def _json_safe_attribute(value):
    """Convert a QGIS attribute value into lossless-enough JSON data."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isNull") and value.isNull():
        return None
    if hasattr(value, "toString"):
        try:
            return value.toString("yyyy-MM-dd")
        except TypeError:
            return value.toString()
    return str(value)


def format_buffer_label(distance_m, use_km=False):
    """Return a compact map label while keeping the source value in metres."""
    value = float(distance_m)
    display_value = value / 1000.0 if use_km and value >= 1000 else value
    unit = "km" if use_km and value >= 1000 else "m"
    compact_value = f"{display_value:.3f}".rstrip("0").rstrip(".")
    return f"{compact_value}{unit}"


class ArchDistribution:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = QCoreApplication.translate('ArchDistribution', '&ArchDistribution')
        self.toolbar = None
        self._current_metric_context = None

    def _user_data_directory(self):
        """Return a writable profile directory for logs and runtime state."""
        try:
            base = Path(QgsApplication.qgisSettingsDirPath())
        except (AttributeError, TypeError, ValueError):
            base = Path(
                QtCore.QStandardPaths.writableLocation(
                    QtCore.QStandardPaths.AppDataLocation
                )
                or self.plugin_dir
            )
        target = base / "ArchDistribution"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _log_path(self):
        return self._user_data_directory() / "latest_log.txt"

    def _record_excluded_layer(self, layer, reason, *, role=None):
        """Record a path-free partial-processing exclusion for manifest v2."""
        statistics = getattr(self, "_current_processing_stats", None)
        if not isinstance(statistics, dict):
            statistics = {}
            self._current_processing_stats = statistics
        record = {
            "name": layer.name() if layer is not None else "<missing-layer>",
            "reason": str(reason),
        }
        if role:
            record["role"] = role
        statistics.setdefault("excluded_layers", []).append(record)

    def _record_processing_warning(self, layer, reason, *, role=None):
        """Record a recoverable issue that makes a run only partly successful."""
        statistics = getattr(self, "_current_processing_stats", None)
        if not isinstance(statistics, dict):
            statistics = {}
            self._current_processing_stats = statistics
        record = {
            "name": layer.name() if layer is not None else "<workflow>",
            "reason": str(reason),
        }
        if role:
            record["role"] = role
        statistics.setdefault("processing_warnings", []).append(record)

    def initGui(self):
        # Create toolbar if it doesn't exist
        if not self.toolbar:
            self.toolbar = self.iface.addToolBar('ArchDistribution')
        self.toolbar.setObjectName('ArchDistribution')

        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.add_action(
            icon_path,
            text=QCoreApplication.translate('ArchDistribution', 'Cultural Heritage Distribution Map'),
            callback=self.run,
            parent=self.iface.mainWindow())

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)

        # Remove toolbar
        if self.toolbar:
            del self.toolbar

    def add_action(self, icon_path, text, callback, enabled_flag=True, add_to_menu=True, add_to_toolbar=True, status_tip=None, parent=None):
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip:
            action.setStatusTip(status_tip)

        if add_to_toolbar:
            # Only add to our custom toolbar (not both)
            if self.toolbar:
                self.toolbar.addAction(action)
            else:
                self.iface.addToolBarIcon(action)  # Fallback to standard toolbar

        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)
        return action

    def run(self):
        """Run the plugin main dialog."""
        print(f"ArchDistribution Version {get_plugin_version()} LOADED")
        self.dlg = ArchDistributionDialog()
        # Connect the run signal to the processing method
        self.dlg.run_requested.connect(self.process_distribution_map)
        self.dlg.renumber_requested.connect(self.process_renumbering)
        self.dlg.exec_()

    def log(self, message):
        """Log a message to the dialog log window, QGIS message bar, and file."""
        timestamp = datetime.now().strftime('%H:%M:%S')
        full_msg = f"[{timestamp}] {message}"

        # 1. Dialog Log
        if hasattr(self, 'dlg') and self.dlg:
            self.dlg.log(full_msg)

        # 2. QGIS Console/Message Bar
        print(f"ArchDistribution: {message}")

        # 3. File Log (New)
        try:
            log_path = self._log_path()
            with log_path.open('a', encoding='utf-8') as f:
                f.write(full_msg + "\n")
        except Exception as e:
            print(f"Log file error: {e}")

    def _build_metric_context(self, layer, settings):
        """Create the single metric contract used by a workflow run.

        Generated layers remain in the analysis CRS so every stored distance,
        area, extent dimension, and buffer geometry is unambiguously metric.
        The untouched input layer remains available in the hidden source group.
        """
        override = (settings or {}).get("analysis_crs_authid") or None
        context = MetricContext.from_layer(layer, analysis_crs=override)
        context = replace(context, output_crs=context.analysis_crs)
        self._current_metric_context = context
        provenance = context.provenance()
        selection = provenance["analysis_selection"]
        self.log(
            "측정 CRS 준비 완료: "
            f"원본={context.source_crs.authid() or '사용자정의'}, "
            f"분석·출력={context.analysis_crs.authid() or '사용자정의'} "
            f"({selection['method']}, 단위=metre)"
        )
        return context

    def _copy_layer_to_analysis_crs(self, layer, metric_context, name):
        """Return a memory copy in the run's projected-metre analysis CRS."""
        try:
            result = processing.run(
                "native:reprojectlayer",
                {
                    "INPUT": layer,
                    "TARGET_CRS": metric_context.analysis_crs,
                    "OUTPUT": "memory:",
                },
            )
            output = result["OUTPUT"]
        except Exception as error:
            raise MetricContextError(
                f"분석 CRS로 레이어를 변환하지 못했습니다: {layer.name()}"
            ) from error
        if not output or not output.isValid():
            raise MetricContextError(
                f"분석 CRS 변환 결과가 유효하지 않습니다: {layer.name()}"
            )
        output.setName(name)
        return output

    def zoom_canvas_to_extent(self, extent_geom, extent_crs=None, padding_ratio=DEFAULT_ZOOM_PADDING_RATIO):
        """Zoom map canvas to a geometry extent (CRS-aware) with a small padding."""
        try:
            if not extent_geom:
                return

            canvas = self.iface.mapCanvas()
            project = QgsProject.instance()
            project_crs = project.crs()

            geom = QgsGeometry(extent_geom)
            if extent_crs and extent_crs != project_crs:
                tr = QgsCoordinateTransform(extent_crs, project_crs, project)
                geom.transform(tr)

            rect = geom.boundingBox()
            if rect.isEmpty():
                return

            xmin, xmax = rect.xMinimum(), rect.xMaximum()
            ymin, ymax = rect.yMinimum(), rect.yMaximum()
            pad_x = (xmax - xmin) * padding_ratio
            pad_y = (ymax - ymin) * padding_ratio

            # Fallback padding for degenerate rectangles
            if pad_x == 0:
                pad_x = DEGENERATE_PAD_GEOGRAPHIC if project_crs.isGeographic() else DEGENERATE_PAD_PROJECTED
            if pad_y == 0:
                pad_y = DEGENERATE_PAD_GEOGRAPHIC if project_crs.isGeographic() else DEGENERATE_PAD_PROJECTED

            padded = QgsRectangle(xmin - pad_x, ymin - pad_y, xmax + pad_x, ymax + pad_y)
            canvas.setExtent(padded)
            canvas.refresh()
        except Exception as e:
            self.log(f"⚠️ 작업 완료 후 화면 확대(Zoom) 실패: {e}")

    def _zoom_duplicate_candidate(self, layer, candidate):
        """Zoom the live map canvas to both sides of a review candidate."""
        feature_ids = {
            int(candidate[key])
            for key in ("left_feature_id", "right_feature_id")
            if candidate.get(key) is not None
        }
        if not feature_ids:
            return

        combined = QgsGeometry()
        request = QgsFeatureRequest().setFilterFids(list(feature_ids))
        for feature in layer.getFeatures(request):
            if not feature.hasGeometry():
                continue
            if combined.isNull():
                combined = QgsGeometry(feature.geometry())
            else:
                combined = combined.combine(feature.geometry())
        if combined.isNull() or combined.isEmpty():
            return

        self.zoom_canvas_to_extent(
            combined,
            extent_crs=layer.crs(),
            padding_ratio=0.25,
        )
        canvas = self.iface.mapCanvas()
        if hasattr(canvas, "flashFeatureIds"):
            try:
                canvas.flashFeatureIds(layer, list(feature_ids))
            except Exception:
                pass

    def process_distribution_map(self, settings):
        """Core logic with logging, progress, and heritage merging."""
        if settings.get("workflow_mode") == "preservation":
            self.process_preservation_area_map(settings)
            return

        # Initialize Log File
        try:
            log_path = self._log_path()
            with log_path.open('w', encoding='utf-8') as f:
                f.write(f"=== ArchDistribution Log Started: {QtCore.QDateTime.currentDateTime().toString(Qt.ISODate)} ===\n")
        except OSError as exc:
            print(f"ArchDistribution: log file initialization failed: {exc}")

        # Disable button to prevent double execution
        self.dlg.btnRun.setEnabled(False)
        self.log("작업을 시작합니다...")

        # 0. Setup Progress Dialog
        total_steps = DEFAULT_PROGRESS_STEPS
        progress = QProgressDialog("데이터를 처리하는 중입니다...", "중단", 0, total_steps, self.iface.mainWindow())
        progress.setWindowModality(Qt.WindowModal)
        progress.setWindowTitle("ArchDistribution 진행률")
        progress.setMinimumDuration(0)
        progress.setValue(0)
        self._active_progress = progress
        transaction_committed = False
        self._pending_decision_store = None
        self._pending_decision_store_path = None
        self._pending_decision_store_dirty = False
        run_started_at = datetime.now().astimezone()
        self._current_processing_stats = {}

        try:
            current_step = 0

            # Step 1: Groups
            self.log("레이어 그룹 설정 중...")
            root = QgsProject.instance().layerTreeRoot()

            # 1-1. Build in staging. The last successful result remains
            # available until every processing step has completed.
            out_group = self._begin_output_transaction(
                "ArchDistribution_결과물",
                "ArchDistribution_작업중",
            )

            # Sub-groups in specific order (Top to Bottom)
            stu_group = out_group.addGroup("00_조사구역_및_표제")
            her_group = out_group.addGroup("01_유적_현황")
            ext_group = out_group.addGroup("02_도곽_및_영역")
            buf_group = out_group.addGroup("03_조사구역_버퍼")
            topo_merged_group = out_group.addGroup("04_수치지형도_병합")
            zone_merged_group = out_group.addGroup("05_현상변경허용기준")
            audit_group = out_group.addGroup("06_중복_검수")
            audit_group.setItemVisibilityChecked(False)

            # 1-2. Source Group: Persist (don't delete original layers!)
            src_group = root.findGroup("ArchDistribution_원본_데이터")
            if not src_group:
                src_group = root.addGroup("ArchDistribution_원본_데이터")

            # Hide source group by default to focus on outputs
            src_group.setItemVisibilityChecked(False)
            current_step += 1
            progress.setValue(current_step)

            # Step 2: Study Area (Clone for display)
            self.log("조사구역 처리 중...")
            original_study_layer = QgsProject.instance().mapLayer(settings['study_area_id'])
            if not original_study_layer:
                self.log("오류: 조사지역 레이어를 찾을 수 없습니다.")
                return

            # Establish one explicit metric contract for the whole run.  A
            # missing/invalid CRS or failed transform is fatal: silently
            # labelling coordinates as EPSG:5186 would corrupt every result.
            metric_context = self._build_metric_context(
                original_study_layer,
                settings,
            )
            study_result_layer = self._copy_layer_to_analysis_crs(
                original_study_layer,
                metric_context,
                "00_조사구역",
            )
            analysis_study_layer = study_result_layer

            self.apply_study_style(study_result_layer, settings['study_style'])
            QgsProject.instance().addMapLayer(study_result_layer, False)
            stu_group.addLayer(study_result_layer)

            # Also keep original in source group (hidden)
            self.move_layer_to_group(original_study_layer, src_group)
            current_step += 1
            progress.setValue(current_step)

            # Step 3: Topo Merge
            if settings['topo_layer_ids']:
                self.log(f"수치지형도 병합 시작 ({len(settings['topo_layer_ids'])}매)...")
                try:
                    self.merge_and_style_topo(settings['topo_layer_ids'], topo_merged_group, src_group, settings['topo_style'])
                    self.log("수치지형도 병합 및 스타일 적용 완료.")
                except Exception as e:
                    self.log(f"경고: 지형도 병합 중 일부 데이터 건립 오류 발생 (계속 진행): {str(e)}")
                    for layer_id in settings["topo_layer_ids"]:
                        self._record_excluded_layer(
                            QgsProject.instance().mapLayer(layer_id),
                            "topographic_merge_failed",
                            role="topographic_map",
                        )
            current_step += 1
            progress.setValue(current_step)

            # Step 4: Centroid & Extent
            self.log("도곽(Extent) 영역 계산 중...")
            centroid = self.get_study_area_centroid(analysis_study_layer)
            if not centroid:
                self.log("오류: 조사지역의 데이터가 비어있거나 중심점을 계산할 수 없습니다.")
                return

            self.log(f"중심점 기반 도곽 생성 중 (Scale 1:{settings['scale']})...")
            extent_geom = self.create_extent_polygon(
                centroid,
                settings['paper_width'],
                settings['paper_height'],
                settings['scale'],
                ext_group,
                metric_context.analysis_crs,
            )
            extent_bounds = extent_geom.boundingBox()
            self.log(
                "도곽 생성 완료: "
                f"{settings['paper_width']}x{settings['paper_height']} mm "
                f"(1:{settings['scale']}) → "
                f"{extent_bounds.width():,.1f}x"
                f"{extent_bounds.height():,.1f} m, "
                f"{metric_context.analysis_crs.authid()}"
            )
            project_crs = QgsProject.instance().crs()
            if project_crs != metric_context.analysis_crs:
                self.log(
                    "안내: 프로젝트 화면 CRS와 도곽 CRS가 다릅니다. "
                    f"화면={project_crs.authid()}, "
                    f"도곽·수집={metric_context.analysis_crs.authid()}. "
                    "ArchDistribution 자동 인쇄조판은 도곽 CRS를 "
                    "사용합니다. 수동 인쇄조판도 지도 항목 CRS를 "
                    f"{metric_context.analysis_crs.authid()}로 설정하세요."
                )
            current_step += 1
            progress.setValue(current_step)

            # Step 5: Buffers
            if settings['buffers']:
                self.log(f"버퍼 생성 시작 ({len(settings['buffers'])}개)...")
                for distance in settings['buffers']:
                    if progress.wasCanceled():
                        raise ProcessingCancelled()
                    self.create_buffer(
                        analysis_study_layer,
                        distance,
                        buf_group,
                        settings['buffer_style'],
                    )
                    self.log(f"{distance}m 버퍼 생성 완료.")
                current_step += 1
                progress.setValue(current_step)

            # Step 6: Heritage Consolidation & Numbering
            if settings['heritage_layer_ids']:
                self.log("주변 유적 데이터 수집 및 병합 시작...")

                # Pre-fetch the Zone layer while preserving its current QGIS
                # provider, subset, edits, and declared encoding.
                zone_layer_obj = None
                if settings.get('zone_layer_id'):
                    zone_layer_obj = QgsProject.instance().mapLayer(settings.get('zone_layer_id'))
                    if zone_layer_obj:
                        self.fix_layer_encoding(zone_layer_obj)

                consolidation = self.consolidate_heritage_layers(
                    settings['heritage_layer_ids'],
                    extent_geom,
                    analysis_study_layer,
                    src_group,
                    filter_categories=settings.get('filter_items', None),
                    exclusion_list=settings.get('exclusion_list', []),
                    zone_layer=zone_layer_obj,
                    exclude_extent_slivers=settings.get(
                        "exclude_extent_slivers",
                        True,
                    ),
                    paper_size_mm=(
                        settings["paper_width"],
                        settings["paper_height"],
                    ),
                    source_roles=settings.get("source_roles", {}),
                    source_encodings=settings.get("source_encodings", {}),
                    match_preset=settings.get(
                        "match_preset",
                        PRESET_BALANCED,
                    ),
                    reuse_review_decisions=settings.get(
                        "reuse_review_decisions",
                        True,
                    ),
                )

                if isinstance(consolidation, dict):
                    merged_heritage = consolidation.get("main")
                    merged_heritage_layers = (
                        consolidation.get("main_layers")
                        or ([merged_heritage] if merged_heritage else [])
                    )
                    suppressed_layers = (
                        consolidation.get("suppressed_layers")
                        or ([consolidation.get("suppressed")]
                            if consolidation.get("suppressed") else [])
                    )
                    protection_layers = (
                        consolidation.get("protection_layers")
                        or ([consolidation.get("protection")]
                            if consolidation.get("protection") else [])
                    )
                    audit_layers = (
                        consolidation.get("audit_layers")
                        or ([consolidation.get("audit")]
                            if consolidation.get("audit") else [])
                    )
                else:
                    merged_heritage = consolidation
                    merged_heritage_layers = (
                        [merged_heritage] if merged_heritage else []
                    )
                    suppressed_layers = []
                    protection_layers = []
                    audit_layers = []

                if merged_heritage:
                    self.log(f"병합 완료 ({merged_heritage.featureCount()}개소).")

                    buffer_geoms = []
                    if settings.get('buffers'):
                        combined_study = QgsGeometry()
                        for f in analysis_study_layer.getFeatures():
                            if not f.hasGeometry():
                                continue
                            if combined_study.isNull():
                                combined_study = f.geometry()
                            else:
                                combined_study = combined_study.combine(f.geometry())

                        if not combined_study.isNull():
                            sorted_buffers = sorted(settings['buffers'])
                            for dist in sorted_buffers:
                                bg = combined_study.buffer(dist, STUDY_BUFFER_SEGMENTS)
                                buffer_geoms.append({'dist': dist, 'geom': bg})
                            self.log(f"버퍼 구간 처리 준비 완료 ({len(buffer_geoms)}단계).")

                        if settings.get('sort_order') != 1:
                            self.log("주의: 버퍼가 설정되었으나 '정렬 기준'이 '거리순'이 아닙니다. 버퍼 구간별 번호 부여는 '거리순'에서만 적용됩니다.")
                    # [NEW] Pass restrict_to_buffer setting
                    self.number_heritage_layers_v4(
                        merged_heritage_layers,
                        analysis_study_layer,
                        settings['sort_order'],
                        extent_geom,
                        metric_context.analysis_crs,
                        buffer_geoms,
                        restrict_to_buffer=settings.get('restrict_to_buffer', True),
                        metric_context=metric_context,
                    )
                    self.log("유적 번호 부여 완료. 스타일 및 라벨 적용 중...")
                    for result_layer in merged_heritage_layers:
                        self.apply_heritage_style(
                            result_layer,
                            settings['heritage_style'],
                            font_size=settings.get('label_font_size', DEFAULT_LABEL_FONT_SIZE),
                            font_family=settings.get('label_font_family', DEFAULT_LABEL_FONT_FAMILY)
                        )
                        QgsProject.instance().addMapLayer(result_layer, False)
                        her_group.addLayer(result_layer)
                    self.log("최종 결과 유적 레이어 등록 완료.")

                    for protection_layer in protection_layers:
                        if protection_layer.featureCount() <= 0:
                            continue
                        self.apply_protection_zone_style(protection_layer)
                        QgsProject.instance().addMapLayer(
                            protection_layer,
                            False,
                        )
                        her_group.addLayer(protection_layer)
                        self.log(
                            "지정유산 보호구역 경계를 무번호 레이어로 "
                            "등록했습니다."
                        )

                    for suppressed_layer in suppressed_layers:
                        if suppressed_layer.featureCount() <= 0:
                            continue
                        QgsProject.instance().addMapLayer(
                            suppressed_layer,
                            False,
                        )
                        audit_group.addLayer(suppressed_layer)
                    for audit_layer in audit_layers:
                        if audit_layer.featureCount() <= 0:
                            continue
                        QgsProject.instance().addMapLayer(
                            audit_layer,
                            False,
                        )
                        audit_group.addLayer(audit_layer)
                    audit_group.setItemVisibilityChecked(False)

                    # [NEW] Check Zone Layer and Add/Style it if present
                    zone_id = settings.get('zone_layer_id')
                    if zone_id:
                        z_layer = QgsProject.instance().mapLayer(zone_id)
                        if z_layer:
                            self.log(
                                "현상변경 허용구간 레이어 분할 및 "
                                "스타일 적용 중..."
                            )

                            buffer_limit_geom = None
                            if settings.get('clip_zone_to_buffer', False):
                                if buffer_geoms:
                                    buffer_limit_geom = buffer_geoms[-1]['geom']
                                else:
                                    self.log("⚠️ 경고: '버퍼 범위 내 자르기'가 켜졌지만 버퍼가 설정되지 않았습니다. 도곽(Extent)만으로 진행합니다.")

                            self.split_and_style_zone_layer(
                                z_layer,
                                zone_merged_group,
                                extent_geom,
                                buffer_limit_geom,
                                source_crs=metric_context.analysis_crs
                            )

                else:
                    self.log("알림: 영역 내에 수집된 유적이 없습니다.")

            current_step = total_steps
            progress.setValue(current_step)
            if progress.wasCanceled():
                raise ProcessingCancelled()

            # Zoom to extent (CRS-aware + padded) to avoid showing blank space
            self.zoom_canvas_to_extent(
                extent_geom,
                extent_crs=metric_context.analysis_crs,
                padding_ratio=DEFAULT_ZOOM_PADDING_RATIO,
            )
            self._commit_output_transaction()
            transaction_committed = True
            optional_result = self._run_optional_outputs(
                settings,
                out_group,
                extent_geom,
                metric_context.analysis_crs,
                "distribution_map",
                run_started_at,
            )
            self._save_pending_decision_store()
            optional_errors = optional_result.get("errors", [])
            if optional_errors:
                self.log(
                    "지도 결과는 생성했지만 선택 출력 일부가 "
                    "실패했습니다. 위 경고를 확인하세요."
                )
                completion_message = "작업 부분 완료 — 선택 출력 경고 확인"
                completion_level = 1
            else:
                self.log("모든 작업이 성공적으로 완료되었습니다.")
                completion_message = "작업 완료"
                completion_level = 0

            # Notify Log File
            self.log(f"로그 파일 저장됨: {self._log_path()}")
            self.iface.messageBar().pushMessage(
                "ArchDistribution",
                completion_message,
                level=completion_level,
            )

        except DuplicateReviewCancelled:
            self.log("사용자가 실행 전 중복 검토를 취소했습니다.")
            self._write_terminal_manifest(
                settings,
                "distribution_map",
                run_started_at,
                "cancelled",
            )
            self.iface.messageBar().pushMessage(
                "ArchDistribution",
                "중복 검토가 취소되어 결과를 만들지 않았습니다.",
                level=1,
            )
        except ProcessingCancelled:
            self.log("사용자가 데이터 처리를 중단했습니다.")
            self._write_terminal_manifest(
                settings,
                "distribution_map",
                run_started_at,
                "cancelled",
            )
            self.iface.messageBar().pushMessage(
                "ArchDistribution",
                "작업이 중단되었습니다.",
                level=1,
            )
        except Exception as e:
            self.log(f"치명적 오류 발생: {str(e)}")
            import traceback
            tb = traceback.format_exc()
            self.log(tb)
            self._write_terminal_manifest(
                settings,
                "distribution_map",
                run_started_at,
                "failed",
                error=e,
            )
            QMessageBox.critical(self.dlg, "오류", f"작업 중 오류 발생: {str(e)}")
        finally:
            if not transaction_committed:
                self._rollback_output_transaction()
                self._clear_pending_decision_store()
            self.dlg.btnRun.setEnabled(True)
            if 'progress' in locals():
                progress.close()
            self._active_progress = None

    def process_preservation_area_map(self, settings):
        """Create a numbered, categorized preservation-area result layer."""
        try:
            log_path = self._log_path()
            with log_path.open('w', encoding='utf-8') as log_file:
                log_file.write(
                    "=== ArchDistribution Preservation Log Started: "
                    f"{QtCore.QDateTime.currentDateTime().toString(Qt.ISODate)} "
                    "===\n"
                )
        except OSError as exc:
            print(f"ArchDistribution: log file initialization failed: {exc}")

        self.dlg.btnRun.setEnabled(False)
        progress = QProgressDialog(
            "매장유산 유존지역을 처리하는 중입니다...",
            "중단",
            0,
            5,
            self.iface.mainWindow(),
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setWindowTitle("ArchDistribution 진행률")
        progress.setMinimumDuration(0)
        progress.setValue(0)
        self._active_progress = progress
        transaction_committed = False
        run_started_at = datetime.now().astimezone()
        self._current_processing_stats = {}

        try:
            self.log("매장유산 유존지역 전용 작업을 시작합니다...")
            source_layer = QgsProject.instance().mapLayer(
                settings.get("preservation_layer_id")
            )
            if (
                not source_layer
                or source_layer.type() != 0
                or source_layer.geometryType() != 2
            ):
                QMessageBox.warning(
                    self.dlg,
                    "입력 오류",
                    "유효한 매장유산 유존지역 폴리곤 레이어를 선택하세요.",
                )
                return

            study_layer = QgsProject.instance().mapLayer(
                settings.get("preservation_study_area_id")
            )
            if (
                not study_layer
                or study_layer.type() != 0
                or study_layer.geometryType() != 2
            ):
                QMessageBox.warning(
                    self.dlg,
                    "입력 오류",
                    "도곽 기준이 될 유효한 조사구역 폴리곤을 선택하세요.",
                )
                return
            if study_layer.id() == source_layer.id():
                QMessageBox.warning(
                    self.dlg,
                    "입력 오류",
                    "유존지역 자료와 도곽 기준 조사구역은 서로 다른 "
                    "레이어를 선택하세요.",
                )
                return

            metric_context = self._build_metric_context(study_layer, settings)
            analysis_study_layer = self._copy_layer_to_analysis_crs(
                study_layer,
                metric_context,
                "매장유산_분석기준",
            )
            centroid = self.get_study_area_centroid(analysis_study_layer)
            if not centroid:
                QMessageBox.warning(
                    self.dlg,
                    "입력 오류",
                    "조사구역이 비어 있어 도곽 중심을 계산할 수 없습니다.",
                )
                return
            extent_geom = self.calculate_extent_geometry(
                centroid,
                settings.get("preservation_paper_width", 210),
                settings.get("preservation_paper_height", 297),
                settings.get("preservation_scale", 5000),
            )
            self.log(
                "매장유산 도곽 계산 완료: "
                f"{settings.get('preservation_paper_width', 210)}×"
                f"{settings.get('preservation_paper_height', 297)} mm, "
                f"1:{settings.get('preservation_scale', 5000)} → "
                f"{extent_geom.boundingBox().width():,.1f}×"
                f"{extent_geom.boundingBox().height():,.1f} "
                "m, "
                f"{metric_context.analysis_crs.authid()}"
            )

            requested_field = settings.get("preservation_action_field")
            action_field = requested_field or self.find_preservation_action_field(
                source_layer
            )
            action_idx = (
                source_layer.fields().indexFromName(action_field)
                if action_field
                else -1
            )
            recognized_actions = (
                recognized_preservation_actions(
                    source_layer.uniqueValues(action_idx)
                )
                if action_idx >= 0
                else set()
            )
            if not recognized_actions:
                QMessageBox.warning(
                    self.dlg,
                    "보존조치 확인 필요",
                    "선택한 필드에서 현상보존·정밀발굴조사·시굴조사·"
                    "표본조사 값을 확인할 수 없습니다.\n"
                    "보존조치 필드를 다시 선택해 주세요.",
                )
                self.log(
                    "중단: 선택 레이어에서 네 가지 보존조치 값을 "
                    "확인하지 못했습니다."
                )
                return

            self.log(
                f"보존조치 필드 확인: {action_field}="
                f"{', '.join(sorted(recognized_actions))}"
            )
            progress.setValue(1)
            if progress.wasCanceled():
                raise ProcessingCancelled()

            root = QgsProject.instance().layerTreeRoot()
            out_group = self._begin_output_transaction(
                "ArchDistribution_매장유산유존지역",
                "ArchDistribution_매장유산_작업중",
            )

            src_group = root.findGroup("ArchDistribution_원본_데이터")
            if not src_group:
                src_group = root.addGroup("ArchDistribution_원본_데이터")
            src_group.setItemVisibilityChecked(False)

            output = self.consolidate_heritage_layers(
                [source_layer.id()],
                extent_geom,
                analysis_study_layer,
                src_group,
                preservation_only=True,
                preservation_action_fields={
                    source_layer.id(): action_field,
                },
                source_encodings={
                    source_layer.id(): settings.get(
                        "preservation_encoding", ""
                    ),
                },
                exclude_extent_slivers=settings.get(
                    "preservation_exclude_extent_slivers",
                    True,
                ),
                paper_size_mm=(
                    settings.get("preservation_paper_width", 210),
                    settings.get("preservation_paper_height", 297),
                ),
            )
            if output is None:
                QMessageBox.warning(
                    self.dlg,
                    "처리 결과 없음",
                    "처리할 매장유산 유존지역 객체가 없습니다.",
                )
                return
            progress.setValue(3)
            if progress.wasCanceled():
                raise ProcessingCancelled()

            self.number_heritage_v4(
                output,
                analysis_study_layer,
                settings.get("preservation_sort_order", 0),
                extent_geom=extent_geom,
                extent_crs=metric_context.analysis_crs,
                buffer_geoms=[],
                restrict_to_buffer=False,
                metric_context=metric_context,
            )

            self.apply_heritage_style(
                output,
                {
                    "fill_color": "#FFFFFF",
                    "stroke_color": "#FF0000",
                    "stroke_width": settings.get(
                        "preservation_stroke_width",
                        0.3,
                    ),
                    "opacity": settings.get(
                        "preservation_opacity",
                        1.0,
                    ),
                    "preservation_action_styles": settings.get(
                        "preservation_action_styles",
                    ),
                    "preservation_action_field": "보존조치",
                },
                font_size=settings.get(
                    "preservation_label_font_size",
                    DEFAULT_LABEL_FONT_SIZE,
                ),
                font_family=settings.get(
                    "preservation_label_font_family",
                    DEFAULT_LABEL_FONT_FAMILY,
                ),
            )
            QgsProject.instance().addMapLayer(output, False)
            out_group.addLayer(output)
            progress.setValue(4)
            if progress.wasCanceled():
                raise ProcessingCancelled()

            numbers = {
                feature["번호"]
                for feature in output.getFeatures()
                if feature["번호"] is not None
            }
            self.log(
                f"완료: {output.featureCount()}개 조치·도형, "
                f"{len(numbers)}개 고유 유적 번호"
            )
            self.zoom_canvas_to_extent(
                extent_geom,
                extent_crs=metric_context.analysis_crs,
                padding_ratio=DEFAULT_ZOOM_PADDING_RATIO,
            )
            progress.setValue(5)
            if progress.wasCanceled():
                raise ProcessingCancelled()
            self._commit_output_transaction()
            transaction_committed = True
            optional_result = self._run_optional_outputs(
                settings,
                out_group,
                extent_geom,
                metric_context.analysis_crs,
                "preservation_area",
                run_started_at,
            )
            optional_errors = optional_result.get("errors", [])
            if optional_errors:
                completion_message = (
                    "매장유산 유존지역 부분 완료 — 선택 출력 경고 확인"
                )
                completion_level = 1
            else:
                completion_message = "매장유산 유존지역 생성 완료"
                completion_level = 0
            self.iface.messageBar().pushMessage(
                "ArchDistribution",
                completion_message,
                level=completion_level,
            )
        except ProcessingCancelled:
            self.log(
                "사용자가 매장유산 유존지역 처리를 중단했습니다."
            )
            self._write_terminal_manifest(
                settings,
                "preservation_area",
                run_started_at,
                "cancelled",
            )
            self.iface.messageBar().pushMessage(
                "ArchDistribution",
                "매장유산 유존지역 작업을 중단했습니다.",
                level=1,
            )
        except Exception as exc:
            self.log(f"치명적 오류 발생: {exc}")
            import traceback
            self.log(traceback.format_exc())
            self._write_terminal_manifest(
                settings,
                "preservation_area",
                run_started_at,
                "failed",
                error=exc,
            )
            QMessageBox.critical(
                self.dlg,
                "오류",
                f"매장유산 유존지역 처리 중 오류가 발생했습니다: {exc}",
            )
        finally:
            if not transaction_committed:
                self._rollback_output_transaction()
            self.dlg.btnRun.setEnabled(True)
            progress.close()
            self._active_progress = None

    def process_renumbering(self, layer):
        """Renumber the specific layer based on current UI settings."""
        self.log(f"레이어 '{layer.name()}' 번호 새로고침 중...")

        try:
            # 1. Get Settings (Sort Order & Study Area)
            settings = self.dlg.get_settings()
            sort_order = settings['sort_order']

            # 2. Get a metric centroid and optional analysis-CRS study copy.
            centroid = None
            study_layer = None
            analysis_study_layer = None
            if settings['study_area_id']:
                study_layer = QgsProject.instance().mapLayer(settings['study_area_id'])
            metric_basis = study_layer or layer
            metric_context = self._build_metric_context(metric_basis, settings)
            if study_layer:
                analysis_study_layer = self._copy_layer_to_analysis_crs(
                    study_layer,
                    metric_context,
                    "재번호_분석기준",
                )
                centroid = self.get_study_area_centroid(
                    analysis_study_layer
                )

            # [FIX] If no study layer, use layer's own extent center as centroid for extent calculation
            if not centroid:
                layer_extent = layer.extent()
                if not layer_extent.isEmpty():
                    centroid = metric_context.transform_point(
                        layer_extent.center(),
                        layer.crs(),
                        metric_context.analysis_crs,
                    )
                    self.log("조사지역 미선택 - 현재 레이어 범위 중심 사용")

            if sort_order == 1 and not centroid:
                QMessageBox.warning(self.dlg, "설정 오류", "조사지역(기준) 레이어가 선택되지 않아 '가까운 순' 정렬을 할 수 없습니다.\n기준을 변경하거나 조사지역을 다시 선택하세요.")
                return

            # [NEW] Calculate Extent Geometry for Exclusion
            extent_geom = self.calculate_extent_geometry(
                centroid,
                settings['paper_width'],
                settings['paper_height'],
                settings['scale']
            )

            # [NEW] Calculate Buffer Geometries (Renumbering context)
            buffer_geoms = []
            if settings.get('buffers') and analysis_study_layer:
                combined_study = QgsGeometry()
                for f in analysis_study_layer.getFeatures():
                    if combined_study.isNull():
                        combined_study = f.geometry()
                    else:
                        combined_study = combined_study.combine(f.geometry())

                if not combined_study.isNull():
                    sorted_buffers = sorted(settings['buffers'])
                    for dist in sorted_buffers:
                        bg = combined_study.buffer(dist, STUDY_BUFFER_SEGMENTS)
                        buffer_geoms.append({'dist': dist, 'geom': bg})
                    self.log(f"버퍼 구간 적용 ({len(buffer_geoms)}단계).")

            # 3. Call Numbering Logic
            extent_crs = metric_context.analysis_crs
            numbering_summary = self.number_heritage_v4(
                layer,
                analysis_study_layer if analysis_study_layer else centroid,
                sort_order,
                extent_geom,
                extent_crs,
                buffer_geoms,
                restrict_to_buffer=settings.get('restrict_to_buffer', True),
                metric_context=metric_context,
            )

            # 4. Refresh & Re-Apply Style (to update font/labels)
            self.log(f"레이어 '{layer.name()}' 번호 재정렬 완료. 스타일 적용 중...")
            self.apply_heritage_style(
                layer,
                settings['heritage_style'],
                font_size=settings.get('label_font_size', DEFAULT_LABEL_FONT_SIZE),
                font_family=settings.get('label_font_family', DEFAULT_LABEL_FONT_FAMILY)
            )

            layer.triggerRepaint()
            self.iface.mapCanvas().refresh()
            numbering_summary = numbering_summary or {}
            group_count = int(
                numbering_summary.get("number_group_count", 0)
            )
            numbered_feature_count = int(
                numbering_summary.get("numbered_feature_count", 0)
            )
            completion_text = self.dlg._t(
                f"{numbered_feature_count:,}개 도형을 "
                f"{group_count:,}개 번호 묶음으로 다시 정리했습니다. "
                "중복·대표 판정은 변경하지 않았습니다.",
                f"Reordered {numbered_feature_count:,} features into "
                f"{group_count:,} numbering groups. Duplicate and "
                "representative decisions were not changed.",
            )
            self.log(f"레이어 '{layer.name()}': {completion_text}")
            QMessageBox.information(
                self.dlg,
                self.dlg._t("완료", "Complete"),
                completion_text,
            )

        except Exception as e:
            self.log(f"오류 발생: {str(e)}")
            QMessageBox.critical(self.dlg, "오류", f"번호 부여 중 오류가 발생했습니다: {str(e)}")

    def perform_scan(self, settings):
        """Execute smart scan and update dialog."""
        self.log("스마트 스캔 시작...")
        try:
            categories = self.scan_smart_categories(settings)
            self.dlg.update_category_list(categories)
            self.log(f"스캔 완료: {len(categories)}개 분류 발견됨.")
        except Exception as e:
            self.log(f"스캔 오류: {str(e)}")
            QMessageBox.critical(self.dlg, "오류", f"스캔 중 오류: {str(e)}")

    def move_layer_to_group(self, layer, group):
        """Move an existing layer to a specific group and hide it."""
        root = QgsProject.instance().layerTreeRoot()
        layer_node = root.findLayer(layer.id())
        if layer_node:
            transaction = getattr(
                self,
                "_active_output_transaction",
                None,
            )
            if (
                transaction is not None
                and layer.id() not in transaction["layer_moves"]
            ):
                original_parent = layer_node.parent()
                original_index = original_parent.children().index(
                    layer_node
                )
                transaction["layer_moves"][layer.id()] = {
                    "parent": original_parent,
                    "index": original_index,
                    "visible": layer_node.itemVisibilityChecked(),
                    "node": layer_node.clone(),
                }
                transaction["move_order"].append(layer.id())

            # Check if it's already in the target group
            if layer_node.parent() == group:
                layer_node.setItemVisibilityChecked(False)
                return

            clone = layer_node.clone()
            clone.setItemVisibilityChecked(False)  # Hide the original layer
            group.addChildNode(clone)
            layer_node.parent().removeChildNode(layer_node)

    @staticmethod
    def _remove_group_with_layers(group):
        """Remove a result group and unregister layers owned by it."""
        if group is None:
            return
        project = QgsProject.instance()
        layer_ids = {
            node.layerId()
            for node in group.findLayers()
            if node.layerId()
        }
        if layer_ids:
            project.removeMapLayers(list(layer_ids))
        parent = group.parent()
        if parent is not None:
            parent.removeChildNode(group)

    def _begin_output_transaction(
        self,
        final_group_name,
        staging_group_name,
    ):
        """Create a staging group while preserving the last good result."""
        if getattr(self, "_active_output_transaction", None):
            self._rollback_output_transaction()

        root = QgsProject.instance().layerTreeRoot()
        stale_staging = root.findGroup(staging_group_name)
        if stale_staging:
            self._remove_group_with_layers(stale_staging)

        source_group = root.findGroup(
            "ArchDistribution_원본_데이터"
        )
        transaction = {
            "root": root,
            "final_group_name": final_group_name,
            "staging_group_name": staging_group_name,
            "previous_group": root.findGroup(final_group_name),
            "staging_group": root.insertGroup(0, staging_group_name),
            "layer_moves": {},
            "move_order": [],
            "source_group_preexisting": source_group is not None,
            "source_group_visibility": (
                source_group.itemVisibilityChecked()
                if source_group
                else None
            ),
        }
        self._active_output_transaction = transaction
        return transaction["staging_group"]

    def _commit_output_transaction(self):
        """Atomically replace the old result group with staged output."""
        transaction = getattr(
            self,
            "_active_output_transaction",
            None,
        )
        if transaction is None:
            return

        previous_group = transaction["previous_group"]
        if previous_group is not None:
            self._remove_group_with_layers(previous_group)
        transaction["staging_group"].setName(
            transaction["final_group_name"]
        )
        self._active_output_transaction = None

    def _rollback_output_transaction(self):
        """Remove staged output and restore every relocated input layer."""
        transaction = getattr(
            self,
            "_active_output_transaction",
            None,
        )
        if transaction is None:
            return

        root = transaction["root"]
        for layer_id in reversed(transaction["move_order"]):
            move = transaction["layer_moves"][layer_id]
            current_node = root.findLayer(layer_id)
            if current_node is not None:
                current_parent = current_node.parent()
                if current_parent is move["parent"]:
                    current_node.setItemVisibilityChecked(
                        move["visible"]
                    )
                    continue
                current_parent.removeChildNode(current_node)

            restored_node = move["node"].clone()
            restored_node.setItemVisibilityChecked(move["visible"])
            original_parent = move["parent"]
            insert_index = min(
                move["index"],
                len(original_parent.children()),
            )
            original_parent.insertChildNode(
                insert_index,
                restored_node,
            )

        self._remove_group_with_layers(
            transaction["staging_group"]
        )

        source_group = root.findGroup(
            "ArchDistribution_원본_데이터"
        )
        if transaction["source_group_preexisting"]:
            if source_group is not None:
                source_group.setItemVisibilityChecked(
                    transaction["source_group_visibility"]
                )
        elif source_group is not None and not source_group.children():
            source_group.parent().removeChildNode(source_group)

        self._active_output_transaction = None

    def _review_decision_store_path(self):
        """Return a project-local decision file or a safe user-data fallback."""
        project = QgsProject.instance()
        project_file = str(project.fileName() or "").strip()
        if project_file:
            return os.path.join(
                os.path.dirname(project_file),
                "ArchDistribution_review_decisions.json",
            )

        app_data = QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.AppDataLocation
        )
        base_dir = app_data or self.plugin_dir
        return os.path.join(
            base_dir,
            "ArchDistribution",
            "review_decisions.json",
        )

    def _clear_pending_decision_store(self):
        self._pending_decision_store = None
        self._pending_decision_store_path = None
        self._pending_decision_store_dirty = False

    def _decision_cache_provenance(self):
        """Return a path-free fingerprint of the reusable review cache."""
        path = Path(self._review_decision_store_path())
        if not path.exists() or not path.is_file():
            return {"present": False, "sha256": None}
        try:
            return {
                "present": True,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        except OSError:
            return {"present": True, "sha256": "unreadable"}

    def _save_pending_decision_store(self):
        """Persist reviewed decisions only after the map output commits."""
        store = getattr(self, "_pending_decision_store", None)
        path = getattr(self, "_pending_decision_store_path", None)
        dirty = bool(
            getattr(self, "_pending_decision_store_dirty", False)
        )
        if not store or not path or not dirty:
            self._clear_pending_decision_store()
            return
        try:
            store.save(path)
            self.log(f"검토 결정 저장 완료: {path} ({len(store)}건)")
        except Exception as exc:
            # A decision-cache write failure must not discard an otherwise
            # complete map result.
            self.log(
                "⚠️ 검토 결정 파일을 저장하지 못했습니다. "
                f"이번 결과는 정상 유지됩니다: {exc}"
            )
        finally:
            self._clear_pending_decision_store()

    def _artifact_layer_summary(self, layer, *, role=None, kind=None):
        encoding, encoding_basis = self._declared_layer_encoding(layer)
        summary = {
            "name": layer.name(),
            "layer_id": layer.id(),
            "source": layer.source(),
            "provider": layer.providerType(),
            "crs": layer.crs().authid() or layer.crs().toWkt(),
            "geometry_type": QgsWkbTypes.displayString(layer.wkbType()),
            "feature_count": layer.featureCount(),
            "encoding": encoding,
            "encoding_basis": encoding_basis,
        }
        if role is not None:
            summary["role"] = role
        if kind is not None:
            summary["kind"] = kind
        return summary

    def _artifact_input_summaries(self, settings, workflow):
        entries = []
        if workflow == "preservation_area":
            entries.extend((
                (
                    settings.get("preservation_layer_id"),
                    "preservation_area",
                ),
                (
                    settings.get("preservation_study_area_id"),
                    "study_area",
                ),
            ))
        else:
            entries.append((settings.get("study_area_id"), "study_area"))
            entries.extend(
                (layer_id, "topographic")
                for layer_id in settings.get("topo_layer_ids", [])
            )
            source_roles = settings.get("source_roles", {})
            entries.extend(
                (
                    layer_id,
                    source_roles.get(layer_id) or ROLE_OTHER,
                )
                for layer_id in settings.get("heritage_layer_ids", [])
            )
            entries.append((settings.get("zone_layer_id"), "change_zone"))

        summaries = []
        seen = set()
        project = QgsProject.instance()
        scans_by_layer = {}
        statistics = getattr(self, "_current_processing_stats", {})
        if isinstance(statistics, dict):
            for scan in statistics.get("source_scans", []):
                if not isinstance(scan, dict) or not scan.get("layer"):
                    continue
                scans_by_layer.setdefault(str(scan["layer"]), []).append(scan)
        for layer_id, role in entries:
            if not layer_id or layer_id in seen:
                continue
            seen.add(layer_id)
            layer = project.mapLayer(layer_id)
            if layer is not None and layer.type() == 0:
                summary = self._artifact_layer_summary(layer, role=role)
                scans = scans_by_layer.get(layer.name(), [])
                if scans:
                    summary["geometry_repairs"] = sum(
                        int(scan.get("geometry_repairs", 0) or 0)
                        for scan in scans
                    )
                    summary["invalid_geometry_exclusions"] = sum(
                        int(
                            scan.get(
                                "invalid_geometry_exclusions", 0
                            ) or 0
                        )
                        for scan in scans
                    )
                summaries.append(summary)
        return summaries

    @staticmethod
    def _shapefile_bundle_paths(source_path):
        """Return same-basename Shapefile components on any case-sensitive OS."""
        source_path = Path(source_path)
        suffix_order = (
            ".shp", ".shx", ".dbf", ".prj", ".qpj", ".cpg", ".qmd",
        )
        wanted = set(suffix_order)
        try:
            siblings = sorted(
                (
                    candidate
                    for candidate in source_path.parent.iterdir()
                    if candidate.is_file()
                    and candidate.stem.casefold() == source_path.stem.casefold()
                    and candidate.suffix.casefold() in wanted
                ),
                key=lambda candidate: candidate.name.casefold(),
            )
        except OSError:
            siblings = []
        by_suffix = {}
        for candidate in siblings:
            by_suffix.setdefault(candidate.suffix.casefold(), candidate)
        return [
            by_suffix[suffix]
            for suffix in suffix_order
            if suffix in by_suffix
        ]

    @classmethod
    def _artifact_input_checksums(cls, input_summaries):
        """Hash local input datasets without exposing their directories."""
        results = []
        seen_paths = set()
        for summary in input_summaries:
            source = str(summary.get("source") or "").split("|", 1)[0]
            if source.casefold().startswith("file://"):
                source = source[7:]
            source_path = Path(source)
            if not source_path.exists() or not source_path.is_file():
                continue
            resolved = str(source_path.resolve(strict=True)).casefold()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            if source_path.suffix.casefold() == ".shp":
                bundle_paths = cls._shapefile_bundle_paths(source_path)
            else:
                bundle_paths = [source_path]
            try:
                fingerprint = sha256_file_bundle(bundle_paths)
            except (OSError, ValueError):
                continue
            fingerprint["layer"] = summary.get("name")
            results.append(fingerprint)
        return results

    @staticmethod
    def _artifact_layer_content_hash(layer):
        """Hash normalized feature content independently of transient IDs."""
        field_names = [field.name() for field in layer.fields()]
        records = []
        for feature in layer.getFeatures():
            attributes = {
                name: _json_safe_attribute(feature[name])
                for name in field_names
            }
            try:
                normalized_geometry = QgsGeometry(feature.geometry())
                # GEOS normalization canonicalizes ring direction, ring start,
                # and multipart order so equivalent geometry has one content
                # digest even when a provider serializes its WKB differently.
                normalized_geometry.normalize()
                geometry_hash = hashlib.sha256(
                    bytes(normalized_geometry.asWkb())
                ).hexdigest()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                geometry_hash = hashlib.sha256(
                    feature.geometry().asWkt().encode("utf-8")
                ).hexdigest()
            stable_key = (
                attributes.get("SRC_UID")
                or attributes.get("NUMBER_KEY")
            )
            if not stable_key:
                stable_key = deterministic_content_hash(
                    {
                        "geometry_sha256": geometry_hash,
                        "attributes": attributes,
                    },
                    ignored_keys=(),
                )
            records.append({
                "key": str(stable_key),
                "geometry_sha256": geometry_hash,
                "attributes": attributes,
            })
        records.sort(key=lambda record: (
            record["key"],
            record["geometry_sha256"],
            json.dumps(
                record["attributes"],
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ),
        ))
        return deterministic_content_hash(records, ignored_keys=())

    @staticmethod
    def _artifact_runtime_environment():
        extra = {
            "qgis": getattr(Qgis, "QGIS_VERSION", "unknown"),
            "qgis_version_int": getattr(Qgis, "QGIS_VERSION_INT", None),
            "qt": getattr(QtCore, "QT_VERSION_STR", "unknown"),
        }
        try:
            from osgeo import gdal, ogr, osr

            extra["gdal"] = gdal.VersionInfo("RELEASE_NAME")
            extra["geos"] = "{}.{}.{}".format(
                ogr.GetGEOSVersionMajor(),
                ogr.GetGEOSVersionMinor(),
                ogr.GetGEOSVersionMicro(),
            )
            extra["proj"] = "{}.{}.{}".format(
                osr.GetPROJVersionMajor(),
                osr.GetPROJVersionMinor(),
                osr.GetPROJVersionMicro(),
            )
        except (ImportError, AttributeError, RuntimeError):
            extra.setdefault("gdal", "unknown")
            extra.setdefault("geos", "unknown")
            extra.setdefault("proj", "unknown")
        return python_runtime_environment(extra)

    def _artifact_output_layers(self, output_group):
        layers = []
        if output_group is None:
            return layers
        for node in output_group.findLayers():
            layer = node.layer()
            if layer is None or layer.type() != 0:
                continue
            parent = node.parent()
            kind = parent.name() if parent is not None else output_group.name()
            layers.append((layer, kind))
        return layers

    def _write_output_group_to_gpkg(self, output_group, target_path):
        """Write all vector results to a temporary GPKG, then replace atomically."""
        layers = self._artifact_output_layers(output_group)
        if not layers:
            raise RuntimeError("GeoPackage로 저장할 결과 레이어가 없습니다.")

        target_path = target_path.resolve(strict=False)
        temporary_path = target_path.with_name(
            f".{target_path.stem}.tmp.gpkg"
        )
        if temporary_path.exists():
            temporary_path.unlink()

        used_layer_names = set()
        exported = []
        try:
            for export_index, (layer, kind) in enumerate(layers):
                base_name = normalize_filename(
                    layer.name(),
                    fallback=f"layer_{export_index + 1}",
                    max_length=60,
                )
                layer_name = base_name
                suffix = 2
                while layer_name.casefold() in used_layer_names:
                    layer_name = normalize_filename(
                        f"{base_name}_{suffix}",
                        max_length=60,
                    )
                    suffix += 1
                used_layer_names.add(layer_name.casefold())

                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = "GPKG"
                options.fileEncoding = "UTF-8"
                options.layerName = layer_name
                options.actionOnExistingFile = (
                    QgsVectorFileWriter.CreateOrOverwriteFile
                    if export_index == 0
                    else QgsVectorFileWriter.CreateOrOverwriteLayer
                )
                result = QgsVectorFileWriter.writeAsVectorFormatV3(
                    layer,
                    str(temporary_path),
                    QgsProject.instance().transformContext(),
                    options,
                )
                error_code = result[0] if isinstance(result, tuple) else result
                if error_code != QgsVectorFileWriter.NoError:
                    detail = result[1] if isinstance(result, tuple) else result
                    raise RuntimeError(
                        f"{layer.name()} 저장 실패: {detail}"
                    )
                exported.append({
                    "name": layer.name(),
                    "gpkg_layer": layer_name,
                    "kind": kind,
                    "feature_count": layer.featureCount(),
                })

            os.replace(str(temporary_path), str(target_path))
            return exported
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def _unique_layout_name(self, base_name):
        manager = QgsProject.instance().layoutManager()
        name = base_name
        suffix = 2
        while manager.layoutByName(name) is not None:
            name = f"{base_name}_{suffix}"
            suffix += 1
        return name

    def _export_print_layout(
        self,
        settings,
        extent_geom,
        extent_crs,
        workflow,
        *,
        base_name,
        image_path=None,
        pdf_path=None,
    ):
        """Create one editable print layout and optionally export JPG/PDF."""
        if not extent_geom or extent_geom.isEmpty():
            raise RuntimeError("인쇄조판 도곽이 비어 있습니다.")
        if not extent_crs or not extent_crs.isValid():
            raise RuntimeError(
                "인쇄조판 도곽의 좌표계를 확인할 수 없습니다."
            )

        preservation = workflow == "preservation_area"
        width = float(
            settings.get(
                "preservation_paper_width" if preservation else "paper_width",
                210,
            )
        )
        height = float(
            settings.get(
                "preservation_paper_height" if preservation else "paper_height",
                297,
            )
        )
        scale = float(
            settings.get(
                "preservation_scale" if preservation else "scale",
                5000,
            )
        )
        if width <= 0 or height <= 0 or scale <= 0:
            raise RuntimeError("용지 크기와 축척은 0보다 커야 합니다.")

        project = QgsProject.instance()
        project_crs = project.crs()
        layout_crs = extent_crs
        map_geometry = QgsGeometry(extent_geom)
        if layout_crs != project_crs:
            self.log(
                "인쇄조판 CRS를 도곽 CRS로 고정합니다: "
                f"{layout_crs.authid()} "
                f"(프로젝트 CRS: {project_crs.authid()})"
            )

        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout_name = self._unique_layout_name(base_name)
        layout.setName(layout_name)
        page = layout.pageCollection().page(0)
        page.setPageSize(
            QgsLayoutSize(
                width,
                height,
                QgsUnitTypes.LayoutMillimeters,
            )
        )

        map_item = QgsLayoutItemMap(layout)
        layout.addLayoutItem(map_item)
        map_item.attemptMove(
            QgsLayoutPoint(
                0,
                0,
                QgsUnitTypes.LayoutMillimeters,
            )
        )
        map_item.attemptResize(
            QgsLayoutSize(
                width,
                height,
                QgsUnitTypes.LayoutMillimeters,
            )
        )
        # The paper size, scale and extent were calculated in extent_crs.
        # Keeping the map item in that same CRS prevents Web Mercator scale
        # distortion from shrinking the printable footprint.
        map_item.setCrs(layout_crs)
        map_item.setExtent(map_geometry.boundingBox())
        map_item.setScale(scale)
        map_item.setFrameEnabled(False)
        map_item.refresh()
        layout.refresh()
        project.layoutManager().addLayout(layout)

        exporter = QgsLayoutExporter(layout)
        exported_paths = []
        errors = []
        if image_path is not None:
            image_path = image_path.resolve(strict=False)
            temporary_image = image_path.with_name(
                f".{image_path.stem}.tmp{image_path.suffix}"
            )
            if temporary_image.exists():
                temporary_image.unlink()
            image_settings = QgsLayoutExporter.ImageExportSettings()
            image_settings.dpi = 300
            try:
                result = exporter.exportToImage(
                    str(temporary_image),
                    image_settings,
                )
                if result == QgsLayoutExporter.Success:
                    os.replace(str(temporary_image), str(image_path))
                    exported_paths.append(str(image_path))
                else:
                    errors.append(f"JPG 내보내기 오류 코드 {result}")
            finally:
                if temporary_image.exists():
                    temporary_image.unlink()
        if pdf_path is not None:
            pdf_path = pdf_path.resolve(strict=False)
            temporary_pdf = pdf_path.with_name(
                f".{pdf_path.stem}.tmp{pdf_path.suffix}"
            )
            if temporary_pdf.exists():
                temporary_pdf.unlink()
            pdf_settings = QgsLayoutExporter.PdfExportSettings()
            try:
                result = exporter.exportToPdf(
                    str(temporary_pdf),
                    pdf_settings,
                )
                if result == QgsLayoutExporter.Success:
                    os.replace(str(temporary_pdf), str(pdf_path))
                    exported_paths.append(str(pdf_path))
                else:
                    errors.append(f"PDF 내보내기 오류 코드 {result}")
            finally:
                if temporary_pdf.exists():
                    temporary_pdf.unlink()
        return {
            "layout_name": layout_name,
            "paths": exported_paths,
            "errors": errors,
            "paper_mm": [width, height],
            "scale": scale,
        }

    def _run_optional_outputs(
        self,
        settings,
        output_group,
        extent_geom,
        extent_crs,
        workflow,
        run_started_at,
    ):
        """Create user-selected archive and print artifacts after commit."""
        save_archive = bool(settings.get("save_gpkg_manifest", False))
        export_jpg = bool(settings.get("export_layout_jpg", False))
        export_pdf = bool(settings.get("export_layout_pdf", False))
        if not any((save_archive, export_jpg, export_pdf)):
            return {"paths": [], "errors": []}

        output_directory = str(
            settings.get("output_directory") or ""
        ).strip()
        if not output_directory:
            message = "선택 출력이 켜졌지만 저장 폴더가 비어 있습니다."
            self.log(f"⚠️ {message}")
            return {"paths": [], "errors": [message]}

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        workflow_label = (
            "매장유산유존지역"
            if workflow == "preservation_area"
            else "문화유적분포지도"
        )
        base_name = normalize_filename(
            f"ArchDistribution_{workflow_label}_{timestamp}"
        )
        output_layers = self._artifact_output_layers(output_group)
        output_summaries = [
            self._artifact_layer_summary(layer, kind=kind)
            for layer, kind in output_layers
        ]
        input_summaries = self._artifact_input_summaries(
            settings,
            workflow,
        )
        input_checksums = self._artifact_input_checksums(input_summaries)
        artifact_paths = []
        artifact_errors = []
        gpkg_layers = []
        manifest_path = None

        try:
            if save_archive:
                prepared = prepare_artifact_paths(
                    output_directory,
                    base_name,
                    include_gpkg=True,
                    include_manifest=True,
                    unique=True,
                )
                manifest_path = prepared["manifest"]
                try:
                    gpkg_layers = self._write_output_group_to_gpkg(
                        output_group,
                        prepared["gpkg"],
                    )
                    artifact_paths.append(str(prepared["gpkg"]))
                    self.log(
                        "GeoPackage 저장 완료: "
                        f"{prepared['gpkg']} ({len(gpkg_layers)}개 레이어)"
                    )
                except Exception as exc:
                    artifact_errors.append(f"GeoPackage: {exc}")
                    self.log(f"⚠️ GeoPackage 저장 실패: {exc}")

            if export_jpg or export_pdf:
                image_path = (
                    prepare_output_path(
                        output_directory,
                        base_name,
                        extension="jpg",
                        unique=True,
                    )
                    if export_jpg
                    else None
                )
                pdf_path = (
                    prepare_output_path(
                        output_directory,
                        base_name,
                        extension="pdf",
                        unique=True,
                    )
                    if export_pdf
                    else None
                )
                try:
                    layout_result = self._export_print_layout(
                        settings,
                        extent_geom,
                        extent_crs,
                        workflow,
                        base_name=base_name,
                        image_path=image_path,
                        pdf_path=pdf_path,
                    )
                    artifact_paths.extend(layout_result["paths"])
                    artifact_errors.extend(layout_result["errors"])
                    self.log(
                        "인쇄조판 생성 완료: "
                        f"{layout_result['layout_name']}"
                    )
                    for path in layout_result["paths"]:
                        self.log(f"  -> 출력: {path}")
                except Exception as exc:
                    artifact_errors.append(f"인쇄조판: {exc}")
                    self.log(f"⚠️ 인쇄조판 출력 실패: {exc}")

            if save_archive and manifest_path is not None:
                processing_stats = dict(
                    getattr(self, "_current_processing_stats", {})
                )
                public_artifacts = []
                output_hashes = []
                for artifact_path in artifact_paths:
                    path = Path(artifact_path)
                    if not path.exists() or not path.is_file():
                        continue
                    try:
                        digest = sha256_file(path)
                    except OSError:
                        continue
                    record = {
                        "filename": path.name,
                        "sha256": digest,
                        "size_bytes": path.stat().st_size,
                    }
                    public_artifacts.append(record)
                    output_hashes.append(record)
                layer_hashes = [
                    {
                        "layer": layer.name(),
                        "content_sha256": self._artifact_layer_content_hash(
                            layer
                        ),
                    }
                    for layer, _kind in output_layers
                ]
                output_hashes.extend(layer_hashes)
                processing_stats.update({
                    # Runtime callers retain usable artifact paths; manifest
                    # schema v2 strips them to public-safe filename/hash rows.
                    "artifacts": list(artifact_paths),
                    "artifact_errors": artifact_errors,
                    "gpkg_layers": gpkg_layers,
                })
                manifest_processing_stats = dict(processing_stats)
                manifest_processing_stats["artifacts"] = public_artifacts
                build_info = read_build_info(self.plugin_dir)
                metric_context = getattr(
                    self,
                    "_current_metric_context",
                    None,
                )
                manifest = build_run_manifest(
                    plugin_version=get_plugin_version(),
                    git_commit=build_info.get("git_commit"),
                    workflow=workflow,
                    settings=settings,
                    input_layers=input_summaries,
                    output_layers=output_summaries,
                    processing_stats=manifest_processing_stats,
                    decision_reuse_count=int(
                        processing_stats.get(
                            "decision_reuse_count",
                            0,
                        )
                    ),
                    status=(
                        "partial_success"
                        if (
                            artifact_errors
                            or processing_stats.get("excluded_layers")
                            or processing_stats.get("processing_warnings")
                        )
                        else "success"
                    ),
                    started_at=run_started_at,
                    finished_at=datetime.now().astimezone(),
                    ruleset=matching_rules_metadata(),
                    runtime_environment=(
                        self._artifact_runtime_environment()
                    ),
                    crs_context=(
                        metric_context.provenance()
                        if metric_context is not None else None
                    ),
                    input_checksums=input_checksums,
                    output_hashes=output_hashes,
                    decision_cache=self._decision_cache_provenance(),
                    excluded_layers=processing_stats.get(
                        "excluded_layers",
                        [],
                    ),
                    public_manifest=True,
                )
                save_manifest_atomic(manifest, manifest_path)
                artifact_paths.append(str(manifest_path))
                self.log(f"실행정보 저장 완료: {manifest_path}")
        except Exception as exc:
            # These are optional post-commit artifacts. The successful QGIS
            # result group must remain available even if a filesystem or
            # exporter error occurs.
            artifact_errors.append(f"선택 결과 저장: {exc}")
            self.log(f"⚠️ 선택 결과 저장 중 오류: {exc}")

        if artifact_errors:
            self.log(
                "선택 출력 일부를 만들지 못했습니다: "
                + " | ".join(artifact_errors)
            )
        return {
            "paths": artifact_paths,
            "errors": artifact_errors,
        }

    def _write_terminal_manifest(
        self,
        settings,
        workflow,
        run_started_at,
        status,
        error=None,
    ):
        """Persist cancelled/failed run evidence without creating map output."""
        if not settings.get("save_gpkg_manifest", False):
            return None
        output_directory = str(settings.get("output_directory") or "").strip()
        if not output_directory:
            return None
        try:
            label = (
                "매장유산유존지역"
                if workflow == "preservation_area"
                else "문화유적분포지도"
            )
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            path = prepare_output_path(
                output_directory,
                f"ArchDistribution_{label}_{status}_{timestamp}_run",
                extension="json",
                unique=True,
            )
            inputs = self._artifact_input_summaries(settings, workflow)
            statistics = dict(
                getattr(self, "_current_processing_stats", {})
            )
            metric_context = getattr(
                self, "_current_metric_context", None
            )
            build_info = read_build_info(self.plugin_dir)
            manifest = build_run_manifest(
                plugin_version=get_plugin_version(),
                git_commit=build_info.get("git_commit"),
                workflow=workflow,
                settings=settings,
                input_layers=inputs,
                output_layers=[],
                processing_stats=statistics,
                decision_reuse_count=int(
                    statistics.get("decision_reuse_count", 0)
                ),
                status=status,
                error=error,
                started_at=run_started_at,
                finished_at=datetime.now().astimezone(),
                ruleset=matching_rules_metadata(),
                runtime_environment=self._artifact_runtime_environment(),
                crs_context=(
                    metric_context.provenance()
                    if metric_context is not None else None
                ),
                input_checksums=self._artifact_input_checksums(inputs),
                output_hashes=[],
                decision_cache=self._decision_cache_provenance(),
                excluded_layers=statistics.get("excluded_layers", []),
                public_manifest=True,
            )
            save_manifest_atomic(manifest, path)
            self.log(f"{status} 실행정보 저장 완료: {path}")
            return path
        except Exception as manifest_error:
            self.log(f"⚠️ 종료 실행정보 저장 실패: {manifest_error}")
            return None

    @classmethod
    def _layer_file_path(cls, layer):
        if not layer:
            return None
        source = str(layer.source() or "").split("|", 1)[0]
        if source.casefold().startswith("file://"):
            source = source[7:]
        if not source:
            return None
        path = Path(source)
        if path.suffix.casefold() in {".shx", ".dbf"}:
            path = next(
                (
                    candidate
                    for candidate in cls._shapefile_bundle_paths(path)
                    if candidate.suffix.casefold() == ".shp"
                ),
                path.with_suffix(".shp"),
            )
        return path if path.exists() else None

    @classmethod
    def _declared_layer_encoding(cls, layer):
        """Respect an explicit override, .cpg, then the provider setting."""
        override = str(
            layer.customProperty(ENCODING_OVERRIDE_PROPERTY, "") or ""
        ).strip()
        if override:
            return override, "layer_override"

        source_path = cls._layer_file_path(layer)
        if source_path and source_path.suffix.casefold() == ".shp":
            cpg_path = next(
                (
                    candidate
                    for candidate in cls._shapefile_bundle_paths(source_path)
                    if candidate.suffix.casefold() == ".cpg"
                ),
                None,
            )
            if cpg_path is not None:
                try:
                    declared = cpg_path.read_text(
                        encoding="ascii",
                        errors="ignore",
                    ).strip()
                except OSError:
                    declared = ""
                if declared:
                    aliases = {
                        "949": LEGACY_KOREAN_ENCODING,
                        "CP-949": LEGACY_KOREAN_ENCODING,
                        "EUC_KR": "EUC-KR",
                        "UTF8": "UTF-8",
                    }
                    return aliases.get(declared.upper(), declared), ".cpg"

        try:
            provider_encoding = str(layer.dataProvider().encoding() or "").strip()
        except (AttributeError, RuntimeError):
            provider_encoding = ""
        return (provider_encoding, "provider") if provider_encoding else (None, "default")

    @classmethod
    def _preservation_number_scope(
        cls,
        layer,
        *,
        supplier_site_id=None,
        supplier_id_field=None,
        site_name=None,
        heritage_name=None,
        address=None,
    ):
        """Build a conservative map-number identity for preservation areas.

        Only a field whose *exact schema name* denotes a site identifier may
        supply the primary key.  A generic ``CODE`` column is deliberately not
        accepted because it is commonly an action/category code.  When no such
        identifier exists, both a non-generic site name and a meaningful exact
        address are required.  The scope controls only the displayed number;
        it never asserts archaeological identity or dissolves source geometry.
        """
        supplier_key = canonical_heritage_text(supplier_site_id)
        field_key = cls._preservation_site_id_field_token(supplier_id_field)
        if supplier_key and field_key in cls._preservation_site_id_tokens():
            return f"supplier:{field_key}:{supplier_key}"

        display_name = heritage_name or site_name
        site_family, _has_area = strip_trailing_area_designator(display_name)
        site_key = canonical_heritage_text(site_family)
        address_key = canonical_heritage_text(address)
        if (
            len(site_key) < 3
            or is_generic_name(site_family)
            or not cls._is_meaningful_preservation_address(address_key)
        ):
            return None
        return f"name_address:{site_key}|{address_key}"

    @staticmethod
    def _preservation_site_id_field_token(field_name):
        """Normalize a field name without turning substrings into matches."""
        return (
            canonical_heritage_text(field_name)
            .replace("_", "")
            .replace("-", "")
        )

    @staticmethod
    def _preservation_site_id_tokens():
        """Exact supplier fields accepted as preservation-site identifiers."""
        return {
            "유산코드",
            "문화유산코드",
            "유적코드",
            "유적id",
            "유적아이디",
            "heritagecode",
            "heritageid",
            "heritagecd",
            "sitecode",
            "siteid",
            "sitecd",
        }

    @classmethod
    def find_preservation_site_id_field(cls, layer):
        """Return an exact semantic site-ID field, never a generic CODE field."""
        if not layer or layer.type() != 0:
            return None
        accepted = cls._preservation_site_id_tokens()
        for field in layer.fields():
            if cls._preservation_site_id_field_token(field.name()) in accepted:
                return field.name()
        return None

    @staticmethod
    def _is_meaningful_preservation_address(address_key):
        """Reject missing and low-information address placeholders."""
        if not address_key:
            return False
        if address_key in {
            "0",
            "00",
            "불명",
            "주소불명",
            "주소미상",
            "해당없음",
            "미입력",
        }:
            return False
        informative = [char for char in address_key if char.isalnum()]
        return len(informative) >= 2 and len(set(informative)) >= 2

    def fix_layer_encoding(self, layer, encoding=None):
        """Apply only an explicit or source-declared encoding.

        Earlier releases forced CP949 onto every vector source.  That corrupted
        UTF-8/GPKG inputs and discarded in-memory provider state.  This helper
        now honours QGIS, .cpg, or an explicit per-layer override.
        """
        if not layer or layer.type() != 0:
            return None
        selected = str(encoding or "").strip()
        basis = "explicit"
        if not selected:
            selected, basis = self._declared_layer_encoding(layer)
        if not selected:
            self.log(f"  -> 인코딩은 공급자 기본값 유지: {layer.name()}")
            return None
        try:
            current = str(layer.dataProvider().encoding() or "").strip()
            if current.casefold() != selected.casefold():
                layer.setProviderEncoding(selected)
                layer.dataProvider().setEncoding(selected)
                layer.dataProvider().reloadData()
                layer.updateFields()
                layer.triggerRepaint()
            self.log(
                f"  -> 인코딩: {selected} ({basis}, {layer.name()})"
            )
            return selected
        except (AttributeError, RuntimeError) as exc:
            self.log(
                f"⚠️ 인코딩 적용 실패, 기존 공급자 상태 유지: "
                f"{layer.name()} ({exc})"
            )
            self._record_processing_warning(
                layer,
                "encoding_application_failed_provider_retained",
            )
            return None

    def merge_and_style_topo(self, layer_ids, target_group, src_group, style):
        """Merge selected topo layers and apply custom style."""
        layers = []
        for lid in layer_ids:
            layer = QgsProject.instance().mapLayer(lid)
            if layer:
                # [FIX] Filter for Line Layers Only (Topo is usually lines)
                if layer.geometryType() != 1:  # 0:Point, 1:Line, 2:Polygon
                    self.log(f"  ⚠️ 지형도 병합 제외 (라인 레이어 아님): {layer.name()}")
                    self._record_excluded_layer(
                        layer,
                        "topographic_non_line_geometry",
                        role="topographic_map",
                    )
                    continue

                self.fix_layer_encoding(layer)
                layers.append(layer)
                self.move_layer_to_group(layer, src_group)

        if not layers:
            self.log("  ⚠️ 병합할 수치지형도(라인)가 없습니다.")
            return

        # Merge
        params = {
            'LAYERS': layers,
            'CRS': layers[0].crs(),
            'OUTPUT': 'memory:Merged_Topo'
        }
        result = processing.run("native:mergevectorlayers", params)
        merged_layer = result['OUTPUT']
        merged_layer.setName("수치지형도_병합")

        # Boundary filtering (H0017334)
        boundary_code = TOPO_BOUNDARY_EXCLUDE_CODE
        fields = [f.name() for f in merged_layer.fields()]
        target_field = None
        for f in fields:
            if f.upper() in ['LAYER', 'REFNAME', 'NAME']:
                target_field = f
                break

        if target_field:
            expr = f"\"{target_field}\" = '{boundary_code}'"
            merged_layer.startEditing()
            ids_to_delete = [f.id() for f in merged_layer.getFeatures(QgsFeatureRequest().setFilterExpression(expr))]
            if ids_to_delete:
                merged_layer.deleteFeatures(ids_to_delete)
            merged_layer.commitChanges()

        # Styling
        symbol = QgsLineSymbol.createSimple({
            'color': style['stroke_color'],
            'width': str(style['stroke_width']),
            'width_unit': 'MM'
        })
        renderer = QgsSingleSymbolRenderer(symbol)
        merged_layer.setRenderer(renderer)
        merged_layer.triggerRepaint()

        QgsProject.instance().addMapLayer(merged_layer, False)
        target_group.addLayer(merged_layer)

    def create_buffer(self, layer, distance, group, style):
        crs = layer.crs() if layer else None
        if (
            not crs
            or not crs.isValid()
            or crs.isGeographic()
            or crs.mapUnits() != QgsUnitTypes.DistanceMeters
        ):
            raise MetricContextError(
                "버퍼 입력은 미터 단위 분석 CRS 레이어여야 합니다."
            )
        params = {
            'INPUT': layer,
            'DISTANCE': distance,
            'SEGMENTS': PROCESSING_BUFFER_SEGMENTS,
            'DISSOLVE': False,
            'OUTPUT': 'memory:Buffer_' + str(distance)
        }
        result = processing.run("native:buffer", params)
        buffer_layer = result['OUTPUT']
        use_km = bool(style.get("format_km_labels", False))
        display_label = format_buffer_label(distance, use_km)
        buffer_layer.setName(f"Buffer_{display_label}")

        # A processing buffer inherits every source field. Those attributes do
        # not describe the buffer and make the output needlessly noisy, so keep
        # only the actual distance in metres. The visible label is generated
        # from this value and does not need another attribute column.
        provider = buffer_layer.dataProvider()
        inherited_field_indexes = list(range(len(buffer_layer.fields())))
        if inherited_field_indexes:
            provider.deleteAttributes(inherited_field_indexes)
            buffer_layer.updateFields()
        provider.addAttributes([
            QgsField("DIST_M", QVariant.Double, "double", 20, 3),
        ])
        buffer_layer.updateFields()
        distance_field_index = buffer_layer.fields().indexOf("DIST_M")
        attribute_changes = {
            feature.id(): {
                distance_field_index: float(distance),
            }
            for feature in buffer_layer.getFeatures()
        }
        if attribute_changes:
            provider.changeAttributeValues(attribute_changes)

        # Apply outline-only style with custom color and dash pattern
        # User requested: Solid, Dot, Dash (indices 0, 1, 2)
        pen_styles = ['solid', 'dot', 'dash']
        target_style = pen_styles[style['style']] if style['style'] < len(pen_styles) else 'solid'

        symbol = QgsFillSymbol.createSimple({
            'color': '0,0,0,0',  # Transparent fill
            'outline_color': style['color'],
            'outline_width': str(style['width']),  # User defined width
            'outline_style': target_style
        })
        buffer_layer.setRenderer(QgsSingleSymbolRenderer(symbol))

        label_settings = QgsPalLayerSettings()
        label_settings.enabled = True
        label_settings.isExpression = True
        label_settings.fieldName = "'{}'".format(
            display_label.replace("'", "''")
        )
        label_settings.placement = QgsPalLayerSettings.PerimeterCurved

        text_format = QgsTextFormat()
        font = QFont(DEFAULT_LABEL_FONT_FAMILY)
        font.setPointSize(9)
        text_format.setFont(font)
        text_format.setColor(QColor(style['color']))
        label_settings.setFormat(text_format)

        buffer_layer.setLabeling(
            QgsVectorLayerSimpleLabeling(label_settings)
        )
        buffer_layer.setLabelsEnabled(True)
        buffer_layer.triggerRepaint()

        QgsProject.instance().addMapLayer(buffer_layer, False)
        group.addLayer(buffer_layer)
        return buffer_layer

    def get_study_area_centroid(self, layer):
        """Calculate the center of the study area layer extent (Fast and Robust)."""
        extent = layer.extent()
        if extent.isEmpty() or not extent.isFinite():
            # Try getting feature count
            if layer.featureCount() == 0:
                return None
            # Fallback to manual combine if extent is weird
            combined_geom = QgsGeometry()
            for feat in layer.getFeatures():
                if feat.hasGeometry():
                    if combined_geom.isNull():
                        combined_geom = feat.geometry()
                    else:
                        combined_geom = combined_geom.combine(feat.geometry())
            if combined_geom.isNull():
                return None
            pt = combined_geom.centroid().asPoint()
            return QgsPointXY(pt.x(), pt.y())

        return extent.center()

    def calculate_extent_geometry(self, centroid, width_mm, height_mm, scale):
        """Calculate the extent geometry (rectangle) without creating a layer."""
        if not centroid:
            return None

        # Real world dimensions in meters
        width_m = (width_mm / 1000.0) * scale
        height_m = (height_mm / 1000.0) * scale

        half_w = width_m / 2.0
        half_h = height_m / 2.0

        # Create corners
        p1 = QgsPointXY(centroid.x() - half_w, centroid.y() + half_h)  # Top Left
        p2 = QgsPointXY(centroid.x() + half_w, centroid.y() + half_h)  # Top Right
        p3 = QgsPointXY(centroid.x() + half_w, centroid.y() - half_h)  # Bottom Right
        p4 = QgsPointXY(centroid.x() - half_w, centroid.y() - half_h)  # Bottom Left

        return QgsGeometry.fromPolygonXY([[p1, p2, p3, p4, p1]])

    def create_extent_polygon(self, centroid, width_mm, height_mm, scale, group, crs):
        """Create a rectangle polygon based on paper size and scale."""
        rect_geom = self.calculate_extent_geometry(centroid, width_mm, height_mm, scale)
        if not rect_geom:
            return None

        if not crs or not crs.isValid():
            raise MetricContextError(
                "도곽을 만들 수 없습니다. 분석 CRS가 없거나 유효하지 않습니다."
            )
        if crs.isGeographic() or crs.mapUnits() != QgsUnitTypes.DistanceMeters:
            raise MetricContextError(
                "도곽 CRS는 미터 단위 투영좌표계여야 합니다."
            )

        # The geometry was calculated in metres, so its layer must use the
        # exact analysis CRS.  Never relabel coordinates with a fallback CRS.
        vl = QgsVectorLayer(f"Polygon?crs={crs.toWkt()}", "도곽_Extent", "memory")
        if not vl.isValid():
            raise MetricContextError(
                "분석 CRS로 도곽 레이어를 만들지 못했습니다."
            )

        # Explicit outline-only styling
        symbol = QgsFillSymbol.createSimple({
            'color': '0,0,0,0',  # No fill
            'outline_color': '0,0,0,255',  # Black outline
            'outline_width': '0.3'
        })
        vl.setRenderer(QgsSingleSymbolRenderer(symbol))

        pr = vl.dataProvider()
        feat = QgsFeature()
        feat.setGeometry(rect_geom)
        pr.addFeatures([feat])
        vl.updateExtents()

        QgsProject.instance().addMapLayer(vl, False)
        group.addLayer(vl)
        return rect_geom

    def apply_study_style(self, layer, style):
        """Apply outline style to study area."""
        symbol = None
        if layer.geometryType() == 2:  # Polygon
            symbol = QgsFillSymbol.createSimple({
                'color': '0,0,0,0',  # Transparent fill
                'outline_color': style['stroke_color'],
                'outline_width': str(style['stroke_width']),
                'outline_width_unit': 'MM'
            })
        elif layer.geometryType() == 1:  # Line
            symbol = QgsLineSymbol.createSimple({
                'color': style['stroke_color'],
                'width': str(style['stroke_width']),
                'width_unit': 'MM'
            })

        if symbol:
            renderer = QgsSingleSymbolRenderer(symbol)
            layer.setRenderer(renderer)
            layer.triggerRepaint()

    def find_field(self, layer, keywords):
        """Find a field name by looking for keywords (case-insensitive fuzzy match)."""
        fields = [f.name() for f in layer.fields()]
        for k in keywords:
            for f in fields:
                if k.upper() in f.upper():
                    return f
        return None

    def find_preservation_action_field(self, layer):
        """
        Detect a buried-heritage preservation-area layer by schema and values.

        A matching field name alone is not enough: at least one official action
        value must be present. This prevents unrelated generic ACTION fields from
        changing grouping or symbology.
        """
        if not layer or layer.type() != 0 or layer.geometryType() != 2:
            return None

        field_names = [field.name() for field in layer.fields()]
        candidates = []
        for keyword in PRESERVATION_ACTION_FIELD_CANDIDATES:
            for field_name in field_names:
                if keyword.casefold() in field_name.casefold():
                    if field_name not in candidates:
                        candidates.append(field_name)

        for field_name in candidates:
            field_idx = layer.fields().indexFromName(field_name)
            if field_idx < 0:
                continue
            recognized = recognized_preservation_actions(
                layer.uniqueValues(field_idx)
            )
            if recognized:
                return field_name
        return None

    @staticmethod
    def _canonical_source_records(records):
        """Deduplicate and order source records for deterministic provenance."""
        keyed = {}
        for record in records:
            safe_record = (
                record
                if isinstance(record, dict)
                else {"unparsed_source": str(record)}
            )
            canonical = json.dumps(
                safe_record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            keyed[canonical] = safe_record
        return [keyed[key] for key in sorted(keyed)]

    def aggregate_source_metadata(self, layer):
        """Attach every source record in a numbering group to each styled part."""
        number_key_idx = layer.fields().indexFromName("NUMBER_KEY")
        count_idx = layer.fields().indexFromName("SRC_COUNT")
        json_idx = layer.fields().indexFromName("SRC_JSON")
        if min(number_key_idx, count_idx, json_idx) < 0:
            return

        group_records = {}
        group_feature_ids = {}
        for feat in layer.getFeatures():
            key = str(feat[number_key_idx] or f"feature:{feat.id()}")
            group_feature_ids.setdefault(key, []).append(feat.id())
            raw_payload = feat[json_idx]
            try:
                records = json.loads(raw_payload) if raw_payload else []
            except (TypeError, ValueError, json.JSONDecodeError):
                records = [{"unparsed_source": str(raw_payload)}]
            if isinstance(records, dict):
                records = [records]
            group_records.setdefault(key, []).extend(records)

        layer.startEditing()
        for key, feature_ids in group_feature_ids.items():
            records = self._canonical_source_records(
                group_records.get(key, [])
            )
            payload = json.dumps(
                records,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            for feature_id in feature_ids:
                layer.changeAttributeValue(feature_id, count_idx, len(records))
                layer.changeAttributeValue(feature_id, json_idx, payload)
        layer.commitChanges()

    def aggregate_source_metadata_layers(self, layers):
        """Aggregate provenance across geometry families sharing a number."""
        groups = {}
        members = {}
        for layer in layers:
            number_idx = layer.fields().indexFromName("NUMBER_KEY")
            count_idx = layer.fields().indexFromName("SRC_COUNT")
            json_idx = layer.fields().indexFromName("SRC_JSON")
            if min(number_idx, count_idx, json_idx) < 0:
                continue
            for feature in layer.getFeatures():
                key = str(
                    feature[number_idx]
                    or f"{layer.id()}:feature:{feature.id()}"
                )
                members.setdefault(key, []).append((
                    layer,
                    feature.id(),
                    count_idx,
                    json_idx,
                ))
                raw_payload = feature[json_idx]
                try:
                    records = json.loads(raw_payload) if raw_payload else []
                except (TypeError, ValueError, json.JSONDecodeError):
                    records = [{"unparsed_source": str(raw_payload)}]
                if isinstance(records, dict):
                    records = [records]
                groups.setdefault(key, []).extend(records)

        updates = {}
        for key, feature_members in members.items():
            records = self._canonical_source_records(groups.get(key, []))
            payload = json.dumps(
                records,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            for layer, feature_id, count_idx, json_idx in feature_members:
                state = updates.setdefault(layer.id(), {
                    "layer": layer,
                    "values": [],
                })
                state["values"].append((
                    feature_id,
                    count_idx,
                    json_idx,
                    len(records),
                    payload,
                ))

        for state in updates.values():
            layer = state["layer"]
            layer.startEditing()
            for (
                feature_id,
                count_idx,
                json_idx,
                record_count,
                payload,
            ) in state["values"]:
                layer.changeAttributeValue(feature_id, count_idx, record_count)
                layer.changeAttributeValue(feature_id, json_idx, payload)
            layer.commitChanges()

    def load_reference_data(self):
        """Load reference data for filtering."""
        import json
        json_path = os.path.join(self.plugin_dir, 'reference_data.json')
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    self.reference_data = json.load(f)
            except Exception:
                self.reference_data = {}
        else:
            self.reference_data = {}

        # [NEW] Load Smart Patterns for Override
        json_pattern_path = os.path.join(os.path.dirname(__file__), 'smart_patterns.json')
        self.smart_patterns = {"noise": [], "artifacts": {}}
        if os.path.exists(json_pattern_path):
            try:
                with open(json_pattern_path, 'r', encoding='utf-8') as f:
                    self.smart_patterns = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                self.log(f"스마트 패턴 로드 실패, 기본값 사용: {exc}")

    def should_exclude(self, name, filter_items):
        """
        Check if feature should be excluded based on name look-up.
        filter_items: List of allowed strings e.g. ["ERA:고려", "TYPE:고분"]
        If filter_items is None, Allow all.
        """
        if filter_items is None:
            return False  # No filtering

        # Load data if not loaded
        if not hasattr(self, 'reference_data'):
            self.load_reference_data()

        if name not in self.reference_data:
            return False  # Unknown items are allowed by default (or denied? Let's allow for safety)

        info = self.reference_data[name]
        era_key = f"ERA:{info['e']}"
        type_key = f"TYPE:{info['t']}"

        # [NEW] Keyword Override Logic
        # Prioritize keyword inference over DB value if a match exists.
        # This solves the "Temple Site containing Stone Buddha" issue.
        effective_type = info['t']
        if hasattr(self, 'smart_patterns'):
            refinements = self.smart_patterns.get('artifacts', {})
            for key, val in refinements.items():
                if key in name:
                    effective_type = val
                    break  # Use the first matching keyword

        type_key = f"TYPE:{effective_type}"

        # Logic:
        # If the item has an Era, and that Era is NOT in the allowed list -> Exclude
        # If the item has a Type, and that Type is NOT in the allowed list -> Exclude
        # Wait, if I uncheck "Era: Goryeo", then Goryeo items should be gone.
        # But what if I uncheck "Type: Tomb"? Then Tomb items gone.
        # Basically, we need to check if the specific Era tag is present in filter_items (if applicable)
        # AND if the specific Type tag is present in filter_items (if applicable).

        # However, we only emitted tags that were found.
        # So we can just check: IS the ERA present in the allowed list?

        # Complication: filter_items contains only CHECKED items.
        # So if era_key is valid (not an unknown era marker) and NOT in filter_items -> Exclude.

        if info['e'] and info['e'] != "시대미상":
            # Does the user care about eras? (i.e. are there any ERA tags in the list?)
            # We can assume if filter_items provided, we enforce it.
            # We need to know if "ERA:Goryeo" was presented to the user?
            # Actually, simpler: if filter_items is passed, it represents the ALLOW LIST of properties.
            # But if "ERA:Goryeo" was never in the list (not found in scan), we shouldn't block it?
            # The Dialog only adds found items.
            # So if it was found, it must be in the list?
            # Correct.

            # Optimization: We assume the Dialog passed ONLY the checked items.
            # But we also need to know if the Era was even *candidate* for filtering.
            # If "Goryeo" wasn't in the input layers, it wouldn't be in the list.
            # But here we are processing features. If this feature is Goryeo, then "ERA:Goryeo" WOULD have been found by scan?
            # YES, because we scan the same layers.

            if era_key not in filter_items:
                # Check if this era key was actually available to be unchecked?
                # If we rely on the list containing ONLY checked items, then missing item = unchecked.
                return True

        if info['t'] and info['t'] != "기타":
            if type_key not in filter_items:
                return True

        return False

    def keyword_inference(self, name):
        """Infer category from name."""
        if not name:
            return "기타"

        # Priority mapping
        if any(k in name for k in ["고분", "분묘", "묘", "총", "릉"]):
            return "분묘"
        if any(k in name for k in ["산성", "성", "진", "보", "루"]):
            return "성곽"
        if any(k in name for k in ["요지", "가마", "생산"]):
            return "생산유적"
        if any(k in name for k in ["주거", "취락", "마을", "생활"]):
            return "생활유적"
        if any(k in name for k in ["사지", "불상", "탑", "비", "당간"]):
            return "불교/장묘"

        return "기타"

    def _memory_layer_like(self, source, name, predicate):
        """Copy matching features to a memory layer without altering source."""
        geometry_name = {
            0: "Point",
            1: "LineString",
            2: "Polygon",
        }.get(source.geometryType(), "None")
        if geometry_name == "None":
            uri = "None"
        else:
            crs_value = source.crs().authid() or source.crs().toWkt()
            uri = f"{geometry_name}?crs={crs_value}"

        output = QgsVectorLayer(uri, name, "memory")
        provider = output.dataProvider()
        provider.addAttributes(source.fields())
        output.updateFields()

        copied = []
        for feature in source.getFeatures():
            if not predicate(feature):
                continue
            clone = QgsFeature(output.fields())
            clone.setGeometry(QgsGeometry(feature.geometry()))
            clone.setAttributes(feature.attributes())
            copied.append(clone)
        if copied:
            provider.addFeatures(copied)
        output.updateExtents()
        return output

    def _create_match_audit_layer(self, candidates):
        """Build a non-spatial, exportable audit table."""
        layer = QgsVectorLayer("None", "중복_판정_검수표", "memory")
        fields = [
            QgsField("A_ID", QVariant.String),
            QgsField("A_ROLE", QVariant.String),
            QgsField("A_NAME", QVariant.String),
            QgsField("B_ID", QVariant.String),
            QgsField("B_ROLE", QVariant.String),
            QgsField("B_NAME", QVariant.String),
            QgsField("PAIR_KIND", QVariant.String),
            QgsField("CONFIDENCE", QVariant.String),
            QgsField("SCORE", QVariant.Double),
            QgsField("OVERLAP", QVariant.Double),
            QgsField("COVER_A", QVariant.Double),
            QgsField("COVER_B", QVariant.Double),
            QgsField("IOU", QVariant.Double),
            QgsField("AREA_RATIO", QVariant.Double),
            QgsField("DIST_M", QVariant.Double),
            QgsField("CENTROID_M", QVariant.Double),
            QgsField("BOUNDARY_M", QVariant.Double),
            QgsField("GEOM_PAIR", QVariant.String),
            QgsField("REL_TYPE", QVariant.String),
            QgsField("RULE", QVariant.String),
            QgsField("DECISION", QVariant.String),
            QgsField("DEC_SOURCE", QVariant.String),
            QgsField("REP_ID", QVariant.String),
        ]
        provider = layer.dataProvider()
        provider.addAttributes(fields)
        layer.updateFields()

        rows = []
        for candidate in candidates:
            feature = QgsFeature(layer.fields())
            feature["A_ID"] = candidate.get("left_uid")
            feature["A_ROLE"] = candidate.get("left_role")
            feature["A_NAME"] = candidate.get("left_name")
            feature["B_ID"] = candidate.get("right_uid")
            feature["B_ROLE"] = candidate.get("right_role")
            feature["B_NAME"] = candidate.get("right_name")
            feature["PAIR_KIND"] = candidate.get("pair_kind")
            feature["CONFIDENCE"] = candidate.get("confidence")
            feature["SCORE"] = candidate.get("score")
            feature["OVERLAP"] = candidate.get("overlap_ratio")
            feature["COVER_A"] = candidate.get("coverage_left")
            feature["COVER_B"] = candidate.get("coverage_right")
            feature["IOU"] = candidate.get("iou")
            feature["AREA_RATIO"] = candidate.get("area_ratio")
            feature["DIST_M"] = candidate.get("distance")
            feature["CENTROID_M"] = candidate.get("centroid_distance")
            feature["BOUNDARY_M"] = candidate.get("boundary_distance")
            feature["GEOM_PAIR"] = candidate.get("geometry_pair")
            feature["REL_TYPE"] = candidate.get("relation_type")
            feature["RULE"] = candidate.get("rule")
            feature["DECISION"] = candidate.get("decision")
            feature["DEC_SOURCE"] = candidate.get("decision_source")
            feature["REP_ID"] = candidate.get("representative_uid")
            rows.append(feature)
        if rows:
            provider.addFeatures(rows)
        return layer

    @staticmethod
    def _relation_key(left_uid, right_uid):
        pair = "|".join(sorted((str(left_uid), str(right_uid))))
        digest = hashlib.sha1(pair.encode("utf-8")).hexdigest()[:16]
        return f"rel:{digest}"

    @staticmethod
    def _geometry_boundary_distance(left_geometry, right_geometry):
        """Measure boundary-to-boundary distance on QGIS 3.28+.

        ``QgsGeometry.boundary()`` was added after some supported QGIS
        releases.  The abstract geometry API exposes the same operation on
        older LTR builds, so contained polygons no longer collapse to a
        misleading zero geometry distance.
        """
        try:
            left_boundary = left_geometry.boundary()
            right_boundary = right_geometry.boundary()
        except AttributeError:
            left_raw = left_geometry.constGet().boundary()
            right_raw = right_geometry.constGet().boundary()
            if left_raw is None or right_raw is None:
                return left_geometry.distance(right_geometry)
            left_boundary = QgsGeometry(left_raw.clone())
            right_boundary = QgsGeometry(right_raw.clone())
        if left_boundary.isEmpty() or right_boundary.isEmpty():
            return left_geometry.distance(right_geometry)
        return left_boundary.distance(right_boundary)

    @staticmethod
    def _protection_name_key(value):
        name = canonical_name(value)
        for suffix in (
            "국가유산보호구역",
            "문화유산보호구역",
            "문화재보호구역",
            "보호구역",
        ):
            suffix_key = canonical_name(suffix)
            if name.endswith(suffix_key):
                name = name[:-len(suffix_key)]
                break
        return name

    @staticmethod
    def _designation_family_hint(source_name):
        text = str(source_name or "").replace(" ", "").replace("·", "")
        if "국가지정" in text or "국가등록" in text:
            return "national"
        if "시도지정" in text or "시도등록" in text:
            return "local"
        return None

    @classmethod
    def _protection_link_compatible(cls, protection, designated):
        """Require evidence beyond a code before linking a legal boundary."""
        protection_name = cls._protection_name_key(protection.get("name"))
        designated_name = cls._protection_name_key(designated.get("name"))
        if protection_name and protection_name == designated_name:
            return True
        family_hint = cls._designation_family_hint(
            protection.get("source")
        )
        target_family = (
            "national"
            if str(designated.get("role", "")).startswith("national_")
            else "local"
            if str(designated.get("role", "")).startswith("local_")
            else None
        )
        return bool(family_hint and family_hint == target_family)

    @staticmethod
    def _matching_policy_key(preset):
        metadata = matching_rules_metadata()
        return ":".join((
            MATCH_POLICY_VERSION,
            str(preset),
            str(metadata.get("ruleset_version") or "unknown"),
            str(metadata.get("sha256") or "unknown"),
        ))

    def apply_source_aware_matching(
        self,
        layer,
        preset=PRESET_BALANCED,
        decision_provider=None,
        decision_store=None,
        reuse_saved_decisions=True,
        policy_version=None,
    ):
        """Find candidates with a spatial index, review them, and apply decisions."""
        policy_version = (
            str(policy_version)
            if policy_version
            else self._matching_policy_key(preset)
        )
        # Migrate 1.0.5 result layers created before the research schema was
        # introduced.  ENTITY_KEY remains the source of the compatibility
        # alias; no identity decision is inferred here.
        entity_index = layer.fields().indexFromName("ENTITY_KEY")
        if layer.fields().indexFromName("SITE_ENTITY_KEY") < 0:
            layer.dataProvider().addAttributes([
                QgsField("SITE_ENTITY_KEY", QVariant.String)
            ])
            layer.updateFields()
            site_index = layer.fields().indexFromName("SITE_ENTITY_KEY")
            if entity_index >= 0:
                layer.startEditing()
                for feature in layer.getFeatures():
                    layer.changeAttributeValue(
                        feature.id(), site_index, feature[entity_index]
                    )
                layer.commitChanges()
        if layer.fields().indexFromName("RELATION_TYPE") < 0:
            layer.dataProvider().addAttributes([
                QgsField("RELATION_TYPE", QVariant.String)
            ])
            layer.updateFields()
        required = (
            "SRC_UID",
            "SOURCE_ROLE",
            "SITE_ENTITY_KEY",
            "ENTITY_KEY",
            "RELATION_KEY",
            "RELATION_TYPE",
            "MATCH_STATUS",
            "MATCH_SCORE",
            "MATCH_RULE",
            "REP_SOURCE",
            "LINKED_IDS",
            "IS_REP",
            "NUMBER_KEY",
        )
        indexes = {
            name: layer.fields().indexFromName(name)
            for name in required
        }
        if any(indexes[name] < 0 for name in required):
            self.log(
                "⚠️ 중복 판정 필드가 없어 기존 번호 처리로 진행합니다."
            )
            return {
                "main": layer,
                "suppressed": None,
                "protection": None,
                "audit": None,
                "decision_store_dirty": False,
                "candidate_count": 0,
                "decision_reuse_count": 0,
            }

        name_idx = layer.fields().indexFromName("유적명")
        source_name_idx = layer.fields().indexFromName("SRC_NAME")
        source_layer_idx = layer.fields().indexFromName("원본레이어")
        address_idx = layer.fields().indexFromName("주소")
        project_idx = layer.fields().indexFromName("사업명")
        code_idx = layer.fields().indexFromName("HERITAGE_CODE")
        fingerprint_idx = layer.fields().indexFromName("SRC_FP")

        features = {}
        records = {}
        geometries = {}
        spatial_index = QgsSpatialIndex()
        invalid_fixed = 0
        matching_context = MetricContext.from_layer(layer)

        layer.startEditing()
        for scan_index, feature in enumerate(layer.getFeatures()):
            if scan_index % 500 == 0:
                progress = getattr(self, "_active_progress", None)
                if progress:
                    progress.setLabelText(
                        "중복 판정을 위한 공간 인덱스를 만드는 중입니다..."
                    )
                    QCoreApplication.processEvents()
                    if progress.wasCanceled():
                        layer.rollBack()
                        raise ProcessingCancelled()
            role = str(feature[indexes["SOURCE_ROLE"]] or ROLE_OTHER)
            uid = str(feature[indexes["SRC_UID"]] or f"feature:{feature.id()}")
            geom = QgsGeometry(feature.geometry())
            if not geom.isGeosValid():
                fixed = geom.makeValid()
                if fixed and not fixed.isEmpty():
                    geom = fixed
                    layer.changeGeometry(feature.id(), geom)
                    feature.setGeometry(geom)
                    invalid_fixed += 1

            features[feature.id()] = feature
            metric_geom = matching_context.to_analysis_geometry(
                geom,
                layer.crs(),
            )
            geometries[feature.id()] = metric_geom
            record = {
                "uid": uid,
                "role": role,
                "name": (
                    feature[source_name_idx]
                    if source_name_idx >= 0
                    else feature[name_idx]
                ),
                "source": (
                    feature[source_layer_idx]
                    if source_layer_idx >= 0
                    else ""
                ),
                "site_name": (
                    feature[source_name_idx]
                    if source_name_idx >= 0
                    else feature[name_idx]
                ),
                "project_name": (
                    feature[project_idx] if project_idx >= 0 else ""
                ),
                "address": (
                    feature[address_idx] if address_idx >= 0 else ""
                ),
                "code": (
                    str(feature[code_idx] or "")
                    if code_idx >= 0
                    else ""
                ),
                "feature_id": feature.id(),
            }
            stored_fingerprint = (
                str(feature[fingerprint_idx] or "").strip()
                if fingerprint_idx >= 0
                else ""
            )
            if not stored_fingerprint:
                try:
                    geometry_payload = bytes(geom.asWkb())
                except (TypeError, ValueError):
                    geometry_payload = geom.asWkt()
                stored_fingerprint = build_source_identity(
                    role,
                    native_code=record["code"],
                    name=record["site_name"],
                    project_name=record["project_name"],
                    address=record["address"],
                    geometry=geometry_payload,
                    extra_content={
                        "source": _json_safe_attribute(record["source"]),
                    },
                ).content_fingerprint
            record["fingerprint"] = stored_fingerprint
            records[feature.id()] = record
            indexed_feature = QgsFeature(feature)
            indexed_feature.setGeometry(metric_geom)
            spatial_index.addFeature(indexed_feature)
        layer.commitChanges()

        if invalid_fixed:
            self.log(
                f"중복 판정 전 잘못된 도형 {invalid_fixed}건을 복구했습니다."
            )

        ruleset = load_matching_rules()
        tolerance = float(
            ruleset["thresholds"]["exact_name_distance_m"]
        )
        candidate_pairs = set()
        candidates = []

        for scan_index, (feature_id, record) in enumerate(records.items()):
            if scan_index % 250 == 0:
                progress = getattr(self, "_active_progress", None)
                if progress:
                    progress.setLabelText(
                        "자료 종류별 중복 후보를 비교하는 중입니다..."
                    )
                    QCoreApplication.processEvents()
                    if progress.wasCanceled():
                        raise ProcessingCancelled()
            if record["role"] == ROLE_PROTECTION_ZONE:
                continue
            geom = geometries[feature_id]
            search_rect = QgsRectangle(geom.boundingBox())
            search_rect.grow(tolerance)
            for other_id in spatial_index.intersects(search_rect):
                if other_id == feature_id:
                    continue
                pair = tuple(sorted((feature_id, other_id)))
                if pair in candidate_pairs:
                    continue
                candidate_pairs.add(pair)

                other = records.get(other_id)
                if not other or other["role"] == ROLE_PROTECTION_ZONE:
                    continue
                other_geom = geometries[other_id]
                try:
                    intersects = geom.intersects(other_geom)
                    distance = 0.0 if intersects else geom.distance(other_geom)
                    centroid_distance = geom.centroid().distance(
                        other_geom.centroid()
                    )
                    try:
                        boundary_distance = (
                            self._geometry_boundary_distance(
                                geom, other_geom
                            )
                        )
                    except RuntimeError:
                        boundary_distance = distance
                    left_family = QgsWkbTypes.geometryType(geom.wkbType())
                    right_family = QgsWkbTypes.geometryType(
                        other_geom.wkbType()
                    )
                    family_names = {
                        QgsWkbTypes.PointGeometry: "point",
                        QgsWkbTypes.LineGeometry: "line",
                        QgsWkbTypes.PolygonGeometry: "polygon",
                    }
                    geometry_pair = "_".join((
                        family_names.get(left_family, "unknown"),
                        family_names.get(right_family, "unknown"),
                    ))
                    overlap_ratio = 0.0
                    coverage_left = 0.0
                    coverage_right = 0.0
                    iou = 0.0
                    area_ratio = 0.0
                    if intersects:
                        intersection = geom.intersection(other_geom)
                        if (
                            intersection
                            and not intersection.isEmpty()
                        ):
                            left_area = geom.area()
                            right_area = other_geom.area()
                            intersection_area = intersection.area()
                            min_area = min(left_area, right_area)
                            max_area = max(left_area, right_area)
                            if min_area > 0 and intersection_area > 0:
                                coverage_left = intersection_area / left_area
                                coverage_right = intersection_area / right_area
                                overlap_ratio = intersection_area / min_area
                                union_area = (
                                    left_area + right_area - intersection_area
                                )
                                iou = (
                                    intersection_area / union_area
                                    if union_area > 0 else 0.0
                                )
                                area_ratio = min_area / max_area
                            else:
                                # Point/line candidates remain reviewable but
                                # the ruleset forbids their automatic merge.
                                overlap_ratio = 1.0
                except Exception as exc:
                    self.log(
                        "⚠️ 중복 후보 도형 비교 실패: "
                        f"{record['name']} ↔ {other['name']} ({exc})"
                    )
                    continue

                evaluated = evaluate_candidate(
                    record,
                    other,
                    intersects=intersects,
                    overlap_ratio=overlap_ratio,
                    distance=distance,
                    preset=preset,
                    coverage_left=coverage_left,
                    coverage_right=coverage_right,
                    iou=iou,
                    area_ratio=area_ratio,
                    centroid_distance=centroid_distance,
                    boundary_distance=boundary_distance,
                    geometry_pair=geometry_pair,
                    rules=ruleset,
                )
                if not evaluated:
                    continue
                item = evaluated.as_dict()
                item.update({
                    "left_role": record["role"],
                    "left_source": record["source"],
                    "left_name": record["name"],
                    "left_address": record["address"],
                    "left_fingerprint": record["fingerprint"],
                    "left_feature_id": feature_id,
                    "right_role": other["role"],
                    "right_source": other["source"],
                    "right_name": other["name"],
                    "right_address": other["address"],
                    "right_fingerprint": other["fingerprint"],
                    "right_feature_id": other_id,
                })
                candidates.append(item)

        candidates.sort(
            key=lambda item: (
                not item.get("auto_apply", False),
                -float(item.get("score", 0)),
                str(item.get("left_name", "")),
                str(item.get("right_name", "")),
            )
        )
        self.log(
            f"공간 인덱스 후보 비교 완료: {len(candidate_pairs)}쌍 검사, "
            f"{len(candidates)}쌍 검토 대상"
        )

        reused_decisions = []
        pending_candidates = []
        stale_decisions = 0
        if decision_store is not None and reuse_saved_decisions:
            for candidate in candidates:
                try:
                    lookup = decision_store.lookup(
                        candidate["left_uid"],
                        candidate["left_fingerprint"],
                        candidate["right_uid"],
                        candidate["right_fingerprint"],
                        policy_version=policy_version,
                    )
                except (TypeError, ValueError):
                    pending_candidates.append(candidate)
                    continue
                if lookup.reusable:
                    reused = dict(candidate)
                    reused["decision"] = lookup.decision
                    reused["decision_source"] = "reused"
                    reused_decisions.append(reused)
                else:
                    if lookup.status == "stale":
                        stale_decisions += 1
                    pending_candidates.append(candidate)
        else:
            pending_candidates = list(candidates)

        if reused_decisions:
            self.log(
                f"이전 검토 결정 {len(reused_decisions)}건을 재사용했습니다."
            )
        if stale_decisions:
            self.log(
                f"원본 또는 판정 규칙이 바뀐 {stale_decisions}건은 "
                "다시 검토합니다."
            )

        if pending_candidates and decision_provider is not None:
            reviewed_decisions = decision_provider(pending_candidates)
            if reviewed_decisions is None:
                raise DuplicateReviewCancelled()
        elif pending_candidates:
            dialog = DuplicateReviewDialog(
                pending_candidates,
                parent=self.dlg,
                ui_lang=getattr(self.dlg, "ui_lang", "ko"),
                zoom_callback=lambda candidate: (
                    self._zoom_duplicate_candidate(layer, candidate)
                ),
            )
            if dialog.exec_() != dialog.Accepted:
                raise DuplicateReviewCancelled()
            reviewed_decisions = dialog.decisions()
        else:
            reviewed_decisions = []

        # Providers normally return copies of candidate dictionaries. Fill any
        # omitted fingerprint metadata from the canonical candidate pair.
        candidate_by_pair = {
            tuple(sorted((
                str(candidate["left_uid"]),
                str(candidate["right_uid"]),
            ))): candidate
            for candidate in pending_candidates
        }
        normalized_reviewed = []
        for decision in reviewed_decisions:
            item = dict(decision)
            pair = tuple(sorted((
                str(item.get("left_uid", "")),
                str(item.get("right_uid", "")),
            )))
            candidate = candidate_by_pair.get(pair, {})
            for key, value in candidate.items():
                item.setdefault(key, value)
            normalized_reviewed.append(item)
        reviewed_decisions = normalized_reviewed
        decisions = reused_decisions + reviewed_decisions

        decision_store_dirty = False
        if decision_store is not None:
            for item in reviewed_decisions:
                decision = item.get("decision")
                if decision not in {
                    DECISION_KEEP,
                    DECISION_LINK,
                    DECISION_MERGE,
                }:
                    continue
                try:
                    decision_store.record(
                        item["left_uid"],
                        item["left_fingerprint"],
                        item["right_uid"],
                        item["right_fingerprint"],
                        decision=decision,
                        policy_version=policy_version,
                    )
                    decision_store_dirty = True
                except (KeyError, TypeError, ValueError) as exc:
                    self.log(
                        "⚠️ 검토 결정을 저장 목록에 추가하지 못했습니다: "
                        f"{exc}"
                    )

        uid_to_feature_id = {
            record["uid"]: feature_id
            for feature_id, record in records.items()
        }
        linked_ids = {uid: set() for uid in uid_to_feature_id}
        relation_keys = {uid: set() for uid in uid_to_feature_id}
        relation_types = {uid: set() for uid in uid_to_feature_id}
        rules = {uid: set() for uid in uid_to_feature_id}
        max_scores = {uid: 0.0 for uid in uid_to_feature_id}
        statuses = {uid: STATUS_UNIQUE for uid in uid_to_feature_id}
        suppressed_by = {}

        # Protection zones are not numbering identities.  Link them to their
        # designated/registered asset only within the same source family code.
        designated_by_code = {}
        for feature_id, record in records.items():
            if record["code"] and is_designated_role(record["role"]):
                designated_by_code.setdefault(
                    record["code"],
                    [],
                ).append(record)
        for feature_id, record in records.items():
            if record["role"] != ROLE_PROTECTION_ZONE or not record["code"]:
                continue
            targets = [
                target
                for target in designated_by_code.get(record["code"], [])
                if self._protection_link_compatible(record, target)
            ]
            # A protection layer does not reliably encode national/provincial
            # family.  Code-only linkage is therefore accepted only when the
            # target is unique; collisions remain unlinked for human review.
            if len(targets) != 1:
                continue
            for target in targets:
                target_uid = target["uid"]
                relation_key = self._relation_key(record["uid"], target_uid)
                linked_ids.setdefault(record["uid"], set()).add(target_uid)
                linked_ids.setdefault(target_uid, set()).add(record["uid"])
                relation_keys.setdefault(
                    record["uid"],
                    set(),
                ).add(relation_key)
                relation_keys.setdefault(
                    target_uid,
                    set(),
                ).add(relation_key)
                relation_types.setdefault(record["uid"], set()).add(
                    "legal_boundary_site"
                )
                relation_types.setdefault(target_uid, set()).add(
                    "legal_boundary_site"
                )

        # One lower-priority record may be near several excavation projects or
        # parent/child designated assets.  Never use it to fuse those separate
        # high-priority entities: only the best accepted representative wins.
        merge_decisions = sorted(
            (
                item for item in decisions
                if item.get("decision") == DECISION_MERGE
            ),
            key=lambda item: (
                -float(item.get("score", 0)),
                -source_priority(
                    item.get(
                        "left_role"
                        if str(item.get("left_uid"))
                        == str(item.get("representative_uid"))
                        else "right_role",
                        ROLE_OTHER,
                    )
                ),
            ),
        )
        for item in merge_decisions:
            if item.get("pair_kind") == "excavation_area_parts":
                # Confirmed parts of one excavation site must remain visible;
                # they are dissolved later through their shared geometry key
                # instead of suppressing one part as a duplicate source.
                continue
            representative_uid = str(item["representative_uid"])
            other_uid = (
                str(item["right_uid"])
                if str(item["left_uid"]) == representative_uid
                else str(item["left_uid"])
            )
            if (
                other_uid in suppressed_by
                and suppressed_by[other_uid] != representative_uid
            ):
                item["decision"] = DECISION_LINK
                item["decision_source"] = "conflict_to_link"
                continue
            suppressed_by[other_uid] = representative_uid

        # Confirmed I/II excavation parts form a true equivalence component.
        # Resolve the whole component once so three or more pair decisions do
        # not depend on candidate iteration order or stale cached attributes.
        area_parent = {}

        def area_find(uid):
            area_parent.setdefault(uid, uid)
            while area_parent[uid] != uid:
                area_parent[uid] = area_parent[area_parent[uid]]
                uid = area_parent[uid]
            return uid

        def area_union(left_uid, right_uid):
            left_root = area_find(left_uid)
            right_root = area_find(right_uid)
            if left_root != right_root:
                area_parent[max(left_root, right_root)] = min(
                    left_root, right_root
                )

        for item in decisions:
            if (
                item.get("decision") == DECISION_MERGE
                and item.get("pair_kind") == "excavation_area_parts"
                and item.get("relation_type") == "same_entity"
            ):
                area_union(
                    str(item["left_uid"]),
                    str(item["right_uid"]),
                )

        layer.startEditing()
        for item in decisions:
            left_uid = str(item["left_uid"])
            right_uid = str(item["right_uid"])
            decision = item.get("decision", DECISION_KEEP)
            relation_key = self._relation_key(left_uid, right_uid)
            relation_type = str(
                item.get("relation_type") or "uncertain"
            )
            for uid, other_uid in (
                (left_uid, right_uid),
                (right_uid, left_uid),
            ):
                if decision in {DECISION_LINK, DECISION_MERGE}:
                    linked_ids.setdefault(uid, set()).add(other_uid)
                    relation_keys.setdefault(uid, set()).add(relation_key)
                    relation_types.setdefault(uid, set()).add(
                        relation_type
                    )
                rules.setdefault(uid, set()).add(str(item.get("rule", "")))
                max_scores[uid] = max(
                    max_scores.get(uid, 0.0),
                    float(item.get("score", 0)),
                )

            if decision == DECISION_MERGE:
                representative_uid = str(item["representative_uid"])
                suppressed_uid = (
                    right_uid
                    if left_uid == representative_uid
                    else left_uid
                )
                representative_id = uid_to_feature_id[representative_uid]
                suppressed_id = uid_to_feature_id[suppressed_uid]
                representative = features[representative_id]

                entity_key = representative[indexes["SITE_ENTITY_KEY"]]
                number_key = representative[indexes["NUMBER_KEY"]]
                representative_role = representative[
                    indexes["SOURCE_ROLE"]
                ]
                status = (
                    STATUS_AUTO_MERGED
                    if item.get("decision_source") == "auto"
                    else STATUS_USER_MERGED
                )
                statuses[representative_uid] = status
                statuses[suppressed_uid] = status
                area_parts_merge = (
                    item.get("pair_kind") == "excavation_area_parts"
                )
                if area_parts_merge:
                    # Component keys are applied in one deterministic pass
                    # after every pair has been reviewed.
                    continue
                # Only an explicit same-entity decision is an identity
                # equivalence.  Parent/child, investigation/site, and
                # uncertain relationships may share a cartographic number,
                # but must retain their distinct archaeological entities.
                if relation_type == "same_entity":
                    layer.changeAttributeValue(
                        suppressed_id,
                        indexes["SITE_ENTITY_KEY"],
                        entity_key,
                    )
                    layer.changeAttributeValue(
                        suppressed_id,
                        indexes["ENTITY_KEY"],
                        entity_key,
                    )
                layer.changeAttributeValue(
                    suppressed_id,
                    indexes["NUMBER_KEY"],
                    number_key,
                )
                layer.changeAttributeValue(
                    suppressed_id,
                    indexes["REP_SOURCE"],
                    representative_role,
                )
                layer.changeAttributeValue(
                    suppressed_id,
                    indexes["IS_REP"],
                    0,
                )
            elif decision == DECISION_LINK:
                for uid in (left_uid, right_uid):
                    if statuses.get(uid) not in {
                        STATUS_AUTO_MERGED,
                        STATUS_USER_MERGED,
                    }:
                        statuses[uid] = STATUS_LINKED
            else:
                if statuses.get(left_uid) == STATUS_UNIQUE:
                    statuses[left_uid] = STATUS_KEPT_SEPARATE
                if statuses.get(right_uid) == STATUS_UNIQUE:
                    statuses[right_uid] = STATUS_KEPT_SEPARATE

        area_components = {}
        for uid in area_parent:
            area_components.setdefault(area_find(uid), []).append(uid)
        geometry_group_index = layer.fields().indexFromName(
            "GEOMETRY_GROUP_KEY"
        )
        group_index = layer.fields().indexFromName("GROUP_KEY")
        for component in area_components.values():
            representative_uid = min(
                component,
                key=lambda uid: (
                    -source_priority(records[uid_to_feature_id[uid]]["role"]),
                    uid,
                ),
            )
            representative_id = uid_to_feature_id[representative_uid]
            representative = features[representative_id]
            for uid in component:
                feature_id = uid_to_feature_id[uid]
                for field_name in (
                    "SITE_ENTITY_KEY", "ENTITY_KEY", "NUMBER_KEY",
                    "REP_SOURCE",
                ):
                    layer.changeAttributeValue(
                        feature_id,
                        indexes[field_name],
                        representative[indexes[field_name]],
                    )
                if geometry_group_index >= 0:
                    layer.changeAttributeValue(
                        feature_id,
                        geometry_group_index,
                        representative[geometry_group_index],
                    )
                if group_index >= 0:
                    layer.changeAttributeValue(
                        feature_id,
                        group_index,
                        representative[group_index],
                    )
                layer.changeAttributeValue(
                    feature_id, indexes["IS_REP"], 1
                )

        for uid, feature_id in uid_to_feature_id.items():
            role = records[feature_id]["role"]
            if role == ROLE_PROTECTION_ZONE:
                statuses[uid] = STATUS_PROTECTION_ZONE
                layer.changeAttributeValue(
                    feature_id,
                    indexes["IS_REP"],
                    0,
                )
                layer.changeAttributeValue(
                    feature_id,
                    indexes["NUMBER_KEY"],
                    "",
                )
            layer.changeAttributeValue(
                feature_id,
                indexes["RELATION_KEY"],
                ",".join(sorted(relation_keys.get(uid, set()))) or None,
            )
            layer.changeAttributeValue(
                feature_id,
                indexes["RELATION_TYPE"],
                ",".join(sorted(relation_types.get(uid, set()))) or None,
            )
            layer.changeAttributeValue(
                feature_id,
                indexes["MATCH_STATUS"],
                statuses.get(uid, STATUS_UNIQUE),
            )
            layer.changeAttributeValue(
                feature_id,
                indexes["MATCH_SCORE"],
                max_scores.get(uid, 0.0),
            )
            layer.changeAttributeValue(
                feature_id,
                indexes["MATCH_RULE"],
                ",".join(
                    sorted(value for value in rules.get(uid, set()) if value)
                ) or None,
            )
            layer.changeAttributeValue(
                feature_id,
                indexes["LINKED_IDS"],
                ",".join(sorted(linked_ids.get(uid, set()))) or None,
            )
        layer.commitChanges()

        # Aggregate before splitting so representative records retain every
        # lower-priority source record in SRC_JSON.
        self.aggregate_source_metadata(layer)

        main = self._memory_layer_like(
            layer,
            "수집_및_병합된_주변유적",
            lambda feature: (
                str(feature["SOURCE_ROLE"]) != ROLE_PROTECTION_ZONE
                and int(feature["IS_REP"] or 0) == 1
            ),
        )
        suppressed = self._memory_layer_like(
            layer,
            "중복_보존",
            lambda feature: (
                str(feature["SOURCE_ROLE"]) != ROLE_PROTECTION_ZONE
                and int(feature["IS_REP"] or 0) == 0
            ),
        )
        protection = self._memory_layer_like(
            layer,
            "지정유산_보호구역",
            lambda feature: (
                str(feature["SOURCE_ROLE"]) == ROLE_PROTECTION_ZONE
            ),
        )
        audit = self._create_match_audit_layer(decisions)
        return {
            "main": main,
            "suppressed": suppressed,
            "protection": protection,
            "audit": audit,
            "decision_store_dirty": decision_store_dirty,
            "candidate_count": len(candidates),
            "decision_reuse_count": len(reused_decisions),
        }

    @staticmethod
    def _split_relation_values(value):
        return {
            item.strip()
            for item in str(value or "").split(",")
            if item.strip()
        }

    def _zoom_cross_family_candidate(self, layers_by_id, candidate):
        """Zoom a review pair whose features live in separate layers."""
        combined = QgsGeometry()
        combined_crs = None
        flash_items = []
        for prefix in ("left", "right"):
            layer = layers_by_id.get(candidate.get(f"{prefix}_layer_id"))
            feature_id = candidate.get(f"{prefix}_feature_id")
            if layer is None or feature_id is None:
                continue
            feature = next(
                layer.getFeatures(
                    QgsFeatureRequest().setFilterFid(int(feature_id))
                ),
                None,
            )
            if feature is None or not feature.hasGeometry():
                continue
            geometry = QgsGeometry(feature.geometry())
            if combined_crs is None:
                combined_crs = layer.crs()
            elif layer.crs() != combined_crs:
                geometry.transform(QgsCoordinateTransform(
                    layer.crs(),
                    combined_crs,
                    QgsProject.instance(),
                ))
            combined = (
                geometry
                if combined.isNull()
                else combined.combine(geometry)
            )
            flash_items.append((layer, int(feature_id)))
        if combined.isNull() or combined.isEmpty() or combined_crs is None:
            return
        self.zoom_canvas_to_extent(
            combined,
            extent_crs=combined_crs,
            padding_ratio=0.25,
        )
        if self.iface is None:
            return
        canvas = self.iface.mapCanvas()
        if hasattr(canvas, "flashFeatureIds"):
            for layer, feature_id in flash_items:
                try:
                    canvas.flashFeatureIds(layer, [feature_id])
                except Exception:
                    pass

    def apply_cross_family_matching(
        self,
        layers,
        *,
        preset=PRESET_BALANCED,
        decision_provider=None,
        decision_store=None,
        reuse_saved_decisions=True,
        policy_version=None,
    ):
        """Review cross-family candidates without coercing their geometries.

        Geometry families stay in separate layers.  Accepted merge decisions
        unify only logical/cartographic keys; no feature is deleted or moved to
        the suppressed layer by this pass.
        """
        layers = [layer for layer in (layers or []) if layer is not None]
        families = {layer.geometryType() for layer in layers}
        if len(families) < 2:
            return {
                "audit": None,
                "candidate_count": 0,
                "decision_reuse_count": 0,
                "decision_store_dirty": False,
            }

        policy_version = (
            str(policy_version)
            if policy_version
            else f"{self._matching_policy_key(preset)}:cross-family-v1"
        )
        required = (
            "SRC_UID", "SRC_FP", "SOURCE_ROLE", "SITE_ENTITY_KEY",
            "ENTITY_KEY", "RELATION_KEY", "RELATION_TYPE", "MATCH_STATUS",
            "MATCH_SCORE", "MATCH_RULE", "REP_SOURCE", "LINKED_IDS",
            "IS_REP", "NUMBER_KEY",
        )
        layer_indexes = {}
        layer_records = {}
        layers_by_id = {layer.id(): layer for layer in layers}
        metric_context = MetricContext.from_layer(layers[0])
        family_names = {
            QgsWkbTypes.PointGeometry: "point",
            QgsWkbTypes.LineGeometry: "line",
            QgsWkbTypes.PolygonGeometry: "polygon",
        }

        for layer in layers:
            indexes = {
                name: layer.fields().indexFromName(name)
                for name in required
            }
            if any(indexes[name] < 0 for name in required):
                self.log(
                    "⚠️ 형상 계열 간 판정 필드가 부족해 건너뜁니다: "
                    f"{layer.name()}"
                )
                continue
            layer_indexes[layer.id()] = indexes
            optional = {
                name: layer.fields().indexFromName(name)
                for name in (
                    "유적명", "SRC_NAME", "주소", "사업명", "원본레이어",
                    "HERITAGE_CODE",
                )
            }
            records = {}
            layer.startEditing()
            for feature in layer.getFeatures():
                if not feature.hasGeometry():
                    continue
                geometry = QgsGeometry(feature.geometry())
                if not geometry.isGeosValid():
                    fixed = geometry.makeValid()
                    if fixed and not fixed.isEmpty():
                        geometry = fixed
                        layer.changeGeometry(feature.id(), geometry)
                metric_geometry = metric_context.to_analysis_geometry(
                    geometry,
                    layer.crs(),
                )
                uid = str(
                    feature[indexes["SRC_UID"]]
                    or f"{layer.id()}:feature:{feature.id()}"
                )
                site_name = (
                    feature[optional["SRC_NAME"]]
                    if optional["SRC_NAME"] >= 0
                    else feature[optional["유적명"]]
                    if optional["유적명"] >= 0
                    else ""
                )
                role = str(feature[indexes["SOURCE_ROLE"]] or ROLE_OTHER)
                source = (
                    feature[optional["원본레이어"]]
                    if optional["원본레이어"] >= 0 else layer.name()
                )
                project_name = (
                    feature[optional["사업명"]]
                    if optional["사업명"] >= 0 else ""
                )
                address = (
                    feature[optional["주소"]]
                    if optional["주소"] >= 0 else ""
                )
                code = (
                    str(feature[optional["HERITAGE_CODE"]] or "")
                    if optional["HERITAGE_CODE"] >= 0 else ""
                )
                fingerprint = str(feature[indexes["SRC_FP"]] or "").strip()
                if not fingerprint:
                    try:
                        geometry_payload = bytes(geometry.asWkb())
                    except (TypeError, ValueError):
                        geometry_payload = geometry.asWkt()
                    fingerprint = build_source_identity(
                        role,
                        native_code=code,
                        name=site_name,
                        project_name=project_name,
                        address=address,
                        geometry=geometry_payload,
                        extra_content={"source": _json_safe_attribute(source)},
                    ).content_fingerprint
                records[feature.id()] = {
                    "uid": uid,
                    "fingerprint": fingerprint,
                    "role": role,
                    "name": site_name,
                    "site_name": site_name,
                    "source": source,
                    "project_name": project_name,
                    "address": address,
                    "code": code,
                    "feature_id": feature.id(),
                    "layer_id": layer.id(),
                    "geometry": metric_geometry,
                }
            layer.commitChanges()
            layer_records[layer.id()] = records

        ruleset = load_matching_rules()
        tolerance = float(ruleset["thresholds"]["exact_name_distance_m"])
        candidates = []
        usable_layers = [
            layer for layer in layers if layer.id() in layer_records
        ]
        for left_pos, left_layer in enumerate(usable_layers):
            left_family = left_layer.geometryType()
            for right_layer in usable_layers[left_pos + 1:]:
                right_family = right_layer.geometryType()
                if left_family == right_family:
                    continue
                right_index = QgsSpatialIndex()
                for right_id, right in layer_records[right_layer.id()].items():
                    indexed = QgsFeature()
                    indexed.setId(right_id)
                    indexed.setGeometry(right["geometry"])
                    right_index.addFeature(indexed)
                for left_id, left in layer_records[left_layer.id()].items():
                    left_geometry = left["geometry"]
                    search_rect = QgsRectangle(left_geometry.boundingBox())
                    search_rect.grow(tolerance)
                    for right_id in right_index.intersects(search_rect):
                        right = layer_records[right_layer.id()].get(right_id)
                        if right is None:
                            continue
                        right_geometry = right["geometry"]
                        try:
                            intersects = left_geometry.intersects(right_geometry)
                            distance = (
                                0.0 if intersects
                                else left_geometry.distance(right_geometry)
                            )
                            centroid_distance = left_geometry.centroid().distance(
                                right_geometry.centroid()
                            )
                            boundary_distance = self._geometry_boundary_distance(
                                left_geometry,
                                right_geometry,
                            )
                        except Exception as exc:
                            self.log(
                                "⚠️ 형상 계열 간 후보 비교 실패: "
                                f"{left['name']} ↔ {right['name']} ({exc})"
                            )
                            continue
                        # Intersection area has no comparable denominator across
                        # unlike dimensions.  A binary topological intersection
                        # keeps the pair reviewable, while evaluate_candidate's
                        # geometry gate prevents automatic action.
                        overlap_ratio = 1.0 if intersects else 0.0
                        geometry_pair = "_".join((
                            family_names.get(left_family, "unknown"),
                            family_names.get(right_family, "unknown"),
                        ))
                        evaluated = evaluate_candidate(
                            left,
                            right,
                            intersects=intersects,
                            overlap_ratio=overlap_ratio,
                            distance=distance,
                            preset=preset,
                            coverage_left=0.0,
                            coverage_right=0.0,
                            iou=0.0,
                            area_ratio=0.0,
                            centroid_distance=centroid_distance,
                            boundary_distance=boundary_distance,
                            geometry_pair=geometry_pair,
                            rules=ruleset,
                        )
                        if not evaluated:
                            continue
                        item = evaluated.as_dict()
                        # Cross-family evidence always requires an explicit
                        # human decision, regardless of preset or score.
                        item["auto_apply"] = False
                        item.update({
                            "left_role": left["role"],
                            "left_source": left["source"],
                            "left_name": left["name"],
                            "left_address": left["address"],
                            "left_fingerprint": left["fingerprint"],
                            "left_feature_id": left_id,
                            "left_layer_id": left_layer.id(),
                            "right_role": right["role"],
                            "right_source": right["source"],
                            "right_name": right["name"],
                            "right_address": right["address"],
                            "right_fingerprint": right["fingerprint"],
                            "right_feature_id": right_id,
                            "right_layer_id": right_layer.id(),
                        })
                        candidates.append(item)

        candidates.sort(key=lambda item: (
            -float(item.get("score", 0)),
            str(item.get("left_uid", "")),
            str(item.get("right_uid", "")),
        ))
        self.log(
            "형상 계열 간 중복 후보 검토 준비 완료: "
            f"{len(candidates)}쌍 (자동 처리 없음)"
        )
        reused_decisions = []
        pending = []
        if decision_store is not None and reuse_saved_decisions:
            for candidate in candidates:
                try:
                    lookup = decision_store.lookup(
                        candidate["left_uid"],
                        candidate["left_fingerprint"],
                        candidate["right_uid"],
                        candidate["right_fingerprint"],
                        policy_version=policy_version,
                    )
                except (TypeError, ValueError):
                    pending.append(candidate)
                    continue
                if lookup.reusable:
                    reused = dict(candidate)
                    reused["decision"] = lookup.decision
                    reused["decision_source"] = "reused"
                    reused_decisions.append(reused)
                else:
                    pending.append(candidate)
        else:
            pending = list(candidates)

        if pending and decision_provider is not None:
            reviewed = decision_provider(pending)
            if reviewed is None:
                raise DuplicateReviewCancelled()
        elif pending:
            dialog = DuplicateReviewDialog(
                pending,
                parent=self.dlg,
                ui_lang=getattr(self.dlg, "ui_lang", "ko"),
                zoom_callback=lambda candidate: self._zoom_cross_family_candidate(
                    layers_by_id,
                    candidate,
                ),
            )
            if dialog.exec_() != dialog.Accepted:
                raise DuplicateReviewCancelled()
            reviewed = dialog.decisions()
        else:
            reviewed = []

        by_pair = {
            tuple(sorted((
                str(candidate["left_uid"]),
                str(candidate["right_uid"]),
            ))): candidate
            for candidate in pending
        }
        normalized_reviewed = []
        for decision in reviewed:
            item = dict(decision)
            pair = tuple(sorted((
                str(item.get("left_uid", "")),
                str(item.get("right_uid", "")),
            )))
            for key, value in by_pair.get(pair, {}).items():
                item.setdefault(key, value)
            if item.get("decision_source") == "auto":
                item["decision_source"] = "human_review"
            else:
                item.setdefault("decision_source", "human_review")
            normalized_reviewed.append(item)
        reviewed = normalized_reviewed
        decisions = reused_decisions + reviewed

        decision_store_dirty = False
        if decision_store is not None:
            for item in reviewed:
                decision = item.get("decision")
                if decision not in {
                    DECISION_KEEP, DECISION_LINK, DECISION_MERGE,
                }:
                    continue
                decision_store.record(
                    item["left_uid"],
                    item["left_fingerprint"],
                    item["right_uid"],
                    item["right_fingerprint"],
                    decision=decision,
                    policy_version=policy_version,
                )
                decision_store_dirty = True

        entries = {}
        for layer in usable_layers:
            indexes = layer_indexes[layer.id()]
            for feature in layer.getFeatures():
                uid = str(feature[indexes["SRC_UID"]])
                entries[uid] = {
                    "layer": layer,
                    "feature": feature,
                    "indexes": indexes,
                    "role": str(feature[indexes["SOURCE_ROLE"]] or ROLE_OTHER),
                }

        parent = {uid: uid for uid in entries}
        entity_parent = {uid: uid for uid in entries}

        def find(mapping, uid):
            while mapping[uid] != uid:
                mapping[uid] = mapping[mapping[uid]]
                uid = mapping[uid]
            return uid

        def union(mapping, left_uid, right_uid):
            left_root = find(mapping, left_uid)
            right_root = find(mapping, right_uid)
            if left_root != right_root:
                mapping[max(left_root, right_root)] = min(left_root, right_root)

        relations = {uid: set() for uid in entries}
        relation_types = {uid: set() for uid in entries}
        links = {uid: set() for uid in entries}
        rules = {uid: set() for uid in entries}
        scores = {uid: 0.0 for uid in entries}
        statuses = {}
        for uid, entry in entries.items():
            feature = entry["feature"]
            indexes = entry["indexes"]
            relations[uid] = self._split_relation_values(
                feature[indexes["RELATION_KEY"]]
            )
            relation_types[uid] = self._split_relation_values(
                feature[indexes["RELATION_TYPE"]]
            )
            links[uid] = self._split_relation_values(
                feature[indexes["LINKED_IDS"]]
            )
            rules[uid] = self._split_relation_values(
                feature[indexes["MATCH_RULE"]]
            )
            scores[uid] = float(feature[indexes["MATCH_SCORE"]] or 0.0)
            statuses[uid] = str(
                feature[indexes["MATCH_STATUS"]] or STATUS_UNIQUE
            )

        for item in decisions:
            left_uid = str(item.get("left_uid", ""))
            right_uid = str(item.get("right_uid", ""))
            if left_uid not in entries or right_uid not in entries:
                continue
            decision = item.get("decision", DECISION_KEEP)
            relation_type = str(item.get("relation_type") or "uncertain")
            rule = str(item.get("rule") or "")
            score = float(item.get("score") or 0.0)
            for uid in (left_uid, right_uid):
                if rule:
                    rules[uid].add(rule)
                scores[uid] = max(scores[uid], score)
            if decision == DECISION_KEEP:
                for uid in (left_uid, right_uid):
                    if statuses[uid] == STATUS_UNIQUE:
                        statuses[uid] = STATUS_KEPT_SEPARATE
                continue

            relation_key = self._relation_key(left_uid, right_uid)
            for uid, other_uid in (
                (left_uid, right_uid),
                (right_uid, left_uid),
            ):
                relations[uid].add(relation_key)
                relation_types[uid].add(relation_type)
                links[uid].add(other_uid)
            if decision == DECISION_LINK:
                for uid in (left_uid, right_uid):
                    if statuses[uid] not in {
                        STATUS_AUTO_MERGED, STATUS_USER_MERGED,
                    }:
                        statuses[uid] = STATUS_LINKED
                continue

            union(parent, left_uid, right_uid)
            if relation_type == "same_entity":
                union(entity_parent, left_uid, right_uid)
            statuses[left_uid] = STATUS_USER_MERGED
            statuses[right_uid] = STATUS_USER_MERGED

        def representative(component):
            return min(
                component,
                key=lambda uid: (
                    -source_priority(entries[uid]["role"]),
                    uid,
                ),
            )

        number_components = {}
        entity_components = {}
        for uid in entries:
            number_components.setdefault(find(parent, uid), []).append(uid)
            entity_components.setdefault(find(entity_parent, uid), []).append(uid)

        for layer in usable_layers:
            layer.startEditing()

        for component in number_components.values():
            if len(component) < 2:
                continue
            rep_uid = representative(component)
            rep_entry = entries[rep_uid]
            rep_feature = rep_entry["feature"]
            rep_indexes = rep_entry["indexes"]
            number_key = str(
                rep_feature[rep_indexes["NUMBER_KEY"]] or rep_uid
            )
            rep_role = rep_entry["role"]
            for uid in component:
                entry = entries[uid]
                layer = entry["layer"]
                indexes = entry["indexes"]
                layer.changeAttributeValue(
                    entry["feature"].id(), indexes["NUMBER_KEY"], number_key
                )
                layer.changeAttributeValue(
                    entry["feature"].id(), indexes["REP_SOURCE"], rep_role
                )
                layer.changeAttributeValue(
                    entry["feature"].id(), indexes["IS_REP"],
                    1 if uid == rep_uid else 0,
                )

        for component in entity_components.values():
            if len(component) < 2:
                continue
            rep_uid = representative(component)
            rep_entry = entries[rep_uid]
            rep_feature = rep_entry["feature"]
            rep_indexes = rep_entry["indexes"]
            entity_key = str(
                rep_feature[rep_indexes["SITE_ENTITY_KEY"]] or rep_uid
            )
            for uid in component:
                entry = entries[uid]
                layer = entry["layer"]
                indexes = entry["indexes"]
                layer.changeAttributeValue(
                    entry["feature"].id(),
                    indexes["SITE_ENTITY_KEY"],
                    entity_key,
                )
                layer.changeAttributeValue(
                    entry["feature"].id(), indexes["ENTITY_KEY"], entity_key
                )

        for uid, entry in entries.items():
            layer = entry["layer"]
            feature_id = entry["feature"].id()
            indexes = entry["indexes"]
            layer.changeAttributeValue(
                feature_id,
                indexes["RELATION_KEY"],
                ",".join(sorted(relations[uid])) or None,
            )
            layer.changeAttributeValue(
                feature_id,
                indexes["RELATION_TYPE"],
                ",".join(sorted(relation_types[uid])) or None,
            )
            layer.changeAttributeValue(
                feature_id,
                indexes["LINKED_IDS"],
                ",".join(sorted(links[uid])) or None,
            )
            layer.changeAttributeValue(
                feature_id,
                indexes["MATCH_RULE"],
                ",".join(sorted(rules[uid])) or None,
            )
            layer.changeAttributeValue(
                feature_id, indexes["MATCH_SCORE"], scores[uid]
            )
            layer.changeAttributeValue(
                feature_id, indexes["MATCH_STATUS"], statuses[uid]
            )
        for layer in usable_layers:
            if layer.isEditable():
                layer.commitChanges()

        self.aggregate_source_metadata_layers(usable_layers)
        return {
            "audit": self._create_match_audit_layer(decisions),
            "candidate_count": len(candidates),
            "decision_reuse_count": len(reused_decisions),
            "decision_store_dirty": decision_store_dirty,
        }

    def _feature_request_for_extent(
        self,
        layer,
        extent_geom,
        extent_crs,
    ):
        """Build a conservative provider-side extent filter."""
        request = QgsFeatureRequest()
        if extent_geom is None or extent_crs is None:
            return request, False

        try:
            source_rect = QgsRectangle(extent_geom.boundingBox())
            if layer.crs() != extent_crs:
                reverse_transform = QgsCoordinateTransform(
                    extent_crs,
                    layer.crs(),
                    QgsProject.instance(),
                )
                source_rect = reverse_transform.transformBoundingBox(
                    source_rect
                )
            if source_rect.isEmpty() or not source_rect.isFinite():
                return request, False
            request.setFilterRect(source_rect)
            return request, True
        except Exception as exc:
            # A CRS/filter failure must cost performance, never source data.
            self.log(
                "⚠️ 도곽 선필터를 적용하지 못해 전체 레이어를 확인합니다: "
                f"{layer.name()} ({exc})"
            )
            return QgsFeatureRequest(), False

    def _build_zone_spatial_lookup(
        self,
        zone_layer,
        target_crs,
        zone_name_field,
    ):
        """Index Zone geometries once in the heritage output CRS."""
        if not zone_layer or not zone_name_field:
            return None, {}

        spatial_index = QgsSpatialIndex()
        zone_records = {}
        transform = None
        if zone_layer.crs() != target_crs:
            transform = QgsCoordinateTransform(
                zone_layer.crs(),
                target_crs,
                QgsProject.instance(),
            )

        for scan_index, zone_feature in enumerate(
            zone_layer.getFeatures()
        ):
            if scan_index % 500 == 0:
                progress = getattr(self, "_active_progress", None)
                if progress:
                    progress.setLabelText(
                        "현상변경 허용구간 공간 인덱스를 만드는 중입니다..."
                    )
                    QCoreApplication.processEvents()
                    if progress.wasCanceled():
                        raise ProcessingCancelled()
            if not zone_feature.hasGeometry():
                continue
            zone_geom = QgsGeometry(zone_feature.geometry())
            if transform:
                zone_geom.transform(transform)
            if zone_geom.isEmpty():
                continue

            indexed_feature = QgsFeature(zone_feature)
            indexed_feature.setGeometry(zone_geom)
            spatial_index.addFeature(indexed_feature)
            zone_records[zone_feature.id()] = (
                zone_geom,
                zone_feature[zone_name_field],
            )

        return spatial_index, zone_records

    def consolidate_heritage_layers(
        self,
        heritage_layer_ids,
        extent_geom,
        study_layer,
        src_group,
        filter_categories=None,
        exclusion_list=None,
        zone_layer=None,
        preservation_only=False,
        preservation_action_fields=None,
        exclude_extent_slivers=False,
        paper_size_mm=None,
        source_roles=None,
        source_encodings=None,
        match_preset=PRESET_BALANCED,
        matching_decision_provider=None,
        reuse_review_decisions=False,
    ):
        """Merge selected heritage layers and filter by extent, study area, and user exclusions. Also tags Zone."""
        """Merge selected heritage layers and filter by extent, study area, and user exclusions."""
        if exclusion_list is None:
            exclusion_list = []
        if preservation_action_fields is None:
            preservation_action_fields = {}
        if source_roles is None:
            source_roles = {}
        if source_encodings is None:
            source_encodings = {}
        temp_layers = []
        selected_fingerprints = {}
        clip_filter_context = None
        if (
            exclude_extent_slivers
            and extent_geom is not None
            and paper_size_mm
        ):
            try:
                extent_bounds = extent_geom.boundingBox()
                paper_width_mm, paper_height_mm = paper_size_mm
                if (
                    extent_bounds.width() > 0
                    and extent_bounds.height() > 0
                    and float(paper_width_mm) > 0
                    and float(paper_height_mm) > 0
                ):
                    clip_filter_context = {
                        "extent_width": extent_bounds.width(),
                        "extent_height": extent_bounds.height(),
                        "paper_width_mm": float(paper_width_mm),
                        "paper_height_mm": float(paper_height_mm),
                    }
            except (TypeError, ValueError):
                clip_filter_context = None

        # Merge study area geometries for fast intersection check
        study_geom = QgsGeometry()
        if study_layer:
            for f in study_layer.getFeatures():
                if study_geom.isNull():
                    study_geom = f.geometry()
                else:
                    study_geom = study_geom.combine(f.geometry())
            target_crs = study_layer.crs()
        else:
            target_crs = None
            for layer_id in heritage_layer_ids:
                candidate = QgsProject.instance().mapLayer(layer_id)
                if candidate and candidate.type() == 0:
                    target_crs = candidate.crs()
                    break
            if target_crs is None:
                self.log("처리할 벡터 레이어를 찾을 수 없습니다.")
                return None

        zone_name_field = None
        zone_spatial_index = None
        zone_records = {}
        if zone_layer:
            zone_name_field = self.find_field(
                zone_layer,
                [
                    '구역',
                    '구역명',
                    'NAME',
                    'ZONENAME',
                    'ZONE',
                    'L3_CODE',
                    'A_L3_CODE',
                    'L2_CODE',
                ],
            )
            if zone_name_field:
                zone_spatial_index, zone_records = (
                    self._build_zone_spatial_lookup(
                        zone_layer,
                        target_crs,
                        zone_name_field,
                    )
                )
                self.log(
                    "현상변경 허용구간 공간 인덱스 준비 완료: "
                    f"{len(zone_records)}건"
                )

        for lid in heritage_layer_ids:
            layer = QgsProject.instance().mapLayer(lid)
            if not layer or layer.type() != 0:
                self._record_excluded_layer(
                    layer,
                    "missing_or_non_vector_layer",
                )
                continue
            if preservation_only and layer.geometryType() != 2:
                self.log(
                    f"  ⚠️ 폴리곤이 아니므로 유존지역 처리에서 제외: "
                    f"{layer.name()}"
                )
                self._record_excluded_layer(
                    layer,
                    "preservation_requires_polygon",
                )
                continue

            self.log(f"데이터 수취 및 필드 맵핑 중: {layer.name()}")
            self.fix_layer_encoding(
                layer,
                source_encodings.get(lid),
            )
            source_role = (
                source_roles.get(lid)
                or detect_source_role(
                    layer.name(),
                    [field.name() for field in layer.fields()],
                )
            )
            self.log(
                "  -> 자료 역할: "
                f"{SOURCE_ROLE_LABELS.get(source_role, source_role)}"
            )

            # Identify fields (Fuzzy matching)
            # [FIX] Broaden search to include National/State Heritage naming conventions
            name_keywords = [
                '유적명', '유존지역명', '명칭', 'NAME', 'SITE', 'TITLE',
                '문화재명', '지정명칭', '국가유산명', '등록명칭',
            ]
            name_field = self.find_field(layer, name_keywords)
            project_name_field = self.find_field(
                layer,
                ['사업명', '조사명', '공사명', 'PROJECT'],
            )

            explicit_action_field = preservation_action_fields.get(lid)
            if explicit_action_field:
                action_field_idx = layer.fields().indexFromName(
                    explicit_action_field
                )
                if action_field_idx >= 0 and recognized_preservation_actions(
                    layer.uniqueValues(action_field_idx)
                ):
                    preservation_action_field = explicit_action_field
                else:
                    preservation_action_field = None
            else:
                preservation_action_field = (
                    self.find_preservation_action_field(layer)
                )

            if preservation_only and not preservation_action_field:
                self.log(
                    f"  ⚠️ 네 가지 보존조치 값이 확인되지 않아 제외: "
                    f"{layer.name()}"
                )
                self._record_excluded_layer(
                    layer,
                    "preservation_action_not_recognized",
                    role=source_role,
                )
                continue

            # [FIX] Skip invalid layers (e.g. Topo maps selected as Heritage)
            if not name_field:
                if preservation_only:
                    self.log(
                        "  -> 명칭 필드 없음: 사업명 또는 객체별 식별자로 "
                        "번호를 부여합니다."
                    )
                else:
                    self.log(f"  ⚠️ 명칭 필드({name_keywords}) 미확인으로 병합 제외: {layer.name()}")
                    self._record_excluded_layer(
                        layer,
                        "heritage_name_field_not_found",
                        role=source_role,
                    )
                    continue

            heritage_name_field = self.find_field(layer, ['국가유산명', '문화재명', '지정명칭'])  # Keep specific for attribute extraction
            addr_field = self.find_field(layer, ['주소', '지번', '소재지', 'ADDR', 'LOC'])
            if preservation_action_field:
                action_idx = layer.fields().indexFromName(
                    preservation_action_field
                )
                recognized_actions = sorted(
                    recognized_preservation_actions(
                        layer.uniqueValues(action_idx)
                    )
                )
                self.log(
                    f"  -> 매장유산 유존지역 자동 인식: "
                    f"{preservation_action_field}="
                    f"{', '.join(recognized_actions)}"
                )

            # Detect geometry type
            geom_type_str = ""
            if layer.geometryType() == 0:
                geom_type_str = "Point"
            elif layer.geometryType() == 1:
                geom_type_str = "LineString"
            elif layer.geometryType() == 2:
                geom_type_str = "Polygon"

            # Create a standardized subset layer
            subset_layer = QgsVectorLayer(f"{geom_type_str}?crs={target_crs.toWkt()}", f"Sub_{layer.name()}", "memory")
            if not subset_layer.isValid():
                subset_layer = QgsVectorLayer(f"{geom_type_str}?crs={target_crs.authid()}", f"Sub_{layer.name()}", "memory")
            subset_pr = subset_layer.dataProvider()

            # Define standard fields (번호 comes first for report readiness)
            # [NOTE] Warnings about QgsField constructor are harmless deprecation warnings in QGIS 3.x
            standard_fields = [
                QgsField("번호", QVariant.Int),
                QgsField("유적명", QVariant.String),
                QgsField("주소", QVariant.String),
                QgsField("면적_m2", QVariant.Double),
                QgsField("DIST_M", QVariant.Double),
                QgsField("국가유산명", QVariant.String),  # [NEW]
                QgsField("사업명", QVariant.String),     # [NEW]
                QgsField("허용기준", QVariant.String),   # [NEW] Zone Info
                QgsField("원본레이어", QVariant.String),
                QgsField("HERITAGE_CODE", QVariant.String),
                QgsField("SRC_UID", QVariant.String),
                QgsField("SRC_FP", QVariant.String),
                QgsField("SOURCE_ROLE", QVariant.String),
                QgsField("INVESTIGATION_KEY", QVariant.String),
                QgsField("SITE_ENTITY_KEY", QVariant.String),
                QgsField("ENTITY_KEY", QVariant.String),
                QgsField("GEOMETRY_GROUP_KEY", QVariant.String),
                QgsField("RELATION_KEY", QVariant.String),
                QgsField("RELATION_TYPE", QVariant.String),
                QgsField("MATCH_STATUS", QVariant.String),
                QgsField("MATCH_SCORE", QVariant.Double),
                QgsField("MATCH_RULE", QVariant.String),
                QgsField("REP_SOURCE", QVariant.String),
                QgsField("LINKED_IDS", QVariant.String),
                QgsField("IS_REP", QVariant.Int),
                QgsField("보존조치", QVariant.String),
                QgsField("SRC_NAME", QVariant.String),
                QgsField("SRC_ACTION", QVariant.String),
                QgsField("NUMBER_KEY", QVariant.String),
                QgsField("GROUP_KEY", QVariant.String),
                QgsField("SRC_COUNT", QVariant.Int),
                QgsField("SRC_JSON", QVariant.String),
            ]

            # Preserve every source field, not just the standardized subset.
            # Standard fields keep their mapped meaning; colliding originals are
            # retained in SRC_NAME/SRC_ACTION and in the complete SRC_JSON audit.
            standard_names = {field.name().casefold() for field in standard_fields}
            copied_source_fields = []
            for source_field in layer.fields():
                source_name = source_field.name()
                if source_name.casefold() in standard_names:
                    continue
                standard_fields.append(QgsField(source_field))
                standard_names.add(source_name.casefold())
                copied_source_fields.append(source_name)

            subset_pr.addAttributes(standard_fields)
            subset_layer.updateFields()

            # Reproject if necessary
            do_reproject = layer.crs() != target_crs
            if do_reproject:
                from qgis.core import QgsCoordinateTransform
                transform = QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance())

            new_features = []
            fingerprint_records = []
            excluded_extent_slivers = 0
            geometry_repairs = 0
            invalid_geometry_exclusions = 0
            source_feature_count = layer.featureCount()
            candidate_feature_count = 0
            scan_started = time.perf_counter()
            code_field = self.find_field(
                layer,
                ["유산코드", "HERITAGE_CODE", "CODE"],
            )
            preservation_site_id_field = (
                self.find_preservation_site_id_field(layer)
                if preservation_only else None
            )
            feature_request, used_extent_filter = (
                self._feature_request_for_extent(
                    layer,
                    extent_geom,
                    target_crs,
                )
            )
            for scan_index, feat in enumerate(
                layer.getFeatures(feature_request)
            ):
                candidate_feature_count += 1
                if scan_index % 500 == 0:
                    progress = getattr(self, "_active_progress", None)
                    if progress:
                        progress.setLabelText(
                            f"{layer.name()} 도곽 후보를 확인하는 중입니다..."
                        )
                        QCoreApplication.processEvents()
                        if progress.wasCanceled():
                            raise ProcessingCancelled()
                if not feat.hasGeometry():
                    invalid_geometry_exclusions += 1
                    continue

                source_geometry = QgsGeometry(feat.geometry())
                try:
                    source_geometry_payload = bytes(source_geometry.asWkb())
                except (TypeError, ValueError):
                    source_geometry_payload = source_geometry.asWkt()
                geom = QgsGeometry(source_geometry)
                try:
                    if do_reproject:
                        geom.transform(transform)
                except Exception as error:
                    raise MetricContextError(
                        f"좌표 변환 실패: {layer.name()} 객체 {feat.id()}"
                    ) from error
                if geom.isNull() or geom.isEmpty():
                    invalid_geometry_exclusions += 1
                    continue
                if not geom.isGeosValid():
                    repaired = geom.makeValid()
                    if repaired and not repaired.isEmpty():
                        geom = repaired
                        geometry_repairs += 1
                    else:
                        invalid_geometry_exclusions += 1
                        continue
                if QgsWkbTypes.geometryType(geom.wkbType()) != layer.geometryType():
                    invalid_geometry_exclusions += 1
                    continue

                # Retrieve Attributes for filtering
                val_name = feat[name_field] if name_field else ""

                # [NEW] Check Exclusion List (Specific Blacklist)
                # If the name is in the user's exclusion list, skip it.
                if exclusion_list and val_name in exclusion_list:
                    # Log removed item occasionally?
                    # self.log(f"  - 사용자 제외: {val_name}")
                    continue

                # Check Category Filters (Legacy Reference Data)
                if self.should_exclude(val_name, filter_categories):
                    continue

                # The distribution-map workflow clips to its map extent. The
                # dedicated preservation workflow intentionally keeps all input
                # polygons and therefore passes no extent.
                if extent_geom is None or geom.intersects(extent_geom):
                    # [NEW FIX] Clip geometry to extent bounds
                    # This handles MultiPolygon features where parts are outside the extent
                    clipped_geom = (
                        geom.intersection(extent_geom)
                        if extent_geom is not None
                        else QgsGeometry(geom)
                    )
                    if clipped_geom.isEmpty():
                        continue  # No part inside extent
                    if (
                        layer.geometryType() == 2
                        and clip_filter_context
                    ):
                        clipped_bounds = clipped_geom.boundingBox()
                        if is_insignificant_extent_fragment(
                            original_area=geom.area(),
                            clipped_area=clipped_geom.area(),
                            clipped_width=clipped_bounds.width(),
                            clipped_height=clipped_bounds.height(),
                            **clip_filter_context,
                        ):
                            excluded_extent_slivers += 1
                            continue

                    # We exclude sites that are entirely within the study area (as they are 'internal')
                    # But we include ones that overlap or are outside
                    is_entirely_inside = clipped_geom.within(study_geom) if not study_geom.isNull() else False

                    if not is_entirely_inside:
                        # [FIX] Included internal sites as well (User Request: Prevent aggressive data loss)
                        # Originally: if not is_entirely_inside:
                        # Now: Allow all (since we clipped to extent already)
                        pass

                    if True:  # Always proceed if it intersects extent
                        new_feat = QgsFeature(subset_layer.fields())
                        new_feat.setGeometry(clipped_geom)  # Use clipped geometry

                        # [NEW] Attribute Extraction
                        val_name = feat[name_field] if name_field else ""
                        val_heritage = feat[heritage_name_field] if heritage_name_field else ""
                        val_project = feat[project_name_field] if project_name_field else ""
                        val_address = feat[addr_field] if addr_field else ""
                        native_code = (
                            feat[code_field]
                            if code_field and feat[code_field] is not None
                            else None
                        )
                        preservation_site_id = (
                            feat[preservation_site_id_field]
                            if (
                                preservation_site_id_field
                                and feat[preservation_site_id_field] is not None
                            ) else None
                        )
                        source_attributes = {
                            source_field.name(): _json_safe_attribute(
                                feat[source_field.name()]
                            )
                            for source_field in layer.fields()
                        }
                        source_identity = build_source_identity(
                            source_role,
                            native_code=native_code,
                            name=val_name,
                            project_name=val_project,
                            address=val_address,
                            geometry=source_geometry_payload,
                            extra_content=source_attributes,
                        )
                        raw_preservation_action = (
                            feat[preservation_action_field]
                            if preservation_action_field else ""
                        )
                        preservation_action = normalize_preservation_action(
                            raw_preservation_action
                        )
                        # [NEW] Filtering Logic
                        # 1. Smart Filter (Era/Type from JSON)
                        if self.should_exclude(val_name, filter_categories):  # filter_categories is actually 'filter_items' list
                            continue

                        # Group every record with the same project name before
                        # numbering. If the project field is empty, the helper
                        # falls back to heritage/site names and explicit area
                        # suffixes such as "I 지역" or "II-1,2,3지역".
                        grouping = resolve_heritage_group(
                            val_project,
                            val_name,
                            val_heritage,
                            fallback_key=source_identity.uid,
                            preservation_action=preservation_action,
                            preservation_number_scope=(
                                self._preservation_number_scope(
                                    layer,
                                    supplier_site_id=preservation_site_id,
                                    supplier_id_field=(
                                        preservation_site_id_field
                                    ),
                                    site_name=val_name,
                                    heritage_name=val_heritage,
                                    address=val_address,
                                )
                                if preservation_only else None
                            ),
                        )
                        display_name = grouping["display_name"]
                        investigation_key = (
                            f"{source_role}:{grouping['investigation_key']}"
                            if grouping.get("investigation_key")
                            else None
                        )
                        site_entity_key = (
                            f"{source_role}:{grouping['site_entity_key']}"
                        )
                        number_key = (
                            f"{source_role}:{grouping['number_key']}"
                        )
                        geometry_group_key = (
                            f"{source_role}:{grouping['geometry_group_key']}"
                        )

                        # Map attributes
                        new_feat["유적명"] = display_name if display_name else "N/A"
                        new_feat["주소"] = val_address or "N/A"
                        new_feat["국가유산명"] = val_heritage
                        # [NEW] Zone Intersection Check
                        val_zone = ""
                        if zone_spatial_index and zone_records:
                            zone_names = []
                            for zone_feature_id in sorted(
                                zone_spatial_index.intersects(
                                    clipped_geom.boundingBox()
                                )
                            ):
                                zone_record = zone_records.get(
                                    zone_feature_id
                                )
                                if not zone_record:
                                    continue
                                zone_geom, z_name = zone_record
                                if zone_geom.intersects(clipped_geom):
                                    if z_name:
                                        zone_names.append(str(z_name))
                            if zone_names:
                                val_zone = ", ".join(zone_names)

                        # Map attributes
                        new_feat["유적명"] = display_name if display_name else "N/A"
                        new_feat["주소"] = val_address or "N/A"
                        new_feat["국가유산명"] = val_heritage
                        new_feat["사업명"] = val_project
                        new_feat["허용기준"] = val_zone if val_zone else None
                        new_feat["보존조치"] = preservation_action or None
                        new_feat["SRC_NAME"] = val_name
                        new_feat["SRC_ACTION"] = raw_preservation_action
                        new_feat["SRC_COUNT"] = 1

                        source_record = dict(source_attributes)
                        source_record["_source_layer"] = layer.name()
                        source_record["_source_uid"] = source_identity.uid
                        new_feat["SRC_JSON"] = json.dumps(
                            [source_record],
                            ensure_ascii=False,
                            separators=(",", ":"),
                            default=str,
                        )

                        for source_name in copied_source_fields:
                            new_feat[source_name] = feat[source_name]

                        # This public field is a measurement, never an alias
                        # for an unverified supplier AREA column.  The original
                        # value is still preserved in its source field/SRC_JSON.
                        new_feat["면적_m2"] = (
                            clipped_geom.area()
                            if layer.geometryType() == 2 else 0.0
                        )

                        new_feat["원본레이어"] = layer.name()
                        new_feat["HERITAGE_CODE"] = (
                            str(native_code)
                            if native_code is not None
                            else None
                        )
                        new_feat["SRC_UID"] = source_identity.uid
                        new_feat["SRC_FP"] = (
                            source_identity.content_fingerprint
                        )
                        new_feat["SOURCE_ROLE"] = source_role
                        new_feat["INVESTIGATION_KEY"] = investigation_key
                        new_feat["SITE_ENTITY_KEY"] = site_entity_key
                        # ENTITY_KEY remains a documented compatibility alias.
                        new_feat["ENTITY_KEY"] = site_entity_key
                        new_feat["GEOMETRY_GROUP_KEY"] = geometry_group_key
                        new_feat["RELATION_KEY"] = None
                        new_feat["RELATION_TYPE"] = (
                            "legal_boundary_site"
                            if source_role == ROLE_PROTECTION_ZONE
                            else None
                        )
                        new_feat["MATCH_STATUS"] = (
                            STATUS_PROTECTION_ZONE
                            if source_role == ROLE_PROTECTION_ZONE
                            else STATUS_UNIQUE
                        )
                        new_feat["MATCH_SCORE"] = 0.0
                        new_feat["MATCH_RULE"] = None
                        new_feat["REP_SOURCE"] = source_role
                        new_feat["LINKED_IDS"] = None
                        new_feat["IS_REP"] = (
                            0
                            if source_role == ROLE_PROTECTION_ZONE
                            else 1
                        )
                        new_feat["NUMBER_KEY"] = (
                            ""
                            if source_role == ROLE_PROTECTION_ZONE
                            else number_key
                        )
                        new_feat["GROUP_KEY"] = geometry_group_key
                        new_features.append(new_feat)
                        fingerprint_records.append({
                            "role": source_role,
                            "content_fingerprint": (
                                source_identity.content_fingerprint
                            ),
                        })

            if new_features:
                fingerprint = selected_content_fingerprint(
                    fingerprint_records
                )
                duplicate_key = fingerprint
                previous = selected_fingerprints.get(duplicate_key)
                if previous:
                    previous_name = previous["name"]
                    self.log(
                        "  ⚠️ 동일 내용 레이어 감지: "
                        f"{layer.name()} = {previous_name}. "
                        "뒤의 레이어는 중복 수집하지 않습니다."
                    )
                    QMessageBox.warning(
                        self.dlg,
                        "동일 자료 중복 선택",
                        f"'{layer.name()}'과 '{previous_name}'의 도곽 내 "
                        "내용이 동일합니다.\n중복 번호를 막기 위해 "
                        f"'{layer.name()}'은 처리에서 제외합니다.",
                    )
                    self._record_excluded_layer(
                        layer,
                        "duplicate_content",
                        role=source_role,
                    )
                    self.move_layer_to_group(layer, src_group)
                    continue
                selected_fingerprints[duplicate_key] = {
                    "id": lid,
                    "name": layer.name(),
                }
                elapsed_seconds = time.perf_counter() - scan_started
                filter_label = (
                    "도곽 선필터"
                    if used_extent_filter
                    else "전체 확인"
                )
                processing_stats = getattr(
                    self,
                    "_current_processing_stats",
                    None,
                )
                if isinstance(processing_stats, dict):
                    processing_stats.setdefault("source_scans", []).append({
                        "layer": layer.name(),
                        "role": source_role,
                        "source_count": source_feature_count,
                        "bbox_candidate_count": candidate_feature_count,
                        "collected_count": len(new_features),
                        "extent_prefilter": used_extent_filter,
                        "elapsed_seconds": round(elapsed_seconds, 6),
                        "geometry_repairs": geometry_repairs,
                        "invalid_geometry_exclusions": (
                            invalid_geometry_exclusions
                        ),
                    })
                self.log(
                    f"  -> {filter_label}: 전체 {source_feature_count}건 중 "
                    f"후보 {candidate_feature_count}건, "
                    f"최종 {len(new_features)}개소 수집 "
                    f"({elapsed_seconds:.2f}초)"
                )
                subset_pr.addFeatures(new_features)
                temp_layers.append(subset_layer)
            else:
                elapsed_seconds = time.perf_counter() - scan_started
                processing_stats = getattr(
                    self,
                    "_current_processing_stats",
                    None,
                )
                if isinstance(processing_stats, dict):
                    processing_stats.setdefault("source_scans", []).append({
                        "layer": layer.name(),
                        "role": source_role,
                        "source_count": source_feature_count,
                        "bbox_candidate_count": candidate_feature_count,
                        "collected_count": 0,
                        "extent_prefilter": used_extent_filter,
                        "elapsed_seconds": round(elapsed_seconds, 6),
                        "geometry_repairs": geometry_repairs,
                        "invalid_geometry_exclusions": (
                            invalid_geometry_exclusions
                        ),
                    })
                self.log(
                    "  -> 영역 내 수집된 유적 없음. "
                    f"(전체 {source_feature_count}건 중 "
                    f"후보 {candidate_feature_count}건, "
                    f"{elapsed_seconds:.2f}초)"
                )
            if excluded_extent_slivers:
                processing_stats = getattr(
                    self,
                    "_current_processing_stats",
                    None,
                )
                if isinstance(processing_stats, dict):
                    processing_stats["excluded_extent_slivers"] = (
                        int(
                            processing_stats.get(
                                "excluded_extent_slivers",
                                0,
                            )
                        )
                        + excluded_extent_slivers
                    )
                self.log(
                    f"  -> 도곽 경계 미세 절단 조각 "
                    f"{excluded_extent_slivers}건 제외"
                )
            if geometry_repairs or invalid_geometry_exclusions:
                processing_stats = getattr(
                    self, "_current_processing_stats", None
                )
                if isinstance(processing_stats, dict):
                    processing_stats["geometry_repairs"] = int(
                        processing_stats.get("geometry_repairs", 0)
                    ) + geometry_repairs
                    processing_stats["invalid_geometry_exclusions"] = int(
                        processing_stats.get(
                            "invalid_geometry_exclusions", 0
                        )
                    ) + invalid_geometry_exclusions
                    if invalid_geometry_exclusions:
                        processing_stats.setdefault(
                            "excluded_layers", []
                        ).append({
                            "name": layer.name(),
                            "role": source_role,
                            "reason": "irreparable_geometry_features",
                            "excluded_feature_count": (
                                invalid_geometry_exclusions
                            ),
                        })
                self.log(
                    f"  -> 도형 복구 {geometry_repairs}건, "
                    f"복구 불가 제외 {invalid_geometry_exclusions}건"
                )

            self.move_layer_to_group(layer, src_group)

        if not temp_layers:
            return None

        # A QGIS vector layer has one geometry family.  Mixing point, line,
        # and polygon inputs in a single native:mergevectorlayers call can
        # silently coerce/drop geometries according to the first input layer.
        # Process each family independently and expose all resulting layers.
        family_inputs = {}
        for prepared_layer in temp_layers:
            family_inputs.setdefault(
                prepared_layer.geometryType(),
                [],
            ).append(prepared_layer)

        decision_store = None
        decision_store_path = None
        if not preservation_only and reuse_review_decisions:
            decision_store_path = self._review_decision_store_path()
            decision_store = DecisionStore.load(decision_store_path)
            if decision_store.load_status == "loaded":
                self.log(
                    "이전 검토 결정 불러오기 완료: "
                    f"{len(decision_store)}건"
                )
            elif decision_store.load_status in {
                "malformed",
                "unsupported_schema",
            }:
                self.log(
                    "⚠️ 기존 검토 결정 파일을 안전하게 무시하고 "
                    "새 검토로 진행합니다."
                )

        family_labels = {0: "점", 1: "선", 2: "면"}
        results = []
        for family in (2, 1, 0):
            inputs = family_inputs.get(family, [])
            if not inputs:
                continue
            results.append(self._finalize_prepared_geometry_family(
                inputs,
                target_crs=target_crs,
                preservation_only=preservation_only,
                match_preset=match_preset,
                matching_decision_provider=matching_decision_provider,
                reuse_review_decisions=reuse_review_decisions,
                decision_store=decision_store,
                decision_store_path=decision_store_path,
                family_label=(
                    family_labels[family]
                    if len(family_inputs) > 1 else ""
                ),
            ))

        if preservation_only:
            # The preservation workflow rejects non-polygons above.
            return results[0]["main"] if results else None

        main_layers = [item["main"] for item in results if item.get("main")]
        auxiliary = {}
        for key in ("suppressed", "protection", "audit"):
            auxiliary[f"{key}_layers"] = [
                item[key] for item in results if item.get(key)
            ]
            auxiliary[key] = (
                auxiliary[f"{key}_layers"][0]
                if auxiliary[f"{key}_layers"] else None
            )
        cross_family_result = self.apply_cross_family_matching(
            main_layers,
            preset=match_preset,
            decision_provider=matching_decision_provider,
            decision_store=decision_store,
            reuse_saved_decisions=reuse_review_decisions,
            policy_version=(
                f"{self._matching_policy_key(match_preset)}:cross-family-v1"
            ),
        )
        cross_audit = cross_family_result.get("audit")
        if cross_audit is not None:
            cross_audit.setName("중복_판정_검수표_형상계열간")
            auxiliary["audit_layers"].append(cross_audit)
            if auxiliary["audit"] is None:
                auxiliary["audit"] = cross_audit

        statistics = getattr(self, "_current_processing_stats", None)
        if not isinstance(statistics, dict):
            statistics = {}
            self._current_processing_stats = statistics
        statistics["duplicate_candidate_count"] = int(
            statistics.get("duplicate_candidate_count", 0)
        ) + int(cross_family_result.get("candidate_count", 0))
        statistics["decision_reuse_count"] = int(
            statistics.get("decision_reuse_count", 0)
        ) + int(cross_family_result.get("decision_reuse_count", 0))
        if (
            decision_store is not None
            and cross_family_result.get("decision_store_dirty")
        ):
            self._pending_decision_store = decision_store
            self._pending_decision_store_path = decision_store_path
            self._pending_decision_store_dirty = True
        return {
            "main": main_layers[0] if main_layers else None,
            "main_layers": main_layers,
            **auxiliary,
        }

    def _finalize_prepared_geometry_family(
        self,
        prepared_layers,
        *,
        target_crs,
        preservation_only,
        match_preset,
        matching_decision_provider,
        reuse_review_decisions,
        decision_store,
        decision_store_path,
        family_label="",
    ):
        """Merge, match, and dissolve one homogeneous geometry family."""
        suffix = f"_{family_label}" if family_label else ""
        self.log(f"최종 데이터 병합 처리 중{suffix}...")
        result = processing.run("native:mergevectorlayers", {
            "LAYERS": prepared_layers,
            "CRS": target_crs,
            "OUTPUT": "memory:Consolidated_Heritage",
        })
        merged_layer = result["OUTPUT"]
        auxiliary_layers = {
            "suppressed": None,
            "protection": None,
            "audit": None,
        }
        if preservation_only:
            self.aggregate_source_metadata(merged_layer)
        else:
            match_result = self.apply_source_aware_matching(
                merged_layer,
                preset=match_preset,
                decision_provider=matching_decision_provider,
                decision_store=decision_store,
                reuse_saved_decisions=reuse_review_decisions,
                policy_version=self._matching_policy_key(match_preset),
            )
            statistics = getattr(self, "_current_processing_stats", None)
            if not isinstance(statistics, dict):
                statistics = {}
                self._current_processing_stats = statistics
            statistics["duplicate_candidate_count"] = int(
                statistics.get("duplicate_candidate_count", 0)
            ) + int(match_result.get("candidate_count", 0))
            statistics["decision_reuse_count"] = int(
                statistics.get("decision_reuse_count", 0)
            ) + int(match_result.get("decision_reuse_count", 0))
            if (
                decision_store is not None
                and match_result.get("decision_store_dirty")
            ):
                self._pending_decision_store = decision_store
                self._pending_decision_store_path = decision_store_path
                self._pending_decision_store_dirty = True
            merged_layer = match_result["main"]
            auxiliary_layers = {
                "suppressed": match_result.get("suppressed"),
                "protection": match_result.get("protection"),
                "audit": match_result.get("audit"),
            }

        self.log(f"동일 형상 그룹의 분할 구역 병합 처리 중{suffix}...")
        fields = [field.name() for field in merged_layer.fields()]
        dissolve_field = "GROUP_KEY" if "GROUP_KEY" in fields else None
        if not dissolve_field:
            self.log("  ⚠️ GROUP_KEY가 없어 Dissolve를 건너뜁니다.")
            final_layer = merged_layer
        else:
            before_count = merged_layer.featureCount()
            try:
                dissolve_result = processing.run("native:dissolve", {
                    "INPUT": merged_layer,
                    "FIELD": [dissolve_field],
                    "OUTPUT": "memory:Dissolved_Heritage",
                })
                final_layer = dissolve_result["OUTPUT"]
                after_count = final_layer.featureCount()
                self.log(
                    f"Dissolve 완료{suffix}: {before_count} -> "
                    f"{after_count}개 (분할 {before_count - after_count}건 통합)"
                )
            except Exception as error:
                self.log(f"Dissolve 실패{suffix} (원본 사용): {error}")
                final_layer = merged_layer

        final_layer.setName(
            ("매장유산_유존지역" if preservation_only
             else "수집_및_병합된_주변유적") + suffix
        )
        for key, layer in auxiliary_layers.items():
            if layer is not None and suffix:
                layer.setName(f"{layer.name()}{suffix}")
        return {"main": final_layer, **auxiliary_layers}

    def number_heritage_layers_v4(
        self,
        layers,
        study_layer_or_centroid,
        sort_order,
        extent_geom=None,
        extent_crs=None,
        buffer_geoms=None,
        restrict_to_buffer=True,
        metric_context=None,
    ):
        """Assign one continuous number sequence across geometry families."""
        layers = [layer for layer in (layers or []) if layer is not None]
        if not layers:
            return {
                "number_group_count": 0,
                "numbered_feature_count": 0,
                "total_feature_count": 0,
            }
        if len(layers) == 1:
            return self.number_heritage_v4(
                layers[0],
                study_layer_or_centroid,
                sort_order,
                extent_geom,
                extent_crs,
                buffer_geoms,
                restrict_to_buffer,
                metric_context,
            )
        if metric_context is None:
            metric_context = self._build_metric_context(layers[0], {})
        buffer_geoms = list(buffer_geoms or [])

        base_analysis = None
        if isinstance(study_layer_or_centroid, QgsVectorLayer):
            combined = QgsGeometry()
            for feature in study_layer_or_centroid.getFeatures():
                if not feature.hasGeometry():
                    continue
                combined = (
                    QgsGeometry(feature.geometry())
                    if combined.isNull()
                    else combined.combine(feature.geometry())
                )
            if not combined.isNull():
                base_analysis = metric_context.to_analysis_geometry(
                    combined,
                    study_layer_or_centroid.crs(),
                )

        records = []
        layer_states = []
        for layer_index, layer in enumerate(layers):
            for field in (
                QgsField("이격거리(m)", QVariant.String),
                QgsField("DIST_M", QVariant.Double),
                QgsField("비고", QVariant.String),
                QgsField("LABEL_OK", QVariant.Int),
            ):
                if layer.fields().indexFromName(field.name()) < 0:
                    layer.dataProvider().addAttributes([field])
            layer.updateFields()
            indexes = {
                name: layer.fields().indexFromName(name)
                for name in (
                    "번호", "이격거리(m)", "비고", "LABEL_OK",
                    "NUMBER_KEY", "유적명", "SRC_UID", "DIST_M",
                )
            }
            target_extent = QgsGeometry(extent_geom) if extent_geom else None
            transformed_buffers = []
            if extent_crs and layer.crs() != extent_crs:
                transform = QgsCoordinateTransform(
                    extent_crs,
                    layer.crs(),
                    QgsProject.instance(),
                )
                if target_extent:
                    target_extent.transform(transform)
                for item in buffer_geoms:
                    geometry = QgsGeometry(item["geom"])
                    geometry.transform(transform)
                    transformed_buffers.append({
                        "dist": item["dist"],
                        "geom": geometry,
                    })
            else:
                transformed_buffers = [
                    {"dist": item["dist"], "geom": QgsGeometry(item["geom"])}
                    for item in buffer_geoms
                ]

            managed_subset = '"번호" IS NOT NULL'
            property_name = "ArchDistribution/renumber_base_subset"
            current_subset = layer.subsetString().strip()
            stored_subset = layer.customProperty(property_name, None)
            if stored_subset is not None:
                stored_subset = str(stored_subset).strip()
                expected = (
                    f"({stored_subset}) AND ({managed_subset})"
                    if stored_subset else managed_subset
                )
                if current_subset == expected:
                    base_subset = stored_subset
                    layer.setSubsetString(base_subset)
                else:
                    base_subset = current_subset
                    layer.removeCustomProperty(property_name)
            elif current_subset == managed_subset:
                base_subset = ""
                layer.setSubsetString("")
            else:
                base_subset = current_subset

            layer.startEditing()
            outside_ids = []
            for feature in layer.getFeatures():
                geometry = QgsGeometry(feature.geometry())
                if not geometry.isGeosValid():
                    fixed = geometry.makeValid()
                    if fixed and not fixed.isEmpty():
                        geometry = fixed
                        layer.changeGeometry(feature.id(), geometry)
                inside = True
                if target_extent:
                    inside = geometry.intersects(target_extent)
                    if inside and layer.geometryType() in (1, 2):
                        clipped = geometry.intersection(target_extent)
                        inside = (
                            not clipped.isEmpty()
                            and (
                                clipped.area() > 0
                                if layer.geometryType() == 2
                                else clipped.length() > 0
                            )
                        )
                if (
                    inside
                    and transformed_buffers
                    and restrict_to_buffer
                    and not geometry.intersects(
                        transformed_buffers[-1]["geom"]
                    )
                ):
                    inside = False
                if not inside:
                    layer.changeAttributeValue(
                        feature.id(), indexes["번호"], None
                    )
                    layer.changeAttributeValue(
                        feature.id(), indexes["이격거리(m)"], None
                    )
                    layer.changeAttributeValue(
                        feature.id(), indexes["DIST_M"], None
                    )
                    layer.changeAttributeValue(
                        feature.id(), indexes["비고"], "범위_밖"
                    )
                    layer.changeAttributeValue(
                        feature.id(), indexes["LABEL_OK"], 0
                    )
                    outside_ids.append(feature.id())
                    continue

                analysis_geometry = metric_context.to_analysis_geometry(
                    geometry,
                    layer.crs(),
                )
                distance = (
                    analysis_geometry.distance(base_analysis)
                    if base_analysis is not None else 0.0
                )
                tier = 0
                if transformed_buffers:
                    tier = len(transformed_buffers)
                    for tier_index, buffer_item in enumerate(
                        transformed_buffers
                    ):
                        if geometry.intersects(buffer_item["geom"]):
                            tier = tier_index
                            break
                name = str(
                    feature[indexes["유적명"]]
                    if indexes["유적명"] >= 0 else ""
                )
                raw_key = (
                    feature[indexes["NUMBER_KEY"]]
                    if indexes["NUMBER_KEY"] >= 0 else None
                )
                uid = (
                    feature[indexes["SRC_UID"]]
                    if indexes["SRC_UID"] >= 0 else None
                )
                number_key = str(
                    raw_key or uid or f"layer:{layer_index}:feature:{feature.id()}"
                )
                centroid = analysis_geometry.centroid().asPoint()
                if sort_order == 1:
                    sort_key = (
                        tier, distance, name.casefold(), layer_index,
                        feature.id(),
                    )
                    distance_text = f"{distance:.1f}m"
                elif sort_order == 0:
                    sort_key = (
                        -centroid.y(), centroid.x(), name.casefold(),
                        layer_index, feature.id(),
                    )
                    distance_text = None
                else:
                    sort_key = (
                        name.casefold(), -centroid.y(), centroid.x(),
                        layer_index, feature.id(),
                    )
                    distance_text = None
                weight = (
                    analysis_geometry.area()
                    if layer.geometryType() == 2
                    else analysis_geometry.length()
                    if layer.geometryType() == 1
                    else 0.0
                )
                records.append({
                    "layer": layer,
                    "feature_id": feature.id(),
                    "indexes": indexes,
                    "number_key": number_key,
                    "sort_key": sort_key,
                    "distance_text": distance_text,
                    "distance_m": distance,
                    "anchor_weight": weight,
                    "anchor_tiebreak": (layer_index, feature.id()),
                })
            layer_states.append({
                "layer": layer,
                "outside_ids": outside_ids,
                "base_subset": base_subset,
                "managed_subset": managed_subset,
                "property_name": property_name,
            })

        records.sort(key=lambda item: item["sort_key"])
        numbers = {}
        anchors = {}
        for record in records:
            key = record["number_key"]
            if key not in numbers:
                numbers[key] = len(numbers) + 1
            layer = record["layer"]
            indexes = record["indexes"]
            feature_id = record["feature_id"]
            layer.changeAttributeValue(
                feature_id, indexes["번호"], numbers[key]
            )
            layer.changeAttributeValue(feature_id, indexes["비고"], None)
            layer.changeAttributeValue(feature_id, indexes["LABEL_OK"], 0)
            layer.changeAttributeValue(
                feature_id,
                indexes["이격거리(m)"],
                record["distance_text"],
            )
            layer.changeAttributeValue(
                feature_id,
                indexes["DIST_M"],
                record["distance_m"],
            )
            anchor_score = (
                record["anchor_weight"],
                tuple(-value for value in record["anchor_tiebreak"]),
            )
            if key not in anchors or anchor_score > anchors[key][0]:
                anchors[key] = (anchor_score, record)

        for _score, record in anchors.values():
            record["layer"].changeAttributeValue(
                record["feature_id"],
                record["indexes"]["LABEL_OK"],
                1,
            )

        for state in layer_states:
            layer = state["layer"]
            layer.commitChanges()
            if state["outside_ids"]:
                visible = (
                    f"({state['base_subset']}) AND "
                    f"({state['managed_subset']})"
                    if state["base_subset"]
                    else state["managed_subset"]
                )
                layer.setCustomProperty(
                    state["property_name"], state["base_subset"]
                )
                layer.setSubsetString(visible)
            else:
                layer.setSubsetString(state["base_subset"])
                layer.removeCustomProperty(state["property_name"])

        self.log(
            f"  -> {len(numbers)}개 번호를 {len(layers)}개 형상 "
            f"레이어의 {len(records)}개 레코드에 연속 부여했습니다."
        )
        return {
            "number_group_count": len(numbers),
            "numbered_feature_count": len(records),
            "total_feature_count": sum(
                layer.featureCount() for layer in layers
            ),
        }

    def number_heritage_v4(
        self,
        layer,
        study_layer_or_centroid,
        sort_order,
        extent_geom=None,
        extent_crs=None,
        buffer_geoms=None,
        restrict_to_buffer=True,
        metric_context=None,
    ):
        """
        Sort features and assign numbers to '번호' field with Buffer Tiers.

        Args:
            study_layer_or_centroid: QgsVectorLayer of study area OR QgsPointXY (fallback).
            buffer_geoms: List of dicts [{'dist': 100, 'geom': QgsGeometry}, ...]. Sorted by distance.
            restrict_to_buffer (bool): If True, exclude features outside max buffer (set Number to NULL).
                                       If False, include them (Number them too), but buffer tiers still prioritize inners.
        """
        if buffer_geoms is None:
            buffer_geoms = []
        if metric_context is None:
            # Backward-compatible direct calls still receive metric distance
            # calculations.  Main workflows pass their already-fixed context.
            metric_context = self._build_metric_context(layer, {})
        idx = layer.fields().indexFromName("번호")

        # [NEW] Check/Add Distance Field
        dist_field_name = "이격거리(m)"
        if layer.fields().indexFromName(dist_field_name) == -1:
            layer.dataProvider().addAttributes([QgsField(dist_field_name, QVariant.String)])
        if layer.fields().indexFromName("DIST_M") == -1:
            layer.dataProvider().addAttributes([
                QgsField("DIST_M", QVariant.Double)
            ])

        # [NEW] Check/Add Note Field (For Human Verification)
        note_field_name = "비고"
        if layer.fields().indexFromName(note_field_name) == -1:
            layer.dataProvider().addAttributes([QgsField(note_field_name, QVariant.String)])

        label_anchor_field_name = "LABEL_OK"
        if layer.fields().indexFromName(label_anchor_field_name) == -1:
            layer.dataProvider().addAttributes([
                QgsField(label_anchor_field_name, QVariant.Int)
            ])

        layer.updateFields()
        dist_idx = layer.fields().indexFromName(dist_field_name)
        numeric_dist_idx = layer.fields().indexFromName("DIST_M")
        note_idx = layer.fields().indexFromName(note_field_name)
        label_anchor_idx = layer.fields().indexFromName(label_anchor_field_name)
        number_key_idx = layer.fields().indexFromName("NUMBER_KEY")

        # Prepare base geometry for precise distance calculation
        base_geom = None
        if isinstance(study_layer_or_centroid, QgsVectorLayer):
            # Merge study layer into one geometry
            combined = QgsGeometry()
            for f in study_layer_or_centroid.getFeatures():
                if combined.isNull():
                    combined = f.geometry()
                else:
                    combined = combined.combine(f.geometry())
            # Transform if needed? usually assume same CRS if passed from main logic
            if combined and not combined.isNull():
                base_geom = combined

        # Prepare transformation for Extent and Buffers
        target_extent = extent_geom
        transformed_buffers = []

        if extent_crs and layer.crs() != extent_crs:
            tr = QgsCoordinateTransform(extent_crs, layer.crs(), QgsProject.instance())
            try:
                if extent_geom:
                    target_extent = QgsGeometry(extent_geom)
                    target_extent.transform(tr)

                # Transform buffers
                for b in buffer_geoms:
                    bg = QgsGeometry(b['geom'])
                    bg.transform(tr)

                    # Also transform base_geom if it came from study_layer (which is in extent_crs usually)
                    # Wait, study_layer is from project, likely same as extent_crs.
                    # We need base_geom in LAYER crs for distance calculation.
                    transformed_buffers.append({'dist': b['dist'], 'geom': bg})

                if base_geom:
                    # base_geom is from study_layer. Its CRS is study_layer.crs() which IS extent_crs.
                    # So we need to transform it to layer.crs()
                    base_geom.transform(tr)

                self.log(f"좌표 변환 적용됨: {extent_crs.authid()} -> {layer.crs().authid()}")
            except Exception as error:
                raise MetricContextError(
                    "재번호 작업의 도곽·버퍼 좌표 변환에 실패했습니다."
                ) from error
        else:
            transformed_buffers = buffer_geoms  # No transform needed

        # Determine Max Limit Geometry (Largest Buffer)
        limit_geom = None
        if transformed_buffers:
            limit_geom = transformed_buffers[-1]['geom']  # Last one is largest

        # A previous numbering run may have applied our managed visibility
        # filter. Clear only that filter so an expanded extent can reconsider
        # records which were hidden by the earlier run. Preserve any filter
        # which the user had already applied.
        managed_subset = '"번호" IS NOT NULL'
        base_subset_property = (
            "ArchDistribution/renumber_base_subset"
        )
        initial_subset = layer.subsetString().strip()
        stored_base_subset = layer.customProperty(
            base_subset_property,
            None,
        )
        if stored_base_subset is not None:
            stored_base_subset = str(stored_base_subset).strip()
            expected_subset = (
                f"({stored_base_subset}) AND ({managed_subset})"
                if stored_base_subset
                else managed_subset
            )
            if initial_subset == expected_subset:
                base_subset = stored_base_subset
                layer.setSubsetString(base_subset)
            else:
                base_subset = initial_subset
                layer.removeCustomProperty(base_subset_property)
        elif initial_subset == managed_subset:
            base_subset = ""
            layer.setSubsetString("")
        else:
            base_subset = initial_subset

        layer.startEditing()

        # Collect all features
        ids_to_delete = []  # [FIX] Initialize early to collect outside features
        all_features = []
        for feat in layer.getFeatures():
            geom = feat.geometry()

            # [FIX] Robust Geometry Check
            if not geom.isGeosValid():
                geom = geom.makeValid()

            # [CHECK 1] Extent Intersection. For polygon and line results,
            # merely touching the frame at a point/edge is not a printable
            # intersection and must not receive a number.
            inside_extent = True
            if target_extent:
                inside_extent = geom.intersects(target_extent)
                if inside_extent and layer.geometryType() in (1, 2):
                    clipped_for_test = geom.intersection(target_extent)
                    if layer.geometryType() == 2:
                        inside_extent = (
                            not clipped_for_test.isEmpty()
                            and clipped_for_test.area() > 0
                        )
                    else:
                        inside_extent = (
                            not clipped_for_test.isEmpty()
                            and clipped_for_test.length() > 0
                        )
            if not inside_extent:
                layer.changeAttributeValue(feat.id(), idx, None)
                layer.changeAttributeValue(feat.id(), dist_idx, None)
                layer.changeAttributeValue(feat.id(), numeric_dist_idx, None)
                layer.changeAttributeValue(feat.id(), note_idx, "도곽_밖")
                layer.changeAttributeValue(feat.id(), label_anchor_idx, 0)
                ids_to_delete.append(feat.id())
                continue

            # [CHECK 2] Limit Geometry (Max Buffer) Intersection
            # If buffers exist AND restriction is enabled
            if limit_geom and restrict_to_buffer:
                if not geom.intersects(limit_geom):
                    layer.changeAttributeValue(feat.id(), idx, None)
                    layer.changeAttributeValue(feat.id(), dist_idx, None)
                    layer.changeAttributeValue(
                        feat.id(), numeric_dist_idx, None
                    )
                    layer.changeAttributeValue(feat.id(), note_idx, "버퍼_밖")
                    layer.changeAttributeValue(
                        feat.id(),
                        label_anchor_idx,
                        0,
                    )
                    ids_to_delete.append(feat.id())  # [FIX] Mark for deletion
                    continue

            # If restriction is OFF, we keep it even if outside buffer.
            # However, if it's OUTSIDE buffer, it won't be in any "Tier", so it ends up in 'remaining' list.
            # That's exactly what we want.

            all_features.append(feat)

        if ids_to_delete:
            self.log(f"  -> 초기 스캔에서 범위 밖 유적 {len(ids_to_delete)}개 식별됨 (삭제 예정).")

        # Sorting Logic
        sorted_features = []

        measurement_base_geom = None
        if base_geom:
            measurement_base_geom = metric_context.to_analysis_geometry(
                base_geom,
                layer.crs(),
            )
        measurement_origin = None
        if isinstance(study_layer_or_centroid, QgsPointXY):
            measurement_origin = metric_context.transform_point(
                study_layer_or_centroid,
                extent_crs or layer.crs(),
                metric_context.analysis_crs,
            )

        def get_dist(feat_geom):
            metric_geom = metric_context.to_analysis_geometry(
                feat_geom,
                layer.crs(),
            )
            if measurement_base_geom:
                return metric_geom.distance(measurement_base_geom)
            if measurement_origin is not None:
                point = metric_geom.centroid().asPoint()
                return ((point.x() - measurement_origin.x()) ** 2 +
                        (point.y() - measurement_origin.y()) ** 2) ** 0.5
            return 0.0

        if sort_order == 1:  # Closest to Study Area (Buffer Tiered)
            # We will process in Tiers if buffers exist

            # Calculate distances for ALL valid features first
            feat_dists = []
            for f in all_features:
                d = get_dist(f.geometry())
                feat_dists.append({'feat': f, 'dist': d, 'dist_str': f"{d:.1f}m"})

            if transformed_buffers:
                # Tiered Sorting
                # 1. Bucket features into rings
                # Ring 0: Inside Buffer 0
                # Ring 1: Inside Buffer 1 AND NOT Inside Buffer 0
                # ...
                # Actually, simpler:
                # Iterate buffers ascending. Assign feature to FIRST buffer it intersects.

                # Careful: 'intersects' checks geometry overlap.
                # Distance based check is cleaner if we trust distance?
                # But polygon buffers might handle holes/islands better.
                # Let's use Geometry Intersection for robustness with complex shapes.

                remaining = feat_dists[:]
                tiered_result = []

                for b_info in transformed_buffers:
                    b_geom = b_info['geom']
                    in_this_tier = []
                    next_remaining = []

                    for item in remaining:
                        # Check intersection
                        if item['feat'].geometry().intersects(b_geom):
                            in_this_tier.append(item)
                        else:
                            next_remaining.append(item)

                    # Sort this tier by distance
                    in_this_tier.sort(key=lambda x: x['dist'])
                    tiered_result.extend(in_this_tier)

                    remaining = next_remaining

                # If anything remains (shouldn't if limit_geom check worked, but floating point issues?)
                if remaining:
                    remaining.sort(key=lambda x: x['dist'])
                    tiered_result.extend(remaining)

                sorted_features = tiered_result

            else:
                # No buffers, just pure distance sort
                feat_dists.sort(key=lambda x: x['dist'])
                sorted_features = feat_dists

        elif sort_order == 0:  # Top-to-Bottom in the analysis CRS
            temp = [
                {
                    'feat': f,
                    'sort_val': -metric_context.to_analysis_geometry(
                        f.geometry(),
                        layer.crs(),
                    ).centroid().asPoint().y(),
                    'dist_str': None,
                    'dist': get_dist(f.geometry()),
                }
                for f in all_features
            ]
            temp.sort(key=lambda x: x['sort_val'])
            sorted_features = temp

        else:  # Alphabetical
            temp = [
                {
                    'feat': f,
                    'sort_val': f["유적명"],
                    'dist_str': None,
                    'dist': get_dist(f.geometry()),
                }
                for f in all_features
            ]
            temp.sort(key=lambda x: x['sort_val'])
            sorted_features = temp

        # Assign Numbers
        # If restrict_to_buffer is True:
        #   Assign IDs 1..N to features that have a valid 'dist' (inside buffer).
        #   Assign NULL to features outside (dist is None or large, but here 'sorted_features' contains ALL).
        # Wait, sorted_features contains 'feat_dists' items.
        # If restrict_to_buffer was handled in previous logic (limit_geom check),
        # then 'sorted_features' might still contain outside features if we didn't filter them out there.
        # Let's check `number_heritage_v4` logic:
        # It calculates distances for ALL features.
        # If buffers exist, it tiers them.
        # But it doesn't seem to explicitly exclude outside features from 'sorted_features' list in the sorting block above,
        # unless 'transformed_buffers' logic handles it.
        #
        # Actually, let's look at how we handle 'restrict_to_buffer'.
        # Previously we just set a subset string.
        # To fix gaps (28, 30...), we must ensure that the sequence 1,2,3 is assigned ONLY to the visible subset.

        # Assign Numbers
        # [FIX] Continuous Numbering Logic
        # We must ensure that only features INSIDE the buffer (if restricted) get numbers,
        # and that the numbers are sequential (1, 2, 3...) with no gaps.

        # [FIX] Delete Outside Features instead of hiding
        # Collect IDs to delete
        # ids_to_delete already initialized above

        # Identify Name Field for Soft Deduplication
        idx_name = layer.fields().indexOf("유적명")
        if idx_name == -1:
            idx_name = layer.fields().indexOf("명칭")  # Fallback

        # 1. First Pass: Identify and Number Inside Features
        current_id = 1
        number_by_key = {}
        label_anchor_by_key = {}
        label_anchor_area_by_key = {}

        # [FIX] Use correctly transformed limit geometry determined above (lines 1073-1075)
        # Verify limit_geom validity with restrict_to_buffer flag
        target_limit_geom = None
        if restrict_to_buffer and limit_geom:
            target_limit_geom = limit_geom

        for item in sorted_features:
            feat = item['feat']

            # [REMOVED] Aggressive Name-based Deduplication
            # User reported excessive feature loss (250 -> 150).
            # We strictly trust the input layer (which may have spatial duplicates if dissolve failed, but safer to keep).

            is_inside = True

            if target_limit_geom:
                if not feat.geometry().intersects(target_limit_geom):
                    is_inside = False

            if is_inside:
                raw_number_key = (
                    feat[number_key_idx] if number_key_idx >= 0 else None
                )
                number_key = str(raw_number_key or f"feature:{feat.id()}").strip()
                if number_key.casefold() in {"", "null", "none", "<null>"}:
                    number_key = f"feature:{feat.id()}"

                if number_key not in number_by_key:
                    number_by_key[number_key] = current_id
                    current_id += 1

                layer.changeAttributeValue(
                    feat.id(),
                    idx,
                    number_by_key[number_key],
                )
                layer.changeAttributeValue(feat.id(), note_idx, None)  # Clear note
                layer.changeAttributeValue(feat.id(), label_anchor_idx, 0)

                geom_area = feat.geometry().area()
                if geom_area > label_anchor_area_by_key.get(number_key, -1):
                    label_anchor_area_by_key[number_key] = geom_area
                    label_anchor_by_key[number_key] = feat.id()
            else:
                ids_to_delete.append(feat.id())
                # [FIX] Human Verification: Mark details instead of just deleting logic
                layer.changeAttributeValue(feat.id(), idx, None)  # No Number
                layer.changeAttributeValue(feat.id(), note_idx, "범위_밖")  # Mark reason
                layer.changeAttributeValue(feat.id(), label_anchor_idx, 0)

            if item.get('dist_str'):
                layer.changeAttributeValue(feat.id(), dist_idx, item['dist_str'])
            else:
                layer.changeAttributeValue(feat.id(), dist_idx, None)
            layer.changeAttributeValue(
                feat.id(),
                numeric_dist_idx,
                float(item.get('dist', get_dist(feat.geometry()))),
            )

        for feature_id in label_anchor_by_key.values():
            layer.changeAttributeValue(feature_id, label_anchor_idx, 1)

        layer.commitChanges()
        self.log(
            f"  -> {len(number_by_key)}개 고유 유적에 번호를 부여했습니다 "
            f"({len(sorted_features)}개 조치·도형 레코드)."
        )

        # 2. Hide Outside Features (Non-Destructive for Human Verification)
        if ids_to_delete:
            visible_subset = (
                f"({base_subset}) AND ({managed_subset})"
                if base_subset
                else managed_subset
            )
            layer.setCustomProperty(
                base_subset_property,
                base_subset,
            )
            layer.setSubsetString(visible_subset)

            self.log(f"범위 밖 유적 {len(ids_to_delete)}개를 숨김 처리했습니다. (삭제 안함)")
            self.log(" -> 확인 방법: 레이어 우클릭 > 필터 설정 > 지우기")
        else:
            layer.setSubsetString(base_subset)
            layer.removeCustomProperty(base_subset_property)

        return {
            "number_group_count": len(number_by_key),
            "numbered_feature_count": len(sorted_features),
            "total_feature_count": layer.featureCount(),
        }

    def create_preservation_action_renderer(
        self,
        layer,
        stroke_width,
        action_styles=None,
        opacity=1.0,
        field_name=None,
    ):
        """Create a configurable four-category preservation-action renderer."""
        if layer.geometryType() != 2:
            return None

        if field_name and layer.fields().indexFromName(field_name) < 0:
            field_name = None
        field_name = field_name or self.find_preservation_action_field(layer)
        if not field_name:
            return None

        field_idx = layer.fields().indexFromName(field_name)
        source_values = {
            normalize_preservation_action(value)
            for value in layer.uniqueValues(field_idx)
        }
        source_values.discard("")
        if not source_values.intersection(PRESERVATION_ACTION_STYLES):
            return None

        resolved_styles = {
            action: dict(default_style)
            for action, default_style in PRESERVATION_ACTION_STYLES.items()
        }
        if isinstance(action_styles, dict):
            for action, custom_style in action_styles.items():
                if action not in resolved_styles or not isinstance(
                    custom_style,
                    dict,
                ):
                    continue
                for color_key in ("fill_color", "outline_color"):
                    color = QColor(custom_style.get(color_key, ""))
                    if color.isValid():
                        resolved_styles[action][color_key] = color.name()

        try:
            opacity = min(1.0, max(0.0, float(opacity)))
        except (TypeError, ValueError):
            opacity = 1.0

        def fill_rgba(color_value):
            color = QColor(color_value)
            return (
                f"{color.red()},{color.green()},{color.blue()},"
                f"{int(round(opacity * 255))}"
            )

        categories = []
        for action, action_style in resolved_styles.items():
            symbol = QgsFillSymbol.createSimple({
                'color': fill_rgba(action_style['fill_color']),
                'outline_color': action_style['outline_color'],
                'outline_width': str(stroke_width),
                'outline_width_unit': 'MM',
            })
            categories.append(QgsRendererCategory(action, symbol, action))

        unknown_values = sorted(
            source_values.difference(PRESERVATION_ACTION_STYLES)
        )
        for value in unknown_values:
            symbol = QgsFillSymbol.createSimple({
                'color': fill_rgba('#D9D9D9'),
                'outline_color': '#FF0000',
                'outline_width': str(stroke_width),
                'outline_width_unit': 'MM',
            })
            categories.append(
                QgsRendererCategory(value, symbol, f"기타: {value}")
            )

        self.log(
            f"보존조치 4종 범례 적용: {field_name} "
            f"(현상보존/정밀발굴조사/시굴조사/표본조사)"
        )
        return QgsCategorizedSymbolRenderer(field_name, categories)

    def apply_heritage_style(self, layer, style, font_size=DEFAULT_LABEL_FONT_SIZE, font_family=DEFAULT_LABEL_FONT_FAMILY):
        """Apply complex symbology and labeling to heritage layer."""
        rgb_fill = QColor(style['fill_color'])
        rgba_fill = f"{rgb_fill.red()},{rgb_fill.green()},{rgb_fill.blue()},{int(style['opacity'] * 255)}"

        renderer = self.create_preservation_action_renderer(
            layer,
            style['stroke_width'],
            action_styles=style.get("preservation_action_styles"),
            opacity=style.get("opacity", 1.0),
            field_name=style.get("preservation_action_field"),
        )
        symbol = None
        if renderer is None and layer.geometryType() == 2:  # Polygon
            symbol = QgsFillSymbol.createSimple({
                'color': rgba_fill,
                'outline_color': style['stroke_color'],
                'outline_width': str(style['stroke_width']),
                'outline_width_unit': 'MM'
            })
        elif renderer is None and layer.geometryType() == 1:  # Line
            symbol = QgsLineSymbol.createSimple({
                'color': style['stroke_color'],
                'width': str(style['stroke_width']),
                'width_unit': 'MM'
            })

        if symbol:
            renderer = QgsSingleSymbolRenderer(symbol)

        if renderer:
            layer.setRenderer(renderer)
            layer.triggerRepaint()

        # Labeling for '번호'
        label_settings = QgsPalLayerSettings()
        if layer.fields().indexFromName("LABEL_OK") >= 0:
            label_settings.fieldName = (
                'CASE WHEN "LABEL_OK" = 1 THEN "번호" END'
            )
            label_settings.isExpression = True
        else:
            label_settings.fieldName = "번호"
        label_settings.enabled = True

        text_format = QgsTextFormat()
        # Use user-specified font
        font = QFont(font_family)
        if not font.exactMatch():
            font = QFont("Arial")
        font.setBold(True)
        font.setPointSize(font_size)

        text_format.setFont(font)
        text_format.setColor(QColor(0, 0, 0))  # Black text

        # Add a buffer (halo) - Removed for Illustrator compatibility as requested
        # (Halos often become separate complex paths in AI, solid black is easier to edit)
        from qgis.core import QgsTextBufferSettings
        buffer_settings = QgsTextBufferSettings()
        buffer_settings.setEnabled(False)  # Now Disabled
        text_format.setBuffer(buffer_settings)

        label_settings.setFormat(text_format)

        # Placement
        if layer.geometryType() == 2:  # Polygon
            label_settings.placement = QgsPalLayerSettings.Horizontal
        else:
            label_settings.placement = QgsPalLayerSettings.AroundPoint

        layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
        layer.setLabelsEnabled(True)

        layer.triggerRepaint()

    def apply_protection_zone_style(self, layer):
        """Render designated-heritage protection zones without numbering."""
        if not layer or layer.geometryType() != 2:
            return
        symbol = QgsFillSymbol.createSimple({
            "color": "0,0,0,0",
            "outline_color": "#2E8B57",
            "outline_width": "0.35",
            "outline_width_unit": "MM",
            "outline_style": "dash",
        })
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.setLabelsEnabled(False)
        layer.triggerRepaint()

    def apply_zone_categorical_style(self, layer):
        """Apply categorical style to Zone Layer based on '구역' or 'NAME' matching user legend."""
        field_name = self.find_field(layer, ['구역', '구역명', 'NAME', 'ZONENAME', 'ZONE', 'L3_CODE', 'A_L3_CODE', 'L2_CODE'])
        if not field_name:
            return

        # Exact Color Map based on User Image
        # 1, 2, 3, 4, 5, 6, 7, 8 -> Filled
        # 2-1, 2-2, 2-3, 2-4, 2-5, 2-6 -> Outline (No Brush)

    def split_and_style_zone_layer(self, layer, parent_group, extent_geom, limit_buffer_geom=None, source_crs=None):
        """
        Split Zone Layer into separate layers for each category, clip to extent (and buffer if requested),
        and apply specific single-symbol style.
        """
        layer_name = layer.name()
        self.log(f"DEBUG: Zone Layer '{layer_name}' Processing Started.")

        # Work from the selected layer instance.  Reloading from disk used to
        # lose pending edits, subset filters, memory sources, and user-selected
        # encodings.  A declared .cpg or explicit layer override is sufficient.
        self.fix_layer_encoding(layer)

        # 1. Identify Field
        field_name = self.find_field(layer, ['구역명', '구역', 'NAME', 'ZONENAME', 'ZONE', 'L3_CODE', 'A_L3_CODE', 'L2_CODE'])
        if not field_name:
            self.log("❌ 오류: 구역 필드 찾기 실패.")
            self.log(f"   - 현재 인코딩: {layer.dataProvider().encoding()}")
            self.log(f"   - 발견된 필드 목록: {[f.name() for f in layer.fields()]}")
            return

        self.log(f"DEBUG: 타겟 필드 식별됨 -> '{field_name}'")

        # 2. Define Style Map (Updated based on User Legend - Image Analysis)
        # 1구역 (Orange), 2구역 (Magenta) -> Filled
        # 2-X구역 -> Transparent Fill + Colored Outline (Thick)
        base_map = {
            # Filled Types (Standard)
            "1": {"fill": "#E67E22", "stroke": "#D35400", "width": 0.2, "style": "solid"},  # 1 (Orange)
            "2": {"fill": "#E056FD", "stroke": "#BE2EDD", "width": 0.2, "style": "solid"},  # 2 (Magenta)
            "3": {"fill": "#5D5FEF", "stroke": "#4834d4", "width": 0.2, "style": "solid"},  # 3 (Blue-Purple)
            "4": {"fill": "#C06C84", "stroke": "#A6586C", "width": 0.2, "style": "solid"},  # 4 (Rose)
            "5": {"fill": "#2ecc71", "stroke": "#27ae60", "width": 0.2, "style": "solid"},  # 5 (Green)
            "6": {"fill": "#e74c3c", "stroke": "#c0392b", "width": 0.2, "style": "solid"},  # 6 (Red)
            "7": {"fill": "#34D399", "stroke": "#1abc9c", "width": 0.2, "style": "solid"},  # 7 (Mint)
            "8": {"fill": "#f1c40f", "stroke": "#f39c12", "width": 0.2, "style": "solid"},  # 8 (Yellow)

            # Outline Types (2-X Sub-zones)
            # Fill: Transparent/Light Pink, Stroke: Specific Colors, Width: 0.8
            "2-1": {"fill": "#FFDDDD", "stroke": "#0000FF", "width": 0.8, "style": "solid", "opacity": 0.2},  # Blue Stroke, Faint Pink Fill
            "2-2": {"fill": "#FFDDDD", "stroke": "#008000", "width": 0.8, "style": "solid", "opacity": 0.2},  # Green Stroke
            "2-3": {"fill": "#FFDDDD", "stroke": "#C71585", "width": 0.8, "style": "solid", "opacity": 0.2},  # Magenta Stroke
            "2-4": {"fill": "#FFDDDD", "stroke": "#008080", "width": 0.8, "style": "solid", "opacity": 0.2},  # Teal Stroke
            "2-5": {"fill": "#FFDDDD", "stroke": "#8B4513", "width": 0.8, "style": "solid", "opacity": 0.2},  # Brown Stroke
            "2-6": {"fill": "#FFDDDD", "stroke": "#808000", "width": 0.8, "style": "solid", "opacity": 0.2},  # Olive Stroke
        }

        style_map = {}
        for k, v in base_map.items():
            style_map[k] = v
            style_map[f"{k}구역"] = v
            style_map[f"제{k}구역"] = v

        # 3. Prepare Clipping Geometries
        project_crs = QgsProject.instance().crs()
        layer_crs = layer.crs()
        if not source_crs:
            source_crs = project_crs

        self.log(f"DEBUG: CRS Info - Zone Layer: {layer_crs.authid()}, Source (Study): {source_crs.authid()}")

        local_extent = QgsGeometry(extent_geom) if extent_geom else None
        local_limit_buffer = QgsGeometry(limit_buffer_geom) if limit_buffer_geom else None

        if local_extent and (layer_crs != source_crs):
            self.log(f"DEBUG: CRS 불일치 감지. 변환 실행: {source_crs.authid()} -> {layer_crs.authid()}")
            xform = QgsCoordinateTransform(source_crs, layer_crs, QgsProject.instance())
            local_extent.transform(xform)
            if local_limit_buffer:
                local_limit_buffer.transform(xform)
        else:
            self.log(f"DEBUG: CRS 일치 ({layer_crs.authid()}). 변환 건너뜀.")

        if not local_extent:
            self.log("❌ 오류: 도곽(Extent) Geometry가 없습니다.")
            return

        # Expand extent slightly to avoid precision loss on the border
        safe_buffer_dist = SAFE_BUFFER_DIST_GEOGRAPHIC if layer_crs.isGeographic() else SAFE_BUFFER_DIST_PROJECTED
        safe_extent = local_extent.buffer(safe_buffer_dist, 5)

        clip_mask = safe_extent
        if local_limit_buffer:
            if not local_limit_buffer.isGeosValid():
                local_limit_buffer = local_limit_buffer.makeValid()
            if not local_limit_buffer.isEmpty():
                try:
                    clip_mask = safe_extent.intersection(local_limit_buffer)
                    if clip_mask.isEmpty():
                        self.log("⚠️ 경고: 버퍼와 도곽(Extent)의 교집합이 비어있습니다. 현상변경허용기준 레이어는 생성되지 않습니다.")
                        return
                    self.log("DEBUG: 버퍼 범위 내 자르기 적용됨.")
                except Exception as e:
                    self.log(f"⚠️ 경고: 버퍼 클립 실패. 도곽(Extent)만으로 진행합니다. ({e})")
                    clip_mask = safe_extent

        self.log(f"DEBUG: Clipping Mask Ready. BBox: {clip_mask.boundingBox().toString()}")

        # 4. Iterate and Split
        idx = layer.fields().indexFromName(field_name)
        if idx == -1:
            return

        # [REFACTOR] Single Pass Feature Collection (O(N))
        # prevents logic gaps between uniqueValues() and manually determining equality.
        from collections import defaultdict
        grouped_feats = defaultdict(list)

        all_feats_count = layer.featureCount()
        self.log(f"DEBUG: 총 피처 개수: {all_feats_count}")

        for f in layer.getFeatures():
            v = f.attributes()[idx]
            if v is None:
                continue

            # Normalize Key
            val_str = str(v).strip()

            # Handle float/int mismatch (e.g. "1.0" vs "1") if necessary,
            # usually str() is enough, but to be safe:
            if isinstance(v, float) and v.is_integer():
                val_str = str(int(v))

            grouped_feats[val_str].append(f)

        self.log(f"DEBUG: 그룹화 완료. 총 {len(grouped_feats)}개 그룹 생성됨.")

        # Sort keys for consistent processing order
        sorted_keys = sorted(grouped_feats.keys())

        for val_str in sorted_keys:
            subset_feats = grouped_feats[val_str]
            # self.log(f"DEBUG: Processing Group '{val_str}' (Count: {len(subset_feats)})")

            # 4.2 Clip Logic
            clipped_feats = []
            for f in subset_feats:
                geom = f.geometry()
                # [FIX] Robust Geometry Check
                if not geom.isGeosValid():
                    geom = geom.makeValid()

                # Check Intersection with Clip Mask (Extent or Extent∩Buffer)
                if geom.intersects(clip_mask):
                    try:
                        res = geom.intersection(clip_mask)
                        if not res.isGeosValid():
                            res = res.makeValid()

                        # [FIX] Handle Mixed Geometry Types (Collection)
                        # If intersection grazing edge returns LineString/Point, we must discard those
                        # but KEEP any Polygon parts.
                        final_geom = QgsGeometry()
                        if res.isEmpty():
                            # If intersection is empty but intersects() was true, it's likely a grazing touch.
                            pass
                        else:
                            if QgsWkbTypes.geometryType(res.wkbType()) == QgsWkbTypes.PolygonGeometry:
                                final_geom = res
                            elif QgsWkbTypes.isMultiType(res.wkbType()) and QgsWkbTypes.geometryType(res.wkbType()) == QgsWkbTypes.PolygonGeometry:
                                final_geom = res
                            elif res.isMultipart():
                                # Collection or Multi-Type with mixed (unlikely but possible from makeValid)
                                parts = []
                                for part in res.asGeometryCollection():
                                    if QgsWkbTypes.geometryType(part.wkbType()) == QgsWkbTypes.PolygonGeometry:
                                        parts.append(part)
                                if parts:
                                    final_geom = QgsGeometry.fromMultiPolygonXY([p.asPolygon() for p in parts])
                            else:
                                # Single non-polygon (Line/Point) -> Discard
                                pass

                        if not final_geom.isEmpty():
                            # [FIX] Force MultiPolygon conversion
                            if not QgsWkbTypes.isMultiType(final_geom.wkbType()):
                                final_geom.convertToMultiType()

                            nf = QgsFeature(f)
                            nf.setGeometry(final_geom)
                            clipped_feats.append(nf)
                    except Exception as e:
                        self.log(f"   -> Geometry Error: {e}")

            if not clipped_feats:
                continue

            # Create Memory Layer
            crs_def = layer.crs().authid()
            if not crs_def:
                crs_def = layer.crs().toWkt()

            vl = QgsVectorLayer(f"MultiPolygon?crs={crs_def}", val_str, "memory")
            if not vl.isValid():
                continue

            pr = vl.dataProvider()
            pr.addAttributes(layer.fields())
            vl.updateFields()
            pr.addFeatures(clipped_feats)
            vl.updateExtents()

            # 4.4 Apply Style
            # Find matching style
            norm_val = val_str.replace("구역", "").replace(" ", "").strip()
            style = None

            # [FIX: Strict 2-X Matching]
            # Detect pattern "2-X" (handles -, space, dot, underscore)
            import re
            match_2x = re.search(r"2[-\s._]+(\d+)", val_str)
            if match_2x:
                sub_code = match_2x.group(1)
                target_key = f"2-{sub_code}"
                if target_key in style_map:
                    style = style_map[target_key]
                else:
                    self.log(f"   -> Regex Matched '2-{sub_code}' but not in style map.")

            if not style:
                if val_str in style_map:
                    style = style_map[val_str]
                elif norm_val in style_map:
                    style = style_map[norm_val]
                else:
                    for k, v in sorted(style_map.items(), key=lambda item: len(item[0]), reverse=True):
                        if k in val_str and len(k) > 0:
                            style = v
                            break

            if style:
                # Apply Style with Opacity
                opacity = style.get('opacity', 0.4)  # Default 0.4 (40%)

                symbol = QgsFillSymbol.createSimple({'outline_style': 'solid', 'style': 'solid'})

                # Check if it's "transparent" fill or actual color
                fill_col = style['fill']
                if fill_col == 'transparent':
                    symbol.setColor(QColor(0, 0, 0, 0))  # Transparent
                else:
                    symbol.setColor(QColor(fill_col))

                symbol.setOpacity(opacity)

                symbol.symbolLayer(0).setStrokeColor(QColor(style['stroke']))
                symbol.symbolLayer(0).setStrokeWidth(style['width'])
                vl.setRenderer(QgsSingleSymbolRenderer(symbol))
            else:
                pass

            vl.triggerRepaint()

            # 4.5 Add to Group
            QgsProject.instance().addMapLayer(vl, False)
            parent_group.addLayer(vl)

        parent_group.setExpanded(True)
        parent_group.setItemVisibilityChecked(True)

        # [UX] Move original input layer to Source Group
        try:
            root = QgsProject.instance().layerTreeRoot()
            src_group = root.findGroup("ArchDistribution_원본_데이터")
            if not src_group:
                src_group = root.addGroup("ArchDistribution_원본_데이터")

            # Find the layer node
            my_node = root.findLayer(layer.id())
            if my_node:
                my_clone = my_node.clone()
                src_group.addChildNode(my_clone)
                # Remove from original position to prevent duplicate (or just leave it? User said "grouped together")
                # Usually better to move.
                parent = my_node.parent()
                parent.removeChildNode(my_node)
                self.log("   -> 원본 현상변경허용기준 레이어를 'ArchDistribution_원본_데이터' 그룹으로 이동했습니다.")
        except Exception as e:
            self.log(f"WARNING: 레이어 이동 실패: {e}")

        self.log(f"  -> 현상변경 허용구간 레이어 분할 완료 ({parent_group.name()} 그룹 확인).")
