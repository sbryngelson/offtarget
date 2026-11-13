#!/usr/bin/env python3
"""Check a built public site (tools/site/site_build.py OUT) before anyone sees it.

    python3 -I tools/site/site_check.py DIR

Every in-site link resolves; no file and no rendered page holds a user, host or
private path (offload.engine.site.scrub.leaks); in headless Chrome at 1280 and 420 px,
the index, an issue page per kind, every compiler page, feature support and method load
with no error, no sideways scroll and a non-empty main region, and no script value shown
as text ("[object ...]"). On the index every filter and sort control of every compiler
family is clicked from that family's default view, and the rows the list shows after the
click are compared with what data/issues.json says (click_problems: a click that changes
nothing, empties the list or shows other rows is a problem; one the data says changes
nothing is listed, not counted); "Copy link" must say it copied or show the URL selected. Prints a summary; exit 1 on any problem. Needs node (>= 22)
and Chrome for the browser part; the link and leak checks run anywhere.
"""
import functools
import http.server
import json
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine.site.scrub import leaks  # noqa: E402

_HREF = re.compile(r'(?:href|src)="([^"#]+)')


def chrome() -> str | None:
    return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")


def link_problems(site: Path) -> list[str]:
    site = Path(site).resolve()
    out = []
    for p in site.rglob("*.html"):
        for url in _HREF.findall(p.read_text()):
            if url.startswith(("http:", "https:", "//", "mailto:")):
                continue
            target = (p.parent / url.split("?", 1)[0]).resolve()
            if not target.is_file() or site not in target.parents:
                out.append(f"{p.relative_to(site)}: broken link {url}")
    return out


def file_leaks(site: Path, allow: tuple[str, ...] = ()) -> list[str]:
    out = []
    for p in Path(site).rglob("*"):
        if p.is_file() and p.suffix in (".html", ".json", ".js", ".css"):
            hits = leaks(p.read_text(errors="replace"), allow)
            if hits:
                out.append(f"{p.relative_to(site)}: leak {sorted(set(hits))[:5]}")
    return out


UNKNOWN_CONSTRUCT = "canuse.html?c=clause.nosuch"


def _pages(site: Path) -> list[str]:
    issues = json.loads((site / "data/issues.json").read_text())["issues"]
    pick = {}
    for i in issues:
        pick.setdefault("mixed" if i["status"] == "mixed" else i["kind"], i["page"])
    atoms = json.loads((site / "data/canuse/index.json").read_text())
    pages = ["index.html", "index.html?fam=nvhpc&sort=construct", "index.html?fam=nosuch&vers=99",
             "index.html?fam=cce,afar&tg=mi250x", FORWARD,
             "method.html", "compilers/index.html", "canuse.html"]
    pages += [f"issues/{p}.html" for p in pick.values()]
    pages += sorted(str(p.relative_to(site)) for p in (site / "compilers").glob("*.html"))
    pages += [f"canuse.html?c={atoms[0]}"] if atoms else ["canuse.html"]
    pages += [UNKNOWN_CONSTRUCT]
    return list(dict.fromkeys(pages))


# the old address of the issue list: it must land on index.html with its query
FORWARD = "issues.html?fam=gcc&q=map"

# the issue list's default statuses (site/static/query.js DEFAULTS.st)
DEFAULT_ST = ("open", "changed", "mixed")
_NARROW = {"kinds": lambda i, f, v: v in i.get("kinds", [i["kind"]]),
           "stages": lambda i, f, v: i.get("stage") == v,
           "legal": lambda i, f, v: i.get("legality") == v,
           "langs": lambda i, f, v: i["lang"] == v,
           "models": lambda i, f, v: i["model"] == v,
           "tg": lambda i, f, v: v in i["fams"][f]["targets"],
           "vers": lambda i, f, v: v in i["fams"][f]["versions"],
           "reg": lambda i, f, v: bool(i["fams"][f].get("regression"))}


def _view(issues: list[dict], fam: str, st=DEFAULT_ST) -> list[dict]:
    return [i for i in issues if i["defect"] == i["id"] and fam in i.get("fams", {})
            and i["fams"][fam]["status"] in st]


def spec_problems(rows: list, issues: list[dict]) -> list[str]:
    """A list row shows the specification sections its issue cites (the data's `specs`), and
    nothing where the data has none."""
    want = {"issues/" + i["page"] + ".html": ("Specification: " + " \u00b7 ".join(i["specs"])) if i.get("specs") else ""
            for i in issues}
    return [f"{href}: shows {got!r}, the data says {want[href]!r}" for href, got in rows
            if href in want and got != want[href]]


def click_problems(clicks: list[dict], issues: list[dict]) -> tuple[list[str], list[str]]:
    """Each click of the issue list (from one family's view) against what the data
    says the list should then show, computed here independently of the page's script.
    Problems: a click that changes nothing, empties the list or shows other rows than the
    data says. Also returns the clicks that rightly change nothing (recorded, not problems:
    e.g. "Fortran" where every issue is Fortran)."""
    page = lambda i: f"issues/{i['page']}.html"  # noqa: E731
    probs, unchanged = [], []
    for c in clicks:
        f, k, v = c["fam"], c["key"], c["value"]
        before, after = set(c["before"]), set(c["after"])
        base = _view(issues, f)
        if k == "fam":       # the buttons toggle: another family adds its issues; the only one stays
            want = {page(i) for i in base} | ({page(i) for i in _view(issues, v)} if v != f else set())
        elif k in ("sort", "reset"):
            want = {page(i) for i in base}
        elif k == "st":
            st = [x for x in DEFAULT_ST if x != v] if v in DEFAULT_ST else [*DEFAULT_ST, v]
            want = {page(i) for i in _view(issues, f, st)}
        elif k in _NARROW:
            want = {page(i) for i in base if _NARROW[k](i, f, v)}
        else:
            continue
        name = f"{f}: {c['label']}"
        if before != {page(i) for i in base}:
            probs.append(f"{name}: the default view shows {len(before)} issues, the data {len(base)}")
        elif after == want:
            if after == before and k not in ("sort", "reset"):
                unchanged.append(name)
        elif after == before:
            probs.append(f"{name}: the click changes nothing; the data has {len(want)} issues there, "
                         f"not {len(before)}")
        elif not after:
            probs.append(f"{name}: the list is empty after the click; the data has {len(want)} issues there")
        else:
            probs.append(f"{name}: the list shows {len(after)} issues after the click, the data {len(want)}")
    return probs, unchanged


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def check(site: Path, allow: tuple[str, ...] = ()) -> dict:
    site = Path(site).resolve()
    problems = link_problems(site) + file_leaks(site, allow)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                          functools.partial(_Quiet, directory=str(site)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    pages = _pages(site)
    issues = json.loads((site / "data/issues.json").read_text())["issues"]
    controls, unchanged = 0, []
    try:
        for width in (1280, 420):
            r = subprocess.run(["node", str(ROOT / "tools/site/site_check.mjs"), base, str(width), chrome(),
                                json.dumps(pages)], capture_output=True, text=True, timeout=900)
            rep = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"fatal": r.stderr[-400:]}
            if "fatal" in rep:
                problems.append(f"{width}px: {rep['fatal']}")
                continue
            controls = max(controls, rep["controls"])
            probs, same = click_problems(rep.get("clicks", []), issues)
            for pg in rep.get("pages", []):
                if pg.get("specRows"):
                    problems += [f"{width}px index.html: {x}" for x in spec_problems(pg["specRows"], issues)]
                if pg["path"] == FORWARD and not str(pg.get("landed", "")).endswith("index.html?" + FORWARD.split("?")[1]):
                    problems.append(f"{width}px {FORWARD} lands on {pg.get('landed')!r}, not index.html with its query")
            problems += [f"{width}px index.html: {x}" for x in probs]
            unchanged = sorted(set(unchanged) | set(same))
            for pg in rep["pages"]:
                tag = f"{width}px {pg['path']}"
                problems += [f"{tag}: {x}" for x in pg["errors"]]
                if pg["sideways"]:
                    problems.append(f"{tag}: sideways scroll")
                if pg["main"] == 0:
                    problems.append(f"{tag}: empty main region")
                hits = leaks(pg["text"], allow)
                if hits:
                    problems.append(f"{tag}: leak {sorted(set(hits))[:5]}")
                if pg["path"] == UNKNOWN_CONSTRUCT and "No catalog program for" not in pg["text"]:
                    problems.append(f"{tag}: no message for a construct the catalog does not have")
                if "[object " in pg["text"]:
                    problems.append(f"{tag}: a script value shown as text ([object ...])")
    finally:
        srv.shutdown()
    return {"pages": len(pages), "controls": controls, "problems": problems, "unchanged": unchanged}


def main(argv=None) -> int:
    args = list(argv or sys.argv[1:])
    allow = ()
    if "--repo-url" in args:           # the repository URL the build linked to: public on purpose
        i = args.index("--repo-url")
        allow = (args[i + 1].rstrip("/"),)
        del args[i:i + 2]
    site = Path(args[0])
    if chrome() and shutil.which("node"):
        rep = check(site, allow)
    else:
        rep = {"pages": 0, "controls": 0, "problems": link_problems(site) + file_leaks(site, allow),
               "note": "no node or Chrome here: link and leak checks only"}
    for p in rep["problems"]:
        print(p)
    if rep.get("unchanged"):
        print(f"{len(rep['unchanged'])} controls change nothing, as the data says: "
              + "; ".join(rep["unchanged"]))
    print(f"{rep['pages']} pages, {rep['controls']} controls clicked, {len(rep['problems'])} problems"
          + (f" ({rep['note']})" if rep.get("note") else ""))
    return 1 if rep["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
