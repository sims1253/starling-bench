# Harbor artifact pilot

The optional adapter implements Harbor's actual `BaseVerifier` interface at
commit `a38eb549b5f3c33d16ccd5c51734b0defff8399e`. Harbor runs the agent and collects
the submission. The host verifier pins the collected executable and declared
libraries, binds them to an operator-owned experiment, then starts the normal
Starling Bench CLI. Only a quality-gated `pass` earns reward 1. A measured failure
or inconclusive result earns 0; unavailable infrastructure raises a verifier
error. Candidate-authored reward files and experiment settings are ignored.

Install the separate integration environment when using Harbor:

```bash
uv sync --project integrations/harbor --locked
uv run --project integrations/harbor pytest tests/test_harbor.py
```

The root package does not install agent/cloud dependencies. The integration lock
pins the Harbor source and its dependencies independently.

Prepare a task from a local Starling clone with initialized submodules:

```bash
uv run starling-bench prepare-task \
  --source /absolute/starling --revision FULL_40_CHARACTER_COMMIT \
  --out runs/tasks/parakeet-cpu
```

The exporter includes committed files and the exact gitlink revisions, without
the repository's history, local edits, model files, or later solutions. It writes
source provenance, a CPU build environment, instructions, artifact collection
rules, and separate-verifier configuration. The generated Docker base/packages
are development defaults; pin the image digest and toolchain before a published
campaign. Build the operator's baseline with the same toolchain. The target host
must be Linux with a compatible libc and architecture.

The pilot enables public network access for agent installation and provider
calls; verification has no network. Before a scored campaign, replace public
access with a tested provider/tooling allowlist and disclose that policy. The
pilot does not claim to prevent agents from finding public solutions online.

Create a native experiment using `starling-bench init`, with the baseline binary
also supplied as the initial candidate. Its candidate file names become the
required submission names. Store the model, held-out corpus, and experiment on
the measurement host, outside the agent's task environment. Include the public
acceptance rules in `instruction.md` before freezing the task. The initial task
has no device feedback API, so this is an artifact-handoff pilot rather than a
complete iterative optimization campaign.

Use this job verifier configuration with the generated task:

```yaml
verifier:
  import_path: starling_bench.harbor:InferenceVerifier
  kwargs:
    experiment: /absolute/experiments/parakeet-cpu.json
    submission_directory: submission
    allow_supervised_execution: true
```

The corresponding CLI options can be passed to `harbor run`:

```bash
uv run --project integrations/harbor harbor run \
  -p runs/tasks/parakeet-cpu -a YOUR_AGENT -m YOUR_MODEL \
  --verifier starling_bench.harbor:InferenceVerifier \
  --verifier-kwarg experiment=/absolute/experiments/parakeet-cpu.json \
  --verifier-kwarg allow_supervised_execution=true
```

That command can call a paid provider. Setup and tests never invoke it.

The adapter intentionally requires explicit supervised-execution opt-in: it
executes collected native programs on the host under the operator's identity.
Use reviewed code and a dedicated measurement account/host. This is not a secure
public agent tournament. A production campaign needs a restricted worker,
trusted source rebuilds, an authenticated measurement broker, and budgets for
public profiling requests.

Separate verification stops the agent environment and preserves declared
artifacts before grading. Each verifier invocation makes a new output directory,
so regrading retains prior evidence. The adapter reads host-collected artifacts,
not a running agent environment. Actual Docker agent trials and Harbor's regrade
CLI still require an end-to-end hardware rehearsal before campaign use; contract
tests do not establish that deployment works.

Primary references: [custom verifiers](https://docs.harborframework.com/core-concepts/jobs/custom-verifiers),
[separate verification](https://docs.harborframework.com/core-concepts/tasks/separate-verifier),
[regrading](https://docs.harborframework.com/core-concepts/jobs/regrade).
