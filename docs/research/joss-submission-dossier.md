# JOSS submission dossier / JOSS 투고 준비 문서

This is a working dossier for ArchDistribution 1.0.5. It separates facts that
are already evidenced from information that only the author can confirm. Text
inside square brackets must be replaced before submission. Do not infer or
invent missing institutional, funding, adoption, or research-use information.

## Current readiness decision / 현재 판단

**Do not submit yet.** The English paper is structurally complete, but JOSS's
pre-review screen requires demonstrated research use and sustained open
development, not only a functioning program and a polished manuscript.

| Requirement | Current evidence | Decision |
| --- | --- | --- |
| Public repository for more than six months | Public GitHub repository created 28 January 2026 | Date threshold met on 28 July 2026 |
| Development over time | 132 public commits before this research-hardening work; activity in January, February, March, and July 2026 | Real history exists, but the early burst makes continued public iteration advisable |
| Open-source practice | GPL licence, README, tests, CI definitions, changelog, contribution guide, issue tracker | Implemented locally; commit, push, and successful public CI are still required |
| Demonstrated research use | Developer use in excavation-report project 2024-0745 is now identified | Minimum use claim exists; disclosure-reviewed aggregate counts and evidence record are still required |
| External/community signal | Two external pull requests, one fork, and two stars; external installation test pending | Useful history, but external use evidence remains weak |
| Paper | English Markdown draft with all required sections | Working draft; author metadata and actual impact paragraph incomplete |
| Validation | 13 policy cases, 84 tests in the latest local QGIS 3.40.5 diagnostic run, indexed 100,000-feature benchmark | Useful technical evidence; regenerate it from the release commit in public CI; it is not a substitute for research use |
| Data/licence | `reference_data.json` and `smart_patterns.json` are withheld from both the installable ZIP and current JOSS snapshot; optional user-supplied loading remains supported | Exclusion implemented; provenance/licence confirmation is required only before either asset can be redistributed later |

The technical gate is tracked in
[`validation/results/status.md`](../../validation/results/status.md), but its
counts and generated result files must be refreshed from the final commit
before they are treated as release evidence.

## Author information to confirm / 저자 확인 정보

Complete every line. `ORCID` and `ROR` are optional; the other identity and
funding statements are not.

```text
Preferred published name: Jinseo Hwang
Corresponding author: yes (confirm before submission)
Email used for submission: [address]
GitHub username: lzpxilfe
ORCID: [0000-0000-0000-0000 / none]

Role: Archaeological researcher
Official department name in English: none reported
Official institution name in English: Nuri Institute for Archaeology
Country wording: Republic of Korea
Institution ROR (optional): [ROR / none]
If unaffiliated, approve: not applicable

Other qualifying authors: none reported
Confirm balguljang2 and lzpxilfe are the same author identity: [yes/no]
```

JOSS authors must have made a substantial contribution and consent to being
listed. Funding alone or general organizational supervision is not sufficient
for authorship.

## Funding, support, and conflicts / 연구비·지원·이해충돌

```text
External funding or grant: none
Dedicated institutional support for software development: none
Did a sponsor influence design, validation, writing, or submission? no
Relevant employment, consulting, financial, or professional interests: none reported beyond the stated affiliation
Confirmed wording for the paper: "Software development received no external funding or dedicated institutional support. The author declares no competing interests."
Confirmed wording for the submission form: "No external funding or dedicated institutional support was received for development of the software. The author declares no competing interests."
```

If there was no external funding and no competing interest, a possible final
form is: “This work received no external funding. The author declares no
competing interests.” The author must confirm that it is factually true.

## Demonstrated research-use evidence / 실제 연구 활용 증거

At least one genuine research use is a JOSS pre-review requirement. Three
anonymized workflows are planned because they make the evidence much stronger.
For each workflow, record facts contemporaneously rather than estimating them
later. Exact site coordinates, private identifiers, and restricted source data
must not be committed.

| Field | Workflow A | Workflow B | Workflow C |
| --- | --- | --- | --- |
| Anonymous identifier | 2024-0745 | [WF-B] | [WF-C] |
| Date and plugin version | Report dated 11 August 2026; exact plugin version to recover | [date/version] | [date/version] |
| Research or heritage-management purpose | Surrounding-site distribution map for an excavation report concerning the housing-development site at 227-2, Ungjin-dong, Gongju (descriptive translation; exact English report title not yet verified) | [purpose] | [purpose] |
| Input roles and feature counts | [counts] | [counts] | [counts] |
| Candidate and automatic-decision counts | [counts] | [counts] | [counts] |
| Human review decisions and corrections | [counts] | [counts] | [counts] |
| Failures, cancellations, or reruns | [facts] | [facts] | [facts] |
| Resulting research/report/map use | Excavation-report work performed on 11 August 2026 for the Gongju Ungjin-dong 227-2 project, Nuri Institute for Archaeology, Gongju, Chungcheongnam-do | [specific output] | [specific output] |
| Evidence available to editors | Author-held report record; e-Minwon portal entry; Korean Heritage Service public permit register (permit 2024-0745; 2,252 m² rescue excavation; fieldwork completed 12 August 2024); recover run manifest if available | [manifest/report statement] | [manifest/report statement] |
| Public disclosure level | Public project metadata and disclosure-reviewed aggregates only; no raw site coordinates | [level] | [level] |

Also list any scholarly or community signal:

```text
Published paper or preprint using ArchDistribution: none reported
Research report using an output: excavation-report work on 11 August 2026 for Korean Heritage Service permit 2024-0745, concerning the archaeological site within a housing development project at 227-2, Ungjin-dong, Gongju; exact report title and publication status still need confirmation
Conference or professional presentation: [citation / none]
External institution or researcher adoption: [evidence / none]
External installation and synthetic-example test: [tester/date/environment / pending]
Changes made in response to non-author feedback: [issues/PRs/commits]
```

## Related-publication disclosure / 관련 논문

JOSS asks whether any code or documentation has been, is being, or is planned
to be submitted elsewhere. Record the relationship without hiding a planned
archaeological-methods paper.

```text
Related publication exists or is planned: no specific publication is currently identified
Title and venue/status: none
Overlap with JOSS paper: not applicable at present
Why this is not duplicate publication: not applicable at present; any later archaeological-methods paper must report distinct empirical methods or results
```

## Release-specific AI disclosure / AI 사용 공개

The paper already identifies OpenAI Codex and its uses. Before submission,
complete this release record from verifiable logs only.

```text
Tool: OpenAI Codex
Verifiable model identifier(s): [identifier and source / unavailable]
Date or commit range: [range]
Code assistance: [files/tasks]
Test assistance: [files/tasks]
Documentation and paper assistance: [files/tasks]
Human reviewer: Jinseo Hwang
Human verification: [diff review, independent expected cases, static checks,
QGIS test versions, manual archaeological review]
Core decisions made by the author: [problem framing and domain-policy summary]
```

During JOSS review, generative AI must not write the substantive conversation
with editors or reviewers. JOSS permits translation assistance, but the human
author must make and communicate all evaluative judgements.

## Draft values for the online form / 온라인 양식 초안

- **Content type:** Software paper
- **Title:** `ArchDistribution: reproducible human-in-the-loop reconciliation of archaeological spatial records in QGIS`
- **Repository:** `https://github.com/lzpxilfe/ArchDistribution`
- **Branch containing paper:** leave blank if `paper/paper.md` is on `main`
- **Software version:** `v1.0.5` (confirm the final reviewed version)
- **Submission type:** `New submission`
- **Main subject:** select the closest subject offered by the live form, likely
  Archaeology, Digital Humanities, or Geographic Information Systems; do not
  enter an unlisted subject by assumption.

### Draft message to editors

Replace every bracketed field before pasting this into the JOSS form.

```text
ArchDistribution is a QGIS plugin for reproducible, human-in-the-loop
reconciliation of heterogeneous archaeological spatial records. It separates
archaeological site identity, investigation events, legal boundaries, geometry
grouping, and displayed map numbering while preserving source records and an
auditable review trail.

This is a new submission. The public repository has been available since
28 January 2026 and documents iterative development, tests, CI, release
preparation, and contribution pathways. The software was used to prepare the
surrounding-site distribution map for the 2026 excavation report for the
Gongju Ungjin-dong 227-2 site (administrative project 2024-0745). Before
submission, the repository record will provide disclosure-reviewed aggregate
counts and editor-verifiable evidence for that workflow.

[No part of this software paper or its code/documentation has been published
or submitted elsewhere / Describe the related publication and explain the
non-overlapping contribution.] The author plans [no related methods paper / a
separate archaeological-methods paper focused on ...]; that work does not
duplicate this software paper's contribution.

Generative AI use is disclosed in the paper and repository. OpenAI Codex
assisted with code proposals, test scaffolding, documentation, and language
revision; the human author made the domain and architectural decisions and
reviewed, edited, and validated all assisted outputs.

Funding and sponsor role: No external funding or dedicated institutional
support was received for software development, and no sponsor influenced the
design, validation, writing, or submission. Competing interests: The author
declares no competing interests.
```

## Required sequence before pressing Submit / 실제 순서

1. Confirm author name, affiliation, ORCID if any, funding, sponsor role, and
   competing interests.
2. Complete and document genuine research use. Update the paper's impact
   paragraph with specific evidence, not predicted benefits.
3. Complete the 300-pair pilot, three anonymized workflow records, external
   installation test, broader golden suite, and release-specific AI record, or
   explicitly reassess which are internal release gates beyond JOSS minimums.
4. Commit and push the research-software changes to `main`; obtain successful
   Python, QGIS 3.44, ZIP-install, and paper-build CI evidence.
5. Ensure an English-speaking reviewer can independently follow installation,
   the synthetic example, ontology, validation protocol, and limitations.
6. Confirm that no restricted national data, sensitive locations, or
   unapproved reference assets enter Git, the plugin ZIP, or the archive.
   `reference_data.json` and `smart_patterns.json` are currently ignored,
   untracked optional user-supplied assets. Do not restore them to a release
   unless their source and redistribution permission are documented.
7. Compile `paper/paper.md` with the Open Journals tooling and inspect the PDF,
   citations, links, author metadata, and word count.
8. Submit the short form and participate personally in the public GitHub
   review. Respond promptly; JOSS generally expects an author response within
   two weeks and requested changes within four to six weeks.
9. After successful review, create the final version tag, archive that exact
   repository state in Zenodo or a similar service, verify title and author
   metadata, report the archive DOI, and then add the JOSS preferred citation.

## Official references

- [Submission requirements and pre-review gates](https://joss.readthedocs.io/en/latest/submitting.html)
- [Paper format, metadata, required sections, and 750--1,750 word range](https://joss.readthedocs.io/en/latest/paper.html)
- [Reviewer criteria](https://joss.readthedocs.io/en/latest/review_criteria.html)
- [Official review checklist](https://joss.readthedocs.io/en/latest/review_checklist.html)
- [End-of-review archive instructions](https://joss.readthedocs.io/en/latest/sample_messages.html#message-to-authors-at-the-end-of-a-review)
- [Current JOSS submission-form source](https://github.com/openjournals/joss/blob/main/app/views/papers/_form.html.erb)
