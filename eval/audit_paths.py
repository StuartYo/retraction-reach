"""Spot-check of the reference answer: draw 5 two-hop paths at random (fixed seed) from the 16 evaluation lists and
check each link again against Crossref live (no cache), plus the retraction record.

    python eval/audit_paths.py   -> eval/path_audit.json

For a path R -> B -> C it checks: B's DOI is in R's Crossref reference list, C's DOI is in B's reference list,
and C is marked retracted (Crossref "updated-by" type retraction, or the Retraction Watch record in the store)."""
import json
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from relate_retraction import graph, sources  # noqa: E402

STORE = HERE.parent / "graph" / "retraction-graph.rl"
SEED = 20261120


def work(doi):
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    req = urllib.request.Request(url, headers={"User-Agent": "retraction-reach-audit/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["message"]


def ref_hit(msg, doi):
    for ref in msg.get("reference", []) or []:
        if sources.norm_doi(ref.get("DOI")) == doi:
            return {"crossref_reference_label": ref.get("key"), "doi_as_deposited": ref.get("DOI")}
    return None


def main():
    ids = [c["id"] for c in json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"] if c["split"] == "eval"]
    conn = graph.connect(STORE, read_only=True)
    paths = []
    for bib in ids:
        for f in conn.execute(graph.q("findings"), {"bib": bib}):
            if f["hops"] == 2:
                paths.append({"bib": bib, "position": f["position"], "path": f["path"], "retracted_on": f["retracted_on"], "notice_doi": f["notice_doi"]})
    conn.close()
    sample = random.Random(SEED).sample(paths, 5)
    out = []
    for s in sample:
        r, b, c = s["path"]
        mr, mb = work(r), work(b)
        time.sleep(0.5)
        mc = work(c)
        upd = [u for u in (mc.get("updated-by") or []) if u.get("type") == "retraction"]
        row = {**s, "R_cites_B": ref_hit(mr, b), "B_cites_C": ref_hit(mb, c),
               "C_crossref_retraction_notice": [{"doi": u.get("DOI"), "source": u.get("source")} for u in upd],
               "C_title": (mc.get("title") or [""])[0]}
        row["all_links_confirmed"] = bool(row["R_cites_B"] and row["B_cites_C"] and (upd or s["notice_doi"]))
        out.append(row)
        print(s["bib"], s["position"], " -> ".join(s["path"]), "OK" if row["all_links_confirmed"] else "NOT CONFIRMED", flush=True)
        time.sleep(0.5)
    res = {"seed": SEED, "two_hop_paths_in_eval": len(paths), "checked": len(out), "confirmed": sum(r["all_links_confirmed"] for r in out),
           "checked_on": time.strftime("%Y-%m-%d"), "paths": out}
    (HERE / "path_audit.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(res["confirmed"], "of", res["checked"], "confirmed;", len(paths), "two-hop paths in the evaluation lists")


if __name__ == "__main__":
    main()
