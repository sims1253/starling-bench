import pytest

from starling_bench.demo import prepare
from starling_bench.models import RunRecord, Sample, Session
from starling_bench.runner import balanced_order


@pytest.fixture
def sealed(tmp_path):
    return prepare(tmp_path / "inputs")


def make_record(sealed, *, candidate_ms=50, candidate_text=None):
    samples, sessions = [], []
    spec = sealed.spec
    for r, pair in enumerate(balanced_order(spec.protocol.repeats, spec.protocol.seed)):
        for arm in pair:
            ms = 100 if arm == "baseline" else candidate_ms
            sessions.append(
                Session(
                    arm=arm,
                    repeat=r,
                    startup_ms=1,
                    reported_backend="cpu",
                    telemetry_before={},
                    telemetry_after={},
                )
            )
            for phase, clip in [("first", spec.clips[0]), *[("warm", c) for c in spec.clips]]:
                text = (
                    clip.reference
                    if arm == "baseline" or candidate_text is None
                    else candidate_text
                )
                samples.append(
                    Sample(
                        arm=arm, repeat=r, phase=phase, clip_id=clip.id, latency_ms=ms, text=text
                    )
                )
    return RunRecord(
        runner_version="test",
        spec_sha256=sealed.sha256,
        kind=spec.kind,
        device_fingerprint=spec.device.fingerprint,
        status="complete",
        started_at="test",
        finished_at="test",
        elapsed_s=1,
        order=tuple(balanced_order(spec.protocol.repeats, spec.protocol.seed)),
        sessions=tuple(sessions),
        samples=tuple(samples),
    )
