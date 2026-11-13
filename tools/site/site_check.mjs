// Headless-Chrome half of tools/site/site_check.py: load each PAGE of BASE at WIDTH; on the issue
// list, click every filter and sort control of every compiler family, each from that family's
// default view, and record the list's rows before and after; check "Copy link" gives feedback;
// report errors, sideways scroll, an empty main region and the rendered text (for the leak
// check). One JSON report on stdout.
// Usage: node tools/site/site_check.mjs BASE WIDTH CHROME PAGES_JSON
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

const [base, width, chromeBin, pagesJson, mode] = process.argv.slice(2);
const clicks = mode !== 'noclicks';    // noclicks: the pages only, not the issue list's click loop
const pages = JSON.parse(pagesJson);
const prof = mkdtempSync(join(tmpdir(), 'sitechk-'));
// Chrome leads its own process group (detached), so that `done` can end every process it
// spawned: a renderer that survives SIGTERM would otherwise hold a compute-node job open.
const chrome = spawn(chromeBin, ['--headless=new', '--no-sandbox', '--disable-gpu',
  '--remote-debugging-port=0', `--user-data-dir=${prof}`, `--window-size=${width},2000`, 'about:blank'],
  { stdio: 'ignore', detached: true,
    env: { ...process.env, HOME: prof, XDG_CONFIG_HOME: prof, XDG_CACHE_HOME: prof, XDG_RUNTIME_DIR: prof } });
// Write the report and, once stdout has drained (a pipe takes 64 KB at a time and
// process.exit drops the rest), end Chrome: SIGTERM, then after a 2 s grace SIGKILL to its
// whole process group, then exit.
let finished = false;
const done = (code, out) => {
  if (finished) return;
  finished = true;
  process.stdout.write(JSON.stringify(out) + '\n', () => {
    chrome.kill();
    const finish = () => {
      try { process.kill(-chrome.pid, 'SIGKILL'); } catch {}
      rmSync(prof, { recursive: true, force: true });
      process.exit(code);
    };
    const grace = setTimeout(finish, 2000);
    chrome.once('exit', () => { clearTimeout(grace); finish(); });
  });
};
setTimeout(() => done(3, { fatal: 'timeout' }), 600000);

// Chrome picks a free debugging port (port 0) and writes it to DevToolsActivePort in its
// profile: parallel checks never contend for one; a slow start gets 60 s
let wsUrl;
for (let i = 0; i < 300 && !wsUrl; i++) {
  try {
    const port = readFileSync(join(prof, 'DevToolsActivePort'), 'utf8').split('\n')[0].trim();
    const t = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
    wsUrl = t.find((x) => x.type === 'page')?.webSocketDebuggerUrl;
  } catch {}
  if (!wsUrl) await sleep(200);
}
if (!wsUrl) done(2, { fatal: 'chrome did not start' });
const sock = new WebSocket(wsUrl);
await new Promise((r) => { sock.onopen = r; });
let id = 0; const pend = new Map(); let logs = []; const urls = new Map();
sock.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pend.has(d.id)) { pend.get(d.id)(d); pend.delete(d.id); }
  else if (d.method === 'Runtime.exceptionThrown') logs.push('exception: ' + (d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text).slice(0, 300));
  else if (d.method === 'Runtime.consoleAPICalled' && d.params.type === 'error') logs.push('console.error: ' + d.params.args.map((a) => a.value ?? a.description).join(' ').slice(0, 300));
  else if (d.method === 'Network.requestWillBeSent') urls.set(d.params.requestId, d.params.request.url);
  // a failed request of the site's own files is a problem; one to another host (the web fonts) is not
  else if (d.method === 'Network.loadingFailed' && (urls.get(d.params.requestId) || base).startsWith(base)) logs.push('load failed: ' + d.params.errorText);
};
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pend.set(i, r); sock.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 300));
  return r.result.result.value;
};
await send('Runtime.enable'); await send('Page.enable'); await send('Network.enable');
await send('Emulation.setDeviceMetricsOverride', { width: Number(width), height: 1600, deviceScaleFactor: 1, mobile: Number(width) < 600 });

// a load the local server dropped (ERR_CONNECTION_CLOSED, _RESET) is the network's, not the page's:
// the page is loaded once more, and any other failure stands
const DROPPED = /^load failed: net::ERR_CONNECTION_(CLOSED|RESET)$/;
async function open(path, again = true) {
  logs = [];
  await send('Page.navigate', { url: base + path });
  for (let i = 0; i < 80; i++) { if (await ev('document.readyState === "complete"').catch(() => false)) break; await sleep(250); }
  // a page with scripts gets time for late errors and fetched data; a static page has none to wait for
  await sleep((await ev('document.scripts.length').catch(() => 1)) ? 800 : 50);
  if (again && logs.length && logs.every((l) => DROPPED.test(l))) await open(path, false);
}
const state = () => ev(`(() => ({ scrollW: document.documentElement.scrollWidth, innerW: innerWidth,
  main: (document.querySelector('main')?.innerText || '').trim().length,
  text: document.body.innerText.slice(0, 200000) }))()`);

// The issue list, ready: its data loaded and the list drawn.
async function openList(path) {
  logs = [];
  await send('Page.navigate', { url: base + path });
  for (let i = 0; i < 80; i++) {
    if (await ev(`document.readyState === "complete" && !!document.getElementById("summary")
      && document.getElementById("summary").textContent !== "Loading\u2026"`).catch(() => false)) return;
    await sleep(125);
  }
}
const items = () => ev('[...document.querySelectorAll("#list .item")].map((a) => a.getAttribute("href"))');
const CONTROLS = '#filters button, #filters input, #sorts button';

const out = { pages: [], controls: 0, clicks: [] };
for (const path of pages) {
  await open(path);
  const s = await state();
  const rec = { path, errors: logs.slice(), sideways: s.scrollW > s.innerW + 1, main: s.main, text: s.text };
  if (path.startsWith('issues.html')) {     // the old list address forwards to index.html
    for (let i = 0; i < 40 && !(await ev('location.pathname').catch(() => '')).endsWith('index.html'); i++) await sleep(50);
    rec.landed = await ev('location.pathname + location.search').catch(() => '');
  }
  if (path === 'index.html' && clicks) {
    await openList('index.html');
    rec.specRows = await ev(`[...document.querySelectorAll("#list .item")].map((a) => [a.getAttribute("href"),
      (a.querySelector(".spec") || { textContent: "" }).textContent])`);
    // every control of every compiler family, each clicked once from that family's default view,
    // with the list's rows before and after (tools/site/site_check.py compares them with the data)
    const fams = await ev(`[...document.querySelectorAll('[data-key="fam"]')].map((b) => b.dataset.value)`);
    for (const fam of fams) {
      await openList('index.html?fam=' + fam);
      const n = await ev(`document.querySelectorAll(${JSON.stringify(CONTROLS)}).length`);
      for (let i = 0; i < n; i++) {
        await openList('index.html?fam=' + fam);
        const before = await items();
        const c = await ev(`(() => { const c = document.querySelectorAll(${JSON.stringify(CONTROLS)})[${i}];
          if (!c || c.dataset.key === 'copy' || c.dataset.key === 'csv') return null;
          const r = { key: c.dataset.key || '', value: c.dataset.value || '',
            label: (c.textContent || c.parentElement.textContent).trim().slice(0, 80) };
          c.click(); return r; })()`);
        if (c === null) continue;
        out.controls++;
        await sleep(60);
        const after = await state();
        out.clicks.push(Object.assign({ fam, before, after: await items() }, c));
        if (after.scrollW > after.innerW + 1) rec.sideways = true;
        rec.errors.push(...logs.filter((x) => !rec.errors.includes(x)));
      }
    }
    // "Copy link": visible feedback, or the URL shown selected where the clipboard refuses
    await openList('index.html');
    const copied = await ev(`(async () => { const b = document.getElementById('copy-link'); if (!b) return 'no button';
      b.click(); await new Promise((r) => setTimeout(r, 400));
      const o = document.getElementById('copy-out'); const a = document.activeElement;
      if (o && /copied/i.test(o.textContent)) return 'ok';
      if (a && a.value === location.href && a.selectionStart === 0 && a.selectionEnd === a.value.length) return 'ok';
      return 'no feedback'; })()`);
    if (copied !== 'ok') rec.errors.push('"Copy link": ' + copied);
  }
  out.pages.push(rec);
}
done(0, out);
