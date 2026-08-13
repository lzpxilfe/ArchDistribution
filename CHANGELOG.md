# Changelog

All notable changes to ArchDistribution are documented here. This project uses
plugin version `1.0.5` while the JOSS research snapshot is prepared; research
tags do not change the installable plugin version.

## Unreleased — JOSS research preparation

### Added

- A shared metric context that validates CRS metadata, selects a local UTM for
  geographic or non-metric inputs, and records source/analysis/output CRS
  provenance.
- Public investigation, site-entity, geometry-group, and typed-relationship
  fields while retaining `ENTITY_KEY` as a compatibility alias.
- A versioned JSON matching rule set with a recorded SHA-256 and additional
  directional coverage, IoU, area-ratio, centroid-distance, and
  boundary-distance evidence.
- Geometry-family-separated point, line, and polygon results with one
  continuous number sequence.
- Explicit per-layer UTF-8/CP949 selectors that preserve `.cpg` and provider
  defaults unless an operator chooses an override.
- Run-manifest schema v2 with explicit statuses, environment and CRS
  provenance, input-bundle checksums, excluded layers, and semantic hashes.
- Pure-Python, leakage-resistant project splitting, blinding, and scoring
  utilities and a private-data CLI for the pending single-reviewer pilot.
- JOSS manuscript, verified bibliography, and workflow figure.
- Research specifications for ontology, validation, provenance, limitations,
  AI usage, and reproducibility.
- Synthetic-validation directory contract, release-gate status, and blank
  templates for pilot, external, real-workflow, and QGIS 3.28 tests.
- Citation metadata and a repository licence matrix.
- GitHub Actions definitions for pure Python checks, QGIS 3.44 integration,
  plugin ZIP verification, and JOSS paper compilation.

### Changed

- The JOSS manuscript now separates demonstrated software behaviour and one
  developer-led research use from future accuracy, adoption, and productivity
  studies; internal readiness notes no longer appear in the paper.
- Mixed-geometry family separation, directional containment evidence, and
  per-layer encoding selection pass QGIS 3.44 CI; broader golden-fixture
  coverage remains part of the future validation programme.
- Preservation-area numbering accepts only exact semantic supplier site-ID
  fields; generic `CODE` fields and incomplete name/address fallbacks cannot
  collapse unrelated records into one number.
- Installable research ZIPs include the licence matrix and withhold reference
  assets until the provenance register explicitly approves redistribution.
- The declared minimum QGIS version is raised from 3.28 to 3.40 because the
  available 3.28 installation could not supply a complete test runtime; the
  claim now matches the locally verified QGIS 3.40.5 baseline.

## 1.0.5

- Current plugin release line. See Git history and README for the implemented
  mapping, preservation-area, duplicate-review, and renumbering workflow.
- Research documentation and journal metadata are versioned separately and do
  not change the installable plugin version.

## Historical tags

Historical Git tags and plugin metadata have not always represented the same
development snapshot. Existing tags will not be deleted, moved, or rewritten.
The JOSS process will use the unambiguous tags `joss-v1.0.5-rc1` and
`joss-v1.0.5` only after their documented release gates are met. Neither tag
has been created as part of this preparation.
