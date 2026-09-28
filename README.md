# Starling Bench

Measure whether an optimization makes native speech inference faster while
preserving transcription quality. Every experiment pins its inputs, runs paired
baseline/candidate measurements, and produces a report from saved evidence.

This first release is a **supervised Linux experiment runner**. It works with
`starling-serve` on CPU, Vulkan, or CUDA. The notebook and RTX host run the same
CLI locally. Android workers and the device broker are the next milestones.

## Try the complete workflow

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
uv sync --locked
uv run starling-bench demo --out runs/demo
uv run starling-bench compare runs/demo/measurement
uv run starling-bench report runs/demo/measurement --out runs/demo-report.html
```

Open `runs/demo/report.html`. The demo is explicitly synthetic: generated WAV
markers select fixed text, and sleeps simulate latency. It runs no model and
provides no inference performance evidence. `--mode incorrect` demonstrates a
quality failure; `--mode unchanged` exercises an A/A control.

## Measure a real candidate

Build baseline and candidate `starling-serve` executables in separate Starling
checkouts. Supply the same GGUF weights and a JSONL corpus of mono, 16 kHz PCM16
WAV files. Paths in the corpus are relative to its JSONL file:

```json
{"id":"clip-001","audio":"audio/001.wav","reference":"the first transcript","group":"speaker-01"}
{"id":"clip-002","audio":"audio/002.wav","reference":"the second transcript","group":"speaker-02"}
```

Use a representative corpus for real claims; two clips only demonstrate the
format. Keep development and final evaluation corpora separate.

For a reproducible starting point, follow [the first native run guide](docs/first-native-run.md).
`prepare-librispeech` converts an extracted official split into a seeded,
speaker-grouped corpus and saves its provenance. `init --unchanged` creates an
A/A control using the baseline's binary, libraries, and runtime settings in both
arms. The guide includes archive checksums and the exercised 16-clip pilot recipe.

```bash
uv run starling-bench doctor --device notebook --backend vulkan
uv run starling-bench init \
  --id parakeet-notebook-001 --device notebook --backend vulkan \
  --baseline /absolute/baseline/build/starling-serve \
  --candidate /absolute/candidate/build/starling-serve \
  --baseline-revision BASE_COMMIT --candidate-revision CANDIDATE_COMMIT \
  --model /absolute/models/parakeet.gguf --corpus /absolute/corpus.jsonl \
  --repeats 8 --min-improvement 5 --max-wer-delta 0.2 \
  --out runs/parakeet-spec.json
uv run starling-bench run runs/parakeet-spec.json --out runs/parakeet-001
```

For a shared-library build, add each required library using
`--baseline-library PATH` / `--candidate-library PATH`; the runner stages these
beside the respective executable. OS and GPU driver libraries remain system
dependencies. Prefer static Starling/ggml libraries for a simpler artifact.
Runtime options use `--baseline-env KEY=VALUE` and `--candidate-env KEY=VALUE`.
Both arms default to `STARLING_ENGINE=ggml`; explicitly set both to `fast` for
a fast-engine comparison. Native startup logs must confirm the requested backend.

On the RTX machine, use `--backend cuda`. CUDA identity discovery requires
`nvidia-smi`; Vulkan requires `vulkaninfo`. Create and run the spec on the target
host. Paths and hardware identity are local, and changed files or drivers are
refused. A baseline is never refreshed from the candidate.

## Read the result

- `pass`: latency improvement clears the registered threshold and quality passes.
- `fail`: a quality requirement or statistically established latency regression fails.
- `inconclusive`: uncertainty does not establish an accepted improvement.
- `unavailable`: incomplete, failed, or incompatible measurements.

`run` exits 0 for a completed evaluation, including `fail` and `inconclusive`;
it exits 2 for unavailable evidence or invalid input. Consume the JSON verdict
when deciding whether to promote a patch. Existing run directories are refused.

Each run saves the sealed spec, staged programs, process logs, first/warmup/warm
observations, transcripts, host telemetry, evidence hashes, comparison, and HTML.
`compare` and `report` verify the evidence hashes and recompute the decision;
they do not trust the saved comparison. They work without the original model or
corpus files. The standalone HTML omits transcripts, host paths, and raw logs.

The clock measures **loopback HTTP WAV-to-text latency**, including HTTP and WAV
parsing. Model startup and first inference are separate. Energy, peak memory,
sustained thermal behavior, and agent cost are not measured in this release.
Read [the protocol](docs/protocol.md) before interpreting results.

The runner controls the clock and WER calculation, but reviewed candidate
programs run as the operator's Unix user. Hashes are integrity checks, not a
sandbox or signatures. Use this release for supervised experiments. The
[Harbor adapter](docs/harbor.md) requires explicit supervised-execution opt-in.

## Develop

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run starling-bench schemas --out schemas
```

CI runs the contract/integration tests and builds the wheel without models,
GPUs, Docker, or paid API calls. See [the roadmap](docs/roadmap.md) for the path
from this runner to the three-device agent benchmark and
[the original investigation](docs/research.md) for source-backed design context.

Apache-2.0. Model weights and datasets retain their respective licenses.
