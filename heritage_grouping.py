"""Grouping rules for multipart archaeological sites."""

import re
import unicodedata


_EMPTY_LABELS = {
    "",
    "-",
    "n/a",
    "na",
    "none",
    "null",
    "<null>",
    "미상",
    "없음",
}

_DASH_TRANSLATION = str.maketrans({
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "−": "-",
})

# Matches only explicit trailing area designators. It intentionally does not
# strip tomb/building numbers such as "1호" because those can be distinct sites.
_AREA_TOKEN = r"(?:[IVXLCDM]+|\d+)"
_AREA_SEQUENCE = rf"(?:제\s*)?{_AREA_TOKEN}(?:\s*[-~·ㆍ,/]\s*{_AREA_TOKEN})*"
_AREA_UNIT = r"(?:지역|지구|구역|구간|지점)"
_AREA_SUFFIX_RE = re.compile(
    rf"(?:\(\s*{_AREA_SEQUENCE}\s*{_AREA_UNIT}\s*\)"
    rf"|\[\s*{_AREA_SEQUENCE}\s*{_AREA_UNIT}\s*\]"
    rf"|{_AREA_SEQUENCE}\s*{_AREA_UNIT})\s*$",
    re.IGNORECASE,
)


def clean_heritage_text(value):
    """Return a normalized display string without treating placeholders as names."""
    if value is None:
        return ""

    text = unicodedata.normalize("NFKC", str(value))
    text = text.translate(_DASH_TRANSLATION)
    text = re.sub(r"\s+", " ", text).strip()
    if text.casefold() in _EMPTY_LABELS:
        return ""
    return text


def canonical_heritage_text(value):
    """Return a stable, conservative comparison key for a heritage label."""
    text = clean_heritage_text(value)
    return re.sub(r"\s+", "", text).casefold()


def strip_trailing_area_designator(value):
    """
    Remove an explicit trailing area label and report whether it was removed.

    Examples:
        "... 유적 I 지역" -> "... 유적"
        "... 유적 II-1,2,3지역" -> "... 유적"
        "... 유적 1호" -> unchanged
    """
    text = clean_heritage_text(value)
    if not text:
        return "", False

    stripped = _AREA_SUFFIX_RE.sub("", text).rstrip(" -·ㆍ,/")
    if stripped == text or not stripped:
        return text, False
    return stripped, True


def _attach_geometry_and_number_keys(decision, preservation_action):
    """
    Keep one numbering identity while preserving separate action geometries.

    A site split into, for example, 시굴조사 and 정밀발굴조사 areas must retain
    both polygons for categorized styling, but both polygons should display the
    same site number.
    """
    number_key = decision["key"]
    action_key = canonical_heritage_text(preservation_action)
    decision["number_key"] = number_key
    decision["dissolve_key"] = (
        f"{number_key}|action:{action_key}" if action_key else number_key
    )
    return decision


def resolve_heritage_group(
    project_name,
    site_name,
    heritage_name=None,
    fallback_key=None,
    preservation_action=None,
):
    """
    Resolve a dissolve key and representative name for numbering.

    Grouping precedence:
    1. A project name, regardless of its individual site/area names.
    2. A designated national-heritage name when no project name is available.
    3. A site-name family when only an explicit area suffix differs.
    4. The exact site name.
    5. A caller-provided unique fallback for unnamed records.
    """
    project = clean_heritage_text(project_name)
    site = clean_heritage_text(site_name)
    heritage = clean_heritage_text(heritage_name)

    if project:
        return _attach_geometry_and_number_keys(
            {
                "key": f"project:{canonical_heritage_text(project)}",
                "display_name": project,
                "basis": "project",
            },
            preservation_action,
        )

    if heritage:
        display_name = heritage
        if site and canonical_heritage_text(site) not in canonical_heritage_text(heritage):
            display_name = f"{heritage} ({site})"
        return _attach_geometry_and_number_keys(
            {
                "key": f"heritage:{canonical_heritage_text(heritage)}",
                "display_name": display_name,
                "basis": "heritage",
            },
            preservation_action,
        )

    site_family, has_area_suffix = strip_trailing_area_designator(site)
    site_key = canonical_heritage_text(site)
    family_key = canonical_heritage_text(site_family)

    if site and has_area_suffix:
        return _attach_geometry_and_number_keys(
            {
                "key": f"site_family:{family_key}",
                "display_name": site_family,
                "basis": "site_area",
            },
            preservation_action,
        )

    if site:
        return _attach_geometry_and_number_keys(
            {
                "key": f"site:{site_key}",
                "display_name": site,
                "basis": "site",
            },
            preservation_action,
        )

    unique_key = canonical_heritage_text(fallback_key) or "unnamed"
    return _attach_geometry_and_number_keys(
        {
            "key": f"feature:{unique_key}",
            "display_name": "N/A",
            "basis": "fallback",
        },
        preservation_action,
    )
