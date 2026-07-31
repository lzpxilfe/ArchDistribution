"""End-to-end QGIS verification for a preservation-area shapefile."""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsProject,
    QgsVectorLayer,
)


def prepare_import_paths():
    qgis_python_plugins = str(
        Path(QgsApplication.prefixPath()) / "python" / "plugins"
    )
    plugin_parent = str(Path(__file__).resolve().parent.parent)
    for import_path in (qgis_python_plugins, plugin_parent):
        if import_path not in sys.path:
            sys.path.insert(0, import_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shp", required=True)
    args = parser.parse_args()

    app = QgsApplication.instance() or QgsApplication([], False)
    app.initQgis()
    prepare_import_paths()

    from processing.core.Processing import Processing
    from ArchDistribution.arch_distribution import ArchDistribution

    Processing.initialize()
    project = QgsProject.instance()
    project.clear()

    source = QgsVectorLayer(args.shp, "매장유산유존지역", "ogr")
    if not source.isValid():
        raise RuntimeError(f"Invalid source layer: {args.shp}")
    source.setProviderEncoding("CP949")
    source.dataProvider().setEncoding("CP949")
    source.dataProvider().reloadData()
    source.updateFields()
    project.addMapLayer(source)

    root = project.layerTreeRoot()
    source_group = root.addGroup("검증 원본")

    plugin = ArchDistribution.__new__(ArchDistribution)
    messages = []
    plugin.log = messages.append

    action_field = plugin.find_preservation_action_field(source)
    if not action_field:
        raise RuntimeError("Preservation-action field was not detected")

    output = plugin.consolidate_heritage_layers(
        [source.id()],
        None,
        None,
        source_group,
        preservation_only=True,
        preservation_action_fields={source.id(): action_field},
    )
    if output is None:
        raise RuntimeError("Consolidation returned no output")

    plugin.number_heritage_v4(
        output,
        output.extent().center(),
        sort_order=2,
        extent_geom=None,
        extent_crs=output.crs(),
        buffer_geoms=[],
        restrict_to_buffer=False,
    )
    plugin.apply_heritage_style(
        output,
        {
            "fill_color": "#FFFFFF",
            "stroke_color": "#000000",
            "stroke_width": 0.3,
            "opacity": 1.0,
        },
    )

    source_fields = {field.name() for field in source.fields()}
    output_fields = {field.name() for field in output.fields()}
    missing_source_fields = sorted(source_fields.difference(output_fields))

    action_counts = Counter()
    number_to_names = defaultdict(set)
    name_to_numbers = defaultdict(set)
    source_counts = []
    for feat in output.getFeatures():
        action_counts[str(feat["보존조치"] or "")] += 1
        number_to_names[feat["번호"]].add(str(feat["유적명"]))
        name_to_numbers[str(feat["유적명"])].add(feat["번호"])
        source_counts.append(int(feat["SRC_COUNT"] or 0))

    renderer = output.renderer()
    renderer_labels = (
        [category.label() for category in renderer.categories()]
        if hasattr(renderer, "categories")
        else []
    )
    numbers = {feat["번호"] for feat in output.getFeatures()}
    numbers.discard(None)

    summary = {
        "input_features": source.featureCount(),
        "output_action_parts": output.featureCount(),
        "unique_numbered_sites": len(numbers),
        "action_counts": dict(action_counts),
        "missing_source_fields": missing_source_fields,
        "max_source_records_per_site": max(source_counts, default=0),
        "renderer_labels": renderer_labels,
        "names_with_multiple_numbers": {
            name: sorted(numbers)
            for name, numbers in name_to_numbers.items()
            if len(numbers) > 1
        },
        "logs": messages,
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))

    expected_actions = {
        "현상보존",
        "정밀발굴조사",
        "시굴조사",
        "표본조사",
    }
    if missing_source_fields:
        raise AssertionError(f"Source fields were lost: {missing_source_fields}")
    if set(renderer_labels[:4]) != expected_actions:
        raise AssertionError(f"Unexpected renderer labels: {renderer_labels}")
    if summary["names_with_multiple_numbers"]:
        raise AssertionError("One site name received multiple numbers")


if __name__ == "__main__":
    main()
