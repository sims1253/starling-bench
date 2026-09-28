"""Generate a model-free fixture with an unmistakable synthetic identity."""

import json
import sys
import wave
from pathlib import Path

from starling_bench.artifacts import pin, seal, write_json
from starling_bench.corpus import read_corpus
from starling_bench.demo_server import TEXTS
from starling_bench.device import identify
from starling_bench.models import Acceptance, Arm, Protocol, Spec


def prepare(directory: Path, *, mode: str = "improvement", repeats: int = 4):
    directory.mkdir(parents=True, exist_ok=False)
    model = directory / "synthetic-model.txt"
    model.write_text("SYNTHETIC: no model weights, audio recognition, or hardware benchmark.\n")
    corpus = directory / "corpus.jsonl"
    rows = []
    for i, text in enumerate(TEXTS):
        audio = directory / f"{i}.wav"
        with wave.open(str(audio), "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes(i.to_bytes(2, "little", signed=True) * 1600)
        rows.append({"id": f"demo-{i}", "audio": audio.name, "reference": text, "group": f"g{i}"})
    corpus.write_text("".join(json.dumps(r) + "\n" for r in rows))
    source = Path(__file__).with_name("demo_server.py")
    arm = Arm(
        binary=pin(Path(sys.executable)),
        runtime_files=(pin(source),),
        source_revision="synthetic-protocol-fixture",
        env={"STARLING_BENCH_DEMO_DELAY_MS": "30"},
    )
    env = {"STARLING_BENCH_DEMO_DELAY_MS": "30" if mode == "unchanged" else "5"}
    if mode == "incorrect":
        env["STARLING_BENCH_DEMO_WRONG"] = "1"
    spec = Spec(
        id="synthetic-demo",
        kind="synthetic",
        model=pin(model),
        device=identify("synthetic-local", "cpu"),
        baseline=arm,
        candidate=Arm(**{**arm.model_dump(), "env": env}),
        clips=read_corpus(corpus),
        protocol=Protocol(repeats=repeats, warmup_requests=0, bootstrap_resamples=400),
        acceptance=Acceptance(min_improvement_pct=15),
    )
    sealed = seal(spec)
    write_json(directory / "spec.json", sealed, exclusive=True)
    return sealed
