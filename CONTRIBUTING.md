# Contributing to ArchDistribution

Thank you for helping improve this archaeological research software. Bug
reports, synthetic regression cases, documentation corrections, translations,
and carefully scoped code changes are welcome.

## Before opening an issue

- Search existing issues and state the ArchDistribution, QGIS, Qt, Python,
  GDAL, GEOS, PROJ, and operating-system versions when relevant.
- Reduce data problems to a wholly synthetic example whenever possible.
- Never attach exact site coordinates, national source layers, restricted
  administrative data, credentials, or personal information to a public issue.
- Describe expected archaeological relationships separately from expected map
  numbering. Spatial overlap alone is not evidence of identity.

If a bug can only be reproduced with restricted material, first open an issue
containing no data and ask the maintainer for a safe disclosure route.

## Development checks

Use a QGIS-supported Python version. Pure policy modules should remain
importable without QGIS. Before proposing a change, run:

```bash
python -m py_compile arch_distribution.py arch_distribution_dialog.py heritage_matching.py heritage_matching_dialog.py heritage_identity_store.py run_artifacts.py
python -m unittest test_heritage_matching test_heritage_grouping test_cartographic_filtering test_preservation_actions test_heritage_identity_store test_run_artifacts
python verify_guardrails.py
```

Run the `test_qgis_*.py` integration suite in a compatible QGIS environment.
The CI workflow uses QGIS 3.44 LTR; any future QGIS 3.28 compatibility claim is recorded with the
manual template under `validation/templates/`. Creating a ZIP for local
installation requires a `Desktop` directory:

```bash
python create_zip.py
```

Do not update golden outputs merely to make a failing test pass. Compare the
change with `docs/research/ontology-and-decision-rules.md`, document intentional
policy changes, and version the rule set.

## Change requirements

- Preserve original geometry and attributes; destructive source edits are not
  acceptable.
- Add a synthetic regression case for changes to matching, grouping, metric
  calculations, encoding, cancellation, or manifests.
- Keep site entity, investigation, geometry group, relationship, and map number
  concepts distinct.
- Record any schema, rules, or compatibility change in `CHANGELOG.md`.
- Update English and Korean user-facing text together where applicable.
- Do not claim pilot accuracy, productivity gains, external usability, or a DOI
  without committed, reviewable evidence.

## Pull requests and review

Keep pull requests focused and explain the user-visible behaviour, risk of
false merge or missed link, test evidence, and data/licence impact. A
maintainer may preserve a useful request while declining a particular
implementation. Closing a pull request does not erase its discussion or
attribution.

Contributors certify that they have the right to submit their work under the
applicable licence in `LICENSES.md`. Do not submit third-party data or media
without documented redistribution permission.

## Research validation

Follow `docs/research/validation-protocol.md`. Pilot labels must be created
without viewing the plugin recommendation, and project-based splits must
prevent leakage between development and locked evaluation. Raw real-data pairs
remain outside the public repository; only approved non-sensitive aggregates
are committed.
