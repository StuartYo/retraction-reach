"""Count citations to a retracted paper that were published after the retraction notice, on the paths the
report finds from the 16 evaluation lists. Reads the committed store graph/retraction-graph.rl (read-only).

    python eval/post_notice.py   -> eval/post_notice.json

A citation is one CITES edge (citing paper -> retracted paper) that is the last link of some path from a listed
reference; each edge is counted once even if several paths or lists reach it. "After the notice" means the citing
paper's publication date (Crossref) is later than the retraction notice date (Retraction Watch); edges with a
missing date on either side are counted as not after."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from relate_retraction import graph  # noqa: E402

STORE = HERE.parent / "graph" / "retraction-graph.rl"


def main():
    ids = [c["id"] for c in json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"] if c["split"] == "eval"]
    conn = graph.connect(STORE, read_only=True)
    edges = {}
    for bib in ids:
        for f in conn.execute(graph.q("findings"), {"bib": bib}):
            key = (f["path"][f["hops"] - 1], f["retracted_doi"])
            edges[key] = edges.get(key, False) or bool(f["cited_after_retraction"])
    rows = list(conn.execute("UNWIND $ds AS d MATCH (p:Paper {doi: d}) RETURN p.doi AS doi, p.date AS date", {"ds": sorted({a for a, _ in edges})}))
    no_date = {r["doi"] for r in rows if not r["date"]}
    missing_date = sum(1 for (a, _) in edges if a in no_date)
    conn.close()
    out = {"store": "graph/retraction-graph.rl", "lists": ids, "citations_to_retracted_on_paths": len(edges),
           "published_after_notice": sum(edges.values()), "citing_date_missing": missing_date}
    (HERE / "post_notice.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
