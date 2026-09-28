import json
import shutil
import subprocess
import wave

import pytest

from starling_bench.artifacts import BenchError, sha256
from starling_bench.corpus import read_corpus
from starling_bench.librispeech import discover, prepare_librispeech, select


@pytest.fixture
def source(tmp_path):
    decoder = shutil.which("ffmpeg")
    if not decoder:
        pytest.skip("ffmpeg is required for the real FLAC decoding integration test")
    wav = tmp_path / "fixture.wav"
    with wave.open(str(wav), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * 1600)
    flac = tmp_path / "fixture.flac"
    subprocess.run([decoder, "-nostdin", "-v", "error", "-i", str(wav), str(flac)], check=True)
    root = tmp_path / "dev-clean"
    for speaker in (11, 22, 33):
        chapter = root / str(speaker) / "100"
        chapter.mkdir(parents=True)
        lines = []
        for n in range(3):
            clip_id = f"{speaker}-100-{n:04d}"
            shutil.copyfile(flac, chapter / f"{clip_id}.flac")
            lines.append(f"{clip_id} REFERENCE WORDS {n}\n")
        (chapter / f"{speaker}-100.trans.txt").write_text("".join(lines))
    return root


def test_real_flac_preparation_is_reproducible_and_speaker_grouped(source, tmp_path):
    first = prepare_librispeech(source, tmp_path / "first", speakers=2, clips_per_speaker=2)
    second = prepare_librispeech(source, tmp_path / "second", speakers=2, clips_per_speaker=2)
    assert first.read_bytes() == second.read_bytes()
    assert (first.parent / "provenance.json").read_bytes() == (
        second.parent / "provenance.json"
    ).read_bytes()
    clips = read_corpus(first)
    assert len(clips) == 4
    assert len({c.group for c in clips}) == 2
    assert all(c.group == f"librispeech-speaker-{c.id.split('-')[1]}" for c in clips)
    assert all(c.duration_s == 0.1 for c in clips)
    provenance = json.loads((first.parent / "provenance.json").read_text())
    assert provenance["available_clips"] == 9
    assert provenance["corpus_sha256"] == sha256(first)
    assert str(tmp_path) not in json.dumps(provenance)
    for clip, original in zip(clips, provenance["clips"], strict=True):
        assert clip.audio.sha256 == original["audio_sha256"]
        assert sha256(source / original["source_audio"]) == original["source_audio_sha256"]


def test_selection_is_order_independent_and_refuses_insufficient_groups(source):
    utterances, _ = discover(source)
    assert select(utterances, 2, 2, 10) == select(list(reversed(utterances)), 2, 2, 10)
    assert {u.id for u in select(utterances, 2, 2, 10)} != {
        u.id for u in select(utterances, 2, 2, 11)
    }
    with pytest.raises(BenchError, match="only 3 speakers"):
        select(utterances, 4, 2, 10)


def test_existing_corpus_is_preserved(source, tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "sentinel").write_text("keep")
    with pytest.raises(FileExistsError):
        prepare_librispeech(source, output)
    assert (output / "sentinel").read_text() == "keep"


def test_missing_audio_is_not_silently_dropped(source, tmp_path):
    next(source.glob("*/*/*.flac")).unlink()
    with pytest.raises(BenchError, match="missing LibriSpeech audio"):
        prepare_librispeech(source, tmp_path / "missing", speakers=2)
    assert not (tmp_path / "missing").exists()


def test_speaker_metadata_must_match_the_audio_id(source):
    path = source / "11/100/11-100.trans.txt"
    path.write_text("22-100-0000 WRONG SPEAKER\n")
    with pytest.raises(BenchError, match="speaker/chapter mismatch"):
        discover(source)


def test_bad_decoder_input_leaves_no_usable_partial_corpus(source, tmp_path):
    for path in source.glob("*/*/*.flac"):
        path.write_text("not a FLAC file")
    with pytest.raises(subprocess.CalledProcessError):
        prepare_librispeech(source, tmp_path / "broken", speakers=2)
    assert not (tmp_path / "broken").exists()


def test_reference_mutation_during_conversion_is_refused(source, tmp_path, monkeypatch):
    original_run = subprocess.run

    def mutate_after_decode(cmd, **kwargs):
        result = original_run(cmd, **kwargs)
        if "-i" in cmd:
            path = source / "11/100/11-100.trans.txt"
            path.write_text(path.read_text().replace("REFERENCE", "CHANGED"))
        return result

    monkeypatch.setattr(subprocess, "run", mutate_after_decode)
    with pytest.raises(BenchError, match="transcripts or decoder changed"):
        prepare_librispeech(source, tmp_path / "changed", speakers=2)
    assert not (tmp_path / "changed").exists()


@pytest.mark.parametrize("speakers,clips,seed", [(1, 2, 0), (2, 0, 0), (2, 2, -1)])
def test_invalid_selection_settings(source, tmp_path, speakers, clips, seed):
    with pytest.raises(BenchError, match="require 2"):
        prepare_librispeech(
            source, tmp_path / "invalid", speakers=speakers, clips_per_speaker=clips, seed=seed
        )
