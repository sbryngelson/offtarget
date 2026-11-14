"""offload issues: search the known compiler problems and show one with its reproducer."""
import argparse
import difflib
import json
import re
import sys

from offload.engine.root import ROOT
from offload import data

STATE_WORDS = {"fails-like": "fails", "correct": "works", "unknown": "untested"}
KIND_WORDS = {"incorrect": "behaves incorrectly", "unsupported": "not supported"}


def _all() -> list[dict]:
    return data.load("issues.json")["issues"]


def _label(tc: str) -> str:
    from offload.engine import toolchains as T
    from offload.engine.site.columns import version_label
    reg = T.registry()
    t = reg.toolchains.get(tc)
    if t is None:
        return tc
    return version_label(reg, t.family_id, t.site_version) if getattr(t, "site_version", None) else (t.label or tc)


def _valid_toolchains() -> set[str]:
    return {t for i in _all() for t in i["versions_failing"]}


def search(query: str = "", compiler: str | None = None, kind: str | None = None,
           status: str | None = None, stage: str | None = None, legality: str | None = None) -> list[dict]:
    """Issues whose id, title, constructs or message text contain every word of `query`."""
    if compiler and not any(t == compiler or t.startswith(compiler) for t in _valid_toolchains()):
        raise ValueError(f"no issue involves a compiler '{compiler}' (known: {', '.join(sorted(_valid_toolchains()))})")
    words = query.lower().split()
    out = []
    for i in _all():
        text = " ".join([i["id"], i["title"], i["search"], " ".join(i["constructs"])]).lower()
        if not all(w in text for w in words):
            continue
        if compiler and not any(t == compiler or t.startswith(compiler) for t in i["versions_failing"]):
            continue
        if (kind and i["kind"] != kind) or (status and i["status"] != status) or (stage and i["stage"] != stage) \
                or (legality and i.get("legality") != legality):
            continue
        out.append(i)
    return sorted(out, key=lambda i: i["id"])


def _normalise(name: str) -> str:
    name = name.split("data/findings/", 1)[-1]
    return re.sub(r"\.(f90|F90|f|c|h|cpp)$", "", name).replace("/", "--")


def _resolve(name: str) -> dict | None:
    pages = {i["page"]: i for i in _all()}
    key = _normalise(name)
    if key in pages:
        return pages[key]
    hits = [p for p in pages if key.lower() in p.lower()]
    return pages[hits[0]] if len(hits) == 1 else None


def _source(rec: dict) -> tuple[str, str]:
    rel = rec["id"]
    for f in sorted((ROOT / "data" / "findings").glob(rel + ".*")):
        if f.suffix != ".yaml":
            return f"data/findings/{f.relative_to(ROOT / 'data' / 'findings')}", f.read_text(errors="replace")
    return "", ""


def _compilers_text(rec: dict) -> str:
    cols = data.load("canuse/columns.json")
    short = {t: n for ts in cols["targets"].values() for t, n in ts}
    lines = []
    for fam in rec["fams"].values():
        for tc in fam["versions"]:
            state = fam["states"].get(tc, "unknown")
            word = KIND_WORDS[rec["kind"]] if state == "fails-like" else STATE_WORDS.get(state, state)
            lines.append(f"  {_label(tc):<18}{word:<22}{', '.join(short.get(t, t) for t in fam['targets'])}")
    return "\n".join(lines)


def show(name: str) -> str:
    rec = _resolve(name)
    if rec is None:
        raise KeyError(name)
    path, source = _source(rec)
    same = [i["page"] for i in _all() if i["defect"] == rec["defect"] and i["id"] != rec["id"]]
    model = "OpenACC" if rec["model"] == "acc" else "OpenMP"
    lang = "C" if rec["lang"] == "c" else "Fortran"
    head = [rec["page"], rec["title"], "",
            f"{KIND_WORDS[rec['kind']]}, {rec['failure']}; status {rec['status']}; {model}, {lang}"]
    if rec["specs"]:
        head.append("spec: " + "; ".join(rec["specs"]))
    if rec.get("legality"):
        why = rec.get("legality_why") or ""
        head.append(f"legality: {rec['legality_words']}" + (f" ({why})" if why else ""))
    out = ["\n".join(head), "compilers:\n" + _compilers_text(rec)]
    if same:
        out.append("other reproducers of the same defect: " + ", ".join(same))
    out.append(f"reproducer ({path}):\n{source}" if path else "reproducer: not in this copy")
    return "\n\n".join(out).rstrip() + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="offload issues", description="search the known compiler problems")
    ap.add_argument("query", nargs="*", help="words that must all appear in the id, title, constructs or messages")
    ap.add_argument("--compiler", help="a family (cce, afar, nvhpc, gcc) or a toolchain (cce19, nvhpc269, ...)")
    ap.add_argument("--kind", choices=sorted(KIND_WORDS))
    ap.add_argument("--stage", choices=("compile", "link", "run"), help="when it fails")
    ap.add_argument("--status", choices=("open", "fixed", "changed", "not-reproduced"))
    ap.add_argument("--legality", choices=("confirmed", "supported", "contested", "unconfirmed"),
                    help="the independent legality review's verdict")
    ap.add_argument("--show", metavar="ID", help="one issue in full, with its reproducer (an id, a part of one or a path)")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    a = ap.parse_args(argv)
    if a.show:
        rec = _resolve(a.show)
        if rec is None:
            near = difflib.get_close_matches(_normalise(a.show), [i["page"] for i in _all()], n=3, cutoff=0.6)
            print(f"offload issues: no issue '{a.show}'" + (f"; did you mean {', '.join(near)}?" if near else ""),
                  file=sys.stderr)
            return 1
        if a.format == "json":
            print(json.dumps({**rec, "source": _source(rec)[1]}, indent=1))
        else:
            print(show(rec["page"]), end="")
        return 0
    try:
        hits = search(" ".join(a.query), a.compiler, a.kind, a.status, a.stage, a.legality)
    except ValueError as e:
        print(f"offload issues: {e}", file=sys.stderr)
        return 2
    if a.format == "json":
        print(json.dumps(hits, indent=1))
        return 0 if hits else 1
    for i in hits:
        who = ", ".join(_label(t) for t in i["versions_failing"])
        note = f"{who}; {i['failure']}" if who else i["failure"]
        print(f"{i['page']}\n    {i['title']}  [{note}]")
    print(f"{len(hits)} of {len(_all())} issues")
    return 0 if hits else 1
