# Baseline Kernel namespace ownership evidence

This counterexample was executed at `44e6fa9f73ed4f1f7d6cc4c97314ebda964f03c5` before the #871 wire migration. Production and independent admission both accept an otherwise empty LDB package called `kernel`, and another candidate exporting `kernel.Boolean` at internal package version `1.0.0`. The Kernel fixed nominal contracts simultaneously name `kernel.Boolean`, `kernel.Unit` and `kernel.EventReference` at reference version `2.0.0`.

[Captured results](baseline-results.json) and the [exact probe](baseline_probe.py.txt) support only that baseline observation. The probe does not show that namespace exclusion or the migrated public path is implemented. Removing reference versions requires a permanent empty reserved-owner refusal and positive distinct-owner cases in the current conformance suite.

To reproduce, use a checkout of the recorded baseline and run the probe from its `libs/gda-balancing` directory with that checkout's frozen environment. Pass the path of this retained probe:

```sh
PYTHONPATH=tests uv run --frozen python /absolute/path/to/baseline_probe.py.txt
```

The probe prints JSON and does not modify repository files. It intentionally uses the baseline input shape and baseline test support. It is historical evidence, not a compatibility utility or a current-schema validator.

SHA-256 of the captured files:

- `baseline_probe.py.txt`: `91967bf7a94f02e1230e745f782314e1a343d01e03e8679d66dee876ef6a36db`
- `baseline-results.json`: `cd8156d54f4288fc2d83fd52e72229d13d1d4a9e59b3cead06181bd9c73ac7cd`
