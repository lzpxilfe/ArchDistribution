import unittest

from attribute_classification import (
    ERA_FIELD_KEYWORDS,
    NAME_FIELD_KEYWORDS,
    TYPE_FIELD_KEYWORDS,
    build_reference_name_index,
    category_values,
    find_semantic_field,
    infer_categories_from_name,
    reference_info_for_name,
    should_exclude_categories,
)


class AttributeClassificationTests(unittest.TestCase):
    def test_finds_supplier_period_and_type_fields(self):
        fields = ["OBJECTID", "유적명", "시대_분류", "유적유형"]
        self.assertEqual(find_semantic_field(fields, NAME_FIELD_KEYWORDS), "유적명")
        self.assertEqual(find_semantic_field(fields, ERA_FIELD_KEYWORDS), "시대_분류")
        self.assertEqual(find_semantic_field(fields, TYPE_FIELD_KEYWORDS), "유적유형")

    def test_splits_categories_and_removes_placeholders(self):
        self.assertEqual(
            category_values("청동기/삼국; 미상", ignored=("시대미상",)),
            {"청동기", "삼국"},
        )

    def test_infers_visible_terms_from_site_name(self):
        self.assertEqual(
            infer_categories_from_name("청동기 유물산포지"),
            ({"청동기"}, {"유물산포지"}),
        )

    def test_unchecked_source_category_is_excluded(self):
        selection = {
            "available": {"ERA:청동기", "ERA:삼국", "TYPE:고분"},
            "allowed": {"ERA:삼국", "TYPE:고분"},
        }
        self.assertTrue(
            should_exclude_categories({"청동기"}, {"고분"}, selection)
        )
        self.assertFalse(
            should_exclude_categories({"삼국"}, {"고분"}, selection)
        )

    def test_unknown_category_is_kept(self):
        selection = {
            "available": {"ERA:삼국"},
            "allowed": {"ERA:삼국"},
        }
        self.assertFalse(
            should_exclude_categories({"고려"}, set(), selection)
        )

    def test_reference_lookup_accepts_spacing_without_guessing(self):
        reference = {
            "공주정지산유적": {"e": "삼국시대", "t": "주거유적"},
        }
        index = build_reference_name_index(reference)

        self.assertEqual(
            reference_info_for_name(reference, index, "공주 정지산 유적"),
            reference["공주정지산유적"],
        )

    def test_reference_lookup_rejects_ambiguous_normalized_name(self):
        reference = {
            "가 나": {"e": "삼국시대"},
            "가나": {"e": "조선시대"},
        }
        index = build_reference_name_index(reference)

        self.assertIsNone(reference_info_for_name(reference, index, "가  나"))
        self.assertEqual(
            reference_info_for_name(reference, index, "가나"),
            {"e": "조선시대"},
        )


if __name__ == "__main__":
    unittest.main()
