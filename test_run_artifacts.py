from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from run_artifacts import (
    MANIFEST_SCHEMA_VERSION,
    REDACTED_VALUE,
    build_run_manifest,
    normalize_filename,
    normalize_layer_summary,
    prepare_artifact_paths,
    prepare_output_path,
    redact_connection_secrets,
    safe_json_value,
    save_manifest_atomic,
)


KST = timezone(timedelta(hours=9), name="KST")


class JsonSafetyTests(unittest.TestCase):
    def test_settings_are_json_safe_and_sensitive_values_are_redacted(self):
        @dataclass
        class CustomSettings:
            enabled: bool
            private_key: str

        cyclic = []
        cyclic.append(cyclic)
        settings = {
            "password": "do-not-save",
            "비밀번호": "이것도-저장하면-안됨",
            "nested": {
                "API-Key": "also-secret",
                "path": Path("결과/파일"),
            },
            "binary": b"abc",
            "custom": CustomSettings(True, "hidden"),
            "set_value": {"나", "가"},
            "nan": math.nan,
            "cycle": cyclic,
            "unknown": object(),
        }

        safe = safe_json_value(settings)

        self.assertEqual(safe["password"], REDACTED_VALUE)
        self.assertEqual(safe["비밀번호"], REDACTED_VALUE)
        self.assertEqual(safe["nested"]["API-Key"], REDACTED_VALUE)
        self.assertEqual(safe["custom"]["private_key"], REDACTED_VALUE)
        self.assertEqual(safe["binary"]["size"], 3)
        self.assertEqual(safe["set_value"], ["가", "나"])
        self.assertEqual(safe["nan"], "NaN")
        self.assertEqual(safe["cycle"], ["<cycle>"])
        self.assertEqual(safe["unknown"], "<non-serializable:object>")
        json.dumps(safe, ensure_ascii=False, allow_nan=False)

    def test_connection_credentials_are_redacted(self):
        source = (
            "postgres://reader:hunter2@example.test/db "
            "password='again' token=abc&api_key=xyz"
        )

        redacted = redact_connection_secrets(source)

        self.assertNotIn("hunter2", redacted)
        self.assertNotIn("again", redacted)
        self.assertNotIn("abc", redacted)
        self.assertNotIn("xyz", redacted)
        self.assertGreaterEqual(redacted.count(REDACTED_VALUE), 4)


class ManifestTests(unittest.TestCase):
    def test_builds_complete_manifest_with_utc_and_local_times(self):
        started = datetime(2026, 7, 30, 1, 2, 3, tzinfo=timezone.utc)
        finished = datetime(2026, 7, 30, 1, 2, 8, 250000, tzinfo=timezone.utc)

        manifest = build_run_manifest(
            plugin_version="1.0.5",
            workflow="distribution_map",
            settings={"buffer_m": 2000, "auth_token": "secret"},
            input_layers=[
                {
                    "name": "문화유적분포지도",
                    "role": "distribution",
                    "feature_count": "10",
                    "source": "file:///data/sites.shp",
                }
            ],
            output_layers=[
                {
                    "name": "주변유적",
                    "kind": "representative",
                    "count": 7,
                }
            ],
            processing_stats={"candidate_count": 3, "elapsed": 5.25},
            decision_reuse_count=2,
            status="success",
            started_at=started,
            finished_at=finished,
            local_timezone=KST,
        )

        self.assertEqual(manifest["schema_version"], MANIFEST_SCHEMA_VERSION)
        self.assertEqual(manifest["plugin"]["version"], "1.0.5")
        self.assertEqual(manifest["workflow"], "distribution_map")
        self.assertEqual(manifest["status"], "success")
        self.assertFalse(manifest["cancelled"])
        self.assertIsNone(manifest["error"])
        self.assertEqual(
            manifest["timestamps"]["started_utc"],
            "2026-07-30T01:02:03+00:00",
        )
        self.assertEqual(
            manifest["timestamps"]["started_local"],
            "2026-07-30T10:02:03+09:00",
        )
        self.assertEqual(manifest["timestamps"]["local_timezone"], "KST")
        self.assertEqual(manifest["timestamps"]["duration_seconds"], 5.25)
        self.assertEqual(manifest["settings"]["auth_token"], REDACTED_VALUE)
        self.assertEqual(manifest["inputs"][0]["feature_count"], 10)
        self.assertEqual(manifest["outputs"][0]["feature_count"], 7)
        self.assertEqual(
            manifest["processing"]["decision_reuse_count"],
            2,
        )
        json.dumps(manifest, ensure_ascii=False, allow_nan=False)

    def test_cancelled_and_error_states_are_explicit_and_safe(self):
        cancelled = build_run_manifest(
            plugin_version="1.0.5",
            workflow="preservation_area",
            status="cancelled",
            error="사용자 취소 token=do-not-save",
        )
        failed = build_run_manifest(
            plugin_version="1.0.5",
            workflow="distribution_map",
            status="error",
            error=RuntimeError("failure password=hidden"),
        )

        self.assertTrue(cancelled["cancelled"])
        self.assertEqual(cancelled["error"]["type"], None)
        self.assertNotIn("do-not-save", cancelled["error"]["message"])
        self.assertFalse(failed["cancelled"])
        self.assertEqual(failed["error"]["type"], "RuntimeError")
        self.assertNotIn("hidden", failed["error"]["message"])

    def test_invalid_status_counts_and_time_order_are_rejected(self):
        now = datetime(2026, 7, 30, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            build_run_manifest(
                plugin_version="1.0.5",
                workflow="distribution_map",
                status="finished",
            )
        with self.assertRaises(ValueError):
            build_run_manifest(
                plugin_version="1.0.5",
                workflow="distribution_map",
                decision_reuse_count=-1,
            )
        with self.assertRaises(ValueError):
            build_run_manifest(
                plugin_version="1.0.5",
                workflow="distribution_map",
                started_at=now,
                finished_at=now - timedelta(seconds=1),
            )

    def test_layer_summary_preserves_details_without_credentials(self):
        summary = normalize_layer_summary(
            {
                "name": "발굴조사",
                "role": "excavation",
                "count": "42",
                "source": "host=x password=hidden",
                "custom": {"client_secret": "hidden-too", "year": 2026},
            }
        )

        self.assertEqual(summary["feature_count"], 42)
        self.assertNotIn("hidden", summary["source"])
        self.assertEqual(
            summary["details"]["custom"]["client_secret"],
            REDACTED_VALUE,
        )
        self.assertEqual(summary["details"]["custom"]["year"], 2026)

    def test_non_numeric_layer_count_is_safely_preserved(self):
        summary = normalize_layer_summary(
            {"name": "외부 레이어", "count": "unknown"}
        )

        self.assertEqual(summary["feature_count"], "unknown")


class OutputPathTests(unittest.TestCase):
    def test_filename_normalization_blocks_traversal_and_reserved_names(self):
        self.assertEqual(
            normalize_filename("../../신관동:24-171?.gpkg"),
            "_.._신관동_24-171_.gpkg",
        )
        self.assertEqual(normalize_filename("CON.json"), "_CON.json")
        self.assertEqual(normalize_filename("  "), "ArchDistribution")
        self.assertLessEqual(len(normalize_filename("가" * 200)), 120)

    def test_prepare_output_path_stays_inside_directory_and_sets_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            target = prepare_output_path(
                Path(directory) / "새 폴더",
                "../../../외부:결과.shp",
                extension=".gpkg",
            )
            base = (Path(directory) / "새 폴더").resolve()

            target.relative_to(base)
            self.assertEqual(target.suffix, ".gpkg")
            self.assertTrue(base.is_dir())

    def test_unique_artifact_paths_use_one_shared_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            first = prepare_artifact_paths(directory, "신관동 결과")
            first["gpkg"].write_bytes(b"existing")

            second = prepare_artifact_paths(
                directory,
                "신관동 결과",
                unique=True,
            )

            self.assertEqual(second["gpkg"].stem, "신관동 결과_1")
            self.assertEqual(second["manifest"].stem, "신관동 결과_1_run")
            self.assertEqual(
                second["gpkg"].parent,
                second["manifest"].parent,
            )

    def test_at_least_one_artifact_must_be_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                prepare_artifact_paths(
                    directory,
                    "result",
                    include_gpkg=False,
                    include_manifest=False,
                )


class AtomicManifestTests(unittest.TestCase):
    def test_atomic_save_round_trip_and_no_temporary_file(self):
        manifest = build_run_manifest(
            plugin_version="1.0.5",
            workflow="distribution_map",
            settings={"비밀번호": "민감하지 않은 키", "password": "secret"},
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "result_run.json"

            returned = save_manifest_atomic(manifest, target)

            loaded = json.loads(target.read_text(encoding="utf-8"))
            temporary_files = list(
                target.parent.glob(".result_run.json.*.tmp")
            )
        self.assertEqual(returned, target)
        self.assertEqual(loaded["plugin"]["version"], "1.0.5")
        self.assertEqual(loaded["settings"]["password"], REDACTED_VALUE)
        self.assertEqual(temporary_files, [])

    def test_replace_failure_preserves_previous_file(self):
        manifest = build_run_manifest(
            plugin_version="1.0.5",
            workflow="distribution_map",
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result_run.json"
            old_content = '{"preserve": true}\n'
            target.write_text(old_content, encoding="utf-8")
            with mock.patch(
                "run_artifacts.os.replace",
                side_effect=OSError("simulated failure"),
            ):
                with self.assertRaises(OSError):
                    save_manifest_atomic(manifest, target)
            after_failure = target.read_text(encoding="utf-8")
            temporary_files = list(
                target.parent.glob(".result_run.json.*.tmp")
            )

        self.assertEqual(after_failure, old_content)
        self.assertEqual(temporary_files, [])


if __name__ == "__main__":
    unittest.main()
