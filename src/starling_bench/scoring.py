"""Paired uncertainty and quality gates, recomputed from complete raw evidence."""

from __future__ import annotations

import math
import random
import statistics
from collections import Counter, defaultdict

from starling_bench.models import Comparison, Interval, RunRecord, SealedSpec
from starling_bench.quality import errors


def interval(estimate: float, draws: list[float], confidence: float) -> Interval:
    draws.sort()
    alpha = (1 - confidence) / 2
    return Interval(
        estimate=estimate,
        low=draws[int(alpha * len(draws))],
        high=draws[min(len(draws) - 1, math.ceil((1 - alpha) * len(draws)) - 1)],
    )


def compare(sealed: SealedSpec, record: RunRecord) -> Comparison:
    spec = sealed.spec
    common = {"spec_sha256": sealed.sha256, "kind": spec.kind}

    def unavailable(reason: str) -> Comparison:
        return Comparison(**common, verdict="unavailable", reasons=(reason,))

    if record.spec_sha256 != sealed.sha256 or record.kind != spec.kind:
        return unavailable("record and sealed spec do not match")
    if record.device_fingerprint != spec.device.fingerprint:
        return unavailable("record device differs from the pinned device")
    if record.status != "complete" or record.failures:
        return unavailable("run did not complete: " + "; ".join(record.failures))
    expected_sessions = {
        (a, r) for a in ("baseline", "candidate") for r in range(spec.protocol.repeats)
    }
    sessions = [(s.arm, s.repeat) for s in record.sessions]
    if len(sessions) != len(expected_sessions) or set(sessions) != expected_sessions:
        return unavailable("missing or duplicate process sessions")
    if len(record.order) != spec.protocol.repeats or any(
        set(pair) != {"baseline", "candidate"} for pair in record.order
    ):
        return unavailable("invalid measurement order")
    starts = Counter(pair[0] for pair in record.order)
    if abs(starts["baseline"] - starts["candidate"]) > 1:
        return unavailable("measurement order is not balanced")
    planned_sessions = [(arm, repeat) for repeat, pair in enumerate(record.order) for arm in pair]
    if sessions != planned_sessions:
        return unavailable("process sessions do not follow the recorded order")
    for session in record.sessions:
        backend = session.reported_backend
        if backend != spec.device.backend and not (
            backend.startswith(spec.device.backend)
            and backend[len(spec.device.backend) :].isdigit()
        ):
            return unavailable("session backend does not match the requested backend")
    samples = {}
    phases = Counter((s.arm, s.repeat, s.phase) for s in record.samples)
    for arm, repeat in expected_sessions:
        if phases[arm, repeat, "first"] != 1 or (
            phases[arm, repeat, "warmup"] != spec.protocol.warmup_requests
        ):
            return unavailable("missing or duplicate first/warmup measurements")
    for sample in record.samples:
        if (sample.arm, sample.repeat) not in expected_sessions:
            return unavailable("sample belongs to an unexpected process session")
        if sample.clip_id not in {c.id for c in spec.clips}:
            return unavailable("sample belongs to an unknown clip")
        if sample.phase != "warm":
            continue
        key = (sample.arm, sample.repeat, sample.clip_id)
        if key in samples:
            return unavailable("duplicate warm measurement")
        samples[key] = sample
    expected = {(a, r, c.id) for a, r in expected_sessions for c in spec.clips}
    if set(samples) != expected:
        return unavailable("incomplete paired workload; failed clips cannot be dropped")

    # Each fresh-process block contributes one equally weighted latency effect.
    # Sum latency over the same full workload, then bootstrap paired process blocks.
    blocks = []
    totals = {"baseline": [], "candidate": []}
    for repeat in range(spec.protocol.repeats):
        for arm in totals:
            totals[arm].append(sum(samples[arm, repeat, c.id].latency_ms for c in spec.clips))
        base, cand = totals["baseline"][-1], totals["candidate"][-1]
        blocks.append(100 * (base - cand) / base)
    rng = random.Random(spec.protocol.seed)
    latency = interval(
        statistics.median(blocks),
        [
            statistics.median(rng.choices(blocks, k=len(blocks)))
            for _ in range(spec.protocol.bootstrap_resamples)
        ],
        spec.protocol.confidence,
    )

    # Average errors across process repeats; resample speakers/sessions, not words.
    groups = defaultdict(lambda: [0.0, 0.0, 0])
    exact = True
    for clip in spec.clips:
        for repeat in range(spec.protocol.repeats):
            base = samples["baseline", repeat, clip.id].text
            cand = samples["candidate", repeat, clip.id].text
            exact = exact and base == cand
            be, count = errors(clip.reference, base)
            ce, _ = errors(clip.reference, cand)
            groups[clip.group][0] += be / spec.protocol.repeats
            groups[clip.group][1] += ce / spec.protocol.repeats
        groups[clip.group][2] += count
    values = list(groups.values())
    words = sum(g[2] for g in values)
    if not words:
        return unavailable("quality corpus has no reference words")
    bwer = 100 * sum(g[0] for g in values) / words
    cwer = 100 * sum(g[1] for g in values) / words
    draws = []
    for _ in range(spec.protocol.bootstrap_resamples):
        sampled = rng.choices(values, k=len(values))
        nwords = sum(g[2] for g in sampled)
        if nwords:
            draws.append(100 * sum(g[1] - g[0] for g in sampled) / nwords)
    if not draws:
        return unavailable("quality bootstrap has no usable reference words")
    quality = interval(cwer - bwer, draws, spec.protocol.confidence)
    base_ms = statistics.median(totals["baseline"]) / len(spec.clips)
    cand_ms = statistics.median(totals["candidate"]) / len(spec.clips)
    results = dict(
        **common,
        baseline_ms=base_ms,
        candidate_ms=cand_ms,
        speedup=base_ms / cand_ms,
        improvement_pct=latency,
        baseline_wer_pct=bwer,
        candidate_wer_pct=cwer,
        wer_delta_pp=quality,
        paired_blocks=len(blocks),
        quality_groups=len(values),
    )
    rules = spec.acceptance
    if bwer > rules.max_wer_pct:
        return Comparison(
            **results, verdict="unavailable", reasons=("baseline quality is invalid",)
        )
    failures = []
    if cwer > rules.max_wer_pct:
        failures.append("candidate exceeds the absolute WER limit")
    if quality.low > rules.max_wer_delta_pp:
        failures.append("quality regression exceeds the allowed margin")
    if rules.require_exact_text and not exact:
        failures.append("candidate changes transcripts under the exact-text contract")
    if latency.high < -rules.max_regression_pct:
        failures.append("latency regression exceeds the allowed margin")
    if failures:
        return Comparison(**results, verdict="fail", reasons=tuple(failures))
    pending = []
    if quality.high > rules.max_wer_delta_pp:
        pending.append("quality uncertainty crosses the allowed margin")
    if latency.low <= rules.min_improvement_pct:
        pending.append("latency uncertainty does not clear the improvement threshold")
    return Comparison(
        **results,
        verdict="inconclusive" if pending else "pass",
        reasons=tuple(pending) or ("quality and latency gates passed",),
    )
