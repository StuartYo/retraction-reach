// Every path of one or two CITES hops from a listed paper to a retracted paper,
// scored by a fixed rule (see README "How a finding is scored").
MATCH (b:Bibliography {id: $bib})-[l:LISTS]->(r:Paper)
MATCH p = (r)-[:CITES*1..2]->(c:Retracted)-[:RETRACTED_BY]->(x:Retraction)
WITH l.position AS position, r, c, x, nodes(p) AS ns, relationships(p) AS rs, length(p) - 1 AS hops
WITH position, r, c, x, ns, rs, hops,
     ns[hops - 1] AS citing, rs[hops - 1] AS last_link, rs[0] AS first_link
WITH position, r, c, x, ns, rs, hops, citing,
     (citing.date IS NOT NULL AND x.date IS NOT NULL AND citing.date > x.date) AS cited_after_retraction,
     (coalesce(last_link.influential, false) OR any(i IN coalesce(last_link.intents, []) WHERE i IN ['methodology', 'result'])) AS last_dependent,
     (coalesce(first_link.influential, false) OR any(i IN coalesce(first_link.intents, []) WHERE i IN ['methodology', 'result'])) AS first_dependent
RETURN position, r.doi AS listed, hops,
       [n IN ns[0..hops + 1] | n.doi] AS path,
       [n IN ns[0..hops + 1] | n.title] AS titles,
       [n IN ns[0..hops + 1] | n.date] AS dates,
       [k IN rs[0..hops] | coalesce(k.intents, [])] AS intents,
       [k IN rs[0..hops] | k.context] AS contexts,
       [k IN rs[0..hops] | k.intent_found] AS intent_found,
       c.doi AS retracted_doi, x.date AS retracted_on, x.reasons AS reasons, x.notice_doi AS notice_doi,
       cited_after_retraction, last_dependent, first_dependent,
       CASE hops
         WHEN 1 THEN 70 + CASE WHEN cited_after_retraction THEN 20 ELSE 0 END + CASE WHEN last_dependent THEN 10 ELSE 0 END
         ELSE 30 + CASE WHEN last_dependent THEN 15 ELSE 0 END + CASE WHEN cited_after_retraction THEN 10 ELSE 0 END + CASE WHEN first_dependent THEN 10 ELSE 0 END
       END AS severity
ORDER BY position, severity DESC
