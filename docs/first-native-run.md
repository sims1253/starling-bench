# Prepare the first native run

Start with an unchanged-engine control (A/A): both arms use identical binaries,
libraries, weights, and runtime settings. This checks the measurement workflow
and exposes timing noise before an optimization receives a score. A completed
control normally reports `inconclusive`, because it should establish no speedup.
Retain unexpected passes, failures, and unavailable runs when investigating them.

## Prepare a corpus with speaker identity

Use the official [LibriSpeech dataset](https://www.openslr.org/12), credited to
Vassil Panayotov, Guoguo Chen, Daniel Povey, and Sanjeev Khudanpur. It contains
read English speech under CC BY 4.0. Use `dev-clean` for this development pilot.
Reserve a separate test split for final evaluation; this command does not enforce
held-out access. Read speech alone cannot establish conversational, multilingual,
or noisy-audio performance.

Install FFmpeg on the preparation machine (`sudo apt-get install ffmpeg` on
Ubuntu). The measurement runner itself does not need it. Download and verify
the archive before extraction:

```bash
mkdir -p data/downloads
curl --fail --location --retry 2 \
  https://www.openslr.org/resources/12/dev-clean.tar.gz \
  --output data/downloads/dev-clean.tar.gz
sha256sum --check <<'CHECKSUM'
76f87d090650617fca0cac8f88b9416e0ebf80350acb97b343a85fa903728ab3  data/downloads/dev-clean.tar.gz
CHECKSUM
# Continue only if the checksum check succeeds.
tar -xzf data/downloads/dev-clean.tar.gz -C data/downloads
uv run starling-bench prepare-librispeech \
  --source data/downloads/LibriSpeech/dev-clean \
  --speakers 8 --clips-per-speaker 2 --seed 1729 \
  --out data/librispeech-dev-pilot-v1
```

The SHA256 above was computed from the archive checked against the publisher's
[MD5 list](https://www.openslr.org/resources/12/md5sum.txt), which specifies
`42e2234ba48799c1f50f24a7926300a1` for `dev-clean.tar.gz`.

The command reads official speaker/chapter IDs and transcripts. It ranks speakers
by a seeded SHA256, takes the requested number, then ranks utterances within
each selected speaker. Speakers with too few clips are ineligible. Selection
does not depend on file traversal order or Python's random implementation.
Missing audio, duplicate IDs, inconsistent IDs, insufficient eligible speakers,
decode errors, and source changes during preparation fail the command. Existing
output directories are preserved.

The output contains:

- `corpus.jsonl`: relative WAV paths, original references, and speaker groups.
- `audio/`: mono, 16 kHz PCM16 WAV files decoded with one FFmpeg thread.
- `provenance.json`: source URL, license, split, selection settings, transcript
  inventory, source/output hashes, and FFmpeg version and executable hash.

Keep that provenance with the corpus. `init` seals the WAV hashes, references,
and groups into the experiment; it does not copy this preparation sidecar into
run evidence. Decoder output may vary across FFmpeg builds. Transfer the prepared
corpus to each device to use identical WAVs, or compare every output WAV hash.

The recipe above was exercised against the real archive: **16 clips, 8 speakers,
148.73 seconds** from a pool of 2,703 clips and 40 speakers. Its `corpus.jsonl`
SHA256 is `ce5593e9d6bb0d241fd6be91db97d26afaa0ae4f7290f8a8345710f0d2646f4a`.
These are corpus checks, not model quality or latency results. Eight speakers
are a small integration pilot; increase coverage and calibrate uncertainty before
freezing a campaign. Keep one seed fixed rather than searching for easy clips.

## Seal an unchanged-engine experiment

Use an idle target host with exclusive access to the measurement device. Check
`doctor` output against the intended machine; the `--device` label is descriptive
and cannot turn a desktop measurement into a notebook measurement. On CUDA hosts,
also inspect `nvidia-smi` for existing workloads. Starling Bench's advisory lease
does not reserve the GPU against other programs.

Supply a reviewed `starling-serve` build and a compatible, fixed Parakeet GGUF.
Record the actual source commit used to build the binary. Prefer static
Starling/ggml libraries. If the build uses shared libraries, supply every required
non-system library with `--baseline-library`, preserving its loader name such as
`libggml.so.0`. System libraries and GPU drivers remain host dependencies.

```bash
uv run starling-bench doctor --device notebook --backend cpu
uv run starling-bench init \
  --id parakeet-notebook-aa-001 --device notebook --backend cpu \
  --baseline /absolute/starling/build/starling-serve --unchanged \
  --baseline-revision FULL_BUILD_COMMIT \
  --baseline-env STARLING_GGML_THREADS=4 \
  --baseline-env OMP_NUM_THREADS=4 \
  --model /absolute/models/parakeet.gguf \
  --corpus data/librispeech-dev-pilot-v1/corpus.jsonl \
  --repeats 8 --warmup-requests 1 --cooldown-seconds 2 --exact-text \
  --out runs/parakeet-notebook-aa-spec.json
uv run starling-bench run runs/parakeet-notebook-aa-spec.json \
  --out runs/parakeet-notebook-aa-001
```

`--unchanged` copies all baseline runtime settings, library pins, and source
revision into the candidate arm. It rejects candidate overrides. The four-thread
setting above is a starting configuration; freeze a suitable setting for the
target before making claims. For the RTX host, use its own label and `--backend
cuda` with a CUDA-capable binary. For notebook Vulkan, use `--backend vulkan` with
a Vulkan-capable binary. Create each spec on its target host after copying inputs.

Check startup logs, backend identity, baseline WER, exact paired transcripts,
timing uncertainty, and session telemetry. First-request and startup observations
are saved separately. If the baseline fails its quality limit, investigate the
model, build, and references before defining a new experiment. Do not loosen the
existing spec to make a completed run pass.

## Recompute and preserve results

Copy the complete run directory to another machine with Starling Bench installed,
then use `compare` and `report` there. Those commands need no model, input corpus,
native execution, or accelerator. Copy the matching corpus provenance separately.

```bash
uv run starling-bench compare /absolute/copied-run
uv run starling-bench report /absolute/copied-run --out runs/aa-report.html
```

Keep the spec, raw evidence, and all control runs. Once the control supports a
useful measurement protocol, create a new spec with an explicit `--candidate`
and the reviewed optimization. An unchanged control alone does not establish
statistical power or validate the intended optimization.
