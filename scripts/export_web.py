"""Export what the browser demo needs from the Relate store.

web/data/graph.json      the bundled reference lists and their two-layer neighbourhood (read by the WASM engine)
web/data/rw/             every Retraction Watch retraction, for checking pasted lists live:
                         hashes.bin = sorted 32-bit FNV-1a hashes of the DOIs (about 250 KB, loaded once),
                         shards/NNN.json = the records themselves, split by the top 10 bits of the hash and
                         fetched only for the DOIs that hit the hash list.

    python scripts/export_web.py                      # from data/work.rl
    python scripts/export_web.py --index-from FILE    # rebuild only web/data/rw/ from an old retracted.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from relate_retraction import graph  # noqa: E402

OUT = ROOT / "web" / "data"


SHARD_BITS = 10
COLUMNS = ["doi", "date", "record_id", "title", "reasons", "notice_doi"]


def fnv1a32(s):
    h = 0x811C9DC5
    for b in s.encode("utf-8"):
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


def write_rw_index(slim, meta):
    """Membership list the page loads once, plus the records split into shards fetched on demand."""
    import shutil
    import struct
    rw = OUT / "rw"
    if rw.exists():
        shutil.rmtree(rw)
    (rw / "shards").mkdir(parents=True)
    hashes = sorted({fnv1a32(r[0]) for r in slim})
    (rw / "hashes.bin").write_bytes(struct.pack(f"<{len(hashes)}I", *hashes))
    shards = {}
    for r in slim:
        shards.setdefault(fnv1a32(r[0]) >> (32 - SHARD_BITS), []).append(r)
    for k in range(1 << SHARD_BITS):
        (rw / "shards" / f"{k:03x}.json").write_text(json.dumps({"rows": shards.get(k, [])}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (rw / "meta.json").write_text(json.dumps({**meta, "columns": COLUMNS, "hash": "fnv1a32(utf-8 lower-case DOI)", "shard_bits": SHARD_BITS,
                                              "dois": len(slim), "hashes": len(hashes)}), encoding="utf-8")
    print(f"rw index: {len(slim)} retractions, {len(hashes)} hashes, {len(shards)} shards")


def rows(conn, stmt, params=None):
    return list(conn.execute(stmt, params or {}))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    conn = graph.connect(graph.DEFAULT_DB)
    bibs = rows(conn, "MATCH (b:Bibliography) RETURN b.id AS id, b.label AS label, b.source_doi AS source_doi, b.size AS size, b.created AS created ORDER BY b.id")
    for b in bibs:
        b["listed"] = [r["doi"] for r in rows(conn, "MATCH (:Bibliography {id:$id})-[l:LISTS]->(p:Paper) RETURN p.doi AS doi ORDER BY l.position", {"id": b["id"]})]
    # papers within two CITES hops of any listed paper
    papers = rows(conn, """
        MATCH (:Bibliography)-[:LISTS]->(r:Paper)
        OPTIONAL MATCH (r)-[:CITES*1..2]->(n:Paper)
        WITH collect(DISTINCT r) + collect(DISTINCT n) AS ps
        UNWIND ps AS p
        WITH DISTINCT p WHERE p IS NOT NULL
        RETURN p.doi AS doi, p.title AS title, p.date AS date, p.journal AS journal,
               p.in_crossref AS in_crossref, p.references_count AS references_count,
               p.refs_with_doi AS refs_with_doi, p:Retracted AS retracted
    """)
    keep = {p["doi"] for p in papers}
    cites = rows(conn, """
        MATCH (a:Paper)-[k:CITES]->(c:Paper)
        RETURN a.doi AS a, c.doi AS b, k.intents AS intents, k.influential AS influential,
               k.context AS context, k.intent_found AS intent_found, k.intent_source AS intent_source
    """)
    cites = [c for c in cites if c["a"] in keep and c["b"] in keep]
    # drop titles of intermediate papers that lie on no path to a retraction (keeps the file small)
    on_path = set()
    for b in bibs:
        for r in rows(conn, graph.q("path_edges"), {"bib": b["id"]}):
            on_path.update((r["citing"], r["cited"]))
    # The browser copy keeps only what the report can reach: listed papers and every paper on a path to a
    # retraction. The .rl file keeps the full two-hop neighbourhood.
    listed = {d for b in bibs for d in b["listed"]}
    keep = listed | on_path
    papers = [p for p in papers if p["doi"] in keep]
    cites = [c for c in cites if c["a"] in keep and c["b"] in keep]
    retractions = rows(conn, """
        MATCH (p:Retracted)-[:RETRACTED_BY]->(x:Retraction)
        RETURN p.doi AS doi, p.title AS title, p.journal AS journal, p.date AS original_date,
               x.record_id AS record_id, x.date AS date, x.reasons AS reasons, x.notice_doi AS notice_doi
    """)
    meta = rows(conn, "MATCH (m:Meta {id:'dataset'}) RETURN m.rw_loaded AS rw_loaded, m.rw_retractions AS rw_retractions")[0]
    near = [r for r in retractions if r["doi"] in keep]
    snap = {"meta": meta, "bibliographies": bibs, "papers": papers, "cites": cites, "retractions": near}
    (OUT / "graph.json").write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    slim = [[r["doi"], r["date"], r["record_id"], (r["title"] or "")[:160], ";".join(r["reasons"] or [])[:300], r["notice_doi"]] for r in retractions]
    write_rw_index(slim, meta)
    conn.close()
    print(f"bibliographies {len(bibs)}, papers {len(papers)}, cites {len(cites)}, retractions near {len(near)} / all {len(retractions)}")


if __name__ == "__main__" and "--index-from" in sys.argv:
    src = json.loads(Path(sys.argv[sys.argv.index("--index-from") + 1]).read_text(encoding="utf-8"))
    write_rw_index(src["rows"], src["meta"])
    sys.exit(0)

if __name__ == "__main__":
    main()


def copy_queries():
    import shutil
    dst = OUT.parent / "queries"
    dst.mkdir(exist_ok=True)
    for f in (ROOT / "queries").glob("*.cypher"):
        shutil.copy(f, dst / f.name)


if __name__ == "__main__":
    copy_queries()
