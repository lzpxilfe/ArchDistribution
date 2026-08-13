#!/usr/bin/env python3
"""Synthetic 100k-feature spatial-index benchmark for research releases.

Run this with QGIS Python.  It prints one JSON document and never writes the
repository, allowing a maintainer to review the measurement before committing
it below ``validation/results``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import sys
import time

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsRectangle,
    QgsSpatialIndex,
)


def peak_rss_mib():
    """Return OS peak working-set MiB when the platform exposes it."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            kernel = ctypes.windll.kernel32
            kernel.GetCurrentProcess.restype = ctypes.c_void_p
            psapi = ctypes.windll.psapi
            psapi.GetProcessMemoryInfo.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(Counters),
                wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            ok = psapi.GetProcessMemoryInfo(
                kernel.GetCurrentProcess(),
                ctypes.byref(counters),
                counters.cb,
            )
            if ok:
                return round(counters.PeakWorkingSetSize / 1048576, 3)
        except (AttributeError, OSError, ValueError):
            return None
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        divisor = 1048576 if sys.platform == "darwin" else 1024
        return round(peak / divisor, 3)
    except (ImportError, AttributeError, ValueError):
        return None


def run(feature_count):
    columns = int(math.ceil(math.sqrt(feature_count)))
    index = QgsSpatialIndex()
    bounds = []
    started = time.perf_counter()
    for feature_id in range(feature_count):
        column = feature_id % columns
        row = feature_id // columns
        x = column * 3.0
        y = row * 3.0
        rectangle = QgsRectangle(x, y, x + 1.0, y + 1.0)
        feature = QgsFeature(feature_id)
        feature.setId(feature_id)
        feature.setGeometry(QgsGeometry.fromRect(rectangle))
        index.addFeature(feature)
        bounds.append(rectangle)
    indexed_at = time.perf_counter()

    raw_hits = 0
    unique_pairs = 0
    maximum_hits = 0
    for feature_id, rectangle in enumerate(bounds):
        search = QgsRectangle(rectangle)
        search.grow(2.1)
        hits = index.intersects(search)
        raw_hits += len(hits)
        maximum_hits = max(maximum_hits, len(hits))
        unique_pairs += sum(1 for other_id in hits if other_id > feature_id)
    finished = time.perf_counter()

    theoretical_pairs = feature_count * (feature_count - 1) // 2
    return {
        "schema_version": 1,
        "benchmark": "qgsspatialindex-local-candidate-generation",
        "synthetic": True,
        "feature_count": feature_count,
        "index_build_seconds": round(indexed_at - started, 6),
        "query_seconds": round(finished - indexed_at, 6),
        "total_seconds": round(finished - started, 6),
        "peak_rss_mib": peak_rss_mib(),
        "raw_index_hits": raw_hits,
        "unique_candidate_pairs": unique_pairs,
        "maximum_hits_per_query": maximum_hits,
        "theoretical_all_pairs": theoretical_pairs,
        "candidate_fraction_of_all_pairs": round(
            unique_pairs / theoretical_pairs, 12
        ),
        "completed": True,
        "runtime": {
            "qgis": Qgis.QGIS_VERSION,
            "python": platform.python_version(),
            "operating_system": platform.platform(),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=int, default=100_000)
    arguments = parser.parse_args()
    if arguments.features < 1:
        parser.error("--features must be positive")
    app = QgsApplication.instance() or QgsApplication([], False)
    app.initQgis()
    try:
        print(json.dumps(
            run(arguments.features),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ))
    finally:
        app.exitQgis()


if __name__ == "__main__":
    main()
