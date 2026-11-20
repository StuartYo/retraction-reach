# Model-only baseline run log

Model: Claude Opus 5.5 (Claude Code subagent, general-purpose, inheriting the parent model). Date: 2026-11-20.
Each batch got 5 (or fewer) prompt files and could call only Read on those files and Write to the answer files.
Expected tool calls per batch = 2 x files. Any batch with more calls than that would be discarded and rerun.

| Batch | Condition | Cases | Tool calls reported | Expected | OK |
|---|---|---|---|---|---|
| 1 | alone | A01-A05 | 10 | 10 | yes |
| 2 | direct | A01-A05 | 10 | 10 | yes |
| 3 | alone | A06-A08 | 6 | 6 | yes |
| 4 | direct | A06-A08 | 6 | 6 | yes |
| 5 | alone | B01-B02 | 4 | 4 | yes |
| 6 | direct | B01-B02 | 4 | 4 | yes |
| 7 | alone | B03-B04 | 4 | 4 | yes |
| 8 | direct | B03-B04 | 4 | 4 | yes |
| 9 | alone | B05, B06, B09, B10 | 8 | 8 | yes |
| 10 | direct | B05, B06, B09, B10 | 8 | 8 | yes |
| 11 | alone | A09, A10, B07, B08 (held out) | 8 | 8 | yes |
| 12 | direct | A09, A10, B07, B08 (held out) | 8 | 8 | yes |

Held-out batches 11-12 were run once on 2026-11-20 after the code was frozen (`python eval/run_graph.py holdout`, then the two batches, then `python eval/score.py holdout` -> `eval/results_holdout.json`).
