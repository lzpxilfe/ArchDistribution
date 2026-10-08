"""Report-style nearby-site tables (CSV and HWPX) for distribution maps.

Korean excavation and survey reports place a numbered table next to the
nearby-site map.  Its common columns are number, site name (with the legal
designation in brackets), period, character, location, distance and
direction from the survey area, source and remarks.  This module turns the
plugin's numbered groups into that table without any QGIS dependency.

HWPX is the open, XML-based Hangul word-processor format (OWPML).  The
writer below produces a minimal package with one titled table that Hangul
can open and edit; reviewers are still expected to check every row.
"""

import csv
from datetime import datetime
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import unicodedata
from xml.sax.saxutils import escape
import zipfile

try:
    from .attribute_classification import (
        ERA_FIELD_KEYWORDS,
        TYPE_FIELD_KEYWORDS,
        category_values,
        find_semantic_field,
    )
except ImportError:
    from attribute_classification import (
        ERA_FIELD_KEYWORDS,
        TYPE_FIELD_KEYWORDS,
        category_values,
        find_semantic_field,
    )


DEFAULT_TABLE_LEXICON_PATH = Path(__file__).with_name("table_lexicon.json")


@lru_cache(maxsize=4)
def _load_lexicon_cached(path_text):
    payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported table-lexicon schema_version")
    return json.dumps(payload, ensure_ascii=False)


def load_table_lexicon(path=None):
    """Load the replaceable period/address vocabulary as a fresh copy."""
    resolved = Path(path or DEFAULT_TABLE_LEXICON_PATH).resolve()
    return json.loads(_load_lexicon_cached(str(resolved)))


TABLE_COLUMNS = (
    ("번호", "No."),
    ("유적명", "Site"),
    ("시대", "Period"),
    ("성격", "Character"),
    ("소재지", "Location"),
    ("이격거리", "Distance"),
    ("출전", "Source"),
    ("비고", "Remarks"),
)
# Relative column widths for the printed table (sum is normalised).
COLUMN_WEIGHTS = (5, 21, 11, 11, 18, 10, 16, 8)

DESIGNATION_FIELD_KEYWORDS = ("지정종목", "종목", "designation")
AGENCY_FIELD_KEYWORDS = ("조사기관", "기관", "institution", "agency")
OUTCOME_FIELD_KEYWORDS = ("유적유무", "조사결과", "outcome", "result")
NEGATIVE_OUTCOME_MARKERS = ("유적없음", "noremains", "none", "absent")
_PLACEHOLDERS = {"", "n/a", "na", "none", "null", "미상", "-"}

_DIRECTIONS_KO = ("북", "북동", "동", "남동", "남", "남서", "서", "북서")
_DIRECTIONS_EN = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def compass_direction(dx, dy, language="ko"):
    """Return an eight-point bearing for a planar offset (north is +y)."""
    if not dx and not dy:
        return ""
    angle = math.degrees(math.atan2(dx, dy)) % 360.0
    labels = _DIRECTIONS_EN if language == "en" else _DIRECTIONS_KO
    return labels[int((angle + 22.5) // 45) % 8]


def format_distance(distance_m, direction="", language="ko"):
    """Format a study-area distance the way report tables print it."""
    try:
        distance = float(distance_m)
    except (TypeError, ValueError):
        return ""
    if distance < 0.5:
        return "Within/adjacent" if language == "en" else "조사지역 내·접함"
    if distance >= 1000:
        text = f"{distance / 1000:.1f}km"
    else:
        text = f"{int(round(distance / 10.0) * 10)}m"
    return f"{direction} {text}".strip()


def _fold(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", text)


# --- period cell -----------------------------------------------------------

def _period_index(lexicon):
    config = lexicon.get("period") or {}
    by_alias = {}
    periods = {}
    for item in config.get("periods") or []:
        periods[item["id"]] = item
        for alias in [item.get("label", "")] + list(item.get("aliases") or []):
            key = _fold(alias)
            if key:
                by_alias[key] = item["id"]
    suffixes = sorted(
        (_fold(item) for item in config.get("strip_suffixes") or []),
        key=len,
        reverse=True,
    )
    unknown = {_fold(item) for item in config.get("unknown") or []}
    return config, periods, by_alias, suffixes, unknown


def _period_id(label, by_alias, suffixes):
    key = _fold(label)
    if key in by_alias:
        return by_alias[key]
    for suffix in suffixes:
        if suffix and key.endswith(suffix) and key[:-len(suffix)] in by_alias:
            return by_alias[key[:-len(suffix)]]
    return None


def _period_slots(periods):
    """Map each period to its position in the chronological sequence."""
    sequence = sorted(
        (
            item for item in periods.values()
            if not item.get("umbrella") and not item.get("contemporaneous")
        ),
        key=lambda item: item.get("order", 0),
    )
    sequence = [item for item in sequence if not item.get("slot_of")]
    position = {item["id"]: index for index, item in enumerate(sequence)}
    for item in periods.values():
        anchor = item.get("slot_of") or (
            item.get("parent") if item.get("contemporaneous") else None
        )
        if anchor in position:
            position[item["id"]] = position[anchor]
    return position


def _compress_period_runs(known, periods, config, labelled=None):
    """Join periods, turning unbroken runs into "first-last" ranges."""
    separator = config.get("list_separator", "·")
    range_separator = config.get("range_separator", "-")
    minimum = int(config.get("range_min_count", 3))
    slots = _period_slots(periods)
    runs = []
    for period in known:
        slot = slots.get(period)
        if (
            runs
            and slot is not None
            and runs[-1][-1][1] is not None
            and slot - runs[-1][-1][1] in (0, 1)
        ):
            runs[-1].append((period, slot))
        else:
            runs.append([(period, slot)])
    parts = []
    for run in runs:
        labels = [
            (labelled or {}).get(period) or periods[period]["label"]
            for period, _slot in run
        ]
        distinct_slots = {slot for _period, slot in run}
        if len(distinct_slots) >= minimum:
            parts.append(f"{labels[0]}{range_separator}{labels[-1]}")
        else:
            parts.extend(labels)
    return separator.join(parts)


def summarize_periods(values, lexicon=None):
    """Combine period labels from several records into one table cell.

    Labels are mapped to a chronology (aliases such as "조선시대"/"조선"),
    a parent ("삼국") is dropped when a child ("백제") is present, unknown
    markers are dropped when anything is known, and four or more periods are
    shown as a range ("삼국-조선").  Labels outside the chronology are kept
    after the known ones in their original order.
    """
    lexicon = lexicon or load_table_lexicon()
    config, periods, by_alias, suffixes, unknown = _period_index(lexicon)
    qualifiers = [
        item for item in config.get("sub_period_qualifiers") or [] if item
    ]
    known = []
    others = []
    saw_unknown = False
    period_qualifiers = {}
    for value in values:
        label = " ".join(str(value or "").split())
        if not label or is_corrupted_text(label):
            continue
        if _fold(label) in unknown:
            saw_unknown = True
            continue
        qualifier = ""
        for word in qualifiers:
            stripped = label[:-len(word)].strip() if label.endswith(word) else ""
            if stripped and _period_id(stripped, by_alias, suffixes):
                label, qualifier = stripped, word
                break
        period = _period_id(label, by_alias, suffixes)
        if period:
            if period not in known:
                known.append(period)
            period_qualifiers.setdefault(period, set()).add(qualifier)
        elif label not in others:
            others.append(label)
    parents = {
        periods[period].get("parent")
        for period in known
        if periods[period].get("parent")
    }
    known = sorted(
        (period for period in known if period not in parents),
        key=lambda period: periods[period].get("order", 0),
    )
    # "조선 후기" survives only when it is the sole description of that
    # period; mixed or unqualified mentions fall back to the period itself.
    labelled = {}
    for period in known:
        marks = period_qualifiers.get(period, set())
        if len(marks) == 1 and "" not in marks:
            labelled[period] = f"{periods[period]['label']} {next(iter(marks))}"
    joined = _compress_period_runs(known, periods, config, labelled)
    cells = ([joined] if joined else []) + others
    if not cells and saw_unknown:
        return str(config.get("unknown_label") or "")
    return config.get("list_separator", "·").join(cells)


# --- address cell ----------------------------------------------------------

_BRACKETS_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_QUOTES_RE = re.compile("[\"'`‘’“”]")
_ENUMERATED_START_RE = re.compile(r"^\s*\d+\)")
_ENUMERATOR_RE = re.compile(r"(?:^|,)\s*\d+\)\s*")
# CJK ideographs and stand-alone Hangul jamo are what CP949-decoded UTF-8
# bytes turn into; ordinary Korean text has neither next to a "?".
_SUSPICIOUS_RE = re.compile("[\u4e00-\u9fff\u3131-\u318e]")


def is_corrupted_text(text):
    """Return whether a cell looks like irreversibly mis-decoded text.

    Supplier tables occasionally store a few UTF-8 strings inside a CP949
    file.  Once read they show runs of "?" mixed with unrelated ideographs;
    the original cannot be recovered, so such cells are reported instead of
    printed.
    """
    value = str(text or "")
    unknown = value.count("?") + value.count("\ufffd")
    suspicious = len(_SUSPICIOUS_RE.findall(value))
    return unknown >= 1 and suspicious >= 1 and unknown + suspicious >= 3


def _address_rules(lexicon):
    config = lexicon.get("address") or {}
    levels = []
    for level, suffixes in (config.get("level_suffixes") or {}).items():
        for suffix in suffixes:
            levels.append((suffix, int(level)))
    levels.sort(key=lambda item: len(item[0]), reverse=True)
    separators = [item for item in config.get("segment_separators") or [] if item]
    word_separators = [item for item in separators if item.isalpha()]
    symbol_separators = [item for item in separators if not item.isalpha()]
    pattern = "|".join(
        [re.escape(item) for item in symbol_separators]
        + [rf"\s{re.escape(item)}\s" for item in word_separators]
    )
    land = "".join(config.get("land_category_suffixes") or [])
    land_class = rf"[{re.escape(land)}]?" if land else ""
    # Optional land-category prefix or suffix ("답529-4", "445-21대"), and
    # trailing particles after 번지 ("1294번지의").
    parcel_re = re.compile(
        rf"^{land_class}(산)?(\d+)(?:-(\d+))?(?:번지\S*)?{land_class}$"
    )
    counts = "|".join(
        re.escape(item) for item in config.get("count_suffixes") or [] if item
    )
    return {
        "config": config,
        "levels": levels,
        "split_re": re.compile(pattern) if pattern else None,
        "parcel_re": parcel_re,
        "aliases": config.get("province_aliases") or {},
        "placeholders": set(config.get("placeholder_tokens") or []),
        "noise": set(config.get("noise_tokens") or []),
        "count_re": re.compile(rf"^\d+(?:{counts})$") if counts else None,
        "land": set(land),
    }


def place_level(token, rules):
    """Return the administrative depth suggested by a place-name suffix."""
    if token in rules["aliases"]:
        return 1
    for suffix, level in rules["levels"]:
        if len(token) > len(suffix) and token.endswith(suffix):
            return level
    return None


def _parse_address_item(text, rules):
    config = rules["config"]
    raw = _BRACKETS_RE.sub(" ", text)
    raw = _QUOTES_RE.sub("", raw)
    extra = 0
    suffix = re.escape(config.get("parcel_suffix", "필지"))
    for match in re.finditer(r"외\s*(\d+)\s*" + suffix, raw):
        extra += int(match.group(1))
    raw = re.sub(r"외\s*\d*\s*" + suffix, " ", raw)
    raw = re.sub(r"(?<=\d)\s*외(?=\s|$)", " ", raw)
    qualified = False
    for word in config.get("qualifiers") or []:
        if word and word in raw:
            qualified = True
            raw = raw.replace(word, " ")
    raw = re.sub(r"(\d+)\s*번지\s*(\d+)\s*호", r"\1-\2", raw)
    raw = re.sub(r"산\s+(?=\d)", "산", raw)
    segments = (
        rules["split_re"].split(raw) if rules["split_re"] else [raw]
    )

    results = []
    context = []

    def flush(places, parcels):
        nonlocal context
        if places:
            first = place_level(places[0], rules)
            if first is None:
                context = context + places
            else:
                context = [
                    token for token in context
                    if (place_level(token, rules) or 99) < first
                ] + places
        if context or parcels:
            results.append((tuple(context), tuple(parcels)))

    for segment in segments:
        places, parcels = [], []
        for token in segment.split():
            token = token.strip(",.")
            if (
                not token
                or token in rules["placeholders"]
                or token in rules["noise"]
                or token in rules["land"]
                or (rules["count_re"] and rules["count_re"].match(token))
            ):
                continue
            match = rules["parcel_re"].match(token)
            if match:
                san, main, sub = match.groups()
                parcels.append(
                    f"{san or ''}{main}" + (f"-{sub}" if sub else "")
                )
                continue
            if parcels:
                flush(places, parcels)
                places, parcels = [], []
            if not places and not context and token in rules["aliases"]:
                token = rules["aliases"][token]
            places.append(token)
        if places or parcels:
            flush(places, parcels)

    merged = {}
    for places, parcels in results:
        merged.setdefault(places, []).extend(parcels)
    return [
        {
            "places": places,
            "parcels": tuple(dict.fromkeys(parcels)),
            "qualified": qualified,
            "extra_parcels": extra if index == 0 else 0,
        }
        for index, (places, parcels) in enumerate(merged.items())
    ]


def parse_address_cell(text, lexicon=None):
    """Split one address cell into ``{places, parcels, ...}`` entries.

    Handles enumerated cells ("0)A,1)B"), several lots or places joined by
    separators (later segments inherit the leading regions), lot numbers
    with a land-category suffix ("445-21대"), "외 N필지" and "일원"
    qualifiers.  Cleaning rules follow ``addressmatcher`` (same author and
    licence).  Region levels come from name suffixes in the lexicon, so new
    administrative units need no code change.
    """
    lexicon = lexicon or load_table_lexicon()
    rules = _address_rules(lexicon)
    text = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not text or is_corrupted_text(text):
        return []
    items = (
        [item for item in _ENUMERATOR_RE.split(text) if item.strip()]
        if _ENUMERATED_START_RE.match(text) else [text]
    )
    parsed = []
    for item in items:
        parsed.extend(_parse_address_item(item, rules))
    return parsed


def parse_address(text, lexicon=None):
    """Return the first parsed entry of an address cell (or an empty one)."""
    entries = parse_address_cell(text, lexicon)
    if entries:
        return entries[0]
    return {"places": (), "parcels": (), "qualified": False,
            "extra_parcels": 0}


def _offset_in(base, places):
    """Return ``(offset, places)`` with ``places`` aligned to ``base``.

    An address may omit leading regions ("경주시 구황동" under "경상북도
    경주시 구황동") or carry ones the base omitted.  ``offset`` is the base
    index of the first aligned token, or ``None`` when no token is shared.
    """
    if not places or not base:
        return None, places
    if places[0] in base:
        return base.index(places[0]), places
    if base[0] in places:
        return 0, places[places.index(base[0]):]
    return None, places


def summarize_address(addresses, lexicon=None, preferred=None):
    """Return one lot-number address that describes every record.

    The representative's address is the base.  Regions shared by every
    record are kept; at the first level where records differ their names are
    listed ("구황동·인왕동") and the cell ends with "일원".  Several lots of
    one place become "<first lot> 외 N필지".  A qualifier such as "일원" is
    kept when any source used it.
    """
    lexicon = lexicon or load_table_lexicon()
    config = lexicon.get("address") or {}
    preferred_entries = parse_address_cell(preferred, lexicon) if preferred else []
    parsed = list(preferred_entries)
    for item in addresses:
        parsed.extend(parse_address_cell(item, lexicon))
    placed = [item for item in parsed if item["places"]]
    if not placed:
        return ""
    parsed = placed
    if preferred_entries and preferred_entries[0]["places"]:
        base = list(preferred_entries[0]["places"])
    else:
        base = list(max(parsed, key=lambda item: len(item["places"]))[
            "places"
        ])

    common_length = len(base)
    divergent = []
    full_matches = []
    for item in parsed:
        offset, places = _offset_in(base, list(item["places"]))
        if offset is None:
            if places:
                divergent.append((0, places[0]))
                common_length = 0
            continue
        shared = offset
        for index, token in enumerate(places):
            if offset + index < len(base) and base[offset + index] == token:
                shared = offset + index + 1
            else:
                break
        if shared == offset + len(places) and shared < len(base):
            # A coarser address ("경주시") of the same place adds nothing
            # and does not contradict the detailed one.
            continue
        if shared < len(base) or len(places) + offset > len(base):
            position = shared
            mismatch = places[shared - offset] if shared - offset < len(
                places
            ) else None
            divergent.append((position, mismatch))
        if shared == len(base) and len(places) + offset == len(base):
            full_matches.append(item)
        common_length = min(common_length, shared)

    place_text = " ".join(base[:common_length])
    listed = []
    if common_length < len(base):
        names = [base[common_length]] + [
            token for position, token in divergent
            if position == common_length and token
        ]
        listed = list(dict.fromkeys(names))
        limit = int(config.get("max_listed_places", 3))
        text = "·".join(listed[:limit]) + (" 등" if len(listed) > limit else "")
        place_text = f"{place_text} {text}".strip()

    qualified = any(item["qualified"] for item in parsed)
    parcel_text = ""
    if not listed:
        parcels = list(dict.fromkeys(
            parcel for item in full_matches for parcel in item["parcels"]
        ))
        extra = sum(item["extra_parcels"] for item in full_matches)
        if parcels:
            others = len(parcels) - 1 + extra
            suffix = config.get("parcel_suffix", "필지")
            first = re.sub(r"^산(?=\d)", "산 ", parcels[0])
            parcel_text = first + (
                f" 외 {others}{suffix}" if others else ""
            )
    else:
        qualified = True
    qualifier = (config.get("qualifiers") or ["일원"])[0] if qualified else ""
    return " ".join(
        part for part in (place_text, parcel_text, qualifier) if part
    )


def drop_shared_province(addresses, lexicon=None):
    """Remove a first-level region shared by every non-empty address."""
    lexicon = lexicon or load_table_lexicon()
    rules = _address_rules(lexicon)
    firsts = {
        address.split()[0] for address in addresses if address.split()
    }
    if (
        len(firsts) != 1
        or place_level(next(iter(firsts)), rules) != 1
    ):
        return list(addresses)
    province = next(iter(firsts))
    return [
        address[len(province):].strip() if address.startswith(province)
        else address
        for address in addresses
    ]


def _clean(value):
    text = " ".join(str(value or "").split())
    return "" if text.casefold() in _PLACEHOLDERS else text


def _field(record, keywords):
    return find_semantic_field(list(record.keys()), keywords)


def _ordered_unique(values):
    seen = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def _record_categories(records, keywords, ignored):
    values = []
    for record in records:
        name = _field(record, keywords)
        if not name:
            continue
        cell = record.get(name)
        if cell is None:
            continue
        text = str(cell)
        # Preserve the supplier's order for enumerated cells.
        parts = sorted(
            category_values(text, ignored=ignored),
            key=lambda part: text.find(part),
        )
        values.extend(parts)
    return _ordered_unique(values)


def _record_addresses(records, lexicon):
    """Return each record's best address text, composing region fields.

    Address fields are tried in lexicon order.  A site-location cell that
    gives only lot numbers ("산 106") borrows the regions of the record's
    next address field (usually the project location).
    """
    config = lexicon.get("address") or {}
    keywords = list(config.get("field_keywords") or ())
    addresses = []
    for record in records:
        fields = []
        for keyword in keywords:
            field = _field(record, (keyword,))
            if field and field not in fields:
                fields.append(field)
        cells = [
            _clean(record.get(field)) for field in fields
            if _clean(record.get(field))
            and not is_corrupted_text(record.get(field))
        ]
        text = cells[0] if cells else ""
        if text and len(cells) > 1:
            entries = parse_address_cell(text, lexicon)
            if entries and not any(entry["places"] for entry in entries):
                regions = next((
                    entry["places"]
                    for cell in cells[1:]
                    for entry in parse_address_cell(cell, lexicon)
                    if entry["places"]
                ), ())
                if regions:
                    lots = _ENUMERATOR_RE.sub(" ", text).strip()
                    text = " ".join(regions) + " " + lots
        if not text:
            # Registers such as designated-heritage layers only carry
            # region names; compose them rather than leave the cell empty.
            parts = []
            for keyword in config.get("region_field_keywords") or ():
                field = _field(record, (keyword,))
                value = _clean(record.get(field)) if field else ""
                if value and value not in parts:
                    parts.append(value)
            text = " ".join(parts)
        if text:
            addresses.append(text)
    return addresses


def summarize_group(group, language="ko", lexicon=None):
    """Return one table row for a numbered site group.

    ``group`` keys: ``number``, ``name``, ``address`` (representative),
    ``distance_m``, ``direction``, ``roles`` (display labels),
    ``designated`` (bool) and ``records`` (the source attribute
    dictionaries from ``SRC_JSON``).
    """
    lexicon = lexicon or load_table_lexicon()
    records = [
        item for item in group.get("records") or [] if isinstance(item, dict)
    ]
    name = _clean(group.get("name"))
    designation = ""
    if group.get("designated"):
        designation = "·".join(_ordered_unique(
            _clean(record.get(_field(record, DESIGNATION_FIELD_KEYWORDS)))
            for record in records
            if _field(record, DESIGNATION_FIELD_KEYWORDS)
        ))
    if designation and designation not in name:
        name = f"{name}({designation})"

    eras = summarize_periods(
        _record_categories(records, ERA_FIELD_KEYWORDS, ()),
        lexicon,
    )
    designations = set(designation.split("·")) if designation else set()
    types = "·".join(
        value for value in _record_categories(
            records, TYPE_FIELD_KEYWORDS, ("기타", "미분류")
        )
        if value not in designations
    )
    address = summarize_address(
        _record_addresses(records, lexicon),
        lexicon,
        preferred=_clean(group.get("address")),
    )

    agencies = _ordered_unique(
        _clean(record.get(_field(record, AGENCY_FIELD_KEYWORDS)))
        for record in records
        if _field(record, AGENCY_FIELD_KEYWORDS)
    )
    roles = _ordered_unique(_clean(role) for role in group.get("roles") or [])
    source = "·".join(roles)
    if agencies:
        source = (
            f"{source}({', '.join(agencies[:2])})" if source
            else ", ".join(agencies[:2])
        )

    remarks = []
    if is_corrupted_text(group.get("name")):
        remarks.append(
            "Source text damaged" if language == "en"
            else "원자료 문자 손상"
        )
    if len(records) > 1:
        remarks.append(
            f"{len(records)} records" if language == "en"
            else f"{len(records)}건 통합"
        )
    for record in records:
        outcome = _field(record, OUTCOME_FIELD_KEYWORDS)
        value = "".join(str(record.get(outcome) or "").split()).casefold()
        if outcome and any(
            marker in value for marker in NEGATIVE_OUTCOME_MARKERS
        ):
            remarks.append(
                "No features found" if language == "en" else "유구 미확인"
            )
            break

    return [
        str(group.get("number") or ""),
        name,
        eras,
        types,
        address,
        format_distance(
            group.get("distance_m"), group.get("direction", ""), language
        ),
        source,
        ", ".join(remarks),
    ]


def build_site_table(groups, language="ko", lexicon=None):
    """Return ``(header, rows)`` sorted by map number."""
    lexicon = lexicon or load_table_lexicon()

    def number_key(group):
        try:
            return (0, int(group.get("number")))
        except (TypeError, ValueError):
            return (1, str(group.get("number")))

    header = [en if language == "en" else ko for ko, en in TABLE_COLUMNS]
    rows = [
        summarize_group(group, language, lexicon)
        for group in sorted(groups, key=number_key)
    ]
    if (lexicon.get("address") or {}).get("drop_shared_province", True):
        addresses = drop_shared_province([row[4] for row in rows], lexicon)
        for row, address in zip(rows, addresses):
            row[4] = address
    return header, rows


def write_csv(path, header, rows):
    """Write a spreadsheet-friendly UTF-8 (BOM) CSV."""
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


# --- HWPX (OWPML) writer -------------------------------------------------

_HWPUNIT_PER_MM = 7200 / 25.4
_PAGE_WIDTH = 59528   # A4 portrait, HWPUNIT
_PAGE_HEIGHT = 84188
_MARGIN_LR = 4252     # 15 mm
_MARGIN_TB = 4252
_TEXT_WIDTH = _PAGE_WIDTH - 2 * _MARGIN_LR
_CELL_MARGIN = 283    # 1 mm
_ROW_HEIGHT = 1700

_NS = (
    'xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
    'xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" '
    'xmlns:opf="http://www.idpf.org/2007/opf/"'
)
_XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
_LANGS = ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")
_LANG_ATTRS = ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")

# charPr ids
_CHAR_BODY, _CHAR_HEAD, _CHAR_TITLE, _CHAR_NOTE = 0, 1, 2, 3
# paraPr ids
_PARA_LEFT, _PARA_CENTER = 0, 1
# borderFill ids
_FILL_NONE, _FILL_CELL, _FILL_HEAD = 1, 2, 3


def _lang_values(value):
    return " ".join(f'{attr}="{value}"' for attr in _LANG_ATTRS)


def _border_fill(fill_id, border, face_color=None):
    sides = "".join(
        f'<hh:{side}Border type="{border}" width="0.12 mm" color="#000000"/>'
        for side in ("left", "right", "top", "bottom")
    )
    brush = (
        '<hc:fillBrush><hc:winBrush faceColor="{0}" hatchColor="#000000" '
        'alpha="0"/></hc:fillBrush>'.format(face_color)
        if face_color else ""
    )
    return (
        f'<hh:borderFill id="{fill_id}" threeD="0" shadow="0" '
        'centerLine="NONE" breakCellSeparateLine="0">'
        '<hh:slash type="NONE" Crooked="0" isCounter="0"/>'
        '<hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
        f'{sides}<hh:diagonal type="NONE" width="0.1 mm" color="#000000"/>'
        f'{brush}</hh:borderFill>'
    )


def _char_pr(char_id, height, bold=False):
    return (
        f'<hh:charPr id="{char_id}" height="{height}" textColor="#000000" '
        'shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" '
        f'borderFillIDRef="{_FILL_NONE}">'
        f'<hh:fontRef {_lang_values(0)}/>'
        f'<hh:ratio {_lang_values(100)}/>'
        f'<hh:spacing {_lang_values(0)}/>'
        f'<hh:relSz {_lang_values(100)}/>'
        f'<hh:offset {_lang_values(0)}/>'
        + ("<hh:bold/>" if bold else "")
        + '<hh:underline type="NONE" shape="SOLID" color="#000000"/>'
        '<hh:strikeout shape="NONE" color="#000000"/>'
        '<hh:outline type="NONE"/>'
        '<hh:shadow type="NONE" color="#C0C0C0" offsetX="10" offsetY="10"/>'
        '</hh:charPr>'
    )


def _para_pr(para_id, horizontal):
    return (
        f'<hh:paraPr id="{para_id}" tabPrIDRef="0" condense="0" '
        'fontLineHeight="0" snapToGrid="0" suppressLineNumbers="0" '
        f'checked="0"><hh:align horizontal="{horizontal}" '
        'vertical="BASELINE"/>'
        '<hh:heading type="NONE" idRef="0" level="0"/>'
        '<hh:breakSetting breakLatinWord="KEEP_WORD" '
        'breakNonLatinWord="BREAK_WORD" widowOrphan="0" keepWithNext="0" '
        'keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>'
        '<hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
        '<hh:margin><hc:intent value="0" unit="HWPUNIT"/>'
        '<hc:left value="0" unit="HWPUNIT"/>'
        '<hc:right value="0" unit="HWPUNIT"/>'
        '<hc:prev value="0" unit="HWPUNIT"/>'
        '<hc:next value="0" unit="HWPUNIT"/></hh:margin>'
        '<hh:lineSpacing type="PERCENT" value="130" unit="HWPUNIT"/>'
        f'<hh:border borderFillIDRef="{_FILL_NONE}" offsetLeft="0" '
        'offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" '
        'ignoreMargin="0"/></hh:paraPr>'
    )


def _header_xml(font_face):
    face = escape(font_face, {'"': "&quot;"})
    fontfaces = "".join(
        f'<hh:fontface lang="{lang}" fontCnt="1"><hh:font id="0" '
        f'face="{face}" type="TTF" isEmbedded="0"/></hh:fontface>'
        for lang in _LANGS
    )
    return (
        f'{_XML_DECL}<hh:head {_NS} version="1.4" secCnt="1">'
        '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" '
        'equation="1"/><hh:refList>'
        f'<hh:fontfaces itemCnt="{len(_LANGS)}">{fontfaces}</hh:fontfaces>'
        '<hh:borderFills itemCnt="3">'
        + _border_fill(_FILL_NONE, "NONE")
        + _border_fill(_FILL_CELL, "SOLID")
        + _border_fill(_FILL_HEAD, "SOLID", "#E7E6E6")
        + '</hh:borderFills><hh:charProperties itemCnt="4">'
        + _char_pr(_CHAR_BODY, 900)
        + _char_pr(_CHAR_HEAD, 900, bold=True)
        + _char_pr(_CHAR_TITLE, 1400, bold=True)
        + _char_pr(_CHAR_NOTE, 900)
        + '</hh:charProperties><hh:tabProperties itemCnt="1">'
        '<hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/>'
        '</hh:tabProperties><hh:paraProperties itemCnt="2">'
        + _para_pr(_PARA_LEFT, "LEFT")
        + _para_pr(_PARA_CENTER, "CENTER")
        + '</hh:paraProperties><hh:styles itemCnt="1">'
        f'<hh:style id="0" type="PARA" name="바탕글" engName="Normal" '
        f'paraPrIDRef="{_PARA_LEFT}" charPrIDRef="{_CHAR_BODY}" '
        'nextStyleIDRef="0" langID="1042" lockForm="0"/></hh:styles>'
        '</hh:refList><hh:compatibleDocument targetProgram="HWP201X">'
        '<hh:layoutCompatibility/></hh:compatibleDocument>'
        '<hh:docOption><hh:linkinfo path="" pageInherit="0" '
        'footnoteInherit="0"/></hh:docOption></hh:head>'
    )


class _Ids:
    def __init__(self):
        self.value = 0

    def next(self):
        self.value += 1
        return self.value


def _paragraph(ids, text, char_id, para_id, inner=""):
    run_text = f"<hp:t>{escape(text)}</hp:t>" if text else ""
    return (
        f'<hp:p id="{ids.next()}" paraPrIDRef="{para_id}" styleIDRef="0" '
        'pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{char_id}">{inner}{run_text}</hp:run></hp:p>'
    )


def _section_properties():
    return (
        '<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" '
        'tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" '
        'outlineShapeIDRef="0" memoShapeIDRef="0" '
        'textVerticalWidthHead="0" masterPageCnt="0">'
        '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0" '
        'strikeContinue="0"/>'
        '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" '
        'equation="0"/>'
        '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" '
        'hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" '
        'hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>'
        '<hp:lineNumberShape restartType="0" countBy="0" distance="0" '
        'startNumber="0"/>'
        f'<hp:pagePr landscape="WIDELY" width="{_PAGE_WIDTH}" '
        f'height="{_PAGE_HEIGHT}" gutterType="LEFT_ONLY">'
        f'<hp:margin header="2834" footer="2834" gutter="0" '
        f'left="{_MARGIN_LR}" right="{_MARGIN_LR}" top="{_MARGIN_TB}" '
        f'bottom="{_MARGIN_TB}"/></hp:pagePr>'
        '<hp:footNotePr><hp:autoNumFormat type="DIGIT" userChar="" '
        'prefixChar="" suffixChar=")" supscript="0"/>'
        '<hp:noteLine length="-1" type="SOLID" width="0.12 mm" '
        'color="#000000"/><hp:noteSpacing betweenNotes="283" '
        'belowLine="567" aboveLine="850"/><hp:numbering type="CONTINUOUS" '
        'newNum="1"/><hp:placement place="EACH_COLUMN" beneathText="0"/>'
        '</hp:footNotePr>'
        '<hp:endNotePr><hp:autoNumFormat type="DIGIT" userChar="" '
        'prefixChar="" suffixChar=")" supscript="0"/>'
        '<hp:noteLine length="14692" type="SOLID" width="0.12 mm" '
        'color="#000000"/><hp:noteSpacing betweenNotes="0" belowLine="567" '
        'aboveLine="850"/><hp:numbering type="CONTINUOUS" newNum="1"/>'
        '<hp:placement place="END_OF_DOCUMENT" beneathText="0"/>'
        '</hp:endNotePr>'
        f'<hp:pageBorderFill type="BOTH" borderFillIDRef="{_FILL_NONE}" '
        'textBorder="PAPER" headerInside="0" footerInside="0" '
        'fillArea="PAPER"><hp:offset left="1417" right="1417" top="1417" '
        'bottom="1417"/></hp:pageBorderFill></hp:secPr>'
        '<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" '
        'colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>'
    )


def _column_widths(count):
    weights = list(COLUMN_WEIGHTS[:count]) or [1]
    weights += [weights[-1]] * (count - len(weights))
    total = float(sum(weights))
    widths = [int(_TEXT_WIDTH * weight / total) for weight in weights]
    widths[-1] += _TEXT_WIDTH - sum(widths)
    return widths


def _table(ids, header, rows):
    widths = _column_widths(len(header))
    all_rows = [header] + rows
    xml_rows = []
    for row_index, row in enumerate(all_rows):
        is_header = row_index == 0
        cells = []
        for col_index, width in enumerate(widths):
            text = str(row[col_index]) if col_index < len(row) else ""
            centred = is_header or col_index in (0, 5)
            paragraph = _paragraph(
                ids,
                text,
                _CHAR_HEAD if is_header else _CHAR_BODY,
                _PARA_CENTER if centred else _PARA_LEFT,
            )
            fill = _FILL_HEAD if is_header else _FILL_CELL
            cells.append(
                f'<hp:tc name="" header="{1 if is_header else 0}" '
                'hasMargin="0" protect="0" editable="0" dirty="0" '
                f'borderFillIDRef="{fill}">'
                '<hp:subList id="" textDirection="HORIZONTAL" '
                'lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" '
                'linkListNextIDRef="0" textWidth="0" textHeight="0" '
                'hasTextRef="0" hasNumRef="0">'
                f'{paragraph}</hp:subList>'
                f'<hp:cellAddr colAddr="{col_index}" rowAddr="{row_index}"/>'
                '<hp:cellSpan colSpan="1" rowSpan="1"/>'
                f'<hp:cellSz width="{width}" height="{_ROW_HEIGHT}"/>'
                f'<hp:cellMargin left="{_CELL_MARGIN}" '
                f'right="{_CELL_MARGIN}" top="{_CELL_MARGIN // 2}" '
                f'bottom="{_CELL_MARGIN // 2}"/></hp:tc>'
            )
        xml_rows.append("<hp:tr>" + "".join(cells) + "</hp:tr>")
    height = _ROW_HEIGHT * len(all_rows)
    return (
        f'<hp:tbl id="{ids.next()}" zOrder="0" numberingType="TABLE" '
        'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
        'dropcapstyle="None" pageBreak="CELL" repeatHeader="1" '
        f'rowCnt="{len(all_rows)}" colCnt="{len(widths)}" cellSpacing="0" '
        f'borderFillIDRef="{_FILL_CELL}" noAdjust="0">'
        f'<hp:sz width="{_TEXT_WIDTH}" widthRelTo="ABSOLUTE" '
        f'height="{height}" heightRelTo="ABSOLUTE" protect="0"/>'
        # Not "treat as character": only a floating, text-flowing table can
        # break between rows across pages (with the header row repeated).
        '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="1" '
        'allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" '
        'horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" '
        'horzOffset="0"/>'
        '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        f'<hp:inMargin left="{_CELL_MARGIN}" right="{_CELL_MARGIN}" '
        f'top="{_CELL_MARGIN // 2}" bottom="{_CELL_MARGIN // 2}"/>'
        + "".join(xml_rows)
        + "</hp:tbl>"
    )


def _section_xml(title, subtitle, header, rows, footnote):
    ids = _Ids()
    parts = [
        _paragraph(
            ids, title, _CHAR_TITLE, _PARA_CENTER,
            inner=_section_properties(),
        ),
    ]
    if subtitle:
        parts.append(_paragraph(ids, subtitle, _CHAR_NOTE, _PARA_LEFT))
    parts.append(_paragraph(
        ids, "", _CHAR_BODY, _PARA_LEFT, inner=_table(ids, header, rows)
    ))
    if footnote:
        parts.append(_paragraph(ids, footnote, _CHAR_NOTE, _PARA_LEFT))
    return f"{_XML_DECL}<hs:sec {_NS}>" + "".join(parts) + "</hs:sec>"


def write_hwpx(
    path,
    header,
    rows,
    *,
    title="주변유적 현황",
    subtitle="",
    footnote="",
    font_face="함초롬바탕",
):
    """Write an editable Hangul (HWPX/OWPML) document with one table."""
    created = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S")
    title_xml = escape(title)
    content_hpf = (
        f'{_XML_DECL}<opf:package {_NS} version="" unique-identifier="" '
        'id=""><opf:metadata>'
        f'<opf:title>{title_xml}</opf:title>'
        '<opf:language>ko</opf:language>'
        '<opf:meta name="creator" content="text">ArchDistribution</opf:meta>'
        f'<opf:meta name="CreatedDate" content="text">{created}</opf:meta>'
        '</opf:metadata><opf:manifest>'
        '<opf:item id="header" href="Contents/header.xml" '
        'media-type="application/xml"/>'
        '<opf:item id="section0" href="Contents/section0.xml" '
        'media-type="application/xml"/>'
        '<opf:item id="settings" href="settings.xml" '
        'media-type="application/xml"/>'
        '</opf:manifest><opf:spine>'
        '<opf:itemref idref="header" linear="yes"/>'
        '<opf:itemref idref="section0" linear="yes"/>'
        '</opf:spine></opf:package>'
    )
    version = (
        f'{_XML_DECL}<hv:HCFVersion '
        'xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" '
        'tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="0" '
        'buildNumber="1" os="1" xmlVersion="1.4" '
        'application="ArchDistribution" appVersion="1"/>'
    )
    container = (
        f'{_XML_DECL}<ocf:container '
        'xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" '
        'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf">'
        '<ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" '
        'media-type="application/hwpml-package+xml"/></ocf:rootfiles>'
        '</ocf:container>'
    )
    manifest = (
        f'{_XML_DECL}<odf:manifest '
        'xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>'
    )
    settings = (
        f'{_XML_DECL}<ha:HWPApplicationSetting '
        'xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
        'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">'
        '<ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/>'
        '</ha:HWPApplicationSetting>'
    )
    preview = "\r\n".join(
        [title] + ["\t".join(header)] + ["\t".join(map(str, row)) for row in rows]
    )
    with zipfile.ZipFile(path, "w") as archive:
        # The OCF container requires an uncompressed mimetype entry first.
        archive.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/hwp+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        entries = (
            ("version.xml", version),
            ("Contents/header.xml", _header_xml(font_face)),
            ("Contents/section0.xml", _section_xml(
                title, subtitle, header, rows, footnote
            )),
            ("Contents/content.hpf", content_hpf),
            ("settings.xml", settings),
            ("Preview/PrvText.txt", preview[:1024]),
            ("META-INF/container.xml", container),
            ("META-INF/manifest.xml", manifest),
        )
        for name, text in entries:
            archive.writestr(
                name, text.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED
            )
    return path
