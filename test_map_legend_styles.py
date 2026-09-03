import unittest

from map_legend_styles import (
    CHANGE_ZONE_STYLES,
    DESIGNATION_LEGEND_STYLES,
    change_zone_style,
    normalize_change_zone_code,
)


class MapLegendStyleTests(unittest.TestCase):
    def test_current_change_primary_zone_colours_match_supplied_legend(self):
        expected = {
            "1": "#CD5400",
            "2": "#CA03F0",
            "3": "#0A04D0",
            "4": "#942858",
            "5": "#20BD03",
            "6": "#C50800",
            "7": "#08D98F",
            "8": "#E6DE00",
            "other": "#634631",
        }
        self.assertEqual(
            {key: CHANGE_ZONE_STYLES[key]["fill"] for key in expected},
            expected,
        )

    def test_current_change_subzones_accept_common_korean_labels(self):
        self.assertEqual(normalize_change_zone_code("제2-1구역"), "2-1")
        self.assertEqual(normalize_change_zone_code("3_4 구역"), "3-4")
        self.assertEqual(normalize_change_zone_code("그외구역"), "other")
        self.assertEqual(change_zone_style("2-6구역"), {
            "fill": "#B5057D", "stroke": "#BAB645", "width": 0.8,
        })
        self.assertEqual(change_zone_style("3-3구역"), {
            "fill": "#5A01FF", "stroke": "#66FF99", "width": 0.8,
        })

    def test_designation_and_protection_legend_categories_are_explicit(self):
        self.assertEqual(
            DESIGNATION_LEGEND_STYLES["national_designated"]["fill"],
            "#FFFF7F",
        )
        self.assertEqual(
            DESIGNATION_LEGEND_STYLES["local_designated"]["label"],
            "시도지정유산구역",
        )
        self.assertEqual(
            DESIGNATION_LEGEND_STYLES["national_protection"]["fill"],
            "#62C7C7",
        )
        self.assertEqual(
            DESIGNATION_LEGEND_STYLES["local_protection"]["label"],
            "시도지정유산보호구역",
        )


if __name__ == "__main__":
    unittest.main()
