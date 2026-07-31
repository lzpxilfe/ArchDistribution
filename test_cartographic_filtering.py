import unittest

from cartographic_filtering import (
    clipped_polygon_print_metrics,
    is_insignificant_extent_fragment,
)


class CartographicFilteringTests(unittest.TestCase):
    def test_complete_small_polygon_is_kept(self):
        self.assertFalse(
            is_insignificant_extent_fragment(
                original_area=4,
                clipped_area=4,
                clipped_width=2,
                clipped_height=2,
                extent_width=1000,
                extent_height=1000,
                paper_width_mm=200,
                paper_height_mm=200,
            )
        )

    def test_tiny_edge_fragment_is_excluded(self):
        self.assertTrue(
            is_insignificant_extent_fragment(
                original_area=50000,
                clipped_area=50,
                clipped_width=3,
                clipped_height=100,
                extent_width=1000,
                extent_height=1000,
                paper_width_mm=200,
                paper_height_mm=200,
            )
        )

    def test_large_visible_piece_is_kept_despite_low_ratio(self):
        self.assertFalse(
            is_insignificant_extent_fragment(
                original_area=10_000_000,
                clipped_area=100_000,
                clipped_width=300,
                clipped_height=300,
                extent_width=1000,
                extent_height=1000,
                paper_width_mm=200,
                paper_height_mm=200,
            )
        )

    def test_moderately_retained_narrow_site_is_kept(self):
        self.assertFalse(
            is_insignificant_extent_fragment(
                original_area=1000,
                clipped_area=500,
                clipped_width=2,
                clipped_height=250,
                extent_width=1000,
                extent_height=1000,
                paper_width_mm=200,
                paper_height_mm=200,
            )
        )

    def test_print_metrics_follow_extent_and_paper_size(self):
        metrics = clipped_polygon_print_metrics(
            clipped_area=2500,
            clipped_width=50,
            clipped_height=50,
            extent_width=1000,
            extent_height=1000,
            paper_width_mm=200,
            paper_height_mm=100,
        )
        self.assertAlmostEqual(metrics["width_mm"], 10)
        self.assertAlmostEqual(metrics["height_mm"], 5)
        self.assertAlmostEqual(metrics["area_mm2"], 50)


if __name__ == "__main__":
    unittest.main()
