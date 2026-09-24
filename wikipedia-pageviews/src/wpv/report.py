"""One-page PDF report.

Numbers, table, chart, assumptions and limitations come from analysis.json.
The agent contributes only prose (headline, summary, recommendation, next
steps), and every number in that prose is checked against the analysis so a
report cannot quietly contain invented figures.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import re
from xml.sax.saxutils import escape

import matplotlib
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepInFrame, ListFlowable, ListItem,
                                Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from . import charts
from .i18n import labels

LIMITS = {"headline": 120, "summary": 900, "recommendation": 600, "next_step": 200}
MAX_NEXT_STEPS = 4

# ---------------------------------------------------------------------------
# Number verification
# ---------------------------------------------------------------------------

_NUM = re.compile(
    r"(?<![\w.])[-+−]?\d{1,3}(?:[   ,]\d{3})+(?:[.,]\d+)?(?![\d])"
    r"|(?<![\w.])[-+−]?\d+(?:[.,]\d+)?(?![\d])"
)
_SUFFIX = re.compile(r"\s*(k|K|тис\.?|thousand|M|млн|million)\b")


def _parse_number(tok: str) -> list[float]:
    """All plausible readings of a token: '1,234' is 1234 in English and
    1.234 in Ukrainian/Polish, so both are returned and either may match."""
    t = tok.replace("−", "-").replace("\u00a0", " ").replace("\u202f", " ")
    readings = []
    m = re.fullmatch(r"([-+]?\d{1,3}(?:[ ,]\d{3})+)(?:[.,](\d+))?", t)
    if m and not re.match(r"[-+]?0[ ,]", t):
        whole = re.sub(r"[ ,]", "", m.group(1))
        readings.append(float(whole + ("." + m.group(2) if m.group(2) else "")))
    if re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", t):
        readings.append(float(t.replace(",", ".")))
    if not readings:
        raise ValueError(tok)
    return readings


def extract_numbers(text: str) -> list[tuple[str, list[float]]]:
    out = []
    for m in _NUM.finditer(text):
        tok = m.group(0).strip()
        try:
            vals = _parse_number(tok)
        except ValueError:
            continue
        suf = _SUFFIX.match(text, m.end())
        if suf:
            mult = 1e6 if suf.group(1).lower() in ("m", "млн", "million") else 1e3
            vals = [v * mult for v in vals]
            tok += suf.group(0)
        out.append((tok, vals))
    return out


def known_numbers(a: dict) -> set[float]:
    """Every number a report may legitimately mention."""
    vals: set[float] = set(range(0, 13)) | {0.05, 0.01, 0.1, 0.001}  # + usual p thresholds
    p = a["params"]
    for d in (p["start"], p["end"]):
        vals.update({int(d[:4]), int(d[5:7])})
    vals.update(range(2015, dt.date.today().year + 2))

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            # also as printed by the summary (1 decimal), since people round that
            vals.update({float(x), round(float(x), 1)})
        elif isinstance(x, dict):
            for k, v in x.items():
                if k not in ("views", "per_million", "project_views", "spike_mask"):
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            for _, vs in extract_numbers(x):
                vals.update(vs)

    walk({k: a[k] for k in ("series", "ranking", "notes", "params")})
    # derived numbers people naturally quote: period length, counts, weights in %
    vals.add(len(a["timeline"]))
    vals.add(len(p["langs"]))
    vals.update(w * 100 for w in p["weights"].values())
    # pairwise comparisons of audience size ("2.5x", "46% more"), so correct
    # derived statements pass while miscalculated ones are still caught
    meds = [s["metrics"]["median_views"] for s in a["series"] if s.get("metrics")]
    for x in meds:
        for y in meds:
            if x > y > 0:
                vals.update({x / y, (x / y - 1) * 100, (1 - y / x) * 100})
    for s in a["series"]:
        if s.get("metrics"):
            m = s["metrics"]
            vals.add(m["confidence"]["max_score"])
    return vals


def _is_rounding_of(v: float, k: float) -> bool:
    """True if v is k rounded to 0-3 decimals or to 1-4 significant digits
    (so 29,778 may appear as 29,778 / 29,800 / 30K, but not as 31,000)."""
    if v == k:
        return True
    if any(abs(round(k, d) - v) < 1e-9 for d in range(4)):
        return True
    if k != 0 and not (k.is_integer() and 1900 <= k <= 2100):  # years: exact only
        mag = math.floor(math.log10(abs(k)))
        return any(abs(round(k, sig - 1 - mag) - v) < 1e-9 for sig in range(1, 5))
    return False


def _matches(v: float, known: set[float]) -> bool:
    v = abs(v)
    return any(_is_rounding_of(v, abs(k)) for k in known)


_NOT_PROSE = re.compile(r"`[^`]*`|https?://\S+|(?:[\w.~-]*/)+[\w.~-]+")


def unverified(text: str, known: set[float]) -> list[str]:
    text = _NOT_PROSE.sub(" ", text)  # file paths, URLs and code are not claims
    return [tok for tok, vals in extract_numbers(text)
            if not any(_matches(v, known) for v in vals)]


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _register_fonts() -> tuple[str, str]:
    ttf = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
    if "DejaVu" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVu", os.path.join(ttf, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", os.path.join(ttf, "DejaVuSans-Bold.ttf")))
    return "DejaVu", "DejaVu-Bold"


def _pct(x):
    return "–" if x is None else f"{x:+.1f}%"


def build_pdf(a: dict, out_dir: str, pdf_path: str, headline: str, summary: str,
              recommendation: str, next_steps: list[str], label_lang: str = "en") -> str:
    L = labels(label_lang)
    font, bold = _register_fonts()
    p = a["params"]
    gran = p["granularity"]
    unit = L["month" if gran == "monthly" else "day"]

    st = {
        "h": ParagraphStyle("h", fontName=bold, fontSize=15, leading=18, spaceAfter=2),
        "meta": ParagraphStyle("meta", fontName=font, fontSize=7.5, leading=9.5,
                               textColor=colors.HexColor("#555555")),
        "body": ParagraphStyle("body", fontName=font, fontSize=9.2, leading=12.2),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=10, leading=13, spaceBefore=4),
        "cell": ParagraphStyle("cell", fontName=font, fontSize=7.6, leading=9.2),
        "cellb": ParagraphStyle("cellb", fontName=bold, fontSize=7.6, leading=9.2),
        "small": ParagraphStyle("small", fontName=font, fontSize=6.8, leading=8.4,
                                textColor=colors.HexColor("#444444")),
    }

    chart_path = os.path.join(out_dir, f"chart_{label_lang}.png")
    charts.plot(a, chart_path, label_lang, size=(11, 4.2))

    period = (f"{p['start'][:7]} – {p['end'][:7]}" if gran == "monthly"
              else f"{p['start']} – {p['end']}")
    meta = (f"{L['period']}: {period} · {L['langs']}: {', '.join(p['langs'])} · "
            f"{L['source']}: {L['source_text']} · {L['generated']}: {a['generated'][:10]}")

    ranks = {r["id"]: r for r in a["ranking"]}
    head = [L["col_series"], L["col_median"].format(unit=unit), L["col_growth"],
            L["col_yoy"], L["col_spikes"], L["col_verdict"], L["col_conf"]]
    if ranks:
        head.append(L["col_rank"])
    rows = [[Paragraph(escape(h), st["cellb"]) for h in head]]
    order = sorted(a["series"], key=lambda s: ranks.get(s["id"], {}).get("rank", 999))
    conf_color = {"high": "#1f7a4d", "medium": "#a8741a", "low": "#b03a2e"}
    win = 12
    for s in order:
        m = s.get("metrics")
        if not m:
            rows.append([Paragraph(escape(s["id"]), st["cell"]),
                         Paragraph(escape(f"{L['missing']}: {s.get('missing', '')}"), st["cell"])]
                        + [""] * (len(head) - 2))
            continue
        win = m["comparison_window"]
        lvl = m["confidence"]["level"]
        cells = [s["id"], f"{m['median_views']:,.0f}", _pct(m["growth_pct_per_year"]),
                 _pct(m["recent_vs_prior_pct"]), str(m["spike_count"]),
                 L[m["verdict"]],
                 f"<font color='{conf_color[lvl]}'>{L[lvl]}</font>"]
        if ranks:
            r = ranks.get(s["id"])
            cells.append(f"{r['rank']} ({r['score']:.2f})" if r else "–")
        rows.append([Paragraph(c if "<font" in c else escape(c), st["cell"]) for c in cells])

    widths = [48, 24, 20, 22, 13, 20, 18] + ([17] if ranks else [])
    scale = 182 / sum(widths)
    table = Table(rows, colWidths=[w * scale * mm for w in widths], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    for i, row in enumerate(rows[1:], 1):
        if len(row) > 1 and row[2] == "":
            table.setStyle(TableStyle([("SPAN", (1, i), (-1, i))]))

    story = [
        Paragraph(escape(headline), st["h"]),
        Paragraph(escape(meta), st["meta"]),
        Spacer(1, 5),
        Paragraph(escape(summary), st["body"]),
        Spacer(1, 4),
        Image(chart_path, width=182 * mm, height=182 * mm * 4.2 / 11),
        table,
        Spacer(1, 2),
        Paragraph(escape(L["footnote"].format(win=win, unit=unit)), st["small"]),
        Paragraph(escape(L["recommendation"]), st["h2"]),
        Paragraph(escape(recommendation), st["body"]),
    ]
    if next_steps:
        story += [
            Paragraph(escape(L["next_steps"]), st["h2"]),
            ListFlowable([ListItem(Paragraph(escape(x), st["body"]), leftIndent=10)
                          for x in next_steps], bulletType="bullet", start="•",
                         leftIndent=10, bulletFontName=font),
        ]
    caveats = list(L["caveats"])
    trend = a.get("project_trend_pct_per_year") or {}
    if trend:
        caveats.append(L["wiki_trend"] + ": " + ", ".join(
            f"{k} {v:+.1f}%/{'рік' if label_lang == 'uk' else 'yr'}" for k, v in trend.items()) + ".")
    story += [Paragraph(escape(L["assumptions"]), st["h2"]),
              Paragraph(escape(" · ".join(caveats)), st["small"])]

    doc = SimpleDocTemplate(pdf_path, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=headline, author="wikipedia-pageviews skill")
    frame_w, frame_h = A4[0] - 28 * mm, A4[1] - 24 * mm
    # shrink-to-fit guarantees a single page whatever the text length
    doc.build([KeepInFrame(frame_w, frame_h, story, mode="shrink")])
    return pdf_path
