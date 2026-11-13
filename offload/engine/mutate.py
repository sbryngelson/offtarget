"""Oracle mutation audit: does a program's check depend on its atom?

``neutralise(prog)`` builds the mutant: the program with the construct,
clause or modifier named by ``prog.primary_atom`` removed, under the id
``<id>-mutant``. ``audit`` runs the original and the mutant on each
toolchain in copy mode (``HSA_XNACK=0``; 1 for programs needing zero-copy)
through ``harness.run_program`` with ``repeats=1``. ``summarise`` gives a
per-atom verdict.
Directives are commented out with their end directive and clauses are
deleted. For modifiers, the removal that still parses and loses the fewest
other atoms is used. ``REPLACEMENTS`` lists forms swapped for a weaker one,
``NO_MUTATION`` the atoms without a mutant. Probe and detector code
(``INFRA_VARS``) is never mutated. OpenACC and C programs use the same rules.
``MutantResult.status`` is ``killed``, ``survived``, ``inconclusive`` or
``not_applicable``; a mutant that breaks a rule is not run."""
from __future__ import annotations

import dataclasses
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Sequence

from offload.engine import grammar as G
from offload.engine.catalog import (base_name, default_grammar, default_skeleton,
                                directive_atom, model_of, slice_atoms)
from offload.engine.gen import Program, generate
from offload.engine.grammar import GrammarError, Directive, parse_directive
from offload.engine.harness import Outcome, Result, run_program
from offload.engine.rules import ProgramError, parse_program
from offload.engine.run_matrix import for_version
from offload.engine.toolchains import TOOLCHAINS


class MutationError(Exception):
    """A program whose primary atom cannot be removed as the rules say."""


# --- atoms without a mutation ------------------------------------------------------

REQUIRES_CLAUSES = ("atomic_default_mem_order", "reverse_offload",
                    "unified_address", "unified_shared_memory",
                    "dynamic_allocators", "self_maps", "device_safesync")

_REQUIRES_WHY = ("declarative requires clause: removing it leaves a program "
                 "with nothing to test (the requirement only constrains the "
                 "compilation unit; the program is observable=False)")


# Forms whose deletion leaves a default that is the same program, or one
# that still does what the form does, and for which no weaker form exists
# (the generated program uses the default value): no mutation.
EQUIVALENT_DEFAULTS: dict[str, str] = {
    "omp.clause.schedule.nonmonotonic":
        "nonmonotonic is the default modifier of the dynamic kind the "
        "program uses (5.0 and later)",
    "omp.clause.order.unconstrained":
        "the program has no schedule clause, so its loop schedule is not "
        "reproducible with or without the modifier (with "
        "schedule(static) unconstrained would remove reproducibility, a "
        "relaxation no run can show)",
    "omp.clause.ordered.n":
        "without n the ordered clause behaves as if n were the collapse "
        "value, 1 on the program's one-loop nest",
    "omp.clause.reduction.default":
        "default is the default reduction-modifier",
    "omp.clause.linear.val":
        "val is the default linear-modifier of a non-reference list item",
    "omp.clause.default.all": "all is the default variable category",
    "omp.clause.defaultmap.default":
        "defaultmap(default) is the behaviour without the clause",
    "omp.clause.nowait.do_not_synchronize":
        "nowait(.true.) is nowait (the argument defaults to true)",
    "omp.clause.nogroup.do_not_synchronize":
        "nogroup(.true.) is nogroup (the argument defaults to true)",
    "omp.clause.replayable.replayable_expression":
        "replayable(.true.) is replayable (the argument defaults to true)",
    "omp.clause.indirect.invoked_by_fptr":
        "indirect(.true.) is indirect (the argument defaults to true)",
    "omp.clause.transparent.impex_type":
        "transparent(omp_impex) is transparent (the default impex type)",
    "omp.clause.uses_allocators.memspace":
        "the program names omp_default_mem_space, the default memory space",
    "omp.clause.default.none":
        "default(none) only requires every variable to be listed: a "
        "compile-time restriction with no run-time effect; its oracle is "
        "the illegal variant of rule default-dsa-001",
    "omp.clause.map.ref_ptr_ptee":
        "without a ref-modifier the map applies to the referring pointer "
        "and its referenced pointee (6.0 §7.9.6), i.e. ref_ptr_ptee",
    "omp.clause.device.device_num":
        "device_num is the default device-modifier (device(n) is "
        "device(device_num: n)); deleting the clause instead tests the "
        "device clause, audited as omp.clause.device",
}

_DNM_WHY = ("a directive-name modifier restricts the clause to the named "
            "constituent; deleting it applies the clause to every "
            "constituent that accepts it, which contains the modifier's "
            "effect (the generated program names the constituent that takes "
            "the clause), and no weaker form exists")


# Directive-name modifiers whose deletion is a mutation: if(parallel: x)
# with x false leaves the region on the device; if(x) sends it to the host.
DNM_MUTATED = frozenset({"omp.clause.if.directive_name"})


def _no_mutation() -> dict[str, str]:
    out = {"omp.directive.requires": (
        "declarative directive: removing requires leaves a program with "
        "nothing to test (its clauses are the atoms; observable=False)")}
    for v in (50, 52, 60):
        for atom in slice_atoms(v):
            parts = atom.split(".")
            if parts[1] == "clause" and parts[2] in REQUIRES_CLAUSES:
                out[atom] = _REQUIRES_WHY
            elif parts[-1] == "directive_name" and atom not in DNM_MUTATED:
                out[atom] = _DNM_WHY
    for atom, why in EQUIVALENT_DEFAULTS.items():
        out[atom] = "equivalent default: " + why
    return dict(sorted(out.items()))


NO_MUTATION: dict[str, str] = _no_mutation()

# Forms whose deletion leaves a default that still does what the form does
# (map(to: a) -> map(a) is tofrom): the form is REPLACED, per directive
# ("*" = any other directive), by one without the behaviour; None deletes
# the clause carrying the form, KEEP leaves it (no weaker form exists there).
KEEP = "keep"
# The iterator's range made empty ("If the iterator value set is empty then
# the effect is as if the list item was not specified", 5.2 §3.2.6, 6.0
# §5.2.6): the clause stays, the items it generates go, k is never unset.
EMPTY_RANGE = "empty range"
_CATEGORY = ("deleting the variable category applies the behaviour to all "
             "categories, which include it; a disjoint category moves it off "
             "the tested variables")
REPLACEMENTS: dict[str, tuple[dict, str]] = {
    "omp.clause.map.to": (
        {"target": "delete", "*": "alloc"},
        "on target the map type is deleted (tofrom: the program checks that "
        "the region's write of the to-mapped array does not come back, copy "
        "mode); elsewhere map(to: x) without its transfer is map(alloc: x) "
        "(deleting the type gives tofrom on target data or to on enter "
        "data, which still copies to the device)"),
    "omp.clause.map.from": (
        {"target exit data": "release", "*": "alloc"},
        "map(from: x) without its transfer is alloc (target, target data) or "
        "release (exit data); deleting the type gives tofrom or from"),
    "omp.clause.map.tofrom": (
        {"*": "alloc"},
        "tofrom is the default map type, so deleting it changes nothing; "
        "alloc keeps the mapping without either transfer"),
    "omp.clause.map.delete": (
        {"*": "release"},
        "delete forces the reference count to zero, release only decrements "
        "it; deleting the type gives from, which also releases"),
    "omp.clause.map.alloc": (
        {"target enter data": None, "target data": None, "*": KEEP},
        "alloc is the weakest map type: its clause is deleted where it "
        "allocates storage for later regions (target enter data, target "
        "data) and kept on target regions (deleting it there gives tofrom, "
        "which still allocates)"),
    "omp.clause.map.storage": (
        {"target enter data": None, "target data": None, "*": KEEP},
        "storage is the weakest map type (alloc/release): as for alloc"),
    "omp.clause.map.release": (
        {"*": None},
        "release is the weakest exit map type: its clause is deleted "
        "(deleting the type gives from, which also releases)"),
    "omp.clause.defaultmap.scalar": ({"*": "aggregate"}, _CATEGORY),
    "omp.clause.defaultmap.aggregate": ({"*": "scalar"}, _CATEGORY),
    "omp.clause.defaultmap.allocatable": ({"*": "scalar"}, _CATEGORY),
    "omp.clause.defaultmap.pointer": ({"*": "scalar"}, _CATEGORY),
    "omp.clause.default.scalar": ({"*": "aggregate"}, _CATEGORY),
    "omp.clause.default.aggregate": ({"*": "scalar"}, _CATEGORY),
    "omp.clause.default.allocatable": ({"*": "scalar"}, _CATEGORY),
    "omp.clause.default.pointer": ({"*": "scalar"}, _CATEGORY),
    # Defaultmap(to: all) -> to: scalar leaves the arrays
    # tofrom
    "omp.clause.defaultmap.all": ({"*": "scalar"}, _CATEGORY),
    # an orphaned loop must carry bind (5.2 §11.7 p.257, 6.0 §13.8 p.424:
    # loop-nesting-001), so removing it is illegal; bind(thread) is the
    # conforming form without the team's or league's sharing
    "omp.clause.bind.parallel": (
        {"*": "thread"},
        "an orphaned loop must have a bind clause; thread binds it to the "
        "encountering thread, so each thread runs every iteration"),
    "omp.clause.bind.teams": (
        {"*": "thread"},
        "an orphaned loop must have a bind clause; thread binds it to the "
        "encountering thread, so each team runs every iteration"),
    # severity(fatal) is the default, so deleting it is the same program;
    # warning lets the compilation go on
    "omp.clause.severity.fatal": (
        {"*": "warning"},
        "fatal is the default sev-level, so deleting it changes nothing; "
        "warning shows the message and lets the compilation go on"),
}
REPLACEMENTS["omp.clause.map.ref_ptee"] = (
    {"*": "ref_ptr"},
    "ref_ptee maps only the pointee; ref_ptr maps only the pointer, so the "
    "pointee's data is not mapped (deleting the modifier maps both, a "
    "superset)")
REPLACEMENTS["omp.clause.map.ref_ptr"] = (
    {"*": "ref_ptee"},
    "ref_ptr maps only the pointer; ref_ptee maps only the pointee, so no "
    "device pointer is attached (deleting the modifier maps both, a "
    "superset)")
for _c in ("depend", "to", "from", "map"):
    REPLACEMENTS[f"omp.clause.{_c}.iterator"] = (
        {"*": EMPTY_RANGE},
        "an empty range (k = 1:0) removes exactly the list items the "
        "iterator generates and keeps the clause; deleting the iterator "
        "alone would leave k unset")
for _t in ("in", "out", "inout", "inoutset", "mutexinoutset", "depobj"):
    REPLACEMENTS[f"omp.clause.depend.{_t}"] = (
        {"*": None},
        "the dependence is deleted with its clause: 6.0's depend(x) without "
        "a type is inout, which still orders the tasks, and no type orders "
        "less than the one tested without adding another dependence")

# Semantic atoms (catalog/omp/semantic_atoms.yaml): no directive
# carries them, so nothing can be deleted. The mutant is the program with
# the behaviour the atom specifies replaced by the competing one: `clause`
# is added to every (unprotected) directive named `directive`.
SEMANTIC_MUTATIONS: dict[str, tuple[str, str, str]] = {
    "omp.clause.defaultmap.character": (
        "target", "firstprivate(ch, s)",
        "the character variables are made firstprivate, as an integer "
        "scalar is implicitly (what treating Fortran character as a scalar "
        "variable would give): the device's writes to ch and s no longer "
        "come back"),
}

# Clauses whose removal makes other constructs non-conforming: those are
# commented out too (atom -> directive atom).
COMPANIONS: dict[str, str] = {
    "omp.clause.ordered": "omp.directive.ordered",
    "omp.clause.reduction.inscan": "omp.directive.scan",
}

# Variables that report where the program ran (not the atom): never removed
# from a clause.
INFRA_VARS = frozenset({"host_flag", "on_dev", "zc"})

# Data-sharing clauses: deleted under default(none), their list items are
# listed in shared(...) instead (the closest conforming program without
# the privatisation).
DSA_CLAUSES = frozenset({"private", "firstprivate", "lastprivate",
                         "reduction", "linear",
                         # Induction is a data-sharing clause too;
                         # deleted under default(none) it left x unlisted,
                         # an illegal mutant (default-dsa-001)
                         "induction"})

# Directives that need a clause (a motion clause, an extended list): when
# the mutation removes the last one, the directive is commented out.
NEEDS_A_CLAUSE = frozenset({"target update", "declare target",
                            "declare"})  # declare: OpenACC

# OpenACC: data clauses whose deletion leaves the implicit copy
# of the array (3.4 §2.6.2: an aggregate in no data clause is copy), which
# still transfers it; the clause is renamed to create, which keeps the
# device copy and drops the transfers (3.4 §2.7.10)
ACC_RENAMES: dict[str, tuple[str, str]] = {
    f"acc.clause.{c}": ("create", f"{c} without its transfers is create: "
                        "deleting it leaves the implicit copy of the array "
                        "(3.4 §2.6.2), which transfers it as well")
    for c in ("copy", "copyin", "copyout")}
ACC_RENAMES["acc.clause.link"] = (
    "create", "declare link allocates the device copy only when a data "
    "clause names the variable (3.4 §2.13.3), so the compute construct's "
    "copyin transfers it; declare create allocates it for the whole "
    "program, so the copyin finds it present and transfers nothing "
    "(deleting link leaves a declare without a clause, and the routine's "
    "use of the global then needs a declare)")
# feature atoms whose argument is replaced by the value its absence means
ACC_ARG_REPLACE: dict[str, tuple[str, str]] = {
    "acc.clause.self.condition": (
        "cond_true", "self without a condition is self(.true.) (3.4 "
        "§2.5.7); CCE 19 rejects self without an argument and with a "
        "literal argument, so the condition is replaced by the program's "
        "variable cond_true, which is .true.")}
# atomic-clauses removed with their construct (see the module docstring)
ACC_CONSTRUCT_CLAUSES = frozenset({"acc.clause.read", "acc.clause.write",
                                   "acc.clause.capture"})
# OpenACC semantic atoms (catalog/acc/semantic_atoms.yaml): the clause that
# gives the variable the competing attribute
SEMANTIC_MUTATIONS_ACC: dict[str, tuple[str, str, str]] = {
    "acc.clause.firstprivate.implicit_scalar": (
        "serial", "copy(x)",
        "x is made copy, so the region's write reaches the host"),
    "acc.clause.copy.implicit_kernels_scalar": (
        "kernels", "create(x)",
        "x is given a device-only copy (create), so the device's write "
        "does not reach the host (copy mode)"),
}


# --- the directives of a source, with positions -----------------------------------

_SENT = re.compile(r"^(\s*)!\$omp", re.I)
_SENTS = {"omp": _SENT, "acc": re.compile(r"^(\s*)!\$acc", re.I)}
# The OpenACC C programs' sentinel too (#pragma acc)
_C_PRAGMA = re.compile(r"^(\s*)#\s*pragma\s+(?:omp|acc)\b")


def _sent(version: int, lang: str = "f90") -> re.Pattern:
    return _C_PRAGMA if lang == "c" else _SENTS[model_of(version)]


def _glang(lang: str) -> str:
    """The parse_directive language name."""
    return "c" if lang == "c" else "fortran"


@dataclass
class _Line:
    idx: int        # physical line index (0-based)
    cstart: int     # content start column
    cend: int       # content end column (before a trailing '&' / comment)


@dataclass
class _Dir:
    first: int
    last: int
    lines: list[_Line]
    text: str        # the directive's physical text (for parse_directive)
    logical: str     # contents joined with one blank
    pos: list        # logical index -> (line idx, col) or None (the blank)
    d: Directive
    end: "_Dir | None" = None
    protected: bool = False
    lang: str = "f90"


def _scan(lines: list[str], version: int, lang: str = "f90") -> list[_Dir]:
    if lang == "c":
        return _scan_c(lines, version)
    out: list[_Dir] = []
    k = 0
    _SENT = _sent(version)
    while k < len(lines):
        if not _SENT.match(lines[k]):
            k += 1
            continue
        first, parts = k, []
        while True:
            raw = lines[k]
            m = _SENT.match(raw)
            if m is None:
                raise MutationError(f"line {k + 1}: continuation is not a "
                                    "directive line")
            c = m.end()
            if parts:  # continuation: optional '&' after the sentinel
                while c < len(raw) and raw[c] in " \t":
                    c += 1
                if raw[c:c + 1] == "&":
                    c += 1
            rest = G._strip_bang_comment(raw[c:])
            end = c + len(rest.rstrip())
            cont = raw[:end].endswith("&")
            if cont:
                end -= 1
            while c < end and raw[c] in " \t":
                c += 1
            while end > c and raw[end - 1] in " \t":
                end -= 1
            parts.append(_Line(k, c, end))
            if not cont:
                break
            k += 1
        text = "\n".join(lines[first:k + 1])
        logical, pos = "", []
        for n, ln in enumerate(parts):
            if n:
                logical += " "
                pos.append(None)
            seg = lines[ln.idx][ln.cstart:ln.cend]
            logical += seg
            pos += [(ln.idx, ln.cstart + i) for i in range(len(seg))]
        out.append(_Dir(first, k, parts, text, logical, pos,
                        parse_directive(text, "fortran", version)))
        k += 1
    return out


def _scan_c(lines: list[str], version: int) -> list[_Dir]:
    """The ``#pragma omp`` directives of a C source, with ``\\``
    continuations. An ``end declare target`` is a directive of
    its own here (``d.end`` is set on it, so it is handled as an end)."""
    out: list[_Dir] = []
    k = 0
    while k < len(lines):
        m = _C_PRAGMA.match(lines[k])
        if not m:
            k += 1
            continue
        first, parts = k, []
        while True:
            raw = lines[k]
            c = m.end() if k == first else 0
            body = raw.rstrip()
            cont = body.endswith("\\")
            end = len(body) - (1 if cont else 0)
            while c < end and raw[c] in " \t":
                c += 1
            while end > c and raw[end - 1] in " \t":
                end -= 1
            parts.append(_Line(k, c, end))
            if not cont or k + 1 >= len(lines):
                break
            k += 1
        text = "\n".join(lines[first:k + 1])
        logical, pos = "", []
        for n, ln in enumerate(parts):
            if n:
                logical += " "
                pos.append(None)
            seg = lines[ln.idx][ln.cstart:ln.cend]
            logical += seg
            pos += [(ln.idx, ln.cstart + i) for i in range(len(seg))]
        d = parse_directive(text, "c", version)
        if d.name == "end declare target":
            d = dataclasses.replace(d, end=True)
        out.append(_Dir(first, k, parts, text, logical, pos, d, lang="c"))
        k += 1
    return out


def _pair(dirs: list[_Dir], source: str, version: int) -> None:
    """Attach end directives (from parse_program's pairing) and mark the
    probe and shared-memory detector as protected."""
    lang = dirs[0].lang if dirs else "f90"
    tree = parse_program(source, version, lang="c" if lang == "c" else None)
    begins = [x for x in dirs if not x.d.end]
    by_line = {x.first + 1: x for x in dirs}
    if len(begins) != len(tree.directives):
        raise MutationError("directive count differs from parse_program")
    for x, a in zip(begins, tree.assoc):
        if x.first + 1 != a.line:
            raise MutationError(f"directive at line {x.first + 1} does not "
                                f"match parse_program's line {a.line}")
        if a.end_line is not None and a.end_line != a.line:
            # a loop construct without its end directive ends at its END DO
            # (OpenACC programs write none), which is no directive
            x.end = by_line.get(a.end_line)
            if x.end is not None and not x.end.d.end:
                x.end = None
    lines = source.splitlines()
    for x, a in zip(begins, tree.assoc):
        if x.d.name == "declare target" and x.d.args == ["on_dev"]:
            x.protected = True
        elif x.d.name in ("target", "serial") and x.end is not None:
            inner = {s.strip() for s in lines[x.last + 1:x.end.first]}
            if inner & {"on_dev = 1", "zc(1) = 1"}:
                x.protected = True
        elif x.lang == "c" and x.d.name == "target" and a.end_line:
            # C: the block statement of the target region
            inner = {s.strip() for s in lines[x.last + 1:a.end_line]}
            if inner & {"on_dev = 1;", "zc[0] = 1;"}:
                x.protected = True


# --- clause positions --------------------------------------------------------------

@dataclass
class _Clause:
    name: str
    start: int            # logical index of the name
    stop: int             # logical index after ')' (or the name)
    arg: tuple | None     # (start, stop) of the argument text


@lru_cache(maxsize=None)
def _fparser(version: int, lang: str = "f90"):
    m = model_of(version)
    return G._parser(default_skeleton(m), default_grammar(m),
                     "C" if lang == "c" else "Fortran", version)


def _clauses(x: _Dir, version: int) -> list[_Clause]:
    """The clauses of a directive with their logical positions (the
    walk of grammar._Parser.parse, keeping the token positions)."""
    if x.lang == "c":
        toks = G._tokenize(x.logical)
        _, _, toks = _fparser(version, "c").c_name(toks)
    else:
        toks = G._tokenize(x.logical.lower())
        _, _, toks = _fparser(version).fortran_name(toks)
    i, out = 0, []
    if toks and toks[0].text == "(":
        i = G._close_paren(toks, 0, x.d.name) + 1
    while i < len(toks):
        t = toks[i]
        if t.text == ",":
            i += 1
            continue
        if i + 1 < len(toks) and toks[i + 1].text == "(":
            j = G._close_paren(toks, i + 1, t.text)
            out.append(_Clause(t.text, t.start, toks[j].end,
                               (toks[i + 1].end, toks[j].start)))
            i = j + 1
        else:
            out.append(_Clause(t.text, t.start, t.end, None))
            i += 1
    if [c.name for c in out] != [c.name for c in x.d.clauses]:
        raise MutationError(f"clause walk differs from the parse of "
                            f"{x.text!r}")
    return out


def _pieces(text: str, base: int) -> tuple[list[tuple], list[tuple]]:
    """Top-level pieces (start, stop) of a clause argument and the
    separators (pos, char) between them, at ',' and ':' (the split of
    grammar._split, with positions)."""
    pieces, seps = [], []
    depth, quote, start = 0, None, 0
    for i, ch in enumerate(text):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif depth == 0 and ch in ",:":
            pieces.append((start, i))
            seps.append((i, ch))
            start = i + 1
    pieces.append((start, len(text)))

    def trim(a, b):
        while a < b and text[a] in " \t":
            a += 1
        while b > a and text[b - 1] in " \t":
            b -= 1
        return a + base, b + base
    return [trim(a, b) for a, b in pieces], [(p + base, c) for p, c in seps]


def _piece_span(c: _Clause, i: int, pieces, seps, logical: str) -> tuple:
    """Logical span deleting piece i with one adjacent separator."""
    n = len(pieces)
    if n == 1:
        return c.arg[0] - 1, c.arg[1] + 1
    ps, pe = pieces[i]
    before = seps[i - 1] if i > 0 else None
    after = seps[i] if i < n - 1 else None
    if after is None or (before is not None and before[1] == ","
                         and after[1] == ":"):
        return before[0], pe
    return ps, pieces[i + 1][0]


def _clause_span(c: _Clause, x: _Dir) -> tuple:
    """Logical span deleting a whole clause with its separating blank (or
    comma): the blank before it, or, at the start of a line, after it."""
    s, e = c.start, c.stop
    line = x.pos[s][0] if x.pos[s] else None
    j = s
    while j > 0 and x.pos[j - 1] is not None and x.logical[j - 1] in " \t,":
        j -= 1
    prev_same = j > 0 and x.pos[j - 1] is not None \
        and x.pos[j - 1][0] == line
    if prev_same:
        return j, e
    while e < len(x.logical) and x.pos[e] is not None \
            and x.logical[e] in " \t,":
        e += 1
    return s, e


# --- applying edits ----------------------------------------------------------------

def _apply(lines: list[str], x: _Dir, edits: list[tuple]) -> list[str]:
    """The directive's physical lines with the logical edits applied: each
    edit is a span (s, e) or (s, e, text), the span deleted and `text`
    put in its place. A continuation line left empty is dropped with the
    '&' before it."""
    kill: dict[int, set] = {}
    put: dict[tuple, str] = {}
    for ed in edits:
        s, e = ed[0], ed[1]
        text = ed[2] if len(ed) > 2 else ""
        cols = [x.pos[i] for i in range(s, e) if x.pos[i] is not None]
        if len({ln for ln, _ in cols}) > 1:
            raise MutationError(f"an edit spans lines in {x.text!r}")
        if cols:
            kill.setdefault(cols[0][0], set()).update(c for _, c in cols)
        if text:
            at = x.pos[s] if s < len(x.pos) else None
            if at is None:
                raise MutationError(f"no position for an insertion in "
                                    f"{x.text!r}")
            put[at] = put.get(at, "") + text
    out: list[tuple[_Line, str]] = []
    for ln in x.lines:
        raw = lines[ln.idx]
        dead = kill.get(ln.idx, set())
        new, content = [], []
        for col, ch in enumerate(raw):
            ins = put.get((ln.idx, col), "")
            new.append(ins)
            if ln.cstart <= col < ln.cend:
                content.append(ins)
            if col not in dead:
                new.append(ch)
                if ln.cstart <= col < ln.cend:
                    content.append(ch)
        if out and not "".join(content).strip():
            continue  # an emptied continuation line
        out.append((ln, "".join(new)))
    if out:
        ln, new = out[-1]
        if ln is not x.lines[-1]:  # the last line was dropped: no '&'
            out[-1] = (ln, re.sub(r"\s*\\\s*$", "", new) if x.lang == "c"
                       else re.sub(r"\s*&\s*$", "", new))
    return [new for _, new in out]


def _rebuild(lines: list[str], edits: dict[int, list[str]]) -> list[str]:
    """Replace each directive (keyed by its first line) by its new lines;
    `edits` values are (number of original lines, new lines)."""
    out, k = [], 0
    while k < len(lines):
        if k in edits:
            n, new = edits[k]
            out += new
            k += n
            continue
        out.append(lines[k])
        k += 1
    return out


def _lang_of(new: list[str]) -> str:
    return "c" if new and _C_PRAGMA.match(new[0]) else "fortran"


def _parse_lines(new: list[str], version: int) -> Directive | None:
    try:
        return parse_directive("\n".join(new), _lang_of(new), version)
    except GrammarError:
        return None


def _parse_error(new: list[str], version: int) -> str | None:
    try:
        parse_directive("\n".join(new), _lang_of(new), version)
    except GrammarError as err:
        return err.code
    return None


# --- choosing the edits -------------------------------------------------------------

def _base(item: str) -> str:
    m = re.match(r"\s*([A-Za-z_]\w*)", item)
    return m.group(1).lower() if m else ""


def _infra(parsed) -> tuple[bool, bool]:
    """(all list items are infrastructure, some are)."""
    items = [_base(a) for a in parsed.args]
    hit = [i in INFRA_VARS for i in items]
    return bool(items) and all(hit), any(hit)


def _default_none(x: _Dir) -> bool:
    return any(c.name == "default" and [a.lower() for a in c.args] ==
               ["none"] for c in x.d.clauses)


def _drop_clause(x: _Dir, c: _Clause, parsed) -> tuple:
    """Edit deleting clause `c`; under default(none) a data-sharing
    clause's list items are listed in shared(...) in its place."""
    s, e = _clause_span(c, x)
    if parsed.name in DSA_CLAUSES and _default_none(x) and parsed.args \
            and (x.text.lstrip().lower().startswith("!$omp")
                 or _C_PRAGMA.match(x.text)):
        rep = f"shared({', '.join(parsed.args)})"
        return (s, e, " " + rep) if s < c.start else (s, e, rep + " ")
    return s, e


def _only_instance(x: _Dir, cl: list[_Clause], keep: int, name: str,
                   lines: list[str]) -> list[str]:
    spans = [_clause_span(c, x) for j, c in enumerate(cl)
             if c.name == name and j != keep]
    return _apply(lines, x, spans)


INFRA_HOW = "the reporting variable's clause left as is"
_INFRA_CLAUSE = re.compile(
    r"\s*\b[a-z_]+\((?:[^():]*:\s*)?(?:" + "|".join(sorted(INFRA_VARS))
    + r")\s*\)", re.I)


def _strip_infra(text: str) -> str:
    """`text` with every clause whose only list item is a reporting
    variable removed from its directive lines."""
    return "\n".join(_INFRA_CLAUSE.sub("", ln)
                     if any(p.match(ln) for p in _SENTS.values())
                     or _C_PRAGMA.match(ln) else ln
                     for ln in text.split("\n"))


def atoms_outside_infra(source: str, version: int) -> frozenset:
    """The atoms of `source` ignoring the reporting variables' clauses
    (e.g. map(tofrom: host_flag) carries omp.clause.map.tofrom)."""
    tree = parse_program(_strip_infra(source), version)
    return frozenset().union(*(d.atoms for d in tree.directives),
                             *(d.atoms for d in tree.ends.values()))
INFRA_KEPT = ("infra",)  # marker in an edit list: an infrastructure clause


def _clause_edits(x: _Dir, name: str, version: int) -> list[tuple]:
    """Every instance of clause `name` deleted, except infrastructure list
    items (a clause of only those is left; from a mixed one only the tested
    items are deleted)."""
    cl = _clauses(x, version)
    edits = []
    for c, parsed in zip(cl, x.d.clauses):
        if c.name != name:
            continue
        everything, some = _infra(parsed)
        if everything:
            edits.append(INFRA_KEPT)
            continue
        if not some:
            edits.append(_drop_clause(x, c, parsed))
            continue
        text = x.logical[c.arg[0]:c.arg[1]]
        pieces, seps = _pieces(text, c.arg[0])
        for i, (ps, pe) in enumerate(pieces):
            item = x.logical[ps:pe]
            if item in parsed.args and _base(item) not in INFRA_VARS:
                edits.append(_piece_span(c, i, pieces, seps, x.logical))
    return edits


def _rule(atom: str, directive: str):
    table = REPLACEMENTS.get(atom)
    if table is None:
        return "delete"
    rules = table[0]
    return rules.get(directive, rules.get("*"))


def _feature_edits(x: _Dir, atom: str, name: str, lines: list[str],
                   version: int) -> tuple[list[tuple], set]:
    cl = _clauses(x, version)
    edits, how = [], set()
    rule = _rule(atom, base_name(x.d.name))
    for j, (c, parsed) in enumerate(zip(cl, x.d.clauses)):
        if c.name != name:
            continue
        alone = _parse_lines(_only_instance(x, cl, j, name, lines), version)
        if alone is None:
            raise MutationError(f"cannot tell whether {name} instance {j} "
                                f"carries {atom} in {x.text!r}")
        if atom not in alone.atoms:
            continue
        everything, some = _infra(parsed)
        if everything:
            how.add(INFRA_HOW)
            continue
        if some:
            raise MutationError(f"{atom} on a clause mixing infrastructure "
                                f"and tested items in {x.text!r}")
        if rule == KEEP:
            how.add(f"kept on {base_name(x.d.name)}: no weaker form")
            continue
        if rule is None:
            edits.append(_drop_clause(x, c, parsed))
            how.add("clause carrying it")
            continue
        best = None
        if c.arg is not None:
            text = x.logical[c.arg[0]:c.arg[1]]
            pieces, seps = _pieces(text, c.arg[0])
            args = next(o.args for o in alone.clauses if o.name == name)
            base = [_clause_span(o, x) for k, o in enumerate(cl)
                    if o.name == name and k != j]
            for i in range(len(pieces)):
                span = _piece_span(c, i, pieces, seps, x.logical)
                new = _parse_lines(_apply(lines, x, base + [span]), version)
                if new is None or atom in new.atoms:
                    continue
                kept = next(o.args for o in new.clauses if o.name == name)
                key = (len(alone.atoms - new.atoms), kept != args, i)
                if best is None or key < best[0]:
                    best = (key, span, pieces[i])
        if best is not None and rule == "delete":
            edits.append(best[1])
            how.add("modifier")
        elif best is not None and rule == EMPTY_RANGE:
            ps, pe = best[2]
            piece = x.logical[ps:pe]
            new_piece, k = re.subn(r"(=\s*)1\s*:\s*[^:,()]+", r"\g<1>1:0",
                                   piece, count=1)
            if k != 1 or not piece.lower().startswith("iterator("):
                raise MutationError(f"no 1:<end> iterator range in {piece!r}")
            edits.append((ps, pe, new_piece))
            how.add(f"iterator range made empty: {new_piece}")
        elif best is not None:
            ps, pe = best[2]
            edits.append((ps, pe, rule))
            how.add(f"{x.logical[ps:pe]} replaced by {rule}")
        elif isinstance(rule, str) and rule not in ("delete", EMPTY_RANGE) \
                and c.arg is not None:
            # a lone argument (severity(fatal)): replace the piece whose
            # replacement no longer carries the atom
            text = x.logical[c.arg[0]:c.arg[1]]
            pieces, _ = _pieces(text, c.arg[0])
            base = [_clause_span(o, x) for k, o in enumerate(cl)
                    if o.name == name and k != j]
            for ps, pe in pieces:
                new = _parse_lines(_apply(lines, x, base + [(ps, pe, rule)]),
                                   version)
                if new is not None and atom not in new.atoms:
                    edits.append((ps, pe, rule))
                    how.add(f"{x.logical[ps:pe]} replaced by {rule}")
                    break
            else:
                raise MutationError(f"no piece of {name} can be replaced by "
                                    f"{rule} in {x.text!r}")
        else:
            edits.append(_drop_clause(x, c, parsed))
            how.add("clause carrying it")
    return edits, how


def _rename_edits(x: _Dir, name: str, new: str, version: int) -> list:
    """Edits renaming every instance of clause `name` (except clauses of
    reporting variables only) to `new`, its arguments kept."""
    out = []
    for c, parsed in zip(_clauses(x, version), x.d.clauses):
        if c.name != name or _infra(parsed)[0]:
            continue
        if _infra(parsed)[1]:
            raise MutationError(f"{name} mixes reporting and tested items "
                                f"in {x.text!r}")
        out.append((c.start, c.start + len(c.name), new))
    return out


def _comment(lines: list[str], x: _Dir) -> list[str]:
    out = []
    lead = "// MUTANT " if x.lang == "c" else "! MUTANT "
    for raw in lines[x.first:x.last + 1]:
        body = raw.lstrip()
        if x.lang == "c":  # no line splice into the next line
            body = re.sub(r"\s*\\\s*$", "", body)
        out.append(raw[:len(raw) - len(raw.lstrip())] + lead + body)
    return out


def _comment_pair(edits: dict, lines: list[str], x: _Dir) -> None:
    edits[x.first] = (x.last - x.first + 1, _comment(lines, x))
    if x.end is not None:
        e = x.end
        edits[e.first] = (e.last - e.first + 1, _comment(lines, e))


def neutralise(prog: Program) -> Program | None:
    """The mutant of `prog` without its primary atom (see the module
    docstring), or None for an atom in NO_MUTATION."""
    atom = prog.primary_atom
    if atom in NO_MUTATION:
        return None
    version = int(re.match(r"(?:omp|acc)(\d\d)-", prog.id).group(1))
    model = model_of(version)
    lang = "c" if prog.lang == "c" else "f90"
    lines = prog.source.split("\n")
    try:
        dirs = _scan(lines, version, lang)
        _pair(dirs, prog.source, version)
    except (GrammarError, ProgramError) as err:
        raise MutationError(f"{prog.id}: {err}") from err
    edits: dict[int, tuple] = {}
    hows: set = set()
    kept = False
    parts = atom.split(".")
    if atom in SEMANTIC_MUTATIONS or atom in SEMANTIC_MUTATIONS_ACC:
        return _semantic_mutant(prog, atom, lines, dirs)
    begins = [x for x in dirs if not x.d.end]
    for x in dirs:
        if x.protected or (x.d.end and parts[1] == "directive"):
            continue
        if parts[1] == "directive":
            if directive_atom(x.d.name, model) != atom:
                continue
            _comment_pair(edits, lines, x)
            hows.add("directive and its end" if x.end else "directive")
            continue
        if atom not in x.d.atoms:
            continue
        name = parts[2]
        if atom in ACC_CONSTRUCT_CLAUSES:
            _comment_pair(edits, lines, x)
            hows.add("its atomic construct commented out (the statements "
                     "stay)")
            continue
        if atom in ACC_ARG_REPLACE:
            new_arg = ACC_ARG_REPLACE[atom][0]
            dedits = [(c.arg[0], c.arg[1], new_arg)
                      for c in _clauses(x, version)
                      if c.name == name and c.arg is not None]
            edits[x.first] = (x.last - x.first + 1,
                              _apply(lines, x, dedits))
            hows.add(f"its argument replaced by {new_arg}")
            kept = True
            continue
        if atom in ACC_RENAMES:
            dedits = _rename_edits(x, name, ACC_RENAMES[atom][0], version)
            if not dedits:
                continue
            new = _apply(lines, x, dedits)
            edits[x.first] = (x.last - x.first + 1, new)
            hows.add(f"renamed {name} -> {ACC_RENAMES[atom][0]}")
            continue
        if len(parts) == 3:
            dedits = _clause_edits(x, name, version)
            how = {"clause"}
            if INFRA_KEPT in dedits:
                how.add(INFRA_HOW)
                dedits = [e for e in dedits if e != INFRA_KEPT]
        else:
            dedits, how = _feature_edits(x, atom, name, lines, version)
        # the atom stays where the table keeps the form (no weaker one) or
        # where the iterator stays with an empty range
        kept = kept or any(h.startswith(("kept on", "iterator range made "
                                         "empty")) for h in how)
        if not dedits:
            hows |= how
            continue
        new = _apply(lines, x, dedits)
        after = _parse_lines(new, version)
        needs = _parse_error(new, version) == "missing_required" or (
            after is not None and not after.clauses and x.d.clauses
            and not x.d.args and base_name(x.d.name) in NEEDS_A_CLAUSE)
        if needs and not x.d.end:
            _comment_pair(edits, lines, x)
            hows.add("directive commented out: its required clause was the "
                     "one removed")
            continue
        bare = _parse_lines(_strip_infra("\n".join(new)).split("\n"),
                            version)
        if bare is not None and atom in bare.atoms and not kept:
            raise MutationError(f"{prog.id}: {atom} still in {new}")
        hows |= how
        if any(len(e) > 2 and e[2].lstrip().startswith("shared(")
               for e in dedits):
            hows.add("its list items made shared under default(none)")
        edits[x.first] = (x.last - x.first + 1, new)
    comp = COMPANIONS.get(atom)
    if comp is not None and edits:
        for x in begins:
            if not x.protected and directive_atom(x.d.name, model) == comp:
                _comment_pair(edits, lines, x)
                hows.add(f"with the {comp.split('.')[-1]} constructs that "
                         "need it")
    if not edits:
        raise MutationError(f"{prog.id}: no directive carries {atom}")
    out = _rebuild(lines, edits)
    if _needs_dynamic_allocators(out, version):
        out = _add_dynamic_allocators(out)
        hows.add("requires dynamic_allocators added: an allocate clause in a "
                 "target region without an allocator needs it")
    how = "; ".join(sorted(hows))
    lead = "//" if lang == "c" else "!"
    out.insert(1, f"{lead} MUTANT of {prog.id}: removed {atom} ({how})")
    source = "\n".join(out)
    try:
        tree = parse_program(source, version)
        atoms = frozenset().union(*(d.atoms for d in tree.directives),
                                  *(d.atoms for d in tree.ends.values()))
    except (GrammarError, ProgramError):
        atoms = frozenset(prog.atoms - {atom})
    if atom in atoms and not kept:
        try:
            outside = atoms_outside_infra(source, version)
        except (GrammarError, ProgramError):
            outside = atoms
        if atom in outside:
            raise MutationError(f"{prog.id}: {atom} survives the mutation")
    return dataclasses.replace(prog, id=f"{prog.id}-mutant", source=source,
                               atoms=atoms)


def _needs_dynamic_allocators(lines: list[str], version: int) -> bool:
    """Removing the allocator modifier of an allocate clause in a
    target region leaves a non-conforming program (rule allocate-clause-002:
    5.2 §6.6 p.179, 6.0 §8.6 p.313) unless a requires dynamic_allocators
    directive is present; the conforming mutant adds it."""
    from offload.engine.rules import violations
    try:
        found = violations(parse_program("\n".join(lines), version), version)
    except (GrammarError, ProgramError):
        return False
    return f"OMP{version}-allocate-clause-002" in found


def _add_dynamic_allocators(lines: list[str]) -> list[str]:
    """`lines` with requires dynamic_allocators after the main program's
    IMPLICIT statement (C: at file scope after the #include lines)."""
    if any(_C_PRAGMA.match(ln) for ln in lines):
        k = max(k for k, ln in enumerate(lines)
                if ln.startswith("#include"))
        return lines[:k + 1] + ["#pragma omp requires dynamic_allocators"] \
            + lines[k + 1:]
    start = next(k for k, ln in enumerate(lines)
                 if ln.strip().startswith("program "))
    k = next(k for k in range(start, len(lines))
             if lines[k].strip().lower() == "implicit none")
    indent = lines[k][:len(lines[k]) - len(lines[k].lstrip())]
    return lines[:k + 1] + [f"{indent}!$omp requires dynamic_allocators"] \
        + lines[k + 1:]


def _semantic_mutant(prog: Program, atom: str, lines: list[str],
                     dirs: list) -> Program:
    """The mutant of a semantic atom (SEMANTIC_MUTATIONS): its clause added
    at the end of every unprotected begin directive of its name."""
    directive, clause, _ = {**SEMANTIC_MUTATIONS,
                            **SEMANTIC_MUTATIONS_ACC}[atom]
    version = int(re.match(r"(?:omp|acc)(\d\d)-", prog.id).group(1))
    out = list(lines)
    hit = False
    for x in dirs:
        if x.protected or x.d.end or base_name(x.d.name) != directive:
            continue
        out[x.last] = out[x.last].rstrip() + " " + clause
        hit = True
    if not hit:
        raise MutationError(f"{prog.id}: no {directive} directive for {atom}")
    mark = "//" if prog.lang == "c" else "!"  # A C program
    out.insert(1, f"{mark} MUTANT of {prog.id}: removed {atom} (added "
               f"{clause} to {directive})")
    source = "\n".join(out)
    try:
        tree = parse_program(source, version,
                             lang="c" if prog.lang == "c" else None)
    except (GrammarError, ProgramError) as err:
        raise MutationError(f"{prog.id}: {err}") from err
    atoms = frozenset().union(*(d.atoms for d in tree.directives),
                              *(d.atoms for d in tree.ends.values()))
    return dataclasses.replace(prog, id=f"{prog.id}-mutant", source=source,
                               atoms=atoms)


def mutation_of(mutant: Program) -> str:
    """The `removed <atom> (<how>)` text of a mutant's header."""
    m = re.search(r"^(?:!|//) MUTANT of \S+: (.*)$", mutant.source, re.M)
    return m.group(1) if m else ""


# --- the audit ---------------------------------------------------------------------

@dataclass(frozen=True)
class MutantResult:
    program_id: str
    primary_atom: str
    version: int
    toolchain: str
    status: str          # killed | survived | inconclusive | not_applicable
    original: str        # the original's Outcome ("" if not run)
    mutant: str          # the mutant's Outcome ("" if not run)
    reason: str
    xnack: int = 0
    mutation: str = ""   # what the mutant removed
    original_reason: str = ""
    mutant_reason: str = ""
    kill_kind: str = ""  # killed only: check_fail | fell_back_to_host | crash
    body_sha: str = ""   # body_sha of the audited original (staleness check)
    # The result was copied from this program's audit (same body,
    # other version: a 5.0 program identical to its 5.2 program)
    reused_from: str = ""


STATUSES = ("killed", "survived", "inconclusive", "not_applicable")


KILL_KINDS = ("check_fail", "fell_back_to_host", "crash")


def kill_kind(mut: Result) -> str:
    """How a failing mutant failed: fell_back_to_host (ran_on_host=1),
    check_fail (the check failed on a completed run), crash (abnormal end:
    a signal, a non-zero exit, no RESULT line), timeout."""
    if mut.outcome == Outcome.fell_back_to_host:
        return "fell_back_to_host"
    if "timeout" in mut.reason:
        return "timeout"
    if mut.reason.startswith("check_fail") or "check=fail" in mut.reason:
        return "check_fail"
    return "crash"


def classify(orig: Result, mut: Result) -> tuple[str, str, str]:
    """(status, reason, kill kind) from the original's and the mutant's
    results. A mutant that times out (also when re-run) is inconclusive:
    a hang may be GPU contention as well as the missing construct."""
    C = Outcome.correct_on_device
    if orig.outcome != C:
        return "inconclusive", (f"original_{orig.outcome}: {orig.reason}; "
                                f"mutant {mut.outcome}: {mut.reason}"), ""
    if mut.outcome == C:
        return "survived", "mutant correct_on_device", ""
    if mut.outcome == Outcome.rejected:
        return "inconclusive", f"mutant_compile_failure: {mut.reason}", ""
    if mut.outcome in (Outcome.wrong_answer, Outcome.fell_back_to_host):
        kind = kill_kind(mut)
        if kind == "timeout":
            return "inconclusive", f"mutant_timeout: {mut.reason}", ""
        return "killed", f"mutant {mut.outcome}: {mut.reason}", kind
    return "inconclusive", f"mutant_{mut.outcome}: {mut.reason}", ""


def illegal(mutant: Program, version: int) -> list[str]:
    """The rules (offload.engine.rules.violations) a mutant breaks; a mutant
    the rule scanner cannot parse counts as illegal too."""
    from offload.engine.rules import violations
    try:
        return violations(parse_program(mutant.source, version), version)
    except (GrammarError, ProgramError) as err:
        return [f"unparsable ({err})"]


def audit_programs(version: int, only: Callable[[Program], bool] | None = None,
                   lang: str = "f90") -> list[Program]:
    """The programs the audit covers at `version`: legal, observable, with
    an audited evidence level (offload.engine.gen.AUDITED: construct,
    copy_mode_only, probe; not the no-oracle categories, legality or
    unverified), device scope (not a host+device pattern),
    accepted by `only`. `lang` "c": the C programs (Task
    20)."""
    from offload.engine.gen import AUDITED
    if lang == "c" and model_of(version) == "acc":
        from offload.engine.acc_c_gen import all_acc_c_programs
        # One program per atom; the -binop companions
        # share their compound twin's oracle and atom, and nvc does not
        # compile them (data/findings/nvhpc-c-acc-atomic-update-sum-ice.c)
        progs = [p for p in all_acc_c_programs()
                 if not p.id.endswith("-binop")]
    elif lang == "c":
        from offload.engine.c_gen import all_c_programs
        progs = all_c_programs(version)
    else:
        progs = generate(slice_atoms(version), version)
    # A host+device pattern is not its atom's oracle (the
    # device-only headline program is)
    return [p for p in progs
            if p.legal and p.observable and p.evidence in AUDITED
            and p.scope == "device" and (only is None or only(p))]


def audit(version: int, toolchains: Sequence[str], xnack: int = 0,
          opt: str = "-O2", workers: int = 8,
          only: Callable[[Program], bool] | None = None, *,
          runner: Callable[..., Result] = run_program, timeout_s: int = 120,
          progress: Callable[[str], None] | None = None,
          lang: str = "f90") -> list[MutantResult]:
    """Run original and mutant of every audited program on each toolchain
    (see the module docstring); `runner` is run_program (tests pass a
    fake). `lang` "c" audits the C programs."""
    progs = audit_programs(version, only, lang)
    # the version flags of the matrix (AFAR 6.0: -fopenmp-version=60), so
    # the audit builds each program as the matrix does
    tcs = [for_version(TOOLCHAINS[t] if isinstance(t, str) else t, version,
                       lang)
           for t in toolchains]
    out: list[MutantResult] = []
    jobs = []  # (prog, mutant, tc, mode)
    for p in progs:
        mut = neutralise(p)
        for tc in tcs:
            if mut is None:
                out.append(MutantResult(p.id, p.primary_atom, version,
                                        tc.name, "not_applicable", "", "",
                                        NO_MUTATION[p.primary_atom], xnack,
                                        body_sha=body_sha(p.source)))
                continue
            # A machine without unified memory (NVHPC on wingtip)
            # runs it in the requested mode
            mode = 1 if "zero_copy" in p.needs and 1 in tc.xnack_modes \
                else xnack
            jobs.append((p, mut, tc, mode))
    cache: dict[tuple, Result] = {}  # originals, within this audit

    def run(prog: Program, tc, mode: int) -> Result:
        r = runner(prog, tc, mode, opt, timeout_s=timeout_s, repeats=1)
        if "timeout" in r.reason:  # once more (GPU contention)
            r = runner(prog, tc, mode, opt, timeout_s=timeout_s, repeats=1)
        return r

    def original(prog, tc, mode):
        key = (prog.id, tc.name, mode)
        if key not in cache:
            cache[key] = run(prog, tc, mode)
        return cache[key]

    def job(item) -> MutantResult:
        p, mut, tc, mode = item
        o = original(p, tc, mode)
        bad = illegal(mut, version)
        if bad:
            # a mutant that breaks a restriction is no evidence:
            # inconclusive, and it is not run
            return MutantResult(p.id, p.primary_atom, version, tc.name,
                                "inconclusive", str(o.outcome), "",
                                f"mutant is illegal: {', '.join(bad)}", mode,
                                mutation_of(mut), o.reason, "", "",
                                body_sha(p.source))
        m = run(mut, tc, mode)
        status, reason, kind = classify(o, m)
        if mode != xnack:
            reason = f"needs_zero_copy: run under HSA_XNACK={mode}; {reason}"
        if progress:
            progress(f"{p.id} {tc.name}: {status}")
        return MutantResult(p.id, p.primary_atom, version, tc.name, status,
                            str(o.outcome), str(m.outcome), reason, mode,
                            mutation_of(mut), o.reason, m.reason, kind,
                            body_sha(p.source))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        out += list(pool.map(job, jobs))
    return sorted(out, key=lambda r: (r.version, r.program_id, r.toolchain))


def summarise(results: Sequence[MutantResult]) -> dict[str, dict]:
    """Per atom: status "valid" (killed on at least one toolchain), "weak"
    (survived on every toolchain where it was conclusive, at least one),
    "unknown" otherwise; the per-toolchain statuses; whether the atom has
    no mutation."""
    by: dict[str, list[MutantResult]] = {}
    for r in results:
        by.setdefault(r.primary_atom, []).append(r)
    out = {}
    for atom in sorted(by):
        rs = by[atom]
        sts = [r.status for r in rs]
        if "killed" in sts:
            status = "valid"
        elif "survived" in sts:
            status = "weak"
        else:
            status = "unknown"
        out[atom] = dict(
            status=status,
            toolchains={r.toolchain: r.status for r in rs},
            programs=sorted({r.program_id for r in rs}),
            not_applicable=all(s == "not_applicable" for s in sts))
    return out


# --- the committed per-atom summary (tests/data/oracle_audit_summary.json) ----------

# Dispositions of a legal program's atom (``audit_summary``). Only "valid"
# and "unaudited_no_passing_original" are acceptable for an observable
# program whose evidence is construct, copy_mode_only or probe; the
# no-oracle ones belong to programs whose evidence is that
# category (header lines ``! no oracle (<kind>): <reason>`` and ``! basis:
# ...``), the unverified ones to programs marked evidence="unverified"
# (``! unverified (<kind>): <reason>``, offload.engine.gen.UNVERIFIED), legality
# to a program whose oracle is an illegal variant.
DISPOSITIONS = {
    "valid": "the mutant is killed on at least one toolchain (copy mode)",
    "unaudited_no_passing_original": "unaudited: no toolchain passes the "
                                     "original, so nothing can be credited "
                                     "to a toolchain",
    "hint_only": "no oracle can exist: the spec lets an implementation "
                 "ignore the form (accepted; conforms vacuously)",
    "implementation_defined": "no oracle can exist: the spec leaves the "
                              "behaviour to the implementation "
                              "(implementation-defined)",
    "equivalent_default": "no oracle can exist: by the spec the form is the "
                          "behaviour without it (equivalent to the default)",
    "legality": "the atom's only effect is a compile-time restriction; its "
                "oracle is the illegal variant named in the reason",
    "unverified_oracle_not_written": "a deterministic oracle for behaviour "
                                     "the spec fixes is possible but the "
                                     "program does not have it",
    "unverified_needs_other_infrastructure": "observable only outside the "
                                             "program's result (a tool "
                                             "interface, or a feature no "
                                             "toolchain provides; evidence "
                                             "unverified)",
    "not_observable": "the program checks no effect of the atom "
                      "(observable=False)",
    "weak": "the mutant survived on every toolchain where the result was "
            "conclusive",
    "no_mutation": "the atom has no mutation (NO_MUTATION) but its program "
                   "claims evidence",
    "unknown": "no conclusive result although an original passed",
    "missing": "no audit result for an audited program",
}


def body_sha(source: str) -> str:
    """sha256 of a program source without its leading header comment block
    (the audited text: a summary is stale when this changes)."""
    import hashlib
    lines = source.splitlines(keepends=True)
    k = 0
    while k < len(lines) and lines[k].startswith(("!", "//")):
        k += 1
    return hashlib.sha256("".join(lines[k:]).encode()).hexdigest()


def audit_summary(results: Sequence[MutantResult], programs: Sequence[Program],
                  version: int) -> dict[str, dict]:
    """Per legal program at `version` (keyed by primary atom): the audit
    status (summarise; "not_audited" for programs the audit skips), the
    per-toolchain statuses, originals and kill kinds, the program's
    evidence and observability, the sha of its body, and the disposition
    (DISPOSITIONS) with its reason."""
    from offload.engine.gen import NO_ORACLE, legality_of, no_oracle_of, \
        unverified_of
    rs = [r for r in results if r.version == version]
    sums = summarise(rs)
    by: dict[str, list[MutantResult]] = {}
    for r in rs:
        by.setdefault(r.primary_atom, []).append(r)
    out = {}
    for p in sorted((p for p in programs
                     if p.legal and p.scope == "device"),
                    key=lambda p: p.primary_atom):
        atom = p.primary_atom
        mine = sorted(by.get(atom, []), key=lambda r: r.toolchain)
        s = sums.get(atom)
        # an audited atom carries the sha of the program the audit ran (a
        # summary rebuilt from results of an older program is stale)
        shas = {r.body_sha for r in mine}
        entry = dict(
            program=p.id, evidence=p.evidence, observable=p.observable,
            body_sha=(shas.pop() if len(shas) == 1 else "mixed") if mine
            else body_sha(p.source),
            status=s["status"] if s else "not_audited",
            toolchains={r.toolchain: r.status for r in mine},
            originals={r.toolchain: r.original for r in mine},
            kill_kinds=sorted({r.kill_kind for r in mine
                               if r.status == "killed"}),
            xnack=max((r.xnack for r in mine), default=0))
        unv = unverified_of(p.source)
        if p.evidence == "unverified":
            kind, why = unv if unv else ("missing_reason", "")
            disp, reason = f"unverified_{kind}", why
        elif p.evidence in NO_ORACLE:
            noo = no_oracle_of(p.source)
            disp = p.evidence
            reason = f"{noo[1]} [basis: {noo[2]}]" if noo else ""
        elif p.evidence == "legality":
            disp = "legality"
            reason = (f"its oracle is the illegal variant of "
                      f"{legality_of(p.source)}")
        elif not p.observable:
            disp = "not_observable"
            m = re.search(r"^(?:!|//) observable: no(?: \((.*)\))?$",
                          p.source, re.M)
            reason = (m.group(1) or "") if m else ""
        elif not mine:
            disp, reason = "missing", ""
        elif s["status"] == "valid":
            disp = "valid"
            reason = "" if "check_fail" in entry["kill_kinds"] else (
                "valid only via " + ", ".join(entry["kill_kinds"]))
        elif s["not_applicable"]:
            disp, reason = "no_mutation", NO_MUTATION.get(atom, "")
        elif s["status"] == "unknown" and all(
                r.original != str(Outcome.correct_on_device) for r in mine):
            disp = "unaudited_no_passing_original"
            reason = "; ".join(f"{r.toolchain}: {r.original}" for r in mine)
        else:
            disp, reason = s["status"], ""
        entry.update(disposition=disp, reason=reason)
        out[atom] = entry
    return out


# --- Map mutants, judged in both memory modes --------------------------

MAP_KINDS = ("weaken_map", "swap_to_from", "drop_map", "drop_update")
MAP_KIND_TEXT = {
    "weaken_map": "every map type of a tested item made alloc (release on "
                  "target exit data; OpenACC: copy, copyin, copyout -> "
                  "create): the mapping stays, its transfers go",
    "swap_to_from": "to <-> from on the map types of target and target data "
                    "and on the motion clauses of target update (OpenACC: "
                    "copyin <-> copyout, update host <-> device)",
    "drop_map": "every map clause of a tested item deleted (OpenACC: copy, "
                "copyin, copyout, create); a data directive left without "
                "one is commented out with its end",
    "drop_update": "every target update (OpenACC: update) directive "
                   "commented out",
}
_MAP_TYPES = frozenset({"to", "from", "tofrom", "alloc", "release", "delete",
                        "storage"})
_DATA_DIRS = frozenset({"target enter data", "target exit data",
                        "target data", "enter data", "exit data", "data"})
_ACC_DATA = ("copy", "copyin", "copyout", "create")


def _map_type_piece(x: _Dir, c: _Clause):
    """(start, stop) of the map-type piece of map clause `c` (a piece
    before the colon that is a map type), or None; and the colon's
    position (None: no modifiers, the whole argument is the list)."""
    text = x.logical[c.arg[0]:c.arg[1]]
    pieces, seps = _pieces(text, c.arg[0])
    colons = [k for k, (_, ch) in enumerate(seps) if ch == ":"]
    if not colons:
        return None, None
    last = colons[-1]
    for ps, pe in pieces[:last + 1]:
        if x.logical[ps:pe].strip().lower() in _MAP_TYPES:
            return (ps, pe), seps[last][0]
    return None, seps[last][0]


def _map_edits(x: _Dir, kind: str, version: int) -> list[tuple]:
    """The logical edits of one directive for an OpenMP map mutant."""
    name = base_name(x.d.name)
    out = []
    for c, parsed in zip(_clauses(x, version), x.d.clauses):
        everything, some = _infra(parsed)
        if kind == "swap_to_from" and name == "target update" \
                and c.name in ("to", "from") and not some:
            out.append((c.start, c.start + len(c.name),
                        "from" if c.name == "to" else "to"))
            continue
        if c.name != "map" or c.arg is None or everything or some:
            continue
        piece, _colon = _map_type_piece(x, c)
        typ = x.logical[piece[0]:piece[1]].lower() if piece else None
        if kind == "weaken_map":
            weak = "release" if name == "target exit data" else (
                "storage" if version >= 60 and "storage" in x.logical.lower()
                else "alloc")
            if typ in ("to", "from", "tofrom"):
                out.append((piece[0], piece[1], weak))
            elif typ is None and _colon is None:
                out.append((c.arg[0], c.arg[0], f"{weak}: "))
        elif kind == "swap_to_from" and name in ("target", "target data") \
                and typ in ("to", "from"):
            out.append((piece[0], piece[1], "from" if typ == "to" else "to"))
    return out


def _acc_edits(x: _Dir, kind: str, version: int) -> list[tuple]:
    """The logical edits of one directive for an OpenACC map mutant."""
    out = []
    for c, parsed in zip(_clauses(x, version), x.d.clauses):
        everything, some = _infra(parsed)
        if everything or some:
            continue
        if kind == "weaken_map" and c.name in ("copy", "copyin", "copyout"):
            out.append((c.start, c.start + len(c.name), "create"))
        elif kind == "swap_to_from" and c.name in ("copyin", "copyout"):
            out.append((c.start, c.start + len(c.name),
                        "copyout" if c.name == "copyin" else "copyin"))
        elif kind == "swap_to_from" and base_name(x.d.name) == "update" \
                and c.name in ("host", "self", "device"):
            out.append((c.start, c.start + len(c.name),
                        "host" if c.name == "device" else "device"))
    return out


def map_mutants(prog: Program) -> dict[str, Program]:
    """The map mutants of `prog` (MAP_KINDS: weaken the map types,
    swap to and from, drop the map clauses, drop target update), each the
    program with that change on every directive outside the
    infrastructure (the probe, the shared-memory detector, the reporting
    variables' clauses). A kind that changes nothing, or whose edit the
    mutation machinery cannot place, is left out. Ids
    ``<id>-map-<kind>``; header ``! MAP MUTANT of <id>: <kind> (...)``."""
    version = int(re.match(r"(?:omp|acc)(\d\d)-", prog.id).group(1))
    acc = model_of(version) == "acc"
    lang = "c" if prog.lang == "c" else "f90"
    lines = prog.source.split("\n")
    dirs = _scan(lines, version, lang)
    _pair(dirs, prog.source, version)
    update = "update" if acc else "target update"
    out = {}
    for kind in MAP_KINDS:
        edits: dict[int, tuple] = {}
        try:
            for x in dirs:
                if x.protected or x.d.end:
                    continue
                name = base_name(x.d.name)
                if kind == "drop_update":
                    if name == update:
                        _comment_pair(edits, lines, x)
                    continue
                if kind == "drop_map":
                    dedits = []
                    for cname in (_ACC_DATA if acc else ("map",)):
                        dedits += [e for e in _clause_edits(x, cname,
                                                            version)
                                   if e != INFRA_KEPT]
                else:
                    dedits = (_acc_edits if acc else _map_edits)(
                        x, kind, version)
                if not dedits:
                    continue
                new = _apply(lines, x, dedits)
                after = _parse_lines(new, version)
                left = after is not None and any(
                    c.name in (_ACC_DATA + ("present", "no_create",
                                            "attach", "delete",
                                            "detach", "deviceptr")
                               if acc else ("map", "use_device_ptr",
                                            "use_device_addr"))
                    for c in after.clauses)
                if after is None or (name in _DATA_DIRS and not left):
                    _comment_pair(edits, lines, x)
                else:
                    edits[x.first] = (x.last - x.first + 1, new)
        except MutationError:
            continue
        if not edits:
            continue
        new_lines = _rebuild(lines, edits)
        lead = "//" if lang == "c" else "!"
        new_lines.insert(1, f"{lead} MAP MUTANT of {prog.id}: {kind} "
                         f"({MAP_KIND_TEXT[kind]})")
        source = "\n".join(new_lines)
        try:
            tree = parse_program(source, version,
                                 lang="c" if lang == "c" else None)
            atoms = frozenset().union(
                *(d.atoms for d in tree.directives),
                *(d.atoms for d in tree.ends.values()))
        except (GrammarError, ProgramError):
            atoms = prog.atoms
        out[kind] = dataclasses.replace(prog, id=f"{prog.id}-map-{kind}",
                                        source=source, atoms=atoms)
    return out


@dataclass(frozen=True)
class MapMutantResult:
    program_id: str
    primary_atom: str
    version: int
    lang: str
    toolchain: str
    kind: str            # MAP_KINDS
    xnack: int
    status: str          # killed | survived | inconclusive
    original: str
    mutant: str
    reason: str
    kill_kind: str = ""
    body_sha: str = ""


def map_audit(version: int, toolchains: Sequence[str],
              modes: Sequence[int] = (0, 1), opt: str = "-O2",
              workers: int = 8,
              only: Callable[[Program], bool] | None = None, *,
              runner: Callable[..., Result] = run_program,
              timeout_s: int = 120,
              progress: Callable[[str], None] | None = None,
              lang: str = "f90") -> list[MapMutantResult]:
    """Run the original and every map mutant of each audited
    program (audit_programs) on each toolchain in each memory mode
    (HSA_XNACK=0 and 1), one repeat (a timeout once more), and classify
    as the primary-atom audit does (classify). A program that needs
    zero-copy memory is not run at HSA_XNACK=0 (inconclusive,
    needs_zero_copy); an illegal mutant is not run (inconclusive)."""
    progs = audit_programs(version, only, lang)
    tcs = [for_version(TOOLCHAINS[t] if isinstance(t, str) else t, version,
                       lang) for t in toolchains]
    jobs = []
    for p in progs:
        muts = map_mutants(p)
        for kind, m in muts.items():
            bad = illegal(m, version)
            for tc in tcs:
                for x in modes:
                    jobs.append((p, kind, m, tc, x, bad))
    cache: dict[tuple, Result] = {}
    lock = __import__("threading").Lock()

    def run(prog, tc, x):
        r = runner(prog, tc, x, opt, timeout_s=timeout_s, repeats=1)
        if "timeout" in r.reason:
            r = runner(prog, tc, x, opt, timeout_s=timeout_s, repeats=1)
        return r

    def original(p, tc, x):
        key = (p.id, tc.name, x)
        with lock:
            have = cache.get(key)
        if have is None:
            have = run(p, tc, x)
            with lock:
                cache.setdefault(key, have)
        return have

    def job(item) -> MapMutantResult:
        p, kind, m, tc, x, bad = item
        base = dict(program_id=p.id, primary_atom=p.primary_atom,
                    version=version, lang=lang, toolchain=tc.name, kind=kind,
                    xnack=x, body_sha=body_sha(p.source))
        if x == 0 and "zero_copy" in p.needs:
            return MapMutantResult(**base, status="inconclusive",
                                   original="", mutant="",
                                   reason="needs_zero_copy: not run at "
                                          "HSA_XNACK=0")
        o = original(p, tc, x)
        if bad:
            return MapMutantResult(**base, status="inconclusive",
                                   original=str(o.outcome), mutant="",
                                   reason="mutant is illegal: "
                                          + ", ".join(bad))
        r = run(m, tc, x)
        status, reason, kk = classify(o, r)
        if progress:
            progress(f"{p.id} {kind} {tc.name} x{x}: {status}")
        return MapMutantResult(**base, status=status, original=str(o.outcome),
                               mutant=str(r.outcome), reason=reason,
                               kill_kind=kk)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        out = list(pool.map(job, jobs))
    return sorted(out, key=lambda r: (r.version, r.program_id, r.kind,
                                      r.toolchain, r.xnack))


def _caught(x0: bool, x1: bool) -> str:
    return {(True, True): "both", (True, False): "x0_only",
            (False, True): "x1_only"}.get((x0, x1), "neither")


def map_summary(results: Sequence[MapMutantResult]) -> dict[str, dict]:
    """Per primary atom (one version and language at a time): for each map
    kind the mode that catches it (``both``, ``x0_only``, ``x1_only``,
    ``neither``: killed on some toolchain in that mode; ``inconclusive``:
    no run of the kind was conclusive), ``caught`` over
    all kinds, ``copy_mode_only`` (the kinds caught at HSA_XNACK=0 only: a
    valid oracle of the mapping in copy mode, blind to it under unified
    memory) and the per-kind, per-toolchain, per-mode statuses."""
    by: dict[str, list[MapMutantResult]] = {}
    for r in results:
        by.setdefault(r.primary_atom, []).append(r)
    out = {}
    for atom in sorted(by):
        rs = by[atom]
        kinds, detail = {}, {}
        for k in MAP_KINDS:
            mine = [r for r in rs if r.kind == k]
            if not mine:
                continue
            kill = {x: any(r.status == "killed" for r in mine
                           if r.xnack == x) for x in (0, 1)}
            kinds[k] = _caught(kill[0], kill[1])
            if kinds[k] == "neither" and not any(
                    r.status == "survived" for r in mine):
                kinds[k] = "inconclusive"  # no conclusive run at all
            detail[k] = {f"{r.toolchain}_x{r.xnack}": r.status
                         for r in mine}
        x0 = any(v in ("both", "x0_only") for v in kinds.values())
        x1 = any(v in ("both", "x1_only") for v in kinds.values())
        caught = _caught(x0, x1)
        if caught == "neither" and all(v == "inconclusive"
                                       for v in kinds.values()):
            caught = "inconclusive"
        out[atom] = dict(program=rs[0].program_id, kinds=kinds,
                         caught=caught,
                         copy_mode_only=[k for k, v in kinds.items()
                                         if v == "x0_only"],
                         detail=detail)
    return out


# --- Checks that read uninitialized from-mapped items --
#
# A check that reads an item the program maps back (map from or tofrom)
# but the host never assigns before the region judges a mutant that loses
# the copy-back on uninitialized memory: the mutant may survive by chance.
# Detected from the text (Fortran and C, the catalog's generated forms).

_MUTANT_LINE = re.compile(r"^\s*(?:!|//) MUTANT\b")
_FROM_MAP = re.compile(
    r"\bmap\s*\(\s*((?:[\w-]+\s*,\s*)*)(from|tofrom)\s*:\s*([^)]*(?:\([^)]*\)[^)]*)*)\)",
    re.I)
_DIRECTIVE = re.compile(r"^\s*(?:!\$omp|!\$acc|#\s*pragma\s+omp)\b", re.I)
# OpenACC: copyout and copy move data back to the host
_ACC_FROM = re.compile(r"\b(?:copyout|copy)\s*\(([^)]*(?:\([^)]*\)[^)]*)*)\)",
                       re.I)


def _live(source: str) -> list[str]:
    return [ln for ln in source.split("\n") if not _MUTANT_LINE.match(ln)]


def _split_items(text: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [re.split(r"[(\[%.]", x.strip(), maxsplit=1)[0].strip()
            for x in out if x.strip()]


def _directive_maps(lines: list[str]) -> list[tuple[int, list[str]]]:
    """(index of the directive's first line, from/tofrom item names) per
    directive, continuation lines joined (Fortran &, C backslash)."""
    return [(i, names) for i, names, _ in _directive_items(lines) if names]


def _directive_text(lines: list[str], i: int) -> tuple[str, int]:
    """The directive starting at line i with its continuation lines joined
    (Fortran &, C backslash), and the index of its last line."""
    j, text = i, lines[i]
    while re.search(r"(&|\\)\s*$", lines[j]) and j + 1 < len(lines):
        j += 1
        text = re.sub(r"(&|\\)\s*$", " ", text) + " " + re.sub(
            r"^\s*(?:!\$omp&|!\$acc&|&)", "", lines[j])
    return text, j


def _directive_items(lines: list[str]) -> list[tuple[int, list[str],
                                                     set[str]]]:
    """(first line, from/tofrom item names, the names mapped as a C array
    section) of every directive."""
    out, i = [], 0
    while i < len(lines):
        if _DIRECTIVE.match(lines[i]):
            text, j = _directive_text(lines, i)
            names, raw = [], []
            for m in _FROM_MAP.finditer(text):
                raw.append(m.group(3))
            if re.match(r"^\s*!\$acc", lines[i], re.I):
                for m in _ACC_FROM.finditer(text):
                    raw.append(m.group(1))
            sections = set()
            for r in raw:
                names += _split_items(r)
                if lines[i].lstrip().startswith("#"):
                    sections |= {re.split(r"\[", x.strip(), maxsplit=1)[0]
                                 .strip() for x in _split_raw(r)
                                 if "[" in x}
            out.append((i, names, sections))
            i = j + 1
        else:
            i += 1
    return out


def _split_raw(text: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [x for x in out if x.strip()]


# C directives without an associated statement: the line after them is
# host code
_C_STANDALONE = re.compile(
    r"#\s*pragma\s+omp\s+(?:target\s+(?:enter|exit)\s+data|target\s+update|"
    r"taskwait|barrier|flush|taskyield|depobj|cancel|cancellation|"
    r"interop|error|scan|assume\b|nothing|requires|declare)\b", re.I)
# directives that open a device region (the code inside runs on the device)
_F_DEVICE = re.compile(r"^\s*!\$(?:omp\s+target(?!\s+(?:data|enter|exit|"
                       r"update)\b)|acc\s+(?:parallel|kernels|serial)\b)",
                       re.I)
_F_DEVICE_END = re.compile(r"^\s*!\$(?:omp\s+end\s+target(?!\s+data\b)|"
                           r"acc\s+end\s+(?:parallel|kernels|serial)\b)",
                           re.I)
_C_DEVICE = re.compile(r"^\s*#\s*pragma\s+omp\s+target(?!\s+(?:data|enter|"
                       r"exit|update)\b)", re.I)


def _c_statement_end(lines: list[str], k: int) -> int:
    """Index of the last line of the C statement (a block or a loop)
    starting after line k."""
    depth, k = 0, k + 1
    while k < len(lines):
        depth += lines[k].count("{") - lines[k].count("}")
        if depth <= 0 and (lines[k].rstrip().endswith((";", "}"))):
            break
        k += 1
    return k


def _host_lines(lines: list[str]) -> list[bool]:
    """Per line: whether it is host code of the main program (not a
    module, a function before main or an internal procedure, not inside a
    device region: a target construct, an OpenACC compute construct)."""
    n = len(lines)
    host = [True] * n
    start = next((k for k, ln in enumerate(lines)
                  if re.match(r"^\s*program\b", ln, re.I)
                  or re.match(r"^\s*int\s+main\s*\(", ln)), 0)
    for k in range(start):
        host[k] = False
    contains = next((k for k in range(start, n)
                     if re.match(r"^\s*contains\s*$", lines[k], re.I)), None)
    if contains is not None:
        for k in range(contains, n):
            host[k] = False
    k = start
    while k < n:
        ln = lines[k]
        if _F_DEVICE.match(ln):
            _, j = _directive_text(lines, k)
            e = next((q for q in range(j + 1, n) if _F_DEVICE_END.match(
                lines[q])), None)
            if e is None:  # a combined loop construct without end directive
                e, depth = j + 1, 0
                while e < n:
                    low = lines[e].strip().lower()
                    if re.match(r"do\b", low):
                        depth += 1
                    elif re.match(r"end\s*do\b", low):
                        depth -= 1
                        if depth <= 0:
                            break
                    e += 1
            for q in range(k, min(e, n - 1) + 1):
                host[q] = False
            k = e + 1
        elif _C_DEVICE.match(ln):
            _, j = _directive_text(lines, k)
            e = _c_statement_end(lines, j)
            for q in range(k, min(e, n - 1) + 1):
                host[q] = False
            k = e + 1
        else:
            k += 1
    return host


def _check_text(lines: list[str]) -> str:
    """The host code that computes the check: every line after the last
    OpenMP directive and the region it opens (Fortran: the directive's
    continuation lines; C: the statement or block after the pragma, none
    after a standalone directive such as target exit data), the RESULT
    print excluded."""
    last = max((k for k, ln in enumerate(lines) if _DIRECTIVE.match(ln)),
               default=-1)
    if last < 0:
        return ""
    _, k = _directive_text(lines, last)
    if lines[last].lstrip().startswith("#") and not _C_STANDALONE.match(
            lines[last].lstrip()):
        # skip the statement the pragma applies to (a block or a loop)
        k = _c_statement_end(lines, k)
    return " ".join(ln for ln in lines[k + 1:] if "RESULT" not in ln)


def _assigned_before(lines: list[str], k: int, name: str,
                     section: bool = False, host=None) -> bool:
    """Whether host code of the main program before line k sets `name`:
    an assignment to it, an element or a component of it (Fortran
    ``x(..)``, ``s%c``; C ``x[..][..]``, ``s.c``), a declaration or DATA
    initializer, a call that receives it, memset. A C array `section`
    (``p[0:n]``) needs its elements set: assigning the pointer is not
    enough."""
    n = re.escape(name)
    host = host if host is not None else _host_lines(lines)
    sub = r"(?:\s*(?:\([^=]*?\)|\[[^\]=]*\]|%\s*\w+|\.\s*[A-Za-z_]\w*))"
    elem = rf"{sub}+" if section else rf"{sub}*"
    assign = re.compile(
        rf"(?:^\s*|[;{{)]\s*|\b(?:int|long|double|float|bool|char|unsigned|"
        rf"short|struct\s+\w+)\s+(?:[\w\s,*=\[\]]*,\s*)?\**\s*){n}{elem}"
        rf"\s*=(?!=)", re.M)
    decl = re.compile(rf"::.*\b{n}\s*(?:\([^)]*\))?\s*=(?!=)")
    data = re.compile(rf"^\s*data\b.*\b{n}\b", re.I)
    call = re.compile(rf"^\s*call\s+\w+\s*\(.*\b{n}\b", re.I)
    cfun = re.compile(rf"\b\w+\s*\([^;]*(?<!&)&(?!&)\s*{n}\b|"
                      rf"\bmemset\s*\(\s*{n}\b")
    for q, ln in enumerate(lines[:k]):
        if not host[q]:
            continue
        if assign.search(ln) or data.search(ln) or call.search(ln) \
                or cfun.search(ln):
            return True
        if not section and decl.search(ln):
            return True
    return False


def uninit_from_items(source: str) -> list[str]:
    """Items mapped from or tofrom whose value the check reads and that the
    host never sets before the directive that maps them (sorted; host code
    of the main program only, see _assigned_before)."""
    lines = _live(source)
    check = _check_text(lines)
    host = _host_lines(lines)
    out = set()
    for k, names, sections in _directive_items(lines):
        for name in names:
            if (re.search(rf"\b{re.escape(name)}\b", check)
                    and not _assigned_before(lines, k, name,
                                             name in sections, host)):
                out.add(name)
    return sorted(out)


def uninit_affected(original: str, mutant: str) -> list[str]:
    """The uninitialized from-mapped items of `original` (uninit_from_items)
    that the mutant no longer maps from or tofrom: its check reads them
    without a copy-back."""
    still = {n for _, names in _directive_maps(_live(mutant)) for n in names}
    return [n for n in uninit_from_items(original) if n not in still]
