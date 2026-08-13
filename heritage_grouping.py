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


def area_designator_family(value):
    """Return the conservative name family for an explicit area suffix.

    The boolean is important: equal ordinary names are not area-part review
    evidence.  Callers can therefore distinguish ``A유적 I지역`` from a plain
    homonym without weakening the normal identity rules.
    """
    family, has_designator = strip_trailing_area_designator(value)
    return canonical_heritage_text(family), has_designator


def _source_identity_key(fallback_key):
    """Return the required per-source identity namespace.

    Initial archaeological identity must never be inferred from a display
    name.  The caller normally supplies ``SourceIdentity.uid``; raising for an
    absent key is safer than silently fusing unrelated homonyms.
    """
    fallback = canonical_heritage_text(fallback_key)
    if not fallback:
        raise ValueError(
            "fallback_key is required for an initial source identity"
        )
    return f"source:{fallback}"


def resolve_heritage_identity(
    project_name,
    site_name,
    heritage_name=None,
    fallback_key=None,
    preservation_action=None,
    preservation_number_scope=None,
):
    """Return separate investigation, site, number, and geometry identities.

    An excavation project is an investigation event, not necessarily one
    archaeological site.  Records from one project therefore share a map
    number, while every source record starts with its own entity and geometry
    keys.  A later, explicit ``same_entity`` review decision may unify those
    keys.  Names (including explicit I/II area suffixes) are never initial
    identity keys.

    The preservation workflow may explicitly provide
    ``preservation_number_scope`` (preferably a supplier site code) so one site
    keeps one label number across its action polygons.  This scope affects only
    numbering; entity and geometry identities remain source-based and the
    action remains available for categorized styling.

    The returned ``entity_key`` and ``dissolve_key`` aliases make it easy for
    callers to migrate to the more explicit research schema without changing
    their field-writing code all at once.
    """
    project = clean_heritage_text(project_name)
    source_key = _source_identity_key(fallback_key)

    investigation_key = (
        f"project:{canonical_heritage_text(project)}" if project else ""
    )

    site_entity_key = source_key
    preservation_scope = canonical_heritage_text(
        preservation_number_scope
    )
    if investigation_key:
        number_key = investigation_key
    elif preservation_scope:
        number_key = f"preservation_site:{preservation_scope}"
    else:
        number_key = source_key
    action_key = canonical_heritage_text(preservation_action)
    # Geometry grouping also starts per source.  The action suffix records why
    # two polygons must remain distinct without turning a name into identity.
    geometry_group_key = (
        f"{source_key}|action:{action_key}" if action_key else source_key
    )
    return {
        "investigation_key": investigation_key,
        "site_entity_key": site_entity_key,
        "entity_key": site_entity_key,
        "number_key": number_key,
        "geometry_group_key": geometry_group_key,
        "dissolve_key": geometry_group_key,
    }


def resolve_heritage_group(
    project_name,
    site_name,
    heritage_name=None,
    fallback_key=None,
    preservation_action=None,
    preservation_number_scope=None,
):
    """
    Resolve display metadata plus safe initial research identities.

    Project names may define a shared investigation/number.  All other initial
    number, entity, and geometry keys remain source based unless the dedicated
    preservation workflow supplies an explicit numbering scope.
    """
    project = clean_heritage_text(project_name)
    site = clean_heritage_text(site_name)
    heritage = clean_heritage_text(heritage_name)

    identity = resolve_heritage_identity(
        project,
        site,
        heritage,
        fallback_key,
        preservation_action,
        preservation_number_scope,
    )

    def attach_identity(decision):
        decision.update({
            "investigation_key": identity["investigation_key"],
            "site_entity_key": identity["site_entity_key"],
            "entity_key": identity["entity_key"],
            "number_key": identity["number_key"],
            "geometry_group_key": identity["geometry_group_key"],
            "dissolve_key": identity["geometry_group_key"],
        })
        # ``key`` is retained as the compatibility alias used by older callers.
        decision["key"] = identity["number_key"]
        return decision

    if project:
        return attach_identity(
            {
                "key": f"project:{canonical_heritage_text(project)}",
                "display_name": project,
                "basis": "project",
            },
        )

    if heritage:
        display_name = heritage
        if site and canonical_heritage_text(site) not in canonical_heritage_text(heritage):
            display_name = f"{heritage} ({site})"
        return attach_identity(
            {
                "key": f"heritage:{canonical_heritage_text(heritage)}",
                "display_name": display_name,
                "basis": "heritage",
            },
        )

    site_family, has_area_suffix = strip_trailing_area_designator(site)
    site_key = canonical_heritage_text(site)
    family_key = canonical_heritage_text(site_family)

    if site and has_area_suffix:
        return attach_identity(
            {
                "key": f"site_family:{family_key}",
                "display_name": site_family,
                "basis": "site_area",
            },
        )

    if site:
        return attach_identity(
            {
                "key": f"site:{site_key}",
                "display_name": site,
                "basis": "site",
            },
        )

    unique_key = canonical_heritage_text(fallback_key) or "unnamed"
    return attach_identity(
        {
            "key": f"feature:{unique_key}",
            "display_name": "N/A",
            "basis": "fallback",
        },
    )
