"""A self-contained, escaped report generated from verified raw records."""

from html import escape
from pathlib import Path
from statistics import median

from starling_bench.runner import load_evidence


def number(value, suffix=""):
    return "unavailable" if value is None else f"{value:,.2f}{suffix}"


def render(directory: Path, output: Path) -> None:
    sealed, record, result = load_evidence(directory)
    spec = sealed.spec
    e = escape
    rows = []
    for clip in spec.clips:
        arms = {
            a: [
                s.latency_ms
                for s in record.samples
                if s.arm == a and s.clip_id == clip.id and s.phase == "warm"
            ]
            for a in ("baseline", "candidate")
        }
        b = median(arms["baseline"]) if arms["baseline"] else None
        c = median(arms["candidate"]) if arms["candidate"] else None
        rows.append(
            f"<tr><th scope='row'>{e(clip.id)}</th><td>{number(clip.duration_s, ' s')}</td>"
            f"<td>{number(b, ' ms')}</td><td>{number(c, ' ms')}</td>"
            f"<td>{number(b / c if b and c else None, '×')}</td></tr>"
        )
    improvement = result.improvement_pct
    delta = result.wer_delta_pp
    note = (
        "SYNTHETIC DEMO · No speech inference was performed. These numbers test the harness."
        if spec.kind == "synthetic"
        else "SUPERVISED EXPERIMENT · Operator-reviewed programs; no adversarial isolation claim."
    )
    reasons = (
        " ".join(result.reasons)
        if record.status == "complete"
        else (
            "The run did not complete. Inspect the private record and process logs for diagnostics."
        )
    )

    def span(value):
        return f"{value.low:.2f} to {value.high:.2f}" if value else "unavailable"

    text = f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{e(spec.id)} · Starling Bench</title>
<style>
:root{{color-scheme:light;--ink:#182825;--muted:#50645f;--line:#cbd5cc;--paper:#f7f8f2}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);
font:16px/1.6 system-ui,sans-serif}}main{{max-width:1100px;margin:auto;padding:40px 24px 64px}}
.brand,dt,thead{{font:12px/1.5 ui-monospace,monospace;letter-spacing:.08em;
text-transform:uppercase}}
.brand{{border-bottom:2px solid var(--ink);padding-bottom:18px}}h1{{font-size:clamp(30px,5vw,52px);
line-height:1.12;margin:32px 0 16px;overflow-wrap:anywhere}}h2{{font-size:20px;margin-top:36px}}
.notice{{padding:12px 16px;background:#ffebbb;border-left:4px solid #895100}}
.result{{display:flex;gap:24px;align-items:baseline;margin:24px 0}}
.verdict{{font:700 30px ui-monospace,monospace;text-transform:uppercase}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:1px;
background:var(--line);border:1px solid var(--line)}}
.metrics div{{padding:20px;background:var(--paper)}}
dt{{color:var(--muted)}}dd{{margin:8px 0 0;font-size:26px;font-variant-numeric:tabular-nums}}
small{{display:block;color:var(--muted);font-size:13px}}.scroll{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;text-align:right;font-variant-numeric:tabular-nums}}
th,td{{padding:12px;border-bottom:1px solid var(--line)}}th:first-child{{text-align:left}}
tbody th{{font-weight:500}}code{{font-size:12px;overflow-wrap:anywhere}}footer{{margin-top:40px;
border-top:2px solid var(--ink);padding-top:16px;color:var(--muted);font-size:13px}}
</style><main><div class="brand">Starling / Bench &nbsp; · &nbsp; experiment record v1</div>
<h1>{e(spec.id)}</h1><p class="notice">{e(note)}</p>
<p>{e(spec.device.label)} · {e(spec.device.backend.upper())} · {e(spec.model_slug)}</p>
<div class="result"><span class="verdict">{e(result.verdict)}</span>
<span>{e(reasons)}</span></div>
<dl class="metrics">
<div><dt>Measured speedup</dt><dd>{number(result.speedup, "×")}</dd>
<small>Full workload, paired process blocks</small></div>
<div><dt>Baseline / candidate</dt>
<dd>{number(result.baseline_ms)} / {number(result.candidate_ms)}</dd>
<small>Milliseconds per clip; median block means</small></div>
<div><dt>Latency improvement</dt>
<dd>{number(improvement.estimate if improvement else None, "%")}</dd>
<small>{spec.protocol.confidence:.0%} interval: {span(improvement)}%</small></div>
<div><dt>WER baseline / candidate</dt>
<dd>{number(result.baseline_wer_pct)} / {number(result.candidate_wer_pct)}</dd>
<small>Percent; quality delta interval: {span(delta)} points</small></div></dl>
<h2>Workload observations</h2><p>Descriptive per-clip medians. The acceptance decision uses the full
paired workload and quality corpus, including every planned measurement.</p>
<div class="scroll"><table><thead><tr><th scope="col">Clip</th><th scope="col">Audio</th>
<th scope="col">Baseline</th><th scope="col">Candidate</th><th scope="col">Speedup</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<h2>Protocol and provenance</h2>
<p>{spec.protocol.repeats} paired process blocks · {len(spec.clips)} clips ·
{result.quality_groups} quality groups · seed {spec.protocol.seed}. Acceptance requires
more than {spec.acceptance.min_improvement_pct:g}% latency improvement and at most
{spec.acceptance.max_wer_delta_pp:g} percentage points of WER degradation, with uncertainty.</p>
<p>Timing: {e(spec.metric)}. Normalizer: {e(spec.normalizer)}.
Startup and first requests are saved separately and excluded from warm timing.</p>
<p>Baseline binary: <code>{spec.baseline.binary.sha256}</code><br>
Candidate binary: <code>{spec.candidate.binary.sha256}</code><br>
Model: <code>{spec.model.sha256}</code><br>Sealed spec: <code>{sealed.sha256}</code></p>
<p>Source revisions: baseline <code>{e(spec.baseline.source_revision)}</code>;
candidate <code>{e(spec.candidate.source_revision)}</code>.</p>
<footer>Starling Bench {e(record.runner_version)} · {e(record.finished_at)} ·
{record.elapsed_s:.1f} seconds elapsed. Cost, energy, and peak memory were not measured.
Raw transcripts, local paths, environment settings, and server logs are omitted from this
standalone report. Review them before publishing the separate evidence bundle.
</footer></main></html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
