"""Interactive review dialog for source-aware duplicate candidates."""

import logging

from qgis.PyQt import QtCore, QtWidgets

from .heritage_matching import (
    DECISION_KEEP,
    DECISION_LABELS,
    DECISION_LINK,
    DECISION_MERGE,
    source_role_label,
)


PAIR_KIND_LABELS = {
    "designated_distribution": "지정·등록유산 ↔ 분포지도",
    "excavation_distribution": "발굴조사 ↔ 분포지도",
    "designated_excavation": "지정·등록유산 ↔ 발굴조사",
    "surface": "지표조사 관련",
}

RULE_LABELS = {
    "exact_name_and_overlap": "동일 명칭 + 공간 중첩",
    "exact_name_within_50m": "동일 명칭 + 50m 이내",
    "name_containment_and_overlap": "명칭 포함관계 + 공간 중첩",
    "fuzzy_name_and_overlap": "유사 명칭 + 공간 중첩",
    "strong_overlap_and_address": "강한 중첩 + 동일 주소",
    "project_name_and_overlap": "사업명 연관 + 공간 중첩",
}
PAIR_KIND_LABELS_EN = {
    "designated_distribution": "Designated/registered ↔ Distribution",
    "excavation_distribution": "Excavation ↔ Distribution",
    "designated_excavation": "Designated/registered ↔ Excavation",
    "surface": "Surface-survey relation",
}
RULE_LABELS_EN = {
    "exact_name_and_overlap": "Exact name + overlap",
    "exact_name_within_50m": "Exact name + within 50 m",
    "name_containment_and_overlap": "Contained name + overlap",
    "fuzzy_name_and_overlap": "Similar name + overlap",
    "strong_overlap_and_address": "Strong overlap + same address",
    "project_name_and_overlap": "Related project name + overlap",
}

LOGGER = logging.getLogger(__name__)


class DuplicateReviewDialog(QtWidgets.QDialog):
    """Review candidate relations before numbering."""

    COLUMNS = (
        "판정",
        "신뢰도",
        "역할·출처 A",
        "명칭 A",
        "주소 A",
        "역할·출처 B",
        "명칭 B",
        "주소 B",
        "중첩률",
        "거리",
        "근거",
    )

    def __init__(
        self,
        candidates,
        parent=None,
        ui_lang="ko",
        zoom_callback=None,
    ):
        super().__init__(parent)
        self.ui_lang = ui_lang
        self.candidates = [dict(candidate) for candidate in candidates]
        self.zoom_callback = (
            zoom_callback if callable(zoom_callback) else None
        )
        self.last_zoom_error = None
        self.action_combos = []
        self.setWindowTitle(self._t(
            "중복 후보 실행 전 검토",
            "Review Duplicate Candidates",
        ))
        self.resize(1280, 620)

        layout = QtWidgets.QVBoxLayout(self)

        intro = QtWidgets.QLabel(
            self._t(
                "<b>이 화면은 도형을 삭제하는 화면이 아니라, 지도에서 어느 "
                "자료가 번호와 라벨을 대표할지 정하는 화면입니다.</b><br>"
                "‘별도 유지’는 각각 번호를 주고, ‘연결만’은 관계를 기록하되 "
                "각각 번호를 유지하며, ‘대표 번호로 묶기’는 번호 하나와 대표 "
                "라벨 하나를 사용합니다. 대표에서 제외된 형상·속성은 "
                "<code>06_중복_검수</code>와 <code>SRC_JSON</code>에 "
                "보존됩니다. ‘자동추천’은 확정이 아닌 초기 선택이므로 결과 "
                "생성 전에 바꿀 수 있습니다.",
                "<b>This dialog does not delete geometry. It decides which "
                "source represents a numbering identity and map label.</b><br>"
                "'Keep separate' assigns separate numbers; 'Link only' "
                "records a relation while keeping separate numbers; and "
                "'Merge numbering identity' uses one number and one "
                "representative label. Suppressed geometry and attributes "
                "remain in <code>06_중복_검수</code> and "
                "<code>SRC_JSON</code>. An automatic recommendation is only "
                "the initial choice and can be changed before generation.",
            )
        )
        intro.setWordWrap(True)
        intro.setTextFormat(QtCore.Qt.RichText)
        intro.setStyleSheet(
            "background:#eef7ff; border:1px solid #9ec9e8; "
            "padding:8px; color:#234;"
        )
        layout.addWidget(intro)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.addWidget(QtWidgets.QLabel(
            self._t("관계 필터:", "Relation filter:")
        ))
        self.pair_filter = QtWidgets.QComboBox()
        self.pair_filter.addItem(self._t("전체", "All"), "")
        present_kinds = {
            candidate.get("pair_kind") for candidate in self.candidates
        }
        pair_labels = (
            PAIR_KIND_LABELS_EN
            if self.ui_lang == "en"
            else PAIR_KIND_LABELS
        )
        for kind, label in pair_labels.items():
            if kind in present_kinds:
                self.pair_filter.addItem(label, kind)
        toolbar.addWidget(self.pair_filter)

        self.btn_recommended = QtWidgets.QPushButton(
            self._t("추천안 적용", "Apply recommendations")
        )
        self.btn_keep = QtWidgets.QPushButton(
            self._t("모두 별도 유지", "Keep all separate")
        )
        toolbar.addWidget(self.btn_recommended)
        toolbar.addWidget(self.btn_keep)
        self.bulk_action = QtWidgets.QComboBox()
        for decision in (
            DECISION_KEEP,
            DECISION_LINK,
            DECISION_MERGE,
        ):
            english_decisions = {
                DECISION_KEEP: "Keep separate",
                DECISION_LINK: "Link only",
                DECISION_MERGE: "Merge numbering identity",
            }
            self.bulk_action.addItem(
                (
                    english_decisions[decision]
                    if self.ui_lang == "en"
                    else DECISION_LABELS[decision]
                ),
                decision,
            )
        self.btn_bulk_apply = QtWidgets.QPushButton(
            self._t(
                "현재 관계에 일괄 적용",
                "Apply to filtered relation",
            )
        )
        toolbar.addWidget(self.bulk_action)
        toolbar.addWidget(self.btn_bulk_apply)
        self.btn_zoom = QtWidgets.QPushButton(
            self._t(
                "선택 후보 지도에서 보기",
                "Show selected candidate on map",
            )
        )
        self.btn_zoom.setEnabled(
            self.zoom_callback is not None and bool(self.candidates)
        )
        toolbar.addWidget(self.btn_zoom)
        toolbar.addStretch(1)

        self.summary = QtWidgets.QLabel()
        toolbar.addWidget(self.summary)
        layout.addLayout(toolbar)

        self.table = QtWidgets.QTableWidget(
            len(self.candidates),
            len(self.COLUMNS),
        )
        self.table.setHorizontalHeaderLabels(
            self.COLUMNS
            if self.ui_lang != "en"
            else (
                "Decision",
                "Confidence",
                "Role / source A",
                "Name A",
                "Address A",
                "Role / source B",
                "Name B",
                "Address B",
                "Overlap",
                "Distance",
                "Evidence",
            )
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        for row, candidate in enumerate(self.candidates):
            combo = QtWidgets.QComboBox()
            for decision in (
                DECISION_KEEP,
                DECISION_LINK,
                DECISION_MERGE,
            ):
                english_decisions = {
                    DECISION_KEEP: "Keep separate",
                    DECISION_LINK: "Link only",
                    DECISION_MERGE: "Merge numbering identity",
                }
                combo.addItem(
                    (
                        english_decisions[decision]
                        if self.ui_lang == "en"
                        else DECISION_LABELS[decision]
                    ),
                    decision,
                )
            default_decision = (
                candidate.get("recommended_decision")
                if candidate.get("auto_apply")
                else DECISION_KEEP
            )
            combo.setCurrentIndex(
                max(0, combo.findData(default_decision))
            )
            combo.currentIndexChanged.connect(self._update_summary)
            self.table.setCellWidget(row, 0, combo)
            self.action_combos.append(combo)

            confidence = candidate.get("confidence", "")
            if candidate.get("auto_apply"):
                confidence = f"{confidence} · 자동추천"
            self._set_item(row, 1, confidence)
            self._set_item(
                row,
                2,
                self._role_and_source(candidate, "left"),
            )
            self._set_item(row, 3, candidate.get("left_name", ""))
            self._set_item(row, 4, candidate.get("left_address", ""))
            self._set_item(
                row,
                5,
                self._role_and_source(candidate, "right"),
            )
            self._set_item(row, 6, candidate.get("right_name", ""))
            self._set_item(row, 7, candidate.get("right_address", ""))
            self._set_item(
                row,
                8,
                f"{float(candidate.get('overlap_ratio', 0)) * 100:.1f}%",
            )
            self._set_item(
                row,
                9,
                f"{float(candidate.get('distance', 0)):.1f}m",
            )
            self._set_item(
                row,
                10,
                (
                    RULE_LABELS_EN
                    if self.ui_lang == "en"
                    else RULE_LABELS
                ).get(
                    candidate.get("rule"),
                    candidate.get("rule", ""),
                ),
            )

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(6, QtWidgets.QHeaderView.Stretch)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok
            | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText(
            self._t(
                "이 선택으로 결과 생성",
                "Generate with these decisions",
            )
        )
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText(
            self._t("취소", "Cancel")
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.pair_filter.currentIndexChanged.connect(
            self._apply_pair_filter
        )
        self.btn_recommended.clicked.connect(
            self._apply_recommended_to_visible
        )
        self.btn_keep.clicked.connect(self._keep_visible)
        self.btn_bulk_apply.clicked.connect(self._bulk_apply_to_visible)
        self.btn_zoom.clicked.connect(self._zoom_selected_candidate)
        self.table.cellDoubleClicked.connect(
            self._zoom_candidate_at_row
        )
        self._update_summary()

    def _t(self, ko_text, en_text):
        return en_text if self.ui_lang == "en" else ko_text

    def _set_item(self, row, column, text):
        item = QtWidgets.QTableWidgetItem(str(text or ""))
        item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
        self.table.setItem(row, column, item)

    def _role_and_source(self, candidate, side):
        role = source_role_label(
            candidate.get(f"{side}_role"),
            self.ui_lang,
        )
        source = str(candidate.get(f"{side}_source") or "").strip()
        return f"{role} · {source}" if source else role

    def _row_visible(self, row):
        return not self.table.isRowHidden(row)

    def _apply_pair_filter(self):
        selected = self.pair_filter.currentData()
        for row, candidate in enumerate(self.candidates):
            self.table.setRowHidden(
                row,
                bool(
                    selected
                    and candidate.get("pair_kind") != selected
                ),
            )

    def _apply_recommended_to_visible(self):
        for row, candidate in enumerate(self.candidates):
            if not self._row_visible(row):
                continue
            combo = self.action_combos[row]
            index = combo.findData(
                candidate.get("recommended_decision", DECISION_KEEP)
            )
            combo.setCurrentIndex(max(0, index))
        self._update_summary()

    def _keep_visible(self):
        for row, combo in enumerate(self.action_combos):
            if self._row_visible(row):
                combo.setCurrentIndex(combo.findData(DECISION_KEEP))
        self._update_summary()

    def _bulk_apply_to_visible(self):
        decision = self.bulk_action.currentData()
        for row, combo in enumerate(self.action_combos):
            if self._row_visible(row):
                combo.setCurrentIndex(combo.findData(decision))
        self._update_summary()

    def _zoom_selected_candidate(self):
        row = self.table.currentRow()
        if row < 0:
            row = 0
        self._zoom_candidate_at_row(row)

    def _zoom_candidate_at_row(self, row, _column=None):
        if (
            self.zoom_callback is None
            or row < 0
            or row >= len(self.candidates)
        ):
            return
        try:
            self.zoom_callback(dict(self.candidates[row]))
            self.last_zoom_error = None
        except Exception as exc:  # pragma: no cover - logger detail varies
            self.last_zoom_error = exc
            LOGGER.exception(
                "Failed to show duplicate candidate %d on the map",
                row,
            )

    def _update_summary(self):
        counts = {
            DECISION_KEEP: 0,
            DECISION_LINK: 0,
            DECISION_MERGE: 0,
        }
        for combo in self.action_combos:
            counts[combo.currentData()] += 1
        self.summary.setText(
            (
                f"Keep {counts[DECISION_KEEP]} · "
                f"Link {counts[DECISION_LINK]} · "
                f"Merge {counts[DECISION_MERGE]}"
                if self.ui_lang == "en"
                else (
                    f"별도 {counts[DECISION_KEEP]} · "
                    f"연결 {counts[DECISION_LINK]} · "
                    f"대표화 {counts[DECISION_MERGE]}"
                )
            )
        )

    def decisions(self):
        result = []
        for candidate, combo in zip(
            self.candidates,
            self.action_combos,
        ):
            item = dict(candidate)
            item["decision"] = combo.currentData()
            item["decision_source"] = (
                "auto"
                if (
                    item.get("auto_apply")
                    and item["decision"]
                    == item.get("recommended_decision")
                )
                else "user"
            )
            result.append(item)
        return result
