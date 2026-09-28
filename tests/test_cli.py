from pathlib import Path

import pytest

from starling_bench.artifacts import load_spec
from starling_bench.cli import main


def init_arguments(sealed, output):
    return [
        "init",
        "--id",
        "unchanged-test",
        "--device",
        "test",
        "--backend",
        "cpu",
        "--baseline",
        sealed.spec.baseline.binary.path,
        "--baseline-library",
        sealed.spec.baseline.runtime_files[0].path,
        "--baseline-env",
        "OMP_NUM_THREADS=2",
        "--baseline-revision",
        "reviewed-build",
        "--model",
        sealed.spec.model.path,
        "--corpus",
        str(Path(sealed.spec.model.path).parent / "corpus.jsonl"),
        "--out",
        str(output),
    ]


def test_unchanged_control_pins_identical_artifacts_and_runtime(sealed, tmp_path):
    output = tmp_path / "control.json"
    assert main([*init_arguments(sealed, output), "--unchanged"]) == 0
    spec = load_spec(output).spec
    assert spec.baseline == spec.candidate
    assert spec.candidate.runtime_files
    assert spec.candidate.env == {"OMP_NUM_THREADS": "2"}
    assert spec.candidate.source_revision == "reviewed-build"


@pytest.mark.parametrize(
    "override",
    [
        ["--candidate-env", "OMP_NUM_THREADS=4"],
        ["--candidate-revision", "different"],
        ["--candidate-library", "/not/a/library"],
    ],
)
def test_unchanged_control_rejects_candidate_overrides(sealed, tmp_path, override):
    output = tmp_path / "invalid.json"
    assert main([*init_arguments(sealed, output), "--unchanged", *override]) == 2
    assert not output.exists()
