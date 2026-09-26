# Iteration 4: regression run with the skill only (Claude Haiku 4.5, headless Claude Code)

Checks passed: 66/68 (97%), mean 34s and $0.056 per scenario. Graded with the current `evals/grade.py`.

| eval | config | run | passed | time | cost | failed checks (evidence) |
|---|---|---|---|---|---|---|
| eval-1-fasting-pl-vs-cs | with_skill | run-1 | 7/7 | 30s | $0.044 | — |
| eval-1-fasting-pl-vs-cs | with_skill | run-2 | 6/7 | 39s | $0.052 | Answer distinguishes topic interest from overall Wikipedia traffic decline — no mention of normalisation / overall traffic |
| eval-2-astronomy-uk-trust | with_skill | run-1 | 7/7 | 26s | $0.038 | — |
| eval-2-astronomy-uk-trust | with_skill | run-2 | 7/7 | 26s | $0.039 | — |
| eval-3-english-learning-report | with_skill | run-1 | 7/7 | 52s | $0.064 | — |
| eval-3-english-learning-report | with_skill | run-2 | 7/7 | 38s | $0.053 | — |
| eval-4-chess-followup-weights | with_skill | run-1 | 6/6 | 34s | $0.089 | — |
| eval-4-chess-followup-weights | with_skill | run-2 | 6/6 | 37s | $0.091 | — |
| eval-5-meditation-ja-vs-ko | with_skill | run-1 | 6/7 | 32s | $0.047 | Answer notes that views are not willingness to pay / purchase intent — no views-vs-payment caveat |
| eval-5-meditation-ja-vs-ko | with_skill | run-2 | 7/7 | 25s | $0.044 | — |
