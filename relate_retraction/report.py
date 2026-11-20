"""Turn Cypher rows into a report: one entry per listed reference, with its strongest findings first."""
from __future__ import annotations

from collections import defaultdict

from .graph import q

CHECK_AT = 60  # findings scored at or above this go to "check before you rely on it"
KEEP_PATHS = 5


def build_report(conn, bib_id: str) -> dict:
    meta = list(conn.execute(q("bibliography"), {"bib": bib_id}))
    if not meta:
        raise SystemExit(f"no bibliography called {bib_id!r} in this store")
    listed = list(conn.execute(q("listed"), {"bib": bib_id}))
    direct = {r["position"]: r for r in conn.execute(q("direct"), {"bib": bib_id})}
    by_pos: dict[int, list] = defaultdict(list)
    for f in conn.execute(q("findings"), {"bib": bib_id}):
        by_pos[f["position"]].append(f)

    items = []
    for row in listed:
        pos = row["position"]
        fs = sorted(by_pos.get(pos, []), key=lambda f: (-f["severity"], f["hops"]))
        d = direct.get(pos)
        top = 100 if d else (fs[0]["severity"] if fs else 0)
        if d:
            status = "retracted"
        elif fs and top >= CHECK_AT:
            status = "check"
        elif fs:
            status = "note"
        elif not row["in_crossref"]:
            status = "notfound"
        elif not row["refs_with_doi"]:
            status = "unknown"
        else:
            status = "clear"
        items.append({
            **row,
            "status": status,
            "severity": top,
            "retraction": d and {k: d[k] for k in ("retracted_on", "reasons", "notice_doi")},
            "layer1": sorted({f["retracted_doi"] for f in fs if f["hops"] == 1}),
            "layer2": sorted({f["retracted_doi"] for f in fs if f["hops"] == 2}),
            "path_count": len(fs),
            "paths": fs[:KEEP_PATHS],
        })

    reached = {f["retracted_doi"] for fs in by_pos.values() for f in fs}
    summary = {
        "listed": len(items),
        "retracted": sum(i["status"] == "retracted" for i in items),
        "check": sum(i["status"] == "check" for i in items),
        "note": sum(i["status"] == "note" for i in items),
        "clear": sum(i["status"] == "clear" for i in items),
        "unknown": sum(i["status"] == "unknown" for i in items),
        "notfound": sum(i["status"] == "notfound" for i in items),
        "with_layer1": sum(bool(i["layer1"]) for i in items),
        "with_layer2": sum(bool(i["layer2"]) for i in items),
        "retracted_papers_reached": len(reached),
        "paths": sum(len(v) for v in by_pos.values()),
        "references_visible": sum(bool(i["refs_with_doi"]) for i in items),
    }
    return {"bibliography": meta[0], "summary": summary, "items": items}


LABEL = {
    "retracted": "RETRACTED",
    "check": "CHECK",
    "note": "note",
    "unknown": "refs not visible",
    "notfound": "not found in Crossref",
    "clear": "clear",
}
INTENT_WORD = {"methodology": "method", "result": "result", "background": "background"}


def _link_word(intents, found) -> str:
    if not found:
        return "cites (intent unknown)"
    words = [INTENT_WORD.get(i, i) for i in intents]
    return f"cites as {'/'.join(words)}" if words else "cites (no intent given)"


def to_markdown(rep: dict) -> str:
    b, s = rep["bibliography"], rep["summary"]
    out = [f"# Retraction exposure: {b['label']}", ""]
    out.append(
        f"{s['listed']} references. Retracted: {s['retracted']}. Check: {s['check']}. "
        f"Note: {s['note']}. Clear: {s['clear']}. Reference list not visible in Crossref: {s['unknown']}. DOI not found in Crossref: {s['notfound']}."
    )
    out.append(
        f"Paths to a retracted paper: {s['paths']} (reaching {s['retracted_papers_reached']} distinct retracted papers). "
        f"References citing a retracted paper directly: {s['with_layer1']}; through one intermediate paper: {s['with_layer2']}."
    )
    out.append("")
    order = {"retracted": 0, "check": 1, "note": 2, "unknown": 3, "notfound": 4, "clear": 5}
    for it in sorted(rep["items"], key=lambda i: (order[i["status"]], -i["severity"], i["position"])):
        if it["status"] in ("clear", "unknown", "notfound"):
            continue
        out.append(f"## [{it['position']}] {LABEL[it['status']]} ({it['severity']}) {it['title'] or it['doi']}")
        out.append(f"doi:{it['doi']}")
        if it["retraction"]:
            r = it["retraction"]
            out.append(f"- Retracted {r['retracted_on']}. Reasons: {'; '.join(r['reasons'][:4])}")
        for p in it["paths"]:
            steps = []
            for k in range(p["hops"]):
                steps.append(f"{p['path'][k]} -[{_link_word(p['intents'][k], p['intent_found'][k])}]->")
            steps.append(f"{p['retracted_doi']} (retracted {p['retracted_on']})")
            flag = " Cited after the retraction notice." if p["cited_after_retraction"] else ""
            out.append(f"- score {p['severity']}, {p['hops']} hop(s): {' '.join(steps)}.{flag}")
        if it["path_count"] > len(it["paths"]):
            out.append(f"- ...and {it['path_count'] - len(it['paths'])} more paths")
        out.append("")
    out.append("Sources: Crossref reference lists; Retraction Watch database (Crossref, CC0); citation intents from Semantic Scholar.")
    return "\n".join(out)
