"""Score the model-only answers against the graph's answers. Writes eval/results.json (all numbers in the
README and the write-up come from this file).

    python eval/score.py [eval|holdout]
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from relate_retraction import sources  # noqa: E402

CONDITIONS = {"alone": "Model alone (no tools)", "direct": "Model + direct retraction lookup"}


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def parse_answer(p):
    txt = p.read_text(encoding="utf-8").strip()
    a, b = txt.find("{"), txt.rfind("}")
    try:
        j = json.loads(txt[a : b + 1])
    except Exception:
        return None
    nd = sources.norm_doi
    return {
        "direct": {int(x) for x in j.get("direct", []) if str(x).isdigit()},
        "l1": {(int(x["position"]), nd(x.get("retracted_doi"))) for x in j.get("layer1", []) if str(x.get("position", "")).isdigit()},
        "l2": {(int(x["position"]), nd(x.get("via_doi")), nd(x.get("retracted_doi"))) for x in j.get("layer2", []) if str(x.get("position", "")).isdigit()},
    }


def ratio(a, b):
    return round(a / b, 3) if b else None


def main(split="eval"):
    rw = set(sources.load_retractions())
    cases = [c for c in load(HERE / "cases.json")["cases"] if c["split"] == split]
    per_case, agg = [], {k: dict.fromkeys(
        ["direct_true", "direct_hit", "direct_claimed", "l1_items_true", "l1_items_hit", "l2_items_true", "l2_items_hit",
         "exp_true", "exp_hit", "claims", "claims_not_retracted", "l1_pairs_claimed", "l1_pairs_real", "answered", "cases"], 0) for k in CONDITIONS}
    graph_tot = dict.fromkeys(["listed", "direct", "l1_items", "l2_items", "exp_items", "check", "paths", "visible"], 0)
    for c in cases:
        t = load(HERE / "truth" / f"{c['id']}.json")
        td = set(t["direct"])
        tl1_items = {x["position"] for x in t["layer1"]}
        tl1_pairs = {(x["position"], x["retracted_doi"]) for x in t["layer1"]}
        tl2_items = set(t["layer2_items"])
        texp = tl1_items | tl2_items
        s = t["summary"]
        for k, v in (("listed", s["listed"]), ("direct", len(td)), ("l1_items", len(tl1_items)), ("l2_items", len(tl2_items)),
                     ("exp_items", len(texp)), ("check", len(t["check"])), ("paths", s["paths"]), ("visible", s["references_visible"])):
            graph_tot[k] += v
        row = {"id": c["id"], "stratum": c["stratum"], "graph": {"direct": len(td), "l1_items": len(tl1_items), "l2_items": len(tl2_items), "check": len(t["check"])}}
        for cond in CONDITIONS:
            f = HERE / "model" / f"{cond}_{c['id']}.json"
            a = agg[cond]
            a["cases"] += 1
            a["direct_true"] += len(td)
            a["l1_items_true"] += len(tl1_items)
            a["l2_items_true"] += len(tl2_items)
            a["exp_true"] += len(texp)
            ans = parse_answer(f) if f.exists() else None
            if ans is None:
                row[cond] = None
                continue
            a["answered"] += 1
            pl1_items = {p for p, _ in ans["l1"]}
            pl2_items = {p for p, _, _ in ans["l2"]}
            a["direct_hit"] += len(ans["direct"] & td)
            a["direct_claimed"] += len(ans["direct"])
            a["l1_items_hit"] += len(pl1_items & tl1_items)
            a["l2_items_hit"] += len(pl2_items & tl2_items)
            a["exp_hit"] += len((pl1_items | pl2_items) & texp)
            claimed = {d for _, d in ans["l1"]} | {d for _, _, d in ans["l2"]}
            claimed.discard(None)
            a["claims"] += len(claimed)
            a["claims_not_retracted"] += len([d for d in claimed if d not in rw])
            a["l1_pairs_claimed"] += len(ans["l1"])
            a["l1_pairs_real"] += len(ans["l1"] & tl1_pairs)
            row[cond] = {"direct": len(ans["direct"]), "direct_hit": len(ans["direct"] & td), "l1_items_hit": len(pl1_items & tl1_items),
                         "l2_items_hit": len(pl2_items & tl2_items), "claims": len(claimed), "claims_not_retracted": len([d for d in claimed if d not in rw])}
        per_case.append(row)
    table = []
    for cond, a in agg.items():
        table.append({
            "condition": CONDITIONS[cond], "key": cond, "cases_answered": f"{a['answered']}/{a['cases']}",
            "direct_recall": ratio(a["direct_hit"], a["direct_true"]),
            "layer1_recall": ratio(a["l1_items_hit"], a["l1_items_true"]),
            "layer2_recall": ratio(a["l2_items_hit"], a["l2_items_true"]),
            "exposure_recall": ratio(a["exp_hit"], a["exp_true"]),
            "layer1_pairs_claimed": a["l1_pairs_claimed"], "layer1_pairs_in_data": a["l1_pairs_real"],
            "retracted_dois_claimed": a["claims"], "claimed_dois_not_retracted": a["claims_not_retracted"],
        })
    table.append({"condition": "Graph (this project, Relate)", "key": "graph", "cases_answered": f"{len(cases)}/{len(cases)}",
                  "direct_recall": 1.0, "layer1_recall": 1.0, "layer2_recall": 1.0, "exposure_recall": 1.0,
                  "note": "reference answer: computed from Crossref reference lists + Retraction Watch"})
    stop = None
    d = next(r for r in table if r["key"] == "direct")
    if d["exposure_recall"] is not None:
        stop = d["exposure_recall"] >= 0.95
    out = {"split": split, "cases": len(cases), "graph_totals": graph_tot, "table": table, "per_case": per_case,
           "stop_loss_rule": "switch topic if model + direct lookup reaches >= 95% of the graph's layer-1+2 exposure recall",
           "stop_loss_triggered": stop}
    (HERE / f"results{'' if split == 'eval' else '_' + split}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({"graph_totals": graph_tot, "table": table, "stop_loss_triggered": stop}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "eval")
