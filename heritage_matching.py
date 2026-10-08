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
    from . import heritage_relations as relations
except ImportError:
    # Keep this policy module directly runnable by the validation scripts and
    # the normal-Python unit tests outside a loaded QGIS plugin package.
    from heritage_grouping import (
        area_designator_family,
        canonical_heritage_text,
        clean_heritage_text,
    )
    import heritage_relations as relations


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
# Distinct records drawn on one footprint (for example several items that a
# register locates at their host site).  They may share a map number while
# keeping separate entities.
RELATION_CO_LOCATED = "co_located"
RELATION_UNCERTAIN = "uncertain"
# Verbose aliases mirror the public output field name and make integration
# code self-documenting.  The shorter names remain the canonical API.
RELATION_TYPE_SAME_ENTITY = RELATION_SAME_ENTITY
RELATION_TYPE_PARENT_CHILD = RELATION_PARENT_CHILD
RELATION_TYPE_INVESTIGATION_SITE = RELATION_INVESTIGATION_SITE
RELATION_TYPE_LEGAL_BOUNDARY_SITE = RELATION_LEGAL_BOUNDARY_SITE
RELATION_TYPE_RELATED_SEPARATE = RELATION_RELATED_SEPARATE
RELATION_TYPE_CO_LOCATED = RELATION_CO_LOCATED
RELATION_TYPE_UNCERTAIN = RELATION_UNCERTAIN
RELATION_TYPES = frozenset({
    RELATION_SAME_ENTITY,
    RELATION_PARENT_CHILD,
    RELATION_INVESTIGATION_SITE,
    RELATION_LEGAL_BOUNDARY_SITE,
    RELATION_RELATED_SEPARATE,
    RELATION_CO_LOCATED,
    RELATION_UNCERTAIN,
})

# Same-register pairs.  Earlier releases never compared two records of one
# role, so a register that lists a site and each of its numbered features,
# buildings or movable items received one map number per record.
PAIR_DISTRIBUTION_PARTS = "distribution_parts"
PAIR_DESIGNATED_PARTS = "designated_parts"
SAME_SOURCE_PAIR_KINDS = frozenset({
    PAIR_DISTRIBUTION_PARTS,
    PAIR_DESIGNATED_PARTS,
})
MERGE_MODE_SUPPRESS = "suppress"
MERGE_MODE_UNION = "union"


def is_union_merge(candidate):
    """Return whether an accepted merge keeps both footprints visible."""
    return (
        candidate.get("merge_mode") == MERGE_MODE_UNION
        or candidate.get("pair_kind") == "excavation_area_parts"
    )

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


def addresses_match(left, right, require_parcel=False):
    """Compare equal/contained addresses without partial parcel-number matches.

    Token sequence containment accepts an omitted administrative prefix, but
    never equates numeric substrings such as parcel ``24-17`` and ``24-171``.
    With ``require_parcel`` both addresses must name a parcel number: two
    records in the same village are neighbours, not evidence of identity.
    """
    left_tokens = canonical_address_tokens(left)
    right_tokens = canonical_address_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    if require_parcel and not (
        any(token.isdigit() for token in left_tokens)
        and any(token.isdigit() for token in right_tokens)
    ):
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
    if left_role == ROLE_DISTRIBUTION and right_role == ROLE_DISTRIBUTION:
        return PAIR_DISTRIBUTION_PARTS
    if is_designated_role(left_role) and is_designated_role(right_role):
        return PAIR_DESIGNATED_PARTS
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
    name_relation: str = None
    geometry_relation: str = None
    # "suppress": the representative carries the label and the other record
    # moves to the audit layer.  "union": both footprints stay on the map and
    # are dissolved under one number (parts or revisions of one site).
    merge_mode: str = "suppress"

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
            "name_relation": self.name_relation,
            "geometry_relation": self.geometry_relation,
            "merge_mode": self.merge_mode,
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


def _generic_identity_keys(rules):
    return frozenset(
        key for key in (
            relations.identity_name_key(item, rules)
            for item in rules.get("generic_names", ())
        ) if key
    )


def _automatic(confidence, preset):
    if preset == PRESET_CONSERVATIVE:
        return False
    return confidence == "high"


def _same_register_relation(
    pair_kind,
    name_relation,
    geometry_relation,
    *,
    coverage_left,
    coverage_right,
    iou,
    generic_name,
    rules,
):
    """Return ``(rule, confidence, decision, relation, parent_side, mode)``.

    Records from one register are compared only through structural evidence:
    the same normalised name, an omitted leading qualifier, a more specific
    name lying inside its parent, or several records drawn on one footprint.
    Fuzzy similarity alone is never used here because numbered siblings
    ("tomb 12"/"tomb 13") are textually almost identical.
    """
    thresholds = relations.relation_thresholds(rules)
    legal_pair = pair_kind == PAIR_DESIGNATED_PARTS
    overlapping = geometry_relation in {
        relations.GEOMETRY_IDENTICAL,
        relations.GEOMETRY_SIMILAR,
        relations.GEOMETRY_LEFT_WITHIN,
        relations.GEOMETRY_RIGHT_WITHIN,
        relations.GEOMETRY_OVERLAP,
        relations.GEOMETRY_UNKNOWN,
        relations.GEOMETRY_NEAR,
    }
    similar = geometry_relation in {
        relations.GEOMETRY_IDENTICAL,
        relations.GEOMETRY_SIMILAR,
    }
    if name_relation in {relations.NAME_EQUAL, relations.NAME_ALIAS}:
        if not overlapping:
            return None
        confidence = "high" if similar and not generic_name else "medium"
        # Same-named pieces of one register are one site: keep every piece
        # visible (adjacent parts, split multiparts) under one number.
        return (
            "same_register_duplicate",
            confidence,
            DECISION_MERGE,
            RELATION_SAME_ENTITY,
            None,
            MERGE_MODE_UNION,
        )
    if name_relation == relations.NAME_AFFIX_OMITTED and similar:
        confidence = (
            "high"
            if geometry_relation == relations.GEOMETRY_IDENTICAL
            and not generic_name
            else "medium"
        )
        return (
            "same_register_affix_duplicate",
            confidence,
            DECISION_MERGE,
            RELATION_SAME_ENTITY,
            None,
            MERGE_MODE_UNION,
        )
    if name_relation in {
        relations.NAME_LEFT_SPECIFIC,
        relations.NAME_RIGHT_SPECIFIC,
    }:
        child_side = (
            "left" if name_relation == relations.NAME_LEFT_SPECIFIC
            else "right"
        )
        child_coverage = (
            coverage_left if child_side == "left" else coverage_right
        )
        child_inside = (
            geometry_relation == relations.GEOMETRY_IDENTICAL
            or geometry_relation == f"{child_side}_within"
            or (
                geometry_relation == relations.GEOMETRY_SIMILAR
                and child_coverage is not None
                and float(child_coverage)
                >= float(thresholds["within_coverage"])
            )
        )
        if not child_inside:
            return None
        confidence = (
            "high"
            if child_coverage is not None
            and float(child_coverage)
            >= float(thresholds["component_auto_coverage"])
            else "medium"
        )
        parent_side = "right" if child_side == "left" else "left"
        return (
            "component_within_parent",
            confidence,
            DECISION_LINK if legal_pair else DECISION_MERGE,
            RELATION_PARENT_CHILD,
            parent_side,
            MERGE_MODE_SUPPRESS,
        )
    if (
        iou is not None
        and float(iou) >= float(thresholds["co_located_iou"])
    ):
        # Several distinct records on one footprint: sharing one label avoids
        # stacking numbers on the same polygon, but published maps also list
        # such items separately, so this stays a reviewed recommendation.
        # Legal designations keep their own numbers and are only linked.
        return (
            "co_located_footprint",
            "medium",
            DECISION_LINK if legal_pair else DECISION_MERGE,
            RELATION_CO_LOCATED,
            None,
            MERGE_MODE_SUPPRESS,
        )
    return None


def _cross_register_component(
    pair_kind,
    name_relation,
    geometry_relation,
    left_role,
    right_role,
    *,
    coverage_left,
    coverage_right,
    rules,
):
    """Return a component relation between records of different registers.

    A more specific name lying inside a less specific one ("<site> tomb 12"
    inside "<site>") is a part of that site.  A distribution-map part joins
    its parent's number; a part with its own legal or investigation identity
    keeps its number and is linked instead.
    """
    if pair_kind == "surface" or name_relation not in {
        relations.NAME_LEFT_SPECIFIC,
        relations.NAME_RIGHT_SPECIFIC,
    }:
        return None
    child_side = (
        "left" if name_relation == relations.NAME_LEFT_SPECIFIC else "right"
    )
    if geometry_relation != f"{child_side}_within":
        return None
    thresholds = relations.relation_thresholds(rules)
    child_coverage = coverage_left if child_side == "left" else coverage_right
    child_role = left_role if child_side == "left" else right_role
    confidence = (
        "high"
        if child_coverage is not None
        and float(child_coverage)
        >= float(thresholds["component_auto_coverage"])
        else "medium"
    )
    decision = (
        DECISION_MERGE if child_role == ROLE_DISTRIBUTION else DECISION_LINK
    )
    parent_side = "right" if child_side == "left" else "left"
    return (
        "component_within_parent",
        confidence,
        decision,
        RELATION_PARENT_CHILD,
        parent_side,
    )


def _survey_relation(
    left,
    right,
    name_relation,
    geometry_relation,
    *,
    coverage_left,
    coverage_right,
    rules,
    generic_keys,
):
    """Classify a surface-survey record against a mapped site or survey.

    Surveys start from the distribution map and then redraw, extend or split
    its sites, or mark action zones inside them.  Those are revisions of one
    site, not new sites.  They stay review-only (a survey record is never
    removed automatically) but the recommendation explains the relation:

    * same or omitted-qualifier name sharing ground: one site, both
      footprints kept under one number (``union``);
    * a more specific name, or a bare zone label, lying inside the site:
      a part that joins the site's number.
    """
    left_role = left.get("role")
    right_role = right.get("role")
    other_role = right_role if left_role == ROLE_SURFACE else left_role
    if other_role not in {ROLE_DISTRIBUTION, ROLE_SURFACE}:
        return None
    thresholds = relations.relation_thresholds(rules)
    touching = geometry_relation in {
        relations.GEOMETRY_IDENTICAL,
        relations.GEOMETRY_SIMILAR,
        relations.GEOMETRY_LEFT_WITHIN,
        relations.GEOMETRY_RIGHT_WITHIN,
        relations.GEOMETRY_OVERLAP,
        relations.GEOMETRY_NEAR,
    }
    if name_relation in {
        relations.NAME_EQUAL,
        relations.NAME_ALIAS,
        relations.NAME_AFFIX_OMITTED,
    } and touching:
        confidence = (
            "high"
            if geometry_relation in {
                relations.GEOMETRY_IDENTICAL,
                relations.GEOMETRY_SIMILAR,
            }
            else "medium"
        )
        return (
            "survey_revision_same_site",
            confidence,
            RELATION_SAME_ENTITY,
            None,
            MERGE_MODE_UNION,
        )

    within = float(thresholds["within_coverage"])
    for side, record, coverage, specific in (
        ("left", left, coverage_left, relations.NAME_LEFT_SPECIFIC),
        ("right", right, coverage_right, relations.NAME_RIGHT_SPECIFIC),
    ):
        if record.get("role") != ROLE_SURFACE or coverage is None:
            continue
        inside = float(coverage) >= within
        zone_label = relations.is_placeholder_name(
            _record_name(record), rules, generic_keys
        )
        if inside and (name_relation == specific or zone_label):
            return (
                "survey_zone_within_site",
                "medium",
                RELATION_PARENT_CHILD,
                "right" if side == "left" else "left",
                MERGE_MODE_SUPPRESS,
            )
    return None


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
    The caller may pass zero for non-polygon geometries.  When the coverage
    metrics are supplied, name and footprint relations
    (:mod:`heritage_relations`) take precedence; otherwise the original
    name-similarity rules apply unchanged.
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
    name_rel = relations.name_relation(
        left_name,
        right_name,
        active_rules,
        _generic_identity_keys(active_rules),
    )
    geometry_rel = relations.geometry_relation(
        intersects=intersects,
        distance=distance,
        overlap_ratio=overlap_ratio,
        coverage_left=coverage_left,
        coverage_right=coverage_right,
        iou=iou,
        area_ratio=area_ratio,
        rules=active_rules,
    )

    same_address = addresses_match(
        left.get("address"), right.get("address"), require_parcel=True
    )
    address_score = 1.0 if same_address else 0.0
    score = round(min(
        1.0,
        (similarity * float(weights["name_similarity"]))
        + (
            min(max(float(overlap_ratio), 0.0), 1.0)
            * float(weights["overlap_ratio"])
        )
        + (address_score * float(weights["address"])),
    ), 4)
    automatic_geometry = _geometry_allows_automatic_decision(
        geometry_pair, active_rules
    )

    def build(
        confidence,
        rule,
        recommended,
        auto_apply,
        relation_type,
        representative_uid=None,
        merge_mode=MERGE_MODE_SUPPRESS,
    ):
        if generic_name or not automatic_geometry:
            auto_apply = False
        return MatchCandidate(
            left_uid=str(left.get("uid")),
            right_uid=str(right.get("uid")),
            pair_kind=pair_kind,
            confidence=confidence,
            score=score,
            rule=rule,
            recommended_decision=recommended,
            representative_uid=(
                representative_uid or _representative_uid(left, right)
            ),
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
            geometry_pair=_normalized_geometry_pair(geometry_pair),
            relation_type=relation_type,
            name_relation=name_rel,
            geometry_relation=geometry_rel,
            merge_mode=merge_mode,
        )

    if pair_kind in SAME_SOURCE_PAIR_KINDS:
        decided = _same_register_relation(
            pair_kind,
            name_rel,
            geometry_rel,
            coverage_left=coverage_left,
            coverage_right=coverage_right,
            iou=iou,
            generic_name=generic_name,
            rules=active_rules,
        )
        if decided is None:
            return None
        (
            rule, confidence, recommended, relation_type, parent_side, mode,
        ) = decided
        representative = (
            str(left.get("uid")) if parent_side == "left"
            else str(right.get("uid")) if parent_side == "right"
            else None
        )
        return build(
            confidence,
            rule,
            recommended,
            _automatic(confidence, preset),
            relation_type,
            representative,
            mode,
        )

    # Explicit, different designators ("tomb 1"/"tomb 2", "I"/"II") name
    # sibling records, never one entity.  Excavation area parts keep their
    # dedicated review rule below.
    if (
        name_rel == relations.NAME_DESIGNATOR_CONFLICT
        and pair_kind != "excavation_area_parts"
    ):
        return None

    if pair_kind == "surface" and geometry_rel != relations.GEOMETRY_UNKNOWN:
        survey = _survey_relation(
            left,
            right,
            name_rel,
            geometry_rel,
            coverage_left=coverage_left,
            coverage_right=coverage_right,
            rules=active_rules,
            generic_keys=_generic_identity_keys(active_rules),
        )
        if survey is not None:
            rule, confidence, relation_type, parent_side, mode = survey
            # Survey records are never suppressed automatically.
            return build(
                confidence,
                rule,
                DECISION_MERGE,
                False,
                relation_type,
                (
                    str(left.get("uid")) if parent_side == "left"
                    else str(right.get("uid")) if parent_side == "right"
                    else None
                ),
                mode,
            )

    component = _cross_register_component(
        pair_kind,
        name_rel,
        geometry_rel,
        left_role,
        right_role,
        coverage_left=coverage_left,
        coverage_right=coverage_right,
        rules=active_rules,
    )
    if component is not None:
        rule, confidence, recommended, relation_type, parent_side = component
        return build(
            confidence,
            rule,
            recommended,
            _automatic(confidence, preset),
            relation_type,
            str(left.get("uid")) if parent_side == "left"
            else str(right.get("uid")),
        )

    # Spelling variants that survive whitespace folding (bracketed aliases,
    # Roman numerals, punctuation, an omitted leading qualifier on a shared
    # footprint) are equal names for the established rules below.
    exact_rule_prefix = "exact"
    if not exact and pair_kind != "excavation_area_parts":
        if name_rel in {relations.NAME_EQUAL, relations.NAME_ALIAS}:
            exact = True
            exact_rule_prefix = "normalized"
        elif name_rel == relations.NAME_AFFIX_OMITTED and geometry_rel in {
            relations.GEOMETRY_IDENTICAL,
            relations.GEOMETRY_SIMILAR,
        }:
            exact = True
            exact_rule_prefix = "affix_omitted"

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
            f"{exact_rule_prefix}_generic_name_and_overlap"
            if generic_name
            else f"{exact_rule_prefix}_name_and_overlap"
        )
    elif exact and distance <= float(thresholds["exact_name_distance_m"]):
        confidence = "medium"
        rule = (
            f"{exact_rule_prefix}_generic_name_within_distance"
            if generic_name
            else f"{exact_rule_prefix}_name_within_50m"
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

    return build(confidence, rule, recommended, auto_apply, relation_type)


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
