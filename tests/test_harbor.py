"""Contract tests against the real pinned Harbor package, without Docker or API calls."""

import asyncio
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("harbor", reason="install integrations/harbor to test the optional adapter")

from harbor.models.task.config import TaskConfig  # noqa: E402
from harbor.models.trial.config import VerifierConfig  # noqa: E402
from harbor.models.trial.paths import TrialPaths  # noqa: E402
from harbor.verifier.factory import VerifierFactory  # noqa: E402

from starling_bench.artifacts import pin, seal, write_json  # noqa: E402
from starling_bench.harbor import InferenceVerifier  # noqa: E402
from starling_bench.models import Spec  # noqa: E402


def task(mode="separate"):
    return SimpleNamespace(config=TaskConfig(verifier={"environment_mode": mode}), has_steps=False)


def kwargs(tmp_path):
    return {
        "task": task(),
        "trial_paths": TrialPaths(trial_dir=tmp_path / "trial"),
        "environment": None,
        "experiment": str(tmp_path / "experiment.json"),
    }


def test_explicit_opt_in_and_separate_verifier_required(tmp_path):
    with pytest.raises(ValueError, match="supervised"):
        InferenceVerifier(**kwargs(tmp_path))
    values = {**kwargs(tmp_path), "task": task("shared")}
    with pytest.raises(ValueError, match="separate"):
        InferenceVerifier(**values, allow_supervised_execution=True)


def test_actual_harbor_factory_loads_adapter(tmp_path):
    values = kwargs(tmp_path)
    config = VerifierConfig(
        import_path="starling_bench.harbor:InferenceVerifier",
        kwargs={
            "experiment": values.pop("experiment"),
            "allow_supervised_execution": True,
        },
    )
    verifier = VerifierFactory.create_verifier_from_config(config=config, **values)
    assert isinstance(verifier, InferenceVerifier)


def test_synthetic_runs_cannot_earn_harbor_inference_rewards(sealed, tmp_path):
    values = kwargs(tmp_path)
    write_json(Path(values["experiment"]), sealed)
    verifier = InferenceVerifier(**values, allow_supervised_execution=True)
    with pytest.raises(ValueError, match="synthetic"):
        asyncio.run(verifier.verify())


def test_missing_submission_is_zero_reward_not_candidate_reward(sealed, tmp_path):
    values = kwargs(tmp_path)
    spec = sealed.spec.model_dump()
    spec["kind"] = "native"
    spec["baseline"]["env"] = {}
    spec["candidate"]["env"] = {}
    write_json(Path(values["experiment"]), seal(Spec(**spec)))
    artifacts = values["trial_paths"].artifacts_dir
    artifacts.mkdir(parents=True)
    (artifacts / "reward.json").write_text('{"reward": 1}')
    verifier = InferenceVerifier(**values, allow_supervised_execution=True)
    result = asyncio.run(verifier.verify())
    assert result.rewards == {"reward": 0}


def test_submission_path_escape_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="inside collected"):
        InferenceVerifier(
            **kwargs(tmp_path), allow_supervised_execution=True, submission_directory="../outside"
        )


def test_collected_artifact_handoff_and_host_grading(sealed, tmp_path):
    # Native-shaped test doubles exercise the real host process path. They are
    # protocol fixtures, not inference measurements or publishable benchmark results.
    values = kwargs(tmp_path)
    root = values["trial_paths"].artifacts_dir / "submission"
    root.mkdir(parents=True)
    baseline = tmp_path / "starling-serve"
    candidate = root / "starling-serve"
    script = Path(__file__).parents[1] / "src" / "starling_bench" / "demo_server.py"
    for executable, delay in ((baseline, 30), (candidate, 5)):
        executable.write_text(
            f"#!{sys.executable}\nimport os, runpy\nfrom pathlib import Path\n"
            f"os.environ['STARLING_BENCH_DEMO_DELAY_MS'] = '{delay}'\n"
            "runpy.run_path(str(Path(__file__).with_name('demo_server.py')), run_name='__main__')\n"
        )
        executable.chmod(0o755)
    shutil.copy2(script, tmp_path / "demo_server.py")
    shutil.copy2(script, root / "demo_server.py")
    spec = sealed.spec.model_dump()
    spec["kind"] = "native"
    for name in ("baseline", "candidate"):
        spec[name] = {
            "binary": pin(baseline).model_dump(),
            "runtime_files": [pin(tmp_path / "demo_server.py").model_dump()],
            "env": {},
        }
    template = seal(Spec(**spec))
    write_json(Path(values["experiment"]), template)
    (root / "reward.json").write_text('{"reward": 0}')
    verifier = InferenceVerifier(**values, allow_supervised_execution=True)
    result = asyncio.run(verifier.verify())
    assert result.rewards == {"reward": 1}
    bound = list(values["trial_paths"].verifier_dir.glob("benchmark-*/submitted-spec.json"))
    from starling_bench.artifacts import load_spec

    assert load_spec(bound[0]).spec.candidate.binary.sha256 == pin(candidate).sha256
    assert load_spec(bound[0]).spec.baseline == template.spec.baseline
