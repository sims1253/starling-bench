"""Run complete paired blocks and retain evidence on every exit path."""

from __future__ import annotations

import random
import time
from datetime import UTC, datetime
from pathlib import Path

from starling_bench import __version__
from starling_bench.artifacts import (
    BenchError,
    digest,
    load_spec,
    sha256,
    verify_inputs,
    write_json,
)
from starling_bench.device import inventory, lease, telemetry
from starling_bench.models import EvidenceIndex, RunRecord, Sample, SealedSpec, Session
from starling_bench.scoring import compare
from starling_bench.worker import Server, stage


def now() -> str:
    return datetime.now(UTC).isoformat()


def balanced_order(repeats: int, seed: int) -> list[tuple[str, str]]:
    order = [
        ("baseline", "candidate") if r % 2 == 0 else ("candidate", "baseline")
        for r in range(repeats)
    ]
    random.Random(seed).shuffle(order)
    return order


def record_hashes(directory: Path) -> None:
    paths = [directory / "spec.json", directory / "record.json", *directory.glob("logs/*.log")]
    paths += [p for p in (directory / "artifacts").glob("*/*") if p.is_file()]
    write_json(
        directory / "evidence.json",
        {
            "schema_version": 1,
            "files": {str(p.relative_to(directory)): sha256(p) for p in sorted(paths)},
        },
    )


def load_evidence(directory: Path):
    index = EvidenceIndex.model_validate_json((directory / "evidence.json").read_text())
    files = index.files
    for name, expected in files.items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise BenchError("evidence path escapes the run directory")
        if not path.is_file() or sha256(path) != expected:
            raise BenchError(f"evidence changed or missing: {name}")
    sealed = load_spec(directory / "spec.json")
    record = RunRecord.model_validate_json((directory / "record.json").read_text())
    return sealed, record, compare(sealed, record)


def run(sealed: SealedSpec, directory: Path, progress=print):
    spec = sealed.spec
    if sealed.sha256 != digest(spec):
        raise BenchError("spec seal is invalid")
    directory = directory.resolve()
    with lease():
        if digest(inventory(spec.device.backend)) != spec.device.fingerprint:
            raise BenchError("worker hardware/driver identity differs from the sealed spec")
        verify_inputs(spec)
        directory.mkdir(parents=True, exist_ok=False)
        write_json(directory / "spec.json", sealed)
        (directory / "logs").mkdir()
        started, t0 = now(), time.monotonic()
        order = balanced_order(spec.protocol.repeats, spec.protocol.seed)
        samples, sessions, failures = [], [], []
        status = "interrupted"

        def snapshot():
            record = RunRecord(
                runner_version=__version__,
                spec_sha256=sealed.sha256,
                kind=spec.kind,
                device_fingerprint=spec.device.fingerprint,
                status=status,
                started_at=started,
                finished_at=now(),
                elapsed_s=time.monotonic() - t0,
                order=tuple(order),
                sessions=tuple(sessions),
                samples=tuple(samples),
                failures=tuple(failures),
            )
            write_json(directory / "record.json", record)
            return record

        try:
            for name in ("baseline", "candidate"):
                stage(getattr(spec, name), directory / "artifacts" / name)
            # Audio and multipart construction are outside the declared request clock.
            audio = {c.id: Path(c.audio.path).read_bytes() for c in spec.clips}
            for repeat, arms in enumerate(order):
                clips = list(spec.clips)
                random.Random(spec.protocol.seed + repeat + 1).shuffle(clips)
                for name in arms:
                    progress(f"block {repeat + 1}/{spec.protocol.repeats}: {name}")
                    arm = getattr(spec, name)
                    before = telemetry()
                    with Server(
                        spec,
                        arm,
                        directory / "artifacts" / name,
                        directory / "logs" / f"{repeat:03d}-{name}.log",
                    ) as server:
                        schedule = [("first", clips[0])]
                        schedule += [
                            ("warmup", clips[i % len(clips)])
                            for i in range(spec.protocol.warmup_requests)
                        ]
                        schedule += [("warm", clip) for clip in clips]
                        for request_index, (phase, clip) in enumerate(schedule, 1):
                            ms, text = server.transcribe(audio[clip.id])
                            samples.append(
                                Sample(
                                    arm=name,
                                    repeat=repeat,
                                    phase=phase,
                                    clip_id=clip.id,
                                    latency_ms=ms,
                                    text=text,
                                )
                            )
                            progress(
                                f"  {request_index}/{len(schedule)} {phase} {clip.id}: "
                                f"{ms / 1000:.3f} s"
                            )
                        sessions.append(
                            Session(
                                arm=name,
                                repeat=repeat,
                                startup_ms=server.startup_ms,
                                reported_backend=server.backend,
                                telemetry_before=before,
                                telemetry_after=telemetry(),
                            )
                        )
                    snapshot()
                    if spec.protocol.cooldown_s:
                        time.sleep(spec.protocol.cooldown_s)
            verify_inputs(spec)
            # Detect modified staged binaries as well as modified original inputs.
            for name in ("baseline", "candidate"):
                arm = getattr(spec, name)
                for artifact in (arm.binary, *arm.runtime_files):
                    target = directory / "artifacts" / name / Path(artifact.path).name
                    if sha256(target) != artifact.sha256:
                        raise BenchError(f"staged {name} artifact changed: {target.name}")
            status = "complete"
        except KeyboardInterrupt:
            failures.append("operator interrupted the run")
        except Exception as exc:
            status = "failed"
            failures.append(f"{type(exc).__name__}: {exc}")
        finally:
            record = snapshot()
            result = compare(sealed, record)
            write_json(directory / "comparison.json", result)
            record_hashes(directory)
        return result
