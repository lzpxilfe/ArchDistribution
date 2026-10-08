"""Language-neutral name and geometry relation signals for heritage records.

Two registers rarely spell one place identically.  Spacing, bracketed
aliases, Roman versus Arabic numerals, omitted administrative prefixes and
item-level qualifiers ("<site> tomb 12", "<temple> main hall") all occur in
the same national dataset.  This module turns two display names and a few
pre-computed geometry metrics into small, explainable relation labels that
the matching policy can combine with source roles.

No place or language vocabulary is embedded here.  Optional lexicons such as
designator unit words, ordinal letters and equivalent suffixes are read from
the versioned matching ruleset, so other registers can supply their own
without code changes.  Every function is QGIS independent.
"""

from dataclasses import dataclass
from functools import lru_cache
import json
import re
import unicodedata


NAME_EQUAL = "equal"
NAME_ALIAS = "alias"
NAME_AFFIX_OMITTED = "affix_omitted"
NAME_LEFT_SPECIFIC = "left_specific"
NAME_RIGHT_SPECIFIC = "right_specific"
NAME_SIBLING = "sibling"
NAME_DESIGNATOR_CONFLICT = "designator_conflict"
NAME_UNRELATED = "unrelated"

GEOMETRY_IDENTICAL = "identical"
GEOMETRY_SIMILAR = "similar"
GEOMETRY_LEFT_WITHIN = "left_within"
GEOMETRY_RIGHT_WITHIN = "right_within"
GEOMETRY_OVERLAP = "overlap"
GEOMETRY_NEAR = "near"
GEOMETRY_APART = "apart"
# Intersecting, but the caller supplied no coverage metrics (legacy callers,
# or point/line pairs without an areal intersection).
GEOMETRY_UNKNOWN = "unknown"

DEFAULT_RELATION_THRESHOLDS = {
    "identical_iou": 0.9,
    "within_coverage": 0.9,
    "similar_overlap": 0.5,
    "similar_area_ratio": 0.3,
    "near_distance_m": 50.0,
    "component_auto_coverage": 0.95,
    "co_located_iou": 0.95,
    "affix_min_chars": 3,
    "affix_min_extra_chars": 2,
    "component_min_chars": 2,
    "sibling_min_chars": 4,
}

DEFAULT_NAME_LEXICON = {
    "ordinal_prefixes": [],
    "designator_units": [],
    "feature_units": [],
    "lot_units": [],
    "ordinal_letters": "",
    "equivalent_suffixes": [],
}

_PLACEHOLDERS = {
    "", "-", "n/a", "na", "none", "null", "<null>", "nan",
}
_OPEN_BRACKETS = "([{（［｛〔【"
_CLOSE_BRACKETS = ")]}）］｝〕】"
_BRACKET_RE = re.compile(
    "[" + re.escape(_OPEN_BRACKETS) + "]"
    + "([^" + re.escape(_OPEN_BRACKETS + _CLOSE_BRACKETS) + "]*)"
    + "[" + re.escape(_CLOSE_BRACKETS) + "]"
)
_QUOTE_RE = re.compile("[\"'`´‘’‚‛“”„‟‹›«»「」『』]")
_DIGIT_DASH_RE = re.compile(r"(?<=\d)\s*[-‐‑‒–—―−~]\s*(?=\d)")
# Only I/V/X are read as numerals: single letters such as "C" or "L" are far
# more often section letters than Roman numbers in site registers.
_ROMAN_RE = re.compile(r"(?<![A-Za-z])([IVX]{1,6})(?![A-Za-z])")
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10}
_SEPARATOR_RE = re.compile(r"[^\w\-]+|_+")


def _roman_to_int(text):
    total = 0
    previous = 0
    for char in reversed(text):
        value = _ROMAN_VALUES[char]
        if value < previous:
            total -= value
        else:
            total += value
            previous = value
    # Reject non-canonical spellings such as "IIII" or "VX" so ordinary
    # capitalised words and codes are left untouched.
    return total if _int_to_roman(total) == text else None


def _int_to_roman(value):
    pairs = ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
    parts = []
    for number, symbol in pairs:
        while value >= number:
            parts.append(symbol)
            value -= number
    return "".join(parts)


def _replace_roman(match):
    value = _roman_to_int(match.group(1))
    return str(value) if value else match.group(1)


def relation_thresholds(rules=None):
    """Return relation thresholds with documented defaults filled in."""
    merged = dict(DEFAULT_RELATION_THRESHOLDS)
    merged.update((rules or {}).get("relation_thresholds") or {})
    return merged


def name_lexicon(rules=None):
    """Return the optional, data-supplied naming lexicon."""
    merged = dict(DEFAULT_NAME_LEXICON)
    merged.update((rules or {}).get("name_lexicon") or {})
    return merged


@dataclass(frozen=True)
class ParsedName:
    """Comparison keys derived from one display name."""

    key: str
    base: str
    designators: tuple
    aliases: tuple
    tokens: tuple = ()
    # The number names a physical feature ("tomb 44", "3호분"), not an
    # investigation round or a report volume.
    feature_numbered: bool = False


def _lexicon_signature(lexicon):
    return json.dumps(lexicon, ensure_ascii=False, sort_keys=True)


@lru_cache(maxsize=16)
def _compiled_lexicon(signature):
    lexicon = json.loads(signature)
    units = sorted(
        {str(unit).casefold() for unit in lexicon.get("designator_units") or []
         if str(unit).strip()},
        key=len,
        reverse=True,
    )
    unit_pattern = "|".join(re.escape(unit) for unit in units)
    unit_group = f"(?:{unit_pattern})?" if unit_pattern else ""
    letters = "".join(
        sorted(set(str(lexicon.get("ordinal_letters") or "").casefold()))
    )
    numeric = r"\d+(?:-\d+)*"
    alternatives = [
        rf"{numeric}{unit_group}",
        rf"[a-z]\d*(?:-\d+)*{unit_group}",
    ]
    if letters and unit_pattern:
        # Ordinal letters ("A", "가") need a unit word; on their own they are
        # too easily the last syllable of an ordinary word.
        alternatives.append(
            rf"[{re.escape(letters)}](?:{unit_pattern})"
        )
    token_re = re.compile(r"^(?:" + "|".join(alternatives) + r")$")
    glued_re = re.compile(rf"^(.*[^\d\-])({numeric}{unit_group})$")
    value_re = re.compile(
        r"^(\d+(?:-\d+)*|[a-z]\d*(?:-\d+)*"
        + (rf"|[{re.escape(letters)}]" if letters else "")
        + ")"
    )
    prefixes = [
        str(prefix) for prefix in lexicon.get("ordinal_prefixes") or []
        if str(prefix).strip()
    ]
    prefix_re = (
        re.compile(
            "(?:" + "|".join(re.escape(prefix) for prefix in prefixes)
            + r")\s*(?=\d)",
            re.IGNORECASE,
        )
        if prefixes else None
    )
    suffixes = []
    for pair in lexicon.get("equivalent_suffixes") or []:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            source = re.sub(r"\s+", "", str(pair[0])).casefold()
            target = re.sub(r"\s+", "", str(pair[1])).casefold()
            if source:
                suffixes.append((source, target))
    suffixes.sort(key=lambda item: len(item[0]), reverse=True)
    feature_units = tuple(sorted(
        {str(unit).casefold() for unit in lexicon.get("feature_units") or []
         if str(unit).strip()},
        key=len,
        reverse=True,
    ))
    lot_units = tuple(
        str(unit).casefold() for unit in lexicon.get("lot_units") or []
        if str(unit).strip()
    )
    return {
        "feature_units": feature_units,
        "lot_units": lot_units,
        "token_re": token_re,
        "glued_re": glued_re,
        "value_re": value_re,
        "prefix_re": prefix_re,
        "suffixes": tuple(suffixes),
    }


def _clean(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return "" if text.casefold() in _PLACEHOLDERS else text


def _tokens(text, compiled):
    text = _QUOTE_RE.sub("", text)
    text = _ROMAN_RE.sub(_replace_roman, text)
    if compiled["prefix_re"] is not None:
        text = compiled["prefix_re"].sub(" ", text)
    text = _DIGIT_DASH_RE.sub("-", text)
    tokens = []
    for raw in _SEPARATOR_RE.split(text.casefold()):
        token = raw.strip("-")
        if token:
            tokens.append(token)
    return tokens


def _apply_suffixes(key, compiled):
    for source, target in compiled["suffixes"]:
        if key.endswith(source) and len(key) > len(source):
            return key[:-len(source)] + target
    return key


def _split_designators(tokens, compiled):
    tokens = list(tokens)
    designators = []
    while len(tokens) > 1 and compiled["token_re"].match(tokens[-1]):
        designators.insert(0, tokens.pop())
    if tokens:
        # A number glued to the last word ("tomb3") is a designator too, but
        # a name made only of a designator keeps it as its key.
        glued = compiled["glued_re"].match(tokens[-1])
        if glued and glued.group(1).rstrip("-"):
            tokens[-1] = glued.group(1).rstrip("-")
            designators.insert(0, glued.group(2))
    return tokens, tuple(designators)


def _designator_values(designators, compiled):
    values = []
    for designator in designators:
        match = compiled["value_re"].match(designator)
        values.append(match.group(1) if match else designator)
    return tuple(values)


def _is_feature_numbered(designators, base_tokens, compiled):
    units = compiled["feature_units"]
    if not designators or not units:
        return False
    if any(designator.endswith(units) for designator in designators):
        return True
    # Unit before the number ("tomb 44"): the last base word is the unit.
    return bool(base_tokens) and base_tokens[-1] in units


_LOT_NUMBER_RE = re.compile(r"\d+\s*[-‐‑‒–—―−]\s*\d+")


def _names_a_lot(text, compiled):
    """Return whether bracketed text gives a lot or parcel number.

    "(49-6)" or "(462 lot)" locates one investigation among its neighbours;
    unlike an alias it must stay part of the name.
    """
    folded = text.casefold()
    if not any(char.isdigit() for char in folded):
        return False
    if not (
        _LOT_NUMBER_RE.search(folded)
        or any(unit in folded for unit in compiled["lot_units"])
    ):
        return False
    # A lot qualifier is the number plus at most a short word ("일원",
    # "and"); a bracketed full name that merely contains a number is an
    # alias.
    residue = folded
    for unit in compiled["lot_units"]:
        residue = residue.replace(unit, " ")
    residue = re.sub(r"[\d\W_]+", "", residue)
    return len(residue) <= 3


def _is_designator_only(text, compiled):
    tokens = _tokens(text, compiled)
    return bool(tokens) and all(
        compiled["token_re"].match(token) for token in tokens
    )


def _parse_plain(text, compiled):
    tokens = _tokens(text, compiled)
    key = _apply_suffixes("".join(tokens), compiled)
    base_tokens, designators = _split_designators(tokens, compiled)
    if base_tokens:
        base_tokens[-1] = _apply_suffixes(base_tokens[-1], compiled)
    base = "".join(base_tokens)
    return key, base, designators, tuple(base_tokens)


@lru_cache(maxsize=200_000)
def _parse_name_cached(value, signature):
    compiled = _compiled_lexicon(signature)
    text = _clean(value)
    if not text:
        return ParsedName("", "", (), ())

    aliases = []

    def bracket(match):
        inner = match.group(1).strip()
        if not inner:
            return " "
        if _is_designator_only(inner, compiled) or _names_a_lot(inner, compiled):
            # "(B area)", "(II)" or a lot number qualifies the name; keep it.
            return f" {inner} "
        aliases.append(inner)
        return " "

    primary = _BRACKET_RE.sub(bracket, text)
    key, base, designators, tokens = _parse_plain(primary, compiled)
    alias_keys = []
    for alias in aliases:
        alias_key = _parse_plain(alias, compiled)[0]
        if alias_key and alias_key != key:
            alias_keys.append(alias_key)
    if not key and alias_keys:
        key = alias_keys.pop(0)
        base = key
        tokens = (key,)
    return ParsedName(
        key=key,
        base=base or key,
        designators=_designator_values(designators, compiled),
        aliases=tuple(sorted(set(alias_keys))),
        tokens=tokens or ((base or key),),
        feature_numbered=_is_feature_numbered(designators, tokens, compiled),
    )


def parse_name(value, rules=None):
    """Return comparison keys for a display name."""
    signature = _lexicon_signature(name_lexicon(rules))
    return _parse_name_cached("" if value is None else str(value), signature)


def is_placeholder_name(value, rules=None, generic_keys=()):
    """Return whether a name identifies only a zone, not a place.

    Survey reports label their own sub-areas "Area 1", "Zone A-4" or with a
    generic type word.  Such a label carries no identity of its own; inside a
    named site it can only be a part of that site.
    """
    parsed = parse_name(value, rules)
    if not parsed.key:
        return True
    if parsed.key in set(generic_keys or ()):
        return True
    compiled = _compiled_lexicon(_lexicon_signature(name_lexicon(rules)))
    return all(compiled["token_re"].match(token) for token in parsed.tokens) or (
        parsed.base in set(generic_keys or ())
    )


def identity_name_key(value, rules=None):
    """Return the alias-free comparison key used for name equality."""
    return parse_name(value, rules).key


def _common_prefix_length(left, right):
    length = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        length += 1
    return length


def _affix_omitted(shorter, longer, thresholds):
    return (
        len(shorter) >= int(thresholds["affix_min_chars"])
        and longer.endswith(shorter)
        and len(longer) - len(shorter)
        >= int(thresholds["affix_min_extra_chars"])
    )


def _is_subsequence(short_tokens, long_tokens):
    iterator = iter(long_tokens)
    return all(token in iterator for token in short_tokens)


def _qualifier_variant(left, right, thresholds, generic):
    """Return whether two bases differ only by omitted qualifiers.

    "<county> <village> <name>" and "<county> <name>" or "<name>" describe
    one place; "<village A> <type>" and "<village B> <type>" do not.  The
    shorter name must therefore survive intact inside the longer one, either
    as its character suffix or as an ordered token subsequence ending on the
    same final word.
    """
    shorter, longer = sorted((left, right), key=lambda item: len(item.base))
    if (
        not shorter.base
        or shorter.base in generic
        or len(shorter.base) < int(thresholds["affix_min_chars"])
    ):
        return False
    if _affix_omitted(shorter.base, longer.base, thresholds):
        return True
    return (
        len(shorter.tokens) < len(longer.tokens)
        and shorter.tokens[-1:] == longer.tokens[-1:]
        and _is_subsequence(shorter.tokens, longer.tokens)
    )


def _opens_within(short_tokens, long_tokens):
    """Return whether ``short_tokens`` run inside ``long_tokens``.

    The last word may be extended by the longer name ("tomb" in "tombs",
    a feature word inside its collective form), so a numbered feature
    finds the group it belongs to without a vocabulary of plural forms.
    A longer name that continues with a number ("<village> 669-1 ...")
    names a lot or another numbered place, not the group.
    """
    size = len(short_tokens)
    if not size or size > len(long_tokens):
        return False
    head, last = tuple(short_tokens[:-1]), short_tokens[-1]
    for start in range(len(long_tokens) - size + 1):
        end = start + size
        if (
            tuple(long_tokens[start:end - 1]) == head
            and long_tokens[end - 1].startswith(last)
            and not any(
                char.isdigit() for char in "".join(long_tokens[end - 1:end + 1])
            )
        ):
            return True
    return False


def _trailing_cores(parsed, thresholds, generic):
    """Yield the name with leading qualifiers removed, longest first."""
    minimum = int(thresholds["affix_min_chars"])
    for start in range(1, len(parsed.tokens)):
        core = "".join(parsed.tokens[start:])
        if len(core) >= minimum and core not in generic:
            yield core


def name_relation(left, right, rules=None, generic_keys=()):
    """Classify how two display names relate.

    The labels are ordered from strongest to weakest identity evidence:

    ``equal``/``alias``
        Same comparison key, or one name is the bracketed alias of the other.
    ``affix_omitted``
        One name repeats the other with an extra leading qualifier, typically
        an omitted administrative prefix.
    ``left_specific``/``right_specific``
        One name is the other plus a qualifier or item number: a part, a
        building or a numbered feature of the other.
    ``designator_conflict``
        The same base name with different explicit numbers or letters; these
        are siblings and never the same entity.
    ``sibling``
        A long shared stem with different endings.
    ``unrelated``
        None of the above.
    """
    thresholds = relation_thresholds(rules)
    parsed_left = parse_name(left, rules)
    parsed_right = parse_name(right, rules)
    if not parsed_left.key or not parsed_right.key:
        return NAME_UNRELATED
    if parsed_left.key == parsed_right.key:
        return NAME_EQUAL
    left_keys = {parsed_left.key, *parsed_left.aliases}
    right_keys = {parsed_right.key, *parsed_right.aliases}
    if left_keys & right_keys:
        return NAME_ALIAS

    generic = set(generic_keys or ())
    left_base, right_base = parsed_left.base, parsed_right.base
    if left_base and right_base:
        shorter = min((left_base, right_base), key=len)
        bases_related = (
            left_base == right_base and shorter not in generic
        ) or _qualifier_variant(
            parsed_left, parsed_right, thresholds, generic
        )
        if bases_related:
            left_designators = parsed_left.designators
            right_designators = parsed_right.designators
            if left_designators and right_designators:
                if left_designators != right_designators:
                    return NAME_DESIGNATOR_CONFLICT
                return NAME_AFFIX_OMITTED
            if left_designators:
                return NAME_LEFT_SPECIFIC
            if right_designators:
                return NAME_RIGHT_SPECIFIC
            return NAME_AFFIX_OMITTED

    left_key, right_key = parsed_left.key, parsed_right.key
    shorter_key, longer_key = sorted((left_key, right_key), key=len)
    if shorter_key not in generic:
        if _affix_omitted(shorter_key, longer_key, thresholds):
            return NAME_AFFIX_OMITTED
        if (
            len(shorter_key) >= int(thresholds["component_min_chars"])
            and shorter_key in longer_key
        ):
            return (
                NAME_LEFT_SPECIFIC
                if longer_key == left_key
                else NAME_RIGHT_SPECIFIC
            )
    # A numbered feature ("<site> tomb 44") is a part of the unnumbered name
    # its base opens ("<site> tombs", "<county> <site> tombs"), never the
    # other way round.  Investigation rounds and volumes are not features.
    for numbered, plain, label in (
        (parsed_left, parsed_right, NAME_LEFT_SPECIFIC),
        (parsed_right, parsed_left, NAME_RIGHT_SPECIFIC),
    ):
        if (
            numbered.feature_numbered
            and not plain.designators
            and len(numbered.base) >= int(thresholds["affix_min_chars"])
            and numbered.base not in generic
            and plain.key not in generic
            and _opens_within(numbered.tokens, plain.tokens)
        ):
            return label
    # "<county> <temple>" versus "<temple> <hall>": the parent's core name,
    # without its leading qualifier, opens or sits inside the child's name.
    for parent, child, label in (
        (parsed_right, parsed_left, NAME_LEFT_SPECIFIC),
        (parsed_left, parsed_right, NAME_RIGHT_SPECIFIC),
    ):
        if parent.feature_numbered and not child.designators:
            # A numbered feature is never the parent of an unnumbered name.
            continue
        for core in _trailing_cores(parent, thresholds, generic):
            if core in child.key and not child.base.endswith(core):
                return label
    prefix = _common_prefix_length(left_key, right_key)
    if (
        prefix >= int(thresholds["sibling_min_chars"])
        and prefix < len(left_key)
        and prefix < len(right_key)
    ):
        return NAME_SIBLING
    return NAME_UNRELATED


def geometry_relation(
    *,
    intersects,
    distance=0.0,
    overlap_ratio=0.0,
    coverage_left=None,
    coverage_right=None,
    iou=None,
    area_ratio=None,
    rules=None,
):
    """Classify two footprints from pre-computed overlap metrics.

    ``coverage_left`` is the share of the left footprint covered by the
    intersection, so a value near one means the left record lies within the
    right record.
    """
    thresholds = relation_thresholds(rules)
    if not intersects:
        try:
            near = float(distance) <= float(thresholds["near_distance_m"])
        except (TypeError, ValueError):
            near = False
        return GEOMETRY_NEAR if near else GEOMETRY_APART
    if coverage_left is None or coverage_right is None:
        return GEOMETRY_UNKNOWN
    coverage_left = float(coverage_left)
    coverage_right = float(coverage_right)
    if iou is not None and float(iou) >= float(thresholds["identical_iou"]):
        return GEOMETRY_IDENTICAL
    within = float(thresholds["within_coverage"])
    left_within = coverage_left >= within
    right_within = coverage_right >= within
    if left_within and right_within:
        return GEOMETRY_SIMILAR
    if left_within:
        return GEOMETRY_LEFT_WITHIN
    if right_within:
        return GEOMETRY_RIGHT_WITHIN
    ratio = float(area_ratio) if area_ratio is not None else 0.0
    if (
        float(overlap_ratio or 0.0) >= float(thresholds["similar_overlap"])
        and ratio >= float(thresholds["similar_area_ratio"])
    ):
        return GEOMETRY_SIMILAR
    if coverage_left > 0 or coverage_right > 0:
        return GEOMETRY_OVERLAP
    # Footprints that only touch (adjacent parcels, a line crossing a
    # boundary) share no area: they are neighbours.
    return GEOMETRY_NEAR
