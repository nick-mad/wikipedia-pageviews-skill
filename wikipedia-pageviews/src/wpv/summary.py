"""Compact plain-text summary of an analysis, printed to stdout.

Written for a small model to read and quote: one block per series, every
number already rounded the way it should appear in an answer.
"""

from __future__ import annotations

from .stats import fmt_p

MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def fmt_pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.1f}%"



def spike_dates(s: dict, timeline: list[str], gran: str) -> list[str]:
    fmt = (lambda k: f"{k[:4]}-{k[4:6]}") if gran == "monthly" else (
        lambda k: f"{k[:4]}-{k[4:6]}-{k[6:8]}")
    return [fmt(k) for k, m in zip(timeline, s["metrics"]["spike_mask"]) if m]


def render(a: dict, out_dir: str | None = None) -> str:
    p = a["params"]
    gran = p["granularity"]
    unit = "month" if gran == "monthly" else "day"
    win = next((s["metrics"]["comparison_window"] for s in a["series"] if s.get("metrics")), 0)
    lines = [
        f"ANALYSIS  {', '.join(t['label'] for t in p['topics'])} | langs: {', '.join(p['langs'])}"
        f" | {p['start'][:7] if gran == 'monthly' else p['start']} .. "
        f"{p['end'][:7] if gran == 'monthly' else p['end']} {gran} | human views, {p['access']}",
    ]
    if out_dir:
        lines.append(f"saved: {out_dir}/analysis.json, {out_dir}/chart.png")
    lines.append("")
    for s in a["series"]:
        if not s.get("metrics"):
            lines.append(f"{s['id']}: NO DATA - {s.get('missing', 'unknown reason')}")
            lines.append("")
            continue
        m = s["metrics"]
        arts = "; ".join(f"{s['lang']}:{x['title']} (+{x['redirects_counted']} redirects)"
                         + (" [EXPLICIT stand-in article, not the same Wikidata item]"
                            if x.get("explicit") else "")
                         for x in s["articles"])
        c = m["confidence"]
        spikes = spike_dates(s, a["timeline"], gran)
        spike_txt = (f"{len(spikes)} ({', '.join(spikes[:4])}{'...' if len(spikes) > 4 else ''}; "
                     f"{m['spike_share_pct']:.0f}% of views)") if spikes else "none"
        lines += [
            f"{s['id']}  <- {arts}",
            f"  median {m['median_views']:,.0f} views/{unit} | total {m['total_views']:,}",
            f"  trend (share of wiki): {fmt_pct(m['growth_pct_per_year'])}/yr, {fmt_p(m['mk_p'])}"
            f" | raw views trend: {fmt_pct(m['raw_growth_pct_per_year'])}/yr",
            f"  last {m['comparison_window']} {unit}s vs previous {m['comparison_window']}: "
            f"{fmt_pct(m['recent_vs_prior_pct'])} (share), {fmt_pct(m['raw_recent_vs_prior_pct'])} (raw)"
            f" | without spikes: {fmt_pct(m['recent_vs_prior_pct_despiked'])}",
            f"  spikes: {spike_txt}"
            + (f" | recurring seasonal peak in: {', '.join(MONTHS[x - 1] for x in m['seasonal_peak_months'])}"
               " (every year, not a news spike)" if m.get("seasonal_peak_months") else ""),
            f"  VERDICT: {m['verdict'].upper()} | confidence: {c['level'].upper()} "
            f"({c['score']:g}/{c['max_score']})",
            "  why: " + "; ".join(c["reasons"]),
            "",
        ]
    measured = [s for s in a["series"] if s.get("metrics")]
    if len(measured) > 1:
        def best(key, label, fmt):
            s = max(measured, key=lambda x: x["metrics"][key])
            return f"{label}: {s['id']} ({fmt(s['metrics'][key])})"
        lines.append("HIGHLIGHTS (facts to quote; do not infer them yourself):")
        lines.append("  " + best("median_views", "largest audience",
                                 lambda v: f"median {v:,.0f} views/{unit}"))
        lines.append("  " + best("growth_pct_per_year", "best share trend",
                                 lambda v: f"{fmt_pct(v)}/yr"))
        worst = min(measured, key=lambda x: x["metrics"]["growth_pct_per_year"])
        lines.append(f"  worst share trend: {worst['id']} "
                     f"({fmt_pct(worst['metrics']['growth_pct_per_year'])}/yr)")
        growing = [s["id"] for s in measured if s["metrics"]["verdict"] == "growing"]
        lines.append("  growing: " + (", ".join(growing) if growing else "none"))
        lines.append("")
    if a["ranking"]:
        w = p["weights"]
        lines.append("RANKING (relative to this set; weights "
                     + ", ".join(f"{k} {v:g}" for k, v in w.items()) + ")")
        for r in a["ranking"]:
            comp = ", ".join(f"{k} {v:.2f}" for k, v in r["components"].items())
            lines.append(f"  {r['rank']}. {r['id']}  score {r['score']:.2f}  ({comp})")
        lines.append("")
    if a["notes"]:
        lines.append("NOTES:")
        lines += [f"  - {n}" for n in a["notes"]]
    if win:
        lines.append(f"(trend = Sen's slope of the share of all {', '.join(p['langs'])} "
                     "Wikipedia views; p = Mann-Kendall, autocorrelation-corrected)")
    return "\n".join(lines)
