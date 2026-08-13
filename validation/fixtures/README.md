# Synthetic fixtures

Only wholly synthetic data may be committed in this directory. Every fixture
must document:

1. the archaeological relationship it models;
2. generation code and random seed, if any;
3. CRS, geometry family, units, encoding, and expected input count;
4. licence (`CC0-1.0` unless explicitly stated otherwise);
5. the expected-file identifier in `../expected/`.

The committed `policy_cases.json` fixture contains 13 synthetic
entity/investigation/number, source-role matching, non-polygon safety, and
cartographic-fragment cases. Run it with:

```bash
python validation/run_synthetic_policy.py
```

The broader planned suite still includes metric equivalence across
EPSG:4326/5179/5186 and a foot-based CRS; invalid and mixed geometry;
UTF-8/CP949; duplicate bundles; cancellation and partial failure; deterministic
reruns; and expanded end-to-end cases. The 100,000-feature spatial-index
benchmark is generated separately by `validation/benchmark_spatial_index.py`.

Only the committed 13-case policy fixture currently has a golden expectation.
The broader golden dataset remains **pending**. Do not replace synthetic cases
with real heritage data.
