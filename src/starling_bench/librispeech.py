"""Prepare a deterministic, speaker-grouped subset of an extracted LibriSpeech split."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from starling_bench.artifacts import BenchError, digest, sha256, write_json
from starling_bench.corpus import read_corpus

SPLITS = ("dev-clean", "dev-other", "test-clean", "test-other")
SELECTION = "sha256_speaker_then_utterance_v1"


@dataclass(frozen=True)
class Utterance:
    id: str
    speaker: str
    audio: Path
    reference: str
    transcript: Path


def discover(source: Path) -> tuple[list[Utterance], list[dict]]:
    utterances, transcripts, seen = [], [], set()
    for path in sorted(source.glob("*/*/*.trans.txt")):
        relative = path.relative_to(source)
        speaker, chapter = relative.parts[:2]
        if path.name != f"{speaker}-{chapter}.trans.txt":
            raise BenchError(f"unexpected LibriSpeech transcript path: {relative}")
        content = path.read_bytes()
        transcripts.append({"path": str(relative), "sha256": hashlib.sha256(content).hexdigest()})
        for line in content.decode("utf-8").splitlines():
            if not line.strip():
                continue
            fields = line.split(maxsplit=1)
            if len(fields) != 2 or not re.fullmatch(r"\d+-\d+-\d+", fields[0]):
                raise BenchError(f"invalid LibriSpeech transcript entry: {relative}")
            clip_id, reference = fields
            if clip_id.split("-")[:2] != [speaker, chapter]:
                raise BenchError(f"speaker/chapter mismatch: {clip_id}")
            if clip_id in seen:
                raise BenchError(f"duplicate LibriSpeech utterance: {clip_id}")
            seen.add(clip_id)
            audio = path.parent / f"{clip_id}.flac"
            if not audio.is_file():
                raise BenchError(f"missing LibriSpeech audio: {clip_id}")
            utterances.append(Utterance(clip_id, speaker, audio, reference, path))
    if not utterances:
        raise BenchError("no LibriSpeech speaker/chapter/*.trans.txt entries found")
    return utterances, transcripts


def select(
    utterances: list[Utterance], speakers: int, clips_per_speaker: int, seed: int
) -> list[Utterance]:
    groups: dict[str, list[Utterance]] = {}
    for utterance in utterances:
        groups.setdefault(utterance.speaker, []).append(utterance)

    def rank(kind: str, value: str):
        return hashlib.sha256(f"{SELECTION}:{seed}:{kind}:{value}".encode()).hexdigest(), value

    # Fail on insufficient speakers; never silently alter the requested sample size.
    eligible = [s for s, clips in groups.items() if len(clips) >= clips_per_speaker]
    if len(eligible) < speakers:
        raise BenchError(
            f"requested {speakers} speakers with {clips_per_speaker} clips each; "
            f"only {len(eligible)} speakers qualify"
        )
    chosen = sorted(eligible, key=lambda s: rank("speaker", s))[:speakers]
    return [
        clip
        for speaker in chosen
        for clip in sorted(groups[speaker], key=lambda c: rank("utterance", c.id))[
            :clips_per_speaker
        ]
    ]


def prepare_librispeech(
    source: Path,
    directory: Path,
    *,
    speakers: int = 8,
    clips_per_speaker: int = 2,
    seed: int = 1729,
) -> Path:
    source, directory = source.expanduser().resolve(), directory.expanduser().absolute()
    if source.name not in SPLITS or not source.is_dir():
        raise BenchError(
            "source must be an extracted dev-clean/dev-other/test-clean/test-other directory"
        )
    if not 2 <= speakers <= 1000 or not 1 <= clips_per_speaker <= 100 or seed < 0:
        raise BenchError("require 2–1000 speakers, 1–100 clips per speaker, and a nonnegative seed")
    if directory.exists():
        raise FileExistsError(f"corpus output already exists: {directory}")
    decoder = shutil.which("ffmpeg")
    if not decoder:
        raise BenchError("prepare-librispeech requires ffmpeg on PATH")
    decoder_hash = sha256(Path(decoder))
    version = subprocess.run(
        [decoder, "-version"], capture_output=True, text=True, check=True, timeout=10
    ).stdout
    utterances, transcripts = discover(source)
    selected = select(utterances, speakers, clips_per_speaker, seed)
    transcript_hashes = {item["path"]: item["sha256"] for item in transcripts}
    directory.mkdir(parents=True, exist_ok=False)
    try:
        (directory / "audio").mkdir()
        rows, evidence = [], []
        for clip in selected:
            output = directory / "audio" / f"{clip.id}.wav"
            source_hash = sha256(clip.audio)
            # Fixed output format, one decoding thread, no inherited source metadata.
            # read_corpus checks the decoded WAV before any result can be used.
            subprocess.run(
                [
                    decoder,
                    "-nostdin",
                    "-v",
                    "error",
                    "-n",
                    "-threads",
                    "1",
                    "-i",
                    str(clip.audio),
                    "-map_metadata",
                    "-1",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    "-fflags",
                    "+bitexact",
                    str(output),
                ],
                capture_output=True,
                check=True,
                timeout=60,
            )
            if sha256(clip.audio) != source_hash:
                raise BenchError(f"source audio changed during conversion: {clip.id}")
            rows.append(
                {
                    "id": f"librispeech-{clip.id}",
                    "audio": f"audio/{clip.id}.wav",
                    "reference": clip.reference,
                    "group": f"librispeech-speaker-{clip.speaker}",
                }
            )
            evidence.append(
                {
                    "id": f"librispeech-{clip.id}",
                    "source_audio": str(clip.audio.relative_to(source)),
                    "source_audio_sha256": source_hash,
                    "transcript": str(clip.transcript.relative_to(source)),
                    "transcript_sha256": transcript_hashes[
                        str(clip.transcript.relative_to(source))
                    ],
                    "audio_sha256": sha256(output),
                }
            )
        manifest = directory / "corpus.jsonl"
        manifest.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
        clips = read_corpus(manifest)
        # Detect edits to the selection pool as well as the selected transcripts.
        _, final_transcripts = discover(source)
        if final_transcripts != transcripts or sha256(Path(decoder)) != decoder_hash:
            raise BenchError("transcripts or decoder changed during corpus preparation")
        write_json(
            directory / "provenance.json",
            {
                "schema_version": 1,
                "dataset": "LibriSpeech ASR corpus / OpenSLR 12",
                "source_url": "https://www.openslr.org/12",
                "license": "CC-BY-4.0",
                "split": source.name,
                "selection": SELECTION,
                "seed": seed,
                "speakers": speakers,
                "clips_per_speaker": clips_per_speaker,
                "available_speakers": len({c.speaker for c in utterances}),
                "available_clips": len(utterances),
                "transcript_inventory": transcripts,
                "transcript_inventory_sha256": digest(transcripts),
                "decoder": {"name": "ffmpeg", "version": version, "sha256": decoder_hash},
                "corpus_sha256": sha256(manifest),
                "duration_s": sum(c.duration_s for c in clips),
                "clips": evidence,
            },
        )
        return manifest
    except BaseException:
        # This directory was created exclusively above; never remove existing output.
        shutil.rmtree(directory)
        raise
