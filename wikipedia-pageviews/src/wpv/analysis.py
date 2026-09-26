"""Build an analysis: topics x languages -> series, metrics, ranking.

The result is a single JSON-serialisable dict (written to analysis.json) that
the chart, report and summary code read. Nothing downstream calls the network.
"""

from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import stats, wiki
from .http import Client

DATA_START = dt.date(2015, 7, 1)  # Pageviews API has no data before this

ASSUMPTIONS = [
    "Wikipedia page views measure curiosity/attention, not willingness to pay.",
    "Only human traffic counted (agent=user); known bots and automated traffic excluded.",
    "Views of redirects to the article (old names, spelling variants) are added to the article.",
    "Growth is measured on the article's share of all views of that language edition "
    "(views per million), so a general decline of Wikipedia traffic is not mistaken for "
    "falling interest in the topic.",
    "One Wikidata item = the same concept in every language, so languages are compared "
    "on equivalent articles.",
]

LIMITATIONS = [
    "Automated-traffic filtering is imperfect; residual bot traffic can create false spikes.",
    "Traffic that moves to search snippets, AI answers or apps is invisible here.",
    "Language edition != country: e.g. English Wikipedia is read worldwide.",
    "A single article is a proxy for a topic; related articles are not included unless "
    "added explicitly.",
    "Articles created or split during the period show artificial growth.",
]


# --------------------------------------------------------------------------
# Periods
# --------------------------------------------------------------------------

def _add_months(d: dt.date, n: int) -> dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    return dt.date(d.year + y, m + 1, 1)


def _month_end(d: dt.date) -> dt.date:
    return _add_months(d, 1) - dt.timedelta(days=1)


def parse_date(s: str, end: bool = False) -> dt.date:
    parts = [int(p) for p in s.split("-")]
    if len(parts) == 2:
        d = dt.date(parts[0], parts[1], 1)
        return _month_end(d) if end else d
    return dt.date(*parts)


def resolve_period(granularity: str, months: int | None, days: int | None,
                   start: str | None, end: str | None,
                   today: dt.date | None = None) -> tuple[dt.date, dt.date, list[str]]:
    """Return (start, end, notes). Defaults: last 24 complete months / 90 days."""
    today = today or dt.date.today()
    notes = []
    if granularity == "monthly":
        last_complete = today.replace(day=1) - dt.timedelta(days=1)
        e = parse_date(end, end=True) if end else last_complete
        if e > last_complete:
            notes.append(f"End moved to {last_complete:%Y-%m}: the current month is incomplete.")
            e = last_complete
        e = _month_end(e.replace(day=1))
        s = parse_date(start) if start else _add_months(e.replace(day=1), -(months or 24) + 1)
        s = s.replace(day=1)
    else:
        yesterday = today - dt.timedelta(days=1)
        e = min(parse_date(end, end=True), yesterday) if end else yesterday
        s = parse_date(start) if start else e - dt.timedelta(days=(days or 90) - 1)
    if s < DATA_START:
        notes.append("Start moved to 2015-07: pageview data does not exist before that.")
        s = DATA_START
    if s > e:
        raise ValueError(f"empty period: {s} .. {e}")
    return s, e, notes


def timeline(start: dt.date, end: dt.date, granularity: str) -> list[str]:
    keys = []
    d = start
    while d <= end:
        keys.append(d.strftime("%Y%m%d"))
        d = _add_months(d, 1) if granularity == "monthly" else d + dt.timedelta(days=1)
    return keys


# --------------------------------------------------------------------------
# Topics
# --------------------------------------------------------------------------

def parse_topic(spec: str) -> dict:
    """Parse a --topic value.

    'Label=Q1,Q2'              Wikidata items; each language uses its sitelink.
    'Label=Q1,pl:Głodówka'     plus an explicit article for one language
                               (a stand-in where the language has no sitelink).
    'Q1'                       label defaults to the id.
    """
    label, ids = spec.split("=", 1) if "=" in spec else (spec, spec)
    qids, titles, bad = [], {}, []
    for part in (x.strip() for x in ids.split(",")):
        if not part:
            continue
        lang, sep, title = part.partition(":")
        if sep and lang.strip().islower() and title.strip():
            titles.setdefault(lang.strip(), []).append(title.strip())
        elif part.upper().startswith("Q") and part[1:].isdigit():
            qids.append(part.upper())
        else:
            bad.append(part)
    if bad or not (qids or titles):
        raise ValueError(f"topic '{spec}': expected Wikidata ids like Q123 or "
                         f"lang:Article title, got {bad or ids!r}")
    return {"label": label.strip(), "qids": qids, "titles": titles}


def build(client: Client, topics: list[dict], langs: list[str],
          start: dt.date, end: dt.date, granularity: str = "monthly",
          access: str = "all-access", agent: str = "user",
          include_redirects: bool = True, weights: dict | None = None,
          notes: list[str] | None = None) -> dict:
    weights = weights or {"growth": 0.5, "volume": 0.3, "trust": 0.2}
    all_qids = sorted({q for t in topics for q in t["qids"]})
    ents = wiki.entities(client, all_qids, langs, label_langs=[])  # English labels only
    notes = list(notes or [])
    for q in all_qids:
        if q not in ents:
            notes.append(f"{q} not found on Wikidata; ignored.")

    # Which titles to fetch per (topic, lang)
    plan: dict[tuple[str, str], list[dict]] = {}
    for t in topics:
        for lang in langs:
            arts = []
            for q in t["qids"]:
                title = ents.get(q, {}).get("sitelinks", {}).get(lang)
                if title:
                    arts.append({"qid": q, "title": title, "redirects": [], "proxy": False})
            if lang in t["titles"]:
                info = wiki.page_info(client, lang, t["titles"][lang])
                for title in t["titles"][lang]:
                    if any(a["title"] == info.get(title, {}).get("canonical_title") for a in arts):
                        continue
                    if title not in info:
                        notes.append(f"{lang}:{title} does not exist on {lang}.wikipedia; ignored.")
                        continue
                    arts.append({"qid": info[title]["qid"], "redirects": [], "proxy": True,
                                 "title": info[title]["canonical_title"]})
            plan[(t["label"], lang)] = arts

    with ThreadPoolExecutor(max_workers=8) as pool:
        if include_redirects:
            jobs = {(lang, a["title"]): pool.submit(wiki.redirects, client, lang, a["title"])
                    for (_, lang), arts in plan.items() for a in arts}
            for (label, lang), arts in plan.items():
                for a in arts:
                    a["redirects"], truncated = jobs[(lang, a["title"])].result()
                    if truncated:
                        notes.append(f"{lang}:{a['title']}: only first "
                                     f"{wiki.MAX_REDIRECTS} redirects counted.")

        titles = {(lang, t) for (_, lang), arts in plan.items()
                  for a in arts for t in [a["title"], *a["redirects"]]}
        view_jobs = {k: pool.submit(wiki.article_views, client, k[0], k[1], start, end,
                                    granularity, access, agent) for k in titles}
        proj_jobs = {lang: pool.submit(wiki.project_views, client, lang, start, end,
                                       granularity, access, agent) for lang in langs}
        views = {k: f.result() for k, f in view_jobs.items()}
        project = {lang: f.result() for lang, f in proj_jobs.items()}

    keys = timeline(start, end, granularity)
    series = []
    for (label, lang), arts in plan.items():
        sid = f"{label} [{lang}]"
        row = {"id": sid, "topic": label, "lang": lang, "articles": [], "metrics": None}
        if not arts:
            row["missing"] = f"no {lang}.wikipedia article for this topic"
            series.append(row)
            continue
        total = np.zeros(len(keys))
        for a in arts:
            main = np.array([views[(lang, a["title"])].get(k, 0) for k in keys], float)
            redir = np.zeros(len(keys))
            for t in a["redirects"]:
                redir += np.array([views[(lang, t)].get(k, 0) for k in keys], float)
            total += main + redir
            row["articles"].append({
                "qid": a["qid"], "title": a["title"],
                "url": f"https://{lang}.wikipedia.org/wiki/{a['title'].replace(' ', '_')}",
                "redirects_counted": len(a["redirects"]),
                "redirect_views": int(redir.sum()), "article_views": int(main.sum()),
                "explicit": a["proxy"],
            })
        proj = np.array([project[lang].get(k, 0) for k in keys], float)
        if not proj.any():
            row["missing"] = f"no project-level data for {lang}.wikipedia"
            series.append(row)
            continue
        share = np.divide(total * 1e6, proj, out=np.zeros_like(total), where=proj > 0)
        row["views"] = total.astype(int).tolist()
        row["per_million"] = [round(x, 4) for x in share]
        row["project_views"] = proj.astype(int).tolist()
        if total.sum() == 0:
            row["missing"] = "article exists but had no recorded views in the period"
        else:
            # Leading zeros usually mean the article did not exist yet; analysing
            # them would report fake growth, so metrics start at the first view.
            lead = int(np.argmax(total > 0))
            m = stats.describe(total[lead:], share[lead:], granularity,
                               [int(k[4:6]) for k in keys[lead:]])
            m["spike_mask"] = [False] * lead + m["spike_mask"]
            if lead >= 2:
                m["data_starts"] = keys[lead]
                m["confidence"]["reasons"].append(
                    f"~ no views before {keys[lead]} (article probably created then); "
                    "metrics cover only the period with data")
            if any(x["explicit"] for x in row["articles"]):
                m["confidence"]["reasons"].append(
                    "- uses an explicitly chosen stand-in article, not the same Wikidata item "
                    "as other languages: cross-language comparison is approximate")
                if m["confidence"]["level"] == "high":
                    m["confidence"]["level"] = "medium"
            row["metrics"] = m
        series.append(row)

    project_trend = {}
    for lang in langs:
        p = np.array([project[lang].get(k, 0) for k in keys], float)
        if p.any():
            g = stats.annual_growth(p, 12 if granularity == "monthly" else 365)
            project_trend[lang] = round(g, 1)
            notes.append(f"{lang}.wikipedia overall traffic trend: {g:+.1f}%/year "
                         "(normalisation removes this).")

    return {
        "schema": 1,
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "params": {
            "topics": topics,
            "langs": langs, "start": start.isoformat(), "end": end.isoformat(),
            "granularity": granularity, "access": access, "agent": agent,
            "include_redirects": include_redirects, "weights": weights,
        },
        "entities": ents,
        "timeline": keys,
        "series": series,
        "ranking": stats.rank(series, weights),
        "project_trend_pct_per_year": project_trend,
        "notes": notes,
        "assumptions": ASSUMPTIONS,
        "limitations": LIMITATIONS,
    }



def write_csv(a: dict, path: str) -> str:
    """Long-format time series (one row per period x series) for spreadsheets."""
    import csv

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["period", "topic", "lang", "views", "project_views",
                    "views_per_million", "news_spike"])
        for s in a["series"]:
            if "views" not in s:
                continue
            spikes = (s.get("metrics") or {}).get("spike_mask") or [False] * len(s["views"])
            for k, v, p, pm, sp in zip(a["timeline"], s["views"], s["project_views"],
                                       s["per_million"], spikes):
                period = f"{k[:4]}-{k[4:6]}" if a["params"]["granularity"] == "monthly" \
                    else f"{k[:4]}-{k[4:6]}-{k[6:]}"
                w.writerow([period, s["topic"], s["lang"], v, p, pm, int(sp)])
    return path
