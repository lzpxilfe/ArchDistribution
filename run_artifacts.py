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
from pathlib import Path
import re
import tempfile
import unicodedata
from typing import Any, Dict, Iterable, Mapping, Optional, Union


MANIFEST_SCHEMA_VERSION = 1
DEFAULT_PLUGIN_NAME = "ArchDistribution"
VALID_RUN_STATUSES = frozenset({"running", "success", "cancelled", "error"})
REDACTED_VALUE = "[REDACTED]"

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
    )
    summary: Dict[str, Any] = {}
    for field_name in known_fields:
        if field_name not in raw:
            continue
        value = raw.pop(field_name)
        if field_name == "source" and value is not None:
            value = redact_connection_secrets(value)
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
        summary["details"] = safe_json_value(raw)
    return summary


def _as_aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("Run timestamps must be datetime values")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_seconds(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _normalize_error(error: Any) -> Optional[Dict[str, Any]]:
    if error is None:
        return None
    if isinstance(error, BaseException):
        return {
            "type": type(error).__name__,
            "message": redact_connection_secrets(str(error)),
        }
    if isinstance(error, Mapping):
        safe_error = safe_json_value(error)
        if isinstance(safe_error, dict) and "message" in safe_error:
            safe_error["message"] = redact_connection_secrets(
                safe_error["message"]
            )
        return safe_error
    return {
        "type": None,
        "message": redact_connection_secrets(error),
    }


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
) -> Dict[str, Any]:
    """Build a complete, JSON-serializable run manifest."""
    normalized_status = str(status).strip().casefold()
    if normalized_status not in VALID_RUN_STATUSES:
        raise ValueError("Unsupported run status: {}".format(status))
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
        normalize_layer_summary(layer, output=False)
        for layer in (input_layers or [])
    ]
    normalized_outputs = [
        normalize_layer_summary(layer, output=True)
        for layer in (output_layers or [])
    ]

    manifest: Dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "plugin": {
            "name": str(plugin_name).strip() or DEFAULT_PLUGIN_NAME,
            "version": str(plugin_version).strip(),
        },
        "workflow": str(workflow).strip(),
        "status": normalized_status,
        "cancelled": normalized_status == "cancelled",
        "error": _normalize_error(error),
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
        "settings": safe_json_value(settings or {}),
        "inputs": normalized_inputs,
        "outputs": normalized_outputs,
        "processing": {
            "statistics": safe_json_value(processing_stats or {}),
            "decision_reuse_count": reuse_count,
        },
    }
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
