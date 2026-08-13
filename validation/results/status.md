# JOSS research-release validation status

Last updated: 2026-08-13

| Gate | Required criterion | Current state | Evidence |
| --- | --- | --- | --- |
| Pure Python CI | Python 3.9 and 3.12 pass | Passed on GitHub Actions; local Python 3.12 suite passes (122 run, 12 QGIS-dependent skips) | `test_*.py`, `.github/workflows/ci.yml` |
| QGIS integration CI | QGIS 3.44 LTR suite and ZIP import pass | Passed 84/84, 100k benchmark, CRC, and headless ZIP factory in QGIS 3.44.13 CI | `qgis-3.44.13-github-2026-08-13.json`, `test_metric_context.py`, `test_qgis_*.py` |
| Synthetic golden suite | All cases pass; zero false merge/source deletion | Initial public policy contract passes 13/13; broader golden suite pending | `fixtures/policy_cases.json`, `expected/policy_cases.json` |
| Metric tolerances | 0.01 m / 0.1 m / 0.5% thresholds pass | Four-CRS regression passes in QGIS 3.40.5 locally and QGIS 3.44.13 CI | `test_metric_context.py`, `qgis-3.44.13-github-2026-08-13.json` |
| Geometry-family safety | Point/line/polygon outputs remain separated | Implemented; mixed-family regression passes locally and in QGIS 3.44.13 CI | `test_qgis_matching_integration.py` |
| Directional containment | A→B and B→A ratios are persisted and tested | Implemented as `COVER_A`/`COVER_B`; unit and local QGIS suite pass; broader golden coverage pending | `test_heritage_matching.py`, `arch_distribution.py` |
| Encoding choice | Per-layer UTF-8/CP949 choice and manifest evidence | Implemented in both workflows; selector and manifest tests pass locally and in CI | `test_qgis_dialog_workflows.py`, `test_run_artifacts.py` |
| 100k benchmark | Indexed completion without memory error | Passed on Windows/QGIS 3.40.5 and Linux/QGIS 3.44.13 CI | `benchmark-qgis-3.40.5-windows.json`, `qgis-3.44.13-github-2026-08-13.json` |
| Single-reviewer pilot | 300 pairs; precision ≥0.98, recall ≥0.95 | Pending | — |
| Real workflows | Three anonymized observations recorded | One developer-led workflow identified; aggregate run counts and disclosure evidence pending, plus two further workflows | `real-workflow-2024-0745.md` |
| External GIS test | Independent ZIP install and synthetic run | Pending | — |
| Minimum QGIS claim | Declared minimum has executable integration evidence | Minimum raised to 3.40; local QGIS 3.40.5 suite and clean ZIP factory pass | `metadata.txt`, `qgis-3.40.5-windows-2026-08-13.json`, `package-qgis-3.40.5-windows-2026-08-13.json` |
| Data/licence audit | Redistributable release contents confirmed | Unapproved `reference_data.json` and `smart_patterns.json` are withheld from the installable ZIP and current JOSS snapshot; audit remains required before any future redistribution | `docs/research/reference-data-register.json`, `package-qgis-3.40.5-windows-2026-08-13.json` |
| AI disclosure | Release-specific record complete | Pending | — |
| DOI/archive | Zenodo version DOI recorded | Pending; create only after final release | — |

No `joss-v1.0.5-rc1` or `joss-v1.0.5` release should be described as validated
until every applicable gate is complete and linked here.
