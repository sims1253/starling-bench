"""Optional Harbor verifier for explicitly supervised Linux artifact evaluation."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import uuid
from pathlib import Path

from harbor.models.verifier.result import VerifierResult
from harbor.verifier.base import BaseVerifier

from starling_bench.artifacts import BenchError, load_spec, pin, seal, write_json
from starling_bench.models import Arm, Spec
from starling_bench.runner import load_evidence


class InferenceVerifier(BaseVerifier):
    """Grade collected artifacts; never accept a candidate-supplied reward or spec."""

    def __init__(
        self,
        *,
        experiment: str,
        allow_supervised_execution: bool = False,
        submission_directory: str = "submission",
        **kwargs,
    ):
        super().__init__(**kwargs)
        if allow_supervised_execution is not True:
            raise ValueError("set allow_supervised_execution=true only for reviewed native code")
        verifier = self.task.config.verifier
        if verifier.environment_mode != "separate" and not (
            verifier.environment_mode is None and verifier.environment is not None
        ):
            raise ValueError("the task must use a separate verifier environment")
        if self.task.has_steps:
            raise ValueError("v0.1 supports single-step Harbor tasks only")
        path = Path(submission_directory)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("submission_directory must remain inside collected artifacts")
        self.experiment = Path(experiment)
        self.submission_directory = path

    async def verify(self) -> VerifierResult:
        template = load_spec(self.experiment)
        if template.spec.kind != "native":
            raise ValueError(
                "Harbor inference rewards require kind=native; synthetic runs are demos"
            )
        root = self.trial_paths.artifacts_dir.resolve()
        submission = root / self.submission_directory
        output = self.trial_paths.verifier_dir / ("benchmark-" + uuid.uuid4().hex[:12])
        output.mkdir(parents=True, exist_ok=False)

        # This directory is populated by Harbor artifact collection before a separate verifier.
        # Read only the fixed executable/library names declared by the operator's template.
        def collect(original):
            candidate = submission / Path(original.path).name
            if candidate.is_symlink() or not candidate.resolve().is_relative_to(root):
                raise BenchError("candidate artifact escapes the collected submission")
            return pin(candidate)

        try:
            prior = template.spec.candidate
            arm = Arm(
                binary=collect(prior.binary),
                runtime_files=tuple(collect(p) for p in prior.runtime_files),
                env=prior.env,
                source_revision="Harbor collected artifact; see trial trace",
            )
        except (BenchError, OSError) as exc:
            write_json(output / "rejection.json", {"reason": str(exc)})
            return VerifierResult(rewards={"reward": 0})
        # Keep budgets, baseline, corpus, model and scoring rules from the host template.
        bound = seal(Spec(**{**template.spec.model_dump(), "candidate": arm.model_dump()}))
        write_json(output / "submitted-spec.json", bound)
        write_json(
            output / "submission.json",
            {
                "template_sha256": template.sha256,
                "bound_spec_sha256": bound.sha256,
                "candidate_sha256": arm.binary.sha256,
                "trust": "supervised",
            },
        )
        with (output / "controller.log").open("wb") as log:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "starling_bench",
                "run",
                str(output / "submitted-spec.json"),
                "--out",
                str(output / "run"),
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            try:
                returncode = await process.wait()
            except BaseException:
                if process.returncode is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        await asyncio.wait_for(process.wait(), timeout=10)
                    except TimeoutError:
                        os.killpg(process.pid, signal.SIGKILL)
                        await process.wait()
                raise
        if returncode:
            raise RuntimeError(f"measurement unavailable; inspect {output / 'controller.log'}")
        result = load_evidence(output / "run")[2]
        if result.verdict == "unavailable":
            raise RuntimeError("measurement unavailable; inspect the benchmark evidence")
        return VerifierResult(rewards={"reward": int(result.verdict == "pass")})
