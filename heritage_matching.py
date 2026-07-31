"""Source-aware duplicate matching rules for archaeological map layers.

The module deliberately has no QGIS dependency.  Geometry discovery is handled
by the plugin with a spatial index and reduced to the metrics consumed here.
This keeps the policy testable in a normal Python runtime.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
import hashlib
import json
import re

try:
    from .heritage_grouping import (
        canonical_heritage_text,
        clean_heritage_text,
    )
except ImportError:
    # Keep this policy module directly runnable by the validation scripts and
    # the normal-Python unit tests outside a loaded QGIS plugin package.
    from heritage_grouping import (
        canonical_heritage_text,
        clean_heritage_text,
    )


ROLE_NATIONAL_DESIGNATED = "national_designated"
ROLE_LOCAL_DESIGNATED = "local_designated"
ROLE_NATIONAL_REGISTERED = "national_registered"
ROLE_LOCAL_REGISTERED = "local_registered"
ROLE_PROTECTION_ZONE = "protection_zone"
ROLE_DISTRIBUTION = "distribution"
ROLE_SURFACE = "surface_survey"
ROLE_EXCAVATION = "excavation"
ROLE_OTHER = "other"

SOURCE_ROLE_LABELS = {
    ROLE_NATIONAL_DESIGNATED: "국가지정유산",
    ROLE_LOCAL_DESIGNATED: "시도지정유산",
    ROLE_NATIONAL_REGISTERED: "국가등록문화유산",
    ROLE_LOCAL_REGISTERED: "시도등록문화유산",
    ROLE_PROTECTION_ZONE: "지정유산 보호구역",
    ROLE_DISTRIBUTION: "문화유적분포지도",
    ROLE_SURFACE: "지표조사",
    ROLE_EXCAVATION: "발굴조사",
    ROLE_OTHER: "기타",
}
SOURCE_ROLE_LABELS_EN = {
    ROLE_NATIONAL_DESIGNATED: "Nationally designated",
    ROLE_LOCAL_DESIGNATED: "Locally designated",
    ROLE_NATIONAL_REGISTERED: "Nationally registered",
    ROLE_LOCAL_REGISTERED: "Locally registered",
    ROLE_PROTECTION_ZONE: "Heritage protection zone",
    ROLE_DISTRIBUTION: "Heritage distribution map",
    ROLE_SURFACE: "Surface survey",
    ROLE_EXCAVATION: "Excavation",
    ROLE_OTHER: "Other",
}
SOURCE_ROLE_ORDER = tuple(SOURCE_ROLE_LABELS)

PRESET_BALANCED = "balanced"
PRESET_CONSERVATIVE = "conservative"
PRESET_AUTOMATION = "automation"
MATCH_PRESET_LABELS = {
    PRESET_BALANCED: "균형형",
    PRESET_CONSERVATIVE: "보수형",
    PRESET_AUTOMATION: "자동화 우선형",
}
MATCH_PRESET_LABELS_EN = {
    PRESET_BALANCED: "Balanced",
    PRESET_CONSERVATIVE: "Conservative",
    PRESET_AUTOMATION: "Automation-first",
}

DECISION_KEEP = "keep"
DECISION_LINK = "link"
DECISION_MERGE = "merge"
DECISION_LABELS = {
    DECISION_KEEP: "별도 유지",
    DECISION_LINK: "연결만",
    DECISION_MERGE: "대표 번호로 묶기",
}

STATUS_UNIQUE = "UNIQUE"
STATUS_AUTO_MERGED = "AUTO_MERGED"
STATUS_USER_MERGED = "USER_MERGED"
STATUS_LINKED = "LINKED"
STATUS_KEPT_SEPARATE = "KEPT_SEPARATE"
STATUS_PROTECTION_ZONE = "PROTECTION_ZONE"

DESIGNATED_ROLES = frozenset({
    ROLE_NATIONAL_DESIGNATED,
    ROLE_LOCAL_DESIGNATED,
    ROLE_NATIONAL_REGISTERED,
    ROLE_LOCAL_REGISTERED,
})


def _compact(value):
    return re.sub(r"[\s_\-]+", "", clean_heritage_text(value)).casefold()


def detect_source_role(layer_name, field_names):
    """Return a conservative role inferred from a layer name and its schema."""
    name = _compact(layer_name)
    fields = {_compact(field) for field in (field_names or [])}

    if "보호구역" in name:
        return ROLE_PROTECTION_ZONE

    if "국가등록" in name:
        return ROLE_NATIONAL_REGISTERED
    if "시도등록" in name or "시·도등록" in clean_heritage_text(layer_name):
        return ROLE_LOCAL_REGISTERED

    if "국가지정" in name:
        return ROLE_NATIONAL_DESIGNATED
    if "시도지정" in name or "시·도지정" in clean_heritage_text(layer_name):
        return ROLE_LOCAL_DESIGNATED

    if "발굴" in name:
        return ROLE_EXCAVATION
    if "지표" in name:
        return ROLE_SURFACE
    if "문화유적분포" in name or "유적분포지도" in name:
        return ROLE_DISTRIBUTION

    has_designation_schema = (
        "국가유산명" in fields
        and ("지정종목" in fields or "종목코드" in fields)
    )
    if has_designation_schema:
        return ROLE_NATIONAL_DESIGNATED

    has_survey_schema = (
        "사업명" in fields
        and "보고서명" in fields
        and "유적명" in fields
    )
    if has_survey_schema:
        # The excavation and surface schemas are intentionally almost equal.
        # Without an explicit layer-name signal, silently choosing one is less
        # safe than asking the user to set the role.
        return ROLE_OTHER

    has_distribution_schema = (
        "명칭" in fields
        and ("유적대분류" in fields or "유적중분류" in fields)
        and "사업명" not in fields
    )
    if has_distribution_schema:
        return ROLE_DISTRIBUTION

    return ROLE_OTHER


def source_role_label(role, language="ko"):
    labels = SOURCE_ROLE_LABELS_EN if language == "en" else SOURCE_ROLE_LABELS
    return labels.get(role, role)


def source_priority(role):
    """Priority used only to select a representative, never number order."""
    if role in DESIGNATED_ROLES:
        return 400
    if role == ROLE_EXCAVATION:
        return 300
    if role == ROLE_SURFACE:
        return 200
    if role == ROLE_DISTRIBUTION:
        return 100
    if role == ROLE_PROTECTION_ZONE:
        return -100
    return 0


def is_designated_role(role):
    return role in DESIGNATED_ROLES


@lru_cache(maxsize=200_000)
def _canonical_name_cached(text):
    return canonical_heritage_text(text)


def canonical_name(value):
    return _canonical_name_cached("" if value is None else str(value))


@lru_cache(maxsize=200_000)
def _canonical_address_cached(text):
    cleaned = clean_heritage_text(text)
    cleaned = re.sub(r"\([^)]*\)", "", cleaned)
    return re.sub(r"[^0-9a-z가-힣]", "", cleaned.casefold())


def canonical_address(value):
    return _canonical_address_cached("" if value is None else str(value))


def name_similarity(left, right):
    left_key = canonical_name(left)
    right_key = canonical_name(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    return SequenceMatcher(None, left_key, right_key).ratio()


def name_contains(left, right):
    left_key = canonical_name(left)
    right_key = canonical_name(right)
    if min(len(left_key), len(right_key)) < 4:
        return False
    if left_key in right_key or right_key in left_key:
        return True

    # Administrative prefixes are not consistently repeated between sources
    # (for example "서울 탑골공원" vs "탑골공원 팔각정").  Treat a substantial
    # shared core as a review signal, not as an automatic identity match.
    matcher = SequenceMatcher(None, left_key, right_key)
    shared = matcher.find_longest_match(
        0,
        len(left_key),
        0,
        len(right_key),
    ).size
    return shared >= 4 and shared / min(len(left_key), len(right_key)) >= 0.60


def _record_name(record):
    return clean_heritage_text(
        record.get("site_name")
        or record.get("name")
        or record.get("heritage_name")
    )


def _pair_kind(left_role, right_role):
    roles = {left_role, right_role}
    if ROLE_SURFACE in roles:
        return "surface"
    if ROLE_DISTRIBUTION in roles:
        other = right_role if left_role == ROLE_DISTRIBUTION else left_role
        if is_designated_role(other):
            return "designated_distribution"
        if other == ROLE_EXCAVATION:
            return "excavation_distribution"
    if (
        (is_designated_role(left_role) and right_role == ROLE_EXCAVATION)
        or (is_designated_role(right_role) and left_role == ROLE_EXCAVATION)
    ):
        return "designated_excavation"
    return None


def _representative_uid(left, right):
    left_priority = source_priority(left.get("role"))
    right_priority = source_priority(right.get("role"))
    if left_priority == right_priority:
        return min(str(left.get("uid")), str(right.get("uid")))
    return (
        str(left.get("uid"))
        if left_priority > right_priority
        else str(right.get("uid"))
    )


@dataclass(frozen=True)
class MatchCandidate:
    left_uid: str
    right_uid: str
    pair_kind: str
    confidence: str
    score: float
    rule: str
    recommended_decision: str
    representative_uid: str
    auto_apply: bool
    name_similarity: float
    overlap_ratio: float
    distance: float

    def as_dict(self):
        return {
            "left_uid": self.left_uid,
            "right_uid": self.right_uid,
            "pair_kind": self.pair_kind,
            "confidence": self.confidence,
            "score": self.score,
            "rule": self.rule,
            "recommended_decision": self.recommended_decision,
            "representative_uid": self.representative_uid,
            "auto_apply": self.auto_apply,
            "name_similarity": self.name_similarity,
            "overlap_ratio": self.overlap_ratio,
            "distance": self.distance,
        }


def evaluate_candidate(
    left,
    right,
    *,
    intersects,
    overlap_ratio,
    distance=0.0,
    preset=PRESET_BALANCED,
):
    """Evaluate one spatially reduced pair.

    ``overlap_ratio`` is intersection area divided by the smaller polygon area.
    The caller may pass zero for non-polygon geometries.
    """
    left_role = left.get("role", ROLE_OTHER)
    right_role = right.get("role", ROLE_OTHER)
    pair_kind = _pair_kind(left_role, right_role)
    if not pair_kind:
        return None

    left_name = _record_name(left)
    right_name = _record_name(right)
    similarity = name_similarity(left_name, right_name)
    exact = bool(left_name and right_name and similarity == 1.0)
    containment = name_contains(left_name, right_name)

    address_left = canonical_address(left.get("address"))
    address_right = canonical_address(right.get("address"))
    same_address = bool(
        address_left
        and address_right
        and (
            address_left == address_right
            or address_left in address_right
            or address_right in address_left
        )
    )

    project_signal = False
    if pair_kind == "excavation_distribution":
        excavation = (
            left if left_role == ROLE_EXCAVATION else right
        )
        distribution = (
            right if left_role == ROLE_EXCAVATION else left
        )
        project = excavation.get("project_name")
        distribution_name = _record_name(distribution)
        project_signal = (
            name_contains(project, distribution_name)
            or name_similarity(project, distribution_name) >= 0.90
        )

    confidence = None
    rule = None
    if exact and intersects and overlap_ratio > 0:
        confidence = "high"
        rule = "exact_name_and_overlap"
    elif exact and distance <= 50:
        confidence = "medium"
        rule = "exact_name_within_50m"
    elif intersects and overlap_ratio >= 0.25 and (
        similarity >= 0.90 or containment
    ):
        confidence = "medium"
        rule = (
            "name_containment_and_overlap"
            if containment and similarity < 0.90
            else "fuzzy_name_and_overlap"
        )
    elif (
        intersects
        and overlap_ratio >= 0.80
        and same_address
    ):
        confidence = "medium"
        rule = "strong_overlap_and_address"
    elif (
        pair_kind == "excavation_distribution"
        and intersects
        and overlap_ratio >= 0.25
        and project_signal
    ):
        confidence = "medium"
        rule = "project_name_and_overlap"
    else:
        return None

    if pair_kind == "surface":
        recommended = DECISION_KEEP
        auto_apply = False
    elif pair_kind == "designated_excavation":
        recommended = DECISION_LINK
        auto_apply = confidence == "high" and preset != PRESET_CONSERVATIVE
    else:
        recommended = DECISION_MERGE
        if preset == PRESET_CONSERVATIVE:
            auto_apply = False
        elif preset == PRESET_BALANCED:
            auto_apply = confidence == "high"
        else:
            auto_apply = (
                confidence == "high"
                or (
                    similarity >= 0.95
                    and overlap_ratio >= 0.50
                    and rule != "name_containment_and_overlap"
                )
            )

    address_score = 1.0 if same_address else 0.0
    score = min(
        1.0,
        (similarity * 0.55)
        + (min(max(float(overlap_ratio), 0.0), 1.0) * 0.35)
        + (address_score * 0.10),
    )

    return MatchCandidate(
        left_uid=str(left.get("uid")),
        right_uid=str(right.get("uid")),
        pair_kind=pair_kind,
        confidence=confidence,
        score=round(score, 4),
        rule=rule,
        recommended_decision=recommended,
        representative_uid=_representative_uid(left, right),
        auto_apply=auto_apply,
        name_similarity=round(similarity, 4),
        overlap_ratio=round(float(overlap_ratio), 4),
        distance=round(float(distance), 3),
    )


def selected_content_fingerprint(records):
    """Return a stable fingerprint for duplicate selected-layer warnings."""
    normalized = []
    for record in records:
        normalized.append({
            "code": clean_heritage_text(record.get("code")),
            "name": canonical_heritage_text(_record_name(record)),
            "geometry": clean_heritage_text(record.get("geometry_key")),
        })
    normalized.sort(
        key=lambda item: (item["code"], item["name"], item["geometry"])
    )
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
