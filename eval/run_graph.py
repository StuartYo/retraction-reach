"""Run every frozen case through the graph and save the reference answer (eval/truth/<id>.json)
plus the two model prompts (eval/prompts/<condition>_<id>.txt)."""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from relate_retraction import graph, report  # noqa: E402
from relate_retraction.__main__ import add_bibliography  # noqa: E402
from relate_retraction import sources  # noqa: E402

PROMPT_HEAD = """Below is the reference list of a published paper, as numbered DOIs with titles.
Using only what you already know (no tools, no browsing), report:
1. "direct": positions of listed papers that have been formally retracted.
2. "layer1": listed papers that themselves cite a retracted paper. Give the position and the retracted paper's DOI.
3. "layer2": listed papers that cite some paper X which in turn cites a retracted paper. Give position, X's DOI (via_doi) and the retracted paper's DOI.
Only list what you are reasonably confident about. Reply with exactly one JSON object and nothing else:
{"direct": [int], "layer1": [{"position": int, "retracted_doi": str}], "layer2": [{"position": int, "via_doi": str, "retracted_doi": str}]}
"""


def main(split=None, only=None):
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
    (HERE / "truth").mkdir(exist_ok=True)
    (HERE / "prompts").mkdir(exist_ok=True)
    conn = graph.connect(graph.DEFAULT_DB)
    retracted = {r["doi"] for r in conn.execute("MATCH (p:Retracted) RETURN p.doi AS doi")}
    for c in cases:
        if split and c["split"] != split:
            continue
        if only and c["id"] not in only:
            continue
        t = time.time()
        src = c["source_doi"]
        dois = sources.crossref_works([src])[src]["refs"]
        add_bibliography(conn, c["id"], f"References of {c['title']}", dois, src, retracted, intents=False)
        rep = report.build_report(conn, c["id"])
        truth = {
            "id": c["id"], "split": c["split"], "source_doi": src,
            "summary": rep["summary"],
            "listed": [{"position": i["position"], "doi": i["doi"], "title": i["title"], "date": i["date"]} for i in rep["items"]],
            "direct": [i["position"] for i in rep["items"] if i["status"] == "retracted"],
            "layer1": [{"position": i["position"], "retracted_doi": d} for i in rep["items"] for d in i["layer1"]],
            "layer2_items": [i["position"] for i in rep["items"] if i["layer2"]],
            "layer2_pairs": [{"position": i["position"], "retracted_doi": d} for i in rep["items"] for d in i["layer2"]],
            "check": [i["position"] for i in rep["items"] if i["status"] in ("retracted", "check")],
            "seconds": round(time.time() - t, 1),
        }
        (HERE / "truth" / f"{c['id']}.json").write_text(json.dumps(truth, indent=1, ensure_ascii=False), encoding="utf-8")
        lines = [f"[{x['position']}] doi:{x['doi']} | {x['title'] or '(title not in Crossref)'} | {(x['date'] or '')[:4]}" for x in truth["listed"]]
        (HERE / "prompts" / f"alone_{c['id']}.txt").write_text(PROMPT_HEAD + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
        lookup = "\nA retraction database lookup was run on the listed papers only. Listed papers marked RETRACTED are retracted; the others are not.\n"
        lines_b = [l + (" | RETRACTED" if x["position"] in truth["direct"] else "") for l, x in zip(lines, truth["listed"])]
        (HERE / "prompts" / f"direct_{c['id']}.txt").write_text(PROMPT_HEAD + lookup + "\n" + "\n".join(lines_b) + "\n", encoding="utf-8")
        s = truth["summary"]
        print(f"{c['id']} {c['split']}: listed {s['listed']} retracted {s['retracted']} L1 {s['with_layer1']} L2 {s['with_layer2']} check {s['check']} ({truth['seconds']}s)", flush=True)
    conn.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    split = args[0] if args and args[0] in ("eval", "holdout") else None
    main(split=split, only=set(args[1:]) or None)
