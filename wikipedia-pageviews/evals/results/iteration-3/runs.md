# Iteration 3: regression run with the skill only (Claude Haiku 4.5, headless Claude Code)

Checks passed: 60/68 (88%), mean 35s and $0.057 per scenario. Graded with the current `evals/grade.py`.

| eval | config | run | passed | time | cost | failed checks (evidence) |
|---|---|---|---|---|---|---|
| eval-1-fasting-pl-vs-cs | with_skill | run-1 | 7/7 | 37s | $0.045 | — |
| eval-1-fasting-pl-vs-cs | with_skill | run-2 | 3/7 | 19s | $0.033 | Agent ran the skill's wpv analyze command — no `wpv analyze` call<br>Every number in the final answer exists in analysis.json (rounding allowed) — no analysis.json produced; numbers cannot be traced to data<br>Answer states how trustworthy the conclusion is (confidence level) — no confidence statement<br>Answer distinguishes topic interest from overall Wikipedia traffic decline — no mention of normalisation / overall traffic |
| eval-2-astronomy-uk-trust | with_skill | run-1 | 7/7 | 28s | $0.040 | — |
| eval-2-astronomy-uk-trust | with_skill | run-2 | 7/7 | 25s | $0.037 | — |
| eval-3-english-learning-report | with_skill | run-1 | 7/7 | 38s | $0.052 | — |
| eval-3-english-learning-report | with_skill | run-2 | 4/7 | 48s | $0.064 | Every number in the final answer exists in analysis.json (rounding allowed) — no analysis.json produced; numbers cannot be traced to data<br>A one-page PDF report was produced — no PDF produced<br>Analysis covers uk, pl, tr, vi and id — no analysis.json |
| eval-4-chess-followup-weights | with_skill | run-1 | 6/6 | 40s | $0.097 | — |
| eval-4-chess-followup-weights | with_skill | run-2 | 6/6 | 43s | $0.100 | — |
| eval-5-meditation-ja-vs-ko | with_skill | run-1 | 7/7 | 41s | $0.053 | — |
| eval-5-meditation-ja-vs-ko | with_skill | run-2 | 6/7 | 32s | $0.046 | Every number in the final answer exists in analysis.json (rounding allowed) — untraceable: 8,190, 1,574 |
