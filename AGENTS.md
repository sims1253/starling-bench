# Working on Starling Bench

Read `docs/protocol.md` before changing measurement, quality gates, or scoring.
Read `docs/harbor.md` before changing agent artifact handoff or verification.

The core runner executes operator-reviewed native programs on Linux. Preserve
the explicit `supervised` trust label. Hashes detect changes; they do not isolate
hostile programs or prove measurements authentic.

Keep synthetic outputs visibly marked throughout records and reports. Compare
every planned pair, retain failures, and treat missing evidence as unavailable.
Baseline replacement must be an explicit new experiment. Compute official
latency in the controller; candidate-reported timing is diagnostic only.

Run `uv run pytest` and `uv run ruff check .` for code changes. Use the synthetic
demo for integration checks. Hardware runs require idle, exclusively leased
devices; run one measurement job at a time on each host. Never start paid agent
campaigns as a side effect of tests or setup.
