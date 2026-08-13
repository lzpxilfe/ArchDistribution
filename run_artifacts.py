"""Pure-Python helpers for optional run artifacts.

The QGIS-facing workflow should pass plain dictionaries to this module.  It
deliberately has no QGIS imports so manifest construction, path handling, and
atomic persistence can be tested without a QGIS runtime.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime, time, timezone, tzinfo
from enum import Enum
import hashlib
import json
import math
import os
import platform
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Union


MANIFEST_SCHEMA_VERSION = 2
DEFAULT_PLUGIN_NAME = "ArchDistribution"
VALID_RUN_STATUSES = frozenset({
    "running",
    "success",
    "partial_success",
    "failed",
    "cancelled",
    # Accepted as a schema-v1 compatibility alias and serialized as ``failed``.
    "error",
})
REDACTED_VALUE = "[REDACTED]"
LOCAL_PATH_REMOVED = "[LOCAL_PATH_REMOVED]"
UNKNOWN_VALUE = "unknown"

DEFAULT_VOLATILE_HASH_KEYS = frozenset({
    "created_at",
    "duration_seconds",
    "finished_at",
    "finished_local",
    "finished_utc",
    "generated_at",
    "layer_id",
    "path",
    "paths",
    "source",
    "started_at",
    "started_local",
    "started_utc",
    "timestamp",
    "timestamps",
})

_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "private_key",
    "access_key",
    "비밀번호",
    "암호",
    "토큰",
    "인증정보",
    "비밀키",
    "접근키",
)
_FORBIDDEN_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE_RE = re.compile(r"\s+")
_REPEATED_UNDERSCORE_RE = re.compile(r"_{2,}")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {"COM{}".format(index) for index in range(1, 10)}
    | {"LPT{}".format(index) for index in range(1, 10)}
)
_CONNECTION_SECRET_RE = re.compile(
    r"""(?ix)
    \b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|
       client[_-]?secret|authorization)
    (\s*=\s*)
    (?:'[^']*'|"[^"]*"|[^&;\s]+)
    """
)
_URL_PASSWORD_RE = re.compile(
    r"(?i)([a-z][a-z0-9+.-]*://[^/@:\s]+:)([^/@\s]+)(@)"
)
_FILE_URI_PATH_RE = re.compile(r"(?i)file://[^\r\n]*")
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/][^\r\n]*"
)
_UNC_ABSOLUTE_PATH_RE = re.compile(r"(?<![\\])\\\\[^\r\n]*")
_POSIX_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9:/])/(?!/)[^\r\n]*"
)


def _is_sensitive_key(key: Any) -> bool:
    normalized = re.sub(
        r"[\W_]+",
        "_",
        unicodedata.normalize("NFKC", str(key)).casefold(),
        flags=re.UNICODE,
    ).strip("_")
    compact = normalized.replace("_", "")
    return any(
        marker in normalized or marker.replace("_", "") in compact
        for marker in _SENSITIVE_KEY_PARTS
    )


def redact_connection_secrets(value: Any) -> str:
    """Mask common credentials embedded in URLs or provider connection text."""
    text = unicodedata.normalize("NFKC", str(value))
    text = _URL_PASSWORD_RE.sub(
        lambda match: "{}{}{}".format(
            match.group(1),
            REDACTED_VALUE,
            match.group(3),
        ),
        text,
    )
    return _CONNECTION_SECRET_RE.sub(
        lambda match: "{}{}{}".format(
            match.group(1),
            match.group(2),
            REDACTED_VALUE,
        ),
        text,
    )


def sanitize_source_reference(value: Any) -> str:
    """Return a public-safe provider reference without local absolute paths.

    QGIS source strings often append provider options after ``|``.  Those
    options are retained after credential redaction, while a local path is
    reduced to its filename.  Database/HTTP connection strings are never
    parsed for semantics; only known credentials are redacted.
    """
    text = redact_connection_secrets(value)
    base, separator, options = text.partition("|")
    normalized = base.replace("\\", "/")
    is_file_uri = normalized.casefold().startswith("file://")
    local_candidate = normalized[7:] if is_file_uri else normalized
    is_windows_absolute = bool(re.match(r"^[A-Za-z]:/", local_candidate))
    is_posix_absolute = local_candidate.startswith("/")
    if is_file_uri or is_windows_absolute or is_posix_absolute:
        basename = Path(local_candidate).name or "<local-source>"
        base = "file:///{}".format(basename)
    else:
        base = redact_local_paths(base)
    safe_options = redact_local_paths(options) if separator else ""
    return base + (separator + safe_options if separator else "")


def redact_local_paths(value: Any) -> str:
    """Remove absolute filesystem paths embedded in diagnostic text.

    Diagnostic messages are not a stable transport format, so when an
    absolute path is found the remainder of that line is conservatively
    removed.  This favours privacy over retaining incidental error wording in
    manifests intended for publication.
    """
    text = redact_connection_secrets(value)
    for pattern in (
        _FILE_URI_PATH_RE,
        _WINDOWS_ABSOLUTE_PATH_RE,
        _UNC_ABSOLUTE_PATH_RE,
        _POSIX_ABSOLUTE_PATH_RE,
    ):
        text = pattern.sub(LOCAL_PATH_REMOVED, text)
    return text


def sanitize_public_value(value: Any) -> Any:
    """Recursively redact credentials and embedded local paths."""
    safe_value = safe_json_value(value)
    if isinstance(safe_value, Mapping):
        return {
            str(key): (
                REDACTED_VALUE
                if _is_sensitive_key(key)
                else sanitize_public_value(item)
            )
            for key, item in safe_value.items()
        }
    if isinstance(safe_value, list):
        return [sanitize_public_value(item) for item in safe_value]
    if isinstance(safe_value, str):
        return redact_local_paths(safe_value)
    return safe_value


def sanitize_public_settings(value: Any, *, key: str = "") -> Any:
    """Remove local paths from settings stored in a public run manifest."""
    if isinstance(value, Mapping):
        result = {}
        for item_key, item_value in value.items():
            string_key = str(item_key)
            result[string_key] = (
                REDACTED_VALUE
                if _is_sensitive_key(string_key)
                else sanitize_public_settings(
                    item_value,
                    key=string_key,
                )
            )
        return result
    normalized_key = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
    path_key = (
        normalized_key.endswith(("path", "paths", "directory", "folder"))
        or normalized_key in {"output_dir", "input_dir"}
    )
    if path_key and value not in (None, ""):
        return LOCAL_PATH_REMOVED
    if isinstance(value, (list, tuple)):
        return [sanitize_public_settings(item, key=key) for item in value]
    return safe_json_value(value)


def _semantic_settings(value: Any) -> Any:
    """Drop transient QGIS object identifiers from deterministic settings."""
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized.endswith("_id") or normalized.endswith("_ids"):
                continue
            if normalized in {"source_roles", "source_encodings"}:
                # These mappings are keyed by transient QgsMapLayer IDs.
                # Their stable role/encoding values are represented by the
                # normalized input summaries in the semantic payload.
                continue
            if normalized in {"output_directory", "output_folder"}:
                continue
            result[str(key)] = _semantic_settings(item)
        return result
    if isinstance(value, list):
        return [_semantic_settings(item) for item in value]
    return value


def _semantic_processing(value: Any) -> Any:
    """Keep result counts while dropping timing and artifact transport data."""
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in {
                "artifacts",
                "artifact_errors",
                "elapsed_seconds",
                "gpkg_layers",
            }:
                continue
            result[str(key)] = _semantic_processing(item)
        return result
    if isinstance(value, list):
        return [_semantic_processing(item) for item in value]
    return value


def _canonical_sequence(value: Any) -> Any:
    """Sort an order-insensitive sequence by canonical JSON content."""
    safe_value = safe_json_value(value)
    if not isinstance(safe_value, list):
        return safe_value
    return sorted(
        safe_value,
        key=lambda item: json.dumps(
            item,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def _semantic_input_summaries(inputs: Iterable[Mapping[str, Any]]) -> list:
    """Keep stable input meaning while dropping paths and QGIS IDs."""
    stable = []
    for summary in inputs:
        item = {
            str(key): value
            for key, value in summary.items()
            if str(key).casefold() not in {"layer_id", "source"}
        }
        stable.append(item)
    return _canonical_sequence(stable)


def _without_volatile_keys(value: Any, ignored_keys: frozenset) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _without_volatile_keys(item, ignored_keys)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key).casefold() not in ignored_keys
        }
    if isinstance(value, (list, tuple)):
        return [_without_volatile_keys(item, ignored_keys) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_without_volatile_keys(item, ignored_keys) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    return value


def deterministic_content_hash(
    value: Any,
    *,
    ignored_keys: Optional[Iterable[str]] = None,
) -> str:
    """Hash semantic JSON content while excluding volatile run metadata."""
    ignored = frozenset(
        str(key).casefold()
        for key in (
            DEFAULT_VOLATILE_HASH_KEYS
            if ignored_keys is None
            else ignored_keys
        )
    )
    safe_value = safe_json_value(value)
    canonical = _without_volatile_keys(safe_value, ignored)
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Union[os.PathLike, str], chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 of one file without loading it entirely in memory."""
    source = Path(path)
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        while True:
            block = stream.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def sha256_file_bundle(paths: Sequence[Union[os.PathLike, str]]) -> Dict[str, Any]:
    """Fingerprint a Shapefile/GPKG-style input bundle deterministically."""
    resolved = sorted(
        (Path(path).resolve(strict=True) for path in paths),
        key=lambda path: path.name.casefold(),
    )
    if not resolved:
        raise ValueError("At least one input file is required")
    bundle_digest = hashlib.sha256()
    files = []
    for path in resolved:
        file_hash = sha256_file(path)
        size = path.stat().st_size
        files.append({
            "name": path.name,
            "size": size,
            "sha256": file_hash,
        })
        bundle_digest.update(path.name.encode("utf-8"))
        bundle_digest.update(b"\0")
        bundle_digest.update(str(size).encode("ascii"))
        bundle_digest.update(b"\0")
        bundle_digest.update(file_hash.encode("ascii"))
        bundle_digest.update(b"\n")
    return {
        "algorithm": "sha256",
        "bundle_sha256": bundle_digest.hexdigest(),
        "files": files,
    }


def python_runtime_environment(extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Collect dependency-free runtime metadata; QGIS callers may add versions."""
    environment = {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "operating_system": platform.system(),
        "architecture": platform.machine(),
    }
    if extra:
        environment.update(safe_json_value(extra))
    return environment


def read_build_info(plugin_directory: Union[os.PathLike, str]) -> Dict[str, Any]:
    """Read packaging provenance without requiring a Git executable at runtime."""
    path = Path(plugin_directory) / "build_info.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"git_commit": UNKNOWN_VALUE}
    if not isinstance(raw, Mapping):
        return {"git_commit": UNKNOWN_VALUE}
    return {
        "git_commit": str(raw.get("git_commit") or UNKNOWN_VALUE),
        "built_at": raw.get("built_at"),
        "dirty": bool(raw.get("dirty", False)),
    }


def safe_json_value(
    value: Any,
    *,
    _seen: Optional[set] = None,
    _depth: int = 0,
    max_depth: int = 20,
) -> Any:
    """Convert arbitrary settings/statistics to deterministic JSON-safe data.

    Sensitive mapping entries are replaced with ``[REDACTED]``.  Unknown
    objects are represented by type name only so their repr cannot leak
    credentials or unstable memory addresses.
    """
    if _depth > max_depth:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Enum):
        return safe_json_value(
            value.value,
            _seen=_seen,
            _depth=_depth + 1,
            max_depth=max_depth,
        )
    if isinstance(value, (bytes, bytearray, memoryview)):
        payload = bytes(value)
        return {
            "type": "bytes",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    if _seen is None:
        _seen = set()
    value_id = id(value)
    if value_id in _seen:
        return "<cycle>"

    if isinstance(value, Mapping):
        _seen.add(value_id)
        try:
            result: Dict[str, Any] = {}
            for key, item in sorted(
                value.items(),
                key=lambda pair: str(pair[0]),
            ):
                string_key = unicodedata.normalize("NFKC", str(key))
                if _is_sensitive_key(string_key):
                    result[string_key] = REDACTED_VALUE
                else:
                    result[string_key] = safe_json_value(
                        item,
                        _seen=_seen,
                        _depth=_depth + 1,
                        max_depth=max_depth,
                    )
            return result
        finally:
            _seen.remove(value_id)

    if is_dataclass(value) and not isinstance(value, type):
        _seen.add(value_id)
        try:
            return safe_json_value(
                {
                    field.name: getattr(value, field.name)
                    for field in fields(value)
                },
                _seen=_seen,
                _depth=_depth + 1,
                max_depth=max_depth,
            )
        finally:
            _seen.remove(value_id)

    if isinstance(value, (list, tuple)):
        _seen.add(value_id)
        try:
            return [
                safe_json_value(
                    item,
                    _seen=_seen,
                    _depth=_depth + 1,
                    max_depth=max_depth,
                )
                for item in value
            ]
        finally:
            _seen.remove(value_id)

    if isinstance(value, (set, frozenset)):
        _seen.add(value_id)
        try:
            safe_items = [
                safe_json_value(
                    item,
                    _seen=_seen,
                    _depth=_depth + 1,
                    max_depth=max_depth,
                )
                for item in value
            ]
            return sorted(
                safe_items,
                key=lambda item: json.dumps(
                    item,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        finally:
            _seen.remove(value_id)

    return "<non-serializable:{}>".format(type(value).__name__)


def normalize_layer_summary(
    layer: Union[Mapping[str, Any], str],
    *,
    output: bool = False,
    public: bool = True,
) -> Dict[str, Any]:
    """Return a stable, safe input/output layer summary.

    The caller may include any extra metadata.  Common fields remain at the
    top level; other values are retained below ``details``.
    """
    if isinstance(layer, str):
        raw: Dict[str, Any] = {"name": layer}
    elif isinstance(layer, Mapping):
        raw = dict(layer)
    else:
        raw = {"name": "<non-serializable:{}>".format(type(layer).__name__)}

    known_fields = (
        "name",
        "role" if not output else "kind",
        "layer_id",
        "source",
        "provider",
        "crs",
        "geometry_type",
        "feature_count",
        "encoding",
        "source_sha256",
        "bundle_sha256",
        "geometry_repairs",
    )
    summary: Dict[str, Any] = {}
    for field_name in known_fields:
        if field_name not in raw:
            continue
        value = raw.pop(field_name)
        if field_name == "source" and value is not None:
            value = (
                sanitize_source_reference(value)
                if public
                else redact_connection_secrets(value)
            )
        elif field_name == "feature_count" and value is not None:
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = safe_json_value(value)
        else:
            value = safe_json_value(value)
        summary[field_name] = value

    if "count" in raw and "feature_count" not in summary:
        count_value = raw.pop("count")
        try:
            summary["feature_count"] = int(count_value)
        except (TypeError, ValueError):
            summary["feature_count"] = safe_json_value(count_value)
    if raw:
        summary["details"] = (
            sanitize_public_value(raw)
            if public else safe_json_value(raw)
        )
    return summary


def _as_aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("Run timestamps must be datetime values")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_seconds(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _normalize_error(
    error: Any,
    *,
    public: bool = False,
) -> Optional[Dict[str, Any]]:
    if error is None:
        return None
    if isinstance(error, BaseException):
        normalized = {
            "type": type(error).__name__,
            "message": redact_connection_secrets(str(error)),
        }
        return sanitize_public_value(normalized) if public else normalized
    if isinstance(error, Mapping):
        safe_error = safe_json_value(error)
        if isinstance(safe_error, dict) and "message" in safe_error:
            safe_error["message"] = redact_connection_secrets(
                safe_error["message"]
            )
        return sanitize_public_value(safe_error) if public else safe_error
    normalized = {
        "type": None,
        "message": redact_connection_secrets(error),
    }
    return sanitize_public_value(normalized) if public else normalized


def build_run_manifest(
    *,
    plugin_version: str,
    workflow: str,
    settings: Optional[Mapping[str, Any]] = None,
    input_layers: Optional[Iterable[Union[Mapping[str, Any], str]]] = None,
    output_layers: Optional[Iterable[Union[Mapping[str, Any], str]]] = None,
    processing_stats: Optional[Mapping[str, Any]] = None,
    decision_reuse_count: int = 0,
    status: str = "success",
    error: Any = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    local_timezone: Optional[tzinfo] = None,
    plugin_name: str = DEFAULT_PLUGIN_NAME,
    git_commit: Optional[str] = None,
    ruleset: Optional[Mapping[str, Any]] = None,
    runtime_environment: Optional[Mapping[str, Any]] = None,
    crs_context: Optional[Mapping[str, Any]] = None,
    input_checksums: Optional[Iterable[Mapping[str, Any]]] = None,
    output_hashes: Any = None,
    decision_cache: Optional[Mapping[str, Any]] = None,
    excluded_layers: Optional[Iterable[Mapping[str, Any]]] = None,
    public_manifest: bool = True,
) -> Dict[str, Any]:
    """Build a complete, JSON-serializable run manifest."""
    normalized_status = str(status).strip().casefold()
    if normalized_status not in VALID_RUN_STATUSES:
        raise ValueError("Unsupported run status: {}".format(status))
    if normalized_status == "error":
        normalized_status = "failed"
    if not str(plugin_version).strip():
        raise ValueError("plugin_version is required")
    if not str(workflow).strip():
        raise ValueError("workflow is required")
    try:
        reuse_count = int(decision_reuse_count)
    except (TypeError, ValueError):
        raise ValueError("decision_reuse_count must be an integer")
    if reuse_count < 0:
        raise ValueError("decision_reuse_count cannot be negative")

    finished_utc = _as_aware_utc(
        finished_at or datetime.now(timezone.utc)
    )
    started_utc = _as_aware_utc(started_at or finished_utc)
    if finished_utc < started_utc:
        raise ValueError("finished_at cannot precede started_at")
    if local_timezone is None:
        local_timezone = datetime.now().astimezone().tzinfo or timezone.utc

    started_local = started_utc.astimezone(local_timezone)
    finished_local = finished_utc.astimezone(local_timezone)
    local_zone_name = finished_local.tzname() or str(local_timezone)

    normalized_inputs = [
        normalize_layer_summary(layer, output=False, public=public_manifest)
        for layer in (input_layers or [])
    ]
    normalized_outputs = [
        normalize_layer_summary(layer, output=True, public=public_manifest)
        for layer in (output_layers or [])
    ]

    manifest: Dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "plugin": {
            "name": str(plugin_name).strip() or DEFAULT_PLUGIN_NAME,
            "version": str(plugin_version).strip(),
            "git_commit": str(git_commit or UNKNOWN_VALUE),
        },
        "workflow": str(workflow).strip(),
        "status": normalized_status,
        "cancelled": normalized_status == "cancelled",
        "error": _normalize_error(error, public=public_manifest),
        "timestamps": {
            "started_utc": _iso_seconds(started_utc),
            "finished_utc": _iso_seconds(finished_utc),
            "started_local": _iso_seconds(started_local),
            "finished_local": _iso_seconds(finished_local),
            "local_timezone": local_zone_name,
            "duration_seconds": round(
                (finished_utc - started_utc).total_seconds(),
                6,
            ),
        },
        "settings": (
            sanitize_public_settings(settings or {})
            if public_manifest else safe_json_value(settings or {})
        ),
        "inputs": normalized_inputs,
        "outputs": normalized_outputs,
        "processing": {
            "statistics": (
                sanitize_public_value(processing_stats or {})
                if public_manifest
                else safe_json_value(processing_stats or {})
            ),
            "decision_reuse_count": reuse_count,
            "excluded_layers": (
                sanitize_public_value(list(excluded_layers or []))
                if public_manifest
                else safe_json_value(list(excluded_layers or []))
            ),
        },
        "provenance": {
            "ruleset": (
                sanitize_public_value(ruleset or {})
                if public_manifest else safe_json_value(ruleset or {})
            ),
            "runtime": (
                sanitize_public_value(
                    runtime_environment or python_runtime_environment()
                )
                if public_manifest else safe_json_value(
                    runtime_environment or python_runtime_environment()
                )
            ),
            "crs_context": (
                sanitize_public_value(crs_context or {})
                if public_manifest else safe_json_value(crs_context or {})
            ),
            "input_checksums": (
                sanitize_public_value(list(input_checksums or []))
                if public_manifest
                else safe_json_value(list(input_checksums or []))
            ),
            "output_hashes": (
                sanitize_public_value(output_hashes or {})
                if public_manifest else safe_json_value(output_hashes or {})
            ),
            "decision_cache": (
                sanitize_public_value(decision_cache or {})
                if public_manifest else safe_json_value(decision_cache or {})
            ),
            "public_manifest": bool(public_manifest),
        },
    }
    manifest["semantic_sha256"] = deterministic_content_hash({
        "plugin": manifest["plugin"],
        "workflow": manifest["workflow"],
        "settings": _semantic_settings(manifest["settings"]),
        "inputs": _semantic_input_summaries(manifest["inputs"]),
        "processing": _semantic_processing(manifest["processing"]),
        "ruleset": manifest["provenance"]["ruleset"],
        "crs_context": manifest["provenance"]["crs_context"],
        "input_checksums": _canonical_sequence(
            manifest["provenance"]["input_checksums"]
        ),
        "decision_cache": manifest["provenance"]["decision_cache"],
        "output_content_hashes": _canonical_sequence([
            item for item in manifest["provenance"]["output_hashes"]
            if isinstance(item, Mapping) and item.get("content_sha256")
        ]) if isinstance(
            manifest["provenance"]["output_hashes"], list
        ) else manifest["provenance"]["output_hashes"],
    }, ignored_keys=())
    # This assertion deliberately rejects accidental non-finite/unsupported
    # additions made by future callers or maintainers.
    json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )
    return manifest


def normalize_filename(
    filename: Any,
    *,
    fallback: str = DEFAULT_PLUGIN_NAME,
    max_length: int = 120,
) -> str:
    """Normalize a single safe filename while preserving Korean text."""
    if max_length < 8:
        raise ValueError("max_length must be at least 8")
    text = unicodedata.normalize("NFKC", str(filename or ""))
    text = _FORBIDDEN_FILENAME_RE.sub("_", text)
    text = _WHITESPACE_RE.sub(" ", text).strip(" .")
    text = _REPEATED_UNDERSCORE_RE.sub("_", text)
    if not text or text in {".", ".."}:
        text = unicodedata.normalize("NFKC", str(fallback or DEFAULT_PLUGIN_NAME))
        text = _FORBIDDEN_FILENAME_RE.sub("_", text).strip(" .")
    if not text:
        text = DEFAULT_PLUGIN_NAME

    suffix = Path(text).suffix
    stem = text[: -len(suffix)] if suffix else text
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        stem = "_{}".format(stem)
        text = "{}{}".format(stem, suffix)
    if len(text) > max_length:
        if suffix and len(suffix) < max_length - 1:
            stem = stem[: max_length - len(suffix)].rstrip(" .")
            text = "{}{}".format(stem or "_", suffix)
        else:
            text = text[:max_length].rstrip(" .")
    return text or DEFAULT_PLUGIN_NAME


def _normalize_extension(extension: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(extension or ""))
    normalized = normalized.lstrip(".").casefold()
    if not normalized or not re.fullmatch(r"[a-z0-9]+", normalized):
        raise ValueError("extension must contain only ASCII letters and digits")
    return ".{}".format(normalized)


def prepare_output_path(
    output_directory: Union[os.PathLike, str],
    filename: Any,
    *,
    extension: Optional[str] = None,
    create_directory: bool = True,
    unique: bool = False,
) -> Path:
    """Return a path guaranteed to remain below the requested directory."""
    if output_directory is None or not str(output_directory).strip():
        raise ValueError("output_directory is required")
    base_directory = Path(output_directory).expanduser().resolve(strict=False)
    if create_directory:
        base_directory.mkdir(parents=True, exist_ok=True)
    elif not base_directory.is_dir():
        raise FileNotFoundError(str(base_directory))

    safe_name = normalize_filename(filename)
    if extension is not None:
        safe_extension = _normalize_extension(extension)
        current_suffix = Path(safe_name).suffix
        stem = safe_name[: -len(current_suffix)] if current_suffix else safe_name
        safe_name = normalize_filename("{}{}".format(stem, safe_extension))

    candidate = (base_directory / safe_name).resolve(strict=False)
    try:
        candidate.relative_to(base_directory)
    except ValueError:
        raise ValueError("Output path escaped the requested directory")

    if unique:
        base_stem = candidate.stem
        suffix = candidate.suffix
        counter = 1
        while candidate.exists():
            candidate = base_directory / "{}_{}{}".format(
                base_stem,
                counter,
                suffix,
            )
            counter += 1
    return candidate


def prepare_artifact_paths(
    output_directory: Union[os.PathLike, str],
    base_name: Any,
    *,
    include_gpkg: bool = True,
    include_manifest: bool = True,
    unique: bool = False,
) -> Dict[str, Path]:
    """Prepare matching GPKG and run-manifest paths under one safe directory."""
    if not include_gpkg and not include_manifest:
        raise ValueError("At least one artifact type must be requested")
    directory = Path(output_directory).expanduser().resolve(strict=False)
    directory.mkdir(parents=True, exist_ok=True)

    normalized = normalize_filename(base_name)
    existing_suffix = Path(normalized).suffix
    stem = (
        normalized[: -len(existing_suffix)]
        if existing_suffix
        else normalized
    )
    stem = normalize_filename(stem)

    counter = 0
    while True:
        candidate_stem = stem if counter == 0 else "{}_{}".format(stem, counter)
        paths: Dict[str, Path] = {}
        if include_gpkg:
            paths["gpkg"] = prepare_output_path(
                directory,
                candidate_stem,
                extension="gpkg",
                create_directory=False,
            )
        if include_manifest:
            paths["manifest"] = prepare_output_path(
                directory,
                "{}_run".format(candidate_stem),
                extension="json",
                create_directory=False,
            )
        if not unique or not any(path.exists() for path in paths.values()):
            return paths
        counter += 1


def save_manifest_atomic(
    manifest: Mapping[str, Any],
    path: Union[os.PathLike, str],
) -> Path:
    """Atomically save a manifest, preserving any prior file on failure."""
    if not isinstance(manifest, Mapping):
        raise TypeError("manifest must be a mapping")
    safe_document = safe_json_value(manifest)
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=str(target_path.parent),
            prefix=".{}.".format(target_path.name),
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(
                safe_document,
                stream,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary_path), str(target_path))
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    return target_path
