MATCH (b:Bibliography {id: $bib}) RETURN b.id AS id, b.label AS label, b.source_doi AS source_doi, b.created AS created, b.size AS size
