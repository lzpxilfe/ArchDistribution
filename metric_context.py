"""Metric-safe coordinate handling for ArchDistribution.

The plugin receives source data in many coordinate reference systems.  This
module keeps the source, analysis, and output CRS roles explicit so that a
value named ``DIST_M`` or ``area_m2`` is never calculated in degrees or feet.

QGIS is an optional import on purpose: the pure UTM-selection helpers remain
usable in ordinary Python environments, while :class:`MetricContext` gives a
clear error if its QGIS-dependent API is used without QGIS.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, Optional, Sequence, Tuple


try:  # pragma: no cover - availability is environment-specific
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsCoordinateTransformContext,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsRectangle,
        QgsUnitTypes,
    )

    QGIS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised outside QGIS
    QGIS_AVAILABLE = False


WGS84_AUTHID = "EPSG:4326"
UTM_MIN_LATITUDE = -80.0
UTM_MAX_LATITUDE = 84.0


class MetricContextError(ValueError):
    """Raised when a trustworthy metric analysis context cannot be built."""


def utm_zone_for_longitude(longitude: float) -> int:
    """Return the standard UTM zone (1..60) for a longitude in degrees."""

    try:
        longitude = float(longitude)
    except (TypeError, ValueError) as error:
        raise MetricContextError("Longitude must be a finite number.") from error
    if not math.isfinite(longitude) or not -180.0 <= longitude <= 180.0:
        raise MetricContextError("Longitude must be between -180 and 180 degrees.")
    # Longitude 180 belongs to zone 60, not the otherwise calculated zone 61.
    return min(60, max(1, int(math.floor((longitude + 180.0) / 6.0)) + 1))


def local_utm_epsg(longitude: float, latitude: float) -> int:
    """Return the WGS 84 UTM EPSG code covering a lon/lat centroid.

    UTM is only defined here for its conventional coverage (-80 to 84
    degrees).  Failing outside that range is safer than silently reporting a
    polar measurement as metres in an unsuitable projection.
    """

    try:
        latitude = float(latitude)
    except (TypeError, ValueError) as error:
        raise MetricContextError("Latitude must be a finite number.") from error
    if not math.isfinite(latitude):
        raise MetricContextError("Latitude must be a finite number.")
    if not UTM_MIN_LATITUDE <= latitude <= UTM_MAX_LATITUDE:
        raise MetricContextError(
            "Local UTM selection requires a latitude between -80 and 84 degrees."
        )
    longitude = float(longitude)
    zone = utm_zone_for_longitude(longitude)
    # Conventional UTM has widened zones in Norway and Svalbard.  Respecting
    # them avoids selecting a neighbouring narrow zone for international data.
    if 56.0 <= latitude < 64.0 and 3.0 <= longitude < 12.0:
        zone = 32
    elif 72.0 <= latitude <= 84.0:
        if 0.0 <= longitude < 9.0:
            zone = 31
        elif 9.0 <= longitude < 21.0:
            zone = 33
        elif 21.0 <= longitude < 33.0:
            zone = 35
        elif 33.0 <= longitude < 42.0:
            zone = 37
    return (32600 if latitude >= 0.0 else 32700) + zone


def local_utm_authid(longitude: float, latitude: float) -> str:
    """Return an ``EPSG:xxxxx`` identifier for the local WGS 84 UTM CRS."""

    return f"EPSG:{local_utm_epsg(longitude, latitude)}"


def _require_qgis() -> None:
    if not QGIS_AVAILABLE:
        raise MetricContextError(
            "MetricContext requires the QGIS Python runtime; the pure UTM "
            "selection helpers remain available without QGIS."
        )


def _validated_crs(crs: Any, role: str):
    _require_qgis()
    if isinstance(crs, str):
        crs = QgsCoordinateReferenceSystem(crs)
    if crs is None or not isinstance(crs, QgsCoordinateReferenceSystem):
        raise MetricContextError(f"{role} CRS must be a QGIS CRS or auth id.")
    if not crs.isValid():
        raise MetricContextError(f"{role} CRS is missing or invalid.")
    # Return a copy so later caller mutation cannot alter the context.
    return QgsCoordinateReferenceSystem(crs)


def _is_projected_metre_crs(crs: Any) -> bool:
    return (
        crs.isValid()
        and not crs.isGeographic()
        and crs.mapUnits() == QgsUnitTypes.DistanceMeters
    )


def _default_transform_context():
    project = QgsProject.instance()
    if project is not None:
        return project.transformContext()
    return QgsCoordinateTransformContext()


def _point_xy(value: Any):
    """Coerce a point, geometry centroid, rectangle centre, or pair to PointXY."""

    if isinstance(value, QgsPointXY):
        return QgsPointXY(value)
    if isinstance(value, QgsGeometry):
        if value.isNull() or value.isEmpty():
            raise MetricContextError("Centroid geometry is empty.")
        centroid = value.centroid()
        if centroid.isNull() or centroid.isEmpty():
            raise MetricContextError("Could not calculate the geometry centroid.")
        return QgsPointXY(centroid.asPoint())
    if isinstance(value, QgsRectangle):
        # A single-point or perfectly horizontal/vertical layer has a
        # zero-area rectangle that QGIS calls empty, but its centre remains a
        # valid representative point for UTM selection.
        if value.isNull():
            raise MetricContextError("Centroid extent is empty.")
        centre = QgsPointXY(value.center())
        if math.isfinite(centre.x()) and math.isfinite(centre.y()):
            return centre
        raise MetricContextError("Centroid extent has non-finite coordinates.")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) == 2:
            try:
                x, y = float(value[0]), float(value[1])
            except (TypeError, ValueError) as error:
                raise MetricContextError("Point coordinates must be numbers.") from error
            if math.isfinite(x) and math.isfinite(y):
                return QgsPointXY(x, y)
    raise MetricContextError(
        "A centroid must be a QgsPointXY, QgsGeometry, QgsRectangle, or (x, y)."
    )


def _crs_payload(crs: Any) -> Dict[str, Any]:
    authid = crs.authid()
    return {
        "authid": authid or None,
        "description": crs.description() or None,
        "is_geographic": bool(crs.isGeographic()),
        # encodeUnit is stable across UI locales, unlike display strings.
        "map_units": QgsUnitTypes.encodeUnit(crs.mapUnits()),
        # Custom CRS definitions may not have an authority identifier.  The
        # WKT keeps their provenance unambiguous without storing a file path.
        "wkt": None if authid else crs.toWkt(),
    }


@dataclass(frozen=True)
class MetricContext:
    """Explicit source/analysis/output CRS roles and metric operations.

    Construct instances with :meth:`create` or :meth:`from_layer`; direct
    construction is intentionally not validated.  Geometry methods never
    mutate their input.  Buffers are returned in the analysis CRS by default,
    making the unit of the buffer distance explicit.
    """

    source_crs: Any
    analysis_crs: Any
    output_crs: Any
    transform_context: Any
    selection_method: str
    centroid_wgs84: Optional[Tuple[float, float]] = None

    @classmethod
    def create(
        cls,
        source_crs: Any,
        centroid: Any = None,
        *,
        output_crs: Any = None,
        analysis_crs: Any = None,
        transform_context: Any = None,
    ) -> "MetricContext":
        """Build a metric context.

        A projected metre source CRS is retained unchanged.  Geographic and
        non-metric projected sources require a representative centroid in
        source coordinates; it is transformed to WGS 84 and selects the local
        UTM CRS.  ``analysis_crs`` is the advanced override and is accepted
        only when it is a projected metre CRS.
        """

        source = _validated_crs(source_crs, "Source")
        output = _validated_crs(
            source if output_crs is None else output_crs,
            "Output",
        )
        context = transform_context or _default_transform_context()
        centroid_lonlat = None

        if analysis_crs is not None:
            analysis = _validated_crs(analysis_crs, "Analysis")
            if not _is_projected_metre_crs(analysis):
                raise MetricContextError(
                    "Analysis CRS must be a projected CRS whose map unit is metre."
                )
            method = "explicit_projected_metre_crs"
        elif _is_projected_metre_crs(source):
            analysis = QgsCoordinateReferenceSystem(source)
            method = "source_projected_metre_crs"
        else:
            if centroid is None:
                raise MetricContextError(
                    "A source-coordinate centroid is required to choose a local "
                    "UTM CRS for geographic or non-metric source data."
                )
            source_point = _point_xy(centroid)
            wgs84 = QgsCoordinateReferenceSystem(WGS84_AUTHID)
            try:
                if source == wgs84:
                    wgs84_point = source_point
                else:
                    transform = QgsCoordinateTransform(source, wgs84, context)
                    wgs84_point = transform.transform(source_point)
            except Exception as error:
                raise MetricContextError(
                    "Could not transform the source centroid to WGS 84."
                ) from error
            longitude, latitude = wgs84_point.x(), wgs84_point.y()
            authid = local_utm_authid(longitude, latitude)
            analysis = _validated_crs(authid, "Derived analysis")
            if not _is_projected_metre_crs(analysis):
                raise MetricContextError(
                    f"Derived analysis CRS {authid} is not a projected metre CRS."
                )
            centroid_lonlat = (float(longitude), float(latitude))
            method = "centroid_local_utm"

        return cls(
            source_crs=source,
            analysis_crs=analysis,
            output_crs=output,
            transform_context=context,
            selection_method=method,
            centroid_wgs84=centroid_lonlat,
        )

    @classmethod
    def from_layer(
        cls,
        layer: Any,
        *,
        output_crs: Any = None,
        analysis_crs: Any = None,
        transform_context: Any = None,
    ) -> "MetricContext":
        """Build from a layer CRS, using its extent centre when UTM is needed."""

        _require_qgis()
        if layer is None or not hasattr(layer, "crs"):
            raise MetricContextError("A QGIS layer is required.")
        source = _validated_crs(layer.crs(), "Layer source")
        centroid = None
        if analysis_crs is None and not _is_projected_metre_crs(source):
            extent = layer.extent()
            if extent is None or extent.isNull():
                raise MetricContextError(
                    "The layer has no usable extent for local UTM selection."
                )
            centroid = extent.center()
        return cls.create(
            source,
            centroid,
            output_crs=output_crs,
            analysis_crs=analysis_crs,
            transform_context=transform_context,
        )

    def transform_geometry(
        self,
        geometry: Any,
        source_crs: Any = None,
        target_crs: Any = None,
    ):
        """Return a transformed geometry copy; never mutate the input."""

        if not isinstance(geometry, QgsGeometry):
            raise MetricContextError("Expected a QgsGeometry.")
        if geometry.isNull():
            raise MetricContextError("Cannot transform a null geometry.")
        source = _validated_crs(
            self.source_crs if source_crs is None else source_crs,
            "Geometry source",
        )
        target = _validated_crs(
            self.analysis_crs if target_crs is None else target_crs,
            "Geometry target",
        )
        result = QgsGeometry(geometry)
        if source == target:
            return result
        try:
            result.transform(
                QgsCoordinateTransform(source, target, self.transform_context)
            )
        except Exception as error:
            raise MetricContextError(
                f"Geometry transform failed: {source.authid()} -> {target.authid()}."
            ) from error
        return result

    def to_analysis_geometry(self, geometry: Any, source_crs: Any = None):
        """Return a geometry copy in the projected-metre analysis CRS."""

        return self.transform_geometry(geometry, source_crs, self.analysis_crs)

    def to_output_geometry(self, geometry: Any, source_crs: Any = None):
        """Return a geometry copy in the declared output CRS."""

        return self.transform_geometry(geometry, source_crs, self.output_crs)

    def prepare_extent(self, extent: Any, source_crs: Any = None):
        """Return an extent polygon in the analysis CRS."""

        if isinstance(extent, QgsRectangle):
            geometry = QgsGeometry.fromRect(extent)
        elif isinstance(extent, QgsGeometry):
            geometry = extent
        else:
            raise MetricContextError("Extent must be a QgsRectangle or QgsGeometry.")
        return self.to_analysis_geometry(geometry, source_crs)

    def transform_point(
        self,
        point: Any,
        source_crs: Any = None,
        target_crs: Any = None,
    ):
        """Return a transformed ``QgsPointXY``."""

        result = _point_xy(point)
        source = _validated_crs(
            self.source_crs if source_crs is None else source_crs,
            "Point source",
        )
        target = _validated_crs(
            self.analysis_crs if target_crs is None else target_crs,
            "Point target",
        )
        if source == target:
            return result
        try:
            return QgsCoordinateTransform(
                source, target, self.transform_context
            ).transform(result)
        except Exception as error:
            raise MetricContextError(
                f"Point transform failed: {source.authid()} -> {target.authid()}."
            ) from error

    def distance_m(self, first: Any, second: Any, source_crs: Any = None) -> float:
        """Return planar point distance in metres in the analysis CRS."""

        a = self.transform_point(first, source_crs, self.analysis_crs)
        b = self.transform_point(second, source_crs, self.analysis_crs)
        return float(math.hypot(b.x() - a.x(), b.y() - a.y()))

    def area_m2(self, geometry: Any, source_crs: Any = None) -> float:
        """Return planar geometry area in square metres."""

        return float(self.to_analysis_geometry(geometry, source_crs).area())

    def extent_dimensions_m(
        self,
        extent: Any,
        source_crs: Any = None,
    ) -> Tuple[float, float]:
        """Return analysis-CRS bounding width and height in metres."""

        bounds = self.prepare_extent(extent, source_crs).boundingBox()
        return float(bounds.width()), float(bounds.height())

    def buffer_m(
        self,
        geometry: Any,
        distance_m: float,
        source_crs: Any = None,
        *,
        segments: int = 8,
        result_crs: Any = None,
    ):
        """Create a metric buffer, returning analysis CRS unless requested.

        ``result_crs`` is useful at an output boundary.  Keeping it ``None``
        is preferred while clipping, measuring, or applying micro-fragment
        thresholds because the returned geometry then remains metric.
        """

        try:
            distance = float(distance_m)
        except (TypeError, ValueError) as error:
            raise MetricContextError("Buffer distance must be a finite number.") from error
        if not math.isfinite(distance) or distance < 0.0:
            raise MetricContextError(
                "Buffer distance must be a finite, non-negative metre value."
            )
        if not isinstance(segments, int) or segments < 1:
            raise MetricContextError("Buffer segments must be a positive integer.")
        metric_geometry = self.to_analysis_geometry(geometry, source_crs)
        buffered = metric_geometry.buffer(distance, segments)
        if buffered.isNull():
            raise MetricContextError("Metric buffer operation failed.")
        if result_crs is None:
            return buffered
        return self.transform_geometry(buffered, self.analysis_crs, result_crs)

    def provenance(self) -> Dict[str, Any]:
        """Return a JSON-serialisable, path-free CRS provenance payload."""

        return {
            "source_crs": _crs_payload(self.source_crs),
            "analysis_crs": _crs_payload(self.analysis_crs),
            "output_crs": _crs_payload(self.output_crs),
            "analysis_selection": {
                "method": self.selection_method,
                "centroid_wgs84": (
                    list(self.centroid_wgs84)
                    if self.centroid_wgs84 is not None
                    else None
                ),
                "projected": not self.analysis_crs.isGeographic(),
                "linear_unit": "metre",
                "metric_guarantee": _is_projected_metre_crs(self.analysis_crs),
            },
        }


__all__ = [
    "MetricContext",
    "MetricContextError",
    "QGIS_AVAILABLE",
    "local_utm_authid",
    "local_utm_epsg",
    "utm_zone_for_longitude",
]
