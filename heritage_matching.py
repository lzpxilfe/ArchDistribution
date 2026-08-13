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
from pathlib import Path
import re
from copy import deepcopy

try:
    from .heritage_grouping import (
        area_designator_family,
        canonical_heritage_text,
        clean_heritage_text,
    )
except ImportError:
    # Keep this policy module directly runnable by the validation scripts and
    # the normal-Python unit tests outside a loaded QGIS plugin package.
    from heritage_grouping import (
        area_designator_family,
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

RELATION_SAME_ENTITY = "same_entity"
RELATION_PARENT_CHILD = "parent_child"
RELATION_INVESTIGATION_SITE = "investigation_site"
RELATION_LEGAL_BOUNDARY_SITE = "legal_boundary_site"
RELATION_RELATED_SEPARATE = "related_separate"
RELATION_UNCERTAIN = "uncertain"
# Verbose aliases mirror the public output field name and make integration
# code self-documenting.  The shorter names remain the canonical API.
RELATION_TYPE_SAME_ENTITY = RELATION_SAME_ENTITY
RELATION_TYPE_PARENT_CHILD = RELATION_PARENT_CHILD
RELATION_TYPE_INVESTIGATION_SITE = RELATION_INVESTIGATION_SITE
RELATION_TYPE_LEGAL_BOUNDARY_SITE = RELATION_LEGAL_BOUNDARY_SITE
RELATION_TYPE_RELATED_SEPARATE = RELATION_RELATED_SEPARATE
RELATION_TYPE_UNCERTAIN = RELATION_UNCERTAIN
RELATION_TYPES = frozenset({
    RELATION_SAME_ENTITY,
    RELATION_PARENT_CHILD,
    RELATION_INVESTIGATION_SITE,
    RELATION_LEGAL_BOUNDARY_SITE,
    RELATION_RELATED_SEPARATE,
    RELATION_UNCERTAIN,
})

DEFAULT_MATCHING_RULES_PATH = Path(__file__).with_name("matching_rules.json")


@lru_cache(maxsize=8)
def _load_matching_rules_cached(path_text):
    path = Path(path_text)
    payload = path.read_bytes()
    rules = json.loads(payload.decode("utf-8"))
    if rules.get("schema_version") != 1:
        raise ValueError("Unsupported matching-rules schema_version")
    if not clean_heritage_text(rules.get("ruleset_version")):
        raise ValueError("matching rules must declare ruleset_version")
    for section in ("thresholds", "score_weights"):
        if not isinstance(rules.get(section), dict):
            raise ValueError(f"matching rules must contain {section}")
    return rules, hashlib.sha256(payload).hexdigest()


def load_matching_rules(path=None):
    """Load and validate a ruleset JSON file using only the standard library."""
    rules, _sha256 = _load_matching_rules_cached(
        str(Path(path or DEFAULT_MATCHING_RULES_PATH).resolve())
    )
    return deepcopy(rules)


def matching_rules_metadata(path=None):
    """Return the version and exact-file SHA-256 needed by run provenance."""
    resolved = Path(path or DEFAULT_MATCHING_RULES_PATH).resolve()
    rules, sha256 = _load_matching_rules_cached(str(resolved))
    return {
        "schema_version": rules["schema_version"],
        "ruleset_version": rules["ruleset_version"],
        "sha256": sha256,
        "filename": resolved.name,
    }


DEFAULT_MATCHING_RULES = load_matching_rules()
_DEFAULT_RULES_METADATA = matching_rules_metadata()
RULESET_VERSION = _DEFAULT_RULES_METADATA["ruleset_version"]
RULESET_SHA256 = _DEFAULT_RULES_METADATA["sha256"]

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


@lru_cache(maxsize=200_000)
def _address_tokens_cached(text):
    cleaned = clean_heritage_text(text)
    cleaned = re.sub(r"\([^)]*\)", " ", cleaned).casefold()
    return tuple(re.findall(r"[a-z가-힣]+|\d+", cleaned))


def canonical_address_tokens(value):
    """Return address components while preserving complete numeric tokens."""
    return _address_tokens_cached("" if value is None else str(value))


def addresses_match(left, right):
    """Compare equal/contained addresses without partial parcel-number matches.

    Token sequence containment accepts an omitted administrative prefix, but
    never equates numeric substrings such as parcel ``24-17`` and ``24-171``.
    """
    left_tokens = canonical_address_tokens(left)
    right_tokens = canonical_address_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    if left_tokens == right_tokens:
        return True
    shorter, longer = sorted(
        (left_tokens, right_tokens), key=lambda tokens: (len(tokens), tokens)
    )
    window_size = len(shorter)
    return any(
        tuple(longer[index:index + window_size]) == tuple(shorter)
        for index in range(len(longer) - window_size + 1)
    )


def name_similarity(left, right):
    left_key = canonical_name(left)
    right_key = canonical_name(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    return SequenceMatcher(None, left_key, right_key).ratio()


def name_contains(left, right, rules=None):
    left_key = canonical_name(left)
    right_key = canonical_name(right)
    active_rules = rules or DEFAULT_MATCHING_RULES
    thresholds = active_rules["thresholds"]
    min_chars = int(thresholds["name_containment_min_chars"])
    min_fraction = float(thresholds["name_containment_min_fraction"])
    if min(len(left_key), len(right_key)) < min_chars:
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
    return (
        shared >= min_chars
        and shared / min(len(left_key), len(right_key)) >= min_fraction
    )


def is_generic_name(value, rules=None):
    """Return whether a label carries too little identity for auto-merging."""
    active_rules = rules or DEFAULT_MATCHING_RULES
    generic = {
        canonical_name(item) for item in active_rules.get("generic_names", ())
    }
    return bool(canonical_name(value) in generic)


def _record_name(record):
    return clean_heritage_text(
        record.get("site_name")
        or record.get("name")
        or record.get("heritage_name")
    )


def _pair_kind(left_role, right_role):
    if left_role == ROLE_EXCAVATION and right_role == ROLE_EXCAVATION:
        return "excavation_area_parts"
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


def excavation_area_review_family(left, right):
    """Return a shared explicit area-name family eligible for review.

    This is deliberately narrower than ordinary fuzzy name matching.  Both
    records must be excavation records with explicit trailing area designators
    (for example I지역 and II-1지역).  Conflicting or one-sided project names
    reject the signal.  Spatial proximity is checked separately by
    :func:`evaluate_candidate`, so distant homonyms never become candidates
    solely because their display names share a family.
    """
    if (
        left.get("role") != ROLE_EXCAVATION
        or right.get("role") != ROLE_EXCAVATION
    ):
        return ""
    left_family, left_has_area = area_designator_family(_record_name(left))
    right_family, right_has_area = area_designator_family(
        _record_name(right)
    )
    if (
        not left_has_area
        or not right_has_area
        or not left_family
        or left_family != right_family
    ):
        return ""

    left_project = canonical_heritage_text(left.get("project_name"))
    right_project = canonical_heritage_text(right.get("project_name"))
    if (left_project or right_project) and left_project != right_project:
        return ""
    return left_family


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
    coverage_left: float = None
    coverage_right: float = None
    iou: float = None
    area_ratio: float = None
    centroid_distance: float = None
    boundary_distance: float = None
    geometry_pair: str = "polygon_polygon"
    relation_type: str = RELATION_UNCERTAIN

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
            "coverage_left": self.coverage_left,
            "coverage_right": self.coverage_right,
            "iou": self.iou,
            "area_ratio": self.area_ratio,
            "centroid_distance": self.centroid_distance,
            "boundary_distance": self.boundary_distance,
            "geometry_pair": self.geometry_pair,
            "relation_type": self.relation_type,
        }


def _metric(value, digits=4):
    if value is None:
        return None
    return round(float(value), digits)


def _normalized_geometry_pair(value):
    text = clean_heritage_text(value or "polygon_polygon").casefold()
    parts = re.findall(r"polygon|line(?:string)?|point", text)
    if len(parts) >= 2:
        normalized = ["line" if part.startswith("line") else part for part in parts[:2]]
        return "_".join(normalized)
    return re.sub(r"[^a-z]+", "_", text).strip("_") or "unknown"


def _geometry_allows_automatic_decision(geometry_pair, rules):
    allowed = {
        _normalized_geometry_pair(item)
        for item in rules.get("automatic_geometry_pairs", ())
    }
    return _normalized_geometry_pair(geometry_pair) in allowed


def evaluate_candidate(
    left,
    right,
    *,
    intersects,
    overlap_ratio,
    distance=0.0,
    preset=PRESET_BALANCED,
    coverage_left=None,
    coverage_right=None,
    iou=None,
    area_ratio=None,
    centroid_distance=None,
    boundary_distance=None,
    geometry_pair="polygon_polygon",
    rules=None,
):
    """Evaluate one spatially reduced pair.

    ``overlap_ratio`` is intersection area divided by the smaller polygon area.
    The caller may pass zero for non-polygon geometries.
    """
    active_rules = rules or DEFAULT_MATCHING_RULES
    thresholds = active_rules["thresholds"]
    weights = active_rules["score_weights"]
    left_role = left.get("role", ROLE_OTHER)
    right_role = right.get("role", ROLE_OTHER)
    pair_kind = _pair_kind(left_role, right_role)
    if not pair_kind:
        return None

    left_name = _record_name(left)
    right_name = _record_name(right)
    similarity = name_similarity(left_name, right_name)
    exact = bool(left_name and right_name and similarity == 1.0)
    containment = name_contains(left_name, right_name, active_rules)
    generic_name = is_generic_name(left_name, active_rules) or is_generic_name(
        right_name, active_rules
    )

    same_address = addresses_match(left.get("address"), right.get("address"))

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
            name_contains(project, distribution_name, active_rules)
            or name_similarity(project, distribution_name)
            >= float(thresholds["project_name_similarity"])
        )

    confidence = None
    rule = None
    if pair_kind == "excavation_area_parts":
        area_family = excavation_area_review_family(left, right)
        if not area_family or not (
            intersects
            or distance <= float(thresholds["exact_name_distance_m"])
        ):
            return None
        confidence = "medium"
        rule = "excavation_area_suffix_spatial_review"
    elif exact and intersects and overlap_ratio > 0:
        confidence = "medium" if generic_name else "high"
        rule = (
            "exact_generic_name_and_overlap"
            if generic_name
            else "exact_name_and_overlap"
        )
    elif exact and distance <= float(thresholds["exact_name_distance_m"]):
        confidence = "medium"
        rule = (
            "exact_generic_name_within_distance"
            if generic_name
            else "exact_name_within_50m"
        )
    elif intersects and overlap_ratio >= float(
        thresholds["review_overlap_ratio"]
    ) and (
        similarity >= float(thresholds["review_name_similarity"])
        or containment
    ):
        confidence = "medium"
        rule = (
            "name_containment_and_overlap"
            if containment and similarity < 0.90
            else "fuzzy_name_and_overlap"
        )
    elif (
        intersects
        and overlap_ratio >= float(thresholds["address_overlap_ratio"])
        and same_address
    ):
        confidence = "medium"
        rule = "strong_overlap_and_address"
    elif (
        pair_kind == "excavation_distribution"
        and intersects
        and overlap_ratio >= float(thresholds["review_overlap_ratio"])
        and project_signal
    ):
        confidence = "medium"
        rule = "project_name_and_overlap"
    else:
        return None

    if pair_kind == "excavation_area_parts":
        recommended = DECISION_MERGE
        # Area suffixes are a review signal, never identity proof.  This
        # remains false even in the automation-first preset.
        auto_apply = False
    elif pair_kind == "surface":
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
                    similarity >= float(
                        thresholds["automation_name_similarity"]
                    )
                    and overlap_ratio >= float(
                        thresholds["automation_overlap_ratio"]
                    )
                    and rule != "name_containment_and_overlap"
                )
            )

    if generic_name or not _geometry_allows_automatic_decision(
        geometry_pair, active_rules
    ):
        auto_apply = False

    address_score = 1.0 if same_address else 0.0
    score = min(
        1.0,
        (similarity * float(weights["name_similarity"]))
        + (
            min(max(float(overlap_ratio), 0.0), 1.0)
            * float(weights["overlap_ratio"])
        )
        + (address_score * float(weights["address"])),
    )

    if pair_kind == "excavation_area_parts":
        relation_type = RELATION_SAME_ENTITY
    elif pair_kind == "designated_excavation" or rule == "project_name_and_overlap":
        relation_type = RELATION_INVESTIGATION_SITE
    elif pair_kind == "surface":
        relation_type = RELATION_RELATED_SEPARATE
    elif rule == "name_containment_and_overlap":
        relation_type = RELATION_PARENT_CHILD
    elif recommended == DECISION_MERGE and exact and not generic_name:
        relation_type = RELATION_SAME_ENTITY
    else:
        relation_type = RELATION_UNCERTAIN

    normalized_pair = _normalized_geometry_pair(geometry_pair)

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
        coverage_left=_metric(coverage_left),
        coverage_right=_metric(coverage_right),
        iou=_metric(iou),
        area_ratio=_metric(area_ratio),
        centroid_distance=_metric(centroid_distance, 3),
        boundary_distance=_metric(boundary_distance, 3),
        geometry_pair=normalized_pair,
        relation_type=relation_type,
    )


def selected_content_fingerprint(records):
    """Return a stable fingerprint for duplicate selected-layer warnings."""
    normalized = []
    for record in records:
        normalized.append({
            # A role-aware full source fingerprint prevents two legitimate
            # records (for example, a designated asset and a distribution-map
            # record with the same code/name/geometry) from being discarded
            # before the typed matching rules can compare them.  The legacy
            # fields remain for callers that do not yet supply the richer
            # identity evidence.
            "role": clean_heritage_text(record.get("role")),
            "source_fingerprint": clean_heritage_text(
                record.get("content_fingerprint")
            ),
            "code": clean_heritage_text(record.get("code")),
            "name": canonical_heritage_text(_record_name(record)),
            "geometry": clean_heritage_text(record.get("geometry_key")),
        })
    normalized.sort(
        key=lambda item: (
            item["role"],
            item["source_fingerprint"],
            item["code"],
            item["name"],
            item["geometry"],
        )
    )
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
