---
title: "ArchDistribution: reproducible human-in-the-loop reconciliation of archaeological spatial records in QGIS"
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
    corresponding: true
    affiliation: "1"
affiliations:
  - index: 1
    name: Nuri Institute for Archaeology, Republic of Korea
date: 13 August 2026
bibliography: paper.bib
---

# Summary

An archaeological distribution map situates a proposed research or development area among previously recorded sites, surveys, excavations, and legally protected places. Producing one may require records from national and local designation systems, municipal inventories, surface surveys, excavation projects, and protection boundaries. These records do not describe the same kind of thing. A designated monument is a legal heritage entity, an excavation record is an investigation event, an inventory polygon is an interpretation, and a protection zone is a regulatory boundary. Nevertheless, their names and geometries frequently overlap. Numbering every intersecting feature can count one place several times, while dissolving every overlap can erase distinct investigations, component monuments, or legal relationships.

ArchDistribution is a QGIS plugin for producing distribution-map layers while retaining these distinctions. Its central contribution is not cartographic automation alone. It implements an explicit, inspectable policy for deciding which records share a displayed number, which may represent the same archaeological entity, and which remain separate but linked. Versioned rules generate candidates from indexed spatial comparisons and normalized descriptive fields; rule-defined automatic recommendations can be inspected, and ambiguous cases enter a human review table. Source records and investigation histories are preserved even when the final map shows one representative label.

Designed for Korean workflows, the software addresses a wider inventory problem: administrative status, archaeological interpretation, fieldwork events, and cartographic representation must not be collapsed into one identifier. ArchDistribution makes that separation operational and auditable in QGIS.

# Statement of need

GIS is now routine infrastructure for archaeological documentation and interpretation [@mccoy2017geospatial; @qgis]. Yet archaeological map production still involves manual comparison between datasets created by different institutions, at different times, for different purposes. Names vary, project areas are divided into subareas, boundaries are revised, and one place may be represented by a legal designation, an inventory polygon, and several excavation episodes. A spatial join can expose intersections but cannot decide whether they mean identity, containment, research history, or coincidence. Generic duplicate removal is risky because archaeological records carry evidential and administrative histories that should remain recoverable.

The project arose from the author's excavation-report workflow in the Republic of Korea. Site information was supplied as SHP layers through national and institutional systems, but the report still required a legible map of the previously recorded sites surrounding the investigated parcel. Repeating selection, buffering, styling, labelling, comparison, and renumbering for each report exposed a gap between data provision and archaeological communication.

ArchDistribution is intended for archaeologists, heritage consultants, local-government heritage staff, and GIS technicians who prepare or audit these maps. It addresses three practical requirements. First, buffers, distances, areas, and print extents must be calculated in a suitable metric coordinate reference system rather than merely labelled with one. Second, entity identity must be separated from investigation grouping and map numbering. Areas belonging to one excavation project can share a number without asserting that every named site in the project is one entity. Third, every automated recommendation must be traceable to a versioned rule, input evidence, and a review decision.

Duplicate numbering can misstate the distribution of known sites, while aggressive merging can conceal significant distinctions. A reproducible human-in-the-loop workflow makes both risks and the remaining judgement visible.

# State of the field

QGIS already provides spatial joins, duplicate-geometry removal, spatial indexes, geometry processing, and print layouts [@qgis]. Those are necessary primitives, but their generic predicates do not express whether two heritage records are the same site, a site and an investigation, or a monument and its legal boundary. ArchDistribution therefore extends QGIS rather than reimplementing its GIS engine.

Korean research established distribution maps as standardized spatial and attribute products for regional management and national GIS integration [@jang2008distribution], and later proposed a shared GeoJSON and Web GIS model connecting prehistoric sites, excavation reports, artefacts, research, education, and public services [@ku2025korean]. Internationally, the Archaeological Map of the Czech Republic distinguishes projects, fieldwork events, and sites [@kuna2017amcr], while reconciliation of repeated surveys shows that one settlement can be split into multiple recorded sites [@drillat2024reconciling]. These works address inventory integration, information services, or analytical reconciliation. ArchDistribution starts from supplier SHP layers in professional practice and addresses the bounded production problem of turning them into an auditable, numbered, print-ready surrounding-site map for a report.

Arches manages heritage inventories [@myers2016arches], while OpenAtlas is a web-based, CIDOC CRM-oriented research system [@filzwieser2020openatlas]. They address persistent inventory management and interoperability, not project-level reconciliation of supplier layers into a print-ready QGIS map. A focused plugin avoids replacing established institutional systems.

Cultural-heritage ontologies demonstrate the value of structured relationships [@doerr2003cidoc], and record-linkage research provides a framework for comparing imperfect descriptions [@fellegi1969theory]. However, similarity alone is not an ontology: near-identical names and geometries can denote a monument and protection area, or a site and an investigation within it. ArchDistribution treats similarity as evidence for a typed relationship, not proof that two rows are interchangeable. Legal boundaries remain unnumbered, survey records are not silently discarded, designation and excavation can remain separately numbered, and parent--component relationships do not become identity merely through overlap. This auditability also supports the FAIR emphasis on reusable data and computational decisions [@wilkinson2016fair].

# Software design

The plugin follows a staged workflow inside QGIS. Users select layers and confirm roles such as designated heritage, protection boundary, distribution map, surface survey, or excavation. Processing is restricted to the requested map extent before a spatial index generates comparison candidates. This trades exhaustive pairwise matching for bounded local comparison: in the documented 100,000-feature synthetic benchmark, the index produced 398,104 candidate pairs rather than 4,999,950,000 theoretical pairs. Source files are never edited, and invalid working geometries are repaired before spatial operations with repairs and exclusions recorded.

![Figure 1: ArchDistribution workflow. Role-assigned inputs are evaluated in an explicit metric context; extent filtering and spatial indexing bound comparisons. Versioned rules and human review produce distinct identifiers and typed relations, while geometry-family outputs preserve source evidence beside the printable map, audit table, and run manifest.](figures/archdistribution-workflow.svg)

Candidate pairs are evaluated with versioned rules combining normalized names, source roles, directional coverage, intersection-over-union, area ratio, and distance. Identity, investigation--site, legal-boundary--site, parent--child, related-but-separate, and uncertain relations remain distinct. The interface records whether a pair stays separate, is linked, or shares a representative number. One excavation project may share a numbering key while retaining distinct entity keys. Only confirmed identity is eligible for equivalence clustering. This deliberately favours review over aggressive automation because a false merge can remove a meaningful distinction, whereas an unresolved candidate remains visible to a person.

Outputs preserve source attributes and add stable fields for investigation, site entity, geometry group, relationship, numbering, rule, and match status. A preservation layer and review table retain non-representative records. A run manifest records software and rule versions, environment, input bundle hashes, encodings, repairs, review-cache identity, counts, status, and normalized content hashes, while public manifests remove local paths and sensitive values. `success`, `partial_success`, `failed`, and `cancelled` states prevent incomplete outputs from being mistaken for complete runs.

Metric processing separates source, analysis, and output coordinate systems. Geographic or non-metric inputs use an explicit local metric analysis CRS; missing or untransformable metadata stops the run. Point, line, and polygon outputs remain family-specific but receive one continuous number sequence, avoiding geometry loss from forced merging. Automatic identity is restricted to polygon--polygon pairs; cross-family pairs are review-only. Per-layer encoding choices follow provider or `.cpg` declarations unless a user explicitly selects UTF-8 or CP949.

# Research impact statement

ArchDistribution turns tacit production decisions into reviewable computational policy. The public repository contains installation instructions, contribution guidance, versioned rules, synthetic fixtures, CI definitions, and machine-readable validation records. This infrastructure supports reuse in contract archaeology, local-government work, heritage-impact assessment, and research mapping, and provides a basis for studying where automated reconciliation succeeds or must defer to expert judgement.

Validation is intentionally conservative. A public fixture passes 13 ontology, matching, and cartographic-safety cases. The latest local QGIS 3.40.5 diagnostic run passes 84 metric and integration tests, and the indexed 100,000-feature benchmark completed in 27.28 s with 164.19 MiB peak resident memory on the documented Windows environment. These local results must be regenerated from the release commit in public CI. The benchmark measures candidate generation, not end-to-end nationwide processing or archaeological accuracy.

The first documented research use was on 11 August 2026, during preparation of an excavation report for the archaeological site within a housing development project at 227-2, Ungjin-dong, Gongju (Korean Heritage Service excavation permit no. 2024-0745) at Nuri Institute for Archaeology. The public permit register records a 2,252 m² rescue excavation completed on 12 August 2024 [@khs2026permit]. The plugin supported production of the surrounding-site distribution map from national shapefile datasets. The reporting task also motivated development: repeated selection, buffering, styling, labelling, and renumbering operations were consolidated into one reviewable workflow. The author observed a substantial practical reduction in repetitive manual work, but no contemporaneous manual-time baseline was recorded; the paper therefore reports operational use rather than a quantified productivity effect.

Before submission, a disclosure-reviewed aggregate record of that workflow must add the exact plugin version, input counts, candidate counts, and human corrections. The 300-pair blinded single-reviewer pilot, two further anonymized workflows, an external GIS installation test, and QGIS 3.44 CI also remain pending. Until those release gates are complete, the paper does not claim validated archaeological accuracy, quantified labour savings, or cross-institutional generalization, and it is **not ready for JOSS submission**.

# AI usage disclosure

OpenAI Codex assisted with code suggestions and refactoring, test scaffolding, documentation structure, and drafting and language revision of this paper. Model identifiers for earlier sessions were not retained and will not be guessed; every identifier recoverable from the research-hardening record will be listed in the release-specific disclosure. Jinseo Hwang framed the archaeological problem, defined the domain policy, made the core design decisions, and reviewed, edited, and validated all AI-assisted outputs through code inspection, independent expected cases, static checks, and QGIS execution. AI output was not used as archaeological evidence or as a gold-standard label. The author retains responsibility for accuracy, originality, licensing, and ethical compliance. The detailed disclosure is maintained in `docs/research/ai-usage.md`.

# Acknowledgements

Software development received no external funding or dedicated institutional support. The author declares no competing interests.

# References
