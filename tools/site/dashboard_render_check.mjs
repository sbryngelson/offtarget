// Headless-Chrome half of tools/site/dashboard_render_check.py: load HARNESS at WIDTH, then
// click every control and the first rows of every table; print one JSON report.
// Usage: node tools/site/dashboard_render_check.mjs HARNESS.html|URL WIDTH CHROME
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

const [harness, width, chromeBin] = process.argv.slice(2);
const prof = mkdtempSync(join(tmpdir(), 'dashchk-'));
const chrome = spawn(chromeBin, ['--headless=new', '--no-sandbox', '--disable-gpu',
  '--remote-debugging-port=0', `--user-data-dir=${prof}`, '--allow-file-access-from-files',
  `--window-size=${width},2000`, 'about:blank'],
  { stdio: 'ignore', env: { ...process.env, HOME: prof, XDG_CONFIG_HOME: prof, XDG_CACHE_HOME: prof, XDG_RUNTIME_DIR: prof } });
const done = (code, out) => { console.log(JSON.stringify(out)); chrome.kill(); rmSync(prof, { recursive: true, force: true }); process.exit(code); };

let wsUrl;
for (let i = 0; i < 300 && !wsUrl; i++) {   // Chrome's own free port (DevToolsActivePort), 60 s
  try {
    const port = readFileSync(join(prof, 'DevToolsActivePort'), 'utf8').split('\n')[0].trim();
    const t = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
    wsUrl = t.find(x => x.type === 'page')?.webSocketDebuggerUrl;
  } catch {}
  if (!wsUrl) await sleep(200);
}
if (!wsUrl) done(2, { fatal: 'chrome did not start' });
const sock = new WebSocket(wsUrl);
await new Promise(r => { sock.onopen = r; });
let id = 0; const pend = new Map(); const logs = [];
sock.onmessage = m => {
  const d = JSON.parse(m.data);
  if (d.id && pend.has(d.id)) { pend.get(d.id)(d); pend.delete(d.id); }
  else if (d.method === 'Runtime.exceptionThrown') logs.push('exception: ' + (d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text).slice(0, 400));
  else if (d.method === 'Runtime.consoleAPICalled' && d.params.type === 'error') logs.push('console.error: ' + d.params.args.map(a => a.value ?? a.description).join(' ').slice(0, 400));
};
const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); sock.send(JSON.stringify({ id: i, method, params })); });
const ev = async expr => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400));
  return r.result.result.value;
};
await send('Runtime.enable'); await send('Page.enable');
// the error collector the clicks read (the harness defines its own; a standalone page does not)
await send('Page.addScriptToEvaluateOnNewDocument', { source: "window.__ERR = window.__ERR || []; addEventListener('error', e => __ERR.push('error: ' + e.message)); addEventListener('unhandledrejection', e => __ERR.push('rejection: ' + e.reason));" });
await send('Page.navigate', { url: /^https?:/.test(harness) ? harness : 'file://' + harness });
for (let i = 0; i < 120; i++) { if (await ev('document.readyState === "complete"').catch(() => false)) break; await sleep(250); }
// a standalone page sets window.__READY once its datasets are fetched
for (let i = 0; i < 240; i++) { if (await ev('window.__READY !== false').catch(() => false)) break; await sleep(250); }
await sleep(1000);

const load = await ev(`(() => {
  const root = document.getElementById('dash-root');
  const blank = e => /^\\s*(—)?\\s*$/.test(e.textContent);
  return {
    unfilled: [...root.querySelectorAll('[data-where][data-field]')].filter(blank).map(e => e.outerHTML.slice(0, 200)),
    marks: root.querySelectorAll('[data-where][data-field]').length,
    tables: [...root.querySelectorAll('table')].map(t => ({ id: t.id, th: t.querySelectorAll('thead tr:first-child th').length, rows: t.querySelectorAll('tbody tr').length })),
    scrollW: document.documentElement.scrollWidth, innerW: innerWidth };
})()`);
const clicks = await ev(`(async () => {
  const sl = ms => new Promise(r => setTimeout(r, ms)); const out = [];
  const ctl = [...document.querySelectorAll('#dash-root button, #dash-root select, #dash-root input, #dash-root summary, #dash-root a, #dash-root th')];
  for (const c of ctl) { const n0 = __ERR.length;
    try {
      if (c.tagName === 'SELECT') { for (const o of c.options) { c.value = o.value; c.dispatchEvent(new Event('change', { bubbles: true })); } }
      else if (c.tagName === 'INPUT' && /^(text|search)$/.test(c.type)) { for (const v of ['target', '']) { c.value = v; c.dispatchEvent(new Event('input', { bubbles: true })); } }
      else c.click();
    } catch (e) { __ERR.push(String(e)); }
    await sl(5);
    if (__ERR.length > n0) out.push(c.tagName + ' ' + (c.id || c.textContent.trim().slice(0, 30)) + ': ' + __ERR.slice(n0).join(' | ').slice(0, 300));
  }
  for (const t of document.querySelectorAll('#dash-root table')) for (const r of [...t.querySelectorAll('tbody tr')].slice(0, 3)) {
    const n0 = __ERR.length; r.click(); await sl(10);
    if (__ERR.length > n0) out.push('row of ' + t.id + ': ' + __ERR.slice(n0).join(' | ').slice(0, 300)); }
  dash._rerun();
  return { controls: ctl.length, failures: out };
})()`);
const after = await ev('({ scrollW: document.documentElement.scrollWidth, innerW: innerWidth, errors: __ERR })');
done(0, { width: Number(width), ...load, ...clicks, errors: after.errors, logs, scrollAfter: after.scrollW });
