// Screenshots of the web demo in headless Chrome at several widths, plus a horizontal-overflow check.
//   node scripts/shots.mjs OUT_DIR [prefix]
import { createRequire } from 'module';
import { execSync } from 'child_process';
import { mkdirSync } from 'fs';
const require = createRequire(import.meta.url);
let pw;
try { pw = require('playwright'); } catch { pw = require(execSync('npm root -g').toString().trim() + '/playwright'); }

const BASE = process.env.RR_BASE || 'http://127.0.0.1:8765/';
const out = process.argv[2] || 'shots';
const prefix = process.argv[3] || 'web';
mkdirSync(out, { recursive: true });
const sizes = [[1440, 900], [390, 844], [1920, 945], [1366, 768]];
const browser = await pw.chromium.launch({ channel: 'chrome', headless: true, args: ['--no-proxy-server'] });
const report = [];
for (const [w, h] of sizes) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: w < 500 ? 2 : 1, isMobile: w < 500, hasTouch: w < 500 });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  const t0 = Date.now();
  await page.goto(BASE, { waitUntil: 'commit', timeout: 120000 });
  await page.waitForSelector('#report:not([hidden])', { timeout: 120000 });
  await page.waitForTimeout(300);
  const ms = Date.now() - t0;
  await page.screenshot({ path: `${out}/${prefix}-${w}-first-screen.png` });
  await page.screenshot({ path: `${out}/${prefix}-${w}-full.png`, fullPage: true });
  const m = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth,
    small_targets: [...document.querySelectorAll('button, select, summary, a, tr.row')].filter((e) => { const r = e.getBoundingClientRect(); const af = getComputedStyle(e, '::after'); const h = af.position === 'absolute' ? Math.max(r.height, parseFloat(af.height) || 0) : r.height; return r.width > 0 && h < (innerWidth < 500 ? 44 : 24); }).map((e) => `${e.tagName}.${e.className}:${Math.round(e.getBoundingClientRect().height)}`).slice(0, 10) }));
  if (w === 1440) {
    // error state: pressing the button with nothing pasted
    await page.fill('#paste', 'not a doi');
    await page.click('#go');
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${out}/${prefix}-${w}-error-state.png`, clip: { x: 0, y: 0, width: 380, height: 700 } });
  }
  report.push({ size: `${w}x${h}`, ms_to_report: ms, overflow_px: m.scrollWidth - m.clientWidth, small_targets: m.small_targets, errors });
  await ctx.close();
}

console.log(JSON.stringify(report, null, 1));
process.exit(0);
