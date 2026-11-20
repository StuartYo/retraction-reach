# Evaluation: graph vs. the same model without the graph

## Cases (`cases.json`, frozen 2026-11-20 before any case was run)

- Stratum A, `random`: a Crossref random sample (`sample=100`) of journal articles published 2019-2024 that have references; the first 10 whose reference lists hold 20-80 DOIs, in the order Crossref returned them.
- Stratum B, `cites-famous-retraction`: for each seed in a list of well-known retracted papers (Wakefield 1998, the two Surgisphere papers, Gautret 2020, STAP 2014, PREDIMED 2013, LaCour 2014, Potti 2006, then two more seeds because two of the first ten DOIs were not retractions), the first paper from 2019-2024 that Semantic Scholar lists as citing it and whose Crossref reference list has 20-80 DOIs and includes the seed.
- 16 cases are the evaluation set; 4 (A09, A10, B07, B08) are held out and run once, after the code is frozen.

A case is the reference list of that paper. The question is the same for the graph and the model: which listed references are retracted, which cite a retracted paper, which cite a paper that cites one.

## Reference answer

`run_graph.py` builds each case in the Relate store (Crossref reference lists, two hops, Retraction Watch) and writes `truth/<id>.json`. This is the reference answer, so the graph row in the results is 100% by construction. What the comparison measures is how much of it a model finds without the graph. The reference answer is limited by Crossref's coverage (see `graph_totals.visible` in `results.json`).

## Model rows

Prompts are in `prompts/`: `alone_<id>.txt` gives numbered DOIs with titles and years; `direct_<id>.txt` adds which listed papers a retraction database marks as retracted (what Zotero would tell you). The model is asked for the three findings as JSON, with paths.

Model: Claude Opus 5.5, the same model that wrote the code. Run as Claude Code subagents told to answer from their own knowledge, with no web, search or shell tools; the only tool calls allowed were reading the prompt file and writing the answer file, and the tool-call counts were checked afterwards (`model/RUNLOG.md`). Answers are in `model/<condition>_<id>.json`. No API key or paid route was used for this run. To rerun it through the Anthropic API with a key of your own, send each prompt file as one user message to the same model with tools disabled and save the reply under the same file name.

## Scoring (`score.py` -> `results.json`)

- Recall per finding type, counted per listed reference (a reference counts once per type even if it has several paths).
- Exposure recall: references with a one-hop or two-hop finding that the model also reported at either hop. Stop rule frozen in advance: if the "model + direct lookup" row reaches 95% exposure recall, the project switches to the backup topic.
- Claimed DOIs that are not retractions in Retraction Watch are counted as false retraction claims.
