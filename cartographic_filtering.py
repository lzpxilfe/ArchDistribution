"""Scale-aware rules for excluding insignificant map-edge clip fragments."""


MIN_PRINT_AREA_MM2 = 1.0
MIN_RETAINED_RATIO = 0.02
MAX_SLIVER_PRINT_AREA_MM2 = 9.0
MAX_SLIVER_NARROW_DIMENSION_MM = 1.0


def clipped_polygon_print_metrics(
    clipped_area,
    clipped_width,
    clipped_height,
    extent_width,
    extent_height,
    paper_width_mm,
    paper_height_mm,
):
    """Return the clipped polygon's approximate printed area and dimensions."""
    values = (
        clipped_area,
        clipped_width,
        clipped_height,
        extent_width,
        extent_height,
        paper_width_mm,
        paper_height_mm,
    )
    try:
        values = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        return None

    if any(value <= 0 for value in values):
        return None

    (
        clipped_area,
        clipped_width,
        clipped_height,
        extent_width,
        extent_height,
        paper_width_mm,
        paper_height_mm,
    ) = values
    width_mm = clipped_width / extent_width * paper_width_mm
    height_mm = clipped_height / extent_height * paper_height_mm
    area_mm2 = (
        clipped_area
        / (extent_width * extent_height)
        * (paper_width_mm * paper_height_mm)
    )
    return {
        "area_mm2": area_mm2,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "narrow_dimension_mm": min(width_mm, height_mm),
    }


def is_insignificant_extent_fragment(
    original_area,
    clipped_area,
    clipped_width,
    clipped_height,
    extent_width,
    extent_height,
    paper_width_mm,
    paper_height_mm,
):
    """
    Return True only for a polygon fragment created by clipping at map extent.

    Complete small sites are never rejected here. A clipped feature is excluded
    when it is below the absolute print-area floor, or when both its retained
    share and its visible footprint indicate a narrow edge sliver.
    """
    try:
        original_area = float(original_area)
        clipped_area = float(clipped_area)
    except (TypeError, ValueError):
        return False
    if original_area <= 0 or clipped_area <= 0:
        return False

    retained_ratio = min(1.0, clipped_area / original_area)
    was_clipped = retained_ratio < 0.999999
    if not was_clipped:
        return False

    metrics = clipped_polygon_print_metrics(
        clipped_area,
        clipped_width,
        clipped_height,
        extent_width,
        extent_height,
        paper_width_mm,
        paper_height_mm,
    )
    if metrics is None:
        return False

    if metrics["area_mm2"] < MIN_PRINT_AREA_MM2:
        return True

    is_tiny_share = retained_ratio < MIN_RETAINED_RATIO
    has_small_footprint = (
        metrics["area_mm2"] < MAX_SLIVER_PRINT_AREA_MM2
        or metrics["narrow_dimension_mm"]
        < MAX_SLIVER_NARROW_DIMENSION_MM
    )
    return is_tiny_share and has_small_footprint
