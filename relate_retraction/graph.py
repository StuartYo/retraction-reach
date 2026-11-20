"""Write the citation + retraction graph into a Relate store and read reports back with Cypher."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import relate

from . import sources

QUERIES = Path(__file__).resolve().parent.parent / "queries"
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "work.rl"


def q(name: str) -> str:
    return (QUERIES / f"{name}.cypher").read_text(encoding="utf-8")


def connect(db: Path | str = DEFAULT_DB, read_only: bool = False):
    db = str(db)
    if read_only:
        try:
            return relate.connect(db, read_only=True)
        except TypeError:
            pass
    return relate.connect(db)


def _batches(rows: list, n: int = 5000):
    for i in range(0, len(rows), n):
        yield rows[i : i + n]


def ensure_schema(conn) -> None:
    for stmt in (
        "CREATE CONSTRAINT paper_doi IF NOT EXISTS FOR (p:Paper) REQUIRE p.doi IS UNIQUE",
        "CREATE CONSTRAINT bib_id IF NOT EXISTS FOR (b:Bibliography) REQUIRE b.id IS UNIQUE",
        "CREATE CONSTRAINT retraction_id IF NOT EXISTS FOR (r:Retraction) REQUIRE r.record_id IS UNIQUE",
    ):
        conn.execute(stmt)


def load_retractions(conn, retractions: dict[str, dict]) -> int:
    """Every Retraction Watch retraction becomes (:Paper:Retracted)-[:RETRACTED_BY]->(:Retraction)."""
    ensure_schema(conn)
    rows = list(retractions.values())
    for chunk in _batches(rows):
        conn.execute(
            """
            UNWIND $rows AS r
            MERGE (p:Paper {doi: r.doi})
              ON CREATE SET p.title = r.title, p.journal = r.journal, p.date = r.original_date
            SET p:Retracted
            MERGE (x:Retraction {record_id: r.record_id})
            SET x.date = r.date, x.reasons = r.reasons, x.notice_doi = r.notice_doi,
                x.source = 'Retraction Watch via Crossref (CC0)'
            MERGE (p)-[:RETRACTED_BY]->(x)
            """,
            {"rows": chunk},
        )
    meta = {"rw_loaded": date.today().isoformat(), "rw_retractions": len(rows)}
    conn.execute("MERGE (m:Meta {id: 'dataset'}) SET m += $m", {"m": meta})
    return len(rows)


def expand_bibliography(dois: list[str], retracted: set[str], progress=print) -> dict:
    """Two citation layers out from the listed DOIs, using Crossref reference lists.

    layer 0: listed papers (R); layer 1: everything R cites (B); layer 2: what B cites.
    Layer-2 edges are kept only when they point at a retracted paper (the graph would otherwise
    hold every reference of every reference); counts of what was dropped are stored on B."""
    listed = [d for d in dict.fromkeys(sources.norm_doi(x) for x in dois) if d]
    progress(f"  layer 0: {len(listed)} listed DOIs")
    works0 = sources.crossref_works(listed)
    b_set: set[str] = set()
    for d in listed:
        b_set.update(works0[d].get("refs", []))
    progress(f"  layer 1: {len(b_set)} cited DOIs, fetching their reference lists from Crossref")
    works1 = sources.crossref_works(sorted(b_set), progress=lambda a, b: progress(f"    {a}/{b}") if a % 800 == 0 or a == b else None)
    papers, edges = {}, []
    for d in listed:
        papers[d] = works0[d]
        for b in works0[d].get("refs", []):
            edges.append((d, b))
    l2_kept = 0
    for b in b_set:
        w = works1.get(b) or {"doi": b, "missing": True, "refs": []}
        papers.setdefault(b, w)
        for c in w.get("refs", []):
            if c in retracted:
                edges.append((b, c))
                l2_kept += 1
    progress(f"  edges: {len(edges)} (layer-2 edges kept because they reach a retracted paper: {l2_kept})")
    return {"listed": listed, "papers": papers, "edges": edges}


def write_bibliography(conn, bib_id: str, label: str, expansion: dict, source_doi: str | None = None) -> None:
    ensure_schema(conn)
    rows = []
    for d, w in expansion["papers"].items():
        rows.append({
            "doi": d,
            "title": w.get("title") or None,
            "journal": w.get("journal") or None,
            "date": w.get("date"),
            "in_crossref": not w.get("missing", False),
            "references_count": w.get("references_count"),
            "refs_with_doi": len(w.get("refs", [])),
        })
    for chunk in _batches(rows):
        conn.execute(
            """
            UNWIND $rows AS r
            MERGE (p:Paper {doi: r.doi})
            SET p.title = coalesce(r.title, p.title), p.journal = coalesce(r.journal, p.journal),
                p.date = coalesce(r.date, p.date), p.in_crossref = r.in_crossref,
                p.references_count = r.references_count, p.refs_with_doi = r.refs_with_doi
            """,
            {"rows": chunk},
        )
    conn.execute(
        "MERGE (b:Bibliography {id: $id}) SET b.label = $label, b.source_doi = $src, b.created = $created, b.size = $n",
        {"id": bib_id, "label": label, "src": source_doi, "created": date.today().isoformat(), "n": len(expansion["listed"])},
    )
    conn.execute(
        """
        UNWIND $rows AS r
        MATCH (b:Bibliography {id: $id}), (p:Paper {doi: r.doi})
        MERGE (b)-[l:LISTS]->(p) SET l.position = r.pos
        """,
        {"id": bib_id, "rows": [{"doi": d, "pos": i + 1} for i, d in enumerate(expansion["listed"])]},
    )
    erows = [{"a": a, "b": b} for a, b in expansion["edges"]]
    for chunk in _batches(erows):
        conn.execute(
            """
            UNWIND $rows AS e
            MATCH (a:Paper {doi: e.a}), (c:Paper {doi: e.b})
            MERGE (a)-[r:CITES]->(c)
              ON CREATE SET r.source = 'Crossref reference list'
            """,
            {"rows": chunk},
        )


def enrich_intents(conn, bib_id: str, progress=print, max_citing: int = 60) -> int:
    """Look up Semantic Scholar citation intents for the edges that lie on a path to a retracted paper.
    The unauthenticated S2 API is slow, so at most max_citing citing papers are looked up per list:
    listed papers first (their edges decide one-hop scores), then the intermediate papers. Edges not
    looked up keep intent_found = null and are shown as "intent not looked up"."""
    rows = list(conn.execute(q("path_edges"), {"bib": bib_id}))
    listed = {r["doi"] for r in conn.execute(q("listed"), {"bib": bib_id})}
    todo = {r["citing"] for r in rows if r.get("checked") is None}
    citing = sorted(todo & listed) + sorted(todo - listed)
    if len(citing) > max_citing:
        progress(f"  intents: {len(citing)} citing papers, looking up the first {max_citing}")
        citing = citing[:max_citing]
    progress(f"  intents: {len(citing)} citing papers to look up on Semantic Scholar")
    updates = []
    for i, a in enumerate(citing, 1):
        refs = sources.s2_reference_intents(a)
        for r in rows:
            if r["citing"] != a:
                continue
            info = refs.get(r["cited"])
            updates.append({
                "a": a, "c": r["cited"],
                "intents": info["intents"] if info else [],
                "influential": bool(info and info["influential"]),
                "context": info["context"] if info else None,
                "found": info is not None,
            })
        if i % 10 == 0:
            progress(f"    {i}/{len(citing)}")
    for chunk in _batches(updates):
        conn.execute(
            """
            UNWIND $rows AS u
            MATCH (a:Paper {doi: u.a})-[r:CITES]->(c:Paper {doi: u.c})
            SET r.intents = u.intents, r.influential = u.influential, r.context = u.context,
                r.intent_found = u.found, r.intent_source = 'Semantic Scholar'
            """,
            {"rows": chunk},
        )
    return len(updates)


def stats(conn) -> dict:
    out = {}
    for key, stmt in {
        "papers": "MATCH (p:Paper) RETURN count(p) AS n",
        "retracted": "MATCH (p:Retracted) RETURN count(p) AS n",
        "cites": "MATCH ()-[r:CITES]->() RETURN count(r) AS n",
        "bibliographies": "MATCH (b:Bibliography) RETURN count(b) AS n",
    }.items():
        out[key] = list(conn.execute(stmt))[0]["n"]
    return out
