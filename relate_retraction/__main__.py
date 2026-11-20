"""Command line: build the store, add a reference list, print its report.

    python -m relate_retraction init                       # load Retraction Watch into graph/retraction-graph.rl
    python -m relate_retraction check refs.txt --name my-paper
    python -m relate_retraction check --from-doi 10.xxxx/yyyy --name some-paper
    python -m relate_retraction report my-paper [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from . import graph, report, sources


def read_dois(path: str) -> list[str]:
    text = Path(path).read_text(encoding="utf-8") if path != "-" else sys.stdin.read()
    found = re.findall(r"10\.\d{4,9}/[^\s\"<>,;]+", text)
    return [d for d in (sources.norm_doi(x) for x in found) if d]


def cmd_init(a):
    t = time.time()
    rw = sources.load_retractions()
    conn = graph.connect(a.db)
    n = graph.load_retractions(conn, rw)
    print(f"loaded {n} retractions into {a.db} in {time.time() - t:.1f}s")
    print(graph.stats(conn))
    conn.close()


def add_bibliography(conn, bib_id, label, dois, source_doi=None, retracted=None, intents=True):
    retracted = retracted if retracted is not None else {
        r["doi"] for r in conn.execute("MATCH (p:Retracted) RETURN p.doi AS doi")
    }
    exp = graph.expand_bibliography(dois, retracted)
    graph.write_bibliography(conn, bib_id, label, exp, source_doi)
    if intents:
        graph.enrich_intents(conn, bib_id)
    return exp


def cmd_check(a):
    if a.from_doi:
        src = sources.norm_doi(a.from_doi)
        w = sources.crossref_works([src])[src]
        dois = w.get("refs", [])
        label = a.label or f"References of {w.get('title') or src}"
    else:
        src = None
        dois = read_dois(a.file)
        label = a.label or a.name
    if not dois:
        raise SystemExit("no DOIs found")
    conn = graph.connect(a.db)
    t = time.time()
    add_bibliography(conn, a.name, label, dois, src)
    rep = report.build_report(conn, a.name)
    rep["elapsed_s"] = round(time.time() - t, 1)
    conn.close()
    print(json.dumps(rep, ensure_ascii=False, indent=1) if a.json else report.to_markdown(rep))


def cmd_report(a):
    conn = graph.connect(a.db)
    rep = report.build_report(conn, a.name)
    conn.close()
    print(json.dumps(rep, ensure_ascii=False, indent=1) if a.json else report.to_markdown(rep))


def main(argv=None):
    p = argparse.ArgumentParser(prog="relate_retraction")
    p.add_argument("--db", default=str(graph.DEFAULT_DB))
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init")
    s.set_defaults(fn=cmd_init)
    s = sub.add_parser("check")
    s.add_argument("file", nargs="?", default="-")
    s.add_argument("--from-doi")
    s.add_argument("--name", required=True)
    s.add_argument("--label")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_check)
    s = sub.add_parser("report")
    s.add_argument("name")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_report)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
