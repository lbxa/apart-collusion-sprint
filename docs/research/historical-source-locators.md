# Historical source locators

The harness consolidation removes obsolete executable packages while preserving
the committed historical source in Git. These locators identify the copies at
pre-migration commit `41c641bdd0f1d2fee0161e3d3e282e738d98bce9`. They do not restore
an active legacy package or change the evidence admitted in the paper brief.

## October agentic analysis

- Path: `harness-v2/src/veracity_harness/analysis.py`
- Git blob: `6f08ca351b8a39d343321c62e75adc7e03018bea`
- Content SHA256: `2f6969bfc8216d9941e77a36ef2c94ded71cd37f354febedd1a3f3048f4cce51`

From the repository root, inspect the committed source without checking it out:

```sh
git show 41c641bdd0f1d2fee0161e3d3e282e738d98bce9:harness-v2/src/veracity_harness/analysis.py
git show 41c641bdd0f1d2fee0161e3d3e282e738d98bce9:harness-v2/src/veracity_harness/analysis.py | shasum -a 256
```

## Legacy metric collector

- Path: `harness/metrics/collector.py`
- Git blob: `c5242a33971787197e70f940b3d1709e39f9a42b`
- Content SHA256: `a3ff68775f1cae57385dcdb0c62c8f4392a0a4a90de63b2bdbd6dc02dbf27084`

```sh
git show 41c641bdd0f1d2fee0161e3d3e282e738d98bce9:harness/metrics/collector.py
git show 41c641bdd0f1d2fee0161e3d3e282e738d98bce9:harness/metrics/collector.py | shasum -a 256
```

## Match the source to the actual run

A committed copy is a retrievable historical reference, not proof that its bytes
were used in every campaign assignment. The October evidence includes a recorded
revision plus per-run hashes from dirty working trees. Compare the relevant
content hashes with the original run manifest, retained source packet, and pinned
review provenance before reproducing an analysis or attributing behavior to a
revision. A dirty variant whose bytes were not retained cannot be reconstructed
from a clean commit alone. Keep that limitation visible rather than substituting
the current implementation or silently changing an original record.

The [migration source manifest](../../harness/migration-source.json) separately
records the imported successor runtime before Collusion adaptations. It is not
the source register for the October experiments.
