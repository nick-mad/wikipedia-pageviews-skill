"""Wikipedia / Wikidata / Pageviews API calls.

Everything here returns plain Python data; no analysis happens in this module.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from urllib.parse import quote, urlencode

from .http import FOREVER, Client, NotFound

PAGEVIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
WIKIDATA = "https://www.wikidata.org/w/api.php"
MAX_REDIRECTS = 100

_SPECIAL_DBNAMES = {"be-tarask": "be_x_oldwiki"}


def site_id(lang: str) -> str:
    """Wikidata sitelink key for a Wikipedia language code (uk -> ukwiki)."""
    return _SPECIAL_DBNAMES.get(lang, lang.replace("-", "_") + "wiki")


def api_url(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


def _query(client: Client, base: str, ttl=7 * 86400, **params) -> dict:
    params = {"format": "json", "formatversion": "2", **params}
    return client.get_json(f"{base}?{urlencode(params)}", ttl=ttl)


# --------------------------------------------------------------------------
# Topic resolution
# --------------------------------------------------------------------------

def search(client: Client, lang: str, text: str, limit: int = 5) -> list[dict]:
    data = _query(
        client, api_url(lang), action="query", list="search", srsearch=text,
        srlimit=limit, srnamespace=0, srprop="snippet",
    )
    out = []
    for hit in data.get("query", {}).get("search", []):
        snippet = html.unescape(re.sub(r"<[^>]+>", "", hit.get("snippet", "")))
        out.append({"title": hit["title"], "snippet": snippet.strip()})
    return out


def page_info(client: Client, lang: str, titles: list[str]) -> dict[str, dict]:
    """title -> {qid, disambiguation, canonical_title}. Follows redirects."""
    if not titles:
        return {}
    data = _query(
        client, api_url(lang), action="query", titles="|".join(titles),
        prop="pageprops", ppprop="wikibase_item|disambiguation", redirects=1,
    )
    q = data.get("query", {})
    alias = {n["from"]: n["to"] for n in q.get("normalized", [])}
    for r in q.get("redirects", []):
        alias[r["from"]] = r["to"]
    by_title = {}
    for page in q.get("pages", []):
        if page.get("missing"):
            continue
        props = page.get("pageprops", {})
        by_title[page["title"]] = {
            "qid": props.get("wikibase_item"),
            "disambiguation": "disambiguation" in props,
            "canonical_title": page["title"],
        }
    out = {}
    for t in titles:
        target = t
        for _ in range(3):  # normalized -> redirect chains
            target = alias.get(target, target)
        if target in by_title:
            out[t] = by_title[target]
    return out


def entities(client: Client, qids: list[str], langs: list[str],
             label_langs: list[str]) -> dict[str, dict]:
    """qid -> {label, description, sitelinks: {lang: title|None}}.

    All sitelinks are requested (no sitefilter), so the cached response is
    reused when a follow-up question adds or changes languages."""
    if not qids:
        return {}
    data = _query(
        client, WIKIDATA, action="wbgetentities", ids="|".join(sorted(qids)),
        props="labels|descriptions|sitelinks",
        languages="|".join(dict.fromkeys(label_langs + ["en"])),
    )
    out = {}
    for qid, ent in data.get("entities", {}).items():
        if "missing" in ent:
            continue

        def pick(field):
            vals = ent.get(field, {})
            for l in label_langs + ["en"]:
                if l in vals:
                    return vals[l]["value"]
            return next(iter(vals.values()), {}).get("value") if vals else None

        links = ent.get("sitelinks", {})
        out[qid] = {
            "label": pick("labels"),
            "description": pick("descriptions"),
            "sitelinks": {l: links.get(site_id(l), {}).get("title") for l in langs},
        }
    return out


def redirects(client: Client, lang: str, title: str) -> tuple[list[str], bool]:
    """Titles (namespace 0) that redirect to `title`; bool = truncated at cap."""
    found: list[str] = []
    cont: dict = {}
    while True:
        data = _query(
            client, api_url(lang), action="query", titles=title, prop="redirects",
            rdnamespace=0, rdlimit="max", rdprop="title", **cont,
        )
        for page in data.get("query", {}).get("pages", []):
            found += [r["title"] for r in page.get("redirects", [])]
        if len(found) >= MAX_REDIRECTS:
            return found[:MAX_REDIRECTS], True
        if "continue" not in data:
            return found, False
        cont = data["continue"]


# --------------------------------------------------------------------------
# Pageviews
# --------------------------------------------------------------------------

def _ttl_for(end: dt.date):
    first_of_this_month = dt.date.today().replace(day=1)
    return FOREVER if end < first_of_this_month else 6 * 3600


def _ts(d: dt.date) -> str:
    return d.strftime("%Y%m%d") + "00"


def _series(items: list[dict]) -> dict[str, int]:
    return {it["timestamp"][:8]: int(it["views"]) for it in items}


def article_views(client: Client, lang: str, title: str, start: dt.date,
                  end: dt.date, granularity: str, access: str,
                  agent: str) -> dict[str, int]:
    """{YYYYMMDD: views}. Missing days/months (no views) are simply absent."""
    art = quote(title.replace(" ", "_"), safe="")
    url = (f"{PAGEVIEWS}/per-article/{lang}.wikipedia.org/{access}/{agent}/"
           f"{art}/{granularity}/{_ts(start)}/{_ts(end)}")
    try:
        return _series(client.get_json(url, ttl=_ttl_for(end))["items"])
    except NotFound:
        return {}


def project_views(client: Client, lang: str, start: dt.date, end: dt.date,
                  granularity: str, access: str, agent: str) -> dict[str, int]:
    url = (f"{PAGEVIEWS}/aggregate/{lang}.wikipedia.org/{access}/{agent}/"
           f"{granularity}/{_ts(start)}/{_ts(end)}")
    try:
        return _series(client.get_json(url, ttl=_ttl_for(end))["items"])
    except NotFound:
        return {}
