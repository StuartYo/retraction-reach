// Measures the web demo in headless Chrome (Playwright) and checks the pasted-DOI path against the CLI.
//   node scripts/serve.mjs      (in another shell; headless Chrome runs with --no-proxy-server)
//   node scripts/measure_web.mjs [case-id] [--old path/to/old/retracted.json]
// Prints JSON: page load, retraction index load (fast and throttled network), and the pasted-list result
// compared with eval/truth/<case>.json, which the Python CLI produced.
import { createRequire } from 'module';
import { readFileSync } from 'fs';
import { execSync } from 'child_process';
const require = createRequire(import.meta.url);
let pw;
try { pw = require('playwright'); } catch { pw = require(execSync('npm root -g').toString().trim() + '/playwright'); }

const BASE = process.env.RR_BASE || 'http://127.0.0.1:8765/';
const caseId = process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : 'B01';
const truth = JSON.parse(readFileSync(new URL(`../eval/truth/${caseId}.json`, import.meta.url), 'utf8'));
// "Throttled": 10 Mbit/s down, 40 ms round trip, roughly a slow home connection.
const SLOW = { offline: false, latency: 40, downloadThroughput: (10 * 1024 * 1024) / 8, uploadThroughput: (5 * 1024 * 1024) / 8 };

async function session(throttle, fn) {
  const browser = await pw.chromium.launch({ channel: 'chrome', headless: true, args: ['--no-proxy-server'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  // a fresh browser context starts with an empty cache
  if (throttle) { await cdp.send('Network.enable'); await cdp.send('Network.emulateNetworkConditions', SLOW); }
  console.error('session', throttle ? 'throttled' : 'fast');
  try { return await fn(page); } finally { browser.close().catch(() => {}); }
}

async function pageLoad(page) {
  const t0 = Date.now();
  await page.goto(BASE, { waitUntil: 'commit', timeout: 120000 });
  await page.waitForFunction(() => window.retractionReachLoad && window.retractionReachLoad.report_since_navigation, null, { timeout: 180000 });
  const steps = await page.evaluate(() => window.retractionReachLoad);
  return { seconds_navigation_to_report: steps.report_since_navigation / 1000, steps_ms_since_app_start: steps, wall_seconds_incl_browser: (Date.now() - t0) / 1000 };
}

// Old approach: one 19.7 MB JSON with every record (fetch + parse + Map), measured for comparison.
async function oldIndex(page, url) {
  return page.evaluate(async (u) => {
    const t0 = performance.now();
    const j = await (await fetch(u, { cache: 'no-store' })).json();
    const m = new Map(j.rows.map((r) => [r[0], r]));
    return { seconds: (performance.now() - t0) / 1000, rows: m.size };
  }, url);
}

async function newIndex(page) {
  return page.evaluate(async () => {
    const t0 = performance.now();
    const b = await (await fetch('data/rw/hashes.bin', { cache: 'no-store' })).arrayBuffer();
    return { seconds: (performance.now() - t0) / 1000, bytes: b.byteLength };
  });
}

async function pasted(page) {
  // also screenshot the result of the pasted list for the review folder

  const dois = truth.listed.map((x) => x.doi);
  await page.fill('#paste', dois.join('\n'));
  const t0 = Date.now();
  await page.click('#go');
  await page.waitForFunction(() => document.body.dataset.state === 'done' && document.querySelector('#example').value.startsWith('pasted-'), null, { timeout: 600000 });
  const total = (Date.now() - t0) / 1000;
  const timing = await page.evaluate(() => window.retractionReachTiming);
  const got = await page.evaluate(() => [...document.querySelectorAll('#results tr.row')].map((tr) => ({
    position: Number(tr.children[0].textContent), status: tr.querySelector('.chip').textContent })));
  const byPos = new Map(got.map((g) => [g.position, g.status]));
  const want = { direct: new Set(truth.direct), l1: new Set(truth.layer1.map((x) => x.position)), l2: new Set(truth.layer2_items) };
  const exposedWeb = new Set(got.filter((g) => g.status === 'Check' || g.status === 'Note').map((g) => g.position));
  const exposedCli = new Set([...want.l1, ...want.l2].filter((p) => !want.direct.has(p)));
  const same = (a, b) => a.size === b.size && [...a].every((x) => b.has(x));
  const retractedWeb = new Set(got.filter((g) => g.status === 'Retracted').map((g) => g.position));
  return {
    case: caseId, dois: dois.length, seconds_total: total, index_seconds: timing.indexMs / 1000, shard_seconds: timing.shardMs / 1000, shards_fetched: timing.shards,
    retracted_match_cli: same(retractedWeb, want.direct), exposed_match_cli: same(exposedWeb, exposedCli),
    web: { retracted: [...retractedWeb], exposed: exposedWeb.size }, cli: { retracted: [...want.direct], exposed: exposedCli.size },
    statuses: Object.fromEntries(['Retracted', 'Check', 'Note', 'Not visible', 'Clear'].map((s) => [s, got.filter((g) => g.status === s).length])),
  };
}

const oldArg = process.argv.indexOf('--old');
const out = {};
for (const throttle of [false, true]) {
  const key = throttle ? 'throttled_10mbit_40ms' : 'local_unthrottled';
  out[key] = await session(throttle, async (page) => {
    const r = { page: await pageLoad(page), new_index: await newIndex(page) };
    if (oldArg > 0) r.old_index = await oldIndex(page, process.argv[oldArg + 1]);
    return r;
  });
}
out.pasted = await session(false, async (page) => { await pageLoad(page); return pasted(page); });
console.log(JSON.stringify(out, null, 1));
process.exit(0);
