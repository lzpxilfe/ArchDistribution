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
                       QgsPrintLayout, QgsLayoutItemMap, QgsLayoutPoint,
                       QgsLayoutSize, QgsUnitTypes, QgsLayoutExporter)

import json
import hashlib
import os.path
import processing
import time
from datetime import datetime

from .cartographic_filtering import is_insignificant_extent_fragment
from .arch_distribution_dialog import ArchDistributionDialog, get_plugin_version
from .heritage_grouping import resolve_heritage_group
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
    evaluate_candidate,
    is_designated_role,
    selected_content_fingerprint,
    source_priority,
)
from .heritage_matching_dialog import DuplicateReviewDialog
from .heritage_identity_store import DecisionStore, build_source_identity
from .preservation_actions import (
    PRESERVATION_ACTION_FIELD_CANDIDATES,
    PRESERVATION_ACTION_STYLES,
    normalize_preservation_action,
    recognized_preservation_actions,
)
from .run_artifacts import (
    build_run_manifest,
    normalize_filename,
    prepare_artifact_paths,
    prepare_output_path,
    save_manifest_atomic,
)

DEFAULT_ENCODING = "CP949"
DEFAULT_LABEL_FONT_FAMILY = "Malgun Gothic"
DEFAULT_LABEL_FONT_SIZE = 10
DEFAULT_ZOOM_PADDING_RATIO = 0.08
DEFAULT_PROGRESS_STEPS = 10
DEGENERATE_PAD_GEOGRAPHIC = 1
DEGENERATE_PAD_PROJECTED = 10
STUDY_BUFFER_SEGMENTS = 20
PROCESSING_BUFFER_SEGMENTS = 50
DEFAULT_EXTENT_FALLBACK_CRS = "EPSG:5186"
TOPO_BOUNDARY_EXCLUDE_CODE = "H0017334"
SAFE_BUFFER_DIST_GEOGRAPHIC = 0.000001
SAFE_BUFFER_DIST_PROJECTED = 0.01
MATCH_POLICY_VERSION = "source-aware-v1"


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
            log_path = os.path.join(self.plugin_dir, 'latest_log.txt')
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(full_msg + "\n")
        except Exception as e:
            print(f"Log file error: {e}")

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
            log_path = os.path.join(self.plugin_dir, 'latest_log.txt')
            with open(log_path, 'w', encoding='utf-8') as f:
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

            # CRS Validation
            if original_study_layer.crs().isGeographic():
                self.log("경고: 지리좌표계(도 단위) 감지됨. 정밀 계산을 위해 투영좌표계 사용을 권장합니다.")

            # Create a clone in memory for the results group
            study_result_layer = QgsVectorLayer(f"{'Polygon' if original_study_layer.geometryType() == 2 else 'LineString'}?crs={original_study_layer.crs().toWkt()}", "00_조사구역", "memory")
            study_result_pr = study_result_layer.dataProvider()

            # Copy all features
            new_feats = []
            for f in original_study_layer.getFeatures():
                nf = QgsFeature(f)
                new_feats.append(nf)
            study_result_pr.addFeatures(new_feats)
            study_result_layer.updateExtents()

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
            current_step += 1
            progress.setValue(current_step)

            # Step 4: Centroid & Extent
            self.log("도곽(Extent) 영역 계산 중...")
            centroid = self.get_study_area_centroid(original_study_layer)
            if not centroid:
                self.log("오류: 조사지역의 데이터가 비어있거나 중심점을 계산할 수 없습니다.")
                return

            self.log(f"중심점 기반 도곽 생성 중 (Scale 1:{settings['scale']})...")
            extent_geom = self.create_extent_polygon(centroid, settings['paper_width'], settings['paper_height'], settings['scale'], ext_group, original_study_layer.crs())
            extent_bounds = extent_geom.boundingBox()
            extent_unit = QgsUnitTypes.toAbbreviatedString(
                original_study_layer.crs().mapUnits()
            )
            self.log(
                "도곽 생성 완료: "
                f"{settings['paper_width']}x{settings['paper_height']} mm "
                f"(1:{settings['scale']}) → "
                f"{extent_bounds.width():,.1f}x"
                f"{extent_bounds.height():,.1f} {extent_unit}, "
                f"{original_study_layer.crs().authid()}"
            )
            project_crs = QgsProject.instance().crs()
            if project_crs != original_study_layer.crs():
                self.log(
                    "안내: 프로젝트 화면 CRS와 도곽 CRS가 다릅니다. "
                    f"화면={project_crs.authid()}, "
                    f"도곽·수집={original_study_layer.crs().authid()}. "
                    "ArchDistribution 자동 인쇄조판은 도곽 CRS를 "
                    "사용합니다. 수동 인쇄조판도 지도 항목 CRS를 "
                    f"{original_study_layer.crs().authid()}로 설정하세요."
                )
            current_step += 1
            progress.setValue(current_step)

            # Step 5: Buffers
            if settings['buffers']:
                self.log(f"버퍼 생성 시작 ({len(settings['buffers'])}개)...")
                for distance in settings['buffers']:
                    if progress.wasCanceled():
                        raise ProcessingCancelled()
                    self.create_buffer(original_study_layer, distance, buf_group, settings['buffer_style'])
                    self.log(f"{distance}m 버퍼 생성 완료.")
                current_step += 1
                progress.setValue(current_step)

            # Step 6: Heritage Consolidation & Numbering
            if settings['heritage_layer_ids']:
                self.log("주변 유적 데이터 수집 및 병합 시작...")

                # [FIX] Pre-fetch Zone Layer and fix encoding (CP949 default)
                # User reported that this layer often has encoding issues.
                zone_layer_obj = None
                if settings.get('zone_layer_id'):
                    zone_layer_obj = QgsProject.instance().mapLayer(settings.get('zone_layer_id'))
                    if zone_layer_obj:
                        self.fix_layer_encoding(zone_layer_obj, DEFAULT_ENCODING)

                consolidation = self.consolidate_heritage_layers(
                    settings['heritage_layer_ids'],
                    extent_geom,
                    original_study_layer,
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
                    suppressed_layer = consolidation.get("suppressed")
                    protection_layer = consolidation.get("protection")
                    audit_layer = consolidation.get("audit")
                else:
                    merged_heritage = consolidation
                    suppressed_layer = None
                    protection_layer = None
                    audit_layer = None

                if merged_heritage:
                    self.log(f"병합 완료 ({merged_heritage.featureCount()}개소).")

                    buffer_geoms = []
                    if settings.get('buffers'):
                        combined_study = QgsGeometry()
                        for f in original_study_layer.getFeatures():
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
                    self.number_heritage_v4(
                        merged_heritage,
                        original_study_layer,
                        settings['sort_order'],
                        extent_geom,
                        original_study_layer.crs(),
                        buffer_geoms,
                        restrict_to_buffer=settings.get('restrict_to_buffer', True)
                    )
                    self.log("유적 번호 부여 완료. 스타일 및 라벨 적용 중...")
                    self.apply_heritage_style(
                        merged_heritage,
                        settings['heritage_style'],
                        font_size=settings.get('label_font_size', DEFAULT_LABEL_FONT_SIZE),
                        font_family=settings.get('label_font_family', DEFAULT_LABEL_FONT_FAMILY)
                    )

                    QgsProject.instance().addMapLayer(merged_heritage, False)
                    her_group.addLayer(merged_heritage)
                    self.log("최종 결과 유적 레이어 등록 완료.")

                    if (
                        protection_layer
                        and protection_layer.featureCount() > 0
                    ):
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

                    if (
                        suppressed_layer
                        and suppressed_layer.featureCount() > 0
                    ):
                        QgsProject.instance().addMapLayer(
                            suppressed_layer,
                            False,
                        )
                        audit_group.addLayer(suppressed_layer)
                    if audit_layer and audit_layer.featureCount() > 0:
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
                            self.log("현상변경 허용구간 레이어 분할 및 스타일 적용 중... (v1.2.0 Split Active)")

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
                                source_crs=original_study_layer.crs()
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
                extent_crs=original_study_layer.crs(),
                padding_ratio=DEFAULT_ZOOM_PADDING_RATIO,
            )
            self._commit_output_transaction()
            transaction_committed = True
            self._run_optional_outputs(
                settings,
                out_group,
                extent_geom,
                original_study_layer.crs(),
                "distribution_map",
                run_started_at,
            )
            self._save_pending_decision_store()
            self.log("모든 작업이 성공적으로 완료되었습니다.")

            # Notify Log File
            self.log(f"로그 파일 저장됨: {os.path.join(self.plugin_dir, 'latest_log.txt')}")
            self.iface.messageBar().pushMessage("ArchDistribution", "작업 완료", level=0)

        except DuplicateReviewCancelled:
            self.log("사용자가 실행 전 중복 검토를 취소했습니다.")
            self.iface.messageBar().pushMessage(
                "ArchDistribution",
                "중복 검토가 취소되어 결과를 만들지 않았습니다.",
                level=1,
            )
        except ProcessingCancelled:
            self.log("사용자가 데이터 처리를 중단했습니다.")
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
            log_path = os.path.join(self.plugin_dir, 'latest_log.txt')
            with open(log_path, 'w', encoding='utf-8') as log_file:
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

            centroid = self.get_study_area_centroid(study_layer)
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
                f"{QgsUnitTypes.toAbbreviatedString(study_layer.crs().mapUnits())}, "
                f"{study_layer.crs().authid()}"
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
                study_layer,
                src_group,
                preservation_only=True,
                preservation_action_fields={
                    source_layer.id(): action_field,
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
                study_layer,
                settings.get("preservation_sort_order", 0),
                extent_geom=extent_geom,
                extent_crs=study_layer.crs(),
                buffer_geoms=[],
                restrict_to_buffer=False,
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
                extent_crs=study_layer.crs(),
                padding_ratio=DEFAULT_ZOOM_PADDING_RATIO,
            )
            progress.setValue(5)
            if progress.wasCanceled():
                raise ProcessingCancelled()
            self._commit_output_transaction()
            transaction_committed = True
            self._run_optional_outputs(
                settings,
                out_group,
                extent_geom,
                study_layer.crs(),
                "preservation_area",
                run_started_at,
            )
            self.iface.messageBar().pushMessage(
                "ArchDistribution",
                "매장유산 유존지역 생성 완료",
                level=0,
            )
        except ProcessingCancelled:
            self.log(
                "사용자가 매장유산 유존지역 처리를 중단했습니다."
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

            # 2. Get Centroid (if needed)
            centroid = None
            study_layer = None
            if settings['study_area_id']:
                study_layer = QgsProject.instance().mapLayer(settings['study_area_id'])
                if study_layer:
                    centroid = self.get_study_area_centroid(study_layer)

            # [FIX] If no study layer, use layer's own extent center as centroid for extent calculation
            if not centroid:
                layer_extent = layer.extent()
                if not layer_extent.isEmpty():
                    centroid = layer_extent.center()
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
            if settings.get('buffers') and study_layer:
                combined_study = QgsGeometry()
                for f in study_layer.getFeatures():
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
            # Pass study_layer.crs() if available, else layer.crs()
            extent_crs = study_layer.crs() if study_layer else layer.crs()
            # If study_layer is missing, pass centroid as fallback
            numbering_summary = self.number_heritage_v4(
                layer,
                study_layer if study_layer else centroid,
                sort_order,
                extent_geom,
                extent_crs,
                buffer_geoms,
                restrict_to_buffer=settings.get('restrict_to_buffer', True)
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

    @staticmethod
    def _artifact_layer_summary(layer, *, role=None, kind=None):
        summary = {
            "name": layer.name(),
            "layer_id": layer.id(),
            "source": layer.source(),
            "provider": layer.providerType(),
            "crs": layer.crs().authid() or layer.crs().toWkt(),
            "geometry_type": QgsWkbTypes.displayString(layer.wkbType()),
            "feature_count": layer.featureCount(),
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
        for layer_id, role in entries:
            if not layer_id or layer_id in seen:
                continue
            seen.add(layer_id)
            layer = project.mapLayer(layer_id)
            if layer is not None and layer.type() == 0:
                summaries.append(
                    self._artifact_layer_summary(layer, role=role)
                )
        return summaries

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
            return {}

        output_directory = str(
            settings.get("output_directory") or ""
        ).strip()
        if not output_directory:
            self.log("⚠️ 선택 출력이 켜졌지만 저장 폴더가 비어 있습니다.")
            return {}

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
                processing_stats.update({
                    "artifacts": artifact_paths,
                    "artifact_errors": artifact_errors,
                    "gpkg_layers": gpkg_layers,
                })
                manifest = build_run_manifest(
                    plugin_version=get_plugin_version(),
                    workflow=workflow,
                    settings=settings,
                    input_layers=input_summaries,
                    output_layers=output_summaries,
                    processing_stats=processing_stats,
                    decision_reuse_count=int(
                        processing_stats.get(
                            "decision_reuse_count",
                            0,
                        )
                    ),
                    status="success",
                    started_at=run_started_at,
                    finished_at=datetime.now().astimezone(),
                )
                save_manifest_atomic(manifest, manifest_path)
                artifact_paths.append(str(manifest_path))
                self.log(f"실행정보 저장 완료: {manifest_path}")
        except Exception as exc:
            # These are optional post-commit artifacts. The successful QGIS
            # result group must remain available even if a filesystem or
            # exporter error occurs.
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

    def fix_layer_encoding(self, layer, encoding=DEFAULT_ENCODING):
        """Force specific encoding to fix broken Korean characters."""
        if layer and layer.type() == 0:  # VectorLayer
            layer.setProviderEncoding(encoding)
            layer.dataProvider().setEncoding(encoding)
            # Reload to apply
            layer.dataProvider().reloadData()
            layer.updateFields()
            layer.triggerRepaint()

    def merge_and_style_topo(self, layer_ids, target_group, src_group, style):
        """Merge selected topo layers and apply custom style."""
        layers = []
        for lid in layer_ids:
            layer = QgsProject.instance().mapLayer(lid)
            if layer:
                # [FIX] Filter for Line Layers Only (Topo is usually lines)
                if layer.geometryType() != 1:  # 0:Point, 1:Line, 2:Polygon
                    self.log(f"  ⚠️ 지형도 병합 제외 (라인 레이어 아님): {layer.name()}")
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

        # Create a memory layer for the extent using the study layer's CRS (use WKT for maximum compatibility)
        vl = QgsVectorLayer(f"Polygon?crs={crs.toWkt()}", "도곽_Extent", "memory")
        if not vl.isValid():
            vl = QgsVectorLayer(f"Polygon?crs={DEFAULT_EXTENT_FALLBACK_CRS}", "도곽_Extent", "memory")

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
            records = group_records.get(key, [])
            payload = json.dumps(
                records,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
            for feature_id in feature_ids:
                layer.changeAttributeValue(feature_id, count_idx, len(records))
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
            QgsField("DIST_M", QVariant.Double),
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
            feature["DIST_M"] = candidate.get("distance")
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
            else f"{MATCH_POLICY_VERSION}:{preset}"
        )
        required = (
            "SRC_UID",
            "SOURCE_ROLE",
            "ENTITY_KEY",
            "RELATION_KEY",
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
            geometries[feature.id()] = geom
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
            spatial_index.addFeature(feature)
        layer.commitChanges()

        if invalid_fixed:
            self.log(
                f"중복 판정 전 잘못된 도형 {invalid_fixed}건을 복구했습니다."
            )

        is_geographic = layer.crs().isGeographic()
        tolerance = 0.0007 if is_geographic else 50.0
        distance_measure = None
        if is_geographic:
            distance_measure = QgsDistanceArea()
            distance_measure.setSourceCrs(
                layer.crs(),
                QgsProject.instance().transformContext(),
            )
            distance_measure.setEllipsoid(layer.crs().ellipsoidAcronym())
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
                    if intersects:
                        distance = 0.0
                    elif distance_measure:
                        point_a = geom.nearestPoint(other_geom).asPoint()
                        point_b = other_geom.nearestPoint(geom).asPoint()
                        distance = distance_measure.measureLine(
                            point_a,
                            point_b,
                        )
                    else:
                        distance = geom.distance(other_geom)
                    overlap_ratio = 0.0
                    if intersects:
                        intersection = geom.intersection(other_geom)
                        if (
                            intersection
                            and not intersection.isEmpty()
                        ):
                            min_area = min(geom.area(), other_geom.area())
                            if min_area > 0:
                                overlap_ratio = (
                                    intersection.area() / min_area
                                )
                            else:
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
                ).append(record["uid"])
        for feature_id, record in records.items():
            if record["role"] != ROLE_PROTECTION_ZONE or not record["code"]:
                continue
            for target_uid in designated_by_code.get(record["code"], []):
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

        layer.startEditing()
        for item in decisions:
            left_uid = str(item["left_uid"])
            right_uid = str(item["right_uid"])
            decision = item.get("decision", DECISION_KEEP)
            relation_key = self._relation_key(left_uid, right_uid)
            for uid, other_uid in (
                (left_uid, right_uid),
                (right_uid, left_uid),
            ):
                linked_ids.setdefault(uid, set()).add(other_uid)
                relation_keys.setdefault(uid, set()).add(relation_key)
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

                entity_key = representative[indexes["ENTITY_KEY"]]
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
                continue
            if preservation_only and layer.geometryType() != 2:
                self.log(
                    f"  ⚠️ 폴리곤이 아니므로 유존지역 처리에서 제외: "
                    f"{layer.name()}"
                )
                continue

            self.log(f"데이터 수취 및 필드 맵핑 중: {layer.name()}")
            self.fix_layer_encoding(layer)
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
                    continue

            heritage_name_field = self.find_field(layer, ['국가유산명', '문화재명', '지정명칭'])  # Keep specific for attribute extraction
            addr_field = self.find_field(layer, ['주소', '지번', '소재지', 'ADDR', 'LOC'])
            area_field = self.find_field(layer, ['면적', 'AREA', 'SHAPE_AREA'])
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
                QgsField("국가유산명", QVariant.String),  # [NEW]
                QgsField("사업명", QVariant.String),     # [NEW]
                QgsField("허용기준", QVariant.String),   # [NEW] Zone Info
                QgsField("원본레이어", QVariant.String),
                QgsField("HERITAGE_CODE", QVariant.String),
                QgsField("SRC_UID", QVariant.String),
                QgsField("SRC_FP", QVariant.String),
                QgsField("SOURCE_ROLE", QVariant.String),
                QgsField("ENTITY_KEY", QVariant.String),
                QgsField("RELATION_KEY", QVariant.String),
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
            source_feature_count = layer.featureCount()
            candidate_feature_count = 0
            scan_started = time.perf_counter()
            code_field = self.find_field(
                layer,
                ["유산코드", "HERITAGE_CODE", "CODE"],
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
                    continue

                source_geometry = QgsGeometry(feat.geometry())
                try:
                    source_geometry_payload = bytes(source_geometry.asWkb())
                except (TypeError, ValueError):
                    source_geometry_payload = source_geometry.asWkt()
                geom = QgsGeometry(source_geometry)
                if do_reproject:
                    geom.transform(transform)

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
                        )
                        display_name = grouping["display_name"]
                        entity_key = (
                            f"{source_role}:{grouping['number_key']}"
                        )
                        geometry_group_key = (
                            f"{source_role}:{grouping['dissolve_key']}"
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
                        new_feat["NUMBER_KEY"] = grouping["number_key"]
                        new_feat["GROUP_KEY"] = grouping["dissolve_key"]
                        new_feat["SRC_COUNT"] = 1

                        source_record = dict(source_attributes)
                        source_record["_source_layer"] = layer.name()
                        source_record["_source_feature_id"] = feat.id()
                        new_feat["SRC_JSON"] = json.dumps(
                            [source_record],
                            ensure_ascii=False,
                            separators=(",", ":"),
                            default=str,
                        )

                        for source_name in copied_source_fields:
                            new_feat[source_name] = feat[source_name]

                        # Area logic
                        if area_field and feat[area_field]:
                            try:
                                new_feat["면적_m2"] = float(feat[area_field])
                            except (TypeError, ValueError):
                                new_feat["면적_m2"] = geom.area() if layer.geometryType() == 2 else 0.0
                        else:
                            new_feat["면적_m2"] = geom.area() if layer.geometryType() == 2 else 0.0

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
                        new_feat["ENTITY_KEY"] = entity_key
                        new_feat["RELATION_KEY"] = None
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
                            else entity_key
                        )
                        new_feat["GROUP_KEY"] = geometry_group_key
                        new_features.append(new_feat)
                        try:
                            geometry_key = bytes(
                                clipped_geom.asWkb()
                            ).hex()
                        except (TypeError, ValueError):
                            geometry_key = clipped_geom.asWkt()
                        fingerprint_records.append({
                            "code": (
                                feat[code_field] if code_field else ""
                            ),
                            "name": val_name,
                            "geometry_key": geometry_key,
                        })

            if new_features:
                fingerprint = selected_content_fingerprint(
                    fingerprint_records
                )
                duplicate_key = (source_role, fingerprint)
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

            self.move_layer_to_group(layer, src_group)

        if not temp_layers:
            return None

        # Merge subsets grouped by geometry type (native:mergevectorlayers prefers uniform types)
        # We'll merge everything into one if possible, but separate results are safer for display
        # For simplicity and export-readiness, we'll try to merge all, but warn if mixed.

        self.log("최종 데이터 병합 처리 중...")
        params = {
            'LAYERS': temp_layers,
            'CRS': target_crs,
            'OUTPUT': 'memory:Consolidated_Heritage'
        }
        # In QGIS 3, this creates a layer with the type of the first layer.
        # To be safe, we'll just use it and rely on the fact that most are Polygons.
        result = processing.run("native:mergevectorlayers", params)
        merged_layer = result['OUTPUT']
        auxiliary_layers = {
            "suppressed": None,
            "protection": None,
            "audit": None,
        }
        if preservation_only:
            self.aggregate_source_metadata(merged_layer)
        else:
            decision_store = None
            decision_store_path = None
            if reuse_review_decisions:
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
            match_result = self.apply_source_aware_matching(
                merged_layer,
                preset=match_preset,
                decision_provider=matching_decision_provider,
                decision_store=decision_store,
                reuse_saved_decisions=reuse_review_decisions,
                policy_version=(
                    f"{MATCH_POLICY_VERSION}:{match_preset}"
                ),
            )
            processing_stats = getattr(
                self,
                "_current_processing_stats",
                None,
            )
            if not isinstance(processing_stats, dict):
                processing_stats = {}
                self._current_processing_stats = processing_stats
            processing_stats.update({
                "duplicate_candidate_count": match_result.get(
                    "candidate_count",
                    0,
                ),
                "decision_reuse_count": match_result.get(
                    "decision_reuse_count",
                    0,
                ),
            })
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

        # Dissolve multipart areas before numbering so one excavation project
        # receives one number even when its geometry is split into several zones.
        self.log("동일 사업·유적의 분할 구역 병합 처리 중...")

        # Prefer the explicit grouping key created above. Keep the old name
        # lookup as a compatibility fallback for previously generated layers.
        fields = [f.name() for f in merged_layer.fields()]
        dissolve_field = "GROUP_KEY" if "GROUP_KEY" in fields else None
        if not dissolve_field:
            keywords = ['유적명', '명칭', '명', '이름', 'NAME', 'SITE', 'TITLE']
            for f in fields:
                for k in keywords:
                    if k in f.upper():
                        dissolve_field = f
                        break
                if dissolve_field:
                    break

        if not dissolve_field:
            self.log("  ⚠️ 병합 레이어에서 명칭 필드를 찾을 수 없어 Dissolve를 건너뜁니다.")
            if preservation_only:
                return merged_layer
            return {
                "main": merged_layer,
                **auxiliary_layers,
            }

        self.log(f"  - Dissolve 기준 필드: {dissolve_field}")
        before_dissolve_count = merged_layer.featureCount()

        try:
            dissolve_params = {
                'INPUT': merged_layer,
                'FIELD': [dissolve_field],
                'OUTPUT': 'memory:Dissolved_Heritage'
            }
            dissolve_result = processing.run("native:dissolve", dissolve_params)
            final_layer = dissolve_result['OUTPUT']
            final_layer.setName(
                "매장유산_유존지역"
                if preservation_only
                else "수집_및_병합된_주변유적"
            )
            after_dissolve_count = final_layer.featureCount()
            grouped_count = before_dissolve_count - after_dissolve_count
            self.log(
                f"Dissolve 완료: {before_dissolve_count} -> "
                f"{after_dissolve_count}개 유적 (분할 구역 {grouped_count}건 통합)"
            )
        except Exception as e:
            self.log(f"Dissolve 실패 (원본 사용): {e}")
            final_layer = merged_layer
            final_layer.setName(
                "매장유산_유존지역"
                if preservation_only
                else "수집_및_병합된_주변유적"
            )

        if preservation_only:
            return final_layer
        return {
            "main": final_layer,
            **auxiliary_layers,
        }

    def number_heritage_v4(self, layer, study_layer_or_centroid, sort_order, extent_geom=None, extent_crs=None, buffer_geoms=None, restrict_to_buffer=True):
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
        idx = layer.fields().indexFromName("번호")

        # [NEW] Check/Add Distance Field
        dist_field_name = "이격거리(m)"
        if layer.fields().indexFromName(dist_field_name) == -1:
            layer.dataProvider().addAttributes([QgsField(dist_field_name, QVariant.String)])

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
            except Exception as e:
                self.log(f"좌표 변환 오류 (무시됨): {e}")
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

        if sort_order == 1:  # Closest to Study Area (Buffer Tiered)
            # We will process in Tiers if buffers exist

            # Helper to calc distance
            def get_dist(feat_geom):
                if base_geom:
                    return feat_geom.distance(base_geom)
                elif isinstance(study_layer_or_centroid, QgsPointXY):
                    pt = feat_geom.centroid().asPoint()
                    dx = pt.x() - study_layer_or_centroid.x()
                    dy = pt.y() - study_layer_or_centroid.y()
                    return (dx * dx + dy * dy) ** 0.5
                return 0

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

        elif sort_order == 0:  # Top-to-Bottom
            temp = [{'feat': f, 'sort_val': -f.geometry().centroid().asPoint().y(), 'dist_str': None} for f in all_features]
            temp.sort(key=lambda x: x['sort_val'])
            sorted_features = temp

        else:  # Alphabetical
            temp = [{'feat': f, 'sort_val': f["유적명"], 'dist_str': None} for f in all_features]
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

        # [FIX] Robust Reload: Ignore UI layer instance, reload effectively from source file
        source_path = layer.source().split("|")[0]

        # [FIX] Handle QGIS oddities (file.shx|layername=...) or wrong extensions
        if source_path:
            base, ext = os.path.splitext(source_path)
            if ext.lower() in ['.shx', '.dbf']:
                source_path = base + '.shp'

        new_layer = None
        if source_path and os.path.exists(source_path):
            self.log(f"DEBUG: 원본 파일 경로 확인됨: {source_path}")
            # Create new layer instance strictly for processing
            layer_uri = f"{source_path}|encoding={DEFAULT_ENCODING}"
            new_layer = QgsVectorLayer(layer_uri, layer_name, "ogr")

            if new_layer.isValid():
                self.log(f"DEBUG: 파일 재로딩 성공 ({DEFAULT_ENCODING}). 객체 수: {new_layer.featureCount()}")
                layer = new_layer  # Replace variable
            else:
                self.log(f"⚠️ 경고: {DEFAULT_ENCODING} 옵션으로 불러오기 실패. 원본 레이어로 진행합니다.")
        else:
            self.log(f"⚠️ 경고: 원본 파일 경로를 찾을 수 없습니다 (Path: {source_path}). 메모리 레이어이거나 임시 파일일 수 있습니다.")
            self.log(" -> 기존 레이어에 인코딩 설정을 시도합니다.")
            self.fix_layer_encoding(layer, DEFAULT_ENCODING)

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
