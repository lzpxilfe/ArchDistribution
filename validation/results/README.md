# Validation results

Commit only non-sensitive logs and aggregate tables. Keep failed, cancelled,
and superseded runs so the development history remains auditable. Raw pilot
pairs and exact real-site coordinates are prohibited.

Every result must reference a protocol version, Git commit, rules hash, input
hash or synthetic fixture identifier, environment, reviewer, and status.
`status.md` is the release gate; narrative descriptions cannot override it.

## Current real-workflow record

`real-workflow-2024-0745.md` records developer-led use during preparation of a
surrounding-site distribution map for an excavation report. Public permit
metadata establishes the project context, while missing software version,
input counts, decision counts, and shareable manifest evidence remain marked
as pending. It is evidence of operational use, not a timing study, accuracy
validation, or external adoption record.

## Current synthetic policy fixture

`python validation/run_synthetic_policy.py` passes all 13 committed cases in
`fixtures/policy_cases.json`. The cases cover investigation/site/number
separation, representative rules, protected relationships, non-polygon review
safety, and a map-edge fragment. This is an initial policy contract, not the
complete metric, encoding, geometry-repair, cancellation, and deterministic
output golden suite.

## Current local integration check

The current working tree was rerun on Windows with QGIS 3.40.5 and Python
3.12.9 on 2026-08-13. `test_metric_context.py` plus every `test_qgis_*.py`
module passed 84/84. This supersedes the earlier local counts because
additional regressions were added, including cross-CRS measurement, terminal
manifest, invalid pre-clip repair, contained-boundary distance, and protection
code-collision, typed cross-family review, entity-versus-number cases,
preservation-site identifier safety, and normalized geometry hashing. It
is diagnostic local evidence. The pinned QGIS 3.44.13 workflow subsequently
passed 84/84 tests, the indexed benchmark, and installable-ZIP import on GitHub
Actions. Its machine-readable record is
`qgis-3.44.13-github-2026-08-13.json`.
The machine-readable local record is
`qgis-3.40.5-windows-2026-08-13.json`; it explicitly marks the working tree as
dirty and is therefore diagnostic rather than release evidence.

The rebuilt `ArchDistribution-1.0.5.zip` was also CRC-checked, inspected for
its one-directory QGIS layout, extracted into a clean temporary plugin path,
and loaded through `classFactory` in QGIS 3.40.5. Its diagnostic checksum and
the list of provenance-blocked assets are recorded in
`package-qgis-3.40.5-windows-2026-08-13.json`. This does not replace the pinned
QGIS 3.44 CI installation evidence or an independent external-user test.

## Current synthetic benchmark

| Runtime | Features | Candidate pairs | All-pairs baseline | Time | Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| QGIS 3.40.5 / Python 3.12.9 / Windows | 100,000 | 398,104 | 4,999,950,000 | 27.280 s | 164.188 MiB |
| QGIS 3.44.13 / Python 3.12.3 / Linux CI | 100,000 | 398,104 | 4,999,950,000 | 3.242 s | 250.699 MiB |

The committed measurement was produced by
`validation/benchmark_spatial_index.py`. It measures synthetic local candidate
generation, not end-to-end nationwide source loading. The maximum query result
was nine records, demonstrating bounded spatial-index work rather than a full
pairwise comparison. The pinned QGIS 3.44.13 CI replication passed.
