// The CITES edges that lie on some path from the list to a retracted paper (these get intent lookups).
MATCH (b:Bibliography {id: $bib})-[:LISTS]->(r:Paper)
MATCH p = (r)-[:CITES*1..2]->(c:Retracted)
UNWIND relationships(p) AS k
WITH DISTINCT startNode(k) AS a, endNode(k) AS z, k
RETURN a.doi AS citing, z.doi AS cited, k.intent_source AS checked
