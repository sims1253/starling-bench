import pytest
from conftest import make_record

from starling_bench.models import RunRecord
from starling_bench.quality import errors, words
from starling_bench.scoring import compare


def replace(record, **changes):
    return RunRecord(**{**record.model_dump(), **changes})


def test_unchanged_is_not_a_win(sealed):
    result = compare(sealed, make_record(sealed, candidate_ms=100))
    assert result.verdict == "inconclusive"
    assert result.improvement_pct.low == result.improvement_pct.high == 0


def test_real_improvement_and_regression(sealed):
    assert compare(sealed, make_record(sealed)).verdict == "pass"
    assert compare(sealed, make_record(sealed, candidate_ms=150)).verdict == "fail"


def test_fast_wrong_answer_fails(sealed):
    result = compare(sealed, make_record(sealed, candidate_ms=1, candidate_text="cached answer"))
    assert result.verdict == "fail"
    assert result.candidate_wer_pct > result.baseline_wer_pct


def test_missing_or_duplicate_measurement_refused(sealed):
    record = make_record(sealed)
    assert compare(sealed, replace(record, samples=record.samples[:-1])).verdict == "unavailable"
    assert (
        compare(sealed, replace(record, samples=record.samples + (record.samples[-1],))).verdict
        == "unavailable"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "failed", "failures": ("timeout",)},
        {"device_fingerprint": "0" * 64},
        {"spec_sha256": "0" * 64},
        {"sessions": ()},
        {"order": ()},
    ],
)
def test_incompatible_or_incomplete_evidence_refused(sealed, changes):
    assert compare(sealed, replace(make_record(sealed), **changes)).verdict == "unavailable"


def test_bootstrap_is_repeatable(sealed):
    record = make_record(sealed)
    assert compare(sealed, record) == compare(sealed, record)


def test_between_process_noise_does_not_become_many_independent_samples(sealed):
    record = make_record(sealed)
    samples = [
        s.model_copy(update={"latency_ms": 20 if s.repeat % 2 else 180})
        if s.arm == "candidate"
        else s
        for s in record.samples
    ]
    result = compare(sealed, replace(record, samples=samples))
    assert result.verdict == "inconclusive"
    assert result.improvement_pct.low < 0 < result.improvement_pct.high


def test_wer_counts_insertions_on_silence_and_unicode():
    assert errors("", "hallucination") == (1, 0)
    assert errors("one two three", "one four") == (2, 3)
    assert words("Straße, ＡＢＣ!") == ["strasse", "abc"]


def test_missing_first_request_invalidates_protocol(sealed):
    record = make_record(sealed)
    filtered = [s for s in record.samples if s.phase != "first"]
    assert compare(sealed, replace(record, samples=filtered)).verdict == "unavailable"


def test_quality_uncertainty_blocks_an_apparent_latency_win(sealed):
    record = make_record(sealed)
    bad_clip = sealed.spec.clips[0].id
    samples = [
        s.model_copy(update={"text": "a small bird"})
        if s.arm == "candidate" and s.clip_id == bad_clip
        else s
        for s in record.samples
    ]
    result = compare(sealed, replace(record, samples=samples))
    assert result.improvement_pct.low > 15
    assert result.verdict == "inconclusive"
    assert result.wer_delta_pp.low == 0 < result.wer_delta_pp.high
