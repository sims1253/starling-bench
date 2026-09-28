# Measurement protocol v1

An experiment consists of a sealed JSON spec and one immutable output directory.
Changing binaries, weights, corpus text, audio, device identity, runtime settings,
or acceptance rules requires a new spec. The spec pins local file hashes; it
does not fetch moving branches or models. File paths are resolved during `init`.

The controller verifies inputs before and after the run. It stages baseline and
candidate executables and declared runtime files in separate directories and
verifies their hashes after execution. A per-user, host-wide advisory lease
rejects concurrent Starling Bench jobs regardless of their labels. Other tools
do not honor this lease; the operator must keep the target host idle.

Each repeat contains one baseline process and one candidate process. Half the
blocks start with each arm (within one block for odd repeat counts), then a
seeded shuffle orders the blocks. Both arms receive the same seeded clip order.
Each process gets one first request, the configured warmup requests, then every
corpus clip exactly once. Every arm starts with an empty private home/cache
directory. Process groups are terminated on exit, timeout, SIGINT, or SIGTERM.

The metric is `loopback_http_wav_to_text_ms_v1`. Audio reads and multipart
construction occur before timing. The controller's monotonic clock covers the
HTTP request through receipt of the response body. It includes loopback HTTP,
WAV parsing, inference, and response serialization. It excludes model startup,
controller JSON parsing, and any transfer to another machine. This is not the
proposed on-device PCM timing metric, and scores from those metrics cannot be
combined. Candidate-reported timings are ignored. Empty transcripts are valid
strings and still participate in quality evaluation.

Startup is measured separately from process launch until matching loaded model
health. First-request and warmup observations are retained but excluded from the
warm latency and WER gates. Native startup logs must identify the requested
backend, including a numbered device suffix if present. This catches ordinary
fallbacks; it is not hardware attestation against malicious native code.
The default ggml device selectors are `cpu`, `CUDA0`, and `Vulkan0`;
explicit per-arm environment settings are retained in the sealed spec. The
current fingerprint describes the host and its enumerated accelerators. Use
one target accelerator per worker; multi-GPU allocation is not implemented.

For latency, sum the warm times over the complete workload in each process.
Compute `(baseline - candidate) / baseline * 100` for each paired block. The
headline improvement is the median paired-block improvement. A seeded percentile
bootstrap resamples whole blocks. The displayed per-clip baseline/candidate
times are medians of the block means; their ratio is descriptive and can differ
from the paired effect used for acceptance. Clip medians are descriptive only.

For quality, `nfkc_casefold_punctuation_space_v1` applies Unicode NFKC, casefolds,
replaces punctuation characters with spaces, then splits on whitespace. It does
not normalize spoken numbers or implement Whisper/Open ASR Leaderboard rules.
WER is total word-level Levenshtein edits divided by total reference words.
Insertions on silent clips count. Average edits per clip across warm repeats,
then resample complete speaker/session groups for a paired WER-difference
interval. At least two groups and a corpus with reference words are required;
in practice substantially more groups are needed for useful confidence bounds.
Bootstrap draws containing no reference words are excluded.

Acceptance is fixed in advance:

- The baseline must satisfy the absolute WER limit; otherwise the comparison is
  unavailable because the reference implementation is invalid for this corpus.
- The candidate must satisfy that limit. A WER-difference interval wholly above
  the allowed margin fails; one crossing the margin is inconclusive.
- If exact text is requested, every paired warm transcript must match byte for
  byte. This compares candidate to baseline, not baseline to ground truth.
- The lower latency-improvement bound must strictly exceed the minimum gain.
  A demonstrated regression beyond the allowed margin fails. Remaining cases
  are inconclusive, including an unchanged implementation.
- Missing, duplicate, failed, or mismatched warm measurements make the run
  unavailable. Failures cannot be dropped to improve the score.

The default 5% improvement and 0.2 percentage-point WER margin are pilot settings,
not calibrated claims of statistical power. Calibrate using A/A measurements
and sufficient speakers before freezing a campaign. Do not retry a candidate
until a lucky measurement passes; freeze the final submission and grade it once
under the declared protocol. Independent reruns and their selection policy must
be reported.

This release records temperature sensors and host load where available. It does
not enforce a thermal window, measure sustained performance, estimate energy,
track peak memory, or account for agent/API cost. Those omissions remain visible
in the report. Provider failure and agent timeout accounting belong to Harbor;
the measurement runner reports its own failures as unavailable.

Candidates execute as the operator's Unix user. Environment inheritance is
restricted to declared inference settings plus a fresh home/cache, a minimal
path, locale, and staged-library path. This avoids accidentally passing provider
credentials to inference processes. It does not stop reviewed code from reading
other files available to that user. There is no public arbitrary-code endpoint.
Separate verifier containers do not make host execution adversarially safe.

`evidence.json` hashes the spec, raw records, staged programs, and process logs.
Offline comparison verifies that index and recomputes the result. The index is
not signed; someone able to replace both the records and their hashes can forge
it. Publish evidence through a versioned release or another trusted channel.
Standalone reports escape text and exclude raw transcripts, filesystem paths,
environment values, and logs. Review corpus IDs and source-revision strings
before publication. They are operator-supplied public labels.
