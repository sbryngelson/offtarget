"""The findings index and failure signatures, used to find duplicates.

``load_index`` reads data/findings/index.yaml and the headers of the
minimized fuzz findings in data/findings/fuzz/, one ``Finding`` per file.
A failure signature is (front end, outcome group, site, key constructs).
The groups are compile-time {ice}, {rejected}, {compile timeout} and
run-time {wrong_answer, fell_back_to_host}, {crash, run_error, run timeout}.
The site of an ICE is the compiler source file and line (CCE) or the AFAR
stack frame or FIR message, recorded per release in ``sites``.

``match`` returns "duplicate" when toolchain, mode, arch and group are among
the finding's and the group's own test passes (same ICE site, rejection
message or crash signal; key constructs for a run-time failure). An ICE with
the same message but an unrecorded release site is "related"."""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path

import yaml

from offload.engine.confirm import programs as P
from offload.engine.toolchains import base_name

from offload.engine.root import ROOT  # noqa: E402
FINDINGS = ROOT / "data" / "findings"
INDEX = FINDINGS / "index.yaml"
GENERIC = frozenset({"dir:target", "clause:map", "clause:to", "clause:from",
                     "clause:tofrom", "clause:alloc", "clause:private",
                     "clause:shared", "clause:default", "clause:none",
                     "clause:implicit", "clause:firstprivate"})
GROUPS = {"ice": "ice", "rejected": "rejected", "wrong_answer": "wrong",
          "fell_back_to_host": "wrong", "crash": "abort",
          "run_error": "abort", "timeout": "abort", "accepted_ignored":
          "ignored", "harness_error": "env"}


# Constructs in a quarter or more of the s1 fuzz
# programs (P.constructs, 200 programs of seeds 1-399): not distinctive for
# a run-time signature in a fuzz program
COMMON_FUZZ = frozenset({
    "dir:declare target", "dir:target update", "dir:declare",
    "clause:reduction", "clause:mapper", "clause:enter", "clause:omp_out",
    "clause:pair_t", "dir:parallel", "dir:teams", "dir:do",
    "dir:distribute", "dir:loop", "dir:simd", "clause:if",
    "dir:target parallel", "clause:lastprivate"})
# runtime error messages of the failing run (offload runtimes, heap
# checks, Fortran runtimes): a failure's output pattern
RUNTIME_MESSAGE = re.compile(
    r"Unhandled Reduction|CRAY_ACC_ERROR[^\n]{0,60}|omptarget (?:fatal )?"
    r"error[^\n]{0,60}|OFFLOAD ERROR[^\n]{0,40}|Memory access fault|"
    r"free\(\)[^\n]{0,30}|double free|corrupted [^\n]{0,30}|"
    r"Fortran runtime error[^\n]{0,40}|hipError\w+|"
    # NVHPC's runtime ("Accelerator Fatal Error: call to
    # cuMemcpyDtoHAsync returned error 700 (CUDA_ERROR_ILLEGAL_ADDRESS)",
    # "FATAL ERROR: data in PRESENT clause ...", "Fatal error: NOT
    # IMPLEMENTED")
    r"Accelerator Fatal Error[^\n]{0,60}|FATAL ERROR: [^\n]{0,40}|"
    r"Fatal error: NOT IMPLEMENTED|CUDA_ERROR_\w+")
FUZZ_ID = re.compile(r"^[A-Za-z][\w-]*:\d+$")


def group(outcome: str, reason: str = "") -> str:
    if outcome == "timeout" and "compile" in (reason or ""):
        return "compile_timeout"
    return GROUPS.get(outcome, outcome)


@functools.lru_cache(maxsize=None)         # asked once per (toolchain, language) per cell; cleared with the registry
def front_end(toolchain: str, lang: str) -> str:
    from offload.engine.harness import table_key
    return table_key(base_name(toolchain), "c" if lang == "c" else "f90")


def normalize(msg: str) -> str:
    """A message without paths, line/column numbers, addresses, hashes."""
    from offload.engine.fuzz_min import ice_signature
    text = ice_signature(msg or "")
    # program line:column positions go; the compiler-source site stays
    text = re.sub(r"\b\d+:\d+\b", "", text)
    return " ".join(text.split())


_SITE = re.compile(r"(\w+\.(?:c|cc|cpp|C|f90)), line (\d+)")
_GCC_SITE = re.compile(r"internal compiler error: in \w+, at (?:\w+/)?([\w.-]+\.cc):(\d+)")
_SIGNAL = re.compile(r"\b(SIG[A-Z]+)\b")


_NV_ICE = re.compile(r"NV(?:FORTRAN|C\+\+)-[SFW]-\d+-(?:Internal compiler "
                     r"error[^\n;]*|Compiler failed to translate[^\n;]*)|"
                     r"nvvmCompileProgram: failed[^\n;]*")


def site_of(reason: str, output: str = "") -> str | None:
    """The ICE site: a compiler source file and line (CCE), else the AFAR
    stack frame or FIR verification message (fuzz_min.ice_signature)."""
    m = _SITE.search(reason or "")
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    g = _GCC_SITE.search(reason or "")
    if g:  # coverage parity: GCC's "internal compiler error: in F, at f.cc:N"
        return f"{g.group(1)}:{g.group(2)}"
    nv = _NV_ICE.search(reason or "")
    if nv:  # NVHPC names no compiler-source site: its message
        return "nvhpc " + " ".join(re.sub(r"\(<tmpdir>[^)]*\)|\d+", "",
                                            nv.group(0)).split())
    from offload.engine.fuzz_min import ice_signature
    sig = ice_signature(reason or "", output or "")
    return sig if sig.startswith("afar ") else None


def strip_site(text: str) -> str:
    """An ICE message without its compiler-source site, path and version
    (a fuzz finding's header embeds the site of its own release; fix
    The related test compares messages without it)."""
    text = (text or "").split(";")[0]
    text = re.sub(r"^ice:\s*", "", text)
    text = re.sub(r"\([^()]*\b\w+\.(?:c|cc|cpp|C), line \d+[^()]*\)", "",
                  text)
    text = re.sub(r"version \S+", "", text)
    return " ".join(text.split())


def signal_of(text: str) -> str | None:
    m = _SIGNAL.search(text or "")
    return m.group(1) if m else None


@dataclass(frozen=True)
class Finding:
    file: str
    toolchains: tuple
    lang: str
    outcome: str
    message: str = ""
    modes: tuple = ("unified", "copy")
    arch: tuple = ("gfx942",)
    expected: str = ""
    scope: str = "device"
    programs: tuple = ()
    constructs: frozenset = field(default_factory=frozenset)
    sites: dict = field(default_factory=dict, hash=False, compare=False)
    # A condition on the build path ("cif_split": the
    # CCE ftn split-CIF-record abort, which only a source path with "-1"
    # not followed by a digit can trigger; see ``path_allows``)
    path_rule: str = ""
    # a link failure whose undefined symbol other defects share
    # (flang_rt_verbose_abort): an instance only in a program with the
    # finding's key constructs, else no match
    link_needs_constructs: bool = False

    @property
    def group(self) -> str:
        return group(self.outcome, self.message)

    def front_ends(self) -> set[str]:
        return {front_end(t, self.lang) for t in self.toolchains}


def _key_constructs(text: str) -> frozenset:
    return frozenset(P.constructs(text) - GENERIC)


FUZZ_KIND = {"wrong_code": "wrong_answer", "run_error": "crash",
             "ice": "ice", "timeout": "timeout", "host_fallback":
             "fell_back_to_host"}


_FOLD = re.compile(r"\n!   (?=\S)")


def unfold(text: str) -> str:
    """Header lines wrapped at 132 characters (F2018 6.3.2.1): a comment
    line indented three spaces continues the line above."""
    return _FOLD.sub(" ", text)


def _fuzz_finding(path: Path) -> Finding | None:
    raw = path.read_text()
    text = unfold(raw)
    tc = re.search(r"^! toolchain: (\S+)", text, re.M)
    fail = re.search(r"^! failure: (\w+)(?: \((.*?)\))?(?::.*)?$", text,
                     re.M)
    if not tc or not fail:
        return None
    also = re.search(r"^! also fails on: (.*)$", text, re.M)
    tcs = (tc.group(1),) + tuple(t.strip() for t in also.group(1).split(",")
                                 ) if also else (tc.group(1),)
    kind = fail.group(1)
    msg = fail.group(2) or ""
    outcome = FUZZ_KIND.get(kind, kind)
    if kind == "run_error" and not msg.startswith("crash"):
        outcome = "run_error"
    xn = re.search(r"HSA_XNACK=(\d)", text)
    sites = {}
    if outcome == "ice":
        s = site_of(msg) or (msg if msg.startswith("afar ") else None)
        if s:
            sites[base_name(tc.group(1))] = s
    if outcome == "crash":
        sig = signal_of(msg)
        msg = sig or msg
    # The runtime message of the failure, when the
    # finding names it ("! message: <regex>")
    named = re.search(r"^! message: (.+)$", text, re.M)
    if named:
        msg = named.group(1).strip()
    # the failing toolchains' arch (a gfx942 campaign's findings stay
    # gfx942; coverage parity minimized GCC failures on gfx90a)
    from offload.engine.toolchains import TOOLCHAINS
    arch = tuple(dict.fromkeys(TOOLCHAINS[t].arch for t in tcs
                               if t in TOOLCHAINS)) or ("gfx942",)
    return Finding(str(path.relative_to(ROOT)), tcs, "f90", outcome, msg,
                   ("copy",) if xn and xn.group(1) == "0" else ("unified",),
                   arch, constructs=_key_constructs(raw),
                   sites=sites)


def load_index(index: Path = INDEX, fuzz_dir: Path | None = None
               ) -> list[Finding]:
    out = []
    data = yaml.safe_load(Path(index).read_text()) or {}
    for d in data.get("findings") or []:
        path = Path(index).parent / d["file"]
        cons = frozenset(d["constructs"]) if d.get("constructs") else (
            _key_constructs(path.read_text()) if path.is_file()
            else frozenset())
        out.append(Finding(str(path.relative_to(ROOT)) if
                           path.is_relative_to(ROOT) else str(path),
                           tuple(d["toolchains"]), d.get("lang", "f90"),
                           d["outcome"], d.get("message", ""),
                           tuple(d.get("modes") or ("unified", "copy")),
                           tuple(d.get("arch") or ("gfx942",)),
                           d.get("expected", ""), d.get("scope", "device"),
                           tuple(d.get("programs") or ()), cons,
                           dict(d.get("sites") or {}),
                           d.get("path_rule", ""),
                           bool(d.get("link_needs_constructs"))))
    fz = fuzz_dir or Path(index).parent / "fuzz"
    for p in sorted(Path(fz).glob("*.f90")):
        f = _fuzz_finding(p)
        if f is not None:
            out.append(f)
    return out


@lru_cache(maxsize=None)
def index() -> tuple:
    return tuple(load_index())


def _message_hit(f: Finding, reason: str) -> bool:
    if not f.message:
        return False
    try:
        if re.search(f.message, reason or ""):
            return True
    except re.error:
        pass
    return normalize(f.message) == normalize(reason) or (
        len(normalize(f.message)) > 12 and
        normalize(f.message) in normalize(reason))


_CUT = re.compile(r"-1(?!\d)")


def path_cuts(path: str) -> bool:
    """A source path that can cut CCE ftn's CIF: it holds "-1" not followed
    by a digit (tools/campaigns/ftn_cif_split.py; whether a record actually splits
    there needs the program's records)."""
    return bool(_CUT.search(path or ""))


def _opt_level(opt: str) -> str:
    """O0..O3 of a flag string or a stress build variant ("" unknown)."""
    m = re.search(r"-?O([0-3s])\b", opt or "")
    if m:
        return "O" + m.group(1)
    return {"lto": "O2", "noinline": "O2", "staticlib": "O2",
            "nordc": "O2"}.get(opt or "", "")


def path_allows(f: Finding, toolchain: str, lang: str, build_dir: str = "",
                source: str = "", opt: str = "") -> str | None:
    """For a finding with a path rule: "cut" when the recorded build path
    can trigger it, "unknown" when no path is recorded and the row is CCE
    ftn at -O2/-O3, None when the row cannot be an instance."""
    if f.path_rule != "cif_split":
        return "cut"
    if build_dir:
        return "cut" if path_cuts(build_dir.rstrip("/") + "/" + (
            source or "")) else None
    if base_name(toolchain).startswith("cce") and lang != "c" and \
            _opt_level(opt) in ("O2", "O3"):
        return "unknown"
    return None


def checked_wrong(outcome: str, reason: str, output: str = "") -> bool:
    """A run that stopped with exit status 1 and printed no runtime error:
    the program's own check found a wrong value."""
    return outcome == "run_error" and bool(
        re.match(r"exit_status: 1\b", reason or "")) and not \
        RUNTIME_MESSAGE.search((reason or "") + "\n" + (output or ""))


def match(f: Finding, toolchain: str, lang: str, outcome: str,
          reason: str, program_text: str, program_id: str = "",
          mode: str = "", arch: str = "", output: str = "",
          build_dir: str = "", source: str = "", opt: str = "",
          checked_exit_is_wrong: bool = False
          ) -> tuple[str, str] | None:
    """("duplicate" | "related", why) when the failure has the finding's
    signature (module docstring), else None. A finding with a path rule
    needs a recorded build path (and source file name)
    that can cut the CIF for a duplicate; without a recorded path a CCE
    ftn row at -O2/-O3 with its message is related; otherwise no match."""
    from offload.engine.toolchains import TOOLCHAINS
    if front_end(toolchain, lang) not in f.front_ends():
        return None
    base = base_name(toolchain)
    if base not in {base_name(t) for t in f.toolchains}:
        return None
    if mode and mode not in f.modes:
        return None
    arch = arch or (TOOLCHAINS[toolchain].arch if toolchain in TOOLCHAINS
                    else "")
    if arch and arch not in f.arch:
        return None
    if f.path_rule:
        how = path_allows(f, toolchain, lang, build_dir, source, opt)
        if how is None:
            return None
        # the driver's own abort: not another process's ("optcg was
        # terminated due to receipt of signal 06" with the heap message in
        # its output) and not an ICE with a compiler-source site
        other = "terminated due to receipt of signal" in (reason or "") or \
            bool(_SITE.search(reason or ""))
        if group(outcome, reason) != f.group or other or not (
                _message_hit(f, reason) or _message_hit(f, output)):
            return None
        if how == "cut":
            return "duplicate", ("the build path can cut the CIF "
                                 "(\"-1\" not followed by a digit) and the "
                                 "finding's message")
        return "related", ("the finding's message; the build path is not "
                           "recorded (CCE ftn at -O2/-O3)")
    g = group(outcome, reason)
    # for a miss analysis only (the confirmer never passes it):
    # a check that finds the wrong answer and stops with code 1 (run_error
    # "exit_status: 1", no runtime error message) is the wrong answer a
    # wrong_answer finding records; such a match of a program that is not
    # a fuzz program needs a distinctive key construct
    relaxed = False
    if checked_exit_is_wrong and f.group == "wrong" and \
            g != "wrong" and checked_wrong(outcome, reason, output):
        g, relaxed = "wrong", True
    if program_id and any(fnmatchcase(program_id, p) for p in f.programs) \
            and g == f.group:
        return "duplicate", f"program {program_id} is named by the finding"
    if g != f.group:
        return None
    if g == "ice":
        if not _message_hit(f, reason) and not f.sites and \
                strip_site(f.message) != strip_site(reason):
            return None
        site = site_of(reason, output)
        known = f.sites.get(base)
        if known and site and (site == known or known in site):
            return "duplicate", f"same ICE site {known}"
        if known and site:
            return None
        if _message_hit(f, reason) or (
                strip_site(f.message) and
                strip_site(f.message) == strip_site(reason)):
            return "related", ("same ICE message; site "
                               f"{site or 'unknown'} not recorded for "
                               f"{base} in the finding")
        return None
    if g == "rejected":
        if not _message_hit(f, reason):
            return None
        # A diagnostic (not a link failure, whose symbol names
        # the defect) is an instance only in a program with the finding's
        # key constructs; a fuzz program's same message elsewhere is
        # related
        if f.link_needs_constructs and \
                not f.constructs <= P.constructs(program_text or ""):
            return None
        if (reason or "").startswith("diagnostic") and f.constructs and \
                not f.constructs <= P.constructs(program_text or ""):
            return "related", ("same diagnostic, without the finding's "
                               "constructs " + ", ".join(sorted(
                                   f.constructs - P.constructs(
                                       program_text or ""))))
        return "duplicate", "same diagnostic"
    cons = P.constructs(program_text or "")
    key = f.constructs
    if not key or not key <= cons:
        return None
    if relaxed and not FUZZ_ID.match(program_id or "") and \
            not (key - GENERIC - COMMON_FUZZ):
        return None
    if g == "abort":
        fs = signal_of(f.message)
        cs = signal_of(reason + " " + output)
        if fs and cs != fs:
            return None
        if fs is None and f.message and not (
                _message_hit(f, reason) or _message_hit(f, output)):
            return None
    # A fuzz program (150-300 lines) holds most
    # common constructs, so a run-time instance needs a distinctive key
    # construct (one in fewer than a quarter of the s1 programs) or the
    # finding's own run-time message; else the failure is only related
    # A fuzz failure that prints a runtime error the
    # finding does not name is another signature (related)
    rt = RUNTIME_MESSAGE.search((reason or "") + "\n" + (output or ""))
    if FUZZ_ID.match(program_id or "") and rt and not (
            f.message and not signal_of(f.message) and (
                _message_hit(f, reason) or _message_hit(f, output))):
        return "related", (f"the failure prints {rt.group(0).strip()!r}, "
                           "which the finding does not name")
    if FUZZ_ID.match(program_id or "") and not (key - COMMON_FUZZ) and \
            not (f.message and not signal_of(f.message) and (
                _message_hit(f, reason) or _message_hit(f, output))):
        return "related", ("only common key constructs "
                           + ", ".join(sorted(key)))
    if len(key) >= 2:
        return "duplicate", "key constructs " + ", ".join(sorted(key))
    if f.message and (_message_hit(f, reason) or _message_hit(f, output)):
        return "duplicate", (f"key construct {next(iter(key))} and the "
                             "finding's message")
    return None


def matches(f: Finding, toolchain: str, lang: str, outcome: str,
            reason: str, program_text: str, program_id: str = "",
            mode: str = "") -> str | None:
    """Why the failure is a duplicate of the finding (None if it is
    not)."""
    m = match(f, toolchain, lang, outcome, reason, program_text,
              program_id, mode)
    return m[1] if m and m[0] == "duplicate" else None


def same_shape(f: Finding, lang: str, outcome: str, reason: str,
               mode: str) -> bool:
    """The finding has a reproducer of the case's shape (front-end
    language, outcome group, mode)."""
    return f.lang == ("c" if lang == "c" else "f90") and \
        f.group == group(outcome, reason) and mode in f.modes


def dedupe(toolchain: str, lang: str, outcome: str, reason: str,
           program_text: str, program_id: str = "", mode: str = "",
           findings=None, arch: str = "", output: str = "",
           related: bool = False, build_dir: str = "", source: str = "",
           opt: str = "") -> list[dict]:
    """The findings whose signature the failure has, best first
    (duplicates, named program, then the most key constructs); with
    `related`, the related ones too (kind "related"). build_dir, source
    and opt (the build path, source file name and optimization flags or
    stress variant, when the row records them) feed findings with a path
    rule."""
    out = []
    for f in findings if findings is not None else index():
        m = match(f, toolchain, lang, outcome, reason, program_text,
                  program_id, mode, arch, output, build_dir, source, opt)
        if m is None or (m[0] == "related" and not related):
            continue
        out.append({"file": f.file, "why": m[1], "kind": m[0],
                    "same_shape": same_shape(f, lang, outcome, reason,
                                             mode),
                    "score": (m[0] == "duplicate",
                              m[1].startswith("program"),
                              len(f.constructs))})
    out.sort(key=lambda d: d["score"], reverse=True)
    for d in out:
        d.pop("score")
    return out


# --- the index's mode and arch scope from the data ---

# verdicts that say nothing about the compiler, or a conforming refusal:
# such a cell never extends a finding's scope
NO_SCOPE_VERDICTS = frozenset({"our_bug", "environment", "not_a_failure",
                               "unspecified", "noncompliant",
                               "needs_unified_memory", "requirement_refused"})


def _best(hits: list) -> list:
    """The best-scoring duplicates (dedupe's order), ties kept."""
    if not hits:
        return []
    top = hits[0][0]
    return [f for s, f in hits if s == top]


def derive_scope(cells, findings=None, arches: tuple = (),
                 modes: tuple = ()) -> dict:
    """The (mode, arch) scope of each index finding from the data: the
    cells the confirmer instance-links to it (``match`` "duplicate").

    ``cells``: dicts with toolchain, lang, outcome, reason, text, ident,
    mode, arch, output, verdict (the stored failing cells and their
    confirmer verdicts). A cell links to a finding when its recorded scope
    covers it; a cell no finding's recorded scope covers is linked to the
    best finding that matches it with the arch widened to every arch (a
    gfx90a cell of a gfx942-only finding: equal cells), then,
    still unlinked, with the mode widened too. Returns {file: {"recorded":
    [(mode, arch)...], "linked": {(mode, arch): n}, "modes": [...],
    "arch": [...]}} where modes/arch are the recorded scope extended by
    every linked pair (a finding with no linked cell keeps its recorded
    scope: it came from runs outside these cells)."""
    import dataclasses
    fs = [f for f in (findings if findings is not None else index())]
    if not arches or not modes:
        from offload.engine.confirm.machines import load as _machines
        ms = _machines().values()
        arches = arches or tuple(sorted({m.arch for m in ms}))
        modes = modes or tuple(sorted({x for m in ms for x in m.modes}))
    wide_arch = [dataclasses.replace(f, arch=tuple(arches)) for f in fs]
    wide_both = [dataclasses.replace(f, arch=tuple(arches),
                                     modes=tuple(modes)) for f in fs]
    out = {f.file: {"recorded": sorted((m, a) for m in f.modes
                                       for a in f.arch),
                    "linked": {}} for f in fs}

    def hits(group, c):
        res = []
        for f, w in zip(fs, group):
            m = match(w, c["toolchain"], c["lang"], c["outcome"],
                      c["reason"], c["text"], c["ident"], c["mode"],
                      c["arch"], c.get("output", ""))
            if m and m[0] == "duplicate":
                res.append(((m[1].startswith("program"),
                             len(f.constructs)), f))
        res.sort(key=lambda x: x[0], reverse=True)
        return res

    for c in cells:
        if c.get("verdict") in NO_SCOPE_VERDICTS:
            continue
        got = _best(hits(fs, c)) or _best(hits(wide_arch, c)) or \
            _best(hits(wide_both, c))
        for f in got:
            k = (c["mode"], c["arch"])
            d = out[f.file]["linked"]
            d[k] = d.get(k, 0) + 1
    for f in fs:
        o = out[f.file]
        pairs = set(o["recorded"]) | set(o["linked"])
        o["modes"] = sorted({m for m, _ in pairs},
                            key=lambda m: (m != "unified", m))
        o["arch"] = sorted({a for _, a in pairs},
                           key=lambda a: (a != "gfx942", a))
    return out


def stored_cells(batch=None, kinds=("catalog", "ompvv")):
    """The failing cells of a confirmer batch file (default results/
    confirm/batch_full.jsonl) with their program text and stored output,
    for ``derive_scope`` (catalog and omp_vv programs: the hand-written
    findings explain these; fuzz cells link to the fuzz findings)."""
    import json
    from offload.engine.confirm import ingest as I
    batch = Path(batch) if batch else ROOT / "results" / "confirm" / \
        "batch_full.jsonl"
    idx = I.stored_index(include_fuzz=False)
    texts: dict = {}
    for line in batch.read_text().splitlines():
        d = json.loads(line)
        c = d["case"]
        kind, ident = c["program"]["kind"], c["program"]["ident"]
        if kind not in kinds:
            continue
        if (kind, ident) not in texts:
            ref = P.catalog_ref(ident) if kind == "catalog" else \
                P.ompvv_ref(ident)
            texts[(kind, ident)] = ref.text or ""
        row = idx.get(kind, ident, c["toolchain"], c["mode"])
        yield {"toolchain": c["toolchain"], "lang": c["program"]["lang"],
               "outcome": c["outcome"], "reason": c["reason"],
               "text": texts[(kind, ident)], "ident": ident,
               "mode": c["mode"], "arch": c["arch"],
               "output": (row.extra or {}).get("stderr_tail", "")
               if row is not None else "", "verdict": d["verdict"]}


def write_scope(scope: dict, index: Path = INDEX) -> list[str]:
    """Rewrite the ``modes`` and ``arch`` lines of the index entries whose
    derived scope (``derive_scope``) differs; returns the files changed.
    Comments and every other line are kept."""
    lines = Path(index).read_text().splitlines(keepends=True)
    out, changed, cur = [], [], None
    for ln in lines:
        m = re.match(r"^  - file: (\S+)", ln)
        if m:
            cur = "data/findings/" + m.group(1)
        key = re.match(r"^    (modes|arch): \[(.*)\]\s*$", ln)
        if cur in scope and key:
            want = scope[cur]["modes" if key.group(1) == "modes" else
                              "arch"]
            new = f"    {key.group(1)}: [{', '.join(want)}]\n"
            if new != ln:
                changed.append(cur)
            ln = new
        out.append(ln)
    Path(index).write_text("".join(out))
    return sorted(set(changed))
