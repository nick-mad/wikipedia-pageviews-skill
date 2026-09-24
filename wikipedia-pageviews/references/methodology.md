# Methodology

Read this when the user asks how numbers are computed, challenges a conclusion, or
wants to change an assumption.

## Data

- Source: Wikimedia Pageviews REST API (`wikimedia.org/api/rest_v1/metrics/pageviews`).
  Available from 2015-07; monthly data for a month appears a few days after it ends.
- `agent=user`: human traffic only. Wikimedia separately labels `spider` and
  `automated` traffic, and both are excluded. The labelling is heuristic, so some
  bot traffic remains. It usually shows up as a spike.
- `access=all-access` by default. You can choose `desktop`, `mobile-web` or
  `mobile-app` with `--access`.
- **Article matching across languages** goes through Wikidata: one item (QID) has
  one sitelink per language, so the same concept is compared everywhere. When a
  language has no sitelink, the series is reported as missing, not silently dropped.
- **Redirects**: views of pages that redirect to the article (old titles after a
  rename, spelling variants) are added to it. Without this, a renamed article would
  look like a collapse, and the new title would look like a sudden rise.
- **Leading zeros**: if an article has no views at the start of the period, it was
  probably created during the period. Metrics then start at its first view.

## Normalisation

Total Wikipedia traffic has been falling in most languages. The tool shows this as
"overall traffic trend" in NOTES, and part of the fall comes from search snippets and
AI answers. A raw decline in an article's views therefore often means nothing about
the topic. The headline trend is computed on

    share = article views / all views of that language edition × 1,000,000

so it reads "views per million". Raw figures are reported next to it for context.

## Trend

- **Sen's slope** of log(share): the median of all pairwise slopes. One extreme month
  cannot move it much. It is reported as % change per year.
- **Mann-Kendall test**: a rank-based test of monotonic trend that gives the p-value.
  Monthly pageviews are autocorrelated (a good month tends to follow a good month),
  and the plain test would then be overconfident. So the variance is multiplied by
  the Yue & Wang (2004) effective-sample-size factor 1 + 2(1 − 1/n)·r₁, where r₁ is
  the lag-1 autocorrelation of the Sen-detrended series. This matches
  `pymannkendall.yue_wang_modification_test(lag=1)`, except that the factor is
  floored at 1, so the correction only ever makes the test stricter.
  `mk_p_uncorrected` in analysis.json holds the plain value.
- **Recent vs prior**: the last 12 months against the 12 before, or half against half
  for shorter series. A full-year window cancels seasonality.

## Spikes and seasonality

Residuals of log(share) around the Sen trend line get a robust z-score
(0.6745·(r − median)/MAD). Months with z > 3 are outliers. Outliers that recur in the
same calendar month in 2 or more years are **seasonal peaks** (exam season, school
start) and are kept as real interest. The rest are **spikes**: news, viral posts,
bot bursts. The tool reports the share of views that spikes carry, and reruns the
verdict with spikes replaced by the trend value.

## Verdict

| verdict   | rule |
|-----------|------|
| growing / declining | p < 0.10 and \|trend\| ≥ 5 %/yr |
| flat      | p ≥ 0.10, \|trend\| < 5 %/yr and \|recent vs prior\| < 15 % |
| unclear   | anything else (the signals disagree) |

## Confidence (0–5 points)

| criterion | +1 | +0.5 | caps at low |
|---|---|---|---|
| series length | ≥24 months (≥90 days) | 12–23 months | <12 months (<28 days); under a year of daily data caps at medium |
| trend test agrees with verdict | p < 0.05 (or flat and not significant) | 0.05 ≤ p < 0.10 | verdict "unclear" |
| trend, YoY and spike-free YoY point the same way | yes | – | – |
| robust to spikes | spikes < 20 % of views and verdict unchanged without them | – | – |
| volume | median ≥1000/month (≥30/day) | ≥100/month (≥3/day) | below that |

High ≥ 4, medium ≥ 2.5, otherwise low. A stand-in article (not the same Wikidata
item) caps confidence at medium.

## Ranking

Each component is min-max scaled within the compared set (0 = worst, 1 = best):
growth = share trend %/yr; volume = log10(median monthly views);
trust = confidence points / 5. Score = weighted mean. The default weights are
growth 0.5, volume 0.3, trust 0.2, and `--weights` changes them. The scores are
relative: adding or removing a language changes them.

## What this cannot tell you

- Willingness to pay, or what the product should be.
- Countries: Spanish Wikipedia readers come from Spain, Mexico, the US and elsewhere.
  English is read by everyone.
- Interest that never reaches Wikipedia (TikTok, YouTube, local sites, AI assistants).
- Causality: a correlation with an event is not proof that the event caused it.

Good follow-up checks: related articles (a topic cluster), search-trend data,
app-store keyword volumes, and a small paid test in the top-ranked market.
