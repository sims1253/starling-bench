import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from starling_bench.artifacts import BenchError, load_spec, pin, verify_inputs, write_json
from starling_bench.models import Sample, Spec


def test_changed_rules_break_seal(sealed, tmp_path):
    path = tmp_path / "spec.json"
    value = sealed.model_dump(mode="json")
    value["spec"]["acceptance"]["min_improvement_pct"] = 0.01
    write_json(path, value)
    with pytest.raises(BenchError, match="seal"):
        load_spec(path)


def test_changed_input_is_refused(sealed):
    Path(sealed.spec.clips[0].audio.path).write_bytes(b"changed")
    with pytest.raises(BenchError, match="changed or missing"):
        verify_inputs(sealed.spec)


def test_unknown_fields_and_secret_environment_are_rejected(sealed):
    value = sealed.spec.model_dump()
    with pytest.raises(ValidationError):
        Spec(**value, mystery_flag=True)
    value["candidate"]["env"] = {"OPENAI_API_KEY": "not-a-real-key"}
    with pytest.raises(ValidationError, match="unsupported runtime"):
        Spec(**value)


@pytest.mark.parametrize("number", [float("nan"), float("inf"), -1, 0])
def test_invalid_timings_rejected(number):
    with pytest.raises(ValidationError):
        Sample(arm="candidate", repeat=0, phase="warm", clip_id="x", latency_ms=number, text="x")


def test_duplicate_corpus_ids_rejected(sealed):
    value = sealed.spec.model_dump(mode="json")
    value["clips"][1]["id"] = value["clips"][0]["id"]
    with pytest.raises(ValidationError, match="unique"):
        Spec.model_validate_json(json.dumps(value))


def test_library_pin_preserves_loader_name(tmp_path):
    library = tmp_path / "libengine.so.1.2.3"
    library.write_bytes(b"library")
    alias = tmp_path / "libengine.so.1"
    alias.symlink_to(library.name)
    artifact = pin(alias)
    assert Path(artifact.path).name == alias.name
    assert artifact.sha256 == pin(library).sha256
