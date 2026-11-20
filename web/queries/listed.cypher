// Everything on the list, with how much of its reference list Crossref could see.
MATCH (b:Bibliography {id: $bib})-[l:LISTS]->(r:Paper)
RETURN l.position AS position, r.doi AS doi, r.title AS title, r.date AS date, r.journal AS journal,
       coalesce(r.in_crossref, false) AS in_crossref, r.references_count AS references_count,
       r.refs_with_doi AS refs_with_doi, r:Retracted AS retracted
ORDER BY position
