# Validation rule snapshots

Copy the exact, released JSON rule set used by each validation run into this
directory without editing it. File names should include the rule-set version,
for example `matching-rules-1.0.0.json`, and the run record must include its
SHA-256.

The runtime's canonical rule library may live elsewhere in the plugin. These
files are immutable validation snapshots, not an alternative configuration
source. A threshold change requires a new version and a new locked evaluation.

No research-release rule snapshot has been approved yet (**pending**).
