"""Pin a local JSONL corpus without downloading or redistributing audio."""

import json
import wave
from pathlib import Path

from starling_bench.artifacts import BenchError, pin
from starling_bench.models import Clip
from starling_bench.quality import words

MAX_AUDIO_BYTES = 64 * 1024 * 1024


def read_corpus(path: Path) -> tuple[Clip, ...]:
    clips = []
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if set(value) != {"id", "audio", "reference", "group"}:
            raise BenchError(f"corpus line {lineno}: expected id, audio, reference, group")
        audio = (path.parent / value["audio"]).resolve()
        if audio.stat().st_size > MAX_AUDIO_BYTES:
            raise BenchError(f"audio exceeds the 64 MiB per-clip limit: {audio}")
        with wave.open(str(audio), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (
                1,
                2,
                16000,
                "NONE",
            ):
                raise BenchError(f"expected mono 16 kHz PCM16 WAV: {audio}")
            frames = wav.getnframes()
            if len(wav.readframes(frames)) != frames * 2:
                raise BenchError(f"truncated WAV: {audio}")
        clips.append(
            Clip(
                id=value["id"],
                audio=pin(audio),
                reference=value["reference"],
                group=value["group"],
                duration_s=frames / 16000,
            )
        )
    if not any(words(c.reference) for c in clips):
        raise BenchError("the corpus needs reference words; silence may be included as extra clips")
    if sum(c.audio.size for c in clips) > 512 * 1024 * 1024:
        raise BenchError("v0.1 preloads audio; use a corpus smaller than 512 MiB")
    return tuple(clips)
