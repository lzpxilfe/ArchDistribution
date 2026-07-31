import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from heritage_identity_store import (
    DecisionStore,
    build_source_identity,
    canonical_uid_pair,
    decision_pair_key,
    geometry_signature,
)


class SourceIdentityTests(unittest.TestCase):
    def test_native_code_identity_is_role_prefixed_and_normalized(self):
        identity = build_source_identity(
            "발굴조사",
            native_code=" AB  123 ",
            name="공주 유적",
            geometry=b"wkb-a",
        )

        self.assertTrue(identity.uid.startswith("발굴조사:code:ab 123:part:"))
        self.assertEqual(identity.native_code, "ab 123")

    def test_same_native_code_different_parts_have_distinct_uids(self):
        first = build_source_identity(
            "발굴조사",
            native_code="A-1",
            name="I 지역",
            geometry=b"polygon-one",
        )
        second = build_source_identity(
            "발굴조사",
            native_code="A-1",
            name="II 지역",
            geometry=b"polygon-two",
        )

        self.assertNotEqual(first.uid, second.uid)
        self.assertNotEqual(first.geometry_signature, second.geometry_signature)

    def test_code_takes_precedence_over_fallback_fields(self):
        first = build_source_identity(
            "문화유적분포지도",
            native_code="H-99",
            name="이름",
            project_name="사업",
            address="주소",
            geometry=b"same-geometry",
        )
        second = build_source_identity(
            "문화유적분포지도",
            native_code="H-99",
            name="이름",
            project_name="사업",
            address="주소",
            geometry=b"same-geometry",
            extra_content={"관리필드": "변경"},
        )

        self.assertEqual(first.uid, second.uid)
        self.assertNotEqual(first.content_fingerprint, second.content_fingerprint)

    def test_fallback_uses_normalized_name_project_address_and_geometry(self):
        first = build_source_identity(
            "지표조사",
            name=" 공주   유적 ",
            project_name="정비 사업",
            address="신관동 24-171",
            geometry="POLYGON ((0 0, 1 0, 0 0))",
        )
        second = build_source_identity(
            "지표조사",
            name="공주 유적",
            project_name="정비  사업",
            address="신관동 24-171",
            geometry="POLYGON ((0 0, 1 0, 0 0))",
        )

        self.assertEqual(first.uid, second.uid)
        self.assertTrue(first.uid.startswith("지표조사:fallback:"))

    def test_role_prevents_cross_source_uid_collision(self):
        common = {
            "native_code": "10",
            "name": "같은 이름",
            "geometry": b"same",
        }
        designated = build_source_identity("국가지정", **common)
        distribution = build_source_identity("문화유적분포지도", **common)

        self.assertNotEqual(designated.uid, distribution.uid)

    def test_geometry_json_order_is_stable(self):
        first = {"type": "Point", "coordinates": [127.1, 36.4]}
        second = {"coordinates": [127.1, 36.4], "type": "Point"}

        self.assertEqual(geometry_signature(first), geometry_signature(second))


class DecisionStoreTests(unittest.TestCase):
    def setUp(self):
        self.first = build_source_identity(
            "국가지정",
            native_code="N-1",
            name="공주 유적",
            geometry=b"national",
        )
        self.second = build_source_identity(
            "문화유적분포지도",
            native_code="D-2",
            name="공주 유적",
            geometry=b"distribution",
        )

    def test_pair_key_is_independent_of_input_order(self):
        self.assertEqual(
            canonical_uid_pair(self.first.uid, self.second.uid),
            canonical_uid_pair(self.second.uid, self.first.uid),
        )
        self.assertEqual(
            decision_pair_key(self.first.uid, self.second.uid),
            decision_pair_key(self.second.uid, self.first.uid),
        )

    def test_reuse_requires_same_policy_and_both_fingerprints(self):
        store = DecisionStore()
        store.record(
            self.first.uid,
            self.first.content_fingerprint,
            self.second.uid,
            self.second.content_fingerprint,
            decision="merge",
            policy_version="balanced-1",
            decided_at="2026-07-30T00:00:00+00:00",
        )

        current = store.lookup(
            self.second.uid,
            self.second.content_fingerprint,
            self.first.uid,
            self.first.content_fingerprint,
            policy_version="balanced-1",
        )
        changed_left = store.lookup(
            self.first.uid,
            "changed",
            self.second.uid,
            self.second.content_fingerprint,
            policy_version="balanced-1",
        )
        changed_right = store.lookup(
            self.first.uid,
            self.first.content_fingerprint,
            self.second.uid,
            "changed",
            policy_version="balanced-1",
        )
        changed_policy = store.lookup(
            self.first.uid,
            self.first.content_fingerprint,
            self.second.uid,
            self.second.content_fingerprint,
            policy_version="balanced-2",
        )

        self.assertTrue(current.reusable)
        self.assertEqual(current.decision, "merge")
        self.assertEqual(changed_left.status, "stale")
        self.assertEqual(changed_right.status, "stale")
        self.assertEqual(changed_policy.status, "stale")

    def test_save_load_round_trip_and_reverse_lookup(self):
        store = DecisionStore()
        store.record(
            self.first.uid,
            self.first.content_fingerprint,
            self.second.uid,
            self.second.content_fingerprint,
            decision="link",
            policy_version="policy-1",
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "decisions.json"
            store.save(path)
            loaded = DecisionStore.load(path)
            result = loaded.lookup(
                self.second.uid,
                self.second.content_fingerprint,
                self.first.uid,
                self.first.content_fingerprint,
                policy_version="policy-1",
            )

        self.assertEqual(loaded.load_status, "loaded")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(result.status, "reusable")
        self.assertEqual(result.decision, "link")

    def test_malformed_json_loads_as_empty_without_raising(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.json"
            path.write_text("{not-json", encoding="utf-8")

            loaded = DecisionStore.load(path)

        self.assertEqual(loaded.load_status, "malformed")
        self.assertEqual(len(loaded), 0)

    def test_old_schema_loads_as_empty_without_reusing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.json"
            path.write_text(
                json.dumps({"schema_version": 0, "decisions": {}}),
                encoding="utf-8",
            )

            loaded = DecisionStore.load(path)

        self.assertEqual(loaded.load_status, "unsupported_schema")
        self.assertEqual(len(loaded), 0)

    def test_invalid_record_is_skipped_without_discarding_valid_record(self):
        store = DecisionStore()
        valid = store.record(
            self.first.uid,
            self.first.content_fingerprint,
            self.second.uid,
            self.second.content_fingerprint,
            decision="keep",
            policy_version="policy-1",
        )
        document = store.to_document()
        document["decisions"]["broken"] = {"decision": "merge"}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            loaded = DecisionStore.load(path)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded._records[valid.pair_key].decision, "keep")

    def test_atomic_save_leaves_no_temporary_file(self):
        store = DecisionStore()
        store.record(
            self.first.uid,
            self.first.content_fingerprint,
            self.second.uid,
            self.second.content_fingerprint,
            decision="keep",
            policy_version="policy-1",
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.json"
            path.write_text('{"old": true}', encoding="utf-8")
            store.save(path)
            temporary_files = list(Path(directory).glob(".decisions.json.*.tmp"))
            document = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(temporary_files, [])
        self.assertEqual(document["schema_version"], 1)

    def test_atomic_replace_failure_preserves_previous_file(self):
        store = DecisionStore()
        store.record(
            self.first.uid,
            self.first.content_fingerprint,
            self.second.uid,
            self.second.content_fingerprint,
            decision="keep",
            policy_version="policy-1",
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.json"
            old_content = '{"preserve": true}\n'
            path.write_text(old_content, encoding="utf-8")
            with mock.patch(
                "heritage_identity_store.os.replace",
                side_effect=OSError("simulated replacement failure"),
            ):
                with self.assertRaises(OSError):
                    store.save(path)
            remaining_temporary_files = list(
                Path(directory).glob(".decisions.json.*.tmp")
            )
            after_failure = path.read_text(encoding="utf-8")

        self.assertEqual(after_failure, old_content)
        self.assertEqual(remaining_temporary_files, [])

    def test_invalid_decision_is_rejected(self):
        store = DecisionStore()
        with self.assertRaises(ValueError):
            store.record(
                self.first.uid,
                self.first.content_fingerprint,
                self.second.uid,
                self.second.content_fingerprint,
                decision="delete",
                policy_version="policy-1",
            )


if __name__ == "__main__":
    unittest.main()
