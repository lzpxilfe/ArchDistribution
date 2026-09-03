"""Source-driven period/type classification for nearby-heritage layers."""

import re
import unicodedata


NAME_FIELD_KEYWORDS = (
    "유적명", "국가유산명", "문화재명", "지정명칭",
    "명칭", "site_name", "heritage_name", "name", "title",
)
ERA_FIELD_KEYWORDS = (
    "시대", "시기", "연대", "편년", "era", "period", "chronology", "age",
)
TYPE_FIELD_KEYWORDS = (
    "성격", "유형", "종류", "유적분류", "분류", "type", "class", "category",
)

ERA_NAME_TOKENS = (
    "구석기", "신석기", "청동기", "초기철기", "원삼국", "삼국",
    "고구려", "백제", "가야", "통일신라", "신라", "고려", "조선",
    "근대", "현대",
)
TYPE_NAME_TOKENS = (
    "유물산포지", "고분군", "고분", "분묘", "성곽", "산성", "읍성",
    "건물지", "주거지", "취락", "가마터", "요지", "사지", "사찰",
    "관방", "봉수", "제철", "생산유적", "생활유적",
)


def _field_key(value):
    return re.sub(r"[\s_\-]+", "", str(value or "")).casefold()


def find_semantic_field(field_names, keywords):
    """Choose an exact semantic field first, then a conservative substring."""
    fields = [(str(name), _field_key(name)) for name in field_names]
    keys = [(_field_key(keyword), index) for index, keyword in enumerate(keywords)]
    for keyword, _index in keys:
        for original, field_key in fields:
            if field_key == keyword:
                return original
    candidates = []
    for original, field_key in fields:
        for keyword, priority in keys:
            minimum = 2 if any(ord(char) > 127 for char in keyword) else 3
            if len(keyword) >= minimum and keyword in field_key:
                candidates.append((priority, len(field_key), original))
    return min(candidates)[2] if candidates else None


def category_values(value, *, ignored=()):
    """Split a supplier category cell into clean, non-placeholder labels."""
    if value is None:
        return set()
    ignored_keys = {_field_key(item) for item in ignored}
    result = set()
    for part in re.split(r"[,;/|\n\r·]+", str(value)):
        text = part.strip()
        if not text:
            continue
        key = _field_key(text)
        if key in {"null", "none", "nan", "미상", "불명"} or key in ignored_keys:
            continue
        result.add(text)
    return result


def infer_categories_from_name(name):
    """Return generic period/type tokens visibly present in a site name."""
    text = str(name or "")
    eras = {token for token in ERA_NAME_TOKENS if token in text}
    types = {token for token in TYPE_NAME_TOKENS if token in text}
    return eras, types


def _reference_name_key(value):
    """Normalize harmless display differences without changing the name."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", normalized)


def build_reference_name_index(reference_data):
    """Build a collision-safe lookup for reference names with space changes.

    Exact dictionary lookup remains authoritative. A normalized key is used
    only when every reference spelling for that key carries identical data;
    ambiguous collisions are deliberately excluded from the fallback index.
    """
    index = {}
    ambiguous = set()
    if not isinstance(reference_data, dict):
        return index
    for name, info in reference_data.items():
        key = _reference_name_key(name)
        if not key or key in ambiguous:
            continue
        if key in index and index[key] != info:
            index.pop(key, None)
            ambiguous.add(key)
        else:
            index[key] = info
    return index


def reference_info_for_name(reference_data, normalized_index, name):
    """Return exact or collision-safe whitespace-normalized reference data."""
    if not isinstance(reference_data, dict):
        return None
    text = str(name or "")
    exact = reference_data.get(text)
    if exact is not None:
        return exact
    return (normalized_index or {}).get(_reference_name_key(text))


def should_exclude_categories(eras, types, selection):
    """Apply the dialog's checked-category allowlist to one source feature.

    Only categories that were actually offered in the dialog participate.
    Unknown source values therefore remain included instead of being silently
    discarded.  A multi-valued field is retained when any displayed value in
    that dimension remains checked.
    """
    if not selection:
        return False
    if isinstance(selection, dict):
        allowed = set(selection.get("allowed") or [])
        available = set(selection.get("available") or [])
    else:
        allowed = set(selection)
        available = set(selection)

    def dimension_excluded(prefix, values):
        feature_tags = {f"{prefix}:{value}" for value in values if value}
        offered = feature_tags.intersection(available)
        return bool(offered) and not bool(offered.intersection(allowed))

    return (
        dimension_excluded("ERA", set(eras or ()))
        or dimension_excluded("TYPE", set(types or ()))
    )
