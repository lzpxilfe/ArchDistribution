r"""Read-only validation of matching rules against nationwide ZIP datasets.

Run with the QGIS Python environment:
    python-qgis-ltr.bat verify_nationwide_matching.py C:\path\to\sites
"""

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time

from osgeo import gdal, ogr
from shapely import from_wkb, make_valid
from shapely.geometry import box
from shapely.strtree import STRtree

from heritage_matching import (
    ROLE_DISTRIBUTION,
    ROLE_EXCAVATION,
    ROLE_PROTECTION_ZONE,
    ROLE_SURFACE,
    detect_source_role,
    evaluate_candidate,
    is_designated_role,
)


NAME_FIELDS = (
    "유적명",
    "명칭",
    "국가유산명",
    "문화재명",
    "지정명칭",
)
PROJECT_FIELDS = ("사업명", "조사명", "공사명")
ADDRESS_FIELDS = ("소재지", "유적소재지", "주소", "지번")
CODE_FIELDS = ("유산코드", "CODE")


def first_field(layer, candidates):
    fields = {
        layer.GetLayerDefn().GetFieldDefn(index).GetName()
        for index in range(layer.GetLayerDefn().GetFieldCount())
    }
    for candidate in candidates:
        if candidate in fields:
            return candidate
    return None


def scan_layer(zip_path, layer):
    layer_name = layer.GetName()
    fields = [
        layer.GetLayerDefn().GetFieldDefn(index).GetName()
        for index in range(layer.GetLayerDefn().GetFieldCount())
    ]
    role = detect_source_role(
        f"{zip_path.stem} {layer_name}",
        fields,
    )
    name_field = first_field(layer, NAME_FIELDS)
    project_field = first_field(layer, PROJECT_FIELDS)
    address_field = first_field(layer, ADDRESS_FIELDS)
    code_field = first_field(layer, CODE_FIELDS)

    digest = hashlib.sha256()
    records = []
    invalid_fixed = 0
    layer.ResetReading()
    for feature in layer:
        geometry_ref = feature.GetGeometryRef()
        if geometry_ref is None:
            continue
        geometry_wkb = bytes(geometry_ref.ExportToWkb())
        digest.update(geometry_wkb)
        code = feature.GetField(code_field) if code_field else ""
        name = feature.GetField(name_field) if name_field else ""
        digest.update(str(code or "").encode("utf-8", "replace"))
        digest.update(str(name or "").encode("utf-8", "replace"))

        geometry = from_wkb(geometry_wkb)
        if not geometry.is_valid:
            geometry = make_valid(geometry)
            invalid_fixed += 1
        if geometry.is_empty:
            continue
        records.append({
            "uid": f"{zip_path.name}:{layer_name}:{feature.GetFID()}",
            "role": role,
            "name": str(name or ""),
            "site_name": str(name or ""),
            "project_name": str(
                (
                    feature.GetField(project_field)
                    if project_field
                    else ""
                )
                or ""
            ),
            "address": str(
                (
                    feature.GetField(address_field)
                    if address_field
                    else ""
                )
                or ""
            ),
            "code": str(code or ""),
            "geometry": geometry,
        })
    return {
        "role": role,
        "layer_name": layer_name,
        "feature_count": len(records),
        "invalid_fixed": invalid_fixed,
        "fingerprint": digest.hexdigest(),
        "records": records,
    }


def compare_collections(left_records, right_records, counters):
    if not left_records or not right_records:
        return
    right_geometries = [record["geometry"] for record in right_records]
    tree = STRtree(right_geometries)
    for left in left_records:
        min_x, min_y, max_x, max_y = left["geometry"].bounds
        search = box(min_x - 50, min_y - 50, max_x + 50, max_y + 50)
        for right_index in tree.query(search):
            right = right_records[int(right_index)]
            left_geometry = left["geometry"]
            right_geometry = right["geometry"]
            intersects = left_geometry.intersects(right_geometry)
            distance = left_geometry.distance(right_geometry)
            overlap = 0.0
            if intersects:
                intersection_area = left_geometry.intersection(
                    right_geometry
                ).area
                smaller_area = min(
                    left_geometry.area,
                    right_geometry.area,
                )
                overlap = (
                    intersection_area / smaller_area
                    if smaller_area > 0
                    else 1.0
                )
            candidate = evaluate_candidate(
                left,
                right,
                intersects=intersects,
                overlap_ratio=overlap,
                distance=distance,
            )
            if not candidate:
                continue
            counters["candidate_total"] += 1
            counters[f"kind:{candidate.pair_kind}"] += 1
            counters[f"confidence:{candidate.confidence}"] += 1
            counters[
                "auto_apply" if candidate.auto_apply else "manual_review"
            ] += 1
            counters[f"rule:{candidate.rule}"] += 1


def main(sites_dir):
    started = time.perf_counter()
    ogr.DontUseExceptions()
    gdal.SetConfigOption("SHAPE_ENCODING", "CP949")
    # National downloads store Korean member names using the Windows code
    # page.  Without this setting GDAL opens the geometry but exposes mojibake
    # layer names, which breaks role detection and permit-boundary exclusion.
    gdal.SetConfigOption("CPL_ZIP_ENCODING", "CP949")
    gdal.PushErrorHandler("CPLQuietErrorHandler")

    sites_dir = Path(sites_dir)
    zip_paths = sorted(sites_dir.glob("*.zip"))
    if not zip_paths:
        raise SystemExit(f"No ZIP datasets found: {sites_dir}")

    all_records = defaultdict(list)
    layer_counts = Counter()
    duplicate_layers = []
    seen_fingerprints = {}
    invalid_total = 0

    for zip_index, zip_path in enumerate(zip_paths, start=1):
        print(
            f"[{zip_index}/{len(zip_paths)}] {zip_path.name}",
            file=sys.stderr,
            flush=True,
        )
        dataset = ogr.Open(f"/vsizip/{zip_path.as_posix()}")
        if dataset is None:
            raise RuntimeError(f"Cannot open {zip_path}")
        for layer_index in range(dataset.GetLayerCount()):
            layer = dataset.GetLayerByIndex(layer_index)
            scanned = scan_layer(zip_path, layer)
            role = scanned["role"]
            layer_name = scanned["layer_name"]
            feature_count = scanned["feature_count"]
            invalid_total += scanned["invalid_fixed"]
            layer_counts[f"{role}:{layer_name}"] += feature_count

            fingerprint_key = (
                role,
                layer_name,
                feature_count,
                scanned["fingerprint"],
            )
            if fingerprint_key in seen_fingerprints:
                duplicate_layers.append({
                    "duplicate": f"{zip_path.name}:{layer_name}",
                    "same_as": seen_fingerprints[fingerprint_key],
                    "features": feature_count,
                })
                continue
            seen_fingerprints[fingerprint_key] = (
                f"{zip_path.name}:{layer_name}"
            )

            # Permit/project boundaries are valuable source information but are
            # not numbered site identities in the distribution map.
            if "사업허가구역" in layer_name:
                continue
            all_records[role].extend(scanned["records"])

    designated = []
    for role, records in all_records.items():
        if is_designated_role(role):
            designated.extend(records)
    distribution = all_records[ROLE_DISTRIBUTION]
    excavation = all_records[ROLE_EXCAVATION]
    surface = all_records[ROLE_SURFACE]

    counters = Counter()
    compare_collections(designated, distribution, counters)
    compare_collections(excavation, distribution, counters)
    compare_collections(designated, excavation, counters)
    compare_collections(surface, designated, counters)
    compare_collections(surface, distribution, counters)
    compare_collections(surface, excavation, counters)

    summary = {
        "zip_count": len(zip_paths),
        "role_record_counts": {
            role: len(records)
            for role, records in sorted(all_records.items())
        },
        "layer_record_counts": dict(sorted(layer_counts.items())),
        "numbering_records": {
            "designated_registered": len(designated),
            "distribution": len(distribution),
            "excavation": len(excavation),
            "surface": len(surface),
            "protection_zone": len(
                all_records[ROLE_PROTECTION_ZONE]
            ),
        },
        "invalid_geometries_repaired": invalid_total,
        "duplicate_layers": duplicate_layers,
        "candidate_summary": dict(sorted(counters.items())),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    directory = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path.home() / "Downloads" / "sites"
    )
    main(directory)
