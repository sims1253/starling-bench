"""Export a history-free, commit-pinned CPU task for Harbor."""

import re
import subprocess
import tarfile
import tempfile
from pathlib import Path

from starling_bench.artifacts import BenchError, write_json


def snapshot(repo: Path, revision: str, destination: Path) -> dict[str, str]:
    if not re.fullmatch("[0-9a-f]{40}", revision):
        raise BenchError("task revision must be a full 40-character Git commit id")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as archive:
        subprocess.run(["git", "-C", str(repo), "archive", revision], stdout=archive, check=True)
        archive.seek(0)
        with tarfile.open(fileobj=archive) as tree:
            tree.extractall(destination, filter="data")
    modules = {}
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-rz", revision], capture_output=True, check=True
    )
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        mode, _, commit = metadata.split()
        if mode == b"160000":
            relative = name.decode()
            child_revision = commit.decode()
            modules[relative] = child_revision
            children = snapshot(repo / relative, child_revision, destination / relative)
            modules.update({f"{relative}/{key}": value for key, value in children.items()})
    return modules


def prepare_task(repo: Path, revision: str, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    environment = output / "environment"
    environment.mkdir()
    modules = snapshot(repo.resolve(), revision, environment / "starling")
    write_json(output / "source.json", {"revision": revision, "submodules": modules})
    (environment / "Dockerfile").write_text("""FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \\
    build-essential cmake ninja-build git curl ca-certificates python3 \\
    && rm -rf /var/lib/apt/lists/*
COPY starling /work/starling
WORKDIR /work/starling
RUN git init && git config user.name benchmark && git config user.email benchmark@localhost \\
    && git add . && git commit -m 'Pinned benchmark input'
RUN mkdir /submission
""")
    (output / "task.toml").write_text("""schema_version = "1.4"
artifacts = [{ source = "/submission", destination = "submission" }]

[metadata]
category = "inference-optimization"
description = "Supervised Parakeet CPU artifact pilot; target measurements occur on the host"

[agent]
timeout_sec = 3600
network_mode = "public"

[environment]
cpus = 2
memory_mb = 4096
network_mode = "public"

[verifier]
timeout_sec = 7200
environment_mode = "separate"
network_mode = "no-network"
""")
    (
        output / "instruction.md"
    ).write_text(f"""Optimize Parakeet inference in the native Starling runtime at
`/work/starling`. Source revision: `{revision}`. Model weights, transcription
semantics, and quantization must remain unchanged. Preserve general input
handling. Submit an implementation that works for unseen 16 kHz audio.

Build a Linux CPU server with:

```bash
cmake -S /work/starling -B /work/build -G Ninja \\
  -DSTARLING_SERVE=ON -DBUILD_SHARED_LIBS=OFF -DGGML_NATIVE=OFF -DGGML_LLAMAFILE=OFF
cmake --build /work/build --target starling-serve -j2
cp /work/build/starling-serve /submission/starling-serve
git -C /work/starling diff --binary HEAD > /submission/change.patch
```

Include new files in the patch with `git add -N` before the final diff.
Write `/submission/notes.md` describing your change and checks. The evaluator
compares complete transcription latency and held-out WER to a fixed baseline.
There is no target-device profiling API in this initial artifact pilot.
The operator supplies the detailed acceptance rules with the task instruction.
""")
    (output / "tests").mkdir()
    (output / "tests" / "test.sh").write_text(
        "#!/bin/sh\nset -eu\necho 'Select starling_bench.harbor:InferenceVerifier' >&2\nexit 1\n"
    )
