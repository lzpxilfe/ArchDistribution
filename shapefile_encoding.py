"""Conservative encoding detection for legacy DBF attribute tables."""

from pathlib import Path


# dBASE language-driver IDs relevant to Korean public GIS data.  A .cpg file
# remains authoritative; this is used only when that declaration is absent.
DBF_LANGUAGE_DRIVER_ENCODINGS = {
    0x79: "CP949",  # Korean (ANSI/OEM Korean in common shapefile writers)
}


def _normalise_cpg_encoding(value):
    """Return the QGIS/Python spelling for a .cpg declaration."""
    aliases = {
        "949": "CP949",
        "CP-949": "CP949",
        "EUC_KR": "EUC-KR",
        "UTF8": "UTF-8",
    }
    declared = str(value or "").strip()
    return aliases.get(declared.upper(), declared)


def declared_shapefile_encoding(shp_path):
    """Return ``(encoding, basis)`` before QGIS reads a shapefile's DBF.

    The point of this helper is timing: QGIS must be told about CP949 before
    callers inspect fields or attributes.  A .cpg declaration wins; absent
    that, the DBF language driver or a high-confidence byte check is used.
    """
    path = Path(shp_path)
    if path.suffix.casefold() != ".shp":
        return None, None
    # The DBF language driver records the bytes actually stored in the
    # attribute table.  Some public downloads ship a stale ``UTF-8`` .cpg
    # next to a CP949 DBF; trusting that sidecar first creates mojibake before
    # the plugin can inspect the zone values.  A positive CP949 DBF detection
    # therefore takes precedence over a conflicting sidecar declaration.
    inferred = infer_dbf_encoding(path.with_suffix(".dbf"))
    if inferred == "CP949":
        return inferred, "DBF automatic detection"

    cpg_path = path.with_suffix(".cpg")
    if cpg_path.exists():
        try:
            declared = _normalise_cpg_encoding(
                cpg_path.read_text(encoding="ascii", errors="ignore")
            )
        except OSError:
            declared = ""
        if declared:
            return declared, ".cpg"
    return (inferred, "DBF automatic detection") if inferred else (None, None)


def infer_dbf_encoding(dbf_path, *, sample_size=65536):
    """Return a high-confidence DBF encoding or ``None``.

    UTF-8 is never guessed over a valid provider default.  CP949 is selected
    only when the DBF language-driver explicitly says so, or UTF-8 decoding
    demonstrably fails while CP949 yields Korean text without replacements.
    """
    try:
        raw = Path(dbf_path).read_bytes()
    except OSError:
        return None
    if len(raw) >= 30:
        declared = DBF_LANGUAGE_DRIVER_ENCODINGS.get(raw[29])
        if declared:
            return declared

    sample = raw[:max(32, int(sample_size))]
    try:
        utf8 = sample.decode("utf-8", errors="replace")
        cp949 = sample.decode("cp949", errors="replace")
    except LookupError:
        return None
    utf8_replacements = utf8.count("\ufffd")
    cp949_replacements = cp949.count("\ufffd")
    cp949_hangul = sum("가" <= char <= "힣" for char in cp949)
    if utf8_replacements and not cp949_replacements and cp949_hangul:
        return "CP949"
    return None
