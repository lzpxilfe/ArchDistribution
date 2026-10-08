import unittest

from heritage_matching import load_matching_rules
from heritage_relations import (
    GEOMETRY_APART,
    GEOMETRY_IDENTICAL,
    GEOMETRY_LEFT_WITHIN,
    GEOMETRY_NEAR,
    GEOMETRY_OVERLAP,
    GEOMETRY_RIGHT_WITHIN,
    GEOMETRY_SIMILAR,
    GEOMETRY_UNKNOWN,
    NAME_AFFIX_OMITTED,
    NAME_ALIAS,
    NAME_DESIGNATOR_CONFLICT,
    NAME_EQUAL,
    NAME_LEFT_SPECIFIC,
    NAME_RIGHT_SPECIFIC,
    NAME_SIBLING,
    NAME_UNRELATED,
    geometry_relation,
    identity_name_key,
    name_relation,
    parse_name,
)


RULES = load_matching_rules()


def relation(left, right):
    return name_relation(left, right, RULES)


class NameNormalisationTests(unittest.TestCase):
    def test_spacing_width_and_punctuation_do_not_change_identity(self):
        self.assertEqual(
            identity_name_key("가상리  고분군 3", RULES),
            identity_name_key("가상리고분군3", RULES),
        )
        self.assertEqual(
            identity_name_key("가상리·나상리 유적", RULES),
            identity_name_key("가상리 나상리유적", RULES),
        )

    def test_roman_and_arabic_numbers_are_equal(self):
        self.assertEqual(relation("가상리 고분군Ⅱ", "가상리 고분군 2"), NAME_EQUAL)
        self.assertEqual(relation("Villa III", "Villa 3"), NAME_EQUAL)

    def test_section_letters_are_not_read_as_roman_numbers(self):
        parsed = parse_name("가상 유적 C지구", RULES)
        self.assertEqual(parsed.designators, ("c",))

    def test_bracketed_alias_matches_either_spelling(self):
        self.assertEqual(relation("가상 누정", "가상 누정(假想樓亭)"), NAME_EQUAL)
        self.assertEqual(
            relation("가상 유물산포지 6(가상 고분군 3)", "가상 고분군3"),
            NAME_ALIAS,
        )

    def test_bracketed_designator_is_kept(self):
        self.assertEqual(
            relation("가상 유적(A지구)", "가상 유적(B지구)"),
            NAME_DESIGNATOR_CONFLICT,
        )

    def test_quotes_and_ordinal_prefix_are_ignored(self):
        self.assertEqual(
            relation("가상 지석묘 ‘가’군", "가상 지석묘 가군"),
            NAME_EQUAL,
        )
        self.assertEqual(
            relation("가상 고분군 제12호", "가상 고분군 12호"),
            NAME_EQUAL,
        )

    def test_configured_equivalent_suffix(self):
        self.assertEqual(relation("가상산성 터", "가상산성지"), NAME_EQUAL)
        self.assertEqual(relation("가상 유적지", "가상 유적"), NAME_EQUAL)


class NameRelationTests(unittest.TestCase):
    def test_omitted_leading_qualifier(self):
        self.assertEqual(relation("가상시 월영대", "월영대"), NAME_AFFIX_OMITTED)
        self.assertEqual(
            relation("가상군 나상리 고분군 1", "나상리 고분군Ⅰ"),
            NAME_AFFIX_OMITTED,
        )

    def test_numbered_feature_is_more_specific_than_its_site(self):
        self.assertEqual(
            relation("가상리 고분군 제14호", "가상리 고분군"),
            NAME_LEFT_SPECIFIC,
        )
        self.assertEqual(
            relation("가상사", "가상시 가상사 대웅전"),
            NAME_RIGHT_SPECIFIC,
        )

    def test_different_numbers_are_siblings_not_one_entity(self):
        self.assertEqual(
            relation("가상리 고분군 제14호", "가상리 고분군 제15호"),
            NAME_DESIGNATOR_CONFLICT,
        )
        self.assertEqual(
            relation("가상 지석묘 2호", "가상지석묘 1호"),
            NAME_DESIGNATOR_CONFLICT,
        )
        self.assertEqual(
            relation("가상군 나상리 고분군Ⅰ", "나상리 고분군 2"),
            NAME_DESIGNATOR_CONFLICT,
        )
        self.assertEqual(relation("Site A", "Site B"), NAME_DESIGNATOR_CONFLICT)
        self.assertEqual(
            relation("가상군 나상동 유물산포지 4(도로 부지 내)", "나상동 유물산포지1-1"),
            NAME_DESIGNATOR_CONFLICT,
        )
        self.assertEqual(
            parse_name("나상동 유물산포지1-1", RULES).designators, ("1-1",)
        )

    def test_shared_stem_with_different_endings_is_sibling(self):
        self.assertEqual(
            relation("가상시 나상동 가상사 법당", "가상시 나상동 가상사 요사"),
            NAME_SIBLING,
        )

    def test_unrelated_names(self):
        self.assertEqual(relation("가상산성", "나상리 비석"), NAME_UNRELATED)
        self.assertEqual(relation("", "가상산성"), NAME_UNRELATED)

    def test_generic_names_never_create_containment(self):
        generic = {identity_name_key("고분군", RULES)}
        self.assertEqual(
            name_relation("가상리 고분군", "고분군", RULES, generic),
            NAME_UNRELATED,
        )

    def test_lexicon_is_data_not_code(self):
        bare = {"name_lexicon": {}}
        # Without configured unit words only bare numbers are designators.
        self.assertEqual(
            name_relation("Mound 12", "Mound 13", bare),
            NAME_DESIGNATOR_CONFLICT,
        )
        self.assertEqual(
            name_relation("가상 고분군 가군", "가상 고분군 나군", bare),
            NAME_SIBLING,
        )


class GeometryRelationTests(unittest.TestCase):
    def test_identical_similar_and_within(self):
        self.assertEqual(geometry_relation(
            intersects=True, overlap_ratio=1.0, coverage_left=0.99,
            coverage_right=0.98, iou=0.97, area_ratio=0.99,
        ), GEOMETRY_IDENTICAL)
        self.assertEqual(geometry_relation(
            intersects=True, overlap_ratio=0.7, coverage_left=0.7,
            coverage_right=0.6, iou=0.47, area_ratio=0.8,
        ), GEOMETRY_SIMILAR)
        self.assertEqual(geometry_relation(
            intersects=True, overlap_ratio=1.0, coverage_left=1.0,
            coverage_right=0.02, iou=0.02, area_ratio=0.02,
        ), GEOMETRY_LEFT_WITHIN)
        self.assertEqual(geometry_relation(
            intersects=True, overlap_ratio=0.95, coverage_left=0.1,
            coverage_right=0.95, iou=0.1, area_ratio=0.1,
        ), GEOMETRY_RIGHT_WITHIN)

    def test_partial_near_apart_and_unknown(self):
        self.assertEqual(geometry_relation(
            intersects=True, overlap_ratio=0.2, coverage_left=0.2,
            coverage_right=0.1, iou=0.07, area_ratio=0.5,
        ), GEOMETRY_OVERLAP)
        self.assertEqual(
            geometry_relation(intersects=False, distance=30.0),
            GEOMETRY_NEAR,
        )
        self.assertEqual(
            geometry_relation(intersects=False, distance=300.0),
            GEOMETRY_APART,
        )
        self.assertEqual(
            geometry_relation(intersects=True, overlap_ratio=0.8),
            GEOMETRY_UNKNOWN,
        )
        # Touching footprints share no area and are neighbours.
        self.assertEqual(geometry_relation(
            intersects=True, overlap_ratio=1.0, coverage_left=0.0,
            coverage_right=0.0, iou=0.0, area_ratio=0.0,
        ), GEOMETRY_NEAR)


if __name__ == "__main__":
    unittest.main()
