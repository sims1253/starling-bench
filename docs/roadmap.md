# From the first runner to a device benchmark

The first implementation owns pinned inputs, supervised Linux server execution,
paired warm measurements, quality gates, evidence verification, reports, and an
optional Harbor artifact adapter. It includes a synthetic end-to-end demo and
controls for unchanged, incorrect, missing, and incompatible results.

The [native rehearsal guide](first-native-run.md) now includes a deterministic
LibriSpeech preparation command, source provenance, and an explicit unchanged
control. The 16-clip preparation recipe has been exercised on real source audio.
Native model measurements and their interpretation remain outstanding.

The next milestones have concrete acceptance criteria:

1. **Real notebook rehearsal.** Run the unchanged native engine and a known
   optimization over a representative Parakeet corpus. Record baseline quality,
   noise, backend selection, build/runtime dependencies, and adequate sample
   counts. Recompute the report on another machine using only saved evidence.
2. **RTX rehearsal.** Run the same protocol locally on the RTX host. Pin the
   selected CUDA device and toolkit. Compare against a credible current baseline.
3. **Android worker.** Deploy independently hashed binaries, maintain one device
   lease, handle disconnects and process cleanup, and enforce display/thermal
   rules. Implement trusted on-device timing with its own metric identity.
   Keep ADB transport overhead out of that metric. Validate an execution identity
   that separates candidate code from reference data and measurement authority.
4. **Device broker and trusted builds.** Accept only declared source patches and
   workload IDs. Rebuild candidates in a restricted environment. Authenticate
   worker requests, limit profiling calls/device time, and keep the agent away
   from SSH/ADB credentials. Demonstrate attempted reward and baseline tampering
   fail under the actual worker boundary.
5. **Agent campaign.** Give two agent configurations equivalent budgets and public
   measurement feedback. Freeze their final submissions, independently grade all
   attempts, and publish cost/time/usage together with quality and speed. Include
   outages, retries, regressions, and uncertainty. One model on three devices is
   a case study, not a broad agent ranking.
6. **Sustained performance and publication.** Add thermal-window validation,
   longer workloads, memory tracking, and device-specific energy methods.
   Generate a versioned multi-run result index and release reviewed artifacts.
   Keep development and held-out corpus versions separate.

MOSS is the second model. Quantization, throughput, streaming, portability of
patches across devices, and NPU integration should be separate task tracks.
