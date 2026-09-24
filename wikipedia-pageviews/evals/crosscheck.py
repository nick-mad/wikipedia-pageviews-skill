# /// script
# requires-python = ">=3.10"
# dependencies = ["pymannkendall>=1.4", "numpy"]
# ///
"""Independent check of a saved analysis.json against third-party code.

1. Raw numbers: re-downloads the main article's monthly views and the project
   totals with plain urllib (not the skill's client) and compares sums.
2. Statistics: recomputes Sen's slope and the Mann-Kendall p-value (plain and
   Yue-Wang corrected) with the pymannkendall library.

    uv run --script evals/crosscheck.py wpv-output/<slug>/analysis.json
"""

import json
import sys
import time
import urllib.parse
import urllib.request

import numpy as np
import pymannkendall as mk

API = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
UA = {"User-Agent": "wikipedia-pageviews-skill crosscheck"}


def get(url, attempt=0):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA)) as r:
            return sum(i["views"] for i in json.load(r)["items"])
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 0
        if e.code == 429 and attempt < 5:
            time.sleep(2 ** attempt)
            return get(url, attempt + 1)
        raise


def main(path):
    a = json.load(open(path))
    p = a["params"]
    start, end = p["start"].replace("-", ""), p["end"].replace("-", "")
    ok = True
    for s in a["series"]:
        if not s.get("metrics"):
            continue
        lang = s["lang"]
        art = s["articles"][0]
        t = urllib.parse.quote(art["title"].replace(" ", "_"), safe="")
        main_views = get(f"{API}/per-article/{lang}.wikipedia.org/{p['access']}/user/{t}/"
                         f"{p['granularity']}/{start}00/{end}00")
        proj = get(f"{API}/aggregate/{lang}.wikipedia.org/{p['access']}/user/"
                   f"{p['granularity']}/{start}00/{end}00")
        raw_ok = main_views == art["article_views"] and proj == sum(s["project_views"])

        share = np.array(s["per_million"])
        ly = np.log(np.maximum(share, share[share > 0].min() / 2))
        m = s["metrics"]
        lead = int(np.argmax(np.array(s["views"]) > 0))
        ly = ly[lead:]
        steps = 12 if p["granularity"] == "monthly" else 365
        growth = (np.exp(mk.sens_slope(ly).slope * steps) - 1) * 100
        p_orig = mk.original_test(ly).p
        p_yw = mk.yue_wang_modification_test(ly, lag=1).p
        stats_ok = (abs(growth - m["growth_pct_per_year"]) < 0.01
                    and abs(p_orig - m["mk_p_uncorrected"]) < 1e-6
                    and m["mk_p"] >= p_yw - 1e-6)  # ours is floored: never less strict
        ok &= raw_ok and stats_ok
        print(f"{s['id']:30} raw {'OK ' if raw_ok else 'DIFF'} "
              f"(article {main_views:,} vs {art['article_views']:,}; project {proj:,}) | "
              f"stats {'OK ' if stats_ok else 'DIFF'} (growth {growth:.2f} vs "
              f"{m['growth_pct_per_year']:.2f}; p {p_orig:.4g}/{p_yw:.4g} vs "
              f"{m['mk_p_uncorrected']:.4g}/{m['mk_p']:.4g})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
