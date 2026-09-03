"""Conservative encoding detection for legacy DBF attribute tables."""

from pathlib import Path


# dBASE language-driver IDs relevant to Korean public GIS data.  A .cpg file
# remains authoritative; this is used only when that declaration is absent.
DBF_LANGUAGE_DRIVER_ENCODINGS = {
    0x79: "CP949",  # Korean (ANSI/OEM Korean in common shapefile writers)
}


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
