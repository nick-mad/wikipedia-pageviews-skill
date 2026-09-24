---
name: wikipedia-pageviews
description: Measure and compare public interest in topics across Wikipedia language editions using Wikimedia pageview data, with trend statistics, charts and a one-page PDF report. Use whenever someone asks whether interest in a topic is growing or declining, wants to compare topics or countries/languages, is choosing what course/topic/feature to build next or which language to localize a product into, asks "is this trend real / can we trust this growth", or mentions Wikipedia views, pageviews or audience interest, even if they don't say "Wikipedia".
compatibility: Needs `uv` and internet access to wikimedia.org / wikidata.org. Python deps install automatically on first run.
---

# Wikipedia pageviews: topic interest research

The CLI `scripts/wpv` (inside this skill's directory) does all data work: finding
articles, downloading views, statistics, charts and the PDF. Do not write your own
code to call Wikimedia APIs or compute trends; the CLI already handles redirects,
bot filtering, normalisation, spikes and caching, and its numbers are the ones the
PDF checker accepts.

Run it with the full path, e.g. `/path/to/wikipedia-pageviews/scripts/wpv analyze ...`.
The first run installs dependencies (about 30 s); later runs are fast, and repeated
requests are served from a local cache.

## Workflow

### 1. Resolve the topic to Wikidata items

```bash
wpv resolve "intermittent fasting" --langs pl,cs
wpv resolve "астрономія" --search-lang uk --langs uk
```

Search in English, or in the language the user wrote in (`--search-lang`). Pick the
candidate whose description matches the user's meaning. Never pick one marked
DISAMBIGUATION. The output lists which requested languages have an article.

- **No article in a language**: say so in your answer. This finding matters on its
  own: nobody has written about the topic in that language. To still measure
  something, search that language directly
  (`wpv resolve "<local words>" --search-lang pl --langs pl`). If a close article
  exists, add it to the same topic as an explicit stand-in:
  `--topic "Label=Q1666254,pl:Głodówka lecznicza"`. The tool then marks it EXPLICIT
  and lowers its confidence. Don't analyse a broader concept as a separate topic and
  compare it as if it were the same thing. You have not read the articles, so don't
  claim what they contain (e.g. "the topic is covered inside article X").
- **Broad topics** (a school subject, a field): one article is a thin proxy. You can
  analyse 2–4 core articles as separate topics (e.g. Astronomy, Solar System,
  Black hole), or sum them into one topic with `Label=Q1,Q2,Q3`.
- **Language codes** are Wikipedia subdomains: uk, pl, cs, en, de, es, pt, tr,
  vi, id, zh, ja…

### 2. Analyse

```bash
wpv analyze --topic "Intermittent fasting=Q1666254" --langs pl,cs
wpv analyze --topic "Astronomy=Q333" --langs uk --months 36
wpv analyze --topic "English=Q1860" --langs uk,pl,tr,vi --weights growth=0.3,volume=0.5,trust=0.2
```

Defaults: the last 24 complete months, monthly, human traffic only. Adjust
`--months`, `--start YYYY-MM --end YYYY-MM`, or `--granularity daily --days 90`
(daily is for recent events only). Use `--topic` several times to compare topics.
The command prints a summary. It also saves `analysis.json` and `chart.png` into
`wpv-output/<slug>/` (the output tells you the path).

### 3. Answer from the summary

Base every claim on the printed summary. For each series it gives:
- **trend (share of wiki)**: the main growth figure, in %/year. It is measured on
  the article's share of all views of that language edition, because overall
  Wikipedia traffic is falling in most languages (see NOTES). Raw views are
  shown for context. When raw views fall but the share is flat, the topic is
  holding its ground and the decline is just the site's.
- **last N months vs previous N**: a year-over-year comparison that is immune to
  seasonality. "without spikes" shows the same comparison with news spikes removed.
- **spikes / seasonal peaks**: one-off news bursts versus peaks that recur every year.
- **VERDICT + confidence + why**: growing / declining / flat / unclear, rated
  high / medium / low. The `why` list explains the rating in plain words. Use it
  to answer "can we trust this?".
- **RANKING**: only when several series are compared. The score is relative to
  this set and depends on the weights. If the user states criteria ("we care about
  audience size most"), rerun with matching `--weights`.

A good answer:
1. Starts with the direct answer: growing or not, and which language ranks first.
2. Gives the key numbers exactly as printed (trend %/yr, p-value, median views).
   Copy numbers; don't compute new ones. Ratios, differences and "X% more than Y"
   are where small arithmetic slips creep in. To compare, put both printed figures
   side by side. HIGHLIGHTS already names the largest audience and the best and
   worst trends.
3. Includes one sentence on the measure itself: the trend is the article's share of
   all views of that Wikipedia, and overall traffic of that Wikipedia changed by
   X%/yr (from NOTES). Without it, readers mistake the site-wide decline for lost
   interest in the topic.
4. States confidence and the main reasons for it, including warnings from `why`.
5. Names the caveats that matter here: stand-in articles, missing languages, low
   volume, spikes, and that language ≠ country and views ≠ willingness to pay.
6. Suggests a next check (related articles, another period, other languages).

Keep it short. Founders want the decision, the evidence and the risk.

### 4. PDF report (when asked for a report / something to share)

```bash
wpv report wpv-output/<slug> --label-lang uk \
  --headline "..." --summary "..." --recommendation "..." \
  --next-step "..." --next-step "..."
```

The PDF fills in the chart, the metrics table and the caveats from `analysis.json`.
You write only the prose, in the user's language. `--label-lang uk` gives Ukrainian
fixed labels; use `en` for other languages. The PDF font has no Chinese/Japanese/Korean
glyphs, so for those users write the report text in English. Limits: headline ≤120 characters,
summary ≤900, recommendation ≤600, at most 4 next steps.

Every number in your text must come from the summary; rounding is fine. If you
include a number that is not in the data, the command refuses with
`REPORT NOT CREATED` and lists the offending numbers. Remove them or replace them
with printed figures, then rerun. Do not bypass the check with `--allow-unverified`
unless the user explicitly supplied that number.

Tell the user the PDF path when you are done.

### 5. Follow-up questions

- "Add Slovak" / "try 5 years" / "only mobile": rerun `analyze` with the changed
  parameters. Unchanged data comes from the cache, so this is cheap.
- "Remind me of the numbers": `wpv show wpv-output/<slug>` reprints the saved summary
  without network access.
- Changed criteria for the ranking: rerun with `--weights`.
- "How is this calculated?" / methodological doubts: read
  `references/methodology.md`.

## Things that go wrong

- **Misreading a raw decline as lost interest.** Check the share trend and NOTES first.
- **Treating one spike as growth.** If `why` says the conclusion changes without
  spikes, say the growth is driven by news events.
- **Comparing unlike articles.** Stand-ins (`EXPLICIT` in the summary) and topic
  clusters of different sizes are only approximately comparable.
- **Proxy topics.** "Interest in learning English" is measured through the article
  about the English language. Say which article stands in for the user's question.
- **Errors**: `ERROR:` lines explain what to fix (bad QID, bad language code,
  empty period). Fix the argument; do not rewrite the tool.
