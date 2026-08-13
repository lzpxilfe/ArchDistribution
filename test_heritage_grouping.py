import unittest

from heritage_grouping import (
    resolve_heritage_group,
    resolve_heritage_identity,
    strip_trailing_area_designator,
)


class HeritageGroupingTests(unittest.TestCase):
    def test_same_project_roman_numeral_areas_share_one_group(self):
        project = "공주 월송 국민임대주택단지 조성사업지구 내 유적"
        names = [
            f"{project} I 지역",
            f"{project} II-1지역",
            f"{project} II-2지역",
            f"{project} II-3지역",
        ]

        decisions = [
            resolve_heritage_group(project, name, fallback_key=f"source:{index}")
            for index, name in enumerate(names)
        ]

        self.assertEqual({item["key"] for item in decisions}, {
            "project:공주월송국민임대주택단지조성사업지구내유적"
        })
        self.assertEqual({item["display_name"] for item in decisions}, {project})
        self.assertEqual({item["basis"] for item in decisions}, {"project"})

    def test_compound_area_suffix_is_removed(self):
        project = "공주 월송 국민임대주택단지 조성사업지구 내 유적"
        decision = resolve_heritage_group(
            project,
            f"{project} Ⅱ-1,2,3지역",
            fallback_key="source:compound",
        )

        self.assertEqual(decision["basis"], "project")
        self.assertEqual(decision["display_name"], project)

    def test_provided_sample_uses_project_as_representative_name(self):
        project = "공주 신금택지개발지구내 유적"
        decision = resolve_heritage_group(
            project,
            "공주 신금택지개발지구내 유적 1지역",
            fallback_key="source:sample",
        )

        self.assertEqual(decision["key"], "project:공주신금택지개발지구내유적")
        self.assertEqual(decision["display_name"], project)

    def test_distinct_sites_in_one_project_are_merged(self):
        project = "공주 도로개설사업 발굴조사"
        site_a = resolve_heritage_group(
            project, "공주 A유적", fallback_key="source:a"
        )
        site_b = resolve_heritage_group(
            project, "공주 B유적", fallback_key="source:b"
        )

        self.assertEqual(site_a["key"], site_b["key"])
        self.assertEqual(site_a["display_name"], project)
        self.assertEqual(site_a["basis"], "project")
        self.assertEqual(site_b["basis"], "project")

    def test_identity_separates_site_entity_from_shared_project_number(self):
        project = "공주 도로개설사업 발굴조사"
        site_a = resolve_heritage_identity(
            project, "공주 A유적", fallback_key="source:a"
        )
        site_b = resolve_heritage_identity(
            project, "공주 B유적", fallback_key="source:b"
        )

        self.assertEqual(site_a["investigation_key"], site_b["investigation_key"])
        self.assertEqual(site_a["number_key"], site_b["number_key"])
        self.assertNotEqual(site_a["site_entity_key"], site_b["site_entity_key"])
        self.assertNotEqual(
            site_a["geometry_group_key"], site_b["geometry_group_key"]
        )
        self.assertEqual(site_a["entity_key"], site_a["site_entity_key"])

    def test_identity_does_not_premerge_explicit_areas(self):
        project = "공주 월송 개발사업"
        first = resolve_heritage_identity(
            project,
            "공주 월송유적 I지역",
            fallback_key="source:area-1",
        )
        second = resolve_heritage_identity(
            project,
            "공주 월송유적 II-1지역",
            fallback_key="source:area-2",
        )

        self.assertNotEqual(first["site_entity_key"], second["site_entity_key"])
        self.assertNotEqual(
            first["geometry_group_key"], second["geometry_group_key"]
        )
        self.assertEqual(first["number_key"], second["number_key"])

    def test_identity_keeps_action_geometries_separate(self):
        trial = resolve_heritage_identity(
            "공주 월송 개발사업",
            "공주 월송유적",
            fallback_key="source:trial",
            preservation_action="시굴조사",
        )
        excavation = resolve_heritage_identity(
            "공주 월송 개발사업",
            "공주 월송유적",
            fallback_key="source:excavation",
            preservation_action="정밀발굴조사",
        )

        self.assertEqual(trial["number_key"], excavation["number_key"])
        self.assertNotEqual(
            trial["site_entity_key"], excavation["site_entity_key"]
        )
        self.assertNotEqual(
            trial["geometry_group_key"], excavation["geometry_group_key"]
        )

    def test_different_excavation_projects_remain_separate(self):
        first = resolve_heritage_group(
            "공주 A지구 발굴조사",
            "공주 월송유적",
            fallback_key="source:a",
        )
        second = resolve_heritage_group(
            "공주 B지구 발굴조사",
            "공주 월송유적",
            fallback_key="source:b",
        )

        self.assertNotEqual(first["number_key"], second["number_key"])

    def test_area_suffix_does_not_group_without_project_field(self):
        first = resolve_heritage_group(
            None, "공주 월송유적 I지역", fallback_key="source:a"
        )
        second = resolve_heritage_group(
            "", "공주 월송유적 II-2지역", fallback_key="source:b"
        )

        self.assertNotEqual(first["key"], second["key"])
        self.assertNotEqual(
            first["site_entity_key"], second["site_entity_key"]
        )
        self.assertEqual(first["display_name"], "공주 월송유적")

    def test_feature_numbers_are_not_treated_as_area_suffixes(self):
        name, stripped = strip_trailing_area_designator("공주 송산리 고분군 1호")

        self.assertFalse(stripped)
        self.assertEqual(name, "공주 송산리 고분군 1호")

    def test_project_name_takes_precedence_over_national_heritage_name(self):
        project = "공주 정비사업"
        first = resolve_heritage_group(
            project, "I지역", "공주 A사지", fallback_key="source:a"
        )
        second = resolve_heritage_group(
            project, "II지역", "공주 B사지", fallback_key="source:b"
        )

        self.assertEqual(first["key"], second["key"])
        self.assertEqual(first["display_name"], project)
        self.assertEqual(first["basis"], "project")
        self.assertEqual(second["basis"], "project")

    def test_national_heritage_names_stay_separate_without_project_name(self):
        first = resolve_heritage_group(
            None, "I지역", "공주 A사지", fallback_key="source:a"
        )
        second = resolve_heritage_group(
            None, "II지역", "공주 B사지", fallback_key="source:b"
        )

        self.assertNotEqual(first["key"], second["key"])
        self.assertEqual(first["basis"], "heritage")
        self.assertEqual(second["basis"], "heritage")

    def test_unnamed_records_use_unique_fallbacks(self):
        first = resolve_heritage_group(None, None, fallback_key="layer:1")
        second = resolve_heritage_group("N/A", "<NULL>", fallback_key="layer:2")

        self.assertNotEqual(first["key"], second["key"])
        self.assertEqual(first["display_name"], "N/A")

    def test_preservation_scope_shares_number_but_not_geometry_key(self):
        site = "공주 반죽동 대통사 추정지"
        excavation = resolve_heritage_group(
            None,
            site,
            fallback_key="source:excavation",
            preservation_action="정밀발굴조사",
            preservation_number_scope="supplier-site:42",
        )
        trial = resolve_heritage_group(
            None,
            site,
            fallback_key="source:trial",
            preservation_action="시굴조사",
            preservation_number_scope="supplier-site:42",
        )

        self.assertEqual(excavation["number_key"], trial["number_key"])
        self.assertNotEqual(excavation["dissolve_key"], trial["dissolve_key"])

    def test_same_action_areas_keep_source_geometry_keys(self):
        first = resolve_heritage_group(
            None,
            "공주 월송유적 I지역",
            fallback_key="source:first",
            preservation_action="시굴조사",
            preservation_number_scope="supplier-site:42",
        )
        second = resolve_heritage_group(
            None,
            "공주 월송유적 II지역",
            fallback_key="source:second",
            preservation_action="시굴조사",
            preservation_number_scope="supplier-site:42",
        )

        self.assertEqual(first["number_key"], second["number_key"])
        self.assertNotEqual(first["dissolve_key"], second["dissolve_key"])

    def test_no_project_homonyms_have_unique_initial_keys(self):
        first = resolve_heritage_identity(
            None, "봉업사지", fallback_key="source:west"
        )
        second = resolve_heritage_identity(
            None, "봉업사지", fallback_key="source:east"
        )

        self.assertNotEqual(first["number_key"], second["number_key"])
        self.assertNotEqual(
            first["site_entity_key"], second["site_entity_key"]
        )
        self.assertNotEqual(
            first["geometry_group_key"], second["geometry_group_key"]
        )

    def test_missing_fallback_is_rejected_instead_of_name_grouping(self):
        with self.assertRaisesRegex(ValueError, "fallback_key"):
            resolve_heritage_identity(None, "봉업사지")


if __name__ == "__main__":
    unittest.main()
