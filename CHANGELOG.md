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
- A language-neutral name relation (equal, alias, omitted qualifier, more
  specific part, conflicting designator, sibling, unrelated) and footprint
  relation (identical, similar, contained, overlapping, near, apart) recorded
  for every candidate as `NAME_REL` and `GEOM_REL`. Designator units, ordinal
  letters, equivalent suffixes, and generic names are data in
  `matching_rules.json` (ruleset 1.1.0).
- Same-register rules: spelling variants and split pieces share one number,
  parts such as individual tombs or buildings join their named site, and
  numbered siblings (`1호`/`2호`, `I`/`II`) are never one entity. Union merges
  keep every footprint under one `NUMBER_KEY`. Differently named records
  drawn on one footprint are offered for review as linked records with
  separate numbers, never as a recommended merge.
- Surface-survey relations: a survey that redraws or extends a mapped site,
  or a survey zone inside a site, is offered as a merge-recommended review
  candidate; surveys are still never merged automatically.
- Record exclusion rules in `exclusion_rules.json` (intangible, movable,
  natural, no-remains outcome) shown as `[Rule]` rows after the attribute
  scan, with report-practice defaults and a `제외_기록` audit layer.
- A "Designated parts inside a site" choice in the duplicate panel: a
  designated or registered part (a pavilion inside a fortress) keeps its own
  number (default) or joins the site's number. Published reports do both.
  Its legal boundary stays in the designated-area layer either way, excavated
  parts always keep their own number, and decisions saved under the other
  choice are not reused.
- Numbering can follow the compass, clockwise from north (sites touching the
  study area first), and can put groups made only of excavation or survey
  records after the known sites in the same order. Both patterns were found
  in published nearby-site tables.
- Optional report-style nearby-site table (number, name, period, type,
  location, distance, source, remarks) written as Hangul HWPX and UTF-8 CSV.
  Period and address cells are summarised by rules in `table_lexicon.json`.

### Changed

- Attribute scan and analysis now inspect DBF character records and reload a
  CP949 Shapefile automatically even when QGIS initially opens it as UTF-8.
- Attribute classification now reconnects exact, registered historical
  reference assets already present in a user's QGIS plugin backups. The files
  remain local and are still excluded from the public ZIP.
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
- Records left out by the operator's period/type choices or name exclusion
  list are kept in the `제외_기록` audit layer (`user_category`,
  `user_name`) instead of being dropped without a trace.
- Address equality counts as identity evidence only when lot numbers match;
  sharing a village name is no longer enough.
- Dialog sections follow the order of decisions (Data: inputs, roles and
  duplicates, legal layers, attribute classification and exclusion, print
  extent; Style: symbols, labels, buffers, numbering, follow-up). Each rule
  checkbox sits with the setting it depends on, and the duplicate
  "renumber active layer" button is hidden in favour of the follow-up card.
- The layer lists skip layers inside the plugin's own result groups instead
  of hiding user layers by name, and a likely study area is preselected.
- The help and the duplicate-rule guide are rewritten around the three-step
  name, footprint, and register decision.

### Fixed

- Designated heritage merged with a distribution-map record lost its map
  number; designated records are now numbered unless a run draws legal
  boundaries only.
- Shapefile sidecars with upper-case extensions (`.DBF`, `.CPG`) were not
  found during encoding detection.
- Change-zone field detection scanned every feature twice.
- With a JPG, PDF, GeoPackage or site-table output enabled, a run could end
  in a fatal error when the source layers had many fields: the run summary
  probed each result layer's memory URI as a file path, which exceeds the
  file-name length limit. Memory layers are no longer treated as files.
- A record repeated by two regional downloads (same source identity) no
  longer appears as a review candidate against itself.
- A numbered feature named after its place ("<place> 44호분",
  "<site> tomb 44") was read as the parent of its group ("<place> 고분군",
  "<site> tombs"), so the tomb never joined the group. Feature units are now
  data (`feature_units` in `matching_rules.json`); investigation rounds such
  as `6차` are not features, and a group name that continues with a lot
  number is not treated as the group.
- The help's name-relation examples are explicit pairs checked against the
  classifier by a test, and use public designated-heritage names only.
- A lot number in brackets ("<village>(49-6) house plot") was read as an
  alias and dropped, so neighbouring lots investigated under the same
  boilerplate title compared as one name. Bracketed lot numbers now stay in
  the name (`lot_units` in `matching_rules.json`); designation numbers and
  former names in brackets are still aliases.
- Surface-survey records sharing a project name shared one map number,
  contrary to the rule that surveys are never merged automatically. Only
  excavation projects share a number; a survey project is kept as
  `INVESTIGATION_KEY`.
- A designated or registered heritage and its distribution-map copy with the
  same name (or the name without its region prefix) drawn a few metres apart
  were two numbers, or a review row each. Within 50 m they now merge
  automatically under the designated record (not in the conservative preset,
  never for generic names or other source combinations).
- Two names that only share a stem ("<place> fortress" / "<place> temple")
  were offered as a recommended merge. They are now recommended as linked
  records unless they name the same lot, differ only by unspecific words
  (`unspecific_names`), or share their distinctive core under a different
  qualifier.

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
