"""Checks the Cypher files on a tiny hand-made graph (synthetic DOIs under 10.0000/, not real papers).

    python -m pytest tests  (or: python tests/test_queries.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import relate  # noqa: E402

from relate_retraction import graph, report  # noqa: E402

SEED = """
CREATE (b:Bibliography {id: 't', label: 'synthetic test list', size: 4}),
  (r1:Paper {doi: '10.0000/r1', title: 'R1', date: '2022-05-01', in_crossref: true, refs_with_doi: 2}),
  (r2:Paper {doi: '10.0000/r2', title: 'R2', date: '2019-01-01', in_crossref: true, refs_with_doi: 1}),
  (r3:Paper:Retracted {doi: '10.0000/r3', title: 'R3', in_crossref: true, refs_with_doi: 0}),
  (r4:Paper {doi: '10.0000/r4', title: 'R4', in_crossref: false, refs_with_doi: 0}),
  (bmid:Paper {doi: '10.0000/b', title: 'B', date: '2018-01-01'}),
  (c:Paper:Retracted {doi: '10.0000/c', title: 'C'}),
  (x:Retraction {record_id: '1', date: '2020-06-04', reasons: ['Concerns about data']}),
  (x3:Retraction {record_id: '3', date: '2021-01-01', reasons: ['Error in analyses']}),
  (b)-[:LISTS {position: 1}]->(r1), (b)-[:LISTS {position: 2}]->(r2),
  (b)-[:LISTS {position: 3}]->(r3), (b)-[:LISTS {position: 4}]->(r4),
  (r1)-[:CITES {intents: ['result'], intent_found: true}]->(c),
  (r2)-[:CITES {intents: ['background'], intent_found: true}]->(bmid),
  (bmid)-[:CITES {intents: [], intent_found: true}]->(c),
  (c)-[:RETRACTED_BY]->(x), (r3)-[:RETRACTED_BY]->(x3)
"""


def build():
    conn = relate.connect(":memory:")
    conn.execute(SEED)
    return conn


def test_report():
    conn = build()
    rep = report.build_report(conn, "t")
    by = {i["position"]: i for i in rep["items"]}
    # R1 cites retracted C for its result, published after the notice: 70 + 20 + 10
    assert by[1]["status"] == "check" and by[1]["severity"] == 100
    assert by[1]["paths"][0]["cited_after_retraction"] is True
    # R2 reaches C through B (B published before the notice, background citations only): 30
    assert by[2]["status"] == "note" and by[2]["severity"] == 30 and by[2]["layer2"] == ["10.0000/c"]
    assert by[3]["status"] == "retracted"
    assert by[4]["status"] == "notfound"
    assert rep["summary"]["paths"] == 2
    conn.close()


if __name__ == "__main__":
    test_report()
    print("ok")
