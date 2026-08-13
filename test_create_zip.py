import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from create_zip import approved_reference_assets, select_runtime_files


class RuntimePackagingTests(unittest.TestCase):
    def test_only_declared_root_paths_are_selected(self):
        selected = select_runtime_files(
            [
                "README.md",
                "LICENSE",
                "arch_distribution.py",
                "paper/README.md",
                "paper/LICENSE",
                "docs/research/LICENSE",
                "validation/fixtures/LICENSE",
            ],
            {"README.md", "LICENSE", "arch_distribution.py"},
        )

        self.assertEqual(
            selected,
            ["README.md", "LICENSE", "arch_distribution.py"],
        )

    def test_reference_assets_are_denied_until_explicitly_approved(self):
        register = {
            "assets": [
                {
                    "path": "reference_data.json",
                    "joss_release_approved": False,
                },
                {
                    "path": "smart_patterns.json",
                    "joss_release_approved": True,
                },
                {
                    "path": "nested/not-runtime.json",
                    "joss_release_approved": True,
                },
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            approved_path = Path(directory) / "smart_patterns.json"
            approved_path.write_text("{}", encoding="utf-8")
            path = Path(directory) / "register.json"
            register["assets"][1]["path"] = str(approved_path)
            register["assets"][1]["sha256"] = hashlib.sha256(
                approved_path.read_bytes()
            ).hexdigest()
            path.write_text(json.dumps(register), encoding="utf-8")
            self.assertEqual(
                approved_reference_assets(
                    path,
                    tracked_files=[str(approved_path)],
                ),
                set(),
            )

    def test_reference_asset_requires_root_path_git_tracking_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            root = Path(directory)
            try:
                import os

                os.chdir(root)
                asset = Path("smart_patterns.json")
                asset.write_text("{}", encoding="utf-8")
                digest = hashlib.sha256(asset.read_bytes()).hexdigest()
                register = {
                    "assets": [{
                        "path": asset.as_posix(),
                        "sha256": digest,
                        "joss_release_approved": True,
                    }]
                }
                register_path = Path("register.json")
                register_path.write_text(
                    json.dumps(register), encoding="utf-8"
                )

                self.assertEqual(
                    approved_reference_assets(
                        register_path,
                        tracked_files=[asset.as_posix()],
                    ),
                    {asset.as_posix()},
                )
                asset.write_text('{"changed": true}', encoding="utf-8")
                self.assertEqual(
                    approved_reference_assets(
                        register_path,
                        tracked_files=[asset.as_posix()],
                    ),
                    set(),
                )
            finally:
                os.chdir(previous)

    def test_missing_reference_register_denies_all_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                approved_reference_assets(Path(directory) / "missing.json"),
                set(),
            )


if __name__ == "__main__":
    unittest.main()
