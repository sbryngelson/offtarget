#!/usr/bin/env python3
"""Render the dashboard page in headless Chrome before publishing it.

    python3 -I tools/site/dashboard_render_check.py DATA_DIR [--page tools/site/dashboard_page.html]
                                               [--widths 1280 420]
    python3 -I tools/site/dashboard_render_check.py --standalone OUT_DIR [--widths 1280 420]

DATA_DIR holds one <dataset id>.json per dataset (the output of tools/site/dashboard_data.py,
or the published files). The page runs against a stand-in for the Dashboard type's `dash`
API (data, calc, onData) with those rows; the type's own runtime and theme are not loaded.
Fails (exit 1) when the page throws while loading or on any click of a control or table
row, when a headline mark (data-where + data-field) stays blank, or when the page scrolls
sideways. Needs node (>= 22, for WebSocket) and Chrome; see docs/tooling/dashboard-publish.md.
With --standalone, OUT_DIR is the output of tools/site/dashboard_standalone.py: it is served
over local HTTP and checked as published (its own runtime fetching data/<id>.json).
"""
import argparse
import functools
import http.server
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

STUB = r"""<script>
window.__ERR = [];
window.addEventListener('error', e => __ERR.push('error: ' + e.message));
window.addEventListener('unhandledrejection', e => __ERR.push('rejection: ' + e.reason));
(function () {
  const calcs = {}, subs = [];
  const cols = r => { const s = []; for (const x of r.slice(0, 50)) for (const k in x) if (!s.includes(k)) s.push(k); return s; };
  const ok = v => ({ status: 'ok', data: v, rows: v, columns: Array.isArray(v) ? cols(v) : [], meta: [] });
  const dash = window.dash = {
    data(id) {
      if (calcs[id]) {
        try { return ok(calcs[id].fn(...calcs[id].inputs.map(i => dash.data(i).data))); }
        catch (e) { __ERR.push('calc ' + id + ': ' + e); return { status: 'error', data: [], message: String(e), meta: [] }; }
      }
      if (!(id in __DS)) { __ERR.push('no dataset ' + id); return { status: 'missing', data: [], columns: [], meta: [] }; }
      return ok(__DS[id]);
    },
    calc(id, o) { calcs[id] = o; },
    onData(fn) { subs.push(fn); try { fn(); } catch (e) { __ERR.push('onData: ' + e.stack); } },
    colors: ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f'],
    params() { return {}; }, setParams() {}, resetParams() {}, setLink() {}, refresh() {}, loader() {},
    _rerun() { for (const f of subs) { try { f(); } catch (e) { __ERR.push('onData rerun: ' + e.stack); } } },
  };
})();
</script>"""

TOKENS = ("--color-fg:#111;--color-fg-muted:#666;--color-bg:#fff;--color-panel:#f6f6f6;"
          "--color-border-line:#ddd;--color-ok:green;--color-warn:orange;--color-bad:red")


def build(page: Path, data: Path, out: Path) -> Path:
    with open(out / "data.js", "w") as f:
        f.write("window.__DS = {};\n")
        for p in sorted(data.glob("*.json")):
            rows = json.loads(p.read_text())
            if isinstance(rows, dict):
                rows = rows.get("rows") or rows.get("data") or rows.get("results")
            f.write(f"__DS[{json.dumps(p.stem)}] = {json.dumps(rows)};\n")
    html = (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width">'
            f'<style>:root{{{TOKENS}}}</style><script src="data.js"></script>{STUB}'
            f'</head><body><div id="dash-root">{page.read_text()}</div></body></html>')
    (out / "harness.html").write_text(html)
    return out / "harness.html"


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def problems(r: dict) -> list:
    out = []
    if r.get("fatal"):
        return [r["fatal"]]
    out += [f"error: {e}" for e in r["errors"]]
    out += [f"click: {e}" for e in r["failures"]]
    out += r["logs"]
    out += [f"blank mark: {m}" for m in r["unfilled"]]
    if max(r["scrollW"], r["scrollAfter"]) > r["innerW"]:
        out.append(f"scrolls sideways: {max(r['scrollW'], r['scrollAfter'])} > {r['innerW']}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data", type=Path)
    ap.add_argument("--standalone", action="store_true",
                    help="DATA is a tools/site/dashboard_standalone.py output directory")
    ap.add_argument("--page", type=Path, default=ROOT / "tools" / "site" / "dashboard_page.html")
    ap.add_argument("--widths", type=int, nargs="+", default=[1280, 420])
    ap.add_argument("--chrome", default=shutil.which("google-chrome") or shutil.which("chromium"))
    a = ap.parse_args(argv)
    node = shutil.which("node")
    if not node or not a.chrome:
        print("needs node and google-chrome on PATH", file=sys.stderr)
        return 2
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        if a.standalone:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(
                Quiet, directory=str(a.data)))
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            harness = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
        else:
            harness = build(a.page, a.data, Path(tmp))
        for w in a.widths:
            p = subprocess.run([node, str(ROOT / "tools" / "site" / "dashboard_render_check.mjs"),
                                str(harness), str(w), a.chrome],
                               capture_output=True, text=True, timeout=900)
            try:
                r = json.loads(p.stdout.strip().splitlines()[-1])
            except (IndexError, json.JSONDecodeError):
                r = {"fatal": f"no report: {p.stderr[-500:]}"}
            found = problems(r)
            if not r.get("fatal"):
                print(f"width {w}: {r['marks']} headline marks, {len(r['tables'])} tables "
                      f"({sum(t['rows'] for t in r['tables'])} rows), {r['controls']} controls clicked, "
                      f"{len(found)} problems")
            for f in found:
                print(f"  {f}")
            bad += len(found)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
