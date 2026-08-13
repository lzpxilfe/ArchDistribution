# JOSS software-paper evidence and future validation

Last updated: 2026-08-13

| Item | Target or scope | Current state | Evidence |
| --- | --- | --- | --- |
| Pure Python CI | Python 3.9 and 3.12 pass | Passed on GitHub Actions; local Python 3.12 suite passes (122 run, 12 QGIS-dependent skips) | `test_*.py`, `.github/workflows/ci.yml` |
| QGIS integration CI | QGIS 3.44 LTR suite and ZIP import pass | Passed 84/84, 100k benchmark, CRC, and headless ZIP factory in QGIS 3.44.13 CI | `qgis-3.44.13-github-2026-08-13.json`, `test_metric_context.py`, `test_qgis_*.py` |
| Synthetic golden suite | All cases pass; zero false merge/source deletion | Initial public policy contract passes 13/13; broader golden suite pending | `fixtures/policy_cases.json`, `expected/policy_cases.json` |
| Metric tolerances | 0.01 m / 0.1 m / 0.5% thresholds pass | Four-CRS regression passes in QGIS 3.40.5 locally and QGIS 3.44.13 CI | `test_metric_context.py`, `qgis-3.44.13-github-2026-08-13.json` |
| Geometry-family safety | Point/line/polygon outputs remain separated | Implemented; mixed-family regression passes locally and in QGIS 3.44.13 CI | `test_qgis_matching_integration.py` |
| Directional containment | A→B and B→A ratios are persisted and tested | Implemented as `COVER_A`/`COVER_B`; unit and local QGIS suite pass; broader golden coverage pending | `test_heritage_matching.py`, `arch_distribution.py` |
| Encoding choice | Per-layer UTF-8/CP949 choice and manifest evidence | Implemented in both workflows; selector and manifest tests pass locally and in CI | `test_qgis_dialog_workflows.py`, `test_run_artifacts.py` |
| 100k benchmark | Indexed completion without memory error | Passed on Windows/QGIS 3.40.5 and Linux/QGIS 3.44.13 CI | `benchmark-qgis-3.40.5-windows.json`, `qgis-3.44.13-github-2026-08-13.json` |
| Planned single-reviewer pilot | 300 pairs; precision ≥0.98, recall ≥0.95 | Future empirical validation; outside the accuracy claims of the current software paper | — |
| Research workflows | Document operational use without exposing sensitive coordinates | One developer-led workflow documented; two additional workflows are a future validation target | `real-workflow-2024-0745.md` |
| External GIS test | Independent ZIP install and synthetic run | Recommended by JOSS for new software; not yet reported as complete | — |
| Minimum QGIS claim | Declared minimum has executable integration evidence | Minimum raised to 3.40; local QGIS 3.40.5 suite and clean ZIP factory pass | `metadata.txt`, `qgis-3.40.5-windows-2026-08-13.json`, `package-qgis-3.40.5-windows-2026-08-13.json` |
| Data/licence audit | Redistributable release contents confirmed | Unapproved `reference_data.json` and `smart_patterns.json` are withheld from the installable ZIP and current JOSS snapshot; audit remains required before any future redistribution | `docs/research/reference-data-register.json`, `package-qgis-3.40.5-windows-2026-08-13.json` |
| AI disclosure | Tool/model, scope, and human verification stated | Complete for the August 2026 manuscript revision; historical model identifiers unavailable from contemporaneous records are not guessed | `docs/research/ai-usage.md`, `paper/paper.md` |
| DOI/archive | Archive the accepted version | Created after successful JOSS review, following the journal's release sequence | — |

The completed technical rows support the claims made in the software paper.
The pilot, additional workflows, and external installation remain explicitly
uncompleted and must not be used to claim archaeological accuracy, quantified
labour savings, or external adoption. They are future validation rather than
JOSS-mandated numerical thresholds. Any release candidate must still pass the
applicable CI and package checks recorded above.
