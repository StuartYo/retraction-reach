// Retraction Reach: browser front end. The graph lives in Relate's WebAssembly build (worker.js);
// every table on the page comes from the same .cypher files the Python CLI runs.

const worker = new Worker(new URL('./worker.js', import.meta.url), { type: 'module' });
let seq = 0;
const pending = new Map();
worker.onmessage = (e) => { const { id, result } = e.data; const cb = pending.get(id); pending.delete(id); cb(result); };
function run(statement, params) {
  return new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, (r) => (r.error ? reject(new Error(typeof r.error === 'string' ? r.error : JSON.stringify(r.error))) : resolve(r)));
    worker.postMessage({ id, statement, params });
  });
}

const $ = (s) => document.querySelector(s);
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') n.className = v; else if (k.startsWith('on')) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return n;
}
const doiLink = (d) => el('a', { href: `https://doi.org/${d}`, target: '_blank', rel: 'noopener', class: 'doi' }, d);
const year = (d) => (d ? String(d).slice(0, 4) : '');
const fmtDate = (d) => (d ? String(d).slice(0, 10) : 'date unknown');
const stripTags = (s) => (s ? String(s).replace(/<[^>]+>/g, '') : s);

const Q = {};
async function loadQueries() {
  for (const name of ['findings', 'direct', 'listed', 'bibliography', 'path_edges']) {
    Q[name] = await (await fetch(`queries/${name}.cypher`)).text();
  }
}

function chunks(arr, n = 4000) { const out = []; for (let i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n)); return out; }

async function ensureSchema() {
  await run('CREATE CONSTRAINT paper_doi IF NOT EXISTS FOR (p:Paper) REQUIRE p.doi IS UNIQUE');
  await run('CREATE CONSTRAINT bib_id IF NOT EXISTS FOR (b:Bibliography) REQUIRE b.id IS UNIQUE');
  await run('CREATE CONSTRAINT retraction_id IF NOT EXISTS FOR (r:Retraction) REQUIRE r.record_id IS UNIQUE');
}

async function writePapers(papers) {
  for (const c of chunks(papers)) {
    await run(`UNWIND $rows AS r MERGE (p:Paper {doi: r.doi})
      SET p.title = coalesce(r.title, p.title), p.journal = coalesce(r.journal, p.journal), p.date = coalesce(r.date, p.date),
          p.in_crossref = coalesce(r.in_crossref, p.in_crossref), p.references_count = coalesce(r.references_count, p.references_count),
          p.refs_with_doi = coalesce(r.refs_with_doi, p.refs_with_doi)`, { rows: c });
  }
}
async function writeRetractions(rs) {
  for (const c of chunks(rs)) {
    await run(`UNWIND $rows AS r MERGE (p:Paper {doi: r.doi}) ON CREATE SET p.title = r.title, p.date = r.original_date
      SET p:Retracted MERGE (x:Retraction {record_id: r.record_id})
      SET x.date = r.date, x.reasons = r.reasons, x.notice_doi = r.notice_doi, x.source = 'Retraction Watch via Crossref (CC0)'
      MERGE (p)-[:RETRACTED_BY]->(x)`, { rows: c });
  }
}
async function writeBibliography(b) {
  await run('MERGE (b:Bibliography {id: $id}) SET b.label = $label, b.source_doi = $src, b.created = $created, b.size = $n',
    { id: b.id, label: b.label, src: b.source_doi || null, created: b.created || new Date().toISOString().slice(0, 10), n: b.listed.length });
  await run(`UNWIND $rows AS r MATCH (b:Bibliography {id: $id}), (p:Paper {doi: r.doi}) MERGE (b)-[l:LISTS]->(p) SET l.position = r.pos`,
    { id: b.id, rows: b.listed.map((d, i) => ({ doi: d, pos: i + 1 })) });
}
async function writeCites(cites) {
  for (const c of chunks(cites)) {
    await run(`UNWIND $rows AS e MATCH (a:Paper {doi: e.a}), (c:Paper {doi: e.b})
      MERGE (a)-[k:CITES]->(c) ON CREATE SET k.source = 'Crossref reference list'
      SET k.intents = e.intents, k.influential = e.influential, k.context = e.context, k.intent_found = e.intent_found, k.intent_source = e.intent_source`, { rows: c });
  }
}

// ---------------------------------------------------------------- report (mirrors relate_retraction/report.py)
const CHECK_AT = 60;
async function buildReport(bib) {
  const meta = (await run(Q.bibliography, { bib })).rows[0];
  const listed = (await run(Q.listed, { bib })).rows;
  const direct = new Map((await run(Q.direct, { bib })).rows.map((r) => [r.position, r]));
  const t0 = performance.now();
  const fres = await run(Q.findings, { bib });
  const findingsMs = performance.now() - t0;
  const byPos = new Map();
  for (const f of fres.rows) { if (!byPos.has(f.position)) byPos.set(f.position, []); byPos.get(f.position).push(f); }
  const items = listed.map((row) => {
    const fs = (byPos.get(row.position) || []).sort((a, b) => b.severity - a.severity || a.hops - b.hops);
    const d = direct.get(row.position);
    const top = d ? 100 : fs.length ? fs[0].severity : 0;
    let status = 'clear';
    if (d) status = 'retracted'; else if (fs.length && top >= CHECK_AT) status = 'check'; else if (fs.length) status = 'note';
    else if (!row.in_crossref) status = 'notfound';
    else if (!row.refs_with_doi) status = 'unknown';
    return { ...row, status, severity: top, retraction: d || null,
      layer1: [...new Set(fs.filter((f) => f.hops === 1).map((f) => f.retracted_doi))],
      layer2: [...new Set(fs.filter((f) => f.hops === 2).map((f) => f.retracted_doi))], paths: fs };
  });
  const reached = new Set(fres.rows.map((f) => f.retracted_doi));
  const count = (s) => items.filter((i) => i.status === s).length;
  return { meta, items, findingsMs, summary: { listed: items.length, retracted: count('retracted'), check: count('check'), note: count('note'),
    clear: count('clear'), unknown: count('unknown'), notfound: count('notfound'), paths: fres.rows.length, reached: reached.size,
    withL1: items.filter((i) => i.layer1.length).length, withL2: items.filter((i) => i.layer2.length).length } };
}

// ---------------------------------------------------------------- rendering
const STATUS = {
  retracted: ['Retracted', 'This listed paper is itself retracted.'],
  check: ['Check', 'Cites a retracted paper directly, or leans on one for methods or results.'],
  note: ['Note', 'Reaches a retracted paper two citations away, as background.'],
  unknown: ['Not visible', 'Crossref has this paper but no reference list for it, so its citations could not be followed.'],
  notfound: ['Not found', 'Crossref has no record of this DOI. Check it for typos.'],
  clear: ['Clear', 'No retracted paper within two citation layers.'],
};
const INTENT = { methodology: 'method', result: 'result', background: 'background' };
function linkWord(intents, found) {
  if (found == null) return 'cites (intent not looked up)';
  if (!found) return 'cites (intent unknown)';
  const w = (intents || []).map((i) => INTENT[i] || i);
  return w.length ? `cites for ${w.join(' / ')}` : 'cites (no intent given)';
}

function renderSummary(rep) {
  const s = rep.summary;
  $('#compare').replaceChildren(
    el('div', { class: 'cmp before' },
      el('div', { class: 'cmp-label' }, 'Direct retraction check only'),
      el('div', { class: 'cmp-num' }, String(s.retracted)),
      el('div', { class: 'cmp-sub' }, `of ${s.listed} references flagged. This is what a reference manager shows.`)),
    el('div', { class: 'cmp after' },
      el('div', { class: 'cmp-label' }, 'Two citation layers (Relate graph)'),
      el('div', { class: 'cmp-num' }, String(s.retracted + s.check), el('span', { class: 'cmp-plus' }, ` + ${s.note} notes`)),
      el('div', { class: 'cmp-sub' }, `${s.retracted} retracted, ${s.check} to check before you rely on them. ${s.paths} citation paths reach ${s.reached} retracted papers.`)),
  );
  $('#counts').replaceChildren(...['retracted', 'check', 'note', 'unknown', 'notfound', 'clear'].filter((k) => k !== 'notfound' || s.notfound).map((k) =>
    el('span', { class: `count s-${k}`, title: STATUS[k][1] }, el('b', {}, String(s[k])), ' ', STATUS[k][0])));
}

function pathView(p) {
  const steps = [];
  for (let k = 0; k <= p.hops; k++) {
    const isLast = k === p.hops;
    const isFirst = k === 0;
    steps.push(el('div', { class: `node ${isLast ? 'node-ret' : ''}` },
      el('div', { class: 'node-role' }, isFirst ? `Your reference #${p.position}` : isLast ? `Retracted ${fmtDate(p.retracted_on)}` : 'Cited by your reference'),
      el('div', { class: 'node-title' }, stripTags(p.titles[k]) || '(title not in Crossref)'),
      el('div', { class: 'node-meta' }, doiLink(p.path[k]), p.dates[k] ? ` · ${year(p.dates[k])}` : '')));
    if (!isLast) {
      const after = k === p.hops - 1 && p.cited_after_retraction;
      steps.push(el('div', { class: `edge ${after ? 'edge-after' : ''}` },
        el('span', {}, linkWord(p.intents[k], p.intent_found[k])),
        after ? el('span', { class: 'after' }, 'after the retraction notice') : null,
        p.contexts[k] ? el('q', { class: 'ctx' }, p.contexts[k]) : null));
    }
  }
  const reasons = (p.reasons || []).slice(0, 3).join('; ');
  return el('div', { class: 'path' },
    el('div', { class: 'path-head' }, el('span', { class: 'score' }, `score ${p.severity}`), `${p.hops === 1 ? 'Direct citation' : 'Two citations away'}`,
      reasons ? el('span', { class: 'reasons' }, ` · Retraction reasons: ${reasons}`) : null,
      p.notice_doi ? el('span', {}, ' · notice ', doiLink(p.notice_doi)) : null),
    el('div', { class: 'chain' }, steps));
}

function renderTable(rep) {
  const order = { retracted: 0, check: 1, note: 2, unknown: 3, notfound: 4, clear: 5 };
  const items = [...rep.items].sort((a, b) => order[a.status] - order[b.status] || b.severity - a.severity || a.position - b.position);
  const body = el('tbody');
  for (const it of items) {
    const top = it.paths[0];
    let why = '';
    if (it.status === 'retracted') why = `Retracted ${fmtDate(it.retraction.retracted_on)}. ${(it.retraction.reasons || []).slice(0, 2).join('; ')}`;
    else if (top) why = `${top.hops === 1 ? 'Cites' : 'Cites a paper that cites'} a paper retracted ${fmtDate(top.retracted_on)}${top.cited_after_retraction ? ', after it was retracted' : ''}`;
    else if (it.status === 'unknown') why = 'No reference list in Crossref';
    else if (it.status === 'notfound') why = 'This DOI is not in Crossref. Check it for typos.';
    const row = el('tr', { class: `row s-${it.status}`, tabindex: it.paths.length ? '0' : null },
      el('td', { class: 'num' }, String(it.position)),
      el('td', {}, el('span', { class: `chip s-${it.status}` }, STATUS[it.status][0])),
      el('td', { class: 'ref' }, el('div', { class: 'ref-title' }, stripTags(it.title) || it.doi), el('div', { class: 'ref-meta' }, doiLink(it.doi), it.date ? ` · ${year(it.date)}` : '')),
      el('td', { class: 'why' }, why),
      el('td', { class: 'num' }, it.paths.length ? String(it.paths.length) : '–'));
    body.append(row);
    if (it.paths.length) {
      const detail = el('tr', { class: 'detail', hidden: true }, el('td', { colspan: '5' },
        it.paths.slice(0, 6).map(pathView), it.paths.length > 6 ? el('div', { class: 'more' }, `${it.paths.length - 6} more paths. Query them in the console below.`) : null));
      body.append(detail);
      const toggle = () => { detail.hidden = !detail.hidden; row.classList.toggle('open', !detail.hidden); };
      row.addEventListener('click', toggle);
      row.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
    }
  }
  $('#results').replaceChildren(el('table', { class: 'grid' },
    el('thead', {}, el('tr', {}, el('th', { class: 'num' }, '#'), el('th', {}, 'Status'), el('th', {}, 'Reference'), el('th', {}, 'Strongest finding'), el('th', { class: 'num' }, 'Paths'))), body));
  const first = body.querySelector('tr.row.s-retracted[tabindex], tr.row.s-check[tabindex], tr.row.s-note[tabindex]');
  if (first) first.click();
}

async function show(bib) {
  setStatus('Running the Cypher queries…');
  const rep = await buildReport(bib);
  $('#bib-title').textContent = rep.meta.label;
  $('#bib-src').replaceChildren(rep.meta.source_doi ? el('span', {}, 'Reference list of ', doiLink(rep.meta.source_doi)) : 'Your pasted list, checked live against Crossref',
    el('span', { class: 'timing' }, ` · findings query ${rep.findingsMs.toFixed(0)} ms, run by Relate in this page`));
  lastReport = rep;
  renderSummary(rep);
  renderTable(rep);
  $('#report').hidden = false;
  $('#console-q').value = `// Paths from this list to retracted papers, as the report computes them\nMATCH (:Bibliography {id: '${bib}'})-[:LISTS]->(r:Paper)\nMATCH p = (r)-[:CITES*1..2]->(c:Retracted)\nRETURN r.doi AS listed, [n IN nodes(p) | n.doi] AS path, length(p) AS hops\nLIMIT 25`;
  setStatus('');
  document.body.dataset.state = 'done';
}
let lastReport = null;
function downloadCsv() {
  if (!lastReport) return;
  const q = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const lines = [['position', 'status', 'doi', 'title', 'year', 'score', 'paths', 'strongest_path', 'retracted_on', 'cited_after_retraction'].join(',')];
  for (const it of [...lastReport.items].sort((a, b) => a.position - b.position)) {
    const top = it.paths[0];
    lines.push([it.position, STATUS[it.status][0], q(it.doi), q(stripTags(it.title)), year(it.date), it.severity, it.paths.length,
      q(top ? top.path.join(' -> ') : ''), top ? fmtDate(top.retracted_on) : it.retraction ? fmtDate(it.retraction.retracted_on) : '',
      top ? (top.cited_after_retraction ? 'yes' : 'no') : ''].join(','));
  }
  const a = el('a', { href: URL.createObjectURL(new Blob([lines.join('\n') + '\n'], { type: 'text/csv' })), download: `retraction-reach-${lastReport.meta.id || 'report'}.csv` });
  document.body.append(a); a.click(); a.remove();
}

function setStatus(t) { $('#status').textContent = t; $('#status').hidden = !t; if (t) document.body.dataset.state = 'busy'; }
function setPasteMsg(t, isError) { const m = $('#paste-msg'); m.textContent = t; m.classList.toggle('err', !!isError); }

// ---------------------------------------------------------------- bundled examples
let snapshot = null;
const loadTiming = {};
window.retractionReachLoad = loadTiming; // read by scripts/measure_web.mjs
async function loadSnapshot() {
  const t0 = performance.now();
  const mark = (k) => { loadTiming[k] = Math.round(performance.now() - t0); };
  setStatus('Loading the Relate engine (WebAssembly)…');
  const snapP = fetch('data/graph.json').then((r) => { if (!r.ok) throw new Error('the bundled graph did not download'); return r.json(); });
  await loadQueries();
  await run('RETURN 1 AS ok');
  mark('engine');
  setStatus('Loading the bundled citation graph…');
  snapshot = await snapP;
  mark('graph_json');
  await ensureSchema();
  // Fresh store and a de-duplicated export, so plain CREATE is enough here (pasted lists use MERGE).
  for (const c of chunks(snapshot.papers)) {
    await run(`UNWIND $rows AS r CREATE (p:Paper {doi: r.doi}) SET p.title = r.title, p.journal = r.journal, p.date = r.date,
      p.in_crossref = r.in_crossref, p.references_count = r.references_count, p.refs_with_doi = r.refs_with_doi`, { rows: c });
  }
  mark('papers');
  await writeRetractions(snapshot.retractions);
  mark('retractions');
  for (const b of snapshot.bibliographies) await writeBibliography(b);
  mark('bibliographies');
  for (const c of chunks(snapshot.cites)) {
    await run(`UNWIND $rows AS e MATCH (a:Paper {doi: e.a}), (c:Paper {doi: e.b})
      CREATE (a)-[:CITES {source: 'Crossref reference list', intents: e.intents, influential: e.influential, context: e.context,
        intent_found: e.intent_found, intent_source: e.intent_source}]->(c)`, { rows: c });
  }
  mark('cites');
  const n = (await run('MATCH (p:Paper) RETURN count(p) AS n')).rows[0].n;
  const r = (await run('MATCH ()-[k:CITES]->() RETURN count(k) AS n')).rows[0].n;
  $('#engine').textContent = `Relate 1.1.0 (WebAssembly) · ${n.toLocaleString()} papers · ${r.toLocaleString()} citations · loaded in ${((performance.now() - t0) / 1000).toFixed(1)} s · Retraction Watch data as of ${snapshot.meta.rw_loaded}`;
  const sel = $('#example');
  sel.replaceChildren(...snapshot.bibliographies.map((b) => el('option', { value: b.id }, `${b.id === 'demo' ? 'Demo: ' : ''}${stripTags(b.label).replace(/^References of /, '').slice(0, 90)}`)));
  const start = snapshot.bibliographies.find((b) => b.id === 'demo') ? 'demo' : snapshot.bibliographies[0].id;
  sel.value = start;
  await show(start);
  loadTiming.report_since_navigation = Math.round(performance.now());
}

// ---------------------------------------------------------------- live check of pasted DOIs (Crossref from the browser)
// The Retraction Watch list is split in two (scripts/export_web.py): a sorted list of 32-bit hashes of every
// retracted DOI (about 250 KB, loaded once), and the records themselves in 1,024 shards keyed by the top
// 10 bits of the hash. A pasted list loads the hash list, then only the shards its DOIs hit.
const enc = new TextEncoder();
function fnv1a(s) { let h = 0x811c9dc5; for (const b of enc.encode(s)) { h ^= b; h = Math.imul(h, 0x01000193) >>> 0; } return h >>> 0; }
let rwHashes = null;
const rwTiming = { indexMs: null, shardMs: null, shards: 0 };
window.retractionReachTiming = rwTiming; // read by scripts/measure_web.mjs
async function loadRetractedIndex() {
  if (rwHashes) return rwHashes;
  setStatus('Loading the Retraction Watch index (62,431 retracted DOIs, 250 KB)…');
  const t0 = performance.now();
  const r = await fetch('data/rw/hashes.bin');
  if (!r.ok) throw new Error('The retraction index did not load. Reload the page and try again.');
  rwHashes = new Uint32Array(await r.arrayBuffer());
  rwTiming.indexMs = performance.now() - t0;
  return rwHashes;
}
function hashListed(h) {
  let lo = 0, hi = rwHashes.length - 1;
  while (lo <= hi) { const m = (lo + hi) >>> 1; const v = rwHashes[m]; if (v === h) return true; if (v < h) lo = m + 1; else hi = m - 1; }
  return false;
}
// Returns Map doi -> retraction record, for the DOIs that are retracted.
async function lookupRetracted(dois) {
  await loadRetractedIndex();
  const byShard = new Map();
  for (const d of dois) { const h = fnv1a(d); if (hashListed(h)) { const k = h >>> 22; if (!byShard.has(k)) byShard.set(k, new Set()); byShard.get(k).add(d); } }
  const t0 = performance.now();
  const out = new Map();
  await Promise.all([...byShard].map(async ([k, want]) => {
    const r = await fetch(`data/rw/shards/${k.toString(16).padStart(3, '0')}.json`);
    if (!r.ok) throw new Error('Part of the retraction index did not load. Reload the page and try again.');
    for (const row of (await r.json()).rows) if (want.has(row[0])) out.set(row[0], { doi: row[0], date: row[1], record_id: row[2], title: row[3], reasons: row[4] ? row[4].split(';') : [], notice_doi: row[5] });
  }));
  rwTiming.shardMs = performance.now() - t0; rwTiming.shards = byShard.size;
  return out;
}
const normDoi = (s) => { if (!s) return null; let d = s.trim().toLowerCase().replace(/^(https?:\/\/(dx\.)?doi\.org\/|doi:)/, '').replace(/[.)\]]+$/, ''); return d.startsWith('10.') && d.includes('/') ? d : null; };
function dateOf(m) { for (const k of ['published', 'issued']) { const p = (m[k] && m[k]['date-parts'] && m[k]['date-parts'][0]) || []; if (p[0]) return `${String(p[0]).padStart(4, '0')}-${String(p[1] || 1).padStart(2, '0')}-${String(p[2] || 1).padStart(2, '0')}`; } return null; }
async function crossref(dois, label) {
  const out = new Map();
  const todo = dois.filter((d) => !d.includes(','));
  const tStart = performance.now();
  for (let i = 0; i < todo.length; i += 60) {
    const chunk = todo.slice(i, i + 60);
    const doneN = i, el0 = (performance.now() - tStart) / 1000;
    const left = doneN ? (el0 / doneN) * (todo.length - doneN) : todo.length / 20;
    setStatus(`${label}: ${Math.min(i + 60, todo.length)} / ${todo.length} from Crossref · about ${fmtLeft(left)} left`);
    const url = `https://api.crossref.org/works?rows=${chunk.length}&select=DOI,title,reference,published,issued,container-title,references-count&filter=${encodeURIComponent(chunk.map((d) => 'doi:' + d).join(','))}`;
    let j = null;
    for (let a = 0; a < 4 && !j; a++) { try { const r = await fetch(url); if (r.ok) j = await r.json(); else await new Promise((s) => setTimeout(s, 1500 * (a + 1))); } catch { await new Promise((s) => setTimeout(s, 1500 * (a + 1))); } }
    if (!j) throw new Error('Crossref did not answer. Check the connection and try again.');
    for (const m of j.message.items) {
      const d = normDoi(m.DOI);
      out.set(d, { doi: d, title: (m.title || [''])[0] || null, journal: (m['container-title'] || [''])[0] || null, date: dateOf(m),
        references_count: m['references-count'] ?? null, refs: [...new Set((m.reference || []).map((r) => normDoi(r.DOI)).filter(Boolean))] });
    }
    await new Promise((s) => setTimeout(s, 250));
  }
  return out;
}
const fmtLeft = (sec) => (sec < 50 ? `${Math.max(5, Math.round(sec / 5) * 5)} seconds` : `${Math.max(1, Math.round(sec / 60))} minute${Math.round(sec / 60) > 1 ? 's' : ''}`);
let pastedN = 0;
async function checkPasted() {
  const text = $('#paste').value;
  const tokens = text.split(/[\s,;]+/).map((t) => t.trim()).filter(Boolean);
  const skipped = tokens.filter((t) => !normDoi((t.match(/10\.\d{4,9}\/\S+/) || [t])[0]));
  const dois = [...new Set(tokens.map((t) => normDoi((t.match(/10\.\d{4,9}\/\S+/) || [t])[0])).filter(Boolean))];
  const skippedNote = skipped.length ? ` Skipped ${skipped.length} ${skipped.length === 1 ? 'entry that is' : 'entries that are'} not a DOI: ${skipped.slice(0, 5).map((t) => `"${t.slice(0, 40)}"`).join(', ')}${skipped.length > 5 ? ', …' : ''}.` : '';
  if (!dois.length) { setPasteMsg('No DOIs found. Paste one DOI per line, for example 10.1056/NEJMoa2007621.' + skippedNote, true); $('#paste').focus(); return; }
  if (dois.length > 150) { setPasteMsg(`That is ${dois.length} DOIs. The browser version takes up to 150; the command-line version has no limit.`, true); return; }
  setPasteMsg(`Checking ${dois.length} DOIs; this can take up to about 3 minutes. Progress is shown above the results.${skippedNote}`, !!skipped.length);
  $('#go').disabled = true; $('#go').textContent = 'Checking…';
  try {
    await loadRetractedIndex();
    const w0 = await crossref(dois, 'Step 1 of 3 · your references');
    const bset = new Set(); for (const w of w0.values()) w.refs.forEach((d) => bset.add(d));
    const w1 = await crossref([...bset], 'Step 2 of 3 · the reference lists behind them');
    setStatus('Step 3 of 3 · matching against Retraction Watch…');
    const all = new Set([...dois, ...bset]); for (const w of w1.values()) w.refs.forEach((d) => all.add(d));
    const rw = await lookupRetracted(all);
    setStatus('Writing the graph into Relate…');
    const papers = new Map();
    const add = (d, w) => papers.set(d, { doi: d, title: w ? w.title : null, journal: w ? w.journal : null, date: w ? w.date : null,
      in_crossref: !!w, references_count: w ? w.references_count : null, refs_with_doi: w ? w.refs.length : 0 });
    dois.forEach((d) => add(d, w0.get(d)));
    bset.forEach((d) => { if (!papers.has(d)) add(d, w1.get(d)); });
    const cites = [];
    for (const d of dois) for (const b of (w0.get(d) || { refs: [] }).refs) cites.push({ a: d, b, intents: null, influential: null, context: null, intent_found: null, intent_source: null });
    const hit = new Set();
    for (const b of bset) for (const c of (w1.get(b) || { refs: [] }).refs) if (rw.has(c)) { cites.push({ a: b, b: c, intents: null, influential: null, context: null, intent_found: null, intent_source: null }); hit.add(c); }
    for (const d of [...dois, ...bset]) if (rw.has(d)) hit.add(d);
    await writePapers([...papers.values()]);
    await writeRetractions([...hit].map((d) => rw.get(d)));
    const id = `pasted-${++pastedN}`;
    await writeBibliography({ id, label: `Your pasted list (${dois.length} DOIs)`, listed: dois });
    await writeCites(cites);
    $('#example').append(el('option', { value: id }, `Your pasted list ${pastedN} (${dois.length} DOIs)`));
    $('#example').value = id;
    await show(id);
    setPasteMsg(`Done: ${dois.length} DOIs checked. The result is on the right${window.innerWidth < 900 ? ' (below)' : ''}.${skippedNote}`, !!skipped.length);
    if (window.innerWidth < 900) $('#report').scrollIntoView({ behavior: 'smooth' });
  } catch (e) {
    setStatus('');
    setPasteMsg(`Stopped: ${e.message}`, true);
  } finally { $('#go').disabled = false; $('#go').textContent = 'Check these references'; }
}

// ---------------------------------------------------------------- console
async function runConsole() {
  const out = $('#console-out');
  try {
    const t0 = performance.now();
    const r = await run($('#console-q').value);
    const cols = r.columns || [];
    const rows = (r.rows || []).slice(0, 50);
    out.replaceChildren(el('div', { class: 'console-meta' }, `${(r.rows || []).length} rows · ${(performance.now() - t0).toFixed(0)} ms`),
      el('table', { class: 'grid small' }, el('thead', {}, el('tr', {}, cols.map((c) => el('th', {}, c)))),
        el('tbody', {}, rows.map((row) => el('tr', {}, cols.map((c) => el('td', {}, typeof row[c] === 'object' ? JSON.stringify(row[c]) : String(row[c]))))))));
  } catch (e) { out.replaceChildren(el('div', { class: 'console-err' }, e.message)); }
}

$('#example').addEventListener('change', (e) => show(e.target.value));
$('#go').addEventListener('click', checkPasted);
$('#run-q').addEventListener('click', runConsole);
$('#csv').addEventListener('click', downloadCsv);
loadSnapshot().catch((e) => setStatus(`Could not start: ${e.message}`));
