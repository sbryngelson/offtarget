"""The public site's data: which findings are published, how they group into
defects, and the JSON each page reads.

`records` works on plain finding dicts (tested on fixtures); `build` gathers
them from the repository (index, site blocks, the finding matrix, commands,
citations) and writes OUT/data/."""
from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from offload.engine.confirm.machines import load as _machines
from offload.engine.site import scrub as S
from offload.engine.site.matrix import ONLY_TARGETS as M_ONLY
from offload.engine.site.matrix import STATUS_ORDER, TARGETS, VERSIONS, Cell
from offload.engine.toolchains import TOOLCHAINS as _TC
from offload.engine.toolchains import registry as _registry

ROOT = Path(__file__).resolve().parents[3]
_R = _registry()
# the families' short names, in catalog order (the order of the site data)
FAMILY_NAME = {f.id: f.name for f in _R.families.values()}
KIND_WORD = {"incorrect": "Appears to behave incorrectly", "unsupported": "Appears not to support"}
UNPUBLISHED = ("not-a-compiler-issue", "out-of-scope")
# target -> its short name (machines.yaml modes.<mode>.target_short)
TG_SHORT = {m.mode_table[mode]["target"]: m.mode_table[mode]["target_short"]
            for m in _machines().values() for mode in m.modes if m.mode_table[mode].get("target")}
# the most open first: the status a defect shows for a family where its reproducers differ
OPENNESS = ("open", "changed", "mixed", "fixed", "not-reproduced", "not-run")
# a version's state in the issue list's strip: the most failing state over its targets (and,
# for a defect, over its reproducers); a version with any target correct and none failing
# is correct, one with nothing decided is unknown
STRIP = ("fails-like", "fails-differently", "correct", "unknown", "na")
# a seeded title's driver prefix ("ftn: ", "craycc/ftn -fopenmp: ", "nvc -mp=gpu: ")
_DRIVER = re.compile(r"^(?:ftn|craycc|amdflang|amdclang|nvfortran|nvc|flang|clang)"
                     r"(?:/(?:ftn|craycc|amdflang|amdclang|nvfortran|nvc|flang|clang))*"
                     r"(?: (?:-\S+|at HSA_XNACK=\d))*: ")
_DIAG = re.compile(r"error|fatal|internal|undefined|abort|-[SF]-", re.I)


class SiteDataError(ValueError):
    pass


def page_name(fid: str) -> str:
    return fid.replace("/", "--")


def _kind(outcome: str) -> str:
    return "unsupported" if outcome == "rejected" else "incorrect"


def _phase(outcome: str) -> str:
    return "compile" if outcome in ("rejected", "ice") else "offload"


# a link step's failure in a failing cell's output: the linker, the offload and LTO tools
_LINK = re.compile(r"lld: error|\bld: error|undefined reference to|undefined symbol|nvlink|mkoffload|lto1|"
                   r"lto-wrapper|collect2|clang-linker-wrapper|unable to find library", re.I)
# what each outcome is called, at each stage it can happen at
FAILURE_WORDS = {("compile", "rejected"): "refused at compile time", ("link", "rejected"): "refused at link time",
                 ("compile", "ice"): "compiler crash", ("link", "ice"): "compiler crash at link time",
                 ("compile", "timeout"): "compiler hangs", ("run", "timeout"): "hangs at run time",
                 ("run", "crash"): "crashes or aborts at run time", ("run", "run_error"): "run-time error",
                 ("run", "wrong_answer"): "wrong answer"}


def _stage(outcome: str, cells: list[Cell]) -> str:
    """When an issue fails: compile, link or run. A refusal or a crash whose failing cells show a
    link message is a link-time one; a hang is at the stage its failing cells stopped in."""
    failing = [c for c in cells if c.state == "fails-like"]
    if outcome in ("rejected", "ice"):
        link = any(_LINK.search(c.message or c.output or "") for c in failing if c.outcome == "COMPILE_FAIL")
        return "link" if link else "compile"
    if outcome == "timeout":
        return "compile" if any(c.outcome == "COMPILE_TIMEOUT" for c in failing) else "run"
    return "run"


def _legality(fid: str) -> dict:
    """The verdict of the issue's independent legality review (offload.engine.legality_review),
    in the site's words, with the reason."""
    from offload.engine import legality_review as L
    v, why = L.status(fid)
    return {"legality": v, "legality_words": L.WORDS[v], "legality_why": S.scrub(why)}


def _version_label(fam: str, version: str) -> str:
    """"<family> <version>", unless the version label names the family already ("AFAR 24.3.0")."""
    name = FAMILY_NAME[fam]
    return version if version.startswith(name) else f"{name} {version}"


def _label(c: Cell) -> str:
    return _version_label(VERSIONS[c.tc][0], c.version)


def _order(tc: str) -> tuple:
    """Family, release order, then catalog position: two installs of one release (GCC on
    the MI250X and the A100) sort the same way in every build."""
    fam, _, n = VERSIONS[tc]
    return (list(FAMILY_NAME).index(fam), n, list(VERSIONS).index(tc))


def _construct_words(cons) -> str:
    return ", ".join(dict.fromkeys(c.split(":", 1)[-1] for c in cons)) or "offload"


def published(f: dict) -> bool:
    h = f["header"]
    return not h.hide and not (h.disposition and h.disposition[0] in UNPUBLISHED)


def _defects(pub: dict) -> dict:
    """finding id -> defect id (the end of its same_as chain)."""
    out = {}
    for fid in pub:
        seen, cur = [fid], fid
        while pub[cur]["header"].same_as:
            nxt = pub[cur]["header"].same_as
            if nxt not in pub:
                raise SiteDataError(f"{cur}: same_as {nxt!r} is not a published finding")
            if nxt in seen:
                raise SiteDataError(f"{fid}: same_as cycle {' -> '.join(seen + [nxt])}")
            seen.append(nxt)
            cur = nxt
        out[fid] = cur
    return out


def _regression(cells: list[Cell]) -> bool:
    """A version fails on a GPU and memory mode where the family's previous version ran correctly."""
    by = {}
    for c in cells:
        fam, _, n = VERSIONS[c.tc]
        by.setdefault((fam, n, c.target), set()).add(c.state)
    return any("fails-like" in states and "correct" in by.get((fam, n - 1, t), set())
               and "fails-like" not in by.get((fam, n - 1, t), set())
               for (fam, n, t), states in by.items() if n > 0)


def _fam_view(f: dict) -> dict:
    """family -> what the finding does there: failing versions and targets, and the
    family's status. A family appears when the finding fails there or
    when the finding was written for it."""
    cells = f["cells"]
    by_fam = f.get("status_by_fam")
    if by_fam is None:
        by_fam = {VERSIONS[c.tc][0]: tuple(f["status"]) for c in cells if c.state == "fails-like"}
    fams = set(by_fam) | {VERSIONS[c.tc][0] for c in cells if c.state == "fails-like"} | \
        {VERSIONS[t][0] for t in f.get("toolchains", ()) if t in VERSIONS}
    mixed = f["status"][0] == "mixed"
    out = {}
    for fam in sorted(fams, key=list(FAMILY_NAME).index):
        mine = [c for c in cells if VERSIONS[c.tc][0] == fam and c.state == "fails-like"]
        st, ver = ("mixed", None) if mixed else by_fam.get(fam, ("not-run", None))
        out[fam] = {"versions": sorted({c.tc for c in mine}, key=_order),
                    "targets": [t for t in TARGETS.values() if any(c.target == t for c in mine)],
                    "status": st, "status_version": ver,
                    "regression": _regression([c for c in cells if VERSIONS[c.tc][0] == fam]),
                    "states": {tc: _strip_state([c.state for c in cells if c.tc == tc])
                               for tc, (f2, _, _) in VERSIONS.items() if f2 == fam}}
    return out


def _strip_state(states: list) -> str:
    known = [x for x in states if x != "na"]
    if not states:
        return "unknown"
    if not known:
        return "na"
    return min(known, key=STRIP.index)


def _merge_views(views: list[dict]) -> dict:
    """A defect's family view: the union over its reproducers, the most open status."""
    out = {}
    for v in views:
        for fam, x in v.items():
            o = out.setdefault(fam, {"versions": [], "targets": [], "status": "not-run", "status_version": None,
                                     "regression": False, "states": {}})
            o["regression"] = o["regression"] or bool(x.get("regression"))
            o["versions"] = sorted(set(o["versions"]) | set(x["versions"]), key=_order)
            for tc, st in x.get("states", {}).items():
                o["states"][tc] = min(st, o["states"].get(tc, st), key=STRIP.index)
            o["targets"] = [t for t in TARGETS.values() if t in o["targets"] or t in x["targets"]]
            if OPENNESS.index(x["status"]) < OPENNESS.index(o["status"]):
                o["status"], o["status_version"] = x["status"], x["status_version"]
    return dict(sorted(out.items(), key=lambda kv: list(FAMILY_NAME).index(kv[0])))


def _where(c: Cell) -> str:
    return f"{_label(c)}, {TG_SHORT[c.target]}"


def _messages(cells: list[Cell]) -> list[dict]:
    """Each distinct failure with its message and where it happens."""
    out: dict = {}
    for c in sorted(cells, key=lambda c: _order(c.tc)):
        if c.state in ("fails-like", "fails-differently") and (c.message or c.outcome):
            key = (c.state, c.outcome, S.scrub(c.message))
            out.setdefault(key, []).append(_where(c))
    return [{"state": st, "outcome": oc, "message": msg, "where": where}
            for (st, oc, msg), where in sorted(out.items(), key=lambda kv: kv[0][0] != "fails-like")]


def _search_text(cells: list[Cell]) -> str:
    """The first diagnostic line of each distinct failure like the issue, for the list's search."""
    lines = []
    for c in cells:
        if c.state == "fails-like" and c.message:
            ls = [x.strip() for x in S.scrub(c.message).splitlines() if x.strip()]
            first = next((x for x in ls if _DIAG.search(x)), ls[0] if ls else "")[:160]
            if first and first not in lines:
                lines.append(first)
    return " | ".join(lines)[:600]


def _title(h, kind: str, cells: list[Cell], constructs, fams: dict) -> str:
    """The site block's title, without a driver prefix ("ftn: ") when the issue fails on more
    than one compiler family; else "<kind>: <constructs> (<failing compilers>)"."""
    if h.title:
        failing = [f for f, v in fams.items() if v["versions"]]
        if len(failing) > 1 and _DRIVER.match(h.title):
            rest = _DRIVER.sub("", h.title, count=1)
            return rest[:1].upper() + rest[1:]
        return h.title
    labels = list(dict.fromkeys(_label(c) for c in sorted(cells, key=lambda c: _order(c.tc))
                                if c.state == "fails-like"))
    return (f"{KIND_WORD[kind]}: {_construct_words(constructs)}"
            + (f" ({', '.join(labels)})" if labels else ""))


def _control_results(cells: list[Cell]) -> list[dict]:
    """Per compiler, what the control did where it was decided."""
    out = []
    for c in sorted(cells, key=lambda c: _order(c.tc)):
        if c.state in ("unknown", "na"):
            continue
        r = {"label": _label(c), "state": c.state}
        if r not in out:
            out.append(r)
    return out


def _spec_labels(citations: list[dict], limit: int = 3) -> list[str]:
    """The distinct "OpenMP 5.2 §5.8.3" labels of verified citations, in order."""
    out: list[str] = []
    for c in citations:
        if c.get("version") and c.get("section"):
            label = f"{c['version']} §{c['section']}"
            if label not in out:
                out.append(label)
    return out[:limit]


def _issue_citations(fid: str, pub: dict, defect: dict, members: dict) -> tuple[list[dict], str | None]:
    """The citations an issue shows: its own; else its defect's page; else the first member
    that has some (the requirement is the defect's, whichever program shows it)."""
    own = pub[fid].get("citations", [])
    if own:
        return own, None
    root = defect[fid]
    for cand in [root] + [m for m in members.get(root, []) if m not in (fid, root)]:
        cs = pub[cand].get("citations", []) if cand in pub else []
        if cs:
            return cs, (cand if cand != fid else None)
    return [], None


# the GitHub issue forms an issue page links to (.github/ISSUE_TEMPLATE/), each with a `finding` field
REPORT_FORMS = {"dispute": "dispute-a-finding.yml", "fixed": "fixed-in-a-release.yml", "wrong": "wrong-result.yml"}
_REPORT_TITLE = {"dispute": "Legality of {id}", "fixed": "{id} fixed in a newer release",
                 "wrong": "Mistake in {id}"}


def report_urls(repo_url: str, finding_id: str) -> dict:
    """The links that open each REPORT_FORMS form with the finding filled in ({} without a repository)."""
    if not repo_url:
        return {}
    from urllib.parse import urlencode
    base = repo_url.rstrip("/") + "/issues/new?"
    return {k: base + urlencode({"template": form, "title": _REPORT_TITLE[k].format(id=finding_id),
                                 "finding": finding_id})
            for k, form in REPORT_FORMS.items()}


def records(findings: list[dict], repo_url: str = "", branch: str = "master") -> dict:
    """`branch`: the repository branch the source links point into (the default branch;
    the workflow passes the repository's)."""
    pub = {f["id"]: f for f in findings if published(f)}
    defect = _defects(pub)
    members: dict = {}
    for fid, d in defect.items():
        members.setdefault(d, []).append(fid)
    views = {fid: _fam_view(f) for fid, f in pub.items()}
    cites = {fid: _issue_citations(fid, pub, defect, members) for fid in pub}
    issues, pages = [], {}
    for fid, f in pub.items():
        h, cells = f["header"], f["cells"]
        kind = _kind(f["outcome"])
        fails_fams = {VERSIONS[c.tc][0] for c in cells if c.state == "fails-like"}
        witnesses = list(dict.fromkeys(
            _label(c) for c in sorted(cells, key=lambda c: _order(c.tc))
            if c.state == "correct" and VERSIONS[c.tc][0] not in fails_fams))
        status, sver = f["status"]
        group = members[defect[fid]] if defect[fid] == fid else [fid]
        fams = _merge_views([views[m] for m in group])
        title = _title(h, kind, cells, f["constructs"], fams)
        issue = {"id": fid, "page": page_name(fid), "title": S.scrub(title), "kind": kind,
                 "kinds": sorted({_kind(pub[m]["outcome"]) for m in group}),
                 "phase": _phase(f["outcome"]), "stage": (st := _stage(f["outcome"], cells)),
                 **_legality(fid),
                 "symptom": f["outcome"], "failure": FAILURE_WORDS.get((st, f["outcome"]), f["outcome"]),
                 "lang": f["lang"], "model": f["model"],
                 "constructs": [c.split(":", 1)[-1] for c in f["constructs"]],
                 "defect": defect[fid], "reproducers": len(group) if defect[fid] == fid else 0,
                 "versions_failing": sorted({t for x in fams.values() for t in x["versions"]}, key=_order),
                 "targets_failing": [t for t in TARGETS.values() if any(t in x["targets"] for x in fams.values())],
                 "status": status, "status_version": sver, "fams": fams,
                 "specs": _spec_labels(cites[fid][0]),
                 "regression": any(_regression(pub[m]["cells"]) for m in group),
                 "search": " | ".join(x for x in (_search_text(pub[m]["cells"]) for m in group) if x)[:600],
                 "mixed_reason": h.disposition[1] if h.disposition and h.disposition[0] == "mixed" else None}
        issues.append(issue)
        observed = next((c.output or c.message for c in cells if c.state == "fails-like" and (c.output or c.message)),
                        "")
        srcs = f.get("control_sources", {})
        pages[fid] = dict(
            issue, summary=h.summary, workaround=h.workaround, found_in=h.found_in,
            cells=[{"tc": c.tc, "version": _label(c), "target": c.target, "state": c.state,
                    "outcome": c.outcome, "message": S.scrub(c.message), "output": S.scrub(c.output),
                    "envs": c.envs, "reason": c.reason} for c in cells],
            messages=_messages(cells),
            controls=[{"path": p, "what": w, "results": _control_results(f.get("control_cells", [])),
                       "source": S.scrub(srcs.get(p, ""))} for p, w in h.controls],
            commands=[dict(c, text=S.scrub(c["text"])) for c in f.get("commands", [])], expected=f.get("expected"), observed=S.scrub(observed),
            citations=cites[fid][0], citations_from=cites[fid][1], witnesses=witnesses, source=S.scrub(f.get("source", "")),
            members=[{"id": m, "page": page_name(m)} for m in members[defect[fid]]],
            defect_page=page_name(defect[fid]),
            source_url=(f"{repo_url.rstrip('/')}/blob/{branch}/data/findings/{f['file']}" if repo_url else None),
            report_urls=report_urls(repo_url, fid))
    ran_tc: dict = {}
    for f in pub.values():
        for c in f["cells"]:
            if c.state not in ("unknown", "na"):
                ran_tc.setdefault(c.tc, set()).add(c.target)
    ran_tc = {tc: [t for t in TARGETS.values() if t in ts] for tc, ts in sorted(ran_tc.items(), key=lambda kv: _order(kv[0]))}
    ran = {}
    for tc, ts in ran_tc.items():
        ran.setdefault(VERSIONS[tc][0], set()).update(ts)
    return _without_task_refs({"issues": issues, "pages": pages,
                               "ran": {fam: [t for t in TARGETS.values() if t in ts] for fam, ts in ran.items()},
                               "ran_tc": ran_tc,
                               "counts": {"defects": len(set(defect.values())), "findings": len(pub)}})


def _map_strings(x, fn):
    if isinstance(x, str):
        return fn(x)
    if isinstance(x, dict):
        return {k: _map_strings(v, fn) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return type(x)(_map_strings(v, fn) for v in x)
    return x


def _without_task_refs(recs: dict) -> dict:
    """Every string of the records without the internal "Task NN" references of the findings'
    program headers (offload.engine.site.scrub.unjargon); a reference no rule covers stops the
    build, so a new phrasing gets its rule and its test instead of reaching the site."""
    recs = _map_strings(recs, functools.lru_cache(maxsize=None)(S.public_text))      # the same text recurs in many cells
    left = sorted({r for s in _strings(recs) for r in S.task_refs(s)})
    if left:
        raise SiteDataError(f"internal task reference on the site: {left[:10]}; add a rewrite rule "
                            "for its phrasing to offload.engine.site.scrub (_TASK_RULES) and its test")
    return recs


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _strings(v)


def write(out: Path, recs: dict, allow: tuple[str, ...] = ()) -> None:
    hits = [h for s in _strings(recs) for h in S.leaks(s, allow)]
    if hits:
        raise SiteDataError(f"leak in the site data: {sorted(set(hits))[:10]}")
    d = Path(out) / "data"
    (d / "issues").mkdir(parents=True, exist_ok=True)
    (d / "issues.json").write_text(json.dumps({"issues": recs["issues"], "counts": recs["counts"],
                                               "ran": recs.get("ran", {}), "ran_tc": recs.get("ran_tc", {})},
                                              separators=(",", ":")))
    for fid, page in recs["pages"].items():
        (d / "issues" / (page_name(fid) + ".json")).write_text(json.dumps(page, separators=(",", ":")))


# --- gathering from the repository ---------------------------------------------------

# target -> (machine, memory mode) for a recipe
_RUN_AT = {t: (mach, int(mode)) for (mach, mode), t in TARGETS.items()}


def _commands(case: dict | None, cells: list[Cell]) -> list[dict]:
    """The build and run lines, with generic compiler roots (no private path): every
    toolchain where the finding fails, in the memory mode where it fails,
    then one compiler that runs it correctly (another family when there is one)."""
    if case is None:
        return []
    from offload.engine.site.matrix import B  # noqa: F401  (puts data/vendor/checks on sys.path)
    import run_checks as R
    tg = list(TARGETS.values())
    picks, seen = [], set()
    for c in sorted(cells, key=lambda c: (_order(c.tc), tg.index(c.target))):
        if c.state == "fails-like" and c.tc not in seen:
            seen.add(c.tc)
            picks.append((c, "fails"))
    fams = {VERSIONS[c.tc][0] for c, _ in picks}
    ok = sorted((c for c in cells if c.state == "correct"),
                key=lambda c: (VERSIONS[c.tc][0] in fams, _order(c.tc), tg.index(c.target)))
    if ok:
        picks.append((ok[0], "correct"))
    out = []
    for c, role in picks:
        tc = c.tc
        mach, mode = _RUN_AT[c.target]
        src = "repro" + (".c" if case.get("lang") == "c" else ".f90")
        r = R.recipe(tc, mach, case.get("lang", "f90"), case.get("model", "omp"),
                     R.extra_for(case, tc), case.get("opt", "-O2"), mode, src, "repro")
        if r is None:
            continue
        pre, cmd, env = r
        lines = [p.replace(" >/dev/null 2>&1", "") for p in pre if "/etc/profile" not in p]
        cmd = cmd.replace(" -L/usr/lib/gcc/x86_64-redhat-linux/8", "")
        machine = _machines()[mach]
        # the mode's run-time setting (AMD: HSA_XNACK; none where the mode is a compile flag)
        run = [f"{k}={v}" for k, v in machine.env(machine.mode_of_row_key(mode)).items()] + (
            [] if case.get("model") == "acc" else ["OMP_TARGET_OFFLOAD=mandatory"])
        t = _TC[tc]
        if t.family.site_runtime_env and "LD_LIBRARY_PATH" in dict(t.env):
            # the release's runtime libraries (NVHPC; GCC's libgomp and ROCm's HSA runtime)
            lines.append("export LD_LIBRARY_PATH=" + S.scrub(t.public(dict(t.env)["LD_LIBRARY_PATH"])))
        lines += [S.scrub(_generic(cmd)), " ".join(run + ["./repro"])]
        out.append({"tc": tc, "target": c.target, "label": _where(c), "role": role, "text": "\n".join(lines)})
    return out


def _generic(cmd: str) -> str:
    """`cmd` with every catalog install root in its public form (Toolchain.public)."""
    for t in _TC.values():
        cmd = t.public(cmd)
    return cmd


def _citations(path: Path) -> list[dict]:
    """A finding file's citations that check out against the specification text
    (offload.engine.citations; needs the git-ignored spec cache). The build does not call
    this: tools/site/site_inputs.py does, and commits the result as site/inputs/citations.json."""
    from offload.engine import citations as C
    allow = C.load_allowlist()
    out = []
    for c in C.extract_file(path, ROOT, allow):
        if c.skipped or c.external:
            continue
        if C.check(c).status == "ok":
            out.append({"text": c.text, "version": c.version, "section": c.section,
                        "quote": c.quote})
    return out


def gather() -> list[dict]:
    """Every finding of the index with what the site needs, from committed data only:
    the finding files, the matrix rows (data/vendor/checks) and the verified citations
    of site/inputs/citations.json (tools/site/site_inputs.py)."""
    from offload.engine.confirm.findings import load_index
    from offload.engine.site import header as H
    from offload.engine.site import inputs as I
    from offload.engine.site import matrix as M
    rows, cases = M._rows(), M._cases()
    cites = I.load_citations()
    base = ROOT / "data" / "findings"
    out = []
    for f in load_index():
        path = ROOT / f.file
        rel = str(path.relative_to(base))
        fid = rel.rsplit(".", 1)[0]
        h = H.parse(path)
        entry = {"file": rel, "outcome": f.outcome, "lang": f.lang, "expected": f.expected,
                 "toolchains": list(f.toolchains)}
        case = M._case(fid, cases, entry)
        cells = M.cells(fid, rows, cases, entry)
        pub = published({"header": h})
        out.append({"id": fid, "file": rel, "lang": f.lang,
                    "model": (case or {}).get("model", "acc" if "acc" in Path(fid).name.split("-") else "omp"),
                    "outcome": f.outcome, "constructs": sorted(f.constructs), "expected": f.expected or None,
                    "toolchains": list(f.toolchains), "header": h, "cells": cells,
                    "control_cells": M.controls(fid, rows, cases),
                    "control_sources": {p: _read(base / p) for p, _ in h.controls} if pub else {},
                    "status": M.status(fid, rows, cases, header=h, entry=entry),
                    "status_by_fam": M.status_by_family(fid, rows, cases, entry), "case": case,
                    "commands": _commands(case, cells) if pub else [],
                    "citations": I.citations_of(rel, cites) if pub else [],
                    "source": H.strip(path.read_text(errors="replace"))})
    return out


def _read(path: Path) -> str:
    return path.read_text(errors="replace") if path.is_file() else ""


# how settled an issue's legality is (the list's sort, site/static/issues.js LEGALITY_RANK)
LEGALITY_RANK = {"confirmed": 2, "supported": 2, "unconfirmed": 1, "contested": 0}


def fixed_order(issues: list[dict], fam: str, regressions: set | None = None) -> list[dict]:
    """The spec's fixed order: wrong answers first (an offload-phase issue that appears to
    behave incorrectly), then how settled its legality is (confirmed or supported, unconfirmed,
    contested), then regressions, then reach (versions and targets it fails on in the family),
    then title."""
    def key(i):
        v = i["fams"].get(fam) or {"versions": [], "targets": []}
        wrong = i["phase"] == "offload" and "incorrect" in i.get("kinds", [i["kind"]])
        reg = i["id"] in regressions if regressions is not None else i["regression"]
        return (not wrong, -LEGALITY_RANK.get(i.get("legality"), 1), not reg,
                -(len(v["versions"]) + len(v["targets"])), i["title"])
    return sorted(issues, key=key)


def compilers(recs: dict) -> dict:
    """tc -> its page: the issues (defects) any reproducer fails there, its regressions,
    what it fixed or changed by the family's status, each list in the
    fixed order."""
    by_defect: dict = {}
    for fid, p in recs["pages"].items():
        by_defect.setdefault(p["defect"], []).append(p)
    primaries = [i for i in recs["issues"] if i["defect"] == i["id"]]
    out = {}
    for tc, (fam, ver, n) in VERSIONS.items():
        label = _version_label(fam, ver)
        if sum(1 for f2, v2, _ in VERSIONS.values() if (f2, v2) == (fam, ver)) > 1:
            # one release, one install per GPU kind (GCC): the page names its GPUs as the catalog's
            # pill does ("AMD", "A100"), else the one GPU it runs on
            gpus = sorted({TG_SHORT[t].split()[0] for t in TARGETS.values() if M_ONLY.get(tc) and t in M_ONLY[tc]})
            label += " " + (_R.toolchains[tc].site_pill.split()[-1] if len(gpus) > 1 else "/".join(gpus))
        prev = [t for t, (f2, _, m) in VERSIONS.items() if f2 == fam and m == n - 1]
        fails, regress, fixed = [], [], []
        for i in primaries:
            pages = by_defect[i["id"]]
            if any(c["tc"] == tc and c["state"] == "fails-like" for p in pages for c in p["cells"]):
                fails.append(i)
                if prev and any(any(c["tc"] == tc and c["state"] == "fails-like" for c in p["cells"])
                                and any(c["tc"] == prev[0] and c["state"] == "correct" for c in p["cells"])
                                and not any(c["tc"] == prev[0] and c["state"] == "fails-like" for c in p["cells"])
                                for p in pages):
                    regress.append(i)
            v = i["fams"].get(fam)
            if v and v["status"] in ("fixed", "changed") and v["status_version"] == ver:
                fixed.append(i)
        reg = {i["id"] for i in regress}
        ids = lambda xs: [i["id"] for i in fixed_order(xs, fam, reg)]  # noqa: E731
        out[tc] = {"tc": tc, "label": label, "family": fam, "version": ver, "fails": ids(fails),
                   "regressions": ids(regress), "fixed_or_changed": ids(fixed)}
    return out


CU_WORD = {"ok": "correct", "rejected": "unsupported", "excluded": "unsupported", "wrong": "incorrect",
           "suspect": "unknown", "unverified": "unknown"}


def _atom_columns() -> dict:
    """toolchain -> ((atom-table column, target), ...) for the toolchains in the merged result
    tables (catalog merged_key): the dashboard's atoms carry <key>_x<mode> per memory mode of
    the toolchain's machine (tools/site/dashboard_data.py) and <key><suffix> for each twin
    (<key>_g90, <key>_mi300x)."""
    out = {}
    for tc in _R.merged():
        t = _TC[tc]
        m = _machines()[t.machine]
        cols = [(f"{t.merged_key}_x{m.row_key(mode)}", TARGETS[(t.machine, str(m.row_key(mode)))])
                for mode in m.modes if m.row_key(mode) in t.xnack_modes]
        for twin in _R.twins_of(tc):
            tw = _TC[twin]
            cols.append((f"{t.merged_key}{_R.twin_key(twin)}",
                         TARGETS[(tw.machine, str(tw.xnack_modes[0]))]))
        out[tc] = tuple(cols)
    return out


def canuse(atoms: list | None = None, recs: dict | None = None) -> dict:
    """Support per construct from the dashboard's atom table (the committed projection
    site/inputs/atoms.json.gz, tools/site/site_inputs.py), in the site's words, with the issues
    whose constructs include it."""
    if atoms is None:
        from offload.engine.site import inputs as I
        atoms = I.load_atoms()
    cols = _atom_columns()
    issues = [i for i in (recs or {}).get("issues", []) if i["defect"] == i["id"]]
    by = {}
    for a in atoms:
        if a.get("scope") != "device":
            continue
        cells = {}
        for tc, cs in cols.items():
            for col, t in cs:
                if col in a:
                    cell = {"state": CU_WORD.get(a[col], "unknown")}
                    note = a.get("note_" + col)
                    if cell["state"] in ("unknown", "unsupported") and note:
                        cell["reason"] = S.public_text(S.scrub(str(note))[:200])
                    cells[f"{tc}|{t}"] = cell
        name = a["atom"].split(".", 1)[-1]
        by.setdefault(a["atom"], []).append({
            "id": a["id"], "version": a["version"], "lang": a["lang"], "citation": a.get("citation"),
            "model": "acc" if a["id"].startswith("acc") else "omp", "cells": cells,
            "issues": [{"page": i["page"], "title": i["title"]} for i in issues if name in i["constructs"]]})
    return by


def build(out: Path, repo_url: str = "", branch: str = "master") -> dict:
    recs = records(gather(), repo_url, branch)
    write(out, recs, allow=(repo_url.rstrip("/"),) if repo_url else ())
    d = Path(out) / "data"
    (d / "compilers").mkdir(parents=True, exist_ok=True)
    for tc, page in compilers(recs).items():
        (d / "compilers" / f"{tc}.json").write_text(json.dumps(page, separators=(",", ":")))
    cu = canuse(recs=recs)
    (d / "canuse").mkdir(parents=True, exist_ok=True)
    (d / "canuse" / "index.json").write_text(json.dumps(sorted(cu), separators=(",", ":")))
    for letter in sorted({k[0] for k in cu}):
        part = {k: v for k, v in cu.items() if k[0] == letter}
        txt = json.dumps(part, separators=(",", ":"))
        if S.leaks(txt):
            raise SiteDataError(f"leak in can-I-use data {letter}")
        if S.task_refs(txt):
            raise SiteDataError(f"internal task reference in can-I-use data {letter}: {S.task_refs(txt)[:5]}")
        (d / "canuse" / f"{letter}.json").write_text(txt)
    search = [{"id": i["id"], "page": i["page"], "title": i["title"], "constructs": i["constructs"]}
              for i in recs["issues"]]
    (d / "search.json").write_text(json.dumps(search, separators=(",", ":")))
    return {"counts": recs["counts"], "issues": len(recs["issues"]), "canuse": len(cu)}
