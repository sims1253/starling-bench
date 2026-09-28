"""Versioned contracts. Unknown fields fail rather than silently changing a run."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Name = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$")]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FilePin(Contract):
    path: str
    sha256: Digest
    size: Annotated[int, Field(ge=0, strict=True)]

    @field_validator("path")
    @classmethod
    def absolute_path(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("artifact paths must be absolute")
        return value


class Clip(Contract):
    id: Name
    audio: FilePin
    reference: str
    group: Annotated[str, Field(min_length=1)]  # Speaker/session bootstrap cluster.
    duration_s: Positive


class Arm(Contract):
    binary: FilePin
    runtime_files: tuple[FilePin, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    source_revision: str = "unrecorded"

    @model_validator(mode="after")
    def validate_runtime(self) -> Arm:
        names = [Path(p.path).name for p in (self.binary, *self.runtime_files)]
        if len(names) != len(set(names)):
            raise ValueError("binary and runtime file basenames must be unique within an arm")
        for key, value in self.env.items():
            if not re.fullmatch(
                r"(?:STARLING_[A-Z0-9_]+|GGML_[A-Z0-9_]+|OMP_NUM_THREADS|"
                r"CUDA_VISIBLE_DEVICES)",
                key,
            ):
                raise ValueError(f"unsupported runtime environment variable: {key}")
            if "\0" in value:
                raise ValueError("environment values cannot contain NUL")
        return self


class Device(Contract):
    label: Name
    backend: Literal["cpu", "cuda", "vulkan"]
    fingerprint: Digest
    observations: dict


class Protocol(Contract):
    repeats: Annotated[int, Field(ge=4, le=100, strict=True)] = 8
    warmup_requests: Annotated[int, Field(ge=0, le=100, strict=True)] = 1
    seed: Annotated[int, Field(ge=0, strict=True)] = 1729
    startup_timeout_s: Positive = 120
    request_timeout_s: Positive = 60
    cooldown_s: Annotated[float, Field(ge=0, le=3600)] = 0
    bootstrap_resamples: Annotated[int, Field(ge=200, le=100000, strict=True)] = 2000
    confidence: Annotated[float, Field(gt=0.5, lt=1)] = 0.95


class Acceptance(Contract):
    min_improvement_pct: Annotated[float, Field(gt=0, lt=100)] = 5
    max_regression_pct: Annotated[float, Field(ge=0, lt=100)] = 5
    max_wer_delta_pp: Annotated[float, Field(ge=0, le=100)] = 0.2
    max_wer_pct: Annotated[float, Field(gt=0)] = 20
    require_exact_text: bool = False


class Spec(Contract):
    schema_version: Literal[1] = 1
    id: Name
    kind: Literal["native", "synthetic"] = "native"
    trust: Literal["supervised"] = "supervised"
    metric: Literal["loopback_http_wav_to_text_ms_v1"] = "loopback_http_wav_to_text_ms_v1"
    normalizer: Literal["nfkc_casefold_punctuation_space_v1"] = "nfkc_casefold_punctuation_space_v1"
    model_slug: Name = "parakeet"
    model: FilePin
    device: Device
    baseline: Arm
    candidate: Arm
    clips: Annotated[tuple[Clip, ...], Field(min_length=2)]
    protocol: Protocol = Field(default_factory=Protocol)
    acceptance: Acceptance = Field(default_factory=Acceptance)

    @model_validator(mode="after")
    def independent_clips(self) -> Spec:
        if len({c.id for c in self.clips}) != len(self.clips):
            raise ValueError("clip ids must be unique")
        if len({c.group for c in self.clips}) < 2:
            raise ValueError("quality evaluation needs at least two speaker/session groups")
        for arm in (self.baseline, self.candidate):
            if self.kind == "native" and any(k.startswith("STARLING_BENCH_DEMO_") for k in arm.env):
                raise ValueError("demo controls require kind=synthetic")
            if self.device.backend == "cpu" and arm.env.get("STARLING_ENGINE") == "fast":
                raise ValueError("the fast engine requires Vulkan")
        return self


class SealedSpec(Contract):
    spec: Spec
    sha256: Digest


class EvidenceIndex(Contract):
    schema_version: Literal[1] = 1
    files: dict[str, Digest]

    @field_validator("files")
    @classmethod
    def relative_paths(cls, files: dict[str, str]) -> dict[str, str]:
        if not {"spec.json", "record.json"} <= files.keys():
            raise ValueError("evidence index must include spec.json and record.json")
        if any(Path(name).is_absolute() or ".." in Path(name).parts for name in files):
            raise ValueError("evidence entries must remain inside the run directory")
        return files


class Sample(Contract):
    arm: Literal["baseline", "candidate"]
    repeat: Annotated[int, Field(ge=0, strict=True)]
    phase: Literal["first", "warmup", "warm"]
    clip_id: str
    latency_ms: Positive
    text: str


class Session(Contract):
    arm: Literal["baseline", "candidate"]
    repeat: Annotated[int, Field(ge=0, strict=True)]
    startup_ms: Positive
    reported_backend: str
    telemetry_before: dict
    telemetry_after: dict


class RunRecord(Contract):
    schema_version: Literal[1] = 1
    runner_version: str
    spec_sha256: Digest
    kind: Literal["native", "synthetic"]
    device_fingerprint: Digest
    status: Literal["complete", "failed", "interrupted"]
    started_at: str
    finished_at: str
    elapsed_s: Annotated[float, Field(ge=0)]
    order: tuple[tuple[str, str], ...]
    sessions: tuple[Session, ...]
    samples: tuple[Sample, ...]
    failures: tuple[str, ...] = ()


class Interval(Contract):
    estimate: float
    low: float
    high: float


class Comparison(Contract):
    schema_version: Literal[1] = 1
    spec_sha256: Digest
    kind: Literal["native", "synthetic"]
    verdict: Literal["pass", "fail", "inconclusive", "unavailable"]
    reasons: tuple[str, ...]
    baseline_ms: float | None = None
    candidate_ms: float | None = None
    speedup: float | None = None
    improvement_pct: Interval | None = None
    baseline_wer_pct: float | None = None
    candidate_wer_pct: float | None = None
    wer_delta_pp: Interval | None = None
    paired_blocks: int = 0
    quality_groups: int = 0
