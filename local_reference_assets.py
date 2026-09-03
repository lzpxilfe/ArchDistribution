"""Resolve optional classification assets already present on the user's PC.

The public plugin ZIP intentionally does not redistribute the historical
reference files while their provenance audit is pending.  Existing users may
still have those exact files in a QGIS plugin backup.  This module reconnects
only the registered historical bytes and never copies them into a release.
"""

from hashlib import sha256
from pathlib import Path


# Hashes recorded in docs/research/reference-data-register.json.  Keeping the
# digest here lets an installed runtime verify a legacy local file even though
# the research documentation is not part of the QGIS plugin ZIP.
REGISTERED_LEGACY_SHA256 = {
    "reference_data.json": {
        "1b1079af54661bc695ebc1884e855618f46a5345af2ab4f09e28737959695b6f",
    },
    "smart_patterns.json": {
        "504e3118aecaffc30c09eb39bce2545f8af25d0794722e1401a1c7c5f2f6a947",
    },
}


def file_sha256(path):
    """Return a streaming SHA-256 digest for ``path``."""
    digest = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def qgis_profile_from_plugin_dir(plugin_dir):
    """Infer the QGIS profile root from an installed plugin directory."""
    directory = Path(plugin_dir).resolve()
    parents = directory.parents
    if (
        len(parents) >= 3
        and parents[0].name.casefold() == "plugins"
        and parents[1].name.casefold() == "python"
    ):
        return parents[2]
    return None


def legacy_asset_candidates(plugin_dir, filename):
    """Return newest-first legacy QGIS backup candidates for ``filename``."""
    profile = qgis_profile_from_plugin_dir(plugin_dir)
    if profile is None:
        return []

    patterns = (
        ("plugin_backups", "ArchDistribution*"),
        ("python/plugins_disabled", "ArchDistribution*"),
        ("python/plugins_TRASH", "ArchDistribution*"),
        ("python/plugins", "ArchDistribution_*"),
    )
    candidates = set()
    for relative_root, plugin_pattern in patterns:
        root = profile / relative_root
        if not root.is_dir():
            continue
        for plugin_backup in root.glob(plugin_pattern):
            candidate = plugin_backup / filename
            if candidate.is_file():
                candidates.add(candidate.resolve())

    def newest_first(path):
        try:
            modified = path.stat().st_mtime_ns
        except OSError:
            modified = 0
        return (-modified, str(path).casefold())

    return sorted(candidates, key=newest_first)


def resolve_local_reference_asset(
    plugin_dir,
    filename,
    *,
    registered_legacy_sha256=None,
):
    """Find a direct user asset or a verified historical QGIS backup.

    A file placed directly in the active plugin directory remains an explicit
    user-supplied override and is accepted as before.  Automatic backup lookup
    is deliberately narrower: only bytes matching a registered digest qualify.

    Returns ``(path, source)`` where source is ``"plugin"`` or
    ``"legacy_backup"``.  ``(None, None)`` means no suitable local asset exists.
    """
    active = Path(plugin_dir) / filename
    if active.is_file():
        return active, "plugin"

    registered = (
        REGISTERED_LEGACY_SHA256.get(filename, set())
        if registered_legacy_sha256 is None
        else set(registered_legacy_sha256)
    )
    if not registered:
        return None, None

    for candidate in legacy_asset_candidates(plugin_dir, filename):
        try:
            if file_sha256(candidate).casefold() in registered:
                return candidate, "legacy_backup"
        except OSError:
            continue
    return None, None
