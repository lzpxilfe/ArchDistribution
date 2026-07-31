import unittest

from preservation_actions import (
    PRESERVATION_ACTION_STYLES,
    normalize_preservation_action,
    preservation_action_style,
    recognized_preservation_actions,
)


class PreservationActionTests(unittest.TestCase):
    def test_all_four_official_actions_have_exact_legend_colors(self):
        expected = {
            "현상보존": "#B9F8FF",
            "정밀발굴조사": "#E7D6FF",
            "시굴조사": "#F5FFD2",
            "표본조사": "#FFDFDF",
        }

        self.assertEqual(
            {name: style["fill_color"] for name, style in PRESERVATION_ACTION_STYLES.items()},
            expected,
        )
        self.assertEqual(
            {style["outline_color"] for style in PRESERVATION_ACTION_STYLES.values()},
            {"#FF0000"},
        )

    def test_common_short_forms_are_normalized(self):
        self.assertEqual(normalize_preservation_action("정밀 발굴"), "정밀발굴조사")
        self.assertEqual(normalize_preservation_action("시굴"), "시굴조사")
        self.assertEqual(normalize_preservation_action(" 표본조사 "), "표본조사")

    def test_unknown_action_is_preserved_but_has_no_forced_style(self):
        self.assertEqual(normalize_preservation_action("참관조사"), "참관조사")
        self.assertIsNone(preservation_action_style("참관조사"))

    def test_detection_requires_an_official_action_value(self):
        self.assertEqual(
            recognized_preservation_actions(["승인", "검토중"]),
            set(),
        )
        self.assertEqual(
            recognized_preservation_actions(["승인", "시굴 조사"]),
            {"시굴조사"},
        )


if __name__ == "__main__":
    unittest.main()
