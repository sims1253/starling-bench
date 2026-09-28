import json
from pathlib import Path

import pytest

from starling_bench.artifacts import BenchError, seal, write_json
from starling_bench.device import lease
from starling_bench.models import Spec
from starling_bench.report import render
from starling_bench.runner import load_evidence, run


def test_full_pipeline_uses_controller_clock_and_regrades_raw_data(sealed, tmp_path):
    output = tmp_path / "run"
    result = run(sealed, output, progress=lambda _: None)
    assert result.verdict == "pass"
    assert result.candidate_ms >= 4  # Demo lies about latency in its JSON response.
    write_json(output / "comparison.json", {"verdict": "forged"})
    assert load_evidence(output)[2] == result
    # Original inputs are unnecessary for offline analysis.
    Path(sealed.spec.model.path).unlink()
    render(output, tmp_path / "report.html")
    html = (tmp_path / "report.html").read_text()
    assert "SYNTHETIC DEMO" in html
    assert str(tmp_path) not in html
    assert all(c.reference not in html for c in sealed.spec.clips)
    with pytest.raises(BenchError, match="changed or missing"):
        run(sealed, output, progress=lambda _: None)


def test_quality_failure_is_saved(sealed, tmp_path):
    value = sealed.spec.model_dump()
    value["candidate"]["env"]["STARLING_BENCH_DEMO_WRONG"] = "1"
    result = run(seal(Spec(**value)), tmp_path / "wrong", progress=lambda _: None)
    assert result.verdict == "fail"


def test_timeout_retains_partial_record_and_stops_processes(sealed, tmp_path):
    value = sealed.spec.model_dump()
    value["candidate"]["env"]["STARLING_BENCH_DEMO_DELAY_MS"] = "2000"
    value["protocol"]["request_timeout_s"] = 0.1
    output = tmp_path / "timeout"
    result = run(seal(Spec(**value)), output, progress=lambda _: None)
    assert result.verdict == "unavailable"
    assert load_evidence(output)[1].status == "failed"
    with lease():  # Cleanup released the exclusive worker lease.
        pass


def test_backend_fallback_is_refused(sealed, tmp_path):
    value = sealed.spec.model_dump()
    value["candidate"]["env"]["STARLING_BENCH_DEMO_BACKEND"] = "vulkan"
    output = tmp_path / "fallback"
    result = run(seal(Spec(**value)), output, progress=lambda _: None)
    assert result.verdict == "unavailable"
    assert "backend mismatch" in " ".join(load_evidence(output)[1].failures)


def test_concurrent_measurement_refused(sealed, tmp_path):
    with lease(), pytest.raises(BenchError, match="active"):
        run(sealed, tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists()


def test_edited_raw_record_is_detected(sealed, tmp_path):
    output = tmp_path / "integrity"
    run(sealed, output, progress=lambda _: None)
    path = output / "record.json"
    value = json.loads(path.read_text())
    value["samples"][0]["text"] = "forged transcript"
    path.write_text(json.dumps(value))
    with pytest.raises(BenchError, match="evidence changed"):
        load_evidence(output)


def test_existing_output_directory_is_refused(sealed, tmp_path):
    output = tmp_path / "already-used"
    output.mkdir()
    (output / "sentinel").write_text("keep")
    with pytest.raises(FileExistsError):
        run(sealed, output)
    assert (output / "sentinel").read_text() == "keep"
