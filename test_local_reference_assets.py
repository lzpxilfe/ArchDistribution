import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from local_reference_assets import (
    REGISTERED_LEGACY_SHA256,
    legacy_asset_candidates,
    qgis_profile_from_plugin_dir,
    resolve_local_reference_asset,
)


class LocalReferenceAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.profile = Path(self.temp_dir.name) / "profiles" / "default"
        self.plugin_dir = (
            self.profile / "python" / "plugins" / "ArchDistribution"
        )
        self.plugin_dir.mkdir(parents=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _backup_asset(self, backup_name, filename, content, mtime=None):
        path = (
            self.profile
            / "plugin_backups"
            / backup_name
            / filename
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path.resolve()

    def test_profile_is_inferred_only_from_qgis_plugin_layout(self):
        self.assertEqual(
            qgis_profile_from_plugin_dir(self.plugin_dir),
            self.profile.resolve(),
        )
        self.assertIsNone(
            qgis_profile_from_plugin_dir(Path(self.temp_dir.name) / "source")
        )

    def test_runtime_hashes_match_the_provenance_register(self):
        register_path = (
            Path(__file__).resolve().parent
            / "docs"
            / "research"
            / "reference-data-register.json"
        )
        register = json.loads(register_path.read_text(encoding="utf-8"))
        registered = {
            item["path"]: {item["sha256"]}
            for item in register["assets"]
        }

        self.assertEqual(REGISTERED_LEGACY_SHA256, registered)

    def test_explicit_active_plugin_asset_remains_authoritative(self):
        active = self.plugin_dir / "reference_data.json"
        active.write_text('{"local": true}', encoding="utf-8")

        selected, source = resolve_local_reference_asset(
            self.plugin_dir,
            "reference_data.json",
            registered_legacy_sha256=set(),
        )

        self.assertEqual(selected, active)
        self.assertEqual(source, "plugin")

    def test_verified_legacy_backup_is_discovered(self):
        content = b'{"site": {"e": "period", "t": "type"}}'
        backup = self._backup_asset(
            "ArchDistribution_backup_20260302_220813",
            "reference_data.json",
            content,
        )
        digest = hashlib.sha256(content).hexdigest()

        selected, source = resolve_local_reference_asset(
            self.plugin_dir,
            "reference_data.json",
            registered_legacy_sha256={digest},
        )

        self.assertEqual(selected, backup)
        self.assertEqual(source, "legacy_backup")

    def test_unregistered_backup_bytes_are_ignored(self):
        self._backup_asset(
            "ArchDistribution_backup_old",
            "smart_patterns.json",
            b'{"noise": ["unreviewed"]}',
        )

        selected, source = resolve_local_reference_asset(
            self.plugin_dir,
            "smart_patterns.json",
            registered_legacy_sha256={"0" * 64},
        )

        self.assertIsNone(selected)
        self.assertIsNone(source)

    def test_candidates_are_checked_newest_first(self):
        now = time.time()
        older = self._backup_asset(
            "ArchDistribution_backup_old",
            "reference_data.json",
            b"old",
            now - 100,
        )
        newer = self._backup_asset(
            "ArchDistribution_backup_new",
            "reference_data.json",
            b"new",
            now,
        )

        self.assertEqual(
            legacy_asset_candidates(
                self.plugin_dir,
                "reference_data.json",
            ),
            [newer, older],
        )


if __name__ == "__main__":
    unittest.main()
