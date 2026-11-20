"""Conservative encoding detection for legacy DBF attribute tables."""

from codecs import getincrementaldecoder
from pathlib import Path


# dBASE language-driver IDs relevant to Korean public GIS data.
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


def _sidecar_path(path, suffix):
    """Return a shapefile sidecar, matching the suffix case-insensitively.

    Public downloads often use upper-case names (``SITE.SHP``/``SITE.CPG``).
    Windows resolves either spelling, but case-sensitive file systems need the
    directory entry itself.
    """
    candidate = path.with_suffix(suffix)
    if candidate.exists():
        return candidate
    try:
        for entry in path.parent.iterdir():
            if (
                entry.stem == path.stem
                and entry.suffix.casefold() == suffix.casefold()
            ):
                return entry
    except OSError:
        pass
    return candidate


def declared_shapefile_encoding(shp_path):
    """Return ``(encoding, basis)`` before QGIS reads a shapefile's DBF.

    The point of this helper is timing: QGIS must be told about CP949 before
    callers inspect fields or attributes.  Strong CP949 evidence can correct
    a stale declaration. Otherwise the .cpg or provider default is used.
    """
    path = Path(shp_path)
    if path.suffix.casefold() != ".shp":
        return None, None
    # Some public downloads ship a stale ``UTF-8`` .cpg next to a CP949 DBF.
    # A positive CP949 DBF detection takes precedence over that declaration.
    inferred = infer_dbf_encoding(_sidecar_path(path, ".dbf"))
    if inferred == "CP949":
        return inferred, "DBF automatic detection"

    cpg_path = _sidecar_path(path, ".cpg")
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

    Read at most the DBF header and a bounded sample of complete records.
    Defer to the provider for ambiguous bytes and correct a Korean driver ID
    when the character data is valid UTF-8 but cannot be decoded as CP949.
    """
    limit = max(32, int(sample_size))
    partial = False
    try:
        with Path(dbf_path).open("rb") as stream:
            header = stream.read(32)
            declared = DBF_LANGUAGE_DRIVER_ENCODINGS.get(header[29]) if len(header) >= 30 else None
            sample = _dbf_character_sample(stream, header, limit=limit)
            if sample is None:
                # Retain a conservative raw fallback for unsupported layouts.
                stream.seek(0)
                raw = stream.read(limit + 1)
                partial = len(raw) > limit
                sample = raw[:limit]
    except OSError:
        return None

    try:
        # A cutoff inside a final multibyte sequence is not a decode error.
        utf8 = getincrementaldecoder("utf-8")("replace").decode(sample, final=not partial)
        cp949 = getincrementaldecoder("cp949")("replace").decode(sample, final=not partial)
    except LookupError:
        return declared
    utf8_replacements = utf8.count("\ufffd") - sample.count(b"\xef\xbf\xbd")
    cp949_replacements = cp949.count("\ufffd")
    if not utf8_replacements:
        if declared and not utf8.isascii():
            # Both encodings can occasionally decode the same bytes. Leave
            # such a sample to the declaration or provider rather than force CP949.
            return "UTF-8" if cp949_replacements else None
        return declared

    cp949_hangul = sum("가" <= char <= "힣" for char in cp949)
    # DBF headers contain binary dates, offsets and lengths.  Treating the
    # whole file as text creates a few false CP949 replacement characters and
    # used to suppress otherwise obvious detection.  The structured sampler
    # below normally removes those bytes; the small ratio allowance keeps the
    # fallback path conservative for damaged/truncated DBFs.
    cp949_error_limit = max(1, utf8_replacements // 100)
    if (
        cp949_replacements <= cp949_error_limit
        and cp949_replacements * 8 < utf8_replacements
        and cp949_hangul
    ):
        return "CP949"
    return declared


def _dbf_character_sample(stream, header, *, limit):
    """Extract complete character fields from a bounded batch of DBF records.

    Return None for unsupported layouts, or empty bytes if there is no text.
    """
    if len(header) < 32:
        return None
    record_count = int.from_bytes(header[4:8], "little")
    header_length = int.from_bytes(header[8:10], "little")
    record_length = int.from_bytes(header[10:12], "little")
    if header_length < 33 or record_length < 1:
        return None
    descriptors = stream.read(header_length - len(header))
    if len(descriptors) != header_length - len(header):
        return None

    character_fields = []
    field_offset = 1  # deletion flag is the first byte of every DBF record
    for start in range(0, len(descriptors), 32):
        if descriptors[start] == 0x0D:
            break
        descriptor = descriptors[start:start + 32]
        if len(descriptor) < 32:
            return None
        is_character = descriptor[11] == ord("C")
        # Shapelib reads both length bytes for character fields. The second
        # byte is decimal precision in numeric field descriptors instead.
        field_length = int.from_bytes(descriptor[16:18], "little") if is_character else descriptor[16]
        if not field_length or field_offset + field_length > record_length:
            return None
        if is_character:
            character_fields.append((field_offset, field_length))
        field_offset += field_length
    else:
        return None
    if not character_fields or not record_count:
        return b""

    # A wide record may exceed the requested sample size. Include one whole
    # record, never a partial field. Blank or deleted records use budget too.
    record_limit = min(record_count, max(1, limit // record_length))
    records = stream.read(record_limit * record_length)
    chunks = []
    for start in range(0, len(records) - record_length + 1, record_length):
        if records[start] == 0x2A:
            continue
        for offset, length in character_fields:
            value = records[start + offset:start + offset + length].strip(b" \x00")
            if value:
                chunks.append(value)
    return b"\n".join(chunks)
