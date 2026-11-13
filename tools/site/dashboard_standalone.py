#!/usr/bin/env python3
"""Build the dashboard as a standalone artifact that any account can publish.

    python3 -I tools/site/dashboard_standalone.py DATA_DIR OUT_DIR [--page tools/site/dashboard_page.html]

DATA_DIR is the output of tools/site/dashboard_data.py (one <dataset id>.json per dataset).
OUT_DIR gets index.html (the page with its own theme tokens and a small `dash` runtime that
fetches data/<id>.json next to the page) and data/<id>.json. It also gets files.json, the
`files` map of the Artifact publish call. No Dashboard type, ArtifactData or account-bound
asset is involved: one Artifact publish of index.html with that `files` map deploys it.
See docs/tooling/dashboard-publish.md.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LIMIT = 16 * 1024 * 1024        # per published text file
PUBLISH_LIMIT = 64 * 1024 * 1024  # per publish call

HEAD = """<meta charset="utf-8">
<title>Offload Support Catalog</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,500&display=swap">
<style>
/* One scrolling column of panels: headline tiles, bars, then the filterable tables. */
:root{
  --color-bg:#f6f8f9; --color-panel:#ecf0f2; --color-fg:#17212b; --color-fg-muted:#56636f;
  --color-border-line:#d3dbe1; --color-ok:#2e7a4d; --color-warn:#b06f12; --color-bad:#bf3d36;
  --font-anthropic-sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --font-anthropic-serif:"Newsreader",Georgia,"Times New Roman",serif;
  --cds-gap-sm:8px; --cds-gap-md:14px; --cds-gap-lg:28px; --cds-pad-lg:20px; --cds-radius:6px;
  --cds-font-size-caption:12.5px; --cds-font-size-body:14.5px; --cds-font-size-heading:18px;
  --cds-font-size-title:2.1rem; --cds-font-weight-medium:500;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --color-bg:#11161b; --color-panel:#192027; --color-fg:#e4e9ed; --color-fg-muted:#93a0ab;
  --color-border-line:#2b353f; --color-ok:#4caa70; --color-warn:#d49a3a; --color-bad:#e0645c;
  color-scheme:dark}}
:root[data-theme="dark"]{
  --color-bg:#11161b; --color-panel:#192027; --color-fg:#e4e9ed; --color-fg-muted:#93a0ab;
  --color-border-line:#2b353f; --color-ok:#4caa70; --color-warn:#d49a3a; --color-bad:#e0645c;
  color-scheme:dark}
body{background:var(--color-bg);color:var(--color-fg);font-family:var(--font-anthropic-sans);
  font-size:var(--cds-font-size-body);padding-block:24px 40px;
  padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
#dash-load{max-width:78rem;margin:0 auto 12px;font-size:var(--cds-font-size-caption);color:var(--color-fg-muted)}
#dash-load.err{color:var(--color-bad)}
:focus-visible{outline:2px solid var(--color-fg-muted);outline-offset:2px}
</style>
<script>
window.__READY = false;
window.__DSIDS = %(ids)s;
(function () {
  var store = {}, err = {}, calcs = {}, subs = [];
  function cols(r) { var s = []; r.slice(0, 50).forEach(function (x) { for (var k in x) if (s.indexOf(k) < 0) s.push(k); }); return s; }
  function ok(v) { return { status: 'ok', data: v, rows: v, columns: Array.isArray(v) ? cols(v) : [], meta: [] }; }
  function run(f) { try { f(); } catch (e) { console.error(e); } }
  var dash = window.dash = {
    data: function (id) {
      if (calcs[id]) {
        try { return ok(calcs[id].fn.apply(null, calcs[id].inputs.map(function (i) { return dash.data(i).data; }))); }
        catch (e) { console.error('calc ' + id, e); return { status: 'error', data: [], message: String(e), meta: [] }; }
      }
      if (id in store) return ok(store[id]);
      if (id in err) return { status: 'error', data: [], columns: [], message: err[id], meta: [] };
      return { status: 'loading', data: [], columns: [], meta: [] };
    },
    calc: function (id, o) { calcs[id] = o; },
    onData: function (f) { subs.push(f); if (window.__READY) run(f); },
    colors: ['#3b6ea8', '#d0812c', '#3f8f5a', '#c4483f', '#7d5fa8', '#8a6a4f', '#c26aa6', '#6f7a84'],
    params: function () { return {}; }, setParams: function () {}, resetParams: function () {},
    setLink: function () {}, refresh: function () {}, loader: function () {},
    _rerun: function () { subs.forEach(run); }
  };
  function rows(j) { return Array.isArray(j) ? j : (j.rows || j.data || j.results || []); }
  function get(id) {
    return fetch('data/' + id + '.json').then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (j) { store[id] = rows(j); }, function (e) { err[id] = String(e); console.error('dataset ' + id + ': ' + e); });
  }
  function start() {
    var el = document.getElementById('dash-load'), n = 0, ids = window.__DSIDS;
    Promise.all(ids.map(function (id) {
      return get(id).then(function () { n++; if (el) el.textContent = 'Loading results: ' + n + ' of ' + ids.length + ' datasets'; });
    })).then(function () {
      var bad = Object.keys(err);
      if (el) {
        if (bad.length) { el.className = 'err'; el.textContent = 'Could not load ' + bad.join(', ') + '. The other tables are shown.'; }
        else el.hidden = true;
      }
      window.__READY = true;
      subs.forEach(run);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
</script>
<div id="dash-load" role="status">Loading results</div>
"""


def build(data: Path, out: Path, page: Path) -> dict:
    files = sorted(data.glob("*.json"))
    if not files:
        raise SystemExit(f"no <id>.json datasets in {data}")
    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    fmap, total = {}, 0
    for p in files:
        size = p.stat().st_size
        if size > LIMIT:
            raise SystemExit(f"{p.name}: {size} bytes, over the 16 MB per-file limit")
        shutil.copyfile(p, out / "data" / p.name)
        fmap[f"data/{p.name}"] = str(out / "data" / p.name)
        total += size
    html = (HEAD % {"ids": json.dumps([p.stem for p in files])}
            + f'<div id="dash-root">\n{page.read_text()}\n</div>\n')
    (out / "index.html").write_text(html)
    total += len(html.encode())
    if total > PUBLISH_LIMIT:
        raise SystemExit(f"{total} bytes in all, over the 64 MB per-publish limit")
    (out / "files.json").write_text(json.dumps(fmap, indent=1) + "\n")
    return {"page": str(out / "index.html"), "files": fmap, "bytes": total}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--page", type=Path, default=ROOT / "tools" / "site" / "dashboard_page.html")
    a = ap.parse_args(argv)
    r = build(a.data, a.out, a.page)
    print(f"{r['page']}: {len(r['files'])} datasets, {r['bytes'] / 2**20:.1f} MB; "
          f"publish map in {a.out / 'files.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
