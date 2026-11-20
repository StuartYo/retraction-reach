"""Start Relate's MCP server on the shipped store (read-only) and talk to it the way an agent host would.
Saves the exchange to docs/mcp-transcript.jsonl so you can see exactly what an agent gets back.

    python scripts/mcp_smoke.py [bibliography-id]
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "graph" / "retraction-graph.rl"
RELATE = shutil.which("relate") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "relate" / "relate.exe")
bib = sys.argv[1] if len(sys.argv) > 1 else "demo"

QUESTION = """MATCH (:Bibliography {id: $bib})-[l:LISTS]->(r:Paper)
MATCH p = (r)-[:CITES*1..2]->(c:Retracted)-[:RETRACTED_BY]->(x:Retraction)
RETURN l.position AS position, r.title AS reference, length(p) - 1 AS hops,
       [n IN nodes(p)[0..-1] | n.doi] AS path, x.date AS retracted_on
ORDER BY hops, position LIMIT 10"""

msgs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "mcp_smoke", "version": "0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_schema", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "read_cypher", "arguments": {"statement": QUESTION, "parameters": {"bib": bib}}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "read_cypher", "arguments": {"statement": "MATCH (p:Paper) DETACH DELETE p"}}},
]
proc = subprocess.run(
    [RELATE, "serve", "--mcp", "stdio", "--database", str(STORE), "--read-only"],
    input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True, text=True, encoding="utf-8", timeout=120,
)
lines = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
out = ROOT / "docs" / "mcp-transcript.jsonl"
out.parent.mkdir(exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    for m in msgs:
        f.write(json.dumps({"sent": m}, ensure_ascii=False) + "\n")
    for l in lines:
        f.write(json.dumps({"received": l}, ensure_ascii=False) + "\n")
by_id = {l.get("id"): l for l in lines}
tools = [t["name"] for t in by_id[2]["result"]["tools"]]
print("tools:", tools)
res = json.loads(by_id[4]["result"]["content"][0]["text"])
print("read_cypher rows:", len(res["rows"]))
for r in res["rows"][:5]:
    print(" ", r["position"], r["hops"], " -> ".join(r["path"]), r["retracted_on"])
print("delete attempt refused:", by_id[5].get("result", {}).get("isError"), str(by_id[5])[:160])
print("saved", out)
