"""Record-level exclusion signals for nearby-heritage maps.

A distribution map numbers places where archaeological or built heritage can
be located.  National registers also carry records that are not such places:
investigations that found no remains, intangible practices registered at an
address, and movable objects registered at their holding institution.

The engine below is language neutral.  It recognises two structures:

``outcome``
    A low-cardinality field (for example "remains: yes/no") whose value
    carries a negative marker and no positive marker.
``classes``
    Classification fields whose every value belongs to an enabled class.
    A record is kept when any of its classification values falls outside the
    enabled classes, so mixed records ("site, tree") are never removed.

All vocabulary lives in ``exclusion_rules.json`` and can be replaced for
other registers.  Nothing is deleted: the plugin keeps excluded records in an
audit layer with the rule that removed them.
"""

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata

try:
    from .attribute_classification import category_values
except ImportError:
    from attribute_classification import category_values


DEFAULT_EXCLUSION_RULES_PATH = Path(__file__).with_name(
    "exclusion_rules.json"
)
RULE_TOKEN_PREFIX = "RULE:"
# Audit reasons for records the operator left out in the attribute scan.
USER_EXCLUDED_NAME = "user_name"
USER_EXCLUDED_CATEGORY = "user_category"


def _compact(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\W_]+", "", text)


@lru_cache(maxsize=4)
def _load_cached(path_text):
    payload = Path(path_text).read_bytes()
    rules = json.loads(payload.decode("utf-8"))
    if rules.get("schema_version") != 1:
        raise ValueError("Unsupported exclusion-rules schema_version")
    return json.dumps(rules, ensure_ascii=False)


def load_exclusion_rules(path=None):
    """Load the exclusion lexicon as an independent copy."""
    resolved = Path(path or DEFAULT_EXCLUSION_RULES_PATH).resolve()
    return json.loads(_load_cached(str(resolved)))


def rule_definitions(rules=None):
    """Return ``[(rule_id, label_ko, label_en, default_enabled), ...]``."""
    rules = rules or load_exclusion_rules()
    definitions = []
    outcome = rules.get("outcome") or {}
    if outcome.get("id"):
        definitions.append((
            outcome["id"],
            outcome.get("label_ko") or outcome["id"],
            outcome.get("label_en") or outcome["id"],
            bool(outcome.get("default_enabled", False)),
        ))
    for item in rules.get("classes") or []:
        if item.get("id"):
            definitions.append((
                item["id"],
                item.get("label_ko") or item["id"],
                item.get("label_en") or item["id"],
                bool(item.get("default_enabled", False)),
            ))
    return definitions


def default_enabled_rules(rules=None):
    return [
        rule_id
        for rule_id, _ko, _en, enabled in rule_definitions(rules)
        if enabled
    ]


def resolve_enabled_rules(offered_and_checked=None, rules=None):
    """Combine reviewed dialog choices with defaults for unreviewed rules.

    ``offered_and_checked`` maps a rule id to the operator's checkbox state.
    A rule the scan never offered (it matched nothing in the scanned layers)
    falls back to its documented default.
    """
    choices = dict(offered_and_checked or {})
    enabled = []
    for rule_id, _ko, _en, default in rule_definitions(rules):
        if choices.get(rule_id, default):
            enabled.append(rule_id)
    return enabled


def _field_matches(field_name, keywords):
    key = _compact(field_name)
    return any(_compact(keyword) and _compact(keyword) in key
               for keyword in keywords)


def outcome_field_candidates(field_names, rules=None):
    """Return fields whose names suggest an investigation outcome.

    Callers measure only these fields' distinct values before
    :func:`prepare_layer_plan`, which keeps the check cheap on large layers.
    """
    rules = rules or load_exclusion_rules()
    keywords = (rules.get("outcome") or {}).get("field_keywords") or ()
    return [name for name in field_names if _field_matches(name, keywords)]


@dataclass(frozen=True)
class LayerExclusionPlan:
    """Fields and enabled rules prepared once per source layer."""

    outcome_field: str
    outcome_rule: str
    negative_markers: tuple
    positive_markers: tuple
    class_fields: tuple
    class_values: tuple

    @property
    def is_active(self):
        return bool(self.outcome_field or (self.class_fields and self.class_values))


def prepare_layer_plan(
    field_names,
    enabled_rules,
    *,
    distinct_value_counts=None,
    rules=None,
):
    """Choose the outcome and classification fields of one layer.

    ``distinct_value_counts`` maps a field name to its number of distinct
    values (or ``None`` when unknown).  An outcome field must be categorical;
    free-text columns that merely mention "none" are never used.
    """
    rules = rules or load_exclusion_rules()
    enabled = set(enabled_rules or ())
    counts = dict(distinct_value_counts or {})
    outcome = rules.get("outcome") or {}

    outcome_field = ""
    if outcome.get("id") in enabled:
        limit = int(outcome.get("max_distinct_values", 12))
        for name in field_names:
            if not _field_matches(name, outcome.get("field_keywords") or ()):
                continue
            distinct = counts.get(name)
            if distinct is not None and distinct > limit:
                continue
            outcome_field = name
            break

    class_values = []
    for item in rules.get("classes") or []:
        if item.get("id") not in enabled:
            continue
        for value in item.get("values") or ():
            key = _compact(value)
            if key:
                class_values.append((key, item["id"]))
    class_fields = tuple(
        name for name in field_names
        if _field_matches(name, rules.get("class_field_keywords") or ())
        and name != outcome_field
    ) if class_values else ()

    return LayerExclusionPlan(
        outcome_field=outcome_field,
        outcome_rule=str(outcome.get("id") or ""),
        negative_markers=tuple(
            key for key in (
                _compact(marker)
                for marker in outcome.get("negative_markers") or ()
            ) if key
        ),
        positive_markers=tuple(
            key for key in (
                _compact(marker)
                for marker in outcome.get("positive_markers") or ()
            ) if key
        ),
        class_fields=class_fields,
        class_values=tuple(class_values),
    )


def exclusion_reason(plan, attributes):
    """Return the rule id that excludes one record, or ``None``.

    ``attributes`` maps field names to values (a QGIS feature can be read with
    ``feature[name]``; a plain ``dict`` works in tests).
    """
    if plan is None or not plan.is_active:
        return None

    if plan.outcome_field:
        value = _compact(attributes[plan.outcome_field])
        if (
            value
            and any(marker in value for marker in plan.negative_markers)
            and not any(marker in value for marker in plan.positive_markers)
        ):
            return plan.outcome_rule

    if plan.class_fields:
        lookup = dict(plan.class_values)
        for field_name in plan.class_fields:
            values = category_values(attributes[field_name])
            if not values:
                continue
            classes = {lookup.get(_compact(value)) for value in values}
            if None not in classes:
                # Every value of this classification belongs to an enabled
                # class.  Report the first class in deterministic order.
                return sorted(classes)[0]
    return None
