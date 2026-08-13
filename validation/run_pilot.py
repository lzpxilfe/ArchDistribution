"""Command-line entry point for the private single-reviewer pilot workflow."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from research_validation import (  # noqa: E402
    DEFAULT_DEVELOPMENT_SIZE,
    DEFAULT_LOCKED_EVALUATION_SIZE,
    DEFAULT_SPLIT_SEED,
    SPLIT_LOCKED_EVALUATION,
    calculate_pilot_metrics,
    deterministic_project_split,
    export_blinded_labeling_csv,
    merge_blinded_labels,
    read_csv_records,
    write_metrics_json,
)


def _write_csv(rows, destination):
    rows = list(rows)
    if not rows:
        return None
    fieldnames = []
    for row in rows:
        for field in row:
            if field not in fieldnames:
                fieldnames.append(field)
    path = Path(destination)
    with path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    payload = path.read_bytes()
    return {
        "row_count": len(rows),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "filename": path.name,
    }


def _split(args):
    rows = read_csv_records(args.input)
    split = deterministic_project_split(
        rows,
        development_size=args.development_size,
        locked_evaluation_size=args.evaluation_size,
        seed=args.seed,
        pair_id_field=args.pair_id_field,
        project_field=args.project_field,
    )
    output = Path(args.output_directory)
    output.mkdir(parents=True, exist_ok=True)
    development_metadata = export_blinded_labeling_csv(
        split.development, output / "development_blinded.csv"
    )
    evaluation_metadata = export_blinded_labeling_csv(
        split.locked_evaluation,
        output / "locked_evaluation_blinded.csv",
    )
    development_private_metadata = _write_csv(
        split.development, output / "development_predictions_private.csv"
    )
    evaluation_private_metadata = _write_csv(
        split.locked_evaluation,
        output / "locked_evaluation_predictions_private.csv",
    )
    excluded_metadata = _write_csv(
        split.excluded, output / "excluded_private.csv"
    )
    manifest = split.manifest()
    manifest["files"] = {
        "development_blinded.csv": development_metadata,
        "locked_evaluation_blinded.csv": evaluation_metadata,
        "development_predictions_private.csv": development_private_metadata,
        "locked_evaluation_predictions_private.csv": (
            evaluation_private_metadata
        ),
        "excluded_private.csv": excluded_metadata,
    }
    (output / "split_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


def _blind(args):
    metadata = export_blinded_labeling_csv(
        read_csv_records(args.input), args.output
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True))


def _score(args):
    labeled_rows = read_csv_records(args.input)
    if args.predictions:
        labeled_rows = merge_blinded_labels(
            read_csv_records(args.predictions),
            labeled_rows,
            label_field=args.label_field,
        )
    metrics = calculate_pilot_metrics(
        labeled_rows,
        label_field=args.label_field,
        candidate_field=args.candidate_field,
        automatic_merge_field=args.automatic_merge_field,
        required_split=(
            None if args.allow_any_split else SPLIT_LOCKED_EVALUATION
        ),
    )
    if args.output:
        write_metrics_json(metrics, args.output)
    print(json.dumps(metrics.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))


def build_parser():
    parser = argparse.ArgumentParser(
        description="Prepare or score the private ArchDistribution pilot study."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    split = subparsers.add_parser(
        "split", help="create deterministic blinded development/evaluation CSVs"
    )
    split.add_argument("input")
    split.add_argument("output_directory")
    split.add_argument("--development-size", type=int, default=DEFAULT_DEVELOPMENT_SIZE)
    split.add_argument(
        "--evaluation-size",
        type=int,
        default=DEFAULT_LOCKED_EVALUATION_SIZE,
    )
    split.add_argument("--seed", default=DEFAULT_SPLIT_SEED)
    split.add_argument("--pair-id-field", default="pair_id")
    split.add_argument("--project-field", default="project_key")
    split.set_defaults(handler=_split)

    blind = subparsers.add_parser(
        "blind", help="remove recommendations and create an empty label column"
    )
    blind.add_argument("input")
    blind.add_argument("output")
    blind.set_defaults(handler=_blind)

    score = subparsers.add_parser(
        "score", help="calculate metrics from completed locked labels"
    )
    score.add_argument("input")
    score.add_argument(
        "--predictions",
        help="private prediction CSV to join with the blinded label CSV",
    )
    score.add_argument("--output")
    score.add_argument("--label-field", default="blind_label")
    score.add_argument("--candidate-field", default="is_candidate")
    score.add_argument("--automatic-merge-field", default="automatic_merge")
    score.add_argument(
        "--allow-any-split",
        action="store_true",
        help="score development data; locked_evaluation is required by default",
    )
    score.set_defaults(handler=_score)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
