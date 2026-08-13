# Expected results

Expected results must be derived independently from the implementation under
test and reviewed against `docs/research/ontology-and-decision-rules.md`.

Each case should state:

- fixture and rule-set identifiers;
- expected `INVESTIGATION_KEY`, `SITE_ENTITY_KEY`, `GEOMETRY_GROUP_KEY`,
  `NUMBER_KEY`, and `RELATION_TYPE` relationships;
- expected run status and excluded-input reasons;
- geometry/count expectations and deterministic content digest;
- numerical tolerances: extent dimensions 0.01 m, buffer distance 0.1 m, and
  cross-CRS buffer-area difference 0.5%;
- reviewer and review date.

Synthetic cases permit zero false merges and zero source-record deletion.
`policy_cases.json` fixes the current 13-case policy contract and zero-tolerance
requirements. Broader geometry, encoding, metric, cancellation, and
deterministic-output golden files remain **pending**.
