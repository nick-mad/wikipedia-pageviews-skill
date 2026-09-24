"""wpv: command-line interface used by the agent.

    wpv resolve "<topic>" --langs uk,pl        find the Wikidata item (QID) for a topic
    wpv analyze --topic "Label=Q123" --langs uk,pl   fetch + analyse, writes analysis.json
    wpv show <dir>                               re-print the summary of a saved analysis
    wpv report <dir> --headline ... --summary ...    one-page PDF
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from . import analysis, report, summary, wiki
from .charts import plot
from .http import Client

LANG_RE = re.compile(r"^[a-z]{2,3}(-[a-z]+)*$")


def _langs(s: str) -> list[str]:
    langs = [x.strip().lower() for x in s.split(",") if x.strip()]
    bad = [x for x in langs if not LANG_RE.match(x)]
    if bad or not langs:
        raise argparse.ArgumentTypeError(
            f"bad language code(s) {bad}; use Wikipedia codes like uk,pl,cs,en")
    return list(dict.fromkeys(langs))


def _weights(s: str) -> dict[str, float]:
    out = {"growth": 0.5, "volume": 0.3, "trust": 0.2}
    for part in s.split(","):
        k, _, v = part.partition("=")
        k = k.strip()
        if k not in out:
            raise argparse.ArgumentTypeError(f"unknown weight '{k}'; use growth, volume, trust")
        out[k] = float(v)
    return out


def _slug(text: str) -> str:
    s = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-")
    return s[:60] or "analysis"


def cmd_resolve(args) -> int:
    client = Client()
    langs = args.langs or []
    if args.qid:
        qids, hits = [q.upper() for q in args.qid], {}
    else:
        results = wiki.search(client, args.search_lang, args.query, limit=args.limit)
        if not results:
            print(f'No {args.search_lang}.wikipedia articles found for "{args.query}". '
                  "Try other wording, or --search-lang in the language of the query.")
            return 1
        info = wiki.page_info(client, args.search_lang, [r["title"] for r in results])
        hits = {}
        for r in results:
            i = info.get(r["title"])
            if i and i["qid"] and i["qid"] not in hits:
                hits[i["qid"]] = {**r, **i}
        qids = list(hits)
    ents = wiki.entities(client, qids, langs, label_langs=[args.search_lang])
    print(f'Candidates for "{args.query or ", ".join(qids)}"'
          + (f" (searched {args.search_lang}.wikipedia)" if not args.qid else "") + ":")
    for n, q in enumerate(qids, 1):
        e = ents.get(q)
        if not e:
            print(f"{n}. {q}  NOT FOUND on Wikidata")
            continue
        h = hits.get(q, {})
        flag = "  [DISAMBIGUATION PAGE - do not use]" if h.get("disambiguation") else ""
        print(f"{n}. {q}  {e['label'] or h.get('title')}{flag}")
        if e["description"]:
            print(f"   {e['description']}")
        if h.get("snippet") and not e["description"]:
            print(f"   {h['snippet'][:140]}")
        if langs:
            have = [f"{l}: {t}" for l, t in e["sitelinks"].items() if t]
            miss = [l for l, t in e["sitelinks"].items() if not t]
            print("   articles: " + ("; ".join(have) if have else "none in requested languages")
                  + (f" | NO ARTICLE in: {', '.join(miss)}" if miss else ""))
    print("\nNext: wpv analyze --topic \"<Label>=<QID>\" --langs "
          + (",".join(langs) or "<codes>"))
    return 0


def cmd_analyze(args) -> int:
    topics = [analysis.parse_topic(t) for t in args.topic]
    start, end, notes = analysis.resolve_period(
        args.granularity, args.months, args.days, args.start, args.end)
    client = Client()
    a = analysis.build(client, topics, args.langs, start, end, args.granularity,
                       args.access, "user", not args.no_redirects, args.weights, notes)
    out = args.out or os.path.join(
        "wpv-output", _slug("_".join(t["label"] for t in topics) + "_" + "-".join(args.langs)))
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(a, f, ensure_ascii=False, indent=1)
    if any(s.get("metrics") for s in a["series"]):
        plot(a, os.path.join(out, "chart.png"), args.label_lang)
    print(summary.render(a, out))
    print(f"(requests: {client.stats['network']} network, {client.stats['cache_hits']} cached)")
    return 0


def _load(d: str) -> dict:
    path = d if d.endswith(".json") else os.path.join(d, "analysis.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cmd_show(args) -> int:
    print(summary.render(_load(args.dir), args.dir.removesuffix("/analysis.json")))
    return 0


def cmd_report(args) -> int:
    a = _load(args.dir)
    out_dir = args.dir.removesuffix("/analysis.json")
    fields = {"headline": args.headline, "summary": args.summary,
              "recommendation": args.recommendation}
    errors = [f"--{k} is {len(v)} chars; max {LIM}" for k, v in fields.items()
              if len(v) > (LIM := report.LIMITS[k])]
    if len(args.next_step) > report.MAX_NEXT_STEPS:
        errors.append(f"at most {report.MAX_NEXT_STEPS} --next-step items")
    errors += [f"--next-step '{s[:30]}...' longer than {report.LIMITS['next_step']} chars"
               for s in args.next_step if len(s) > report.LIMITS["next_step"]]
    if not args.allow_unverified:
        known = report.known_numbers(a)
        for k, v in list(fields.items()) + [("next-step", s) for s in args.next_step]:
            bad = report.unverified(v, known)
            if bad:
                errors.append(f"--{k} mentions numbers not found in analysis.json: "
                              f"{', '.join(bad)}. Use the exact figures from `wpv show`, "
                              "or drop them.")
    if errors:
        print("REPORT NOT CREATED:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 2
    pdf = args.out or os.path.join(out_dir, "report.pdf")
    report.build_pdf(a, out_dir, pdf, args.headline, args.summary, args.recommendation,
                     args.next_step, args.label_lang)
    print(f"PDF written: {pdf} (1 page)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wpv", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("resolve", help="find Wikidata items (QIDs) for a topic")
    r.add_argument("query", nargs="?", default="", help="topic text to search for")
    r.add_argument("--search-lang", default="en",
                   help="Wikipedia to search in (use the language the query is written in)")
    r.add_argument("--langs", type=_langs, help="languages to check article coverage for")
    r.add_argument("--qid", action="append", help="look up a known QID instead of searching")
    r.add_argument("--limit", type=int, default=5)
    r.set_defaults(func=cmd_resolve)

    a = sub.add_parser("analyze", help="fetch pageviews and analyse trends")
    a.add_argument("--topic", action="append", required=True,
                   help='"Label=Q123" or "Label=Q1,Q2" (several articles summed); repeatable')
    a.add_argument("--langs", type=_langs, required=True, help="e.g. uk,pl,cs")
    a.add_argument("--months", type=int, help="last N complete months (default 24)")
    a.add_argument("--start", help="YYYY-MM or YYYY-MM-DD")
    a.add_argument("--end", help="YYYY-MM or YYYY-MM-DD (default: last complete month)")
    a.add_argument("--granularity", choices=["monthly", "daily"], default="monthly")
    a.add_argument("--days", type=int, help="daily only: last N days (default 90)")
    a.add_argument("--access", default="all-access",
                   choices=["all-access", "desktop", "mobile-web", "mobile-app"])
    a.add_argument("--no-redirects", action="store_true",
                   help="do not add views of redirects (faster, undercounts)")
    a.add_argument("--weights", type=_weights, default=None,
                   help="ranking weights, e.g. growth=0.6,volume=0.2,trust=0.2")
    a.add_argument("--label-lang", default="en", choices=["en", "uk"], help="chart labels")
    a.add_argument("--out", help="output directory (default wpv-output/<slug>)")
    a.set_defaults(func=cmd_analyze)

    s = sub.add_parser("show", help="print the summary of a saved analysis")
    s.add_argument("dir")
    s.set_defaults(func=cmd_show)

    p = sub.add_parser("report", help="one-page PDF from a saved analysis")
    p.add_argument("dir", help="analysis directory (contains analysis.json)")
    p.add_argument("--headline", required=True)
    p.add_argument("--summary", required=True, help="2-4 sentences, key findings")
    p.add_argument("--recommendation", required=True)
    p.add_argument("--next-step", action="append", default=[], help="repeatable, max 4")
    p.add_argument("--label-lang", default="en", choices=["en", "uk"],
                   help="language of fixed PDF labels; write your text in the user's language")
    p.add_argument("--out", help="PDF path (default <dir>/report.pdf)")
    p.add_argument("--allow-unverified", action="store_true",
                   help="skip the check that numbers in the text exist in analysis.json")
    p.set_defaults(func=cmd_report)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
