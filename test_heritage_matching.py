import re
import unittest

from heritage_matching import (
    DEFAULT_MATCHING_RULES_PATH,
    DECISION_KEEP,
    DECISION_LINK,
    DECISION_MERGE,
    PRESET_AUTOMATION,
    PRESET_BALANCED,
    PRESET_CONSERVATIVE,
    RELATION_INVESTIGATION_SITE,
    RELATION_PARENT_CHILD,
    RELATION_SAME_ENTITY,
    ROLE_DISTRIBUTION,
    ROLE_EXCAVATION,
    ROLE_LOCAL_DESIGNATED,
    ROLE_NATIONAL_DESIGNATED,
    ROLE_NATIONAL_REGISTERED,
    ROLE_OTHER,
    ROLE_PROTECTION_ZONE,
    ROLE_SURFACE,
    RULESET_SHA256,
    RULESET_VERSION,
    addresses_match,
    detect_source_role,
    evaluate_candidate,
    excavation_area_review_family,
    is_generic_name,
    load_matching_rules,
    matching_rules_metadata,
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
        self.assertEqual(match.relation_type, RELATION_PARENT_CHILD)

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
        self.assertEqual(match.relation_type, RELATION_INVESTIGATION_SITE)

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

    def test_exact_entity_match_records_same_entity_relation(self):
        designated = record("d1", ROLE_LOCAL_DESIGNATED, "봉업사지")
        distribution = record("m1", ROLE_DISTRIBUTION, "봉업사지")
        match = evaluate_candidate(
            designated,
            distribution,
            intersects=True,
            overlap_ratio=0.75,
        )

        self.assertEqual(match.relation_type, RELATION_SAME_ENTITY)

    def test_generic_exact_name_is_review_only_in_every_preset(self):
        designated = record("d1", ROLE_LOCAL_DESIGNATED, "유적")
        distribution = record("m1", ROLE_DISTRIBUTION, "유적")
        self.assertTrue(is_generic_name(" 유적 "))

        for preset in (
            PRESET_CONSERVATIVE,
            PRESET_BALANCED,
            PRESET_AUTOMATION,
        ):
            match = evaluate_candidate(
                designated,
                distribution,
                intersects=True,
                overlap_ratio=1.0,
                preset=preset,
            )
            self.assertEqual(match.rule, "exact_generic_name_and_overlap")
            self.assertFalse(match.auto_apply)

    def test_non_polygon_pair_never_auto_applies(self):
        designated = record("d1", ROLE_LOCAL_DESIGNATED, "봉업사지")
        distribution = record("m1", ROLE_DISTRIBUTION, "봉업사지")
        match = evaluate_candidate(
            designated,
            distribution,
            intersects=True,
            overlap_ratio=1.0,
            preset=PRESET_AUTOMATION,
            geometry_pair="polygon_point",
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.geometry_pair, "polygon_point")
        self.assertFalse(match.auto_apply)

    def test_candidate_exposes_research_geometry_metrics(self):
        designated = record("d1", ROLE_LOCAL_DESIGNATED, "봉업사지")
        distribution = record("m1", ROLE_DISTRIBUTION, "봉업사지")
        match = evaluate_candidate(
            designated,
            distribution,
            intersects=True,
            overlap_ratio=0.8,
            coverage_left=0.4,
            coverage_right=0.8,
            iou=0.36,
            area_ratio=0.5,
            centroid_distance=12.3456,
            boundary_distance=0.0,
            geometry_pair="Polygon/Polygon",
        )

        metrics = match.as_dict()
        self.assertEqual(metrics["coverage_left"], 0.4)
        self.assertEqual(metrics["coverage_right"], 0.8)
        self.assertEqual(metrics["iou"], 0.36)
        self.assertEqual(metrics["area_ratio"], 0.5)
        self.assertEqual(metrics["centroid_distance"], 12.346)
        self.assertEqual(metrics["boundary_distance"], 0.0)
        self.assertEqual(metrics["geometry_pair"], "polygon_polygon")

    def test_excavation_area_suffix_pair_is_review_only_in_all_presets(self):
        first = record(
            "e1",
            ROLE_EXCAVATION,
            "공주 월송유적 I지역",
            "공주 월송 개발사업",
        )
        second = record(
            "e2",
            ROLE_EXCAVATION,
            "공주 월송유적 II-1지역",
            "공주 월송 개발사업",
        )

        self.assertEqual(
            excavation_area_review_family(first, second),
            "공주월송유적",
        )
        for preset in (
            PRESET_CONSERVATIVE,
            PRESET_BALANCED,
            PRESET_AUTOMATION,
        ):
            match = evaluate_candidate(
                first,
                second,
                intersects=False,
                overlap_ratio=0.0,
                distance=20.0,
                preset=preset,
            )
            self.assertIsNotNone(match)
            self.assertEqual(
                match.rule,
                "excavation_area_suffix_spatial_review",
            )
            self.assertEqual(match.relation_type, RELATION_SAME_ENTITY)
            self.assertEqual(match.recommended_decision, DECISION_MERGE)
            self.assertFalse(match.auto_apply)

    def test_distant_excavation_area_homonyms_are_not_candidates(self):
        first = record(
            "e1", ROLE_EXCAVATION, "공주 월송유적 I지역"
        )
        second = record(
            "e2", ROLE_EXCAVATION, "공주 월송유적 II지역"
        )

        self.assertIsNone(evaluate_candidate(
            first,
            second,
            intersects=False,
            overlap_ratio=0.0,
            distance=500.0,
        ))

    def test_plain_excavation_homonyms_are_not_area_candidates(self):
        first = record("e1", ROLE_EXCAVATION, "봉업사지")
        second = record("e2", ROLE_EXCAVATION, "봉업사지")

        self.assertEqual(excavation_area_review_family(first, second), "")
        self.assertIsNone(evaluate_candidate(
            first,
            second,
            intersects=True,
            overlap_ratio=1.0,
        ))

    def test_area_suffixes_from_different_projects_are_not_candidates(self):
        first = record(
            "e1", ROLE_EXCAVATION, "공주 월송유적 I지역", "A사업"
        )
        second = record(
            "e2", ROLE_EXCAVATION, "공주 월송유적 II지역", "B사업"
        )

        self.assertEqual(excavation_area_review_family(first, second), "")
        self.assertIsNone(evaluate_candidate(
            first,
            second,
            intersects=True,
            overlap_ratio=1.0,
        ))


def metrics(cov_left, cov_right, iou, area_ratio, overlap=None):
    return {
        "intersects": True,
        "overlap_ratio": (
            max(cov_left, cov_right) if overlap is None else overlap
        ),
        "coverage_left": cov_left,
        "coverage_right": cov_right,
        "iou": iou,
        "area_ratio": area_ratio,
    }


IDENTICAL = metrics(1.0, 1.0, 1.0, 1.0)
LEFT_INSIDE = metrics(1.0, 0.01, 0.01, 0.01)


class SameRegisterRelationTests(unittest.TestCase):
    def test_spacing_variant_duplicate_is_merged_automatically(self):
        left = record("m1", ROLE_DISTRIBUTION, "가상리 고분군 3")
        right = record("m2", ROLE_DISTRIBUTION, "가상리고분군3")
        match = evaluate_candidate(left, right, **IDENTICAL)
        self.assertEqual(match.pair_kind, "distribution_parts")
        self.assertEqual(match.rule, "same_register_duplicate")
        self.assertEqual(match.relation_type, RELATION_SAME_ENTITY)
        self.assertEqual(match.recommended_decision, DECISION_MERGE)
        self.assertEqual(match.merge_mode, "union")
        self.assertTrue(match.auto_apply)

    def test_numbered_feature_joins_its_site_number(self):
        site = record("m1", ROLE_DISTRIBUTION, "가상리 고분군")
        tomb = record("m2", ROLE_DISTRIBUTION, "가상리고분군 제14호")
        match = evaluate_candidate(
            tomb, site, **metrics(1.0, 0.001, 0.001, 0.001)
        )
        self.assertEqual(match.rule, "component_within_parent")
        self.assertEqual(match.relation_type, RELATION_PARENT_CHILD)
        self.assertEqual(match.representative_uid, "m1")
        self.assertEqual(match.recommended_decision, DECISION_MERGE)
        self.assertTrue(match.auto_apply)
        self.assertFalse(evaluate_candidate(
            tomb,
            site,
            preset=PRESET_CONSERVATIVE,
            **metrics(1.0, 0.001, 0.001, 0.001),
        ).auto_apply)

    def test_numbered_siblings_are_never_candidates(self):
        first = record("m1", ROLE_DISTRIBUTION, "가상리 고분군 제14호")
        second = record("m2", ROLE_DISTRIBUTION, "가상리 고분군 제15호")
        self.assertIsNone(evaluate_candidate(
            first, second, **metrics(0.3, 0.3, 0.18, 1.0)
        ))

    def test_specific_name_outside_its_parent_is_not_a_component(self):
        site = record("m1", ROLE_DISTRIBUTION, "가상사")
        hall = record("m2", ROLE_DISTRIBUTION, "가상사 대웅전")
        self.assertIsNone(evaluate_candidate(
            hall, site, **metrics(0.3, 0.05, 0.04, 0.2)
        ))

    def test_unrelated_records_inside_a_site_stay_separate(self):
        site = record("m1", ROLE_DISTRIBUTION, "가상리 유물산포지")
        dolmen = record("m2", ROLE_DISTRIBUTION, "나상 고인돌")
        self.assertIsNone(evaluate_candidate(dolmen, site, **LEFT_INSIDE))

    def test_different_sites_on_one_footprint_are_only_linked(self):
        for first_name, second_name in (
            ("가상리 고분군", "가상 누정"),
            ("가상리 지석묘 1호", "가상리 지석묘 2호"),
        ):
            match = evaluate_candidate(
                record("m1", ROLE_DISTRIBUTION, first_name),
                record("m2", ROLE_DISTRIBUTION, second_name),
                **IDENTICAL,
            )
            self.assertEqual(match.rule, "co_located_footprint")
            self.assertEqual(match.relation_type, "co_located")
            self.assertEqual(match.recommended_decision, DECISION_LINK)
            self.assertFalse(match.auto_apply)

    def test_legal_designations_inside_each_other_are_only_linked(self):
        parent = record("d1", ROLE_NATIONAL_DESIGNATED, "가상사")
        child = record("d2", ROLE_LOCAL_DESIGNATED, "가상사 석탑")
        match = evaluate_candidate(child, parent, **LEFT_INSIDE)
        self.assertEqual(match.pair_kind, "designated_parts")
        self.assertEqual(match.recommended_decision, DECISION_LINK)
        co_located = evaluate_candidate(
            record("d3", ROLE_LOCAL_DESIGNATED, "가상 누정"),
            record("d4", ROLE_LOCAL_DESIGNATED, "나상 정자"),
            **IDENTICAL,
        )
        self.assertEqual(co_located.recommended_decision, DECISION_LINK)

    def test_legacy_callers_without_coverage_get_no_same_register_merge(self):
        first = record("m1", ROLE_DISTRIBUTION, "가상리 고분군 제14호")
        second = record("m2", ROLE_DISTRIBUTION, "가상리 고분군")
        self.assertIsNone(evaluate_candidate(
            first, second, intersects=True, overlap_ratio=1.0
        ))


class CrossRegisterRelationTests(unittest.TestCase):
    def test_shared_stem_alone_is_linked_not_merged(self):
        # "<place> fortress" inside "<place> temple" are two sites.
        match = evaluate_candidate(
            record("m1", ROLE_DISTRIBUTION, "가상다라산성"),
            record("d1", ROLE_NATIONAL_DESIGNATED, "가상 다라사지"),
            **LEFT_INSIDE,
        )
        self.assertEqual(match.recommended_decision, DECISION_LINK)
        self.assertFalse(match.auto_apply)

    def test_stem_variants_of_one_place_stay_merge_candidates(self):
        for left, right in (
            ("가상 새각단 유물산포지", "가상 새각단 유적"),
            ("신라가상왕릉", "나상 가상왕릉"),
        ):
            match = evaluate_candidate(
                record("m1", ROLE_DISTRIBUTION, left),
                record("d1", ROLE_NATIONAL_DESIGNATED, right),
                **LEFT_INSIDE,
            )
            self.assertEqual(match.recommended_decision, DECISION_MERGE)

    def test_numbered_distribution_part_joins_designated_site(self):
        designated = record("d1", ROLE_NATIONAL_DESIGNATED, "가상리 고분군")
        tomb = record("m1", ROLE_DISTRIBUTION, "가상리고분군 제7호")
        match = evaluate_candidate(designated, tomb, **metrics(
            0.002, 1.0, 0.002, 0.002
        ))
        self.assertEqual(match.rule, "component_within_parent")
        self.assertEqual(match.representative_uid, "d1")
        self.assertEqual(match.recommended_decision, DECISION_MERGE)
        self.assertTrue(match.auto_apply)

    def test_designated_part_inside_mapped_site_keeps_its_number(self):
        temple = record("m1", ROLE_DISTRIBUTION, "가상군 가상사")
        pagoda = record("d1", ROLE_NATIONAL_DESIGNATED, "가상사 삼층석탑")
        match = evaluate_candidate(pagoda, temple, **LEFT_INSIDE)
        self.assertEqual(match.recommended_decision, DECISION_LINK)
        self.assertEqual(match.relation_type, RELATION_PARENT_CHILD)

    def test_numbered_siblings_across_registers_are_not_merged(self):
        designated = record("d1", ROLE_LOCAL_DESIGNATED, "가상 지석묘 2호")
        distribution = record("m1", ROLE_DISTRIBUTION, "가상지석묘 1호")
        self.assertIsNone(evaluate_candidate(
            designated, distribution, intersects=True, overlap_ratio=0.5
        ))

    def test_alias_and_omitted_prefix_count_as_the_same_name(self):
        designated = record("d1", ROLE_LOCAL_DESIGNATED, "가상 누정")
        distribution = record("m1", ROLE_DISTRIBUTION, "가상 누정(假想樓亭)")
        match = evaluate_candidate(designated, distribution, **IDENTICAL)
        self.assertEqual(match.rule, "normalized_name_and_overlap")
        self.assertEqual(match.relation_type, RELATION_SAME_ENTITY)
        self.assertTrue(match.auto_apply)

        prefixed = evaluate_candidate(
            record("d2", ROLE_LOCAL_DESIGNATED, "가상시 나상대"),
            record("m2", ROLE_DISTRIBUTION, "나상대"),
            **metrics(0.9, 0.95, 0.86, 0.95),
        )
        self.assertEqual(prefixed.rule, "affix_omitted_name_and_overlap")
        self.assertTrue(prefixed.auto_apply)

    def test_candidate_reports_name_and_geometry_relation(self):
        designated = record("d1", ROLE_LOCAL_DESIGNATED, "가상사지")
        distribution = record("m1", ROLE_DISTRIBUTION, "가상사지")
        match = evaluate_candidate(designated, distribution, **IDENTICAL)
        self.assertEqual(match.name_relation, "equal")
        self.assertEqual(match.geometry_relation, "identical")


class AddressSafetyTests(unittest.TestCase):
    def test_address_prefix_can_be_omitted(self):
        self.assertTrue(addresses_match(
            "공주시 가상동 1-1",
            "충청남도 공주시 가상동 1-1",
        ))

    def test_village_level_address_is_not_identity_evidence(self):
        self.assertTrue(addresses_match("가상군 가상리", "가상리"))
        self.assertFalse(addresses_match(
            "가상군 가상리", "가상리", require_parcel=True
        ))
        self.assertTrue(addresses_match(
            "가상군 가상리 12", "가상리 12", require_parcel=True
        ))
        first = record("m1", ROLE_DISTRIBUTION, "가상 산포지",
                       address="가상군 가상리")
        second = record("s1", ROLE_LOCAL_DESIGNATED, "나상 누정",
                        address="가상리")
        self.assertIsNone(evaluate_candidate(
            first, second, intersects=True, overlap_ratio=0.9
        ))

    def test_numeric_parcel_substring_is_not_a_match(self):
        self.assertFalse(addresses_match(
            "공주시 신관동 24-17",
            "공주시 가상동 1-1",
        ))

        designated = record(
            "d1",
            ROLE_LOCAL_DESIGNATED,
            "서로 다른 이름 A",
            address="공주시 신관동 24-17",
        )
        distribution = record(
            "m1",
            ROLE_DISTRIBUTION,
            "무관한 이름 B",
            address="공주시 가상동 1-1",
        )
        self.assertIsNone(evaluate_candidate(
            designated,
            distribution,
            intersects=True,
            overlap_ratio=1.0,
        ))


class MatchingRuleSetTests(unittest.TestCase):
    def test_default_rules_are_versioned_and_hashed(self):
        rules = load_matching_rules()
        metadata = matching_rules_metadata()

        self.assertEqual(rules["ruleset_version"], RULESET_VERSION)
        self.assertEqual(metadata["sha256"], RULESET_SHA256)
        self.assertEqual(metadata["filename"], DEFAULT_MATCHING_RULES_PATH.name)
        self.assertRegex(RULESET_SHA256, re.compile(r"^[0-9a-f]{64}$"))

    def test_rule_load_returns_copy(self):
        first = load_matching_rules()
        first["thresholds"]["review_overlap_ratio"] = -1
        second = load_matching_rules()

        self.assertEqual(second["thresholds"]["review_overlap_ratio"], 0.25)


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

    def test_full_source_fingerprint_is_role_aware(self):
        designated = [{
            "role": "national_designated",
            "content_fingerprint": "same-source-content",
        }]
        distribution = [{
            "role": "distribution_map",
            "content_fingerprint": "same-source-content",
        }]

        self.assertNotEqual(
            selected_content_fingerprint(designated),
            selected_content_fingerprint(distribution),
        )


if __name__ == "__main__":
    unittest.main()
