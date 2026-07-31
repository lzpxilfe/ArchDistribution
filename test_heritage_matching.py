import unittest

from heritage_matching import (
    DECISION_KEEP,
    DECISION_LINK,
    DECISION_MERGE,
    PRESET_AUTOMATION,
    PRESET_BALANCED,
    PRESET_CONSERVATIVE,
    ROLE_DISTRIBUTION,
    ROLE_EXCAVATION,
    ROLE_LOCAL_DESIGNATED,
    ROLE_NATIONAL_DESIGNATED,
    ROLE_NATIONAL_REGISTERED,
    ROLE_OTHER,
    ROLE_PROTECTION_ZONE,
    ROLE_SURFACE,
    detect_source_role,
    evaluate_candidate,
    selected_content_fingerprint,
)


def record(uid, role, name, project="", address=""):
    return {
        "uid": uid,
        "role": role,
        "name": name,
        "site_name": name,
        "project_name": project,
        "address": address,
    }


class SourceRoleTests(unittest.TestCase):
    def test_known_nationwide_layer_names_are_detected(self):
        self.assertEqual(
            detect_source_role("국가지정유산", ["국가유산명", "지정종목"]),
            ROLE_NATIONAL_DESIGNATED,
        )
        self.assertEqual(
            detect_source_role("시도지정유산보호구역", ["유산코드"]),
            ROLE_PROTECTION_ZONE,
        )
        self.assertEqual(
            detect_source_role("국가등록문화유산", ["국가유산명"]),
            ROLE_NATIONAL_REGISTERED,
        )
        self.assertEqual(
            detect_source_role("지표유적위치도", ["사업명", "보고서명"]),
            ROLE_SURFACE,
        )
        self.assertEqual(
            detect_source_role("발굴유적위치도", ["사업명", "유적명"]),
            ROLE_EXCAVATION,
        )
        self.assertEqual(
            detect_source_role(
                "문화유적분포지도",
                ["명칭", "유적대분류", "유적중분류"],
            ),
            ROLE_DISTRIBUTION,
        )

    def test_ambiguous_survey_schema_does_not_guess(self):
        self.assertEqual(
            detect_source_role(
                "조사자료",
                ["사업명", "보고서명", "유적명"],
            ),
            ROLE_OTHER,
        )


class MatchingPolicyTests(unittest.TestCase):
    def test_designated_beats_exact_distribution_duplicate(self):
        designated = record(
            "d1", ROLE_LOCAL_DESIGNATED, "서울 탑골공원"
        )
        distribution = record(
            "m1", ROLE_DISTRIBUTION, "서울 탑골공원"
        )
        match = evaluate_candidate(
            designated,
            distribution,
            intersects=True,
            overlap_ratio=0.8,
            preset=PRESET_BALANCED,
        )
        self.assertEqual(match.recommended_decision, DECISION_MERGE)
        self.assertEqual(match.representative_uid, "d1")
        self.assertTrue(match.auto_apply)

    def test_registered_heritage_has_designated_priority(self):
        registered = record(
            "r1", ROLE_NATIONAL_REGISTERED, "서울 근대건축"
        )
        distribution = record(
            "m1", ROLE_DISTRIBUTION, "서울 근대건축"
        )
        match = evaluate_candidate(
            registered,
            distribution,
            intersects=True,
            overlap_ratio=0.9,
        )
        self.assertEqual(match.representative_uid, "r1")
        self.assertTrue(match.auto_apply)

    def test_parent_child_name_is_review_not_auto_merge(self):
        parent = record("d1", ROLE_LOCAL_DESIGNATED, "서울 탑골공원")
        child = record(
            "m1", ROLE_DISTRIBUTION, "탑골공원 팔각정"
        )
        match = evaluate_candidate(
            parent,
            child,
            intersects=True,
            overlap_ratio=1.0,
            preset=PRESET_BALANCED,
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.confidence, "medium")
        self.assertFalse(match.auto_apply)

    def test_excavation_beats_exact_distribution_duplicate(self):
        excavation = record(
            "e1", ROLE_EXCAVATION, "공주 월송유적", "월송 개발사업"
        )
        distribution = record(
            "m1", ROLE_DISTRIBUTION, "공주 월송유적"
        )
        match = evaluate_candidate(
            excavation,
            distribution,
            intersects=True,
            overlap_ratio=0.7,
        )
        self.assertEqual(match.representative_uid, "e1")
        self.assertTrue(match.auto_apply)

    def test_project_name_signal_is_review_only(self):
        excavation = record(
            "e1",
            ROLE_EXCAVATION,
            "A지점",
            "공주 월송유적 정비사업",
        )
        distribution = record(
            "m1", ROLE_DISTRIBUTION, "공주 월송유적"
        )
        match = evaluate_candidate(
            excavation,
            distribution,
            intersects=True,
            overlap_ratio=0.6,
        )
        self.assertEqual(match.rule, "project_name_and_overlap")
        self.assertFalse(match.auto_apply)

    def test_designated_and_excavation_are_linked_not_merged(self):
        designated = record(
            "d1", ROLE_NATIONAL_DESIGNATED, "경희궁지"
        )
        excavation = record("e1", ROLE_EXCAVATION, "경희궁지")
        match = evaluate_candidate(
            designated,
            excavation,
            intersects=True,
            overlap_ratio=0.9,
        )
        self.assertEqual(match.recommended_decision, DECISION_LINK)
        self.assertNotEqual(match.representative_uid, "")

    def test_surface_survey_is_never_automatically_suppressed(self):
        surface = record("s1", ROLE_SURFACE, "공주 월송유적")
        excavation = record("e1", ROLE_EXCAVATION, "공주 월송유적")
        for preset in (
            PRESET_CONSERVATIVE,
            PRESET_BALANCED,
            PRESET_AUTOMATION,
        ):
            match = evaluate_candidate(
                surface,
                excavation,
                intersects=True,
                overlap_ratio=1.0,
                preset=preset,
            )
            self.assertEqual(match.recommended_decision, DECISION_KEEP)
            self.assertFalse(match.auto_apply)

    def test_spatial_overlap_alone_never_creates_candidate(self):
        designated = record("d1", ROLE_LOCAL_DESIGNATED, "아차산성")
        distribution = record("m1", ROLE_DISTRIBUTION, "용마산 보루")
        self.assertIsNone(evaluate_candidate(
            designated,
            distribution,
            intersects=True,
            overlap_ratio=1.0,
        ))

    def test_conservative_preset_does_not_auto_apply_exact_match(self):
        designated = record("d1", ROLE_LOCAL_DESIGNATED, "봉업사지")
        distribution = record("m1", ROLE_DISTRIBUTION, "봉업사지")
        match = evaluate_candidate(
            designated,
            distribution,
            intersects=True,
            overlap_ratio=1.0,
            preset=PRESET_CONSERVATIVE,
        )
        self.assertFalse(match.auto_apply)


class DuplicateFingerprintTests(unittest.TestCase):
    def test_order_independent_selected_content_fingerprint(self):
        first = [
            {"code": "A", "name": "유적1", "geometry_key": "g1"},
            {"code": "B", "name": "유적2", "geometry_key": "g2"},
        ]
        second = list(reversed(first))
        self.assertEqual(
            selected_content_fingerprint(first),
            selected_content_fingerprint(second),
        )


if __name__ == "__main__":
    unittest.main()
