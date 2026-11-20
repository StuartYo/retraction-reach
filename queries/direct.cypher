// Listed papers that are themselves retracted.
MATCH (b:Bibliography {id: $bib})-[l:LISTS]->(r:Retracted)-[:RETRACTED_BY]->(x:Retraction)
RETURN l.position AS position, r.doi AS listed, r.title AS title, x.date AS retracted_on,
       x.reasons AS reasons, x.notice_doi AS notice_doi, 100 AS severity
ORDER BY position
