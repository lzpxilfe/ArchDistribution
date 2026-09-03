import unittest

from attribute_classification import (
    ERA_FIELD_KEYWORDS,
    NAME_FIELD_KEYWORDS,
    TYPE_FIELD_KEYWORDS,
    category_values,
    find_semantic_field,
    infer_categories_from_name,
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


if __name__ == "__main__":
    unittest.main()
