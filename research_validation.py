"""Pure-Python utilities for the single-reviewer JOSS pilot study.

The module prepares and scores evidence; it never manufactures labels or
claims a validation gate has passed when a metric has no valid denominator.
Real pilot rows and heritage coordinates must remain outside the repository.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
import csv
import hashlib
import json
from pathlib import Path


LABEL_SAME_ENTITY = "same_entity"
LABEL_RELATED_SEPARATE = "related_separate"
LABEL_UNRELATED = "unrelated"
LABEL_UNCERTAIN = "uncertain"
PILOT_LABELS = (
    LABEL_SAME_ENTITY,
    LABEL_RELATED_SEPARATE,
    LABEL_UNRELATED,
    LABEL_UNCERTAIN,
)

SPLIT_DEVELOPMENT = "development"
SPLIT_LOCKED_EVALUATION = "locked_evaluation"

DEFAULT_DEVELOPMENT_SIZE = 200
DEFAULT_LOCKED_EVALUATION_SIZE = 100
DEFAULT_SPLIT_SEED = "archdistribution-joss-v1.0.5-pilot"

MIN_AUTOMATIC_MERGE_PRECISION = 0.98
MIN_CANDIDATE_RECALL = 0.95

_BLINDED_FIELDS = frozenset({
    "automatic_merge",
    "auto_apply",
    "blind_label",
    "candidate_status",
    "confidence",
    "gold_label",
    "is_candidate",
    "label",
    "match_rule",
    "match_score",
    "recommended_decision",
    "recommendation",
    "representative_uid",
    "rule",
    "score",
})


class PilotValidationError(ValueError):
    """Raised when a pilot input could yield misleading validation evidence."""


def _stable_rank(seed, namespace, value):
    payload = f"{seed}\0{namespace}\0{value}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validated_records(records, pair_id_field, project_field):
    copied = []
    pair_ids = set()
    for raw in records:
        row = dict(raw)
        pair_id = str(row.get(pair_id_field, "")).strip()
        project = str(row.get(project_field, "")).strip()
        if not pair_id:
            raise PilotValidationError(f"missing {pair_id_field}")
        if pair_id in pair_ids:
            raise PilotValidationError(f"duplicate pair_id: {pair_id}")
        if not project:
            raise PilotValidationError(
                f"pair {pair_id} has no {project_field}; project leakage "
                "cannot be prevented"
            )
        row[pair_id_field] = pair_id
        row[project_field] = project
        pair_ids.add(pair_id)
        copied.append(row)
    return copied


def _choose_development_projects(groups, ordered_projects, target, upper):
    """Choose a deterministic project subset with capacity in [target, upper]."""
    reachable = {0: ()}
    for index, project in enumerate(ordered_projects):
        size = len(groups[project])
        snapshot = tuple(reachable.items())
        for subtotal, chosen in snapshot:
            new_total = subtotal + size
            if new_total <= upper and new_total not in reachable:
                reachable[new_total] = chosen + (index,)

    valid_totals = [total for total in reachable if target <= total <= upper]
    if not valid_totals:
        raise PilotValidationError(
            "project groups cannot satisfy the requested split without "
            "project leakage; change the sample or requested sizes"
        )
    selected = reachable[min(valid_totals)]
    return {ordered_projects[index] for index in selected}


def _sample_assigned_projects(
    groups,
    ordered_projects,
    assigned_projects,
    target,
    seed,
    split_name,
    pair_id_field,
):
    selected = []
    excluded = []
    for project in ordered_projects:
        if project not in assigned_projects:
            continue
        rows = sorted(
            groups[project],
            key=lambda row: _stable_rank(
                seed, f"{split_name}:pair", row[pair_id_field]
            ),
        )
        remaining = target - len(selected)
        if remaining > 0:
            selected.extend(rows[:remaining])
            excluded.extend(rows[remaining:])
        else:
            excluded.extend(rows)
    return selected, excluded


@dataclass(frozen=True)
class PilotSplit:
    development: tuple
    locked_evaluation: tuple
    excluded: tuple
    seed: str

    def as_dict(self):
        return {
            "development": [dict(row) for row in self.development],
            "locked_evaluation": [dict(row) for row in self.locked_evaluation],
            "excluded": [dict(row) for row in self.excluded],
            "seed": self.seed,
        }

    def manifest(self):
        return {
            "schema_version": 1,
            "seed": self.seed,
            "development_pairs": len(self.development),
            "locked_evaluation_pairs": len(self.locked_evaluation),
            "excluded_pairs": len(self.excluded),
            "labels_present": False,
        }


def deterministic_project_split(
    records,
    development_size=DEFAULT_DEVELOPMENT_SIZE,
    locked_evaluation_size=DEFAULT_LOCKED_EVALUATION_SIZE,
    seed=DEFAULT_SPLIT_SEED,
    pair_id_field="pair_id",
    project_field="project_key",
):
    """Select exact-size pilot splits without assigning a project to both.

    Projects are ranked by a seeded SHA-256, not input order or Python's
    process-randomized hash.  If an assigned project's rows exceed a target,
    the excess rows are excluded rather than leaked into the other split.
    """
    development_size = int(development_size)
    locked_evaluation_size = int(locked_evaluation_size)
    if development_size < 1 or locked_evaluation_size < 1:
        raise PilotValidationError("split sizes must both be positive")

    rows = _validated_records(records, pair_id_field, project_field)
    required = development_size + locked_evaluation_size
    if len(rows) < required:
        raise PilotValidationError(
            f"pilot needs at least {required} rows; received {len(rows)}"
        )

    groups = defaultdict(list)
    for row in rows:
        groups[row[project_field]].append(row)
    ordered_projects = sorted(
        groups,
        key=lambda project: (
            _stable_rank(seed, "project", project),
            project,
        ),
    )

    maximum_development_capacity = len(rows) - locked_evaluation_size
    development_projects = _choose_development_projects(
        groups,
        ordered_projects,
        development_size,
        maximum_development_capacity,
    )
    evaluation_pool = [
        project for project in ordered_projects
        if project not in development_projects
    ]

    evaluation_projects = set()
    evaluation_capacity = 0
    for project in evaluation_pool:
        evaluation_projects.add(project)
        evaluation_capacity += len(groups[project])
        if evaluation_capacity >= locked_evaluation_size:
            break
    if evaluation_capacity < locked_evaluation_size:
        raise PilotValidationError(
            "not enough independent projects for the locked evaluation split"
        )

    development, _excluded_development = _sample_assigned_projects(
        groups,
        ordered_projects,
        development_projects,
        development_size,
        seed,
        SPLIT_DEVELOPMENT,
        pair_id_field,
    )
    evaluation, _excluded_evaluation = _sample_assigned_projects(
        groups,
        ordered_projects,
        evaluation_projects,
        locked_evaluation_size,
        seed,
        SPLIT_LOCKED_EVALUATION,
        pair_id_field,
    )

    used_ids = {
        row[pair_id_field] for row in development + evaluation
    }
    excluded = [
        row for row in rows
        if row[pair_id_field] not in used_ids
    ]
    excluded.sort(
        key=lambda row: _stable_rank(
            seed, "excluded:pair", row[pair_id_field]
        )
    )

    development_output = tuple(
        {**row, "project_split": SPLIT_DEVELOPMENT}
        for row in development
    )
    evaluation_output = tuple(
        {**row, "project_split": SPLIT_LOCKED_EVALUATION}
        for row in evaluation
    )
    return PilotSplit(
        development=development_output,
        locked_evaluation=evaluation_output,
        excluded=tuple(excluded),
        seed=str(seed),
    )


def blinded_labeling_rows(records):
    """Remove model recommendations/scores and add an empty human label field."""
    blinded = []
    for raw in records:
        row = {
            key: value for key, value in dict(raw).items()
            if key not in _BLINDED_FIELDS
        }
        if not str(row.get("pair_id", "")).strip():
            raise PilotValidationError("blinded export requires pair_id")
        row["blind_label"] = ""
        blinded.append(row)
    return blinded


def merge_blinded_labels(
    prediction_records,
    labeled_records,
    pair_id_field="pair_id",
    label_field="blind_label",
):
    """Reattach completed blind labels to private prediction rows by pair ID."""
    predictions = {}
    for raw in prediction_records:
        row = dict(raw)
        pair_id = str(row.get(pair_id_field, "")).strip()
        if not pair_id or pair_id in predictions:
            raise PilotValidationError(
                f"missing or duplicate prediction {pair_id_field}: {pair_id!r}"
            )
        predictions[pair_id] = row

    labels = {}
    for raw in labeled_records:
        row = dict(raw)
        pair_id = str(row.get(pair_id_field, "")).strip()
        if not pair_id or pair_id in labels:
            raise PilotValidationError(
                f"missing or duplicate label {pair_id_field}: {pair_id!r}"
            )
        label = str(row.get(label_field, "")).strip()
        if label not in PILOT_LABELS:
            raise PilotValidationError(
                f"pair {pair_id} has invalid or blank {label_field}: {label!r}"
            )
        labels[pair_id] = label

    missing_labels = sorted(set(predictions) - set(labels))
    unknown_labels = sorted(set(labels) - set(predictions))
    if missing_labels or unknown_labels:
        raise PilotValidationError(
            "prediction/label pair IDs differ: "
            f"missing_labels={missing_labels[:5]}, "
            f"unknown_labels={unknown_labels[:5]}"
        )
    return [
        {**predictions[pair_id], label_field: labels[pair_id]}
        for pair_id in sorted(predictions)
    ]


def export_blinded_labeling_csv(records, destination, fieldnames=None):
    """Write a UTF-8 CSV for human labeling and return factual file metadata."""
    rows = blinded_labeling_rows(records)
    if not rows:
        raise PilotValidationError("cannot export an empty labeling set")
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    if "blind_label" not in fieldnames:
        fieldnames = list(fieldnames) + ["blind_label"]

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    payload = path.read_bytes()
    return {
        "row_count": len(rows),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "filename": path.name,
    }


def read_csv_records(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _strict_bool(value, field, pair_id):
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().casefold()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise PilotValidationError(
        f"pair {pair_id} has invalid {field}: {value!r}"
    )


def _safe_ratio(numerator, denominator):
    if denominator == 0:
        return None
    return numerator / denominator


@dataclass(frozen=True)
class PilotMetrics:
    total_pairs: int
    automatic_merge_precision: object
    candidate_recall: object
    review_rate: float
    automatic_merges: int
    candidate_pairs: int
    review_pairs: int
    false_automatic_merges: int
    missed_same_entities: int
    label_counts: dict
    error_counts: dict
    precision_threshold: float = MIN_AUTOMATIC_MERGE_PRECISION
    recall_threshold: float = MIN_CANDIDATE_RECALL

    @property
    def precision_pass(self):
        return (
            self.automatic_merge_precision is not None
            and self.automatic_merge_precision >= self.precision_threshold
        )

    @property
    def recall_pass(self):
        return (
            self.candidate_recall is not None
            and self.candidate_recall >= self.recall_threshold
        )

    @property
    def release_gate_pass(self):
        return self.precision_pass and self.recall_pass

    def as_dict(self):
        return {
            "schema_version": 1,
            "total_pairs": self.total_pairs,
            "automatic_merge_precision": self.automatic_merge_precision,
            "candidate_recall": self.candidate_recall,
            "review_rate": self.review_rate,
            "automatic_merges": self.automatic_merges,
            "candidate_pairs": self.candidate_pairs,
            "review_pairs": self.review_pairs,
            "false_automatic_merges": self.false_automatic_merges,
            "missed_same_entities": self.missed_same_entities,
            "label_counts": dict(self.label_counts),
            "error_counts": dict(self.error_counts),
            "thresholds": {
                "automatic_merge_precision": self.precision_threshold,
                "candidate_recall": self.recall_threshold,
            },
            "precision_pass": self.precision_pass,
            "recall_pass": self.recall_pass,
            "release_gate_pass": self.release_gate_pass,
        }


def calculate_pilot_metrics(
    records,
    label_field="blind_label",
    candidate_field="is_candidate",
    automatic_merge_field="automatic_merge",
    required_split=None,
):
    """Score completely labeled pilot rows against the two release thresholds.

    ``review_rate`` is the fraction of all evaluated pairs that became a
    candidate but were not automatically merged.  Uncertain automatic merges
    count as errors; uncertain rows do not enter the same-entity recall
    denominator.  A zero precision or recall denominator produces ``None`` and
    a failed gate rather than an invented perfect score.
    """
    rows = [dict(row) for row in records]
    if not rows:
        raise PilotValidationError("cannot score an empty pilot set")

    labels = Counter()
    automatic_merges = 0
    correct_automatic_merges = 0
    candidates = 0
    review_pairs = 0
    same_entities = 0
    candidate_same_entities = 0
    false_automatic_by_label = Counter()

    for row in rows:
        pair_id = str(row.get("pair_id", "")).strip() or "<unknown>"
        if required_split is not None and row.get("project_split") != required_split:
            raise PilotValidationError(
                f"pair {pair_id} is not in required split {required_split}"
            )
        label = str(row.get(label_field, "")).strip()
        if label not in PILOT_LABELS:
            raise PilotValidationError(
                f"pair {pair_id} has invalid or blank {label_field}: {label!r}"
            )
        candidate = _strict_bool(row.get(candidate_field), candidate_field, pair_id)
        automatic_merge = _strict_bool(
            row.get(automatic_merge_field), automatic_merge_field, pair_id
        )
        if automatic_merge and not candidate:
            raise PilotValidationError(
                f"pair {pair_id} is automatically merged but is not a candidate"
            )

        labels[label] += 1
        candidates += int(candidate)
        automatic_merges += int(automatic_merge)
        review_pairs += int(candidate and not automatic_merge)
        if label == LABEL_SAME_ENTITY:
            same_entities += 1
            candidate_same_entities += int(candidate)
        if automatic_merge:
            if label == LABEL_SAME_ENTITY:
                correct_automatic_merges += 1
            else:
                false_automatic_by_label[label] += 1

    precision = _safe_ratio(correct_automatic_merges, automatic_merges)
    recall = _safe_ratio(candidate_same_entities, same_entities)
    false_automatic_merges = sum(false_automatic_by_label.values())
    missed_same_entities = same_entities - candidate_same_entities
    label_counts = {label: labels[label] for label in PILOT_LABELS}
    error_counts = {
        "false_automatic_merges": false_automatic_merges,
        "missed_same_entities": missed_same_entities,
        "auto_merged_related_separate": false_automatic_by_label[
            LABEL_RELATED_SEPARATE
        ],
        "auto_merged_unrelated": false_automatic_by_label[LABEL_UNRELATED],
        "auto_merged_uncertain": false_automatic_by_label[LABEL_UNCERTAIN],
    }
    return PilotMetrics(
        total_pairs=len(rows),
        automatic_merge_precision=precision,
        candidate_recall=recall,
        review_rate=review_pairs / len(rows),
        automatic_merges=automatic_merges,
        candidate_pairs=candidates,
        review_pairs=review_pairs,
        false_automatic_merges=false_automatic_merges,
        missed_same_entities=missed_same_entities,
        label_counts=label_counts,
        error_counts=error_counts,
    )


def write_metrics_json(metrics, destination):
    """Persist only metrics calculated from supplied completed labels."""
    if not isinstance(metrics, PilotMetrics):
        raise TypeError("metrics must be a PilotMetrics instance")
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        metrics.as_dict(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    path.write_text(payload, encoding="utf-8")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
