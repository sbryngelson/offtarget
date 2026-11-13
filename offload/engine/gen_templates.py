"""Fortran templates and per-atom recipes for ``offload.engine.gen``.

Every program has the same frame (``Src.render``): the module ``gen_mod`` when
a recipe needs one, then ``program gen_prog`` with the standard data
(``a(i) = i``, ``b(i) = 0``, host reference ``ref(i)``, ``host_flag = 1``),
a region of interest where the device computes ``b``, and
``ok = all(b == ref)`` plus the recipe's extra checks. The program prints
``RESULT ran_on_host=<0|1> check=<pass|fail>`` and always exits 0.
``host_flag`` is set inside the target region of interest (``region``), or in
a separate probe target region before it where that region may not contain an
OpenMP API call. Programs are deterministic: integers only, n = 64, one
writer per element, order-independent reductions, explicit ``map`` clauses.
Template families (``Region.kind``): ``loop``, ``block``, ``data``,
``declare`` and ``none`` (``requires`` with the standard kernel).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from offload.engine.catalog import (default_grammar, default_skeleton,
                                rule_valid, spelling_valid)
from offload.engine.rules import association, leaves

FLAG = "host_flag = merge(1, 0, omp_is_initial_device())"
BODY = ("b(i) = 2*a(i) + 1",)
STD_MAPS = "map(to: a) map(from: b)"
FLAG_MAP = "map(tofrom: host_flag)"
MAX_LINE = 96
# The host value of an item a region maps back (from) and the
# check reads, set before the region: no thread, team or device number,
# count or ticket the checks accept is negative, so a lost copy-back
# (a mutant, a compiler) fails deterministically instead of being judged
# on uninitialized memory
SENTINEL = -1


class TemplateError(Exception):
    """A recipe could not be built (a generator bug, never data)."""


# --- the frame ----------------------------------------------------------------

@dataclass
class Src:
    """One program before rendering. Lists hold source lines without the
    frame's indentation."""
    module: list = field(default_factory=list)   # gen_mod body (+contains)
    uses: list = field(default_factory=list)     # extra USE statements
    spec: list = field(default_factory=list)     # directives in spec part
    decls: list = field(default_factory=list)
    init: list = field(default_factory=list)     # host setup statements
    region: list = field(default_factory=list)
    post: list = field(default_factory=list)
    checks: list = field(default_factory=list)   # extra logical checks
    ref: str = "2*i + 1"
    observable: bool = True
    note: str = ""
    probe: bool = False
    focus: str = ""   # the clause text that exercises the atom, if any
    std: str = "f2008"
    needs: tuple = ()          # run-time needs (offload.engine.gen.NEEDS)
    evidence: str = "construct"  # offload.engine.gen.EVIDENCE
    expect: str = "result"       # offload.engine.gen.EXPECT
    token: str = ""              # compile-output probes: offload.engine.gen
    header_notes: list = field(default_factory=list)  # extra header lines
    basis: str = ""          # no-oracle programs: catalog/omp/no_oracle.yaml
    legality_rule: str = ""  # legality programs: the rule stem

    def _strip_marks(self):
        self.header_notes = [h for h in self.header_notes if not h.startswith(
            ("unverified (", "no oracle ("))]
        self.basis = ""

    def unverified(self, kind: str, reason: str,
                   checked: bool = False) -> "Src":
        """Mark the program evidence="unverified" (a deterministic
        oracle for behaviour the spec fixes is possible but missing) with
        its header line ``! unverified (<kind>): <reason>``
        (offload.engine.gen.UNVERIFIED). Unless `checked` (the check does test
        what the atom requires), the program is observable=False: it checks
        the device kernel, not the atom."""
        self.evidence = "unverified"
        if not checked:
            self.observable = False
            self.note = "unverified: the check covers the device kernel, " \
                "not the atom"
        self._strip_marks()
        self.header_notes.append(f"unverified ({kind}): {reason}")
        return self

    def no_oracle(self, kind: str, reason: str, basis: str,
                  checked: bool = False) -> "Src":
        """Mark a program whose atom no single run can separate from its
        absence, for the reason the spec gives: evidence `kind`
        (offload.engine.gen.NO_ORACLE: hint_only, implementation_defined,
        equivalent_default), header lines ``! no oracle (<kind>):
        <reason>`` and ``! basis: <cite>: "<quote>"`` (the basis id's
        sentence in catalog/omp/no_oracle.yaml). Unless `checked` (the check
        tests what the atom requires, so a wrong answer is a real failure),
        the program is observable=False."""
        self.evidence = kind
        if not checked:
            self.observable = False
            self.note = f"{kind}: the check covers the device kernel, " \
                "not the atom"
        self._strip_marks()
        self.basis = basis
        self.header_notes.append(f"no oracle ({kind}): {reason}")
        return self

    def presence(self, names, present: bool) -> list[str]:
        """Host statements asserting (into `pres`, checked at the end) that
        each array is (not) present in the default device's data
        environment, in copy mode only.

        Under unified memory (HSA_XNACK=1) AFAR maps nothing and
        omp_target_is_present returns 0 even after target enter data, so
        the assertions are skipped when the frame detects shared storage:
        a target region writes a map(to:) array, and the host sees the
        write only if host and device share the storage. Such programs
        carry evidence copy_mode_only."""
        self.shared_setup()
        op = "/=" if present else "=="
        return [f"if (.not. shared_mem) pres = pres .and. "
                f"omp_target_is_present(c_loc({x}), "
                f"omp_get_default_device()) {op} 0" for x in names]

    def shared_setup(self):
        """`pres` (checked at the end) and `shared_mem` (host and device
        share storage), once per program."""
        if "logical :: pres, shared_mem" not in self.decls:
            self.decls += ["logical :: pres, shared_mem", "integer :: zc(1)"]
            self.init += ["pres = .true.", "zc = 0",
                          omp("target", "map(to: zc)"), "zc(1) = 1",
                          omp("end target"), "shared_mem = zc(1) == 1"]
            self.checks.append("pres")
            self.uses.append("use, intrinsic :: iso_c_binding, only: c_loc")
            self.evidence = "copy_mode_only"

    def copy_check(self, cond: str) -> list[str]:
        """A host statement asserting `cond` (into `pres`) in copy mode only:
        a host value that a data transfer would change (a device write that
        must not come back, a stale device copy). Under unified memory host
        and device share the storage, so the program carries evidence
        copy_mode_only."""
        self.shared_setup()
        return [f"if (.not. shared_mem) pres = pres .and. ({cond})"]

    def address_moved(self, names) -> list[str]:
        """Inside a use_device_addr region: assert (copy mode only) that
        c_loc of each array is no longer its host address, saved as
        h<name> before the region by `save_addresses`."""
        self.shared_setup()
        return [f"if (.not. shared_mem) pres = pres .and. .not. "
                f"c_associated(c_loc({x}), h{x})" for x in names]

    def save_addresses(self, names) -> list[str]:
        self.decls.append("type(c_ptr) :: " + ", ".join(f"h{x}" for x in
                                                        names))
        self.uses.append("use, intrinsic :: iso_c_binding, only: c_ptr, "
                         "c_associated")
        return [f"h{x} = c_loc({x})" for x in names]

    def omp_names(self) -> list[str]:
        """The omp_lib names the program's statements and directives use
        (the ONLY list: a USE without ONLY would hide the program's
        declarations from the restriction rules)."""
        names = {"omp_is_initial_device"}
        for line in self.spec + self.decls + self.init + self.region \
                + self.post:
            low = line.lower()
            if low.lstrip().startswith("!$omp") or \
                    not low.lstrip().startswith("!"):
                names.update(re.findall(r"\b(omp_\w+)", low))
        return sorted(names)

    def render(self, header: list[str]) -> str:
        out = [f"! {h}" for h in header]
        if self.module:
            out += ["module gen_mod", "  implicit none"]
            out += _indent(self.module, 2)
            out += ["end module gen_mod", ""]
        out.append("program gen_prog")
        out.append("  use omp_lib, only: " + ", ".join(self.omp_names()))
        if self.module:
            out.append("  use gen_mod")
        out += _indent(self.uses, 2)
        out.append("  implicit none")
        body = list(self.spec) + [
            "integer, parameter :: n = 64",
            "integer, allocatable, target :: a(:), b(:)",
            "integer :: ref(n)",
            "integer :: i, host_flag",
            "logical :: ok"] + list(self.decls) + [
            "allocate(a(n), b(n))",
            "do i = 1, n",
            "  a(i) = i",
            "  b(i) = 0",
            f"  ref(i) = {self.ref}",
            "end do",
            "host_flag = 1"] + list(self.init) + list(self.region) + list(
            self.post)
        ok = " .and. ".join(["all(b == ref)"] + list(self.checks))
        body += [f"ok = {ok}",
                 "print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, "
                 "' check=', merge('pass', 'fail', ok)",
                 "deallocate(a, b)"]
        out += _indent(body, 2)
        out.append("end program gen_prog")
        return "\n".join(_wrap(line) for line in out) + "\n"


def _indent(lines, n):
    """Indent `lines` by n blanks plus two per open construct (DO, IF ...
    THEN, block and loop directives up to their end directives)."""
    out, depth = [], 0
    for line in lines:
        low = line.strip().lower()
        opens, closes = _opens(low), _closes(low)
        depth -= closes
        out.append(" " * (n + 2 * max(depth, 0)) + line.strip()
                   if line else "")
        depth += opens
    return out


def _opens(low: str) -> int:
    if re.match(r"do(\s|$)", low) or re.match(r"if\s*\(.*\)\s*then$", low) \
            or low.startswith("contains") or re.match(
                r"(integer|logical)\s+function\b|subroutine\b", low) \
            or re.match(r"type\s*::", low):
        return 1
    if low.startswith("!$omp") and not low.startswith("!$omp&"):
        name = _omp_key(low)
        return int(name is not None and association(name) in
                   ("block", "loop"))
    return 0


def _closes(low: str) -> int:
    if re.match(r"end\s*(do|if|function|subroutine|type)\b", low):
        return 1
    if low.startswith("!$omp end"):
        return 1
    return 0


def _omp_key(low: str):
    """Skeleton key of a directive line (not an end directive), or None."""
    from offload.engine.grammar import GrammarError, parse_directive
    if low.startswith("!$omp end"):
        return None
    text = low.rstrip("&").rstrip()
    try:
        return parse_directive(text, "fortran", 60).name
    except GrammarError:
        try:
            return parse_directive(text, "fortran", 52).name
        except GrammarError:
            return None


def _wrap(line: str) -> str:
    """Split a long directive line at clause boundaries (free-form
    continuation: ``&`` at the end, ``!$omp&`` on the next line)."""
    if len(line) <= MAX_LINE or not line.lstrip().lower().startswith("!$omp"):
        return line
    ind = line[:len(line) - len(line.lstrip())]
    parts, depth, cur = [], 0, ""
    for ch in line.strip():
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == " " and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        cur += ch
    parts.append(cur)
    lines, cur = [], ""
    for p in parts:
        if cur and len(ind) + len(cur) + len(p) + 3 > MAX_LINE:
            lines.append(cur)
            cur = "!$omp& " + p
        else:
            cur = f"{cur} {p}" if cur else p
    lines.append(cur)
    return " &\n".join(ind + x for x in lines)


# --- directive facts ------------------------------------------------------------

def spell(key: str, version: int) -> str:
    """A valid spelling of skeleton directive `key` at `version` (blanks
    preferred)."""
    sk, g = default_skeleton(), default_grammar()
    cands = [key, key.replace(" ", "_")] + [
        s.text for s in sk.directive(key).spellings] + [
        e.spelling for e in g.spellings if e.directive == key]
    for c in cands:
        if spelling_valid(sk, g, key, c, version):
            return c
    raise TemplateError(f"no spelling of {key!r} at {version}")


def permits(key: str, clause: str, version: int) -> bool:
    rule = default_grammar().allowed(default_skeleton(), key).get(clause)
    return rule is not None and rule_valid(rule, version)


def tablegen_permits(key: str, clause: str, version: int) -> bool:
    """Whether the TableGen skeleton itself (without spec overrides) allows
    `clause` on `key` at `version`."""
    rule = default_skeleton().directive(key).allowed.get(clause)
    return rule is not None and rule_valid(rule, version)


def hygiene(key: str, version: int, shared) -> str:
    """``default(none) shared(...)`` where the directive allows both. The
    hygiene clause is added only where TableGen allows `default` too: where
    only a provisional spec override allows it (target teams distribute simd
    at 5.2) a compiler may reject it, and the rejection would be read as one
    of the atom under test."""
    if shared and permits(key, "default", version) \
            and tablegen_permits(key, "default", version) \
            and permits(key, "shared", version):
        return f"default(none) shared({', '.join(shared)})"
    return ""


def concurrent(key: str, clauses: str) -> bool:
    """Whether the region may not contain an OpenMP API call."""
    return bool({"loop", "simd", "workdistribute"} & set(leaves(key))) \
        or bool(re.search(r"\border\s*\(", clauses))


def omp(*parts: str) -> str:
    return "!$omp " + " ".join(p for p in parts if p)


def seq_loop(body=BODY, flag=False, var="i"):
    out = [f"do {var} = 1, n"] + ["  " + b for b in body]
    if flag:
        out.append(f"  if ({var} == 1) {FLAG}")
    return out + ["end do"]


def guarded(cond: str, lines) -> list:
    return [f"if ({cond}) then"] + ["  " + x for x in lines] + ["end if"]


# A teams region may not call omp_is_initial_device directly (5.2
# §10.2, p.232: omp_get_num_teams and omp_get_team_num regions are the only
# routine regions that may be strictly nested in it; 6.0 §12.2, p.396: only
# teams-nestable routines, and omp_is_initial_device is not one, §24.9), so
# a teams region reports the device from a one-thread parallel region
# (parallel is teams-nestable).
TEAMS_FLAG = [omp("parallel", "num_threads(1)"), FLAG, omp("end parallel")]


# The probe region: reports the device in host_flag and sets the device
# copy of the declare-target variable on_dev (host copy 0) to 1. The
# construct of interest then computes b(i) = 2*a(i) + on_dev, so a host
# fallback of the construct alone reads the host copy: b = 2*a, the check
# fails and the frame sets host_flag = 1 (PROBE_POST).
PROBE = [omp("target", FLAG_MAP), FLAG, "on_dev = 1", omp("end target")]
# The extended-list form (5.2 §7.8.1, p.206; 6.0 §9.9.1, p.346: as if an
# enter clause were given; 5.0 §2.12.7, p.180: as if a to clause were
# given) is legal at every version and accepted by AFAR and CCE 19 (which
# lacks the enter clause).
PROBE_MODULE = {v: ["integer :: on_dev = 0", "!$omp declare target(on_dev)"]
                for v in (50, 52, 60)}
PROBE_POST = ["if (all(b == 2*a)) host_flag = 1"]


# --- the region of interest ---------------------------------------------------------

@dataclass
class Region:
    """The construct of interest and how it is embedded.

    `clauses` go on the construct of interest; `maps` (and the host_flag
    map) on the outermost target construct; `wrap` are extra clauses for a
    wrapper target construct; `shared` the variables the construct shares
    (for the default(none) hygiene); `loop` replaces the DO loop (a list of
    lines, or a function of `flag` returning lines); `body` the loop body.
    """
    key: str
    clauses: str = ""
    maps: str = STD_MAPS
    wrap: str = ""
    shared: tuple = ("a", "b")
    body: tuple = BODY
    loop: object = None
    hyg: bool = True
    wrapper: str | None = None  # force the wrapper construct
    pre: tuple = ()  # wrapper statements before the construct (nested form)
    # the region may call the OpenMP API although a leaf is simd
    # (simd restricts constructs, not routines, 5.2 §10.4, 6.0 §12.4)
    api: bool = False
    # the loop body of a probe region (default: b(i) = 2*a(i) + on_dev),
    # which must compute b = 2*a + on_dev
    probe_body: tuple = ()

    def lines(self, version: int) -> tuple[list, bool]:
        """(source lines, whether a separate probe region is used)."""
        key, v = self.key, version
        ls = leaves(key)
        sp = spell(key, v)
        conc = concurrent(key, self.clauses) and not self.api
        assoc = association(key)

        def hyg(extra=()):
            if not self.hyg or re.search(r"\bdefault\s*\(", self.clauses):
                return ""
            h = hygiene(key, v, tuple(self.shared) + tuple(extra))
            # 5.0: a sequential loop's variable is predetermined
            # private only in a parallel or task generating construct (5.0
            # §2.19.1.1 p.271; 5.2 adds teams), so under default(none) a
            # teams block lists the DO variable (AFAR -fopenmp-version=50
            # rejects it otherwise)
            if h and v == 50 and assoc != "loop" and "teams" in ls \
                    and "parallel" not in ls:
                h += " private(i)"
            return h

        def loop(flag):
            if self.loop is None:
                return seq_loop(self.body, flag)
            return self.loop(flag) if callable(self.loop) else list(self.loop)

        def probe_loop():
            if self.probe_body:
                return seq_loop(self.probe_body)
            if self.loop is not None or tuple(self.body) != BODY:
                raise TemplateError(f"probe region for {key!r} needs the "
                                    "standard body")
            return seq_loop(("b(i) = 2*a(i) + on_dev",))

        array_probe = "b = 2*a + on_dev"

        def end():
            return [omp("end", sp)]

        if ls[0] == "target":
            inner = ls[1:]
            if assoc == "loop":
                if conc:
                    return PROBE + [omp(sp, self.maps, hyg(["on_dev"]),
                                        self.clauses)] \
                        + probe_loop() + end(), True
                return [omp(sp, self.maps, FLAG_MAP, hyg(["host_flag"]),
                            self.clauses)] + loop(True) + end(), False
            if inner and inner[-1] == "workdistribute":
                return PROBE + [omp(sp, self.maps, hyg(["on_dev"]),
                                    self.clauses), array_probe] + end(), True
            head = omp(sp, self.maps, FLAG_MAP, hyg(["host_flag"]),
                       self.clauses)
            if not inner:
                return [head, FLAG] + loop(False) + end(), False
            cond = {"parallel": "omp_get_thread_num() == 0",
                    "teams": "omp_get_team_num() == 0"}[inner[-1]]
            flag = TEAMS_FLAG if inner[-1] == "teams" else [FLAG]
            return [head] + guarded(cond, flag + loop(False)) + end(), \
                False
        if ls[0] == "teams":
            wrapper = omp("target", self.maps, self.wrap)
            if assoc == "loop":
                if conc:
                    return PROBE + [wrapper, omp(sp, hyg(["on_dev"]),
                                                 self.clauses)] + \
                        probe_loop() + end() + [omp("end target")], True
                return [omp("target", self.maps, FLAG_MAP, self.wrap),
                        omp(sp, hyg(["host_flag"]), self.clauses)] + \
                    loop(True) + end() + [omp("end target")], False
            if ls[-1] == "workdistribute":
                return PROBE + [wrapper, omp(sp, hyg(["on_dev"]),
                                             self.clauses), array_probe] + \
                    end() + [omp("end target")], True
            return [omp("target", self.maps, FLAG_MAP, self.wrap),
                    omp(sp, hyg(["host_flag"]), self.clauses)] + \
                guarded("omp_get_team_num() == 0", TEAMS_FLAG + loop(False)) + \
                end() + [omp("end target")], False
        # a construct nested in a wrapper target region with a statement
        kind = self.wrapper
        if kind is None:
            if ls[0] == "distribute":
                kind = "target teams"
            elif ls[0] == "loop":
                b = re.search(r"\bbind\s*\(\s*(\w+)", self.clauses)
                kind = {"parallel": "target parallel", "thread": "target"}.get(
                    b.group(1) if b else "", "target teams")
            else:
                kind = "target"
        flag = {"target": [FLAG],
                "target teams": guarded("omp_get_team_num() == 0",
                                        TEAMS_FLAG),
                "target parallel": [f"if (omp_get_thread_num() == 0) {FLAG}"]
                }[kind]
        return [omp(kind, self.maps, FLAG_MAP, self.wrap)] + flag + list(
            self.pre) + [omp(sp, hyg(), self.clauses)] + loop(False) + \
            end() + [omp("end", kind)], False


def kernel(src: Src, region: Region, version: int) -> Src:
    lines, probe = region.lines(version)
    src.region += lines
    if probe:
        src.probe = True
        src.module = PROBE_MODULE[version] + src.module
        src.post = PROBE_POST + src.post
        if "workdistribute" in leaves(region.key):
            src.header_notes.append("unverified: no toolchain compiles this "
                                    "(6.0 workdistribute), so the on_dev "
                                    "evidence is untested here")
    if not src.focus:
        src.focus = region.clauses
    return src


DEFAULT_KEY = "target teams distribute parallel do"


# --- recipes -------------------------------------------------------------------------
#
# recipe(atom, version) -> Src. Directive atoms use the directive's own
# family; clause atoms put the clause on a construct that allows it at the
# version, with the context it needs. Each builder states its choice.

def _k(version, region: Region, **src) -> Src:
    return kernel(Src(**src), region, version)


# Compute directives: what the check reads to tell the construct from the
# loop or block run without it.
#
# * distribute / loop forms in a target teams region of num_teams(4) teams
#   (exactly 4: 5.2 §10.2.1, 6.0 §12.2.1): every iteration counts itself in
#   its team's column of cnt (the team number tm, taken in the teams region
#   before the construct, so no API call is needed in a simd or loop
#   region); with the construct each iteration runs once in the league,
#   without it every team runs every iteration (sum 4).
# * teams forms nested in target, with num_teams(4): the region reads
#   omp_get_num_teams(); without the construct it is 1.
# * parallel do: the team size (omp_get_num_threads in the loop) must be
#   more than one whenever a plain parallel region before it got more than
#   one thread (the reference region; a one-thread team is conforming and
#   then nothing is required); without the construct the loop runs on the
#   target's one thread.
LEAGUE = {"distribute", "distribute parallel do",
          "distribute parallel do simd", "distribute simd", "loop"}
TEAMS_N = {"teams", "teams distribute", "teams distribute parallel do",
           "teams distribute simd", "teams distribute parallel do simd"}
# A simd region may call the OpenMP API (simd
# restricts only the constructs in its region to SIMDizable ones, 5.2
# §10.4 p.234, 6.0 §12.4 p.398), so the simd compound forms read the team
# or league like their non-simd counterparts.
SIMD_API = {"parallel do simd", "teams distribute simd",
            "teams distribute parallel do simd"}
# parallel loop and teams loop: the region may not call the
# OpenMP API (a loop construct behaves as if order(concurrent) were
# specified, 5.2 §11.7 / 6.0 §13.8, and such a region may not contain API
# calls, 5.2 §10.3, or only order-concurrent-nestable routines, 6.0 §12.3,
# none of which queries the team or league), and the combined construct
# leaves no statement between its constituents, so who ran the iterations
# is not observable in one run. What is observable is the data environment
# the construct creates: t (mapped tofrom, 7) is private on the construct
# and every iteration writes it; with the construct the target's t stays 7,
# without it (or with the construct run as a plain loop that does not
# privatize) the iterations write the target's t. The check therefore
# shows that the construct and its data environment were created on the
# device, not that more than one thread or team ran the loop.
PRIVATE_LOOP = {"parallel loop", "teams loop"}


def compute_prog(key: str, version: int) -> Src:
    if key in LEAGUE:
        shared = ("a", "b", "cnt", "tm")
        return _k(version, Region(
            key, maps=f"{STD_MAPS} map(tofrom: cnt)",
            wrap="num_teams(4) private(tm)", shared=shared,
            pre=("tm = omp_get_team_num()",),
            body=BODY + ("cnt(i, tm + 1) = cnt(i, tm + 1) + 1",)),
            decls=["integer :: cnt(n, 4), tm"], init=["cnt = 0"],
            checks=["all(sum(cnt, dim=2) == 1)"])
    if key == "teams":
        def loop(flag):
            return ["nt = omp_get_num_teams()"] + seq_loop()
        return _k(version, Region(key, "num_teams(4)",
                                  maps=f"{STD_MAPS} map(from: nt)",
                                  shared=("a", "b", "nt"), loop=loop),
                  decls=["integer :: nt"], init=[f"nt = {SENTINEL}"],
                  checks=["(nt == 4)"],
                  focus="")
    if key in TEAMS_N:
        return _k(version, Region(
            key, "num_teams(4)", maps=f"{STD_MAPS} map(from: nt)",
            shared=("a", "b", "nt"), api=key in SIMD_API,
            body=BODY + ("if (i == 1) nt = omp_get_num_teams()",)),
            decls=["integer :: nt"], init=[f"nt = {SENTINEL}"],
            checks=["(nt == 4)"], focus="")
    if key in ("parallel do", "parallel do simd"):
        return _k(version, Region(
            key, maps=f"{STD_MAPS} map(from: nref, nthr)",
            shared=("a", "b", "nthr"),
            pre=(omp("parallel"),
                 "if (omp_get_thread_num() == 0) nref = omp_get_num_threads()",
                 omp("end parallel")),
            body=BODY + ("if (i == 1) nthr = omp_get_num_threads()",)),
            decls=["integer :: nref, nthr"],
            init=[f"nref = {SENTINEL}", f"nthr = {SENTINEL}"],
            checks=["(nref == 1 .or. nthr > 1)"])
    if key in PRIVATE_LOOP:
        return _k(version, Region(
            key, "private(t)", maps=f"{STD_MAPS} map(tofrom: t)",
            body=("t = 2*a(i)", "b(i) = t + 1"),
            probe_body=("t = 2*a(i)", "b(i) = 2*a(i) + on_dev")),
            decls=["integer :: t"], init=["t = 7"], checks=["(t == 7)"],
            focus="")
    return _k(version, Region(key))


def directive_recipe(key: str, version: int) -> Src:
    if key == "target data":
        return data_prog(version)
    if key == "target enter data" or key == "target exit data":
        return enter_exit_prog(version)
    if key == "target update":
        return update_prog(version)
    if key == "declare target":
        # the extended-list form on a variable: a declare target procedure
        # cannot be told from an implicitly declare target one (see
        # IMPLICIT_PROCEDURE_NOTE), a variable's device copy can
        return declare_var_prog(version, "!$omp declare target(dv)")
    if key == "requires":
        return requires_prog(version, "atomic_default_mem_order(seq_cst)")
    return compute_prog(key, version)


# target data / enter / exit / update ------------------------------------------------

INNER = [omp("target", STD_MAPS, FLAG_MAP), FLAG] + seq_loop() + \
    [omp("end target")]
# The kernel inside a data construct: map(alloc: ...) moves no data, so the
# result depends on the construct's own maps (copy mode); the presence
# assertions of the frame depend on it in every mode where the runtime
# keeps a mapping table.
INNER_ALLOC = [omp("target", "map(alloc: a, b)", FLAG_MAP), FLAG] + \
    seq_loop() + [omp("end target")]


def data_prog(version, clauses="", maps=STD_MAPS, **src):
    """target data around an alloc-mapped kernel; a and b must be present
    inside the region and absent after it."""
    sp = spell("target data", version)
    s = Src(**src)
    s.region += [omp(sp, maps, clauses)] + s.presence(("a", "b"), True) + \
        INNER_ALLOC + [omp("end", sp)] + s.presence(("a", "b"), False)
    s.focus = s.focus or clauses
    return s


def enter_exit_prog(version, enter="map(to: a) map(alloc: b)",
                    exit_="map(from: b) map(release: a)", twice=False,
                    **src):
    """enter data, an alloc-mapped kernel, exit data, with presence
    assertions after each. With `twice`, a is entered a second time
    (reference count 2) before exit data, which must then leave a present
    when it releases a and absent when it deletes a."""
    s = Src(**src)
    ent, ext = spell("target enter data", version), spell("target exit "
                                                          "data", version)
    s.region += [omp(ent, enter)] + s.presence(("a", "b"), True)
    if twice:
        s.region.append(omp(ent, "map(to: a)"))
    s.region += INNER_ALLOC + [omp(ext, exit_)]
    if twice and "release: a" in exit_:
        s.region += s.presence(("a",), True) + [omp(ext, "map(release: a)")]
    s.region += s.presence(("a", "b"), False)
    return s


def update_prog(version, to="to(a)", frm="from(b)", **src):
    """Copy-mode evidence only: under unified memory a missing update
    still gives the right answer (see offload.engine.gen)."""
    s = Src(ref="2*(i + 10) + 1", evidence="copy_mode_only", **src)
    s.region += [omp(spell("target enter data", version),
                     "map(to: a) map(alloc: b)")] + [
        "do i = 1, n", "  a(i) = a(i) + 10", "end do",
        omp(spell("target update", version), to)] + INNER + [
        omp(spell("target update", version), frm),
        omp(spell("target exit data", version), "map(release: a, b)")]
    return s


# declare target ---------------------------------------------------------------------

def proc_list(version: int, name: str = "f") -> str:
    """The list clause of a procedure's declare target directive: ``to`` at
    5.2 (deprecated, still valid) and ``enter`` at 6.0 (``to`` is no longer
    allowed there). CCE 19 rejects ``enter`` (ftn-1725), which at 5.2 would
    otherwise be read as a rejection of the clause under test."""
    return f"to({name})" if version < 60 else f"enter({name})"


def declare_prog(version, var="", func="", body=BODY, maps=STD_MAPS,
                 pre=(), **src):
    """Module gen_mod with variables dv, dw (= 1), the function f(x) =
    2*x + 1 and the host function g; the declare target directive `var` in
    the module's specification part, `func` in f's."""
    s = Src(**src)
    s.module = ["integer :: dv = 1", "integer :: dw = 1"] + (
        [var] if var else []) + [
        "contains", "  integer function f(x)"] + (
        ["    " + func] if func else []) + [
        "    integer, intent(in) :: x", "    f = 2*x + 1",
        "  end function f"] + s.module
    s.region += [omp("target", maps, FLAG_MAP), FLAG] + list(pre) + \
        seq_loop(body) + [omp("end target")]
    return s


def declare_var_prog(version, directive, focus="", data=False):
    """Device-copy oracle for a declare target variable: a first target
    region sets dv = 5 with no map clause, the checked region computes
    b = 2*a + dv - 4 (also with no map of dv). With the directive both
    regions use the one device copy of dv (enter/extended list: allocated
    for the whole program; link: inside a target data region that maps dv
    with `data`; local: a device-local copy). Without it dv is a scalar
    referenced in a target construct, implicitly firstprivate (5.2 §5.8.1,
    6.0 §7.9.3), so the first region's write is lost, dv is 1 in the
    checked region and the check fails, in both memory modes
    (mutation-checked under HSA_XNACK 0 and 1 on AFAR, and on CCE 19 for
    link and the extended list; CCE 19 rejects enter(dv) and local)."""
    s = declare_prog(version, var=directive, body=("b(i) = 2*a(i) + dv - 4",),
                     focus=focus)
    first = [omp("target"), "dv = 5", omp("end target")]
    if data:
        sp = spell("target data", version)
        s.init += [omp(sp, "map(tofrom: dv)")] + first
        s.post.insert(0, omp("end", sp))
    else:
        s.init += first
    return s


# A procedure referenced in a target construct is treated as if it appeared
# in an enter clause (5.2 §13.8 p.285, 6.0 §15.8 p.461), so in a one-file
# program a declare target directive on f changes nothing observable.
IMPLICIT_PROCEDURE_NOTE = (
    "f is implicitly declare target without the directive (a procedure "
    "referenced in a target construct, 5.2 §13.8 p.285, 6.0 §15.8 p.461), "
    "so the clause has no checked effect")


# requires clauses whose programs need memory the device can access
# (under HSA_XNACK=0 AFAR aborts and CCE reports an unsupported requirement)
ZERO_COPY_REQUIRES = ("unified_shared_memory", "self_maps")


def requires_prog(version, clause, **src):
    if clause.split("(")[0] in ZERO_COPY_REQUIRES:
        src.setdefault("needs", ("zero_copy",))
    s = Src(observable=False, note="requires only changes semantics: no "
            "checked device effect", **src)
    s.spec.append(omp("requires", clause))
    s.focus = clause
    return kernel(s, Region(DEFAULT_KEY), version)


# reductions ---------------------------------------------------------------------------

# identifier -> (operator text, type, initial value, update statement)
RED = {
    "plus": ("+", "integer", "0", "{x} = {x} + a(i)"),
    "minus": ("-", "integer", "0", "{x} = {x} - a(i)"),
    "times": ("*", "integer", "1", "{x} = {x} * merge(2, 1, a(i) <= 10)"),
    "max": ("max", "integer", "0", "{x} = max({x}, a(i))"),
    "min": ("min", "integer", "1000", "{x} = min({x}, a(i))"),
    "iand": ("iand", "integer", "-1", "{x} = iand({x}, a(i) + 64)"),
    "ior": ("ior", "integer", "0", "{x} = ior({x}, a(i))"),
    "ieor": ("ieor", "integer", "0", "{x} = ieor({x}, a(i))"),
    "and": (".and.", "logical", ".true.", "{x} = {x} .and. (a(i) > 0)"),
    "or": (".or.", "logical", ".false.", "{x} = {x} .or. (a(i) == n)"),
    "eqv": (".eqv.", "logical", ".true.", "{x} = {x} .eqv. (a(i) > 0)"),
    "neqv": (".neqv.", "logical", ".false.",
             "{x} = {x} .neqv. (mod(a(i), 3) == 0)"),
}


# Logical reductions whose combined value does not show a missing
# privatisation (every contribution is .true.): the original value is
# .false. and the body reads the reduction variable before its update,
# which is the private copy, initialised to the identity .true. (5.2
# §5.5.5, 6.0 §7.6.6); without the reduction the body reads the shared
# .false. and b is wrong.
RED["and"] = (".and.", "logical", ".false.", "{x} = {x} .and. (a(i) > 0)")
RED["eqv"] = (".eqv.", "logical", ".false.", "{x} = {x} .eqv. (a(i) > 0)")
RED_BODY = {"and": ("b(i) = 2*a(i) + merge(1, 5, ls)",),
            "eqv": ("b(i) = 2*a(i) + merge(1, 5, ls)",)}


def red_body(ident):
    """The loop body before the reduction update."""
    return RED_BODY.get(ident, BODY)


# in_reduction on target need not create a private copy (5.2 §5.5.11, 6.0
# §7.6.12: "a private copy may be created"), so its programs cannot read
# the identity: their logical reductions start from .true. and combine to
# .false. instead (a value the target's firstprivate copy, which is what
# the scalar becomes without the clause, never brings back): 17 is the
# one false contribution of and, the 9 multiples of 7 make eqv false.
RED_TASK = {"and": (".and.", "logical", ".true.",
                    "{x} = {x} .and. (a(i) /= 17)"),
            "eqv": (".eqv.", "logical", ".true.",
                    "{x} = {x} .eqv. (mod(a(i), 7) /= 0)")}


def red_vars(ident, table=None):
    """(op, var, declarations, host init + sequential reference, check)."""
    op, typ, init, upd = (table or RED).get(ident, RED[ident])
    x = "s" if typ == "integer" else "ls"
    decls = [f"{typ} :: {x}, {x}ref"]
    host = [f"{x} = {init}", f"{x}ref = {init}", "do i = 1, n",
            "  " + upd.format(x=f"{x}ref"), "end do"]
    check = f"({x} == {x}ref)" if typ == "integer" else f"({x} .eqv. {x}ref)"
    return op, x, decls, host, check, upd.format(x=x)


def reduction_prog(version, ident="plus", modifier="", key=DEFAULT_KEY,
                   hyg=True):
    op, x, decls, host, check, upd = red_vars(ident)
    mod = f"{modifier}, " if modifier else ""
    clause = f"reduction({mod}{op}: {x})"
    return _k(version, Region(key, clause, maps=f"{STD_MAPS} map(tofrom: {x})",
                              body=red_body(ident) + (upd,), hyg=hyg),
              decls=decls, init=host, checks=[check], focus=clause)


def in_reduction_prog(version, ident="plus"):
    op, x, decls, host, check, upd = red_vars(ident, RED_TASK)
    clause = f"in_reduction({op}: {x})"
    s = Src(decls=decls, init=host, checks=[check], focus=clause)
    s.region += [omp("taskgroup", f"task_reduction({op}: {x})"),
                 omp("target", STD_MAPS, FLAG_MAP, clause), FLAG] + \
        seq_loop(BODY + (upd,)) + [omp("end target"), omp("end taskgroup")]
    return s


def task_reduction_prog(version):
    """reduction(task, ...) on a worksharing-loop construct in a parallel
    region in the target region (the do and its end directive are
    separate, for the nowait transform of reduction-clause-005)."""
    op, x, decls, host, check, upd = red_vars("plus")
    clause = f"reduction(task, {op}: {x})"
    s = Src(decls=decls, init=host, checks=[check], focus=clause)
    s.region += [omp("target", STD_MAPS, FLAG_MAP, f"map(tofrom: {x})"),
                 FLAG, omp("parallel", f"default(none) shared(a, b, {x})"),
                 omp("do", clause)] + seq_loop(BODY + (upd,)) + [
        omp("end do"), omp("end parallel"), omp("end target")]
    return s


def inscan_prog(version):
    """An inclusive scan: b(i) = a(1) + ... + a(i)."""
    def loop(flag):
        return ["do i = 1, n", "  s = s + a(i)", "  " + omp("scan",
                "inclusive(s)"), "  b(i) = s", "end do"]
    clause = "reduction(inscan, +: s)"
    return _k(version, Region("parallel do", clause,
                              maps=f"{STD_MAPS} map(tofrom: s)", loop=loop),
              decls=["integer :: s"], init=["s = 0"], ref="i*(i + 1)/2",
              focus=clause)


# shared helpers ----------------------------------------------------------------------

def pdo(version, clauses, **kw) -> Src:
    """The clause on parallel do in a target region."""
    src = {k: kw.pop(k) for k in list(kw) if k in Src.__dataclass_fields__}
    return _k(version, Region("parallel do", clauses, **kw), **src)


def pdo_simd(version, clauses, **kw) -> Src:
    src = {k: kw.pop(k) for k in list(kw) if k in Src.__dataclass_fields__}
    return _k(version, Region("parallel do simd", clauses, **kw), **src)


def combined(version, clauses, key=DEFAULT_KEY, **kw) -> Src:
    src = {k: kw.pop(k) for k in list(kw) if k in Src.__dataclass_fields__}
    return _k(version, Region(key, clauses, **kw), **src)


def collapse_loop(flag):
    """A 2 x 32 nest over b; each iteration records the thread that ran it
    (tid) and iteration (1, 1) the team size (nthr)."""
    idx = "(j - 1)*32 + k"
    return ["do j = 1, 2", "  do k = 1, 32",
            f"    b({idx}) = 2*a({idx}) + 1",
            f"    tid({idx}) = omp_get_thread_num()",
            "    if (j == 1 .and. k == 1) nthr = omp_get_num_threads()",
            "  end do", "end do"]


def count_owners(arr: str, var: str, upto: str) -> list[str]:
    """Host statements: `var` = how many of the values 0 .. upto-1 occur
    in `arr` (the threads or teams that ran at least one iteration)."""
    return [f"{var} = 0", f"do i = 0, {upto} - 1",
            f"  if (any({arr} == i)) {var} = {var} + 1", "end do"]


def blocked(arr: str, m: str, parts: str, var: str) -> list[str]:
    """Host statements: `var` = what the static schedule without a chunk
    size guarantees for the m iterations recorded in `arr` (owner per
    iteration; the owners are the `parts` threads or teams): every
    iteration ran on a maintainer 0 .. parts - 1 (its slot holds a maintainer
    number, not the sentinel), and each owner's iterations are one
    contiguous run. The spec text: chunks are "contiguous non-empty subsets"
    and "at most one chunk is distributed to each thread" (5.2 §11.5.3
    p.252; dist_schedule: each initial team, §11.6.1 p.256; 5.0 §2.9.2
    p.103 (chunks), p.104 (Table 2.5), §2.9.4.1 p.122; 6.0 §13.6.3 p.418,
    §13.7.1 p.422, contiguity from the Glossary "chunk" p.31). Nothing about the chunk
    sizes is checked: "approximately equal" is illustrated by the Note
    (5.2 §11.5.3 p.253, 5.0 §2.9.2 p.105) with two compliant
    implementations, chunks of ceil(n/p) (the last shorter) and q / q - 1
    splits, and neither the number of chunks nor their order over the
    owners is fixed."""
    return [f"{var} = all({arr} >= 0 .and. {arr} < {parts})",
            f"do i = 2, {m}",
            f"  if ({arr}(i) /= {arr}(i - 1)) {var} = {var} .and. "
            f".not. any({arr}(1:i - 1) == {arr}(i))", "end do"]


def round_robin(arr: str, m: str, chunk: int, parts: str,
                var: str) -> list[str]:
    """Host statements: `var` = whether iteration i ran on owner
    mod((i - 1)/chunk, parts): chunks of `chunk` iterations assigned to
    the owners round-robin in the order of their number (schedule(static,
    c), dist_schedule(static, c))."""
    return [f"{var} = .true.", f"do i = 1, {m}",
            f"  {var} = {var} .and. {arr}(i) == mod((i - 1)/{chunk}, "
            f"{parts})", "end do"]


# The schedule programs run a loop of m = 1000 iterations (b is written by
# the first n), more than the team of either toolchain has threads, so the
# assignment of iterations to threads shows the schedule.
SCHED_M = 1000


def schedule_prog(version, clause, chunk=None):
    """schedule(static[, chunk]) on parallel do in a target region: each
    iteration records its thread; the static schedule fixes the assignment
    (5.2 §11.5.3, 6.0 §13.6.3: without a chunk size one chunk of
    approximately m/T iterations per thread, with chunk size c chunks of c
    assigned round-robin in thread order)."""
    def loop(flag):
        return ["do i = 1, m", "  if (i <= n) b(i) = 2*a(i) + 1",
                "  if (i == 1) nthr = omp_get_num_threads()",
                "  tid(i) = omp_get_thread_num()", "end do"]
    check = blocked("tid", "m", "nthr", "sok") if chunk is None else \
        round_robin("tid", "m", chunk, "nthr", "sok")
    s = pdo(version, clause, loop=loop,
            maps=f"{STD_MAPS} map(from: tid, nthr)",
               shared=("a", "b", "tid", "nthr"),
               decls=[f"integer, parameter :: m = {SCHED_M}",
                      "integer :: tid(m), nthr", "logical :: sok"],
               init=[f"tid = {SENTINEL}", f"nthr = {SENTINEL}"],
               post=check, checks=["(nthr >= 1)", "sok"])
    if chunk is None:
        # See STATIC_NO_CHUNK_WHY
        s.no_oracle("implementation_defined", STATIC_NO_CHUNK_WHY,
                    "schedule_default", checked=True)
    return s


def team_param(version, clause, record, decls, check, key=DEFAULT_KEY,
               extra_decls=(), extra_shared=(), **kw):
    """`clause` on `key` (a target construct); iteration 1 (or every
    iteration) records what the clause controls with an OpenMP API call
    (`record`, lines of the loop body), checked on the host (`check`).
    `extra_shared`: variables of a clause expression evaluated inside an
    outer leaf, listed under default(none)."""
    names = [d.split("::")[1].strip() for d in decls]
    names = [x.split("(")[0] for n in names for x in n.split(", ")]
    # Every recorded item starts at the sentinel, which the
    # check rejects, so a lost copy-back fails deterministically
    kw["init"] = list(kw.get("init", [])) + [f"{x} = {SENTINEL}"
                                             for x in names]
    return combined(version, clause, key=key, body=BODY + tuple(record),
                    maps=f"{STD_MAPS} map(from: {', '.join(names)})",
                    shared=("a", "b") + tuple(names) + tuple(extra_shared),
                    decls=list(decls) + list(extra_decls),
                    checks=list(check), **kw)


def linear_prog(version, clause, var="x", step=1):
    """x is linear with `step`: at the start of iteration i it is
    3 + step*(i - 1) (the body adds the step, so the value at the end of
    an iteration is the next one's), and n*step + 3 after the loop."""
    body = (f"b(i) = 2*a(i) + 1 + ({var} - ({step}*i + {3 - step}))",
            f"{var} = {var} + {step}")
    return pdo(version, clause, maps=f"{STD_MAPS} map(tofrom: {var})",
               body=body, decls=[f"integer :: {var}"], init=[f"{var} = 3"],
               checks=[f"({var} == {step}*n + 3)"])


def linear_simd_decl_prog(version, mod):
    """ref / uval are allowed only on declare simd (5.2 §5.4.6, 6.0
    §7.5.6): a declare simd function called in the target region. 5.0
: the modifier(list) syntax, and every modifier (val too) is
    for declare simd only, since the worksharing-loop and simd constructs
    take none (5.0 §2.9.2 p.107, §2.9.3.1 p.113); a ref list item must not
    be an assumed-shape array (5.0 §2.19.4.6 p.293), so x is a scalar
    dummy argument."""
    ds = spell("declare simd", version)
    if version == 50:
        func = ["  integer function lf(x)", "    " + omp("declare target"),
                "    " + omp(f"{ds}(lf)", f"linear({mod}(x))"),
                "    integer, intent(in) :: x",
                "    lf = 2*x + 1", "  end function lf"]
        s = Src(module=["contains"] + func, focus=f"linear({mod}(x))",
                note=f"linear({mod}(x)) on a declare simd directive; the "
                "SIMD variant need not be called", observable=False)
        s.region += [omp("target", STD_MAPS, FLAG_MAP), FLAG] + seq_loop(
            ("b(i) = lf(a(i))",)) + [omp("end target")]
        return s
    if mod == "ref":
        func = ["  integer function lf(x)", "    " + omp("declare target"),
                "    " + omp(f"{ds}(lf)", "linear(x: ref)"),
                "    integer, intent(in) :: x(:)",
                "    lf = 2*x(1) + 1", "  end function lf"]
        body = ("b(i) = lf(a(i:i))",)
    else:
        func = ["  integer function lf(x)", "    " + omp("declare target"),
                "    " + omp(f"{ds}(lf)", "linear(x: uval)"),
                "    integer, intent(in) :: x",
                "    lf = 2*x + 1", "  end function lf"]
        body = ("b(i) = lf(a(i))",)
    s = Src(module=["contains"] + func, focus=f"linear(x: {mod})",
            note=f"linear({mod}) on a declare simd directive; the SIMD "
            "variant need not be called", observable=False)
    s.region += [omp("target", STD_MAPS, FLAG_MAP), FLAG] + seq_loop(body) + \
        [omp("end target")]
    return s


def defaultmap_prog(version, mtype, cat=""):
    """defaultmap on target; the region writes the implicitly mapped
    variables of the category (scalar c, array w, allocatable wa, pointer
    wp) before reading them. What tells the clause from its absence (a
    scalar is firstprivate and an array tofrom without it):

    * tofrom / from on a category with the scalar c: the device's c = 1
      comes back to the host (both memory modes);
    * to / alloc on the arrays: the device's writes stay on the device, so
      the host copy is unchanged (copy mode only);
    * present: c and w are present (enter data) with values the host then
      changes without an update: the region must use the device copies
      (copy mode only; without the clause c is firstprivate, the host's).
    """
    clause = f"defaultmap({mtype}: {cat})" if cat else f"defaultmap({mtype})"
    decls = ["integer :: c", "integer :: w(n)"]
    init, post, pre = [], [], []
    arr = None
    if mtype == "none":
        pre, body = [], BODY
    elif mtype == "present":
        body = ("b(i) = w(i) + c",)
    elif cat == "scalar":
        pre, body = ["c = 1"], ("b(i) = 2*a(i) + c",)
    elif cat == "allocatable":
        decls.append("integer, allocatable :: wa(:)")
        init, post = ["allocate(wa(n))", "wa = 0"], ["deallocate(wa)"]
        body, arr = ("wa(i) = 2*a(i)", "b(i) = wa(i) + 1"), "wa"
    elif cat == "pointer":
        decls.append("integer, pointer :: wp(:)")
        init, post = ["allocate(wp(n))", "wp = 0"], ["deallocate(wp)"]
        body, arr = ("wp(i) = 2*a(i)", "b(i) = wp(i) + 1"), "wp"
    elif cat == "aggregate":
        body, arr = ("w(i) = 2*a(i)", "b(i) = w(i) + 1"), "w"
    else:  # all variables / no category: a scalar and an aggregate
        pre, body = ["c = 1"], ("w(i) = 2*a(i)", "b(i) = w(i) + c")
        arr = "w"
    init = ["c = 0", "w = 0"] + init
    s = Src(decls=decls, init=init, post=post, focus=clause)
    if mtype == "present":
        ent = spell("target enter data", version)
        ext = spell("target exit data", version)
        s.shared_setup()
        s.init += ["c = 1", "w = 2*a", omp(ent, "map(to: c, w)"),
                   "if (.not. shared_mem) then", "  c = 7", "  w = 0",
                   "end if"]
        s.post.insert(0, omp(ext, "map(release: c, w)"))
    if mtype in ("tofrom", "from") and cat in ("", "scalar"):
        s.checks.append("(c == 1)")
    if mtype in ("to", "alloc") and arr is not None:
        s.post[0:0] = s.copy_check(f"all({arr} == 0)")
    if mtype == "self":
        s.note = ("self maps the original storage: needs memory the device "
                  "can access (zero-copy)")
        s.needs = ("zero_copy",)
    # i is predetermined private (5.2 §5.1.1); listed anyway under
    # defaultmap(none), which AFAR otherwise rejects, and defaultmap(present),
    # under which AFAR's runtime otherwise requires i to be present
    # ("device mapping required by 'present' ... (4 bytes)") and aborts
    extra = "private(i)" if mtype in ("none", "present") else ""
    s.region += [omp("target", STD_MAPS, FLAG_MAP, clause, extra),
                 FLAG] + pre + seq_loop(body) + [omp("end target")]
    return s


def defaultmap_character_prog(version):
    """omp.clause.defaultmap.character (a semantic atom): no
    defaultmap clause; the target region writes a character scalar ch, a
    character(len=4) s and an integer scalar k. For Fortran a variable of
    character type is an aggregate, not a scalar (5.2 §1.2.6 p.14, 6.0
    Glossary pp.20, 94), so ch and s are implicitly mapped tofrom and the
    device's writes come back (5.2 §5.8.1 p.148, 6.0 §7.9.3 p.277); k is a
    scalar without TARGET, ALLOCATABLE or POINTER, so it is firstprivate and
    the host's k stays 1. Both memory modes: under unified memory a tofrom
    map shares the storage (the write is seen) and firstprivate is still a
    private copy. A host fallback writes k too (check fails)."""
    s = Src(decls=["character :: ch", "character(len=4) :: s", "integer :: k"],
            init=["ch = 'a'", "s = 'abcd'", "k = 1"],
            checks=["(ch == 'b')", "(s == 'wxyz')", "(k == 1)"],
            focus="implicit data-mapping of character variables (no "
                  "defaultmap clause)")
    s.header_notes.append(
        "semantic atom: no defaultmap clause; Fortran character variables "
        "are aggregates (implicitly mapped tofrom), the integer scalar k is "
        "firstprivate")
    s.region += [omp("target", STD_MAPS, FLAG_MAP), FLAG,
                 "ch = 'b'", "s = 'wxyz'", "k = 2"] + seq_loop() + [
        omp("end target")]
    return s


# Device spin of the producer target task: about one second of
# integer work on the MI300A (AFAR and CCE), long enough for a consumer
# target task that ignores the dependence to run first.
DEPEND_SPIN = 20000000


def _depend_clauses(s: Src, first: str, second: str) -> tuple[str, str]:
    d1 = f"depend({first}: w)"
    d2 = f"depend({second}: w)"
    if first == "iterator":
        s.decls.append("integer :: k")
        d1 = "depend(iterator(k = 1:n), out: w(k))"
        d2 = "depend(iterator(k = 1:n), in: w(k))"
    if first == "depobj":
        s.decls.append("integer(omp_depend_kind) :: obj")
        s.init.append(omp("depobj(obj)", "depend(out: w)"))
        d1 = "depend(depobj: obj)"
    return d1, d2


def depend_prog(version, first="out", second="in", writer=False):
    """Device only: two target tasks ordered only by a dependence
    on w. The producer (`first` dependence, target nowait) spins on the
    device for about a second (DEPEND_SPIN iterations; the spin value goes
    to spin(1), so it cannot be optimised away) and then writes w = 2*a;
    the consumer (`second` dependence, target nowait) maps w to the device
    and computes b = w + 1; a taskwait completes both. Without the
    dependence a runtime that runs the two target tasks concurrently gives
    the consumer w before the producer's write (w = 0, or a partial w) and
    the check fails; a runtime that runs each target task to completion
    when it is encountered cannot fail it (the audit says which toolchain
    does what). w is mapped tofrom by the producer and to by the consumer,
    so the order also holds in copy mode. `writer` (the dependence types a
    producer carries: out, inout, inoutset, mutexinoutset): the producer
    also has a dependence of another type on a token tk, so that its mutant
    keeps a depend clause: CCE's C runtime starts the consumer's
    depend(in) task only after a producer without any depend clause has
    finished (the mutant survived), not after one with a dependence on
    something else."""
    s = Src(decls=["integer :: w(n)", "integer :: j, sp, spin(1)"],
            init=["w = 0", "spin = 0"])
    d1, d2 = _depend_clauses(s, first, second)
    if writer:
        s.decls.append("integer :: tk")
        s.init.append("tk = 0")
        d1 += f" depend({'out' if first == 'inout' else 'inout'}: tk)"
    s.region += [omp("target", "nowait", "map(to: a) map(tofrom: w)",
                     "map(from: spin)", d1),
                 "sp = 1", f"do j = 1, {DEPEND_SPIN}",
                 "  sp = mod(7*sp + j, 1000003)", "end do", "spin(1) = sp",
                 "do j = 1, n", "  w(j) = 2*a(j)", "end do",
                 omp("end target"),
                 omp("target", "nowait", "map(to: w) map(from: b)", FLAG_MAP,
                     d2), FLAG] + \
        seq_loop(("b(i) = w(i) + 1",)) + [omp("end target"), omp("taskwait")]
    if first == "depobj":
        s.post.append(omp("depobj(obj)", "destroy"))
    s.header_notes.append(
        "device only: the dependence orders two target tasks (target nowait "
        "producer and consumer, completed by taskwait)")
    s.focus = d2 if first == "out" and second == "in" else d1
    return s


# The realistic use each host+device pattern stands for (owner
# exception): its header line ``! scope: host+device: <use>``.
DEPEND_HOST_USE = ("CPU producer / GPU consumer pipeline: a host task "
                   "prepares data (depend(out)) that a dependent target task "
                   "consumes on the device (depend(in)), as in task-based "
                   "codes that overlap host preprocessing with offload")
THREADS_USE = ("multi-threaded offload: host threads (one per chunk, as in "
               "MPI+OpenMP or task-parallel host codes) each launch their "
               "own target region on the same device")
THREADS_NOWAIT_USE = ("multi-threaded asynchronous offload: host threads "
                      "each launch a target nowait region on the same "
                      "device; the parallel region's end completes the "
                      "target tasks")


def depend_host_prog(version, first="out", second="in"):
    """host+device pattern (the earlier depend programs): a
    host task and a target task generated in a host parallel region's
    single construct, ordered only by a dependence on w: the task (`first`
    dependence) spins for 0.5 s of wall time before writing w = 2*a on the
    host, the target task (`second` dependence) maps w to the device and
    computes b = w + 1. Without the dependence the target task maps the
    host's w, still 0, while the task spins, and the check fails (a
    runtime that runs the task at once, undeferred, cannot fail it). The
    spin is on the host clock, so the ordering does not depend on how the
    device schedules its kernels. Judged on the device result (b, and
    ran_on_host from the target task)."""
    s = Src(decls=["integer :: w(n)", "double precision :: t0"],
            init=["w = 0"])
    d1, d2 = _depend_clauses(s, first, second)
    s.region += [omp("target", "map(tofrom: w)"), "w(1) = 0",
                 omp("end target"),
                 omp("parallel", "num_threads(2)"), omp("single"),
                 omp("task", d1),
                 "t0 = omp_get_wtime()",
                 "do while (omp_get_wtime() - t0 < 0.5d0)", "end do",
                 "w = 2*a", omp("end task"),
                 omp("target", "map(to: w) map(from: b)", FLAG_MAP, d2),
                 FLAG] + \
        seq_loop(("b(i) = w(i) + 1",)) + [omp("end target"), omp("taskwait"),
                                          omp("end single"),
                                          omp("end parallel")]
    if first == "depobj":
        s.post.append(omp("depobj(obj)", "destroy"))
    s.header_notes.append(f"scope: host+device: {DEPEND_HOST_USE}")
    s.focus = d2 if first == "out" and second == "in" else d1
    return s


def threads_offload_prog(version, nowait=False):
    """host+device pattern: a host parallel do over four chunks of
    b; each iteration (one host thread each, num_threads(4)) launches its
    own target region for its chunk (`nowait`: a target nowait region,
    completed by the parallel region's end). Each target region reports
    the device into hf(c); the check is the device result b and
    ran_on_host = 1 when any hf(c) is 1.

    A and b (and hf) are mapped whole once, by target enter data
    before the parallel region, and copied back by target exit data after
    it. The form mapped each thread's sections (map(to: a(lo:hi))
    map(from: b(lo:hi))) on the threads' target constructs; the target
    region references the whole arrays, so they are also implicitly
    mapped (5.2 §5.8.1), and once sections created by two earlier
    constructs are present when a third thread's construct maps the array
    "the behavior is unspecified" (5.2 §5.8.3 p.155; 6.0 §7.9.6 p.286:
    the storage "must correspond to a single mappable storage block").
    Without nowait each thread moves its own section with target update
    (to before, from after its region)."""
    c = "nowait" if nowait else ""
    s = Src(decls=["integer :: c, lo, hi, hf(4)"], init=["hf = 1"])
    if nowait:
        enter = omp("target enter data", "map(to: a, hf) map(alloc: b)")
        exit_ = omp("target exit data", "map(from: b, hf) map(release: a)")
        before, after = [], []
    else:
        enter = omp("target enter data", "map(alloc: a, b) map(to: hf)")
        exit_ = omp("target exit data", "map(from: hf) map(release: a, b)")
        before = ["  " + omp("target update", "to(a(lo:hi))")]
        after = ["  " + omp("target update", "from(b(lo:hi))")]
    s.region += [enter, omp("parallel do", "num_threads(4) private(lo, hi)"),
                 "do c = 1, 4", "  lo = (c - 1)*16 + 1", "  hi = c*16"] \
        + before + ["  " + omp("target", c),
                    "    hf(c) = merge(1, 0, omp_is_initial_device())",
                    "    do i = lo, hi", "      b(i) = 2*a(i) + 1",
                    "    end do", "  " + omp("end target")] + after \
        + ["end do", omp("end parallel do"), exit_, "host_flag = 0",
           "do c = 1, 4", "  if (hf(c) == 1) host_flag = 1", "end do"]
    s.header_notes.append("scope: host+device: " + (
        THREADS_NOWAIT_USE if nowait else THREADS_USE))
    s.focus = c or "target"
    return s


# CCE 19 does not run target nowait tasks synchronously (it
# kills every depend mutant: without the dependence the consumer target
# task reads the producer's output before it is written; audit);
# AFAR completes each one before the next outside a parallel region (it
# survives them)
NOWAIT_WHY = ("an implementation may run a target nowait task synchronously "
              "(AFAR does outside a parallel region; CCE 19 runs two of them "
              "concurrently, as the depend programs show), so no single run "
              "of a conforming program can tell nowait from its absence")


def device_ptr_prog(version, data_extra=""):
    """use_device_ptr on target data, is_device_ptr on the target inside.
    5.0: an is_device_ptr list item must be a dummy argument
    without the ALLOCATABLE, POINTER or VALUE attribute (5.0 §2.12.5
    p.176), so the target region is in a module subroutine whose dummy
    arguments are the two pointers."""
    sp = spell("target data", version)
    if version == 50:
        s = Src(uses=["use, intrinsic :: iso_c_binding, only: c_ptr, c_loc"],
                decls=["type(c_ptr) :: pa, pb"],
                init=["pa = c_loc(a)", "pb = c_loc(b)"],
                needs=("device_c_f_pointer",), evidence="copy_mode_only")
        s.module = ["contains", "  subroutine dev_kernel(pa, pb, m, hf)",
                    "    use omp_lib, only: omp_is_initial_device",
                    "    use, intrinsic :: iso_c_binding, only: c_ptr, "
                    "c_f_pointer",
                    "    type(c_ptr) :: pa, pb",
                    "    integer :: m, hf, i",
                    "    integer, pointer :: pp(:), qq(:)",
                    "    " + omp("target", "is_device_ptr(pa, pb)",
                                 "private(pp, qq)", "map(tofrom: hf)"),
                    "    hf = merge(1, 0, omp_is_initial_device())",
                    "    call c_f_pointer(pa, pp, [m])",
                    "    call c_f_pointer(pb, qq, [m])",
                    "    do i = 1, m", "      qq(i) = 2*pp(i) + 1",
                    "    end do", "    " + omp("end target"),
                    "  end subroutine dev_kernel"]
        s.region += [omp(sp, STD_MAPS, "use_device_ptr(pa, pb)", data_extra),
                     "call dev_kernel(pa, pb, n, host_flag)", omp("end", sp)]
        return s
    s = Src(uses=["use, intrinsic :: iso_c_binding, only: c_ptr, c_loc, "
                  "c_f_pointer"],
            decls=["type(c_ptr) :: pa, pb", "integer, pointer :: pp(:), qq(:)"],
            init=["pa = c_loc(a)", "pb = c_loc(b)"],
            needs=("device_c_f_pointer",), evidence="copy_mode_only")
    s.region += [omp(sp, STD_MAPS, "use_device_ptr(pa, pb)", data_extra),
                 omp("target", "is_device_ptr(pa, pb)", "private(pp, qq)",
                     FLAG_MAP), FLAG,
                 "call c_f_pointer(pa, pp, [n])",
                 "call c_f_pointer(pb, qq, [n])"] + seq_loop(
        ("qq(i) = 2*pp(i) + 1",)) + [omp("end target"), omp("end", sp)]
    return s


def device_addr_prog(version, data_extra=""):
    """use_device_addr on target data, has_device_addr on the target
    inside. Inside the data region c_loc(a) must differ from a's host
    address (checked in copy mode only: under unified memory the device
    address is the host address). 5.0 has no has_device_addr: an
    outer target data maps a and b, an inner one with use_device_addr(a, b)
    holds the address check, and the kernel follows it in the outer region
    (a and b present)."""
    s = Src(evidence="copy_mode_only")
    sp = spell("target data", version)
    if version == 50:
        s.region += s.save_addresses(("a", "b")) + [
            omp(sp, STD_MAPS), omp(sp, "use_device_addr(a, b)", data_extra)] \
            + s.address_moved(("a", "b")) + [omp("end", sp),
                                             omp("target", FLAG_MAP), FLAG] \
            + seq_loop() + [omp("end target"), omp("end", sp)]
        return s
    s.region += s.save_addresses(("a", "b")) + [
        omp(sp, STD_MAPS, "use_device_addr(a, b)", data_extra)] + \
        s.address_moved(("a", "b")) + [
            omp("target", "has_device_addr(a, b)", FLAG_MAP), FLAG] + \
        seq_loop() + [omp("end target"), omp("end", sp)]
    return s


def mapper_prog(version):
    """The mapper maps s%v with map type to; the clause invoking it says
    tofrom, and the decayed map type is to (5.2 Table 5.3, 6.0 map-type
    decay): the region's write of s%v stays on the device (copy mode).
    Without the mapper modifier the default mapper maps s tofrom and the
    write comes back."""
    dm = spell("declare mapper", version)
    c = "map(mapper(mm), tofrom: s)"
    s = Src(spec=["type :: dt", "  integer :: v", "end type dt",
                  omp(f"{dm}(mm: dt :: q)", "map(to: q%v)")],
            decls=["type(dt) :: s"], init=["s%v = 1"], focus=c)
    s.region += [omp("target", STD_MAPS, c, FLAG_MAP), FLAG] + seq_loop(
        ("b(i) = 2*a(i) + s%v",)) + ["s%v = 7", omp("end target")]
    s.post += s.copy_check("s%v == 1")
    return s


def ancestor_prog(version, modifier="ancestor: 1"):
    """A reverse-offload region (device(ancestor: 1)) inside a target
    region. Its body has no checked effect: no OpenMP construct or API call
    may appear in it (5.2 §13.8, 6.0 §15.8)."""
    s = Src(spec=[omp("requires", "reverse_offload")],
            decls=["integer :: t"], init=["t = 0"], observable=False,
            note="the reverse-offload region has no checked effect",
            focus=f"device({modifier})")
    s.region += [omp("target", STD_MAPS, FLAG_MAP), FLAG] + seq_loop() + [
        omp("target", f"device({modifier})", "firstprivate(t)"),
        "t = t + 1", omp("end target"), omp("end target")]
    return s


def alloc_prog(version, alloc_clause, wrap="uses_allocators("
               "omp_default_mem_alloc)", decls=(), shared=("a", "b")):
    """`shared` names the variables the parallel do shares under the
    default(none) hygiene; an allocator handle variable named in the
    allocate clause must be among them (CCE 19 ftn-1510)."""
    return pdo(version, f"private(t) {alloc_clause}", wrap=wrap,
               body=("t = 2*a(i)", "b(i) = t + 1"), shared=tuple(shared),
               decls=["integer :: t"] + list(decls), focus=alloc_clause)


TRAITS = ["integer(omp_allocator_handle_kind) :: my_alloc",
          "type(omp_alloctrait), parameter :: my_traits(1) = &",
          "  [omp_alloctrait(omp_atk_alignment, 64)]"]


# --- clause atoms -----------------------------------------------------------------

# message/severity on a compute construct (the
# re-audit with AFAR's -fopenmp-version=60 shows the mutant survives).
def error_probe(version, sev):
    """Message and severity (6.0) on an error
    directive with at(compilation) in a target region (before,
    the main program's specification part), message PROBE_TOKEN: with
    severity(warning) the compiler must show the message and go on
    (expect compile_message; the program then runs the standard kernel),
    with severity(fatal) it must stop the compilation (expect
    compile_error) (6.0 §10.1 error directive, §10.3 message, §10.4
    severity). Mutants: the message removed (the token disappears), the
    severity removed (fatal by default: the compile stops), fatal replaced
    by warning (the compile goes on)."""
    from offload.engine.gen import PROBE_TOKEN
    c = f'message("{PROBE_TOKEN}")'
    s = Src(evidence="probe", token=PROBE_TOKEN,
            expect="compile_error" if sev == "fatal" else "compile_message",
            focus=f"severity({sev})")
    s.header_notes.append(
        "compile-output probe: the error directive's message must appear in "
        "the compiler output " + ("and stop the compilation (fatal)"
                                  if sev == "fatal" else
                                  "as a warning, and the compilation go on"))
    # The error directive is in the target region (device code),
    # not in the host program's specification part
    s.region += [omp("target", STD_MAPS, FLAG_MAP),
                 omp("error", "at(compilation)", f"severity({sev})", c),
                 FLAG] + seq_loop() + [omp("end target")]
    return s


# message/severity on parallel do: the directive-name family members keep
# this form (offload.engine.gen._DNM_RECIPE)
ERROR_CLAUSE_WHY = ("message and severity on parallel act only when a "
                    "num_threads(strict: n) request cannot be met (6.0 "
                    "§12.1.2: error termination as if by an error directive "
                    "with these clauses); neither AFAR nor CCE 19 accepts "
                    "the strict modifier (omp.clause.num_threads.strict is "
                    "rejected by both), so no program can trigger them here, "
                    "and a passing program raises no error")
# The present modifiers as negative probes: an absent item with
# present requires runtime error termination (5.2 §5.8.3 p.152 and §5.9
# p.165; 6.0 §7.9.6 p.283 and §7.10 p.296); without the modifier the map
# maps it and the update skips it, and the program goes on.
PRESENT_CITE = {"map": {52: "5.2 §5.8.3 p.152", 60: "6.0 §7.9.6 p.283"},
                "update": {52: "5.2 §5.9 p.165", 60: "6.0 §7.10 p.296"}}


def present_probe(version, which):
    """Negative probe for map(present, ...), to(present: ...) or
    from(present: ...): the standard kernel runs first (device evidence; it
    maps a and b only for its region), then the construct names an item
    that is not present with the present modifier. A correct run ends there
    with runtime error termination (offload.engine.harness.ERROR_TERMINATION);
    a run that goes on sets `continued` and prints check=fail."""
    up = spell("target update", version)
    if which == "map":
        c = "map(present, to: a)"
        probe = [omp("target", c, "map(from: b)")] + seq_loop() + [
            omp("end target")]
    else:
        c = "to(present: a)" if which == "to" else "from(present: b)"
        probe = [omp(up, c)]
    what = "map" if which == "map" else "update"
    s = Src(decls=["logical :: continued"], init=["continued = .false."],
            checks=["(.not. continued)"], focus=c, evidence="probe",
            expect="error_termination")
    s.header_notes.append(
        f"negative probe: {c} names an item that is not present, which "
        f"requires runtime error termination ({PRESENT_CITE[what][version]}); "
        "reaching the end of the program prints check=fail")
    s.region += INNER + probe + ["continued = .true."]
    return s


SELF_WHY = ("re-categorised (was implementation_defined): a self "
            "map is 'a mapping operation for which the corresponding storage "
            "is the same as its original storage' (6.0 Glossary p.95), and a "
            "map-entering self map of storage the device cannot access must "
            "end in runtime error termination (6.0 §7.9.6 p.285), so the "
            "spec fixes the behaviour: in copy mode (HSA_XNACK=0) a device "
            "write of a self-mapped a must be seen by the host, or the "
            "run must stop; without self the write stays on the device. That "
            "check is not written: the program needs zero-copy memory as "
            "generated, and AFAR at HSA_XNACK=0 copies even with self (probe "
            "2026-10-18: map(self, to: a) with a device write of a leaves the "
            "host's a unchanged), which the check would report as a wrong "
            "answer")
CLOSE_WHY = ("close is a hint to allocate the device copy in memory close to "
             "the device; values and presence are the same without it")


def _feat_map(version, feat):
    """map clause features."""
    ent, ext = (spell("target enter data", version),
                spell("target exit data", version))
    if feat in (None, "to", "from"):
        # the device overwrites a after reading it: with map(to: a) the
        # write stays on the device (copy mode), so the host's a is
        # unchanged; without the map type (or the clause) a is mapped
        # tofrom and the write comes back
        s = _k(version, Region("target", body=BODY + ("a(i) = 0",)),
               focus="map(to: a)")
        s.post += s.copy_check("all(2*a + 1 == ref)")
        return s
    if feat == "tofrom":
        return _k(version, Region("target", maps="map(to: a) map(tofrom: b)"),
                  focus="map(tofrom: b)")
    if feat == "always":
        # a is present (enter data) when the host changes it: only the
        # always modifier copies the new values to the present device copy
        # (copy mode; without it the region reads the stale copy)
        c = "map(always, to: a)"
        s = _k(version, Region("target", maps=f"{c} map(from: b)"),
               focus=c, ref="2*(i + 10) + 1", evidence="copy_mode_only",
               init=[omp(ent, "map(to: a)"), "do i = 1, n",
                     "  a(i) = a(i) + 10", "end do"],
               post=[omp(ext, "map(release: a)")])
        return s
    if feat == "close":
        c = f"map({feat}, to: a)"
        return _k(version, Region("target", maps=f"{c} map(from: b)"),
                  focus=c).no_oracle("hint_only", CLOSE_WHY, "close_hint")
    if feat == "present":
        return present_probe(version, "map")
    if feat == "alloc":
        return enter_exit_prog(version, focus="map(to: a) map(alloc: b)")
    if feat == "release":
        return enter_exit_prog(version, twice=True,
                               focus="map(from: b) map(release: a)")
    if feat == "delete":
        return enter_exit_prog(version, exit_="map(from: b) map(delete: a)",
                               twice=True, focus="map(delete: a)")
    if feat == "storage":
        return enter_exit_prog(version, enter="map(to: a) map(storage: b)",
                               focus="map(storage: b)")
    if feat == "self":
        c = "map(self: a)"
        return _k(version, Region("target", maps=f"{c} map(from: b)"),
                  focus=c, note="self maps the original storage: needs memory "
                  "the device can access (zero-copy)", needs=("zero_copy",)
                  ).unverified("oracle_not_written", SELF_WHY)
    if feat == "ref_ptee":
        # ref_ptee maps the pointee only (6.0 §7.9.5): the region, which
        # dereferences p, maps the pointer itself (ref_ptr), attached to
        # the pointee that the enter data made present with its values
        c = "map(ref_ptee, to: p)"
        return _k(version, Region("target", maps="map(ref_ptr, to: p) "
                                  "map(from: b)", body=("b(i) = 2*p(i) + 1",)),
                  decls=["integer, pointer :: p(:)"],
                  init=["p => a", omp(ent, c)],
                  post=[omp(ext, "map(ref_ptee, release: p)")], focus=c)
    if feat in ("ref_ptr", "ref_ptr_ptee"):
        c = f"map({feat}, to: p)"
        maps = f"map(to: a) {c} map(from: b)" if feat == "ref_ptr" \
            else f"{c} map(from: b)"
        s = _k(version, Region("target", maps=maps,
                               body=("b(i) = 2*p(i) + 1",)),
               decls=["integer, pointer :: p(:)"], init=["p => a"], focus=c)
        if feat == "ref_ptr_ptee":
            s.no_oracle("equivalent_default", "without a ref-modifier the "
                        "map applies to the referring pointer and its "
                        "pointee (6.0 §7.9.6), i.e. ref_ptr_ptee",
                        "ref_ptr_ptee_default")
        return s
    if feat == "iterator":
        # only the items the iterator generates are mapped: for k = 1 the
        # section w(2:n/2) is present after enter data, the elements around
        # it are not (copy mode: under unified memory nothing is reported
        # present); an empty range maps nothing. One iterator
        # value, since list items generated from different values must not
        # have the same containing array (5.2 §5.8.3 p.155, 6.0 §7.9.6
        # p.286); the form w(k), k = 1:n:2, broke that restriction
        c = "map(iterator(k = 1:1), to: w(k + 1:n/2))"
        s = _k(version, Region("target"), focus=c,
               decls=["integer :: k", "integer, target :: w(n)"],
               init=["w = 0", omp(ent, c)])
        s.post += s.presence(("w(2)", "w(n/2)"), True) + s.presence(
            ("w(1)", "w(n/2 + 1)"), False) + [
            omp(ext, "map(iterator(k = 1:1), release: w(k + 1:n/2))")]
        return s
    if feat == "mapper":
        return mapper_prog(version)
    return None


def _motion(version, which, feat):
    """to / from on target update."""
    arr = "a" if which == "to" else "b"
    if feat is None:
        c = f"{which}({arr})"
    elif feat == "present":
        return present_probe(version, which)
    elif feat == "mapper":
        return motion_mapper_prog(version, which)
    elif feat == "iterator":
        c = f"{which}(iterator(k = 1:1): {arr}(k:n))"
    else:
        return None
    kw = {"to": c} if which == "to" else {"frm": c}
    s = update_prog(version, focus=c, **kw)
    if feat == "iterator":
        s.decls.append("integer :: k")
    return s


def motion_mapper_prog(version, which):
    """The mapper mm of type dt maps only the
    component v; s (v = w = 1) is entered whole. to: the host sets v = w =
    5 and `target update to(mapper(mm): s)` copies only v, so the device
    sees v = 5, w = 1. from: the device sets v = w = 5 and `target update
    from(mapper(mm): s)` copies only v back, so the host sees v = 5, w = 1.
    Without the modifier the update copies all of s (w = 5 too). Copy mode
    only (shared storage hides the copies)."""
    dm, up = spell("declare mapper", version), spell("target update",
                                                     version)
    ent, ext = (spell("target enter data", version),
                spell("target exit data", version))
    c = f"{which}(mapper(mm): s)"
    s = Src(spec=["type :: dt", "  integer :: v(8)", "  integer :: w(8)",
                  "end type dt", omp(f"{dm}(mm: dt :: q)", "map(q%v)")],
            decls=["type(dt) :: s", "integer :: rv, rw"],
            init=["s%v = 1", "s%w = 1", "rv = 0", "rw = 0"], focus=c)
    s.region += INNER + [omp(ent, "map(to: s)")]
    if which == "to":
        s.region += ["s%v = 5", "s%w = 5", omp(up, c),
                     omp("target", "map(from: rv, rw)"), "rv = s%v(1)",
                     "rw = s%w(1)", omp("end target")]
        cond = "rv == 5 .and. rw == 1"
    else:
        s.region += [omp("target"), "s%v = 5", "s%w = 5", omp("end target"),
                     omp(up, c), "rv = s%v(1)", "rw = s%w(1)"]
        cond = "rv == 5 .and. rw == 1"
    s.region += [omp(ext, "map(delete: s)")]
    s.post += s.copy_check(cond)
    return s


SCHEDULE = {None: "schedule(static)", "static": "schedule(static)",
            "dynamic": "schedule(dynamic)", "guided": "schedule(guided)",
            "auto": "schedule(auto)", "runtime": "schedule(runtime)",
            "chunk_size": "schedule(static, 4)",
            "monotonic": "schedule(monotonic: static)",
            "nonmonotonic": "schedule(nonmonotonic: dynamic)",
            "simd": "schedule(simd: static)"}

REQUIRES = {"unified_address", "unified_shared_memory", "reverse_offload",
            "dynamic_allocators", "self_maps", "device_safesync"}


# Triage (probe on Tuolumne, 2026-10-18, HSA_XNACK=0): with a chunk
# size the dynamic and guided schedules would be checkable (each chunk is a
# contiguous block of chunk_size iterations, at least chunk_size for
# guided), but schedule(dynamic, 4) and schedule(guided, 8) on parallel do in
# a target region give iteration i to thread mod(i - 1, T) on AFAR (T = 32)
# and CCE 19 (T = 256), as schedule(static, 4) does (the unaudited
# omp.clause.schedule.chunk_size), so no chunked mutant could be killed.
SCHED_CHUNK_PROBE = (
    "; with a chunk size the chunks would be checkable (a chunk is a "
    "contiguous set of iterations executed by one thread: 5.2/6.0 glossary, "
    "§11.5.3 / §13.6.3), but both toolchains split chunks across threads on "
    "the device (probe 2026-10-18: schedule(dynamic, 4) and schedule(guided, "
    "8) give iteration i to thread mod(i - 1, T), as schedule(static, 4) "
    "does), which violates the spec rather than using a freedom it grants; "
    "that failure is measured by the unaudited schedule.chunk_size and "
    "schedule.static programs, and no chunked mutant could be killed here")
# Re-categorisation (was implementation_defined): with a chunk size
# the spec fixes the chunks of dynamic and guided ("Each chunk contains
# chunk_size iterations, except for the chunk that contains the
# sequentially last iteration", 5.2 §11.5.3 p.253, 6.0 §13.6.3 p.418; for
# guided "the chunks do not contain fewer than k iterations"), so a
# deterministic check exists (each chunk is one thread's), and run-sched-var
# can be set on the device with omp_set_schedule.
SCHED_UNWRITTEN_WHY = {
    "dynamic": "the program uses schedule(dynamic), whose chunk size 1 lets "
               "any assignment conform, but the kind fixes its chunks once a "
               "chunk size is given (5.2 §11.5.3 p.253, 6.0 §13.6.3 p.418: "
               "each chunk is chunk_size contiguous iterations run by one "
               "thread), so schedule(dynamic, 4) with a check that every "
               "aligned block of 4 iterations ran on one thread is a "
               "deterministic oracle; it is not written" + SCHED_CHUNK_PROBE,
    "guided": "the program uses schedule(guided), whose chunk size 1 lets "
              "any assignment conform, but with a chunk size k no chunk but "
              "the last may have fewer than k iterations (5.2 §11.5.3 p.253, "
              "6.0 §13.6.3 p.419), so schedule(guided, 8) with a check that "
              "every run of iterations on one thread but the last is at "
              "least 8 long is a deterministic oracle; it is not written"
              + SCHED_CHUNK_PROBE,
    "runtime": "run-sched-var's initial value is implementation defined "
               "(5.2 §2.2 p.40, 6.0 §3.2 p.118; the harness clears "
               "OMP_SCHEDULE), but omp_set_schedule in the target region "
               "fixes it, after which schedule(runtime) is the schedule set "
               "(5.2 §11.5.3 p.253), a deterministic oracle with the static "
               "kind; it is not written: CCE 19 does not link "
               "omp_set_schedule in device code (probe 2026-10-18) and the "
               "chunked kinds are those the toolchains do not honour on the "
               "device"}
# Schedule(static) and dist_schedule(static) without
# a chunk size, one reading for both
STATIC_NO_CHUNK_WHY = (
    "the static kind without a chunk size guarantees only contiguous "
    "chunks, at most one per thread (team), and the spec's Note calls "
    "chunks of ceil(n/p) and q / q - 1 splits alike compliant, so the check "
    "tests contiguity and that every iteration ran on an owner; without the "
    "clause the schedule is implementation defined by the spec (worksharing "
    "loop: def-sched-var / auto; distribute: stated in the construct's "
    "section), so it may be such a split and no single run separates the "
    "clause from its absence (the label rests on this spec text, not on an "
    "observed default); the chunk_size forms fix one assignment exactly and "
    "keep an audited oracle")
SCHED_WHY = {
    "auto": "the auto schedule delegates the assignment of iterations to "
            "threads to the compiler and runtime, so every assignment is "
            "conforming (5.2 §11.5.3, 6.0 §13.6.3)",
    "simd": "the simd modifier only rounds the chunk size up to a multiple "
            "of the implementation-defined SIMD width (5.2 §11.5.3, 6.0 "
            "§13.6.3), and both toolchains ignore schedule chunk sizes on "
            "the device (probe 2026-10-18)"}
SCHED_BASIS = {"auto": "schedule_auto", "simd": "schedule_simd_width"}
NONMONOTONIC_WHY = ("nonmonotonic is the modifier the dynamic kind the "
                    "program uses has without one (5.0 and later)")
MONOTONIC_WHY = (
    "Schedule(monotonic: dynamic) with a check of the order each "
    "thread ran its iterations in (a per-thread counter, firstprivate from "
    "0): monotonic requires increasing logical iteration order per thread, "
    "and a wrong answer is a real failure; without the modifier the dynamic "
    "kind is nonmonotonic, under which chunks may run in any order, "
    "increasing order included, so a conforming run without it can "
    "coincide")
PROC_BIND_WHY = ("if bind-var is false the proc_bind clause has no effect, "
                 "and the initial value of bind-var is implementation "
                 "defined (5.2 §2.5 Table 2.4, 6.0 §3.5), so a run without "
                 "the clause may coincide with one with it; omp_get_proc_bind "
                 "returns the policy for nested regions without a proc_bind "
                 "clause (5.2 §18.3.1), never the clause's own value; on the "
                 "device AFAR reports omp_get_num_places() = 0 and CCE 19 "
                 "does not link the places routines in device code (probe "
                 "2026-10-18), so no place check is available either")
SIMD_WHY = {
    "safelen": "safelen bounds the distance between concurrent iterations; "
               "the number of iterations run concurrently is implementation "
               "defined, so an implementation that runs one at a time meets "
               "the bound vacuously (the program's loop has no dependence "
               "the bound would protect)",
    "simdlen": "simdlen is a hint for the preferred number of concurrent "
               "iterations",
    "nontemporal": "nontemporal states a property of the accesses (low "
                   "temporal locality), not a behaviour",
    "aligned": "aligned asserts an alignment the program ensures; it "
               "requires nothing observable of the implementation"}
SIMD_BASIS = {"safelen": "simd_concurrency", "simdlen": "simdlen_hint",
              "nontemporal": "nontemporal_locality",
              "aligned": "aligned_assertion"}
ORDER_WHY = ("order(concurrent) permits but does not require concurrent "
             "execution; the region may not call the OpenMP API (5.2 §10.3) "
             "that could see the threads, so a single run cannot tell it "
             "from the loop without the clause")
# The 5.0 programs cite the 5.0 restriction (the
# worksharing-loop with order(concurrent) takes the loop construct's
# restrictions, 5.0 §2.9.2 p.108)
ORDER_WHY_50 = ("order(concurrent) permits but does not require concurrent "
                "execution; the region may not call the OpenMP Runtime API "
                "(5.0 §2.9.5 p.131: \"A loop region corresponding to a loop "
                "construct may not contain calls to the OpenMP Runtime "
                "API\", which applies with order(concurrent), 5.0 §2.9.2 "
                "p.108) that could see the threads, so a single run cannot "
                "tell it from the loop without the clause")
ORDER_REPRODUCIBLE_WHY = (
    "re-categorised (was implementation_defined): two "
    "worksharing-loops with the same reproducible schedule have consistent "
    "schedules, and the implementation guarantees that the memory effects "
    "of an iteration of the first happen before the same iteration of the "
    "second (5.2 §4.4.5 p.95, 6.0 §6.4.4 p.205), so a first loop with "
    "nowait that writes w(i) and a second that reads it is a deterministic "
    "oracle (no barrier between them); it is not written (AFAR rejects "
    "order on the worksharing-loop construct)")
ORDER_UNCONSTRAINED_WHY = (
    "corrected: unconstrained is not 'the default order-modifier' "
    "(with schedule(static) it removes the reproducible schedule the loop "
    "would otherwise have, 5.2 §11.5 p.248, 6.0 §13.6 p.414), but this "
    "program has no schedule clause, so its schedule is not reproducible "
    "with or without the modifier and the forms are the same")


# The loop construct's iterations "may execute in any order,
# including concurrently" (5.2 §11.7 p.257, 6.0 §13.8; order(concurrent)
# implied), so a per-thread counter `mine = mine + 1` updated by every
# iteration is a data race between the iterations one thread runs (AFAR
# printed 1 per thread for bind(thread) in Fortran). Each iteration
# therefore records itself in its own element, hit(i, owner + 1) (owner:
# the thread or team), and the host sums each owner's column into tot.
BIND_HIT_DECLS = ["integer :: hit(n, 1024), tot(1024), k"]
BIND_HIT_POST = ["do k = 1, 1024", "  tot(k) = 0", "  do i = 1, n",
                 "    tot(k) = tot(k) + hit(i, k)", "  end do", "end do"]


def bind_orphan_prog(version, kind):
    """An orphaned loop bind(parallel|teams)
    in a declare target subroutine, called from every thread of a parallel
    region (from every team of a teams region of num_teams(4)) in a target
    region; each iteration a thread (team) runs is recorded in its own
    element of the declare target module array hit(i, owner + 1)
    (64 rows: n, written as a literal for the C port's file-scope array) (BIND_HIT_DECLS: race-free), summed into tot(thread or team + 1) on the
    host after target update from(hit). With the binding the team (league)
    shares the iterations: sum(tot) == n. Without bind an orphaned loop
    binds to the encountering thread (5.2 §11.7.1 p.257, 6.0 §13.8.1), so
    each thread (team) runs all n and the sum is T*n."""
    sub = ["integer :: hit(64, 1024)", omp("declare target(hit)"),
           "contains", "subroutine work(t)", omp("declare target"),
           "integer, intent(in) :: t",
           "integer :: i", omp("loop", f"bind({kind})"), "do i = 1, 64",
           "  hit(i, t) = hit(i, t) + 1", "end do", omp("end loop"),
           "end subroutine work"]
    s = Src(module=sub, decls=["integer :: tot(1024), k", "integer :: nthr"],
            init=["hit = 0", omp("target update", "to(hit)"),
                  f"nthr = {SENTINEL}"],
            post=[omp("target update", "from(hit)")] + [
                x.replace("do i = 1, n", "do i = 1, 64")
                for x in BIND_HIT_POST],
            checks=["(nthr >= 1 .and. nthr <= 1024)", "(sum(tot) == n)"],
            focus=f"bind({kind})")
    head = omp("target", STD_MAPS, "map(tofrom: nthr)", FLAG_MAP)
    if kind == "parallel":
        s.region += [head, FLAG] + seq_loop() + [
            omp("parallel"),
            "if (omp_get_thread_num() < 1024) call work("
            "omp_get_thread_num() + 1)",
            "if (omp_get_thread_num() == 0) nthr = omp_get_num_threads()",
            omp("end parallel"), omp("end target")]
    else:
        s.region += [head, omp("teams", "num_teams(4)")] + \
            guarded("omp_get_team_num() == 0",
                    TEAMS_FLAG + ["nthr = omp_get_num_teams()"]
                    + seq_loop()) + [
            "if (omp_get_team_num() < 1024) call work("
            "omp_get_team_num() + 1)",
            omp("end teams"), omp("end target")]
    return s


def bind_thread_prog(version):
    """loop bind(thread) in a parallel region in a target region: every
    thread of the team runs all n iterations (the binding region is the
    thread's own), each recorded in the thread's own column of hit
    (BIND_HIT_DECLS), summed into tot(thread + 1) on the host; thread 0
    alone writes b. Without bind the loop binds to the parallel region and
    the team shares the iterations, so with more than one thread some
    thread counts fewer than n (and b is only partly written). A
    one-thread team cannot tell them apart. Fix: the team size is implementation defined (NVHPC's nvc makes
    110,560 threads), so the check no longer assumes nthr <= 1024: the
    first min(nthr, 1024) threads record their iterations and are
    checked."""
    s = Src(decls=BIND_HIT_DECLS + ["integer :: tid, nthr"],
            init=["hit = 0", f"nthr = {SENTINEL}"], post=list(BIND_HIT_POST),
            checks=["(nthr >= 1)",
                    "all(tot(1:min(nthr, 1024)) == n)"],
            focus="bind(thread)")
    s.region += [omp("target", STD_MAPS, "map(tofrom: hit, nthr)", FLAG_MAP),
                 FLAG,
                 omp("parallel", "default(none) private(tid) "
                     "shared(a, b, hit, nthr)"),
                 "tid = omp_get_thread_num()",
                 "if (tid == 0) nthr = omp_get_num_threads()",
                 omp("loop", "bind(thread)"),
                 "do i = 1, n", "  if (tid == 0) b(i) = 2*a(i) + 1",
                 "  if (tid < 1024) hit(i, tid + 1) = hit(i, tid + 1) + 1",
                 "end do", omp("end loop"),
                 omp("end parallel"), omp("end target")]
    return s


def bind_teams_thread_prog(version):
    """omp.clause.bind: loop bind(thread) closely nested in a
    teams region of num_teams(4) teams (exactly 4: 5.2 §10.2.1, 6.0
    §12.2.1) in a target region. With binding thread the binding region is
    not defined and the binding thread set is the encountering thread (5.2
    §11.7.1 p.258, 6.0 §13.8.1), so every team's initial thread runs all n
    iterations, each recorded in the team's own column of hit
    (BIND_HIT_DECLS), summed into tot(team + 1) on the host; team 0 alone
    writes b. Without the clause the loop, closely nested in teams, binds
    to the teams region and the league shares the iterations, so some team
    counts fewer than n. Unlike the orphaned forms (bind.parallel,
    bind.teams), deleting the clause leaves a conforming program (an
    orphaned loop must have bind, 5.2 §11.7 p.257); unlike bind.thread
    (closely nested in parallel), the binding it replaces is the
    league's."""
    s = Src(decls=BIND_HIT_DECLS + ["integer :: tm, nt"],
            init=["hit = 0", f"nt = {SENTINEL}"], post=list(BIND_HIT_POST),
            checks=["(nt >= 1 .and. nt <= 1024)",
                    "all(tot(1:min(nt, 1024)) == n)"],
            focus="bind(thread)")
    s.region += [omp("target", STD_MAPS, "map(tofrom: hit, nt)", FLAG_MAP),
                 omp("teams", "num_teams(4) default(none) private(tm) "
                     "shared(a, b, hit, nt, host_flag)"),
                 "tm = omp_get_team_num()",
                 "if (tm == 0) nt = omp_get_num_teams()",
                 *guarded("tm == 0", TEAMS_FLAG),
                 omp("loop", "bind(thread)"),
                 "do i = 1, n", "  if (tm == 0) b(i) = 2*a(i) + 1",
                 "  if (tm < 1024) hit(i, tm + 1) = hit(i, tm + 1) + 1",
                 "end do", omp("end loop"),
                 omp("end teams"), omp("end target")]
    return s


def task_default_prog(version, clause):
    """default(shared) on a task: in a parallel region in the
    target region, each thread's c is private (c = 7); a task with
    `clause` sets c = 42 and, after taskwait, thread 0 reports its c in r.
    With default(shared) the task shares the generating thread's c, so r
    is 42. Without a default clause, c, which is not shared by all implicit
    tasks of the team in the enclosing context, is firstprivate in the task
    (5.2 §5.1.1 p.100, 6.0 §7.1.1 p.214): the write is lost and r is 7. In a
    parallel construct default(shared) would be the default and change
    nothing; on a task it does not."""
    s = Src(decls=["integer :: c, r"], init=["r = 0"],
            checks=["(r == 42)"], focus=clause)
    s.region += [omp("target", STD_MAPS, "map(from: r)", FLAG_MAP), FLAG] + \
        seq_loop() + [omp("parallel", "private(c)"), "c = 7",
                      omp("task", clause), "c = 42", omp("end task"),
                      omp("taskwait"),
                      "if (omp_get_thread_num() == 0) r = c",
                      omp("end parallel"), omp("end target")]
    return s


def monotonic_prog(version):
    """schedule(monotonic: dynamic) on parallel do in a target region (Task
    15): every iteration records its thread (tid) and its place in that
    thread's execution order (ord, from a per-thread counter firstprivate
    from 0). Monotonic requires each thread to run the chunks it is
    assigned in increasing logical iteration order (5.2 §11.5.3 p.254, 6.0
    §13.6.3 p.419): for two iterations of one thread, the later iteration
    has the larger ord. Without the modifier the dynamic kind is
    nonmonotonic, which permits that order too (see MONOTONIC_WHY)."""
    def loop(flag):
        return ["do i = 1, m", "  if (i <= n) b(i) = 2*a(i) + 1",
                "  mine = mine + 1", "  ord(i) = mine",
                "  tid(i) = omp_get_thread_num()", "end do"]
    post = ["mok = .true.", "do i = 2, m", "  do k = 1, i - 1",
            "    if (tid(k) == tid(i) .and. ord(k) >= ord(i)) mok = .false.",
            "  end do", "end do"]
    s = pdo(version, "schedule(monotonic: dynamic) firstprivate(mine)",
            loop=loop, maps=f"{STD_MAPS} map(from: tid, ord)",
            shared=("a", "b", "tid", "ord"),
            decls=[f"integer, parameter :: m = {SCHED_M}",
                   "integer :: tid(m), ord(m), mine, k", "logical :: mok"],
            init=["mine = 0", f"tid = {SENTINEL}", f"ord = {SENTINEL}"],
            post=post, checks=["mok"])
    s.focus = "schedule(monotonic: dynamic)"
    return s.no_oracle("implementation_defined", MONOTONIC_WHY,
                       "schedule_nonmonotonic_order", checked=True)


def if_prog(version):
    """The if clause judged on the device. if(use_par) with use_par
    false on a parallel do nested in a target region: the parallel region
    is inactive, a team of one thread (iteration 1 records the team size),
    while the region runs on the device. Without the clause the team has
    more than one thread on both toolchains. (The if clause on a target
    construct with a false condition runs the region on the host, which is
    not device offload; the clause is the same atom.)"""
    s = pdo(version, "if(use_par)",
            maps=f"{STD_MAPS} map(from: nthr)",
            body=BODY + ("if (i == 1) nthr = omp_get_num_threads()",),
            shared=("a", "b", "nthr"),
            decls=["integer :: nthr", "logical :: use_par"],
            init=["use_par = .false.", "nthr = 0"], checks=["(nthr == 1)"])
    s.focus = "if(use_par)"
    return s


def if_dnm_prog(version):
    """if(parallel: use_dev) with use_dev false on the combined construct:
    the parallel constituent is inactive, a team of one thread, while the
    region still runs on the device. Without the modifier the if clause
    applies to the target constituent too and the region runs on the host
    (the audit's kill is a host fallback)."""
    return team_param(version, "if(parallel: use_dev)",
                      ["if (i == 1) nthr = omp_get_num_threads()"],
                      ["integer :: nthr"], ["(nthr == 1)"],
                      extra_decls=["logical :: use_dev"],
                      # If(parallel: ...) is evaluated inside the
                      # teams region (5.2 §17.2 p.340) and default(none)
                      # applies to teams (5.2 §5.4.1 p.109): use_dev is listed
                      extra_shared=("use_dev",),
                      init=["use_dev = .false."])


def _UNCHECKED_CLAUSE(clause):
    """Src fields for a clause whose own effect the program cannot
    observe (the check covers the enclosing construct only)."""
    return {"observable": False,
            "note": f"the check covers the enclosing target data, not "
                    f"{clause} itself",
            "header_notes": [f"clause not checked: {clause}"]}


def clause_recipe(clause: str, feat: str | None, version: int) -> Src | None:
    """The program for omp.clause.<clause>[.<feat>] (directive_name is
    built by offload.engine.gen from the clause's base program)."""
    v = version
    if clause in REQUIRES:
        if feat in (None, "required"):
            return requires_prog(v, clause if feat is None
                                 else f"{clause}(.true.)")
        return None
    if clause == "atomic_default_mem_order":
        return requires_prog(v, f"{clause}({feat or 'seq_cst'})")
    if clause == "map":
        return _feat_map(v, feat)
    if clause in ("to", "from") and feat in (None, "present", "mapper",
                                            "iterator"):
        if clause == "to" and feat is None:
            # the declare target clause and the motion clause share the
            # atom; the motion clause is the one with a device effect
            return _motion(v, "to", None)
        return _motion(v, clause, feat)
    if clause == "reduction":
        if feat in RED:
            return reduction_prog(v, feat)
        if feat is None:
            return reduction_prog(v)
        if feat == "default":
            return reduction_prog(v, modifier="default").no_oracle(
                "equivalent_default", "default is the default "
                "reduction-modifier", "reduction_default_modifier")
        if feat == "original":
            return reduction_prog(v, modifier="original(shared)")
        if feat == "task":
            return task_reduction_prog(v)
        if feat == "inscan":
            return inscan_prog(v)
        return None
    if clause == "in_reduction":
        return in_reduction_prog(v, feat or "plus") \
            if feat is None or feat in RED else None
    if clause == "schedule":
        c = SCHEDULE.get(feat)
        if c is None:
            return None
        if feat in (None, "static"):
            return schedule_prog(v, c)
        if feat == "chunk_size":
            return schedule_prog(v, c, chunk=4)
        if feat == "monotonic":
            return monotonic_prog(v)
        s = (pdo_simd if feat == "simd" else pdo)(v, c)
        if feat == "nonmonotonic":
            return s.no_oracle("equivalent_default", NONMONOTONIC_WHY,
                               "schedule_default_modifier")
        if feat in SCHED_UNWRITTEN_WHY:
            return s.unverified("oracle_not_written",
                                SCHED_UNWRITTEN_WHY[feat])
        return s.no_oracle("implementation_defined", SCHED_WHY[feat],
                           SCHED_BASIS[feat])
    if clause == "proc_bind":
        return pdo(v, f"proc_bind({feat or 'close'})").no_oracle(
            "implementation_defined", PROC_BIND_WHY, "proc_bind_bind_var")
    if clause == "num_threads":
        if feat not in (None, "strict"):
            return None
        c = "num_threads(strict: 4)" if feat == "strict" else "num_threads(4)"
        # at most 4 threads (exactly 4 with strict); both toolchains give
        # more than 4 without the clause
        want = "nthr == 4" if feat == "strict" else "nthr >= 1 .and. nthr <= 4"
        return pdo(v, c, body=BODY + ("if (i == 1) nthr = "
                                      "omp_get_num_threads()",),
                   maps=f"{STD_MAPS} map(from: nthr)",
                   shared=("a", "b", "nthr"), decls=["integer :: nthr"],
                   init=[f"nthr = {SENTINEL}"], checks=[f"({want})"])
    if clause == "message" and feat is None:
        return error_probe(v, "warning")
    if clause == "severity" and feat in (None, "warning", "fatal"):
        return error_probe(v, feat or "warning")
    if clause in ("safelen", "simdlen") and feat is None:
        return pdo_simd(v, f"{clause}({8 if clause == 'safelen' else 4})"
                        ).no_oracle("hint_only", SIMD_WHY[clause],
                                    SIMD_BASIS[clause])
    if clause == "nontemporal" and feat is None:
        return pdo_simd(v, "nontemporal(b)").no_oracle(
            "hint_only", SIMD_WHY[clause], SIMD_BASIS[clause])
    if clause == "aligned" and feat in (None, "alignment"):
        return pdo_simd(v, "aligned(a: 8)").no_oracle(
            "hint_only", SIMD_WHY[clause], SIMD_BASIS[clause])
    if clause == "order":
        c = {None: "order(concurrent)", "concurrent": "order(concurrent)",
             "reproducible": "order(reproducible: concurrent)",
             "unconstrained": "order(unconstrained: concurrent)"}.get(feat)
        if c is None:
            return None
        if feat == "unconstrained":
            return pdo(v, c).no_oracle(
                "equivalent_default", ORDER_UNCONSTRAINED_WHY,
                "order_unconstrained_reproducible")
        if feat == "reproducible":
            return pdo(v, c).unverified("oracle_not_written",
                                        ORDER_REPRODUCIBLE_WHY)
        return pdo(v, c).no_oracle("implementation_defined",
                                   ORDER_WHY_50 if v == 50 else ORDER_WHY,
                                   "order_concurrent")
    if clause == "bind":
        if feat == "thread":
            return bind_thread_prog(v)
        if feat is None:
            return bind_teams_thread_prog(v)
        return bind_orphan_prog(v, feat)
    if clause == "collapse" and feat is None:
        # with collapse(2) the 64 iterations of the 2 x 32 nest are shared
        # by the team (schedule(static): one chunk per thread, min(T, 64)
        # threads busy); without it only the 2 outer iterations are, so at
        # most 2 threads run the loop
        s = pdo(v, "collapse(2) schedule(static)", loop=collapse_loop,
                maps=f"{STD_MAPS} map(from: tid, nthr)",
                shared=("a", "b", "tid", "nthr"),
                decls=["integer :: j, k", "integer :: tid(n), nthr, nd"],
                init=[f"tid = {SENTINEL}", f"nthr = {SENTINEL}"],
                post=count_owners("tid", "nd", "nthr"),
                checks=["(nd == min(nthr, n))"])
        s.focus = "collapse(2)"
        return s
    if clause == "ordered":
        if feat is None:
            # the ordered regions run in iteration order: each takes the
            # next ticket; without the ordered clause (and regions) the
            # team races for the counter
            def loop(flag):
                return ["do i = 1, n", "  b(i) = 2*a(i) + 1",
                        "  " + omp("ordered"), "  cnt = cnt + 1",
                        "  seq(i) = cnt", "  " + omp("end ordered"),
                        "end do"]
            s = pdo(v, "ordered", loop=loop,
                    maps=f"{STD_MAPS} map(tofrom: cnt) map(from: seq)",
                    shared=("a", "b", "cnt", "seq"),
                    decls=["integer :: cnt, seq(n)"],
                    init=["cnt = 0", f"seq = {SENTINEL}"],
                    checks=["all(2*seq + 1 == ref)"])
            s.focus = "ordered"
            return s
        if feat == "n":
            return pdo(v, "ordered(1)").no_oracle(
                "equivalent_default", "re-categorised (was "
                "implementation_defined): without n the ordered clause "
                "behaves as if n were the collapse value, here 1, so "
                "ordered(1) on this one-loop nest is the ordered clause "
                "without its argument, with or without doacross constructs",
                "ordered_n_default")
        return None
    if clause == "private" and feat is None:
        # t is written by every iteration; the target's t (mapped tofrom,
        # 7) must not change: without private(t) the team shares it
        return pdo(v, "private(t)", body=("t = 2*a(i)", "b(i) = t + 1"),
                   maps=f"{STD_MAPS} map(tofrom: t)", decls=["integer :: t"],
                   init=["t = 7"], checks=["(t == 7)"])
    if clause == "firstprivate":
        c = {None: "firstprivate(c)", "saved": "firstprivate(saved: c)"}.get(
            feat)
        if c is None:
            return None
        # each thread's c starts at 1 (the body reads mod(c, 100) = 1 and
        # adds 100); the target's c (mapped tofrom) must stay 1: without
        # the clause the team shares c and the additions come back
        return pdo(v, c, body=("b(i) = 2*a(i) + mod(c, 100)", "c = c + 100"),
                   maps=f"{STD_MAPS} map(tofrom: c)", decls=["integer :: c"],
                   init=["c = 1"], checks=["(c == 1)"])
    if clause == "lastprivate":
        if feat is None:
            c, body, want = "lastprivate(t)", ("t = a(i)",), "n"
        elif feat == "conditional":
            c, body, want = ("lastprivate(conditional: t)",
                             ("if (a(i) <= 10) t = a(i)",), "10")
        else:
            return None
        return pdo(v, c, maps=f"{STD_MAPS} map(tofrom: t)",
                   body=BODY + body, decls=["integer :: t"], init=["t = 0"],
                   checks=[f"(t == {want})"])
    if clause == "shared" and feat is None:
        # under default(private) only shared(a, b) lets the team write the
        # target's b
        s = pdo(v, "default(private) shared(a, b)", hyg=False)
        s.focus = "shared(a, b)"
        return s
    if clause == "default":
        if feat in (None, "none", "shared", "private", "firstprivate"):
            # the base atom uses the observable private form
            feat = feat or "private"
            c = f"default({feat}) shared(a, b)"
        elif feat in ("aggregate", "all", "allocatable", "pointer", "scalar"):
            c = f"default(shared: {feat}) shared(a, b)"
        else:
            return None
        if feat in ("private", "firstprivate"):
            # c is not listed: private (firstprivate) by default, written by
            # every iteration; the target's c (mapped tofrom, 7) must not
            # change, as it would if the team shared c
            return pdo(v, c, focus=c.split(" shared")[0],
                       body=("c = 2*a(i)", "b(i) = c + 1"),
                       maps=f"{STD_MAPS} map(tofrom: c)",
                       decls=["integer :: c"], init=["c = 7"],
                       checks=["(c == 7)"])
        if feat == "shared":
            return task_default_prog(v, "default(shared)")
        if feat == "all":
            return task_default_prog(v, "default(shared: all)").no_oracle(
                "equivalent_default", "default(shared: all) is "
                "default(shared) (all is the variable category without one); "
                "the program checks what both require: a task in a target "
                "region shares the generating thread's private c", 
                "default_category_all", checked=True)
        s = pdo(v, c, focus=c.split(" shared")[0])
        if feat == "none":
            s.evidence = "legality"
            s.legality_rule = "default-dsa-001"
            s.observable = False
            s.note = ("default(none) has no run-time effect; its oracle is "
                      "the illegal variant without a listed variable")
            return s
        return s
    if clause == "linear":
        # the step forms use step 2, which the mutation (step removed: 1)
        # changes
        c = {None: "linear(x: 1)", "step_simple_modifier": "linear(x: 2)",
             "step": "linear(x: step(2))", "val": "linear(x: val, step(1))"
             }.get(feat)
        if v == 50 and feat == "val":
            return linear_simd_decl_prog(v, feat)
        if c:
            s = linear_prog(v, c, step=2 if feat in (
                "step", "step_simple_modifier") else 1)
            if feat == "val":
                s.no_oracle("equivalent_default", "on a worksharing-loop the "
                            "only linear-modifier allowed is val, and the "
                            "clause's loop semantics do not depend on it, so "
                            "linear(x: val, step(1)) is linear(x: step(1))",
                            "linear_modifier_val")
            return s
        if feat in ("ref", "uval"):
            return linear_simd_decl_prog(v, feat)
        return None
    if clause == "induction":
        c = {None: "induction(step(1), +: x)", "plus":
             "induction(step(1), +: x)", "step": "induction(step(1), +: x)",
             "strict": "induction(step(1), strict, +: x)",
             "relaxed": "induction(step(1), relaxed, +: x)",
             "times": "induction(step(-1), *: y)"}.get(feat)
        if c is None:
            return None
        # the body applies the inductor, so the value at the end of each
        # iteration is the closed form for the next (relaxed, 6.0 §7.6.13)
        if feat == "times":
            # y = (-1)**(i-1) at the start of iteration i
            return pdo(v, c, maps=f"{STD_MAPS} map(tofrom: y)",
                       body=("b(i) = 2*a(i) + 1 + (y - merge(1, -1, "
                             "mod(i, 2) == 1))", "y = y * (-1)"),
                       decls=["integer :: y"], init=["y = 1"],
                       checks=["(y == 1)"])
        return pdo(v, c, maps=f"{STD_MAPS} map(tofrom: x)",
                   body=("b(i) = 2*a(i) + 1 + (x - (i + 2))", "x = x + 1"),
                   decls=["integer :: x"], init=["x = 3"],
                   checks=["(x == n + 3)"])
    if clause == "allocate":
        c = {None: "allocate(t)",
             "allocator": "allocate(allocator(omp_default_mem_alloc): t)",
             "allocator_simple_modifier": "allocate(omp_default_mem_alloc: t)",
             # the allocator-complex-modifier with the align modifier (5.2
             # §6.6 p.179): names an allocator, so no requires is needed
             "align": "allocate(allocator(omp_default_mem_alloc), "
                      "align(8): t)"}.get(feat)
        if c and feat is None:
            # An allocate clause in a target region must name an
            # allocator unless requires dynamic_allocators is present (5.2
            # §6.6 p.179, 6.0 §8.6 p.313); the form without one (the bare list) gets the
            # requirement, which also makes uses_allocators unnecessary
            # (5.2 §13.8 p.286, 6.0 §15.8 p.463)
            s = alloc_prog(v, c, wrap="")
            s.spec = [omp("requires", "dynamic_allocators")] + s.spec
            return s
        return alloc_prog(v, c) if c else None
    if clause == "uses_allocators":
        if feat is None:
            s = alloc_prog(v, "allocate(omp_default_mem_alloc: t)")
            s.focus = "uses_allocators(omp_default_mem_alloc)"
            return s
        mod = {"memspace": "memspace(omp_default_mem_space)",
               "traits": "traits(my_traits)"}.get(feat)
        if mod is None:
            return None
        c = f"uses_allocators({mod}: my_alloc)"
        if v == 50:  # 5.0 §2.12.5 p.170: allocator(allocator-traits-array)
            c = "uses_allocators(my_alloc(my_traits))"
        s = alloc_prog(v, "allocate(my_alloc: t)", wrap=c, decls=TRAITS,
                       shared=("a", "b", "my_alloc"))
        s.focus = c
        if feat == "memspace":
            s.no_oracle("equivalent_default", "the program names "
                        "omp_default_mem_space, the memory space used "
                        "without the modifier", "memspace_default")
        else:  # CCE passes, the mutant ICEs
            s.unverified("oracle_not_written", "re-categorised "
                         "(was implementation_defined): memory from the "
                         "allocator 'will be byte aligned to at least the "
                         "value specified for the alignment trait' (5.2 §6.2 "
                         "p.173, 6.0 §8.2 p.306" + (", 5.0 §2.11.2 p.153"
                                                    if v == 50 else "")
                         + "), so a check that t's "
                         "address is a multiple of 64 is a deterministic "
                         "oracle of the original; it is not written. A "
                         "mutant without the trait could still be 64-byte "
                         "aligned (any alignment conforms then), AFAR "
                         "rejects uses_allocators and CCE 19's mutant without "
                         "the trait is an internal compiler error "
                         "(final-review re-audit)")
        return s
    if clause == "defaultmap":
        if feat == "character":
            return defaultmap_character_prog(v)
        if feat in (None, "scalar"):
            return defaultmap_prog(v, "tofrom", "scalar")
        if feat in ("aggregate", "allocatable", "pointer"):
            # to: an array of the category is not copied back; the
            # mutation's other category leaves it tofrom
            return defaultmap_prog(v, "to", feat)
        if feat == "all":
            # to: all: the array w written on
            # the device is not copied back (copy mode); the mutation all ->
            # scalar leaves arrays tofrom
            return defaultmap_prog(v, "to", feat)
        if feat == "default":
            return defaultmap_prog(v, feat).no_oracle(
                "equivalent_default", "defaultmap(default) is the behaviour "
                "without the clause", "defaultmap_default")
        return defaultmap_prog(v, feat)
    if clause == "depend":
        if feat is None:
            return depend_prog(v, "out", "in")
        if feat == "in":
            s = depend_prog(v, "out", "in")
            s.focus = "depend(in: w)"
            return s
        if feat in ("out", "inout", "inoutset", "mutexinoutset"):
            s = depend_prog(v, feat, "in", writer=True)
            s.focus = f"depend({feat}: w)"
            return s
        if feat in ("iterator", "depobj"):
            return depend_prog(v, feat, "in")
        return None
    if clause == "device":
        if feat == "ancestor":
            return ancestor_prog(v)
        c = {None: "device(dev)", "device_num": "device(device_num: dev)"
             }.get(feat)
        if c is None:
            return None
        # the last device, not the default one (0): the region must report
        # it (omp_get_device_num); with one device both are device 0
        s = team_param(v, c, ["if (i == 1) dn = omp_get_device_num()"],
                       ["integer :: dn"], ["(dn == dev)"],
                       extra_decls=["integer :: dev"],
                       init=["dev = max(0, omp_get_num_devices() - 1)"])
        if feat == "device_num":
            s.no_oracle("equivalent_default", "device_num is the default "
                        "device-modifier: device(n) is device(device_num: "
                        "n)", "device_num_default")
        return s
    if clause == "if" and feat is None:
        return if_prog(v)
    if clause == "nowait":
        c = {None: "nowait", "do_not_synchronize": "nowait(.true.)"}.get(feat)
        if c is None:
            return None
        s = combined(v, c, post=[omp("taskwait")])
        return s.no_oracle("implementation_defined", NOWAIT_WHY,
                           "target_nowait") \
            if feat is None else s.no_oracle(
                "equivalent_default", "nowait(.true.) is nowait (the "
                "argument defaults to true), and nowait itself has no "
                "separating oracle (an implementation may run the target "
                "task synchronously)", "nowait_true_default")
    if clause == "thread_limit" and feat is None:
        # at most 16 threads per team (both toolchains use more without)
        return team_param(v, "thread_limit(16)",
                          ["if (i == 1) nthr = omp_get_num_threads()"],
                          ["integer :: nthr"],
                          ["(nthr >= 1 .and. nthr <= 16)"])
    if clause == "num_teams":
        c = {None: "num_teams(4)", "lower_bound": "num_teams(2: 4)"}.get(feat)
        if c is None:
            return None
        # without a lower bound it equals the upper bound: exactly 4 teams
        # (5.2 §10.2.1, 6.0 §12.2.1)
        want = "(nt == 4)" if feat is None else "(nt >= 2 .and. nt <= 4)"
        if v == 50:
            # 5.0: the clause is an upper bound ('less than or
            # equal to the value specified in the num_teams clause', 5.0
            # §2.7 p.83), so the program asks for one team, which leaves
            # exactly one: AFAR creates two teams for this loop without the
            # clause (CCE 19 one), so the check can fail (a bound of 4 was
            # met without the clause on both, audit)
            c, want = "num_teams(1)", "(nt == 1)"
        s = team_param(v, c, ["if (i == 1) nt = omp_get_num_teams()"],
                       ["integer :: nt"], [want])
        if feat == "lower_bound":
            s.no_oracle("implementation_defined", "the number of teams is "
                         "an implementation-defined value between the lower "
                         "and the upper bound (5.2 §10.2.1, 6.0 §12.2.1); "
                         "without the lower bound exactly the upper bound "
                         "(4) teams are created, which is also a conforming "
                         "execution of the form with the lower bound 2",
                         "num_teams_bounds", checked=True)
        return s
    if clause == "dist_schedule":
        c = {None: "dist_schedule(static)", "static": "dist_schedule(static)",
             "chunk_size": "dist_schedule(static, 4)"}.get(feat)
        if c is None:
            return None
        # 4 teams (num_teams(4)); each iteration records its team: one
        # chunk of about n/4 iterations per team, or chunks of 4
        # round-robin
        check = blocked("team", "n", "nt", "dok") if feat != "chunk_size" \
            else round_robin("team", "n", 4, "nt", "dok")
        s = team_param(v, f"num_teams(4) {c}",
                       ["team(i) = omp_get_team_num()",
                        "if (i == 1) nt = omp_get_num_teams()"],
                       ["integer :: team(n), nt"], ["(nt >= 1)", "dok"],
                       extra_decls=["logical :: dok"], post=check)
        s.focus = c
        if feat != "chunk_size":
            # With the corrected oracle (idle teams allowed) the
            # implementation-defined default distribution of AFAR and CCE
            # also passes, so the clause cannot be told apart from its
            # absence in one run; the check still tests what the clause
            # requires (checked: a failure is a real one)
            s.no_oracle("implementation_defined", STATIC_NO_CHUNK_WHY,
                        "dist_schedule_default", checked=True)
        return s
    if clause == "replayable":
        c = {None: "replayable", "replayable_expression": "replayable(.true.)"
             }.get(feat)
        if c is None:
            return None
        s = combined(v, c, key="target")
        return s.no_oracle("equivalent_default", "replayable(.true.) is "
                           "replayable (the argument defaults to true)",
                           "replayable_true_default") if feat else s
    if clause == "transparent":
        c = {None: "transparent", "impex_type": "transparent(omp_impex)"
             }.get(feat)
        return data_prog(v, c, **_UNCHECKED_CLAUSE("transparent")) \
            if c else None
    if clause == "nogroup":
        c = {None: "nogroup", "do_not_synchronize": "nogroup(.true.)"}.get(
            feat)
        return data_prog(v, c, **_UNCHECKED_CLAUSE("nogroup")) if c else None
    if clause in ("use_device_ptr", "is_device_ptr") and feat is None:
        s = device_ptr_prog(v)
        s.focus = "use_device_ptr(pa, pb)" if clause == "use_device_ptr" \
            else "is_device_ptr(pa, pb)"
        return s
    if clause in ("use_device_addr", "has_device_addr") and feat is None:
        s = device_addr_prog(v)
        s.focus = f"{clause}(a, b)"
        if clause == "has_device_addr":
            # Removing has_device_addr leaves the result unchanged on AFAR
            # and CCE 19 in both memory modes (they pass the device address
            # through an implicit map), and a device-side c_loc comparison
            # did not separate the two either: no check found.
            s.observable = False
            s.note = "has_device_addr itself is not checked"
            s.header_notes.append(
                "clause not checked: has_device_addr (removing it leaves the "
                "result unchanged on AFAR and CCE 19)")
            s.unverified("oracle_not_written", "re-categorised "
                         "(was implementation_defined): the spec fixes what "
                         "has_device_addr does (its list items 'may be "
                         "directly accessed from a target device', 5.2 "
                         "§5.4.9 p.122; their storage location is the same "
                         "inside the construct as for the original list "
                         "item, 6.0 §7.5.9 p.238), so a device-side check "
                         "that c_loc(a) in the region equals a's address in "
                         "the use_device_addr region (copy mode) is a "
                         "deterministic oracle of the original; it is not "
                         "written. Without the clause the program maps "
                         "storage that 'may not be accessible from the host "
                         "device' (5.2 §5.4.10 p.123), so no conforming "
                         "mutant exists: AFAR and CCE 19 translate it back "
                         "to the same device storage (9c probes)")
        return s
    return declare_clause(clause, feat, v)


def declare_clause(clause, feat, v) -> Src | None:
    """Clauses of declare target."""
    if clause == "enter":
        if feat is None:
            return declare_var_prog(v, omp("declare target", "enter(dv)"),
                                    focus="enter(dv)")
        if feat == "automap":
            # pv is an array: without the directive it is implicitly mapped
            # tofrom, so the device write of the first region comes back
            # to the host; with it pv is present and the host copy stays
            # unchanged. Copy mode only (shared storage hides the copy);
            # mutation-checked on AFAR (CCE 19 rejects enter(automap:)).
            s = declare_prog(v, focus="enter(automap: pv)",
                             body=("b(i) = 2*(pv(i) - 4) + 1",))
            s.module[2:2] = ["integer, allocatable :: pv(:)",
                             omp("declare target", "enter(automap: pv)")]
            s.shared_setup()
            s.init += ["allocate(pv(n))", "pv = a",
                       omp(spell("target update", v), "to(pv)"),
                       omp("target")] + seq_loop(("pv(i) = pv(i) + 4",)) + [
                       omp("end target")]
            s.post += ["if (.not. shared_mem) pres = pres .and. all(pv == a)",
                       "deallocate(pv)"]
            return s
        return None
    if clause == "to" and feat is None:
        return declare_prog(v, var=omp("declare target", "to(dv)"),
                            body=("b(i) = 2*a(i) + dv",), focus="to(dv)")
    if clause == "link" and feat is None:
        return declare_var_prog(v, omp("declare target", "link(dv)"),
                                focus="link(dv)", data=True)
    if clause == "local" and feat is None:
        return declare_var_prog(v, omp("declare target", "local(dv)"),
                                focus="local(dv)")
    if clause == "device_type":
        kind = feat or "any"
        if kind == "host":
            s = declare_prog(v, focus="device_type(host)", observable=False,
                             note="device_type(host): the function is only "
                             "called on the host")
            s.module += ["contains"] if "contains" not in s.module else []
            s.module += ["  integer function g(x)",
                         "    " + omp("declare target", proc_list(v, "g"),
                                      "device_type(host)"),
                         "    integer, intent(in) :: x", "    g = 2*x + 1",
                         "  end function g"]
            s.init += ["do i = 1, n", "  ref(i) = g(i)", "end do"]
            return s
        if kind not in ("any", "nohost"):
            return None
        return declare_prog(v, func=omp("declare target", proc_list(v),
                                        f"device_type({kind})"),
                            body=("b(i) = f(a(i))",),
                            focus=f"device_type({kind})", observable=False,
                            note=IMPLICIT_PROCEDURE_NOTE)
    if clause == "indirect":
        c = {None: "indirect", "invoked_by_fptr": "indirect(.true.)"}.get(feat)
        if c is None:
            return None
        # enter at both versions: AFAR rejects indirect with to ("The
        # INDIRECT clause cannot be used without the ENTER clause"), CCE 19
        # rejects enter (a listed confound in offload.engine.report)
        return declare_prog(v, func=omp("declare target", "enter(f)", c),
                            body=("b(i) = f(a(i))",), focus=c,
                            observable=False, note="f is called directly; "
                            "no indirect call is checked")
    return None
