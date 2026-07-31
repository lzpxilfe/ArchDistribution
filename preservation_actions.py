"""Canonical preservation-action values and their QGIS legend colors."""

import re
import unicodedata


PRESERVATION_ACTION_STYLES = {
    "현상보존": {
        "fill_color": "#B9F8FF",
        "outline_color": "#FF0000",
    },
    "정밀발굴조사": {
        "fill_color": "#E7D6FF",
        "outline_color": "#FF0000",
    },
    "시굴조사": {
        "fill_color": "#F5FFD2",
        "outline_color": "#FF0000",
    },
    "표본조사": {
        "fill_color": "#FFDFDF",
        "outline_color": "#FF0000",
    },
}

PRESERVATION_ACTION_FIELD_CANDIDATES = (
    "보존조치",
    "조치내용",
    "보존방안",
    "조사조치",
    "PRESERVATION",
    "ACTION",
)

_ACTION_ALIASES = {
    "현상보존": "현상보존",
    "현상": "현상보존",
    "정밀발굴조사": "정밀발굴조사",
    "정밀발굴": "정밀발굴조사",
    "시굴조사": "시굴조사",
    "시굴": "시굴조사",
    "표본조사": "표본조사",
    "표본": "표본조사",
}


def _canonical_action_text(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"[\s_()]+", "", text).casefold()


def normalize_preservation_action(value):
    """Normalize common action variants while retaining unknown source values."""
    if value is None:
        return ""

    display_text = re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", str(value)),
    ).strip()
    if not display_text or display_text.casefold() in {"null", "none", "n/a", "<null>"}:
        return ""

    return _ACTION_ALIASES.get(_canonical_action_text(display_text), display_text)


def preservation_action_style(value):
    """Return the configured legend style for a known action, if any."""
    return PRESERVATION_ACTION_STYLES.get(normalize_preservation_action(value))


def recognized_preservation_actions(values):
    """Return official action values recognized in an iterable of source values."""
    return {
        normalized
        for value in values
        if (normalized := normalize_preservation_action(value))
        in PRESERVATION_ACTION_STYLES
    }
