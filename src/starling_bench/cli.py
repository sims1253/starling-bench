"""Small operator CLI. Native runs execute only after an explicit run command."""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import wave
from pathlib import Path

from pydantic import ValidationError

from starling_bench.artifacts import BenchError, load_spec, pin, seal, write_json
from starling_bench.corpus import read_corpus
from starling_bench.device import identify
from starling_bench.models import Acceptance, Arm, Protocol, Spec


def environment(values: list[str]) -> dict[str, str]:
    result = {}
    for value in values:
        key, sep, content = value.partition("=")
        if not sep or key in result:
            raise BenchError("runtime options must be unique KEY=VALUE assignments")
        result[key] = content
    return result


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Quality-gated native inference experiments")
    sub = p.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="inspect the local Linux worker identity")
    doctor.add_argument("--device", default="local")
    doctor.add_argument("--backend", choices=("cpu", "cuda", "vulkan"), default="cpu")
    init = sub.add_parser(
        "init", help="pin binaries, weights, corpus, device, and acceptance rules"
    )
    init.add_argument("--id", required=True)
    init.add_argument("--baseline", type=Path, required=True)
    candidate = init.add_mutually_exclusive_group(required=True)
    candidate.add_argument("--candidate", type=Path)
    candidate.add_argument(
        "--unchanged",
        action="store_true",
        help="use the baseline and its runtime settings for both arms",
    )
    init.add_argument("--baseline-library", type=Path, action="append", default=[])
    init.add_argument("--candidate-library", type=Path, action="append", default=[])
    init.add_argument("--baseline-env", action="append", default=[])
    init.add_argument("--candidate-env", action="append", default=[])
    init.add_argument("--baseline-revision", default="unrecorded")
    init.add_argument("--candidate-revision", default="unrecorded")
    init.add_argument("--model", type=Path, required=True)
    init.add_argument("--model-slug", default="parakeet")
    init.add_argument("--corpus", type=Path, required=True)
    init.add_argument("--device", required=True)
    init.add_argument("--backend", choices=("cpu", "cuda", "vulkan"), required=True)
    init.add_argument("--repeats", type=int, default=8)
    init.add_argument("--seed", type=int, default=1729)
    init.add_argument("--warmup-requests", type=int, default=1)
    init.add_argument("--cooldown-seconds", type=float, default=0)
    init.add_argument("--request-timeout", type=float, default=60)
    init.add_argument("--startup-timeout", type=float, default=120)
    init.add_argument("--min-improvement", type=float, default=5)
    init.add_argument("--max-wer-delta", type=float, default=0.2)
    init.add_argument("--max-wer", type=float, default=20)
    init.add_argument("--exact-text", action="store_true")
    init.add_argument("--out", type=Path, required=True)
    run = sub.add_parser("run", help="execute a sealed experiment with a local host lease")
    run.add_argument("spec", type=Path)
    run.add_argument("--out", type=Path, required=True)
    for name in ("compare", "report"):
        cmd = sub.add_parser(name, help="recompute from verified saved evidence")
        cmd.add_argument("run", type=Path)
        if name == "report":
            cmd.add_argument("--out", type=Path, required=True)
    demo = sub.add_parser("demo", help="run a visibly synthetic, model-free protocol smoke test")
    demo.add_argument("--out", type=Path, required=True)
    demo.add_argument(
        "--mode", choices=("improvement", "unchanged", "incorrect"), default="improvement"
    )
    schemas = sub.add_parser("schemas", help="export the JSON contracts")
    schemas.add_argument("--out", type=Path, required=True)
    task = sub.add_parser("prepare-task", help="export a pinned Starling CPU task for Harbor")
    task.add_argument("--source", type=Path, required=True)
    task.add_argument("--revision", required=True)
    task.add_argument("--out", type=Path, required=True)
    corpus = sub.add_parser(
        "prepare-librispeech", help="convert a deterministic speaker subset from an extracted split"
    )
    corpus.add_argument("--source", type=Path, required=True)
    corpus.add_argument("--speakers", type=int, default=8)
    corpus.add_argument("--clips-per-speaker", type=int, default=2)
    corpus.add_argument("--seed", type=int, default=1729)
    corpus.add_argument("--out", type=Path, required=True)
    return p


def execute(args) -> int:
    from starling_bench.report import render
    from starling_bench.runner import load_evidence, run

    if args.command == "doctor":
        print(identify(args.device, args.backend).model_dump_json(indent=2))
    elif args.command == "init":
        if args.unchanged and (
            args.candidate_library or args.candidate_env or args.candidate_revision != "unrecorded"
        ):
            raise BenchError("--unchanged copies baseline settings; remove candidate overrides")
        arms = {}
        for name in ("baseline", "candidate"):
            if name == "candidate" and args.unchanged:
                arms[name] = arms["baseline"]
                continue
            arms[name] = Arm(
                binary=pin(getattr(args, name)),
                runtime_files=tuple(pin(p) for p in getattr(args, name + "_library")),
                env=environment(getattr(args, name + "_env")),
                source_revision=getattr(args, name + "_revision"),
            )
        value = Spec(
            id=args.id,
            model=pin(args.model),
            model_slug=args.model_slug,
            device=identify(args.device, args.backend),
            clips=read_corpus(args.corpus),
            **arms,
            protocol=Protocol(
                repeats=args.repeats,
                seed=args.seed,
                warmup_requests=args.warmup_requests,
                cooldown_s=args.cooldown_seconds,
                request_timeout_s=args.request_timeout,
                startup_timeout_s=args.startup_timeout,
            ),
            acceptance=Acceptance(
                min_improvement_pct=args.min_improvement,
                max_wer_delta_pp=args.max_wer_delta,
                max_wer_pct=args.max_wer,
                require_exact_text=args.exact_text,
            ),
        )
        write_json(args.out, seal(value), exclusive=True)
        print(f"Sealed experiment: {args.out}")
    elif args.command == "run":
        result = run(load_spec(args.spec), args.out, progress=lambda s: print(s, file=sys.stderr))
        render(args.out, args.out / "report.html")
        print(result.model_dump_json(indent=2))
        return 2 if result.verdict == "unavailable" else 0
    elif args.command == "compare":
        print(load_evidence(args.run)[2].model_dump_json(indent=2))
    elif args.command == "report":
        render(args.run, args.out)
        print(f"Report: {args.out}")
    elif args.command == "demo":
        from starling_bench.demo import prepare

        args.out.mkdir(parents=True, exist_ok=False)
        sealed = prepare(args.out / "inputs", mode=args.mode)
        result = run(sealed, args.out / "measurement", progress=lambda s: print(s, file=sys.stderr))
        render(args.out / "measurement", args.out / "report.html")
        print(f"SYNTHETIC {args.mode}: {result.verdict}; report: {args.out / 'report.html'}")
        return 2 if result.verdict == "unavailable" else 0
    elif args.command == "schemas":
        from starling_bench.models import Comparison, EvidenceIndex, RunRecord, SealedSpec

        for model in (SealedSpec, RunRecord, Comparison, EvidenceIndex):
            write_json(args.out / (model.__name__ + ".json"), model.model_json_schema())
    elif args.command == "prepare-task":
        from starling_bench.task import prepare_task

        prepare_task(args.source, args.revision, args.out)
        print(f"Pinned Harbor CPU task: {args.out}")
    elif args.command == "prepare-librispeech":
        from starling_bench.librispeech import prepare_librispeech

        manifest = prepare_librispeech(
            args.source,
            args.out,
            speakers=args.speakers,
            clips_per_speaker=args.clips_per_speaker,
            seed=args.seed,
        )
        print(f"Prepared corpus: {manifest}")
    return 0


def main(argv=None) -> int:
    def terminate(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    try:
        return execute(parser().parse_args(argv))
    except (
        BenchError,
        ValidationError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
        wave.Error,
    ) as exc:
        print(f"starling-bench: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("starling-bench: interrupted", file=sys.stderr)
        return 130
