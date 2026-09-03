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

    sample = _dbf_character_sample(raw, sample_size=sample_size)
    try:
        utf8 = sample.decode("utf-8", errors="replace")
        cp949 = sample.decode("cp949", errors="replace")
    except LookupError:
        return None
    utf8_replacements = utf8.count("\ufffd")
    cp949_replacements = cp949.count("\ufffd")
    cp949_hangul = sum("가" <= char <= "힣" for char in cp949)
    # DBF headers contain binary dates, offsets and lengths.  Treating the
    # whole file as text creates a few false CP949 replacement characters and
    # used to suppress otherwise obvious detection.  The structured sampler
    # below normally removes those bytes; the small ratio allowance keeps the
    # fallback path conservative for damaged/truncated DBFs.
    cp949_error_limit = max(1, utf8_replacements // 100)
    if (
        utf8_replacements
        and cp949_replacements <= cp949_error_limit
        and cp949_replacements * 8 < utf8_replacements
        and cp949_hangul
    ):
        return "CP949"
    return None


def _dbf_character_sample(raw, *, sample_size=65536):
    """Extract character-field bytes from valid DBF records.

    Numeric/binary fields and the binary header are deliberately excluded.
    If the byte sequence is not a structurally valid DBF, return the old raw
    sample so tiny fixtures and unusual providers retain conservative support.
    """
    limit = max(32, int(sample_size))
    if len(raw) < 33:
        return raw[:limit]

    record_count = int.from_bytes(raw[4:8], "little")
    header_length = int.from_bytes(raw[8:10], "little")
    record_length = int.from_bytes(raw[10:12], "little")
    if (
        record_count <= 0
        or header_length < 33
        or header_length > len(raw)
        or record_length <= 1
        or header_length + record_length > len(raw)
    ):
        return raw[:limit]

    character_fields = []
    field_offset = 1  # deletion flag is the first byte of every DBF record
    descriptor_offset = 32
    while descriptor_offset + 32 <= header_length:
        if raw[descriptor_offset] == 0x0D:
            break
        descriptor = raw[descriptor_offset:descriptor_offset + 32]
        try:
            field_type = chr(descriptor[11])
        except (IndexError, ValueError):
            return raw[:limit]
        field_length = int(descriptor[16])
        if field_length <= 0:
            return raw[:limit]
        if field_type == "C":
            character_fields.append((field_offset, field_length))
        field_offset += field_length
        descriptor_offset += 32

    if not character_fields or field_offset > record_length:
        return raw[:limit]

    chunks = []
    sampled_bytes = 0
    available_records = min(
        record_count,
        max(0, (len(raw) - header_length) // record_length),
    )
    for record_index in range(available_records):
        start = header_length + record_index * record_length
        record = raw[start:start + record_length]
        if not record or record[0] == 0x2A:  # deleted record
            continue
        for offset, length in character_fields:
            value = record[offset:offset + length].strip(b" \x00")
            if not value:
                continue
            remaining = limit - sampled_bytes
            if remaining <= 0:
                break
            value = value[:remaining]
            chunks.append(value)
            sampled_bytes += len(value)
        if sampled_bytes >= limit:
            break

    return b"\n".join(chunks) if chunks else raw[:limit]
