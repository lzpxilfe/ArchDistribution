"""Stable source identities and reusable review decisions.

This module deliberately has no QGIS imports.  Callers should pass geometry as
WKB bytes (preferred), WKT text, or a JSON-compatible GeoJSON-like value.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from typing import Any, Dict, Mapping, Optional, Tuple, Union


STORE_SCHEMA_VERSION = 1
VALID_DECISIONS = frozenset({"keep", "link", "merge"})
_EMPTY_TEXT = frozenset({"", "-", "n/a", "na", "none", "null", "<null>"})


def normalize_identity_text(value: Any) -> str:
    """Return a deterministic key form for identity-bearing text."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    if text.casefold() in _EMPTY_TEXT:
        return ""
    return text.casefold()


def _canonical_value(value: Any) -> Any:
    """Convert JSON-compatible content to a normalized, deterministic value."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFKC", value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"bytes_sha256": hashlib.sha256(bytes(value)).hexdigest()}
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise TypeError(
        "Fingerprint content must be JSON-compatible or bytes; "
        f"got {type(value).__name__}"
    )


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def geometry_signature(geometry: Any) -> str:
    """Return a SHA-256 signature for WKB, WKT, or JSON-like geometry."""
    if geometry is None:
        return _stable_hash({"geometry": None})
    if isinstance(geometry, (bytes, bytearray, memoryview)):
        return hashlib.sha256(bytes(geometry)).hexdigest()
    if isinstance(geometry, str):
        normalized_wkt = re.sub(
            r"\s+",
            " ",
            unicodedata.normalize("NFKC", geometry),
        ).strip()
        return _stable_hash({"wkt": normalized_wkt})
    if isinstance(geometry, (Mapping, list, tuple)):
        return _stable_hash({"geometry": geometry})
    raise TypeError(
        "Geometry must be WKB bytes, WKT text, or a JSON-compatible value; "
        f"got {type(geometry).__name__}"
    )


@dataclass(frozen=True)
class SourceIdentity:
    """A stable source UID plus the fingerprint used to validate reuse."""

    uid: str
    content_fingerprint: str
    geometry_signature: str
    role: str
    native_code: str


def build_source_identity(
    role: Any,
    *,
    native_code: Any = None,
    name: Any = None,
    project_name: Any = None,
    address: Any = None,
    geometry: Any = None,
    extra_content: Any = None,
) -> SourceIdentity:
    """Build an identity from source role, native identifiers, and geometry.

    A source-native code is the preferred identity base.  A part signature is
    still appended so multiple polygons sharing one native code remain distinct.
    Without a native code, normalized name/project/address and geometry form the
    fallback identity.
    """
    normalized_role = normalize_identity_text(role) or "other"
    normalized_code = normalize_identity_text(native_code)
    normalized_name = normalize_identity_text(name)
    normalized_project = normalize_identity_text(project_name)
    normalized_address = normalize_identity_text(address)
    geom_signature = geometry_signature(geometry)

    identity_content = {
        "name": normalized_name,
        "project_name": normalized_project,
        "address": normalized_address,
        "geometry_signature": geom_signature,
    }
    part_signature = _stable_hash(identity_content)[:20]

    if normalized_code:
        uid = (
            f"{normalized_role}:code:{normalized_code}"
            f":part:{part_signature}"
        )
    else:
        fallback_signature = _stable_hash(identity_content)[:32]
        uid = f"{normalized_role}:fallback:{fallback_signature}"

    content_fingerprint = _stable_hash(
        {
            "role": normalized_role,
            "native_code": normalized_code,
            "identity_content": identity_content,
            "extra_content": extra_content,
        }
    )
    return SourceIdentity(
        uid=uid,
        content_fingerprint=content_fingerprint,
        geometry_signature=geom_signature,
        role=normalized_role,
        native_code=normalized_code,
    )


def canonical_uid_pair(uid_a: str, uid_b: str) -> Tuple[str, str]:
    """Return two non-empty UIDs in deterministic lexical order."""
    first = str(uid_a).strip()
    second = str(uid_b).strip()
    if not first or not second:
        raise ValueError("Both source UIDs are required")
    if first == second:
        raise ValueError("A review decision requires two distinct source UIDs")
    return tuple(sorted((first, second)))


def decision_pair_key(uid_a: str, uid_b: str) -> str:
    """Return the stable key for an unordered pair of source UIDs."""
    pair = canonical_uid_pair(uid_a, uid_b)
    return _stable_hash({"uids": pair})


@dataclass(frozen=True)
class DecisionRecord:
    pair_key: str
    left_uid: str
    right_uid: str
    left_fingerprint: str
    right_fingerprint: str
    policy_version: str
    decision: str
    decided_at: str


@dataclass(frozen=True)
class DecisionLookup:
    """Result of consulting saved review decisions."""

    status: str
    decision: Optional[str] = None
    record: Optional[DecisionRecord] = None

    @property
    def reusable(self) -> bool:
        return self.status == "reusable"


class DecisionStore:
    """In-memory review decisions with safe JSON persistence."""

    def __init__(
        self,
        records: Optional[Mapping[str, DecisionRecord]] = None,
        *,
        load_status: str = "new",
    ):
        self._records: Dict[str, DecisionRecord] = dict(records or {})
        self.load_status = load_status

    def __len__(self) -> int:
        return len(self._records)

    @classmethod
    def load(
        cls,
        path: Union[os.PathLike, str],
    ) -> "DecisionStore":
        """Load current-schema decisions; malformed or old files become empty."""
        source_path = Path(path)
        if not source_path.exists():
            return cls(load_status="missing")
        try:
            with source_path.open("r", encoding="utf-8") as stream:
                document = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return cls(load_status="malformed")

        if (
            not isinstance(document, dict)
            or document.get("schema_version") != STORE_SCHEMA_VERSION
            or not isinstance(document.get("decisions"), dict)
        ):
            return cls(load_status="unsupported_schema")

        records: Dict[str, DecisionRecord] = {}
        for stored_key, raw_record in document["decisions"].items():
            record = cls._parse_record(raw_record)
            if record is None:
                continue
            if stored_key != record.pair_key:
                continue
            records[record.pair_key] = record
        return cls(records, load_status="loaded")

    @staticmethod
    def _parse_record(raw_record: Any) -> Optional[DecisionRecord]:
        if not isinstance(raw_record, dict):
            return None
        required = {
            "pair_key",
            "left_uid",
            "right_uid",
            "left_fingerprint",
            "right_fingerprint",
            "policy_version",
            "decision",
            "decided_at",
        }
        if not required.issubset(raw_record):
            return None
        if raw_record["decision"] not in VALID_DECISIONS:
            return None
        try:
            left_uid, right_uid = canonical_uid_pair(
                raw_record["left_uid"],
                raw_record["right_uid"],
            )
        except (TypeError, ValueError):
            return None
        expected_key = decision_pair_key(left_uid, right_uid)
        if raw_record["pair_key"] != expected_key:
            return None
        if left_uid != raw_record["left_uid"] or right_uid != raw_record["right_uid"]:
            return None
        return DecisionRecord(
            pair_key=expected_key,
            left_uid=left_uid,
            right_uid=right_uid,
            left_fingerprint=str(raw_record["left_fingerprint"]),
            right_fingerprint=str(raw_record["right_fingerprint"]),
            policy_version=str(raw_record["policy_version"]),
            decision=raw_record["decision"],
            decided_at=str(raw_record["decided_at"]),
        )

    def record(
        self,
        uid_a: str,
        fingerprint_a: str,
        uid_b: str,
        fingerprint_b: str,
        *,
        decision: str,
        policy_version: str,
        decided_at: Optional[str] = None,
    ) -> DecisionRecord:
        """Save a decision, ordering fingerprints with their sorted UIDs."""
        if decision not in VALID_DECISIONS:
            raise ValueError(f"Unsupported decision: {decision}")
        if not str(policy_version).strip():
            raise ValueError("policy_version is required")
        if not str(fingerprint_a).strip() or not str(fingerprint_b).strip():
            raise ValueError("Both content fingerprints are required")

        left_uid, right_uid = canonical_uid_pair(uid_a, uid_b)
        fingerprints = {
            str(uid_a).strip(): str(fingerprint_a),
            str(uid_b).strip(): str(fingerprint_b),
        }
        record = DecisionRecord(
            pair_key=decision_pair_key(left_uid, right_uid),
            left_uid=left_uid,
            right_uid=right_uid,
            left_fingerprint=fingerprints[left_uid],
            right_fingerprint=fingerprints[right_uid],
            policy_version=str(policy_version),
            decision=decision,
            decided_at=decided_at or datetime.now(timezone.utc).isoformat(),
        )
        self._records[record.pair_key] = record
        return record

    def lookup(
        self,
        uid_a: str,
        fingerprint_a: str,
        uid_b: str,
        fingerprint_b: str,
        *,
        policy_version: str,
    ) -> DecisionLookup:
        """Return reusable only when policy and both fingerprints still match."""
        left_uid, right_uid = canonical_uid_pair(uid_a, uid_b)
        record = self._records.get(decision_pair_key(left_uid, right_uid))
        if record is None:
            return DecisionLookup(status="missing")

        fingerprints = {
            str(uid_a).strip(): str(fingerprint_a),
            str(uid_b).strip(): str(fingerprint_b),
        }
        is_current = (
            record.policy_version == str(policy_version)
            and record.left_fingerprint == fingerprints[left_uid]
            and record.right_fingerprint == fingerprints[right_uid]
        )
        if not is_current:
            return DecisionLookup(status="stale", record=record)
        return DecisionLookup(
            status="reusable",
            decision=record.decision,
            record=record,
        )

    def to_document(self) -> Dict[str, Any]:
        return {
            "schema_version": STORE_SCHEMA_VERSION,
            "decisions": {
                key: asdict(record)
                for key, record in sorted(self._records.items())
            },
        }

    def save(self, path: Union[os.PathLike, str]) -> None:
        """Atomically replace a JSON store, leaving the prior file on failure."""
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=str(target_path.parent),
                prefix=f".{target_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                json.dump(
                    self.to_document(),
                    stream,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, target_path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass
