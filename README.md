# Retraction Reach

Paste a reference list of DOIs. Retraction Reach tells you which references are retracted, which cite a retracted paper, and which cite a paper that cites one, and it shows the citation path for each finding. It runs on [Relate](https://relatedb.ai/), the embedded Cypher graph database, from a single `.rl` file, in the browser (WebAssembly), and as a read-only MCP server for coding or writing agents.

**Try it:** open the web demo (`web/`, see "Run it" below) and pick a bundled list, or paste your own DOIs.

## Why

Reference managers such as Zotero flag a reference when that paper itself is retracted. They do not look at what your references rely on. The Retraction Watch database, which Crossref publishes under CC0, lists 62,431 retracted papers with a DOI in the copy used here (downloaded 2026-11-20). Retracted papers also keep being cited after the notice: in the 16 evaluation lists below, 335 of the 1,194 citations that point at a retracted paper (on a path from a listed reference) were published after the retraction notice (`python eval/post_notice.py`, from the committed `.rl` file; result in `eval/post_notice.json`). If a review you cite took its main estimate from a retracted trial, a direct check says nothing.

Who this is for: authors checking a manuscript before submission, systematic-review teams, and journal editors or research-integrity staff screening submissions.

## What it finds

For each listed reference R:

| Finding | Meaning |
|---|---|
| Retracted | R itself is retracted. |
| One hop | R cites a retracted paper C. |
| Two hops | R cites a paper B, and B cites a retracted paper C. |

Each finding is a path in the graph, and the report shows it: R -> (B) -> C, with C's retraction date, the reasons Retraction Watch records, the notice DOI, and, where Semantic Scholar has it, why the citing paper cited C (method, result or background) with the citing sentence.

### How a finding is scored

The score is a fixed rule written in Cypher (`queries/findings.cypher`), not a model judgment:

- R is retracted: 100.
- One hop: 70, +20 if R was published after C's retraction notice, +10 if R cites C for its method or result (or Semantic Scholar marks the citation influential).
- Two hops: 30, +15 if B cites C for method or result, +10 if B was published after the notice, +10 if R cites B for method or result.

60 or more is marked **Check**; lower scores are **Note**. A reference whose reference list Crossref does not have is marked **Not visible** rather than clear.

## How it uses Relate

Graph model:

```
(:Bibliography {id, label, source_doi})-[:LISTS {position}]->(:Paper {doi, title, date, journal, refs_with_doi})
(:Paper)-[:CITES {intents, influential, context, intent_found, source}]->(:Paper)
(:Paper:Retracted)-[:RETRACTED_BY]->(:Retraction {record_id, date, reasons, notice_doi, source})
```

The core query is a variable-length path match; the path it returns is the evidence the report prints:

```cypher
MATCH (b:Bibliography {id: $bib})-[l:LISTS]->(r:Paper)
MATCH p = (r)-[:CITES*1..2]->(c:Retracted)-[:RETRACTED_BY]->(x:Retraction)
RETURN l.position, [n IN nodes(p) | n.doi] AS path, x.date, x.reasons ...
```

Four Relate surfaces run the same `.cypher` files in `queries/`:

1. **Python, embedded** (`relate-db`): the CLI builds and queries `data/work.rl`.
2. **Single-file store**: `graph/retraction-graph.rl` is committed. It holds all Retraction Watch retractions plus the bundled reference lists and their two-hop neighbourhood. Open it with `relate --database graph/retraction-graph.rl --read-only`.
3. **WebAssembly**: the web demo loads the same graph into Relate's WASM engine in a worker and runs the same queries in the page. The browser build cannot open a `.rl` file (it uses memory or OPFS), so `scripts/export_web.py` exports the store to `web/data/graph.json`, and the page writes it back into Relate with the same `UNWIND ... MERGE` statements the CLI uses.
4. **MCP**: `relate serve --mcp stdio --database graph/retraction-graph.rl --read-only` gives an agent `read_cypher` and `get_schema` over the store; writes are refused. `.mcp.json` registers it for Claude Code. `docs/mcp-transcript.jsonl` is a recorded session (see `scripts/mcp_smoke.py`).

### Where the data lives

- `graph/retraction-graph.rl`: single-file store, committed, compacted with `relate clone`. Single file because it travels with a manuscript: a co-author or editor can open it read-only without running anything else.
- `data/work.rl`: the working store the CLI writes to (not committed).
- `data/cache/`: cached Crossref and Semantic Scholar responses (not committed).

## Run it

Requirements: Python 3.9+, and for the MCP part the Relate CLI ([install](https://relatedb.ai/docs/get-started/install/)).

```bash
pip install -r requirements.txt

# 1. load Retraction Watch (downloads the CC0 CSV, about 65 MB) into data/work.rl
python -m relate_retraction init

# 2. check a list: a file of DOIs, or the reference list of any paper by its DOI
python -m relate_retraction check my-refs.txt --name my-paper
python -m relate_retraction check --from-doi 10.1097/MJT.0000000000001402 --name bryant-2021

# 3. print a stored report again (Markdown, or --json)
python -m relate_retraction report my-paper
```

Measured on the 20 evaluation and held-out lists (21 to 71 references, first run, no cache, without the Semantic Scholar step): 55 s to 6.3 min, median about 1.6 min (`seconds` in `eval/truth/*.json`). Most of the time is Crossref: one request per 80 DOIs, about 1,500 DOIs for the second layer. The Semantic Scholar step adds time; cached runs take seconds.

Web demo, a static site in `web/` (no build step):

```bash
python scripts/export_web.py     # refresh web/data from data/work.rl (already done for the bundled lists)
node scripts/serve.mjs           # or: python -m http.server 8765 -d web
# open http://127.0.0.1:8765
```

For pasted lists the page needs the Retraction Watch list. It is not shipped as one file: `web/data/rw/hashes.bin` holds a sorted 32-bit hash of each of the 62,431 retracted DOIs (250 KB, loaded once), and the records sit in 1,024 shards (`web/data/rw/shards/`) that the page fetches only for DOIs that hit the hash list. Measured in headless Chrome (`node scripts/measure_web.mjs`, results in `docs/web-measurements.json`):

| | Local server | 10 Mbit/s, 40 ms |
|---|---|---|
| Retraction list, old single file (19.7 MB JSON) | 0.18 s | 15.6 s |
| Retraction list, hash index (250 KB) | 0.01 s | 0.28 s |
| Page open to first report (WebAssembly engine 7.1 MB + bundled graph 1.4 MB) | 1.6 s | 8.8 s |

A pasted 31-DOI list (eval case B01) took 35 s end to end and a 16-DOI list 16 s, almost all of it Crossref requests; a reviewer's 7-DOI list took 100 to 150 s while Crossref was slow, so the page shows an estimate of the time left while it waits. For B01, 13 shards were fetched (0.15 s) and its statuses matched the CLI's answer for the same list exactly (1 retracted, 2 check, 13 note, 6 not visible, 9 clear).

Deploying: `vercel.json` serves `web/` as a static site with no build (`.vercelignore` uploads only `web/`). Any static host works; GitHub Pages can publish the `web/` folder.

MCP, for Claude Code or any MCP host:

```bash
relate serve --mcp stdio --database graph/retraction-graph.rl --read-only
python scripts/mcp_smoke.py demo   # scripted session, prints what an agent receives
```

## Does a model need this? The model-only baseline

Same model, no tools, on 16 frozen cases (`eval/cases.json`: 8 random Crossref journal articles from 2019-2024, 8 papers that cite a well-known retracted paper; 4 more held out). Each case is the real reference list of a published paper. The model is asked for the same three findings with paths.

**How to read the tables.** The graph's output is the reference answer: it is computed from Crossref reference lists and Retraction Watch, so its row is 100% by definition, not a measured accuracy. What the tables measure is how much of that answer the model finds without the data. Each cell is "references the model also flagged / references the graph flagged", counted per listed reference. To check the reference answer itself, `eval/audit_paths.py` drew 5 two-hop paths at random (fixed seed) from the 1,503 in the evaluation lists and re-checked every link against Crossref live: 5 of 5 confirmed, each with a Crossref retraction notice on the retracted paper (`eval/path_audit.json`).

Evaluation set, 16 lists:

| | Retracted references | Cite a retracted paper (1 hop) | 2 hops from one | Any 1- or 2-hop exposure |
|---|---|---|---|---|
| Model alone (no tools) | 13/14 (93%) | 9/55 (16%) | 2/285 (0.7%) | 17/292 (5.8%) |
| Model + direct retraction lookup | 14/14 (100%) | 15/55 (27%) | 7/285 (2.5%) | 26/292 (8.9%) |
| Reference answer (graph, 100% by definition) | 14 | 55 | 285 | 292 of 727 references |

Held-out set, 4 lists, run once after the code was frozen (`eval/results_holdout.json`). n is small: 47 exposed references.

| | Retracted references | 1 hop | 2 hops | Any 1- or 2-hop exposure |
|---|---|---|---|---|
| Model alone (no tools) | 3/3 | 2/10 | 0/44 | 3/47 (6.4%) |
| Model + direct retraction lookup | 3/3 | 3/10 | 0/44 | 4/47 (8.5%) |
| Reference answer (graph, 100% by definition) | 3 | 10 | 44 | 47 of 175 references |

The model knows which famous papers were retracted: every DOI it called retracted really is one. It does not know what your references cite. Of the layer-1 links it proposed, 9 of 21 (alone) and 14 of 28 (with the lookup) exist in the Crossref data. The stop rule we froze before running (switch topic if the lookup row reaches 95% exposure) was not triggered.

What this comparison does not test: we did not give the model the reference lists themselves. With each listed paper's reference list pasted in, the one-hop question becomes a lookup the model could probably do; the two-hop question needs the reference lists of about 1,500 cited papers per case (about 60,000 references), which is the part the graph does. So the tables show that the answer depends on citation data, not that a model with that data could not match one hop.

292 of the 727 listed references (40%) reach some retracted paper within two hops, most of them two hops away as background. That is why the report ranks findings: under the fixed scoring rule, 65 references (9%) are marked Check or Retracted.

The numbers come from `eval/results.json` (`python eval/score.py`). How the baseline was run is in `eval/README.md`.

## Limits

- Coverage follows Crossref. Some publishers deposit no reference lists; those references are marked Not visible. A DOI Crossref has no record of is marked Not found. In the evaluation cases, 660 of 727 listed references (91%) had a visible reference list.
- Two-hop edges are stored only when they reach a retracted paper; storing every reference of every reference would multiply the store size by about 40 for no change in the answer.
- Citation intent comes from Semantic Scholar and is missing for many edges ("intent unknown"). Pasted lists in the browser skip the intent lookup.
- Only Retraction Watch entries marked "Retraction" count; expressions of concern and corrections are ignored.
- A citation to a retracted paper is not an error by itself. Papers that study retractions cite them on purpose. The tool shows the path; a person decides.
- Relate keeps the whole graph in memory and allows one writer per store.

## Tools and AI use

- Relate 1.1.0 (Python package `relate-db`, WebAssembly package `@relate/relate-wasm`, CLI for `clone` and `serve --mcp`).
- Data: Crossref REST API, Retraction Watch database (Crossref, CC0), Semantic Scholar Graph API.
- AI: Claude (Anthropic) was used through Claude Code to write most of the code and the first draft of this README, under my direction; I chose the problem, the data sources, the scoring rule and the evaluation design, and checked the outputs. The model-only baseline above uses the same model without tools.

## License

MIT. Retraction Watch data: CC0 (Crossref). Relate WASM files in `web/relate/`: Apache-2.0.
