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
    deterministic_content_hash,
    normalize_filename,
    normalize_layer_summary,
    prepare_artifact_paths,
    prepare_output_path,
    redact_connection_secrets,
    safe_json_value,
    save_manifest_atomic,
    sanitize_source_reference,
    sha256_file_bundle,
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
        self.assertEqual(manifest["plugin"]["git_commit"], "unknown")
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
        self.assertEqual(manifest["schema_version"], 2)
        self.assertIn("runtime", manifest["provenance"])
        self.assertRegex(manifest["semantic_sha256"], r"^[0-9a-f]{64}$")
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
        self.assertEqual(failed["status"], "failed")
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

    def test_public_source_summary_removes_absolute_path(self):
        summary = normalize_layer_summary({
            "name": "sites",
            "source": r"C:\\private\\project\\sites.shp|encoding=CP949",
        })

        self.assertEqual(
            summary["source"],
            "file:///sites.shp|encoding=CP949",
        )
        self.assertNotIn("private", summary["source"])

    def test_public_manifest_removes_output_directory_and_hash_is_semantic(self):
        common = {
            "plugin_version": "1.0.5",
            "workflow": "distribution_map",
            "input_checksums": [{"bundle_sha256": "input-hash"}],
            "ruleset": {"ruleset_version": "1", "sha256": "rules"},
            "output_hashes": [
                {"layer": "result", "content_sha256": "content"},
            ],
        }
        first = build_run_manifest(
            **common,
            settings={
                "output_directory": r"C:\private\first",
                "study_area_id": "transient-a",
                "scale": 25000,
            },
            processing_stats={
                "source_scans": [{"elapsed_seconds": 1.2}],
                "artifacts": [{"filename": "first.jpg"}],
            },
        )
        second = build_run_manifest(
            **common,
            settings={
                "output_directory": "/private/second",
                "study_area_id": "transient-b",
                "scale": 25000,
            },
            processing_stats={
                "source_scans": [{"elapsed_seconds": 9.8}],
                "artifacts": [{"filename": "second.jpg"}],
            },
        )

        self.assertEqual(
            first["settings"]["output_directory"],
            "[LOCAL_PATH_REMOVED]",
        )
        self.assertNotIn("private", json.dumps(first))
        self.assertEqual(
            first["semantic_sha256"], second["semantic_sha256"]
        )

    def test_semantic_hash_uses_stable_inputs_not_qgis_mapping_ids(self):
        base = {
            "plugin_version": "1.0.5",
            "workflow": "distribution_map",
            "ruleset": {"ruleset_version": "1", "sha256": "rules"},
            "input_checksums": [
                {"bundle_sha256": "b"},
                {"bundle_sha256": "a"},
            ],
            "output_hashes": [
                {"layer": "b", "content_sha256": "2"},
                {"layer": "a", "content_sha256": "1"},
            ],
        }
        inputs = [
            {
                "name": "designated",
                "role": "local_designated",
                "layer_id": "left-a",
                "source": r"C:\private\designated.shp",
                "encoding": "CP949",
            },
            {
                "name": "distribution",
                "role": "distribution",
                "layer_id": "left-b",
                "source": r"C:\private\distribution.shp",
                "encoding": "UTF-8",
            },
        ]
        first = build_run_manifest(
            **base,
            settings={
                "source_roles": {
                    "left-a": "local_designated",
                    "left-b": "distribution",
                },
                "source_encodings": {
                    "left-a": "CP949",
                    "left-b": "UTF-8",
                },
            },
            input_layers=inputs,
        )
        remapped_inputs = [dict(inputs[1]), dict(inputs[0])]
        remapped_inputs[0]["layer_id"] = "right-b"
        remapped_inputs[1]["layer_id"] = "right-a"
        second = build_run_manifest(
            **{
                **base,
                "input_checksums": list(reversed(base["input_checksums"])),
                "output_hashes": list(reversed(base["output_hashes"])),
            },
            settings={
                "source_roles": {
                    "right-b": "distribution",
                    "right-a": "local_designated",
                },
                "source_encodings": {
                    "right-b": "UTF-8",
                    "right-a": "CP949",
                },
            },
            input_layers=remapped_inputs,
        )

        self.assertEqual(
            first["semantic_sha256"], second["semantic_sha256"]
        )

        changed_inputs = [dict(item) for item in remapped_inputs]
        changed_inputs[0]["role"] = "surface_survey"
        changed = build_run_manifest(
            **base,
            settings=second["settings"],
            input_layers=changed_inputs,
        )
        self.assertNotEqual(
            first["semantic_sha256"], changed["semantic_sha256"]
        )

    def test_partial_success_and_v2_provenance_are_explicit(self):
        manifest = build_run_manifest(
            plugin_version="1.0.5",
            workflow="distribution_map",
            status="partial_success",
            git_commit="abc123",
            ruleset={"version": "matching-v1", "sha256": "deadbeef"},
            crs_context={
                "source": "EPSG:4326",
                "analysis": "EPSG:32652",
                "output": "EPSG:4326",
            },
            excluded_layers=[{"name": "broken", "reason": "invalid CRS"}],
        )

        self.assertEqual(manifest["status"], "partial_success")
        self.assertEqual(manifest["plugin"]["git_commit"], "abc123")
        self.assertEqual(
            manifest["provenance"]["crs_context"]["analysis"],
            "EPSG:32652",
        )
        self.assertEqual(
            manifest["processing"]["excluded_layers"][0]["name"],
            "broken",
        )

    def test_public_manifest_redacts_paths_in_errors_and_statistics(self):
        manifest = build_run_manifest(
            plugin_version="1.0.5",
            workflow="distribution_map",
            status="failed",
            error=RuntimeError(
                r"failed C:\Users\example\private\source.gpkg"
            ),
            processing_stats={
                "artifact_errors": [
                    "failed /home/reviewer/private/result.gpkg"
                ],
                "nested": {
                    "message": "cannot open file:///secret/input.shp"
                },
            },
            excluded_layers=[{
                "name": "broken",
                "reason": r"read error C:\private\broken.shp",
            }],
        )

        serialized = json.dumps(manifest, ensure_ascii=False)
        self.assertNotIn("Users", serialized)
        self.assertNotIn("/home/reviewer", serialized)
        self.assertNotIn("file:///secret", serialized)
        self.assertNotIn(r"C:\private", serialized)
        self.assertGreaterEqual(serialized.count("[LOCAL_PATH_REMOVED]"), 4)


class ReproducibilityTests(unittest.TestCase):
    def test_semantic_hash_ignores_time_paths_and_layer_ids(self):
        left = {
            "timestamps": {"started_utc": "first"},
            "path": r"C:\\one\\result.gpkg",
            "layer_id": "volatile-a",
            "features": [{"id": 1, "name": "유적 A"}],
        }
        right = {
            "timestamps": {"started_utc": "second"},
            "path": "/different/result.gpkg",
            "layer_id": "volatile-b",
            "features": [{"id": 1, "name": "유적 A"}],
        }

        self.assertEqual(
            deterministic_content_hash(left),
            deterministic_content_hash(right),
        )
        right["features"][0]["name"] = "유적 B"
        self.assertNotEqual(
            deterministic_content_hash(left),
            deterministic_content_hash(right),
        )

    def test_bundle_hash_is_order_independent_and_content_sensitive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shp = root / "sample.shp"
            dbf = root / "sample.dbf"
            shp.write_bytes(b"geometry")
            dbf.write_bytes(b"attributes")

            forward = sha256_file_bundle([shp, dbf])
            reverse = sha256_file_bundle([dbf, shp])
            self.assertEqual(
                forward["bundle_sha256"],
                reverse["bundle_sha256"],
            )

            dbf.write_bytes(b"changed")
            changed = sha256_file_bundle([shp, dbf])
            self.assertNotEqual(
                forward["bundle_sha256"],
                changed["bundle_sha256"],
            )

    def test_source_sanitizer_preserves_provider_options(self):
        sanitized = sanitize_source_reference(
            "file:///secret/sites.gpkg|layername=sites"
        )
        self.assertEqual(
            sanitized,
            "file:///sites.gpkg|layername=sites",
        )


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
