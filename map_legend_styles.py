"""Official-style legend definitions used by the QGIS renderers.

The values are deliberately plain Python data so the exact legend mapping can
be regression-tested without a QGIS runtime.  Colours were transcribed from
the National Heritage Administration legend supplied with this plugin.
"""

import re


# ``fill`` and ``stroke`` are CSS-style RGB hex values understood by QGIS.
CHANGE_ZONE_STYLES = {
    "1": {"fill": "#CD5400", "stroke": "#CD5400", "width": 0.2},
    "2": {"fill": "#CA03F0", "stroke": "#CA03F0", "width": 0.2},
    "3": {"fill": "#0A04D0", "stroke": "#0A04D0", "width": 0.2},
    "4": {"fill": "#942858", "stroke": "#942858", "width": 0.2},
    "5": {"fill": "#20BD03", "stroke": "#20BD03", "width": 0.2},
    "6": {"fill": "#C50800", "stroke": "#C50800", "width": 0.2},
    "7": {"fill": "#08D98F", "stroke": "#08D98F", "width": 0.2},
    "8": {"fill": "#E6DE00", "stroke": "#E6DE00", "width": 0.2},
    "2-1": {"fill": "#F200FA", "stroke": "#0022E2", "width": 0.8},
    "2-2": {"fill": "#F013DA", "stroke": "#227100", "width": 0.8},
    "2-3": {"fill": "#F000B8", "stroke": "#BC0090", "width": 0.8},
    "2-4": {"fill": "#E0029A", "stroke": "#16A58D", "width": 0.8},
    "2-5": {"fill": "#CD018D", "stroke": "#704017", "width": 0.8},
    "2-6": {"fill": "#B5057D", "stroke": "#BAB645", "width": 0.8},
    "3-1": {"fill": "#2701FC", "stroke": "#FFD400", "width": 0.8},
    "3-2": {"fill": "#4901FF", "stroke": "#FF6A00", "width": 0.8},
    "3-3": {"fill": "#5A01FF", "stroke": "#66FF99", "width": 0.8},
    "3-4": {"fill": "#8001FF", "stroke": "#92D050", "width": 0.8},
    "other": {"fill": "#634631", "stroke": "#634631", "width": 0.2},
}


DESIGNATION_LEGEND_STYLES = {
    "national_designated": {
        "label": "국가지정유산구역",
        "fill": "#FFFF7F",
        "stroke": "#525252",
        "width": 0.35,
        "fill_style": "dense4",
    },
    "local_designated": {
        "label": "시도지정유산구역",
        "fill": "#FFFF7F",
        "stroke": "#525252",
        "width": 0.35,
        "fill_style": "dense4",
    },
    "national_registered": {
        "label": "국가등록문화유산",
        "fill": "#F6CF0B",
        "stroke": "#F6CF0B",
        "width": 0.35,
        "fill_style": "dense4",
    },
    "local_registered": {
        "label": "시도등록문화유산",
        "fill": "#FFFFFF",
        "stroke": "#00FF28",
        "width": 0.55,
        "fill_style": "no",
    },
    "national_protection": {
        "label": "국가지정유산보호구역",
        "fill": "#62C7C7",
        "stroke": "#62C7C7",
        "width": 0.45,
        "fill_style": "dense4",
    },
    "local_protection": {
        "label": "시도지정유산보호구역",
        "fill": "#62C7C7",
        "stroke": "#62C7C7",
        "width": 0.45,
        "fill_style": "dense4",
    },
    "protection": {
        "label": "지정유산보호구역",
        "fill": "#62C7C7",
        "stroke": "#62C7C7",
        "width": 0.45,
        "fill_style": "dense4",
    },
}


def normalize_change_zone_code(value):
    """Return an official legend code for a supplied zone label, if known."""
    text = str(value or "").strip()
    compact = re.sub(r"\s+", "", text).replace("_", "-").replace(".", "-")
    compact = compact.replace("제", "")
    match = re.search(r"([123])[-]+([1-9][0-9]*)", compact)
    if match:
        code = f"{match.group(1)}-{match.group(2)}"
        return code if code in CHANGE_ZONE_STYLES else None
    match = re.fullmatch(r"([1-8])(?:구역)?", compact)
    if match:
        return match.group(1)
    # A malformed DBF encoding can turn the Korean suffix in ``1구역`` into
    # replacement characters while leaving the numeric official code intact.
    # Treat a single valid zone digit followed only by non-digits as a code;
    # never reinterpret values such as 10 or 101 as Zone 1.
    match = re.fullmatch(r"([1-8])[^0-9]+", compact)
    if match:
        return match.group(1)
    if any(token in compact for token in ("그외", "기타", "외구역")):
        return "other"
    return None


def change_zone_style(value):
    """Return a copy-safe style definition for a supplied zone label."""
    code = normalize_change_zone_code(value)
    return dict(CHANGE_ZONE_STYLES[code]) if code else None
