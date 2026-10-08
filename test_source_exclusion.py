import unittest

from source_exclusion import (
    default_enabled_rules,
    exclusion_reason,
    load_exclusion_rules,
    outcome_field_candidates,
    prepare_layer_plan,
    resolve_enabled_rules,
    rule_definitions,
)


RULES = load_exclusion_rules()
SURVEY_FIELDS = ["CODE", "사업명", "유적유무", "보고서명"]
REGISTER_FIELDS = ["CODE", "명칭", "시대", "유적대분류", "유적중분류"]


class OutcomeRuleTests(unittest.TestCase):
    def plan(self, distinct=3, enabled=("no_remains",)):
        return prepare_layer_plan(
            SURVEY_FIELDS,
            enabled,
            distinct_value_counts={"유적유무": distinct},
            rules=RULES,
        )

    def test_negative_outcome_is_excluded_and_positive_kept(self):
        plan = self.plan()
        self.assertEqual(plan.outcome_field, "유적유무")
        self.assertEqual(
            exclusion_reason(plan, {"유적유무": "유적없음"}), "no_remains"
        )
        self.assertEqual(
            exclusion_reason(plan, {"유적유무": "유적 없음 (추가 확인 필요)"}),
            "no_remains",
        )
        self.assertIsNone(exclusion_reason(plan, {"유적유무": "유적있음"}))
        self.assertIsNone(exclusion_reason(plan, {"유적유무": None}))

    def test_free_text_field_is_never_an_outcome_field(self):
        plan = self.plan(distinct=500)
        self.assertEqual(plan.outcome_field, "")
        self.assertIsNone(exclusion_reason(plan, {"유적유무": "없음"}))

    def test_disabled_rule_does_nothing(self):
        plan = self.plan(enabled=[])
        self.assertFalse(plan.is_active)
        self.assertIsNone(exclusion_reason(plan, {"유적유무": "유적없음"}))

    def test_outcome_candidates_are_named_fields_only(self):
        self.assertEqual(
            outcome_field_candidates(SURVEY_FIELDS, RULES), ["유적유무"]
        )
        self.assertEqual(
            outcome_field_candidates(["Result", "Name"], RULES), ["Result"]
        )

    def test_english_outcome_vocabulary(self):
        plan = prepare_layer_plan(
            ["Name", "Result"],
            ["no_remains"],
            distinct_value_counts={"Result": 2},
            rules=RULES,
        )
        self.assertEqual(
            exclusion_reason(plan, {"Result": "No remains"}), "no_remains"
        )
        self.assertIsNone(
            exclusion_reason(plan, {"Result": "Remains present"})
        )


class ClassRuleTests(unittest.TestCase):
    def plan(self, enabled):
        return prepare_layer_plan(REGISTER_FIELDS, enabled, rules=RULES)

    def test_enumerated_movable_and_intangible_records(self):
        plan = self.plan(["movable", "intangible"])
        self.assertEqual(
            exclusion_reason(plan, {
                "유적대분류": "0)동산문화유산", "유적중분류": "0)회화",
            }),
            "movable",
        )
        self.assertEqual(
            exclusion_reason(plan, {
                "유적대분류": "0)의식", "유적중분류": "",
            }),
            "intangible",
        )

    def test_mixed_record_is_kept(self):
        plan = self.plan(["natural"])
        self.assertIsNone(exclusion_reason(plan, {
            "유적대분류": "0)유적,1)식물",
            "유적중분류": "0)유물산포지,1)노거수",
        }))
        self.assertEqual(
            exclusion_reason(plan, {
                "유적대분류": "0)식물", "유적중분류": "0)노거수",
            }),
            "natural",
        )

    def test_archaeological_record_is_kept(self):
        plan = self.plan(["movable", "intangible", "natural"])
        self.assertIsNone(exclusion_reason(plan, {
            "유적대분류": "0)유적", "유적중분류": "0)무덤유적",
        }))

    def test_report_practice_defaults(self):
        # Published nearby-site maps keep "no remains" investigations and
        # non-archaeological heritage, but never list intangible or
        # location-less movable heritage.
        defaults = default_enabled_rules(RULES)
        self.assertNotIn("natural", defaults)
        self.assertNotIn("no_remains", defaults)
        self.assertIn("intangible", defaults)
        self.assertIn("movable", defaults)

    def test_possible_distribution_area_is_not_a_negative_outcome(self):
        plan = prepare_layer_plan(
            SURVEY_FIELDS,
            ["no_remains"],
            distinct_value_counts={"유적유무": 3},
            rules=RULES,
        )
        self.assertIsNone(exclusion_reason(
            plan, {"유적유무": "유적없음 유적분포가능지"}
        ))


class RuleSelectionTests(unittest.TestCase):
    def test_unreviewed_rules_fall_back_to_defaults(self):
        self.assertEqual(
            resolve_enabled_rules(None, RULES),
            default_enabled_rules(RULES),
        )

    def test_reviewed_choice_overrides_default(self):
        enabled = resolve_enabled_rules(
            {"no_remains": True, "natural": True, "movable": False}, RULES
        )
        self.assertIn("no_remains", enabled)
        self.assertIn("natural", enabled)
        self.assertNotIn("movable", enabled)
        self.assertIn("intangible", enabled)

    def test_every_rule_has_bilingual_label(self):
        for rule_id, label_ko, label_en, _default in rule_definitions(RULES):
            self.assertTrue(rule_id and label_ko and label_en)


if __name__ == "__main__":
    unittest.main()
