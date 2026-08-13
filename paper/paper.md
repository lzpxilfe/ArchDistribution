---
title: "ArchDistribution: A QGIS plugin for reconciling and mapping archaeological spatial records"
tags:
  - Python
  - QGIS
  - archaeology
  - cultural heritage
  - spatial data
  - record linkage
authors:
  - given-names: Jinseo
    surname: Hwang
    orcid: 0009-0000-8228-4083
    corresponding: true
    affiliation: "1"
affiliations:
  - index: 1
    name: Nuri Institute for Archaeology, Republic of Korea
date: 13 August 2026
bibliography: paper.bib
---

# Summary

Archaeological distribution maps show a proposed investigation or development area in relation to previously documented heritage. Preparing one may require legal designations, inventory areas, surface surveys, excavation projects, and protection boundaries. The same place can appear once as a protected monument, again as an inventory polygon, and several more times as fieldwork records. Treating every intersecting feature as a separate site duplicates labels. Dissolving every overlap can erase independent investigations, component monuments, or legal relationships.

ArchDistribution [@hwang2026archdistribution] is a QGIS plugin that prepares numbered, print-ready map layers while keeping these distinctions explicit. It assigns a role to each input, restricts comparison to the requested map extent, and applies versioned spatial and textual rules to suggest possible relationships. Users inspect uncertain cases and decide whether the source entries remain separate, are linked, or share a displayed number. Original geometries, attributes, decisions, and investigation histories remain available in audit outputs and a run manifest.

The plugin was developed for Korean archaeological reporting, where shapefiles from several administrative and research systems must be reconciled for individual projects. Its data model separates archaeological entities, investigation events, geometry groups, and map numbers. A map can therefore be simplified without claiming that the underlying entries are identical.

# Statement of need

GIS is routine infrastructure for archaeological documentation and interpretation [@mccoy2017geospatial; @qgis], but producing a distribution map requires decisions that a spatial join cannot make. Overlap may indicate identity, containment, a sequence of investigations, a legal relationship, or coincidence. Names also vary across institutions and over time, and a project may be divided into several recorded subareas. Removing apparent duplicates without preserving these distinctions can alter the evidential and administrative history of a site.

ArchDistribution arose from the author's excavation-report work in the Republic of Korea. National and institutional shapefiles supplied the source information, but each report still required repeated selection, buffering, comparison, styling, labeling, and renumbering to produce a legible map of previously recorded sites around the project area.

The intended users are archaeologists, heritage consultants, local-government heritage staff, and GIS technicians who prepare or audit these maps. Measurements must use a valid metric coordinate reference system (CRS). Site identity, investigation grouping, and displayed numbering require separate identifiers. Each recommendation also needs an audit trail that connects it to the relevant rule, source evidence, and human decision. Expert judgment remains part of the process, but its effect on the result becomes inspectable and repeatable.

# State of the field

QGIS provides the spatial indexes, geometry operations, joins, and print layouts required for this work [@qgis]. Its generic predicates can identify intersections, but they cannot determine whether two heritage entries describe the same site, an investigation at a site, or a monument and its protection boundary. ArchDistribution builds on the QGIS processing engine and adds the domain policy needed for archaeological report mapping.

Korean studies have proposed distribution-map data models for regional heritage management and national GIS integration [@jang2008distribution]. More recent work describes a GeoJSON and Web GIS model connecting prehistoric sites, excavation reports, artifacts, research, education, and public services [@ku2025korean]. The Archaeological Map of the Czech Republic distinguishes projects, fieldwork events, and sites [@kuna2017amcr]. Research on repeated surveys also shows why inconsistent locations may reflect changes in observation rather than a simple database error [@drillat2024reconciling]. These projects establish the need to distinguish sites, investigations, and documentary sources.

Arches supports persistent heritage inventories [@myers2016arches], while OpenAtlas provides a web-based research environment based on the CIDOC Conceptual Reference Model [@filzwieser2020openatlas]. These systems address persistent inventory and research-data management. ArchDistribution addresses the narrower task of reconciling supplied shapefiles into a numbered QGIS report map. A plugin retains QGIS geometry and layout tools without replacing institutional inventory systems or adding jurisdiction-specific semantics to QGIS core.

Record-linkage methods compare imperfect descriptions [@fellegi1969theory], and cultural-heritage ontologies support typed relationships [@doerr2003cidoc]. ArchDistribution uses similarity to nominate a relationship, not to prove that two rows are interchangeable. A protection boundary, an excavation, and a designated monument may overlap closely while remaining different objects. Retaining the rules, source evidence, and human decisions supports inspection and reuse in keeping with FAIR principles [@wilkinson2016fair].

# Software design

Users first assign source roles such as designated heritage, protection boundary, distribution-map entry, surface survey, or excavation. Measurements are performed in an explicit metric analysis CRS, separate from the source and output CRSs. A missing or untransformable CRS stops the run. Processing is then restricted to the requested map extent, and a spatial index generates candidate pairs. This bounded comparison avoids an exhaustive search. In the 100,000-feature synthetic benchmark, the index returned 398,104 candidates instead of 4,999,950,000 possible pairs.

The workflow is summarized in \autoref{fig:workflow}.

![Role-assigned inputs are measured in an explicit metric context. Extent filtering and spatial indexing bound the comparisons. Versioned rules and human review produce separate identifiers and typed relations, while geometry-family outputs preserve source evidence beside the printable map, audit table, and run manifest. \label{fig:workflow}](figures/archdistribution-workflow.svg)

Versioned rules evaluate candidate pairs using source roles, normalized names, directional containment, intersection over union, area ratio, and distance. The resulting relation types distinguish identity, an investigation at a site, a legal boundary around a site, a parent and component, related but separate entries, and uncertainty. A user can keep a pair separate, link it, or assign a shared representative number. One excavation project may share a numbering key without forcing all named sites in that project to share an entity key. Only a confirmed identity decision enters equivalence clustering. Unresolved matches remain visible for review because a false merge may erase a meaningful distinction.

Point, line, and polygon results remain in separate geometry families while sharing one numbering sequence. This prevents geometry loss from forced conversion, and cross-family matches always require review. Invalid working geometries may be repaired, but every repair or exclusion is recorded. Source attributes remain intact, and non-representative entries are retained in a preservation layer and audit table. Provider settings and `.cpg` files determine text encoding by default, with per-layer UTF-8 and CP949 overrides available when needed.

A run manifest records the plugin and ruleset versions, processing environment, input hashes, encoding decisions, geometry repairs, review-cache identity, output counts, terminal status, and normalized content hashes. Its public form omits local paths and credential-like values. Explicit `success`, `partial_success`, `failed`, and `cancelled` states prevent incomplete runs from being presented as complete results.

# Research impact statement

The repository provides versioned rules, synthetic fixtures, installation and contribution documentation, CI definitions, and machine-readable validation results. Thirteen committed policy cases cover entity identity, investigation grouping, numbering, protection boundaries, geometry families, and map-edge behavior. Windows with QGIS 3.40.5 and Linux with QGIS 3.44.13 each pass 84 automated tests, including 68 QGIS integration tests. In the synthetic 100,000-feature benchmark, candidate generation completed in 27.28 s with 164.19 MiB peak memory on the local Windows environment and in 3.24 s with 250.70 MiB in CI. These measurements concern indexed candidate generation, not nationwide ingestion or archaeological accuracy.

On 11 August 2026, the developer used ArchDistribution while preparing a surrounding-site map for an excavation-report workflow at Nuri Institute for Archaeology. The project concerned a housing-development site at 227-2, Ungjin-dong, Gongju. The public permit register independently establishes the project context: a 2,252 m² rescue excavation associated with permit 2024-0745 and completed on 12 August 2024 [@khs2026permit]. The register does not document software use; that statement comes from the author's workflow record. ArchDistribution combined filtering, clipping, numbering, styling, and map preparation in one reviewable process. No contemporaneous manual-time baseline was recorded.

The available evidence demonstrates developer-led operational use and reproducible software behavior. It does not establish a numerical estimate of labor saved, independently validated archaeological classification accuracy, external adoption, or generalization across institutions. Future evaluation will require independent reviewers and use across institutions.

# AI usage disclosure

OpenAI Codex, including the `gpt-5.6-sol` model for the August 2026 software and manuscript revision recorded in this repository, assisted with code suggestions and refactoring, test scaffolding, documentation organization, and language editing. Historical Codex session records did not retain every underlying model identifier, so unavailable identifiers were not reconstructed.

Jinseo Hwang defined the archaeological problem and domain policy and made the principal design decisions. He reviewed and modified the assisted outputs, then checked them through code inspection, expected cases derived from the written rules, static analysis, and QGIS execution. AI output was not used as archaeological evidence or as a reference label. The author accepts responsibility for the accuracy, originality, licensing, and ethical compliance of the software and manuscript. The repository contains a detailed use record in `docs/research/ai-usage.md`.

# Acknowledgements

This work received no external funding or dedicated institutional support. The author declares no competing interests.

# References
