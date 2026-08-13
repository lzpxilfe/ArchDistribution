# JOSS submission dossier / JOSS 투고 자료

This dossier collects the information needed to submit ArchDistribution 1.0.5
to the *Journal of Open Source Software* (JOSS). It separates the claims made
in the paper from later empirical studies that could evaluate classification
accuracy or time savings.

## Submission position / 투고 판단

The English manuscript is written as a submission paper rather than an
internal readiness memo. It contains the sections and metadata required by
JOSS, stays within the 750--1,750 word range, documents one developer-led
research use, and limits its claims to the available evidence. The repository
has more than six months of public history, an OSI-approved licence, tests,
CI, a changelog, contribution guidance, and public issue and pull-request
pathways.

The 300-pair single-reviewer pilot, two additional anonymized workflows, and a
multi-institution study remain useful future validation. JOSS does not impose
those numerical requirements, and the paper does not claim the archaeological
accuracy, quantified labor savings, or institutional generalizability that
such studies would be needed to support. A colleague installation test is
recommended by JOSS for new software and would strengthen the submission; it
must not be described as complete until it has actually occurred.

## Author and disclosure information / 저자·공개 정보

| Field | Submission value |
| --- | --- |
| Published name | Jinseo Hwang |
| Corresponding author | Yes |
| GitHub account | `lzpxilfe` |
| Affiliation | Nuri Institute for Archaeology, Republic of Korea |
| Role | Archaeological researcher |
| ORCID | Not provided; optional |
| Email | `lzpxilfe@gmail.com` (already published in `metadata.txt`; confirm in the JOSS account) |
| Other authors | None reported |
| External funding | None |
| Dedicated institutional support | None |
| Competing interests | None declared |

Confirmed manuscript wording:

> This work received no external funding or dedicated institutional support.
> The author declares no competing interests.

## Research use supporting the impact statement / 연구 활용

ArchDistribution was used on 11 August 2026 while the developer prepared a
surrounding-site map for an excavation-report workflow at Nuri Institute for
Archaeology. The project concerned a housing-development site at 227-2,
Ungjin-dong, Gongju. The Korean Heritage Service permit register independently
documents permit 2024-0745, a 2,252 m² rescue excavation completed on 12 August
2024. The public register establishes the project context but does not record
software use; the latter is a developer-reported workflow fact.

The paper states exactly that distinction. It does not estimate time saved
because no contemporaneous manual baseline was recorded. Private source data,
exact archaeological coordinates, and an unpublished report are not included
in the repository. Editors may be given a disclosure-reviewed statement or
private supporting material if they request evidence during pre-review.

## Technical evidence / 기술 증거

| Evidence | Current repository record |
| --- | --- |
| Policy cases | 13 committed synthetic cases |
| QGIS integration | 84 tests on Windows/QGIS 3.40.5 and Linux/QGIS 3.44.13 |
| Scale check | Indexed candidate generation for 100,000 synthetic features |
| Local benchmark | 398,104 candidates; 27.28 s; 164.19 MiB peak memory |
| CI benchmark | 398,104 candidates; 3.24 s; 250.70 MiB peak memory |
| Reproducibility | Versioned rules, manifests, input and output hashes, synthetic fixtures |
| Packaging | QGIS plugin ZIP at version 1.0.5 |
| Paper | JOSS Markdown, BibTeX, and an English workflow figure in `paper/` |

The benchmark measures candidate generation. It is not evidence of
end-to-end nationwide processing speed or archaeological classification
accuracy.

`reference_data.json` and `smart_patterns.json` are excluded from the current
repository snapshot and plugin package because their redistribution basis has
not been documented. Optional user-supplied loading remains available. Neither
asset may return to a release without source and licence evidence.

## AI usage / 생성형 AI

The manuscript and [`ai-usage.md`](ai-usage.md) disclose OpenAI Codex use in
code suggestions, refactoring, tests, documentation, repository maintenance,
and language editing. The recoverable model identifier for the August 2026
revision is `gpt-5.6-sol`. Historical identifiers that were not retained are
not guessed. Jinseo Hwang made the archaeological and architectural decisions,
reviewed and modified assisted output, and remains responsible for all
submitted material.

During JOSS review, generative AI must not write substantive exchanges with
editors or reviewers. Translation assistance is permitted, but the author
must make and communicate the evaluative judgement.

## Online submission form / 온라인 양식

- **Content type:** Software paper
- **Title:** `ArchDistribution: A QGIS plugin for reconciling and mapping archaeological spatial records`
- **Repository:** `https://github.com/lzpxilfe/ArchDistribution`
- **Branch containing paper:** `main`
- **Software version:** `1.0.5`
- **Submission type:** New submission
- **Main subject:** Choose the closest live option to Archaeology, Digital
  Humanities, or Geographic Information Systems.
- **Corresponding author:** Jinseo Hwang

### Message to editors

```text
ArchDistribution is a QGIS plugin for reconciling heterogeneous archaeological
spatial records when preparing numbered distribution maps for research and
excavation reports. It distinguishes archaeological sites, investigation
events, legal boundaries, geometry groups, and displayed map numbers while
preserving source data and a review trail.

This is a new submission. The public repository has been available since
28 January 2026 and records iterative development, tests, continuous
integration, documentation, a changelog, and contribution pathways. The
developer used the software on 11 August 2026 to prepare a surrounding-site map
for an excavation-report workflow concerning Korean Heritage Service permit
2024-0745. The manuscript distinguishes this developer-reported use from the
public permit data that independently establish the project context.

Neither this software paper nor its code or documentation has been published
or submitted elsewhere. No separate archaeological-methods paper is currently
identified. Any future methods paper would report distinct empirical methods
and results rather than duplicate this software paper.

Generative AI use is disclosed in the manuscript and repository. OpenAI Codex
assisted with code proposals, test scaffolding, documentation, and language
editing. Jinseo Hwang framed the problem, made the domain and architectural
decisions, reviewed and modified assisted output, and verified the software
through static checks, synthetic policy cases, and QGIS execution.

This work received no external funding or dedicated institutional support. No
sponsor influenced the design, validation, writing, or submission. The author
declares no competing interests.
```

## Final author actions / 최종 제출 동작

1. Confirm `lzpxilfe@gmail.com` in the JOSS account; add an ORCID only if the
   author has one and wishes to publish it.
2. Confirm that the public `main` commit passes Python, QGIS, package-install,
   and paper-build workflows.
3. Download and inspect the CI-built PDF, especially the workflow figure,
   references, author name, and affiliation.
4. If a colleague completes an independent installation test before
   submission, record the environment and outcome without inventing or
   backdating evidence.
5. Submit through the JOSS form and answer editors and reviewers personally.
6. After successful review, tag the accepted version, archive that exact state
   in Zenodo or a comparable service, report the DOI in the review issue, and
   add the final JOSS preferred citation.

## Official references

- [Submission requirements and pre-review gates](https://joss.readthedocs.io/en/latest/submitting.html)
- [Paper format and 750--1,750 word range](https://joss.readthedocs.io/en/latest/paper.html)
- [Reviewer criteria](https://joss.readthedocs.io/en/latest/review_criteria.html)
- [Review checklist](https://joss.readthedocs.io/en/latest/review_checklist.html)
- [End-of-review archive instructions](https://joss.readthedocs.io/en/latest/sample_messages.html#message-to-authors-at-the-end-of-a-review)
- [Current submission form source](https://github.com/openjournals/joss/blob/main/app/views/papers/_form.html.erb)
