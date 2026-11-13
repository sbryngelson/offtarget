"""Vendor-claim mismatches and omp_vv flags, run through the confirmer.

Each mismatch between an ingested vendor claim (offload.engine.confirm.claims,
compared by offload.engine.report.compare_claims) and each omp_vv cross-check flag
(tools/derive/ompvv_compare.py) becomes one or more cases: the contradicting
cells, our failing catalog cells of an ``ours_bad_suite_passes`` flag, or the
failing narrow suite tests of an ``ours_ok_suite_fails`` flag. ``confirm``
decides each case offline from stored evidence; ``mismatch_disposition`` and
``flag_disposition`` combine the verdicts. Items left ``needs_human`` are
decided in catalog/triage_27b.yaml (``decisions``), which also records the spot
checks (``spot_checks``). ``render`` writes the tables of
data/reports/triage-2026-10.md, the doc-overclaim list and the draft
docs/upstream.md from results/confirm/triage27b.jsonl."""
from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DECISIONS = ROOT / "catalog" / "triage_27b.yaml"
UPSTREAM_STATUS = ROOT / "catalog" / "upstream_status.yaml"
OUT = ROOT / "results" / "confirm" / "triage27b.jsonl"

# mismatch dispositions (brief item 3) and flag dispositions (item 4)
MISMATCH_CLASSES = ("our_error", "compiler_bug", "doc_overclaims",
                    "doc_understates", "version_scope", "partial_support",
                    "unsupported_everywhere", "implementation_defined",
                    "harness_issue", "needs_human")
FLAG_CLASSES = ("compiler_bug", "unsupported_form", "test_bug", "our_error",
                "harness_issue", "not_a_contradiction", "needs_human")
BUG = {"compiler_bug", "copy_mode_failure", "unified_memory_failure",
       "arch_specific"}


@dataclass
class Item:
    kind: str                 # mismatch | flag
    key: str
    info: dict
    cases: list = field(default_factory=list)   # confirm results (slim)
    disposition: str = ""
    basis: str = ""           # why: the rule of the computed disposition
    decided_by: str = "confirmer"   # confirmer | agent

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def slim(res: dict) -> dict:
    """The fields of a confirm result the triage keeps."""
    c = res["case"]
    return {"case_id": c["case_id"], "toolchain": c["toolchain"],
            "arch": c["arch"], "mode": c["mode"], "outcome": c["outcome"],
            "reason": (c.get("reason") or "")[:200],
            "verdict": res["verdict"], "rule": res["rule"],
            "why": (res.get("reason") or "")[:300],
            "findings": [h.get("file", "") for h in res.get("findings") or []]}


# --- directives inside target regions (documented device limitations) ---------------

_F_DIR = re.compile(r"^\s*!\$omp\s+(.*)$", re.I)
_C_DIR = re.compile(r"^\s*#\s*pragma\s+omp\s+(.*)$", re.I)
_DATA = ("target data", "target enter data", "target exit data",
         "target update")


def _name(body: str) -> str:
    """The directive name of a directive's text (its leading directive
    words; a word with an argument, or the clause ordered after a name,
    ends it)."""
    from offload.engine.confirm.programs import _DIRECTIVE_WORDS
    words = body.strip().lower().replace(",", " ").split()
    name: list[str] = []
    for w in words:
        bare = w.split("(")[0]
        if bare not in _DIRECTIVE_WORDS or "(" in w or len(name) >= 5 or \
                (name and bare in ("ordered", "simd") and name[-1] in
                 ("for", "do") and bare == "ordered"):
            break
        name.append(bare)
    return " ".join(name)


def _joined(lines: list[str], lang: str) -> list[tuple[int, str]]:
    """(line index, directive text) with continuations joined."""
    out, i = [], 0
    while i < len(lines):
        m = (_F_DIR if lang != "c" else _C_DIR).match(lines[i])
        if not m:
            i += 1
            continue
        text, j = m.group(1), i
        if lang != "c":
            while text.rstrip().endswith("&") and j + 1 < len(lines):
                j += 1
                nxt = re.sub(r"^\s*!\$omp&?\s*", "", lines[j], flags=re.I)
                text = text.rstrip()[:-1] + " " + nxt.lstrip("&")
        else:
            while text.rstrip().endswith("\\") and j + 1 < len(lines):
                j += 1
                text = text.rstrip()[:-1] + " " + lines[j].strip()
        out.append((i, text.split("!")[0] if lang != "c" else text))
        i = j + 1
    return out


def _is_target(name: str) -> bool:
    return name.startswith("target") and not name.startswith(_DATA)


def device_directives(text: str, lang: str) -> set[str]:
    """The names of the directives lexically inside target regions (a
    target construct's own leaves excluded)."""
    lines = text.splitlines()
    dirs = _joined(lines, lang)
    out: set[str] = set()
    if lang != "c":
        depth = 0
        loop_targets: list[int] = []   # do-nesting levels of combined loops
        do_level = 0
        at = {i: s for i, s in dirs}
        for i, line in enumerate(lines):
            if i in at:
                name = _name(at[i])
                if name.startswith("end"):
                    if _is_target(name[4:]) and depth:
                        depth -= 1
                        if loop_targets and loop_targets[-1] == -1:
                            loop_targets.pop()
                    continue
                if _is_target(name):
                    depth += 1
                    loopish = any(w in name.split() for w in
                                  ("do", "loop", "simd", "distribute"))
                    loop_targets.append(do_level + 1 if loopish else -1)
                elif depth:
                    out.add(name)
                continue
            if re.match(r"^\s*(\w+\s*:\s*)?do\b", line, re.I):
                do_level += 1
            elif re.match(r"^\s*end\s*do\b", line, re.I):
                if loop_targets and loop_targets[-1] == do_level:
                    loop_targets.pop()
                    depth -= 1
                do_level -= 1
        return out
    for i, body in dirs:
        if not _is_target(_name(body)):
            continue
        # the structured block: the next statement, braces balanced
        j = i + 1 + body.count("\\")
        while j < len(lines) and (not lines[j].strip() or
                                  _C_DIR.match(lines[j])):
            if _C_DIR.match(lines[j]):
                break
            j += 1
        k, bal, seen = j, 0, False
        while k < len(lines):
            s = lines[k]
            bal += s.count("{") - s.count("}")
            seen = seen or "{" in s
            ends = s.rstrip().endswith(";")
            if (seen and bal <= 0) or (not seen and ends and not (
                    s.lstrip().startswith("for") and
                    s.rstrip().endswith(")"))):
                break
            k += 1
        for i2, b2 in dirs:
            if j <= i2 <= k:
                out.add(_name(b2))
    out.discard("")
    return out


def directive_clauses(text: str, lang: str) -> list[tuple[str, set]]:
    """(directive name, clause names) of every directive of a program
    (continuations joined; end directives skipped)."""
    out = []
    for _, body in _joined(text.splitlines(), lang):
        name = _name(body)
        if not name or name.startswith("end"):
            continue
        rest = body.strip().lower()
        rest = re.sub(r"\([^()]*(?:\([^()]*\)[^()]*)*\)", "()", rest)
        words = rest.replace(",", " ").split()[len(name.split()):]
        out.append((name, {w.split("(")[0].strip(":") for w in words
                           if re.fullmatch(r"[a-z_]+(\(\))?:?", w)}))
    return out


def device_limits(toolchain: str, lang: str, text: str,
                  own_atom: str = "") -> tuple[list, str]:
    """What the program uses that the vendor documents as unsupported:
    directives inside target regions (generic claims on
    ``device.directive.<name>``), clauses with a specific unsupported
    claim of their own (``omp.clause.<name>``, other than the program's
    own atom and its family), and a clause on a construct whose leaf the
    vendor documents it as unsupported on (``onleaf.<leaf>.<clause>``,
    NVHPC's "The lastprivate clause is not
    supported" for distribute; a combined construct takes the clause as
    far as its leaves do, guide §2.14; the program's own clause included,
    since a pseudo-atom is never compared with the support tables), with
    the document section of the first."""
    from fnmatch import fnmatchcase
    from offload.engine.confirm import claims as CL
    from offload.engine.confirm.programs import constructs
    from offload.engine.toolchains import base_name
    tc = base_name(toolchain)
    mine = [c for c in CL.generic()
            if c.toolchain == tc and c.claim == "unsupported" and
            not c.general and c.covers_language(lang)]
    dev = {c.construct: c for c in mine
           if c.atom.startswith("device.directive.")}
    hit, page = [], ""
    for w in sorted({w for d in device_directives(text, lang)
                     for w in d.split() if w in dev}):
        hit.append(w)
        page = page or dev[w].page
    onleaf = [c for c in mine if c.atom.startswith("onleaf.")]
    if onleaf:
        for name, clauses in directive_clauses(text, lang):
            leaves = name.split()
            for c in onleaf:
                _, leaf, cl = c.atom.split(".", 2)
                if leaf in leaves and cl in clauses and \
                        f"clause {cl} on {leaf}" not in hit:
                    hit.append(f"clause {cl} on {leaf}")
                    page = page or c.page
    own = own_atom.split(".")[2] if own_atom.count(".") >= 2 else ""
    for con in sorted(constructs(text)):
        if not con.startswith("clause:"):
            continue
        name = con.split(":", 1)[1]
        if name == own:
            continue
        atom = f"omp.clause.{name}"
        c = next((c for c in mine if c.atom.startswith("omp.") and
                  fnmatchcase(atom, c.atom)), None)
        if c is not None:
            hit.append(f"clause {name}")
            page = page or c.page
    return hit, page


# --- dispositions --------------------------------------------------------------------

PRIORITY = ("our_error", "compiler_bug", "doc_overclaims", "partial_support",
            "version_scope", "unsupported_everywhere",
            "implementation_defined", "harness_issue", "doc_understates",
            "needs_human")


def _cell_class(m: dict, v: dict) -> tuple[str, str]:
    """The mismatch class one contradicting cell's verdict supports."""
    verdict, rule = v["verdict"], v["rule"]
    passing = v["outcome"] in ("correct_on_device", "unobservable")
    if passing:
        if m["claim"] == "unsupported":
            if m["older_doc"]:
                return "version_scope", "the claim's document describes an " \
                    "older compiler than the one measured"
            return "doc_understates", "the vendor says unsupported; the " \
                "compiler runs it correctly on the device"
        return "needs_human", "a passing cell contradicting a support claim"
    lim = (m.get("device_unsupported") or {}).get(
        _ident(v.get("case_id", "")))
    if lim and v["outcome"] != "ice" and verdict in BUG | {"unsupported"}:
        return "partial_support", (
            f"{rule}; documented limitation: the program uses "
            f"{', '.join(lim)}, which the vendor documents as not supported "
            f"(in a target region, for a directive) "
            f"({m.get('device_unsupported_doc', '')})")
    if verdict in BUG:
        return "compiler_bug", f"{rule}"
    if verdict == "our_bug":
        return "our_error", rule
    if verdict == "unsupported":
        if rule.startswith("R11a"):
            return "version_scope", f"{rule}: a 6.0 form the vendor does " \
                "not claim; the claim covers the earlier spelling"
        if m["claim"] == "unsupported":
            # a compile-error claim contradicted by an ignored clause
            return "doc_overclaims", f"{rule}: the vendor says the form is " \
                "a compile error; the compiler accepts and ignores it"
        if m["cross_language"]:
            return "version_scope", f"{rule}: the claim is about C/C++ " \
                "(the AMD-hosted Clang table), the program is Fortran"
        if m["confound"]:
            return "partial_support", f"{rule}: the compiler does not " \
                "implement the construct this program uses (" + \
                m["confound"][:120] + ")"
        return "doc_overclaims", f"{rule}: the vendor claims support; the " \
            "compiler says it does not implement it or ignores it"
    if verdict == "unsupported_everywhere":
        # RUL-UNSUPPORTED-EVERYWHERE-AMENDED: without an
        # independent witness, a quoted legality reading and a vendor
        # claim, every family rejecting stays unsupported_everywhere
        return "unsupported_everywhere", rule
    if verdict == "unspecified":
        return "implementation_defined", rule
    if verdict in ("environment",):
        return "harness_issue", rule
    if verdict in ("needs_unified_memory", "requirement_refused"):
        return "implementation_defined", f"{rule}: a memory-mode " \
            "requirement, not the claimed feature"
    if verdict == "flaky":
        return "compiler_bug", f"{rule}: nondeterministic failure of a " \
            "legal program the vendor claims to support"
    return "needs_human", f"{rule}: {verdict}"


def mismatch_disposition(m: dict, verdicts: list[dict]) -> tuple[str, str]:
    """The disposition of one mismatch from its cells' confirm verdicts:
    the highest class of ``PRIORITY`` any cell supports (one failing cell
    with a bug verdict contradicts a support claim), needs_human only when
    no cell decides."""
    if not verdicts:
        return "needs_human", "no contradicting cell found"
    got = [_cell_class(m, v) for v in verdicts]
    classes = Counter(c for c, _ in got)
    for c in PRIORITY:
        if classes.get(c):
            if c == "needs_human" and len(classes) > 1:
                continue
            why = next(w for k, w in got if k == c)
            mix = "" if len(classes) == 1 else " (cells: " + ", ".join(
                f"{k} {n}" for k, n in sorted(classes.items())) + ")"
            return c, why + mix
    return "needs_human", "undecided"


def flag_disposition(flag: dict, verdicts: list[dict]) -> tuple[str, str]:
    """An ours_bad_suite_passes flag: our failing cell's verdict (the
    suite's narrow test, a different form of the construct, passes); an
    ours_ok_suite_fails flag: the suite's failing tests' verdicts
    (omp_vv is untrusted, so these are needs_human for an agent)."""
    if not verdicts:
        return "needs_human", "no case"
    vs = Counter(v["verdict"] for v in verdicts)
    if flag["flag"] == "ours_bad_suite_passes":
        if any(v["verdict"] in BUG for v in verdicts):
            return "compiler_bug", "our cell: " + ", ".join(
                sorted({v["rule"] for v in verdicts if v["verdict"] in BUG})
            ) + "; the suite's narrow test uses another form"
        if vs.get("our_bug"):
            return "our_error", "our cell: our_bug"
        if vs.get("unsupported") or vs.get("unsupported_everywhere"):
            return "unsupported_form", "our cell: " + ", ".join(sorted(
                {v["rule"] for v in verdicts})) + "; the suite's narrow " \
                "test uses a form the compiler implements"
        if vs.get("environment"):
            return "harness_issue", "our cell: environment"
        if vs.get("unspecified"):
            return "not_a_contradiction", "our cell is implementation-" \
                "defined (no support verdict)"
        return "needs_human", "our cell: " + ", ".join(
            f"{k} {n}" for k, n in sorted(vs.items()))
    if all(v["verdict"] == "environment" for v in verdicts):
        return "harness_issue", "every failing suite test: environment"
    return "needs_human", "suite tests: " + ", ".join(
        f"{k} {n}" for k, n in sorted(vs.items()))


# --- items ---------------------------------------------------------------------------

def _tables():
    from offload.engine import report
    return (("omp", "f90", report.MATRIX, report.AUDIT),
            ("omp", "c", report.C_MATRIX, report.C_AUDIT),
            ("acc", "f90", report.ACC_MATRIX, report.ACC_AUDIT))


OLDER_DOCS = ("rocm-clang-openmp-status",)   # Clang 20 for AFAR 24


def mismatch_items() -> list[Item]:
    from offload.engine import report
    from offload.engine.confirm import programs as P
    out = []
    claims = report.load_claims(report.CLAIMS)
    for model, lang, results, audit in _tables():
        table = report.build_table(results, audit=audit)
        for m in report.compare_claims(table, claims):
            claim = m.claimed.split(" ", 1)[0]
            key = (f"mismatch:{model}:{lang}:{m.toolchain}:{m.atom}:"
                   f"{m.version}:{m.source}:{claim}")
            info = {"model": model, "lang": lang, "toolchain": m.toolchain,
                    "atom": m.atom, "version": m.version,
                    "claimed": m.claimed, "claim": claim,
                    "measured": m.measured, "source": m.source,
                    "url": m.url, "quote": m.quote, "page": m.page,
                    "spec_version": m.spec_version, "general": m.general,
                    "language": m.language,
                    "cross_language": m.lang != "c" and
                    m.language == "C/C++",
                    "older_doc": m.source in OLDER_DOCS,
                    "confound": m.confound,
                    "oracle_unaudited": m.oracle_unaudited,
                    "cells": [list(c) for c in m.cells]}
            # Spot check: a failure inside a target region of a
            # construct the vendor documents as unsupported there
            lim, doc = {}, ""
            for pid in sorted({c[0] for c in m.cells}):
                prog = P.catalog_program(pid)
                if prog is None:
                    continue
                hit, page = device_limits(m.toolchain, lang, prog.source,
                                          m.atom)
                if hit:
                    lim[pid], doc = hit, page
            info["device_unsupported"] = lim
            info["device_unsupported_doc"] = doc
            out.append(Item("mismatch", key, info))
    return out


def flag_items() -> list[Item]:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ompvv_compare", ROOT / "tools" / "derive" / "ompvv_compare.py")
    oc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oc)
    import csv
    out = []
    for lang in ("f90", "c"):
        rows, flags, narrow, _, _ = oc.compare(lang)
        table = list(csv.DictReader(open(oc.PATHS[lang][1])))
        for f in flags:
            xn = int(f["xnack"])
            info = dict(f, lang=lang)
            tests = narrow.get((f["atom"], f["toolchain"], xn), [])
            info["suite_tests"] = [list(t) for t in tests]
            info["our_programs"] = sorted(
                {r["program_id"] for r in table
                 if r["version"] == f["version"] and r["atom"] == f["atom"]
                 and r["toolchain"] == f["toolchain"]
                 and r["xnack"] == str(xn) and r["legal"] == "1"
                 and (r.get("scope") or "device") == "device"})
            key = (f"flag:{lang}:{f['version']}:{f['atom']}:"
                   f"{f['toolchain']}:{f['mode']}:{f['flag']}")
            out.append(Item("flag", key, info))
    return out


def item_cases(item: Item) -> list[tuple[str, str, str, int]]:
    """(kind, ident, toolchain, xnack) of the cells an item is about."""
    if item.kind == "mismatch":
        return [("catalog", pid, tc, int(x))
                for pid, tc, x, _ in item.info["cells"]]
    f = item.info
    if f["flag"] == "ours_bad_suite_passes":
        return [("catalog", pid, f["toolchain"], int(f["xnack"]))
                for pid in f["our_programs"]]
    return [("ompvv", path, f["toolchain"], int(f["xnack"]))
            for path, st in f["suite_tests"] if st != "pass"]


def run(items: list[Item], ctx=None, log=None) -> list[Item]:
    """Decide every case offline (stored evidence) and each item's
    disposition; agent decisions (catalog/triage_27b.yaml) are applied to
    needs_human items."""
    from offload.engine.confirm import engine as EN
    from offload.engine.confirm import ingest as I
    if ctx is None:
        from offload.engine.confirm import collectors as C
        from offload.engine.confirm.store import Store
        ctx = C.Context(I.stored_index(), Store(), allow_run=False)
    cache: dict = {}
    for n, it in enumerate(items):
        for kind, ident, tc, x in item_cases(it):
            arch, mode = I._mode(tc, x)
            k = (kind, ident, tc, mode)
            if k not in cache:
                row = ctx.index.get(kind, ident, tc, mode)
                if row is None:
                    cache[k] = {"case_id": f"{kind}:{ident}:{tc}:{arch}:"
                                f"{mode}", "toolchain": tc, "arch": arch,
                                "mode": mode, "outcome": "missing",
                                "reason": "no stored row", "verdict":
                                "needs_human", "rule": "none", "why":
                                "no stored row", "findings": []}
                else:
                    case = I.case_of_row(row)
                    cache[k] = slim(EN.confirm(case, ctx))
                    if cache[k]["verdict"] == "needs_human":
                        cache[k]["candidates"] = candidates(case, row)
            it.cases.append(cache[k])
        if it.kind == "mismatch":
            it.disposition, it.basis = mismatch_disposition(it.info,
                                                            it.cases)
        else:
            it.disposition, it.basis = flag_disposition(it.info, it.cases)
        if log and n % 25 == 0:
            log(f"{n}/{len(items)} items")
    apply_decisions(items)
    return items


def candidates(case, row) -> list[str]:
    """Findings whose signature an undecided case has (the confirmer
    dedupes bug verdicts only; for an agent deciding a needs_human case
    the existing findings it matches are the first thing to check)."""
    from offload.engine.confirm import findings as FI
    hits = FI.dedupe(case.toolchain, case.program.lang, case.outcome,
                     case.reason, case.program.text or "",
                     case.program.ident, case.mode, arch=case.arch,
                     output=(row.extra or {}).get("stderr_tail", ""),
                     related=True, opt=case.opt)
    return [f"{h['kind']}:{h['file']}" for h in hits]


def decisions() -> dict:
    if not DECISIONS.is_file():
        return {"decisions": [], "spot_checks": []}
    d = yaml.safe_load(DECISIONS.read_text()) or {}
    d.setdefault("decisions", [])
    d.setdefault("spot_checks", [])
    return d


def _ident(case_id: str) -> str:
    return case_id.split(":", 2)[1] if case_id.count(":") >= 2 else case_id


def _decision_hits(d: dict, it: Item) -> bool:
    """A decision names an item by `key` (an fnmatch pattern), or
    by `programs` (any of the item's cases is of one of them) with
    optional `toolchains` (the item's toolchain, gfx90a twins included)
    and `kind`."""
    if d.get("kind") and d["kind"] != it.kind:
        return False
    k = d.get("key")
    if k:
        from fnmatch import fnmatchcase
        return fnmatchcase(it.key, k)
    progs = set(d.get("programs") or ())
    if not progs or not {_ident(c["case_id"]) for c in it.cases} & progs:
        return False
    tcs = d.get("toolchains")
    if tcs:
        from offload.engine.toolchains import base_name
        return base_name(it.info.get("toolchain", "")) in tcs
    return True


def apply_decisions(items: list[Item]) -> None:
    """An agent decision applies to a needs_human item (first match in
    file order; see _decision_hits)."""
    ds = decisions()["decisions"]
    for it in items:
        for d in ds:
            if it.disposition != "needs_human" and not d.get("override"):
                continue
            if _decision_hits(d, it):
                if it.disposition != "needs_human":
                    # an agent correction of a computed disposition (never
                    # of a cell verdict), with the computed one kept
                    d_reason = (f"{d['reason']} (computed: {it.disposition}"
                                f"; {it.basis})")
                else:
                    d_reason = d["reason"]
                it.disposition = d["disposition"]
                it.basis = d_reason
                it.decided_by = "agent"
                if d.get("finding"):
                    it.info["finding"] = d["finding"]
                if d.get("upstream"):
                    it.info["upstream"] = d["upstream"]
                break


def spot_sample(items: list[Item], frac: float = 0.1, seed: int = 27
                ) -> dict[str, list[str]]:
    """A random `frac` (at least one) of the decided cases of each verdict
    class, by case id (seeded: the same sample each run)."""
    by: dict = defaultdict(set)
    for it in items:
        for c in it.cases:
            if c["verdict"] != "needs_human":
                by[c["verdict"]].add(c["case_id"])
    rnd = random.Random(seed)
    out = {}
    for v in sorted(by):
        ids = sorted(by[v])
        k = max(1, round(len(ids) * frac))
        out[v] = sorted(rnd.sample(ids, k))
    return out


def save(items: list[Item], path: Path = OUT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for it in items:
            f.write(json.dumps(it.to_dict(), default=str) + "\n")


def load(path: Path = OUT) -> list[Item]:
    return [Item(**json.loads(line)) for line in path.read_text().splitlines()
            if line.strip()]


# --- rendering (data/reports/triage-2026-10.md, docs/upstream.md) -------

def _md(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _short(atom: str) -> str:
    return atom.split(".", 1)[1] if atom.startswith(("omp.", "acc.")) else atom


def _ver(v) -> str:
    v = int(v)
    return f"{v // 10}.{v % 10}"


def _finding(it: Item) -> str:
    fs = sorted({f for c in it.cases for f in c.get("findings") or ()})
    if it.info.get("finding"):
        fs = [it.info["finding"]] + [f for f in fs
                                      if f != it.info["finding"]]
    return ", ".join(f"`{Path(f).name}`" for f in fs)


def render_tables(items: list[Item], sample: dict, checks: dict) -> str:
    """The Markdown of the section (generated)."""
    ms = [i for i in items if i.kind == "mismatch"]
    fl = [i for i in items if i.kind == "flag"]
    L = []
    for name, group, classes in (("Claim mismatches", ms, MISMATCH_CLASSES),
                                 ("omp_vv flags", fl, FLAG_CLASSES)):
        c = Counter(i.disposition for i in group)
        a = Counter(i.disposition for i in group if i.decided_by == "agent")
        L += [f"### {name}: {len(group)} by disposition", "",
              "| disposition | items | of which decided by an agent |",
              "|---|---|---|"]
        L += [f"| {k} | {c[k]} | {a.get(k, 0)} |" for k in classes if c[k]]
        other = sorted(set(c) - set(classes))
        L += [f"| {k} | {c[k]} | {a.get(k, 0)} |" for k in other]
        L.append("")
    # spot check
    sp = checks.get("spot") or []
    agree = sum(1 for s in sp if s.get("agree"))
    L += ["### Spot check of the confirmer's decided cases", "",
          f"A seeded random 10% (at least one) of the decided cases of each "
          f"verdict class ({sum(len(v) for v in sample.values())} cases); "
          f"agreement {agree}/{len(sp)}.", "",
          "| verdict class | cases sampled |", "|---|---|"]
    L += [f"| {k} | {len(v)} |" for k, v in sorted(sample.items())]
    L.append("")
    L += ["### Mismatches (one line each)", "",
          "| model | lang | compiler | atom | version | claimed [source] | "
          "measured | disposition | by | basis | finding |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i in sorted(ms, key=lambda i: (i.info["model"], i.info["lang"],
                                       i.info["toolchain"], i.info["atom"],
                                       int(i.info["version"]),
                                       i.info["source"])):
        f = i.info
        L.append(f"| {f['model']} | {f['lang']} | {f['toolchain']} | "
                 f"`{_short(f['atom'])}` | {_ver(f['version'])} | "
                 f"{_md(f['claimed'])} | {_md(f['measured'])[:90]} | "
                 f"{i.disposition} | {i.decided_by} | "
                 f"{_md(i.basis)[:160]} | {_finding(i)} |")
    L += ["", "### omp_vv flags (one line each)", "",
          "| lang | version | atom | compiler | mode | flag | ours | cases "
          "| disposition | by | basis |", "|---|---|---|---|---|---|---|---|"
          "---|---|---|"]
    for i in sorted(fl, key=lambda i: (i.info["lang"], i.info["atom"],
                                       i.info["toolchain"],
                                       str(i.info["version"]))):
        f = i.info
        cases = ", ".join(sorted({Path(_ident(c["case_id"])).name
                                  for c in i.cases}))
        L.append(f"| {f['lang']} | {_ver(f['version'])} | "
                 f"`{_short(f['atom'])}` | {f['toolchain']} | {f['mode']} | "
                 f"{f['flag']} | {f['ours']} | {_md(cases)[:120]} | "
                 f"{i.disposition} | {i.decided_by} | "
                 f"{_md(i.basis)[:200]} |")
    over = [i for i in ms if i.disposition == "doc_overclaims"]
    under = [i for i in ms if i.disposition == "doc_understates"]
    L += ["", "### Documentation overclaims (doc page and version)", "",
          "The vendor document claims support; the compiler says it does "
          "not implement the form (or ignores it).", "",
          "| compiler | lang | atom | version | document (section) [edition]"
          " | quote |", "|---|---|---|---|---|---|"]
    for i in sorted(over, key=lambda i: (i.info["toolchain"],
                                         i.info["atom"])):
        f = i.info
        L.append(f"| {f['toolchain']} | {f['lang']} | `{_short(f['atom'])}`"
                 f" | {_ver(f['version'])} | {_md(f.get('page', ''))} | "
                 f"{_md(f['quote'])[:120]} |")
    L += ["", "### Documentation understates (the vendor says unsupported; "
          "it runs correctly on the device)", "",
          "| compiler | lang | atom | version | document (section) [edition]"
          " | quote |", "|---|---|---|---|---|---|"]
    for i in sorted(under, key=lambda i: (i.info["toolchain"],
                                          i.info["atom"])):
        f = i.info
        L.append(f"| {f['toolchain']} | {f['lang']} | `{_short(f['atom'])}`"
                 f" | {_ver(f['version'])} | {_md(f.get('page', ''))} | "
                 f"{_md(f['quote'])[:120]} |")
    return "\n".join(L) + "\n"


STATUSES = ("already_fixed", "filed", "changed_upstream", "not_filed")


def upstream_status(path: Path | None = None) -> dict:
    """catalog/upstream_status.yaml, checked: every test has a known
    status, a defect text, and a filed or fixed test its issue/PR refs."""
    d = yaml.safe_load(Path(path or UPSTREAM_STATUS).read_text()) or {}
    if d.get("version") != 1:
        raise ValueError("upstream_status: unknown version")
    seen = set()
    for df in d.get("defects") or ():
        for tst in df.get("tests") or ():
            if tst.get("status") not in STATUSES:
                raise ValueError(f"upstream_status: {tst.get('path')}: "
                                 f"status {tst.get('status')!r}")
            if not tst.get("defect"):
                raise ValueError(f"upstream_status: {tst['path']}: no "
                                 "defect text")
            if tst["status"] in ("already_fixed", "filed") and \
                    not tst.get("refs"):
                raise ValueError(f"upstream_status: {tst['path']}: "
                                 f"{tst['status']} without an issue or PR")
            if tst["path"] in seen:
                raise ValueError(f"upstream_status: {tst['path']} twice")
            seen.add(tst["path"])
    return d


def _status_text(tst: dict) -> str:
    refs = ", ".join(f"[{r['text']}]({r['url']})" if r.get("url")
                     else r["text"] for r in tst.get("refs") or ())
    note = tst.get("note", "")
    st = tst["status"]
    if st == "already_fixed":
        return f"Already fixed: {refs}" + (f" ({note})" if note else "")
    if st == "filed":
        return f"Filed: {refs}" + (f" ({tst['date']})" if tst.get("date")
                                   else "") + (f"; {note}" if note else "")
    if st == "changed_upstream":
        return "Changed upstream: " + note + (f" ({refs})" if refs else "")
    return "Not filed: " + note


def _paths_cell(paths: list[str]) -> str:
    """a/b/x.c, a/b/x.F90 -> a/b/x.c, .F90 (same stem)."""
    out = [paths[0]]
    stem = paths[0].rsplit(".", 1)[0]
    for p in paths[1:]:
        out.append("." + p.rsplit(".", 1)[1] if p.rsplit(".", 1)[0] == stem
                   else p)
    return ", ".join(out)


def render_upstream(items: list[Item], status: dict | None = None) -> str:
    """docs/upstream.md: the suspected omp_vv test bugs (the
    agent's test_bug decisions) and their filing status upstream
    (catalog/upstream_status.yaml): one table row per test file (files
    with the same defect and status share a row), then one section per
    defect with the decision's text and where the tests fail here."""
    st = upstream_status() if status is None else status
    tests: dict = defaultdict(list)
    for i in items:
        if i.kind == "flag" and i.disposition == "test_bug":
            for c in i.cases:
                tests[_ident(c["case_id"])].append(i)
    defect_of = {}
    for df in st.get("defects") or ():
        for tst in df["tests"]:
            defect_of[tst["path"].replace("/", "_")] = df["id"]
    missing = sorted(set(tests) - set(defect_of))
    if missing:
        raise ValueError("test_bug tests without a filing status in "
                         "catalog/upstream_status.yaml: " + ", ".join(missing))
    cp, ac = st["corpus"], st["active"]
    if cp["repo"] == ac["repo"]:
        # The corpus is a clone of the active repository
        where = (f"Our {cp['path']} is a clone of the active repository "
                 f"{ac['url']} at {cp['commit']} ({cp['date']}; "
                 f"{cp['note']}), checked on {ac['checked']}.")
    else:
        where = (f"Our {cp['path']} is the archived {cp['repo']} "
                 f"({cp['note']}); the active repository is {ac['url']}, "
                 f"checked on {ac['checked']}.")
    L = ["# Suspected omp_vv test bugs: filing status", "",
         f"{st['decision']} {where}", "",
         "| Test | Defect (spec) | Status upstream |", "|---|---|---|"]
    for df in st.get("defects") or ():
        rows: list = []
        for tst in df["tests"]:
            key = (tst["defect"], _status_text(tst), tst.get("where", ""))
            if rows and rows[-1][0] == key:
                rows[-1][1].append(tst["path"])
            else:
                rows.append((key, [tst["path"]]))
        for (defect, status_text, where), paths in rows:
            cell = _paths_cell(paths) + (f" {where}" if where else "")
            L.append(f"| {cell} | {defect} | {status_text} |")
    L += ["", " ".join(st.get("observed", "").split()), "",
          "Generated by `tools/confirm.py triage` from "
          "catalog/upstream_status.yaml (the filing status) and the agent "
          "decisions in catalog/triage_27b.yaml (the defects as found, "
          "below).", ""]
    for df in st.get("defects") or ():
        ids = [tst["path"].replace("/", "_") for tst in df["tests"]]
        its = [i for p in ids for i in tests.get(p, [])]
        L += [f"## {df['title']}", "",
              "Test files: " + ", ".join(f"`{tst['path']}`"
                                         for tst in df["tests"]) + ".", ""]
        ups = []
        for i in its:
            u = i.info.get("upstream")
            if u and u not in ups:
                ups.append(u)
        L += [u + "\n" for u in ups]
        if its:
            tcs = sorted({c.get("toolchain") or i.info.get("toolchain", "")
                          for i in its for c in i.cases
                          if _ident(c["case_id"]) in ids})
            L += [f"Compilers where the tests fail here: {', '.join(tcs)}. "
                  f"Flags: " + ", ".join(sorted({i.key for i in its})), ""]
        elif df.get("observed"):
            # A drafted defect no flag case covers
            L += [" ".join(df["observed"].split()), ""]
        else:
            L += ["No failing case here.", ""]
    return "\n".join(L) + "\n"
