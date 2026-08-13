# Validation templates

These blank forms define evidence fields; they are not completed validation.

- `pilot-candidate-template.csv` is the blinded reviewer view. It deliberately
  contains no recommendation, score, rule, candidate flag, or automatic-merge
  flag. Prefer generating it with
  `research_validation.export_blinded_labeling_csv()`.
- `pilot-private-prediction-template.csv` remains private while labels are
  assigned. After labeling, `merge_blinded_labels()` joins the two by
  `pair_id`; `calculate_pilot_metrics()` requires `is_candidate`,
  `automatic_merge`, and `blind_label`.
- `real-workflow-template.csv` contains anonymized case-level observations.
- The Markdown forms record independent ZIP installation and manual QGIS 3.28
  checks.

Raw pilot rows, names, addresses, and real coordinates must remain outside the
public repository. Only disclosure-reviewed aggregates belong in `results/`.
