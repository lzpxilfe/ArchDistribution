# Validation assets

This directory contains only openly redistributable synthetic fixtures,
expected outputs, rule snapshots, templates, and non-sensitive aggregate
results for the ArchDistribution research release.

Real national heritage layers, actual site coordinates, institution-internal
identifiers, and the raw 300-pair pilot set must **not** be committed here.

## Directory contract

- `fixtures/`: wholly synthetic inputs with generation notes and fixed seeds.
- `expected/`: expected decisions, schemas, hashes, and numerical tolerances.
- `rules/`: immutable copies of rule sets used by published validation runs.
- `templates/`: blank forms for pilot, workflow, manual, and external tests.
- `results/`: status and non-sensitive aggregate results, including failures.

An empty directory or template is not evidence that a test has passed. The
authoritative release-readiness record is `results/status.md`.

## Private pilot command line

Run the pilot outside the repository (or in a gitignored private directory):

```bash
python validation/run_pilot.py split private/predictions.csv private/pilot-split
python validation/run_pilot.py score private/pilot-split/locked_evaluation_blinded.csv \
  --predictions private/pilot-split/locked_evaluation_predictions_private.csv \
  --output private/pilot-split/locked_metrics.json
```

The input requires unique `pair_id` and nonempty `project_key` fields, plus
private `is_candidate` and `automatic_merge` predictions for scoring. The split
command creates exactly 200 development and 100 locked-evaluation rows by
default without placing one project in both sets. The score command rejects
development rows unless `--allow-any-split` is explicitly used. Do not commit
any generated private CSV.

## Required provenance per run

Record the Git commit, plugin version, rule-set version and SHA-256, QGIS/Qt/
Python/GDAL/GEOS/PROJ and OS versions, input hashes, command or UI procedure,
status, output hashes, and reviewer. See
`docs/research/validation-protocol.md` and `reproducibility.md`.
