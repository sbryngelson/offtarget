"""Support table and vendor-claims comparison.

Reads the matrix (results/matrix.jsonl, one Result per program, toolchain and
memory mode), the oracle audit summary (tests/data/oracle_audit_summary.json)
and the vendor claims (catalog/omp/claims.yaml), and renders
results/support_table.md and results/support_table.csv
(command line: tools/derive/support_table.py).
One table row per matrix cell (program x toolchain x HSA_XNACK). The headline
outcome is HSA_XNACK=1 with THP; the copy-mode column (HSA_XNACK=0) is filled
where the program ran in copy mode (``COPY_MARK`` marks copy_mode_only). Each cell carries its
evidence level and its atom's audit disposition. Cells without a separating
oracle read ``NO_ORACLE_TEXT``, ``LEGALITY_TEXT`` or ``UNVERIFIED_TEXT`` and
never count as supported. A wrong answer is "confirmed" only when the atom's
oracle is audited valid. A dagger marks modes that ran on different nodes.
The omp_vv suite is a second source. OpenACC matrices use the OpenACC catalog."""
from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path

import yaml

from offload.engine.textclean import scrub as _public
from offload.engine.toolchains import arch_of, base_name, family
# Report.family (below) is the label category; the toolchain
# family (message tables: every CCE release is cce19; a gfx90a twin is its
# compiler) is this one
from offload.engine.toolchains import family as _tc_family

ROOT = Path(__file__).resolve().parent.parent.parent
MATRIX = ROOT / "results" / "matrix.jsonl"
BASELINE = ROOT / "results" / "baseline.jsonl"
AUDIT = ROOT / "tests" / "data" / "oracle_audit_summary.json"
# The generic claims ingested from the vendor documents
# (tools/derive/claims.py ingest; mapping in catalog/<model>/claims.yaml)
CLAIMS = ROOT / "catalog" / "vendor_claims_generic.yaml"
CLAUSES = ROOT / "catalog" / "omp" / "clauses.yaml"
RULES = ROOT / "catalog" / "omp" / "rules.yaml"
OVERRIDES = ROOT / "catalog" / "omp" / "spec_overrides.yaml"

# Links in the Markdown are relative to results/support_table.md.
LINK = {"clauses": "../catalog/omp/clauses.yaml",
        "skeleton": "../catalog/omp/skeleton.yaml",
        "rules": "../catalog/omp/rules.yaml",
        "claims": "../catalog/vendor_claims_generic.yaml",
        "semantic": "../catalog/omp/semantic_atoms.yaml",
        "audit": "../reports/oracle-audit.md"}
# The OpenACC catalog and audit
ACC_AUDIT = ROOT / "tests" / "data" / "acc_audit_summary.json"
ACC_CLAIMS = CLAIMS
ACC_MATRIX = ROOT / "results" / "acc_matrix.jsonl"
# The C programs' matrix, audit summary and omp_vv C baseline
C_MATRIX = ROOT / "results" / "matrix_c.jsonl"
C_AUDIT = ROOT / "tests" / "data" / "oracle_audit_summary_c.json"
C_BASELINE = ROOT / "results" / "baseline_c.jsonl"
# The OpenACC C slice (NVHPC only; its audits are NV_AUDIT's)
ACC_C_MATRIX = ROOT / "results" / "acc_matrix_c.jsonl"
ACC_C_AUDIT = ROOT / "tests" / "data" / "acc_audit_summary_c.json"
LINK_ACC = {k: v.replace("/omp/", "/acc/") for k, v in LINK.items()}
LINK_ACC["audit"] = "../reports/acc-oracle-audit.md"
# the OpenACC section of each directive (3.4)
ACC_DIRECTIVE_SECTION = {
    "parallel": "2.5.1", "serial": "2.5.2", "kernels": "2.5.3",
    "data": "2.6.5", "enter_data": "2.6.6", "exit_data": "2.6.6",
    "host_data": "2.8", "loop": "2.9", "cache": "2.10",
    "parallel_loop": "2.11", "serial_loop": "2.11", "kernels_loop": "2.11",
    "atomic": "2.12", "declare": "2.13", "init": "2.14.1",
    "shutdown": "2.14.2", "set": "2.14.3", "update": "2.14.4",
    "routine": "2.15.1", "wait": "2.16.3"}


def model_of_atom(atom: str) -> str:
    return "acc" if atom.startswith("acc.") else "omp"


def _paths(model: str) -> tuple[Path, Path, Path, dict]:
    """(clauses, rules, overrides, links) of a model's catalog."""
    d = ROOT / "catalog" / model
    return (d / "clauses.yaml", d / "rules.yaml", d / "spec_overrides.yaml",
            LINK_ACC if model == "acc" else LINK)


def table_model(table) -> str:
    """"acc" when every row is an OpenACC atom, else "omp"."""
    return "acc" if table and all(r.atom.startswith("acc.")
                                  for r in table) else "omp"


def table_lang(table) -> str:
    """"c" when every row is a C program, else "f90"."""
    return "c" if table and all(getattr(r, "lang", "f90") == "c"
                                for r in table) else "f90"

# "unverified" only where a deterministic oracle is possible and
# missing; the forms no run can separate read as their category.
UNVERIFIED_TEXT = "accepted; unverified (an oracle is possible but missing)"
NO_ORACLE_TEXT = {
    "hint_only": "accepted; conforms vacuously",
    "implementation_defined": "implementation-defined",
    "equivalent_default": "equivalent to the default (no separable effect)"}
LEGALITY_TEXT = "accepted (its oracle is the illegal variant)"
NO_ORACLE_NAME = {"hint_only": "hint only",
                  "implementation_defined": "implementation-defined",
                  "equivalent_default": "equivalent default"}
EVIDENCE_LEVELS = ("construct", "probe", "copy_mode_only", "hint_only",
                   "implementation_defined", "equivalent_default",
                   "legality", "unverified")
# evidence whose accepted run is never credited as support
UNCREDITED = ("unverified", "legality") + tuple(NO_ORACLE_TEXT)
# the toolchains and their names come from catalog/toolchains.yaml
# (offload.engine.toolchains): the AMD columns (each with its HSA_XNACK modes,
# then its twins), the NVIDIA machine's toolchains get columns of their own
from offload.engine.toolchains import NVIDIA_TOOLCHAINS  # noqa: E402
from offload.engine.toolchains import ARCH_SUFFIX as _SUFFIX, registry as _reg  # noqa: E402
# the AMD columns: every AMD toolchain with a report column that is neither a
# twin nor a regression release (AFAR, CCE, GCC)
ALL_TOOLCHAINS = _reg().of_gpu("amd")
# the toolchains with rows in the matrix being rendered (build_table narrows
# it); a column for a compiler that was never run would only say "not run"
TOOLCHAINS = list(ALL_TOOLCHAINS)
HEADLINE, COPY = 1, 0
MODES = (HEADLINE, COPY)  # headline HSA_XNACK=1 first, then copy mode
# The gfx90a twin of each toolchain (Tioga MI250X, a discrete GPU,
# HSA_XNACK=0 only): a third column per compiler, after its two MI300A
# modes. G90 holds the twins with rows in the matrix being rendered.
G90_SUFFIX = _SUFFIX["gfx90a"]
G90: list[str] = []
# Every twin with rows in the matrix being rendered, in catalog order: the
# gfx90a ones and those on other machines (MI300X, MI350X, copy memory only).
# Each is a cell column after its compiler's MI300A modes; only the gfx90a
# cell enters the portable verdict (portable3).
TWINS: list[str] = []
# the AMD columns' toolchains with MI300A rows of their own (a compiler whose
# MI300A rows are left out, GCC, has only its twins' columns)
MI300A: list[str] = []
# Toolchains of other machines (NVIDIA: nvhpc on wingtip, A100,
# sm_80) get columns of their own after the AMD ones, one per memory mode
# of their machine (catalog/machines.yaml: headline mode first); the AMD
# columns, cells and verdicts are computed as before and never read an
# NVIDIA row. NV holds those with rows in the matrix being rendered.
NV: list[str] = []
# toolchains left out of the support tables on purpose (catalog
# ``report_column: false``): their rows are dropped, never an error
REPORT_EXCLUDED = tuple(n for n, t in _reg().toolchains.items()
                        if not t.report_column)
# the column names: every column (and the excluded) by its catalog label
TC_NAME = {n: _reg().label(n) for n in (*ALL_TOOLCHAINS,
                                        *(w for t in ALL_TOOLCHAINS for w in _reg().twins_of(t)),
                                        *NVIDIA_TOOLCHAINS, *REPORT_EXCLUDED)
           if n in _reg().toolchains}  # a gfx942 toolchain may have no twin yet


def nv_modes(tc: str) -> tuple[int, ...]:
    """The row keys of an NVIDIA toolchain's modes, headline first (those
    the toolchain has: GCC runs separate memory only)."""
    from offload.engine.confirm.machines import machine_of
    from offload.engine.toolchains import TOOLCHAINS as _TC
    m = machine_of(tc)
    keys = (m.row_key(m.headline_mode),) + tuple(
        m.row_key(x) for x in m.other_modes(m.headline_mode))
    return tuple(k for k in keys if k in _TC[tc].xnack_modes)


def nv_mode_name(tc: str, x: int) -> str:
    """The mode's name for an NVIDIA row ("separate", "managed"): the
    machine's mode, ``copy`` named after NVHPC's -gpu=mem:separate."""
    from offload.engine.confirm.machines import machine_of
    m = machine_of(tc).mode_of_row_key(x)
    return "separate" if m == "copy" else m


def _mode_word(tc: str, x: int) -> str:
    """How a cell's memory mode is named in a label."""
    return nv_mode_name(tc, x) if tc in NVIDIA_TOOLCHAINS \
        else f"HSA_XNACK={x}"


def g90_of(tc: str) -> str:
    """The gfx90a twin's name of a gfx942 toolchain."""
    return f"{tc}{G90_SUFFIX}"


def twins_of(tc: str) -> list[str]:
    """The twins of a compiler with rows in the matrix being rendered."""
    return [w for w in _reg().twins_of(tc) if w in TWINS]


def columns() -> list[tuple[str, int]]:
    """The (toolchain, xnack) cell columns, per compiler: HSA_XNACK=1 and
    0 on MI300A, then each twin with rows (HSA_XNACK=0)."""
    out = []
    for tc in TOOLCHAINS:
        out += [(tc, x) for x in MODES] if tc in MI300A else []
        out += [(w, COPY) for w in twins_of(tc)]
    for tc in NV:  
        out += [(tc, x) for x in nv_modes(tc)]
    return out
COPY_MARK = "◊"
NOT_RUN = "not run"
COPY_NOT_RUN = "copy-mode check not run"
# outcomes the memory mode cannot change: no copy-mode pointer needed
_COMPILE_TIME = ("rejected", "harness_error")
CLAIM_VALUES = ("supported", "unsupported", "partial")
CLAIM_FORMS = (None, "compile_error", "accepted")

# How a rejected legal cell is attributed:
# - NOT COUNTED (against the atom or in the claims): a listed confound
#   (CONFOUNDS: the message shows that the compiler rejected another feature
#   the program needs), or a diagnostic at an OpenMP directive line that
#   does not carry the atom (_line_confound; e.g. AFAR stops at the
#   uses_allocators line of an allocate program).
# - COUNTED WITH A CAVEAT (‡): a listed caveat (CAVEATS: the rejection is
#   the atom's own, but the message needs context), or a diagnostic at a
#   non-directive statement that does not carry the atom (the compiler's
#   check of the atom points at a statement that uses a variable).
# Each entry: (atom patterns, toolchain, message regex, text); it applies
# only to a rejected cell whose toolchain and reason match.
_ALLOC = ("the allocate programs also use uses_allocators("
          "omp_default_mem_alloc); AFAR rejects them with 'USES_ALLOCATORS "
          "clause is not implemented yet', so they measure uses_allocators, "
          "not allocate")
_DSIMD = ("the linear(ref) and linear(uval) programs put the clause on "
          "declare simd; AFAR stops with 'not yet implemented: "
          "omp.declare_simd', so they measure declare simd, not the modifier")
CONFOUNDS = (
    (("omp.clause.allocate", "omp.clause.allocate.a*"), "afar",
     r"USES_ALLOCATORS", _ALLOC),
    (("omp.clause.linear.ref", "omp.clause.linear.uval"), "afar",
     r"omp\.declare_simd", _DSIMD),
    # 5.0 allows a linear modifier only on declare simd (5.0
    # §2.9.2 p.107), so the 5.0 linear(val) program is a declare simd one
    (("omp.clause.linear.val",), "afar", r"omp\.declare_simd",
     "at 5.0 the linear(val(x)) program puts the clause on declare simd "
     "(5.0 allows no linear modifier on the worksharing-loop and simd "
     "constructs); AFAR stops with 'not yet implemented: omp.declare_simd', "
     "so it measures declare simd, not the modifier"),
    (("omp.clause.allocate",), "cce19",
     r"DYNAMIC_ALLOCATORS",
     "the allocate(t) program "
     "has requires dynamic_allocators (an allocate clause in a target "
     "region without an allocator needs it, 5.2 §6.6 p.179, 6.0 §8.6 "
     "p.313); CCE 19 does not implement that requirement, so it measures "
     "dynamic_allocators, not allocate"),
    (("omp.clause.device_type*", "omp.clause.indirect*"), "cce19",
     r"INDIRECT, LINK, TO or DEVICE_TYPE",
     "CCE 19 rejects the enter spelling on declare target (ftn-1725 "
     "'\"INDIRECT, LINK, TO or DEVICE_TYPE\" was expected'); the 6.0 program "
     "must use enter (to is not allowed on declare target at 6.0), so it "
     "measures enter, not the clause under test"),
    (("omp.directive.target_teams_distribute_simd",), "afar",
     r"DEFAULT clause is not allowed",
     "AFAR rejected the default(none) hygiene clause, which only a "
     "provisional spec override allows on this directive at 5.2"),
    (("omp.clause.default.shared", "omp.clause.default.all"), None,
     r"^ice:",
     "the program needs an explicit task in a target region (default(shared) "
     "differs from the default only on a task); both toolchains fail to "
     "compile any task in a target region, with or without the default "
     "clause (AFAR: segmentation fault in OpenMPIRBuilder::createTask; CCE "
     "19: internal compiler error 'unhandled construct type'), so "
     "it measures the task construct on the device, not "
     "default(shared)"),
    (("omp.clause.uses_allocators.memspace", "omp.clause.uses_allocators.traits"),
     "cce19", r"ftn-1510",
     "CCE 19 rejected the allocator handle my_alloc for lacking a "
     "data-sharing attribute under default(none) (ftn-1510), not the "
     "uses_allocators modifier"),
)


CAVEATS = (
    (("omp.clause.in_reduction.*",), "afar",
     r"no symbol found for|minus reduction operator is deprecated",
     "AFAR's error is on the companion task_reduction line that the spec "
     "requires for in_reduction (same reduction identifier), not on the "
     "in_reduction clause"),
    (("omp.clause.transparent*",), None, r"(?i)omp_impex",
     "the cause is omp_impex missing from the compiler's omp_lib module (a "
     "6.0 runtime constant the clause needs), not a parse of the clause"),
    (("omp.clause.device_type.nohost",), "cce19", r"f\$gen_mod_",
     "link failure: undefined `f$gen_mod_` from the host build (the host "
     "version of the target region references the nohost procedure); "
     "whether that is a CCE gap or a non-conforming program is open"),
    # Omp_vv cross-check, decided by results/task14/probe runs
    (("omp.clause.order", "omp.clause.order.*"), "afar",
     r"Unhandled clause order in omp\.wsloop",
     "construct-specific: AFAR rejects order on the worksharing-loop "
     "construct this program uses (parallel do; also on loop: 'Unhandled "
     "clause order in omp.loop'), but compiles and runs order(concurrent) "
     "on simd and target simd in both memory modes (probe and "
     "omp_vv test_target_simd_order_concurrent)"),
    (("omp.clause.map.iterator",), "cce19", r"OmpIt\$",
     "construct-specific: CCE 19 fails to link map(iterator) on target "
     "enter data, which this program uses (undefined `OmpIt$k`); on the "
     "target construct it links, runs correctly at HSA_XNACK=0 and fails at "
     "HSA_XNACK=1 in the runtime (hipFree hipErrorInvalidValue; "
     "omp_vv test_target_map_iterators)"),
)
VARIABLE_STATEMENT = ("the compiler points at a statement that uses a "
                      "variable, not at the clause")


def confound(atom: str, toolchain: str | None = None,
             reason: str | None = None, table=None) -> str | None:
    """The listed text for a rejected cell (atom, toolchain, reason) from
    `table` (CONFOUNDS by default); with only `atom`, any entry for it."""
    for pats, tc, rx, text in (CONFOUNDS if table is None else table):
        if not any(fnmatchcase(atom, p) for p in pats):
            continue
        if toolchain is None or (tc in (None, _tc_family(toolchain))
                                 and reason is not None
                                 and re.search(rx, reason)):
            return text
    return None


_LINE_RX = (re.compile(r'\.f90"?:(\d+):\d+'), re.compile(r"Line = (\d+)"),
            # Clang diagnostics of the C programs
            re.compile(r'\.c:(\d+):\d+'),
            # NVHPC, "NVFORTRAN-S-0034-... (<file>.f90: 12)" and
            # nvc's '"<file>.c", line 12: error: ...'
            re.compile(r'\.f90: (\d+)\)'), re.compile(r'\.c", line (\d+):'))


def diagnosed_line(reason: str) -> int | None:
    """The source line a compiler diagnostic in `reason` points at."""
    for rx in _LINE_RX:
        m = rx.search(reason)
        if m:
            return int(m.group(1))
    return None


def _statement(source: str, n: int) -> str | None:
    """Line n (1-based) of `source` with its & continuation lines (C: its
    backslash continuation lines)."""
    lines = source.splitlines()
    if not 1 <= n <= len(lines):
        return None
    cont = "\\" if re.search(r"^\s*#\s*pragma\s+omp", source, re.M) \
        else "&"
    i = j = n - 1
    while i > 0 and lines[i - 1].rstrip().endswith(cont):
        i -= 1
    while j < len(lines) - 1 and lines[j].rstrip().endswith(cont):
        j += 1
    return " ".join(lines[i:j + 1]).lower()


def carries(atom: str, text: str) -> bool:
    """Whether a statement carries the atom: its clause name followed by
    `(` or a word end, or its directive name. A semantic atom
    (catalog/<model>/semantic_atoms.yaml, e.g.
    ``omp.clause.defaultmap.character``) is exercised through the
    program's data, not through a clause, so every statement of its
    program carries it: a rejection at a directive line is the atom's own
    failure."""
    from offload.engine.catalog import semantic_atoms
    if atom in semantic_atoms():
        return True
    parts = atom.split(".")
    if len(parts) >= 3 and parts[1] == "clause":
        return re.search(rf"(?<![\w]){re.escape(parts[2])}\b", text) is not None
    if len(parts) >= 3 and parts[1] == "directive":
        words = parts[2].split("_")
        return re.search(r"\b" + r"[\s_]*".join(map(re.escape, words))
                         + r"\b", text) is not None
    return True


def _line_confound(atom: str, reason: str, source: str | None
                   ) -> tuple[str, bool]:
    """(text, excluded) for a diagnostic at a line that does not carry the
    atom: excluded when that line is an OpenMP directive, counted with a
    caveat otherwise; ("", False) when the line carries the atom or cannot
    be found."""
    n = diagnosed_line(reason)
    if n is None or source is None:
        return "", False
    text = _statement(source, n)
    if text is None or carries(atom, text):
        return "", False
    if text.lstrip().startswith(("!$omp", "!$acc")) or re.match(
            r"\s*#\s*pragma\s+omp\b", text):
        return (f"the diagnosed directive line {n} does not carry the atom",
                True)
    return f"{VARIABLE_STATEMENT} (line {n})", False


@lru_cache(maxsize=None)
def _programs(version: int, lang: str = "f90") -> dict:
    from offload.engine.catalog import model_of, slice_atoms
    if lang == "c" and model_of(version) == "acc":
        from offload.engine.acc_c_gen import all_acc_c_programs  
        return {p.id: p.source for p in all_acc_c_programs()}
    if lang == "c":
        from offload.engine.c_gen import all_c_programs
        return {p.id: p.source for p in all_c_programs(version)}
    from offload.engine.gen import generate
    return {p.id: p.source for p in generate(slice_atoms(version), version)}


def generated_source(program_id: str, atom: str, version: int) -> str | None:
    """The current generator's source of a matrix program (None if it is no
    longer generated); a C program (``ompNN-c-...``) from
    offload.engine.c_gen."""
    lang = "c" if re.match(r"(omp|acc)\d\d-c-", program_id) else "f90"
    try:
        return _programs(version, lang).get(program_id)
    except Exception:
        return None


def _root_reason(rec: dict) -> str:
    """A CCE reason quoting a module summary (ftn-855/894) is replaced by
    the root error from the stored stderr."""
    reason = rec.get("reason", "")
    if family(rec.get("toolchain", "")) != "cce19" or not re.search(
            r"ftn-(855|894) ftn:", reason):
        return reason
    from offload.engine.harness import classify_message
    found = classify_message("cce19", rec.get("stderr", ""))
    if not found or re.search(r"ftn-(855|894) ftn:", found[1]):
        return reason
    prefix = reason.split(":", 1)[0]
    return f"{prefix}: {found[1]}"


AUDIT_TEXT = {
    "valid": "audited (valid)",
    "unaudited_no_passing_original": "oracle unaudited",
    "hint_only": "no oracle (hint only)",
    "implementation_defined": "no oracle (implementation-defined)",
    "equivalent_default": "no oracle (equivalent default)",
    "legality": "legality (illegal variant)",
    "unverified_oracle_not_written": "unverified (oracle not written)",
    "unverified_needs_other_infrastructure": "unverified (needs other "
                                             "infrastructure)",
    "not_observable": "not observable",
    "": "not in audit",
}


# --- the table -----------------------------------------------------------------------

@dataclass(frozen=True)
class Row:
    atom: str
    toolchain: str
    xnack: int
    outcome: str          # harness outcome; illegal cells: rejected | not_rejected
    flaky: bool
    version: int = 0
    program_id: str = ""
    legal: bool = True
    violates: str | None = None
    evidence: str = "construct"
    audit: str = ""       # audit disposition of (version, atom), "" if none
    label: str = ""       # what the report prints for the cell
    reason: str = ""
    needs: tuple = ()
    thp: str = ""
    confound: str = ""    # caveat or exclusion reason of a rejection
    excluded: bool = False  # rejection not counted (another feature)
    copy_label: str = ""  # headline rows: the copy-mode label, or NOT_RUN
    basis: str = ""       # no-oracle programs: '<cite>: "<spec sentence>"'
    lang: str = "f90"     # "c" for a C program
    # "device" (the atom's headline program) or "host+device" (a
    # host construct feeding a target region, reported apart) and, for the
    # latter, the realistic use its program header names
    scope: str = "device"
    use: str = ""
    # Headline legal rows: the portable verdict (PORTABLE) and,
    # when the two modes differ, the class of the difference (MODE_CLASSES,
    # catalog/mode_differences.yaml; "unclassified" if no entry)
    portable: str = ""
    mode_class: str = ""
    # The outcome of the program's presence checks run at
    # HSA_XNACK=1 (tools/campaigns/presence_x1.py), "" if it has none
    presence_x1: str = ""
    # Headline legal rows: the class of a difference between the
    # MI300A copy-mode cell and the gfx90a cell (ARCH_CLASSES,
    # catalog/mode_differences.yaml arch_entries; "unclassified" if none)
    arch_class: str = ""
    # Failing legal cells: the reproduction gate's status
    # (GATE_STATES, annotate_gate); "" for every other cell
    gate: str = ""


def _audit_map(path: Path | None) -> dict[tuple[int, str], str]:
    if path is None or not Path(path).is_file():
        return {}
    data = json.loads(Path(path).read_text())
    return {(int(v), atom): e.get("disposition", "")
            for v, atoms in data.get("versions", {}).items()
            for atom, e in atoms.items()}


# The NVIDIA toolchains' oracle audits (tools/campaigns/oracle_audit.py
# --toolchains nvhpc, one run per memory mode), per model and language:
# {"modes": {"<row key>": <an audit summary>}}
NV_AUDIT = {("omp", "f90"): ROOT / "tests" / "data" /
            "oracle_audit_summary_nvhpc.json",
            ("omp", "c"): ROOT / "tests" / "data" /
            "oracle_audit_summary_nvhpc_c.json",
            ("acc", "f90"): ROOT / "tests" / "data" /
            "acc_audit_summary_nvhpc.json",
            # The OpenACC C slice
            ("acc", "c"): ROOT / "tests" / "data" /
            "acc_audit_summary_nvhpc_c.json"}


@lru_cache(maxsize=None)
def _nv_audit_file(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        return {}
    return {int(x): {(int(v), atom): e.get("disposition", "")
                     for v, atoms in doc.get("versions", {}).items()
                     for atom, e in atoms.items()}
            for x, doc in json.loads(p.read_text()).get("modes", {}).items()}


def nv_audit_path(toolchain: str, model: str, lang: str) -> Path | None:
    """The NVIDIA audit summary of a toolchain (NV_AUDIT is nvhpc's;
    another release's is the same file name with its toolchain, e.g.
    oracle_audit_summary_nvhpc269.json); a release without its own audit
    reuses nvhpc's (ruling: the programs are unchanged)."""
    path = NV_AUDIT.get((model, lang))
    if path is None or toolchain == "nvhpc":
        return path
    own = path.with_name(path.name.replace("_nvhpc", f"_{toolchain}"))
    return own if own.is_file() else path


def _nv_audit(rec: dict) -> dict:
    path = nv_audit_path(rec["toolchain"], rec.get("model", "omp"),
                         "c" if rec.get("lang") == "c" else "f90")
    return _nv_audit_file(str(path)).get(int(rec["xnack"]), {}) \
        if path else {}


def _is_crash(rec: dict | None) -> bool:
    return (rec is not None and rec["outcome"] == "wrong_answer"
            and rec.get("reason", "").startswith("crash:"))


def _crash_kind(reason: str) -> str:
    return reason[len("crash:"):].split(";")[0].strip()


def _label(rec: dict, other: dict | None, disposition: str) -> str:
    """The report text for one legal or illegal cell (see module docstring)."""
    o = rec["outcome"]
    if not rec.get("legal", True):
        return {"rejected": "rejected",
                "harness_error": "harness error"}.get(o, "not rejected")
    if o == "harness_error":
        return "harness error"
    ev = rec.get("evidence", "construct")
    unaudited = disposition.startswith("unaudited")
    mark = " (oracle unaudited)" if unaudited else ""
    flaky = " [flaky]" if rec.get("flaky") else ""
    nv = rec["toolchain"] in NVIDIA_TOOLCHAINS
    if ("zero_copy" in rec.get("needs", ()) and (rec["xnack"] == 0 or nv)
            and o in ("wrong_answer", "fell_back_to_host")):
        how = _crash_kind(rec["reason"]) if _is_crash(rec) else rec["reason"]
        # No NVHPC mode on wingtip is unified memory
        need = (f"{nv_mode_name(rec['toolchain'], rec['xnack'])} memory, no "
                "unified memory on this machine" if nv else "HSA_XNACK=1")
        return ("fails in copy mode: needs zero-copy memory "
                f"({need}); {how.split(';')[0]}{flaky}")
    if _is_crash(rec):
        text = f"crash: {_crash_kind(rec['reason'])}"
        if other is not None and not _is_crash(other):
            text += f", {_mode_word(rec['toolchain'], rec['xnack'])} only"
        return text + mark + flaky
    if o == "rejected":
        return "rejected" + flaky
    if o == "accepted_ignored":
        return "accepted, ignored (warning)" + flaky
    if o == "fell_back_to_host":
        return "fell back to host" + mark + flaky
    if o == "wrong_answer":
        if ev == "probe" and "compile-time" in rec["reason"]:
            return ("compile-time probe failed" + (
                " (confirmed)" if disposition == "valid" else "")
                + mark + flaky)
        if ev == "probe" and "no_error_termination" in rec["reason"]:
            return ("no error termination (negative probe" + (
                ", confirmed" if disposition == "valid" else "")
                + ")" + mark + flaky)
        if unaudited:
            return "wrong answer (oracle unaudited)" + flaky
        if ev == "unverified":
            return "wrong answer (evidence unverified)" + flaky
        if ev in NO_ORACLE_TEXT:
            return f"wrong answer (no oracle: {NO_ORACLE_NAME[ev]})" + flaky
        if ev == "legality":
            return "wrong answer (legality program's kernel)" + flaky
        if disposition == "valid":
            return "wrong answer (confirmed)" + flaky
        return "wrong answer" + flaky
    if ev in UNCREDITED and o in ("correct_on_device", "unobservable"):
        return {"unverified": UNVERIFIED_TEXT, "legality": LEGALITY_TEXT,
                **NO_ORACLE_TEXT}[ev] + flaky
    if o == "unobservable":
        return "compiled and ran; nothing checked (unobservable)" + flaky
    if o == "correct_on_device":
        if unaudited:
            return "correct on device (oracle unaudited)" + flaky
        if ev == "copy_mode_only" and rec["xnack"] == 1 and not nv:
            return ("correct on device (copy-mode evidence; not separable at "
                    "HSA_XNACK=1)" + flaky)
        if ev == "copy_mode_only" and nv and rec["xnack"] != nv_modes(
                rec["toolchain"])[0]:  # Managed shares the heap
            return ("correct on device (copy-mode evidence; not separable in "
                    f"{nv_mode_name(rec['toolchain'], rec['xnack'])} memory)"
                    + flaky)
        if ev == "probe" and rec["reason"].startswith(
                "compile_error_termination"):
            return ("compile-time error termination as required (probe)"
                    + flaky)
        if ev == "probe" and "compile message: " in rec["reason"]:
            return ("correct on device; compile-time message as required "
                    "(probe)" + flaky)
        if ev == "probe":
            return "error termination as required (negative probe)" + flaky
        return "correct on device" + flaky
    return o + flaky


COMPANION_SUFFIX = "-binop"  # offload.engine.acc_c_gen.BINOP_SUFFIX


def is_companion(program_id: str) -> bool:
    """A companion form of an atom's program (the
    OpenACC C port's atomic update as written, beside the atom's program),
    not the atom's program: kept out of the one-row-per-atom tables."""
    return program_id.endswith(COMPANION_SUFFIX)


def companion_section(results: Path) -> list[str]:
    """Markdown lines listing the companion programs' cells of `results`
    (none: no lines)."""
    results = Path(results)
    if not results.is_file():
        return []
    recs = [json.loads(line) for line in results.read_text().splitlines()
            if line.strip()]
    recs = sorted((r for r in recs if is_companion(r["program_id"])),
                  key=lambda r: (r["program_id"], r["toolchain"],
                                 r["xnack"]))
    if not recs:
        return []
    out = ["## Companion forms (not in the per-atom counts)", "",
           "A companion program is another legal form of an atom's program "
           "(the OpenACC C port's atomic update "
           "x = x + e1 + e2, legal by OpenACC 3.4 §2.12, beside the atom's "
           "program, which writes x += e1 + e2). Its cells are listed here "
           "and go through the confirmer; they are not in the tables above.",
           "", "| program | atom | toolchain | mode | outcome | reason |",
           "|---|---|---|---|---|---|"]
    for r in recs:
        out.append(f"| {r['program_id']} | `{r['primary_atom']}` | "
                   f"{TC_NAME.get(r['toolchain'], r['toolchain'])} | "
                   f"{r['xnack']} | {r['outcome']} | "
                   f"{_md(r.get('reason', '')[:120])} |")
    return out + [""]


def build_table(results: Path, audit: Path | None = AUDIT,
                source_of=generated_source) -> list[Row]:
    """One Row per matrix cell (program, toolchain, HSA_XNACK).

    Raises ValueError on a duplicate cell. ``audit`` is the committed audit
    summary (dispositions per version and atom); ``source_of(program_id,
    atom, version)`` gives a program's source for the diagnosed-line check.
    """
    recs = [json.loads(line) for line in Path(results).read_text().splitlines()
            if line.strip()]
    # One program per atom; the companion forms (the
    # OpenACC C -binop programs) are listed by companion_section
    recs = [r for r in recs if not is_companion(r["program_id"])]
    # GCC: toolchains kept out of the support tables on purpose
    # (REPORT_EXCLUDED); their rows are dropped here, never an error
    recs = [r for r in recs if r["toolchain"] not in REPORT_EXCLUDED]
    present = {r["toolchain"] for r in recs}
    # Rows of a toolchain without a column fail loudly
    # (they were dropped)
    every_twin = [w for t in ALL_TOOLCHAINS for w in _reg().twins_of(t)]
    unknown = sorted(present - set(ALL_TOOLCHAINS) - set(every_twin) -
                     set(NVIDIA_TOOLCHAINS))
    if unknown:
        raise ValueError(f"{results}: rows of toolchains with no support-"
                         f"table column: {unknown} (offload.engine.report."
                         "ALL_TOOLCHAINS)")
    TOOLCHAINS[:] = [t for t in ALL_TOOLCHAINS if t in present
                     or present & set(_reg().twins_of(t))]
    G90[:] = [g90_of(t) for t in ALL_TOOLCHAINS if g90_of(t) in present]
    TWINS[:] = [w for w in every_twin if w in present]
    MI300A[:] = [t for t in ALL_TOOLCHAINS if t in present]
    NV[:] = [t for t in NVIDIA_TOOLCHAINS if t in present]
    seen: set[tuple] = set()
    by_cell: dict[tuple, dict] = {}
    for r in recs:
        key = (r["program_id"], r["toolchain"], r["xnack"], r.get("opt", ""))
        if key in seen:
            raise ValueError(f"duplicate matrix cell {key}")
        seen.add(key)
        by_cell[key] = r
    disp = _audit_map(audit)
    rows = []
    for (pid, tc, x, opt), r in by_cell.items():
        if tc in NVIDIA_TOOLCHAINS:  # Its other mode
            other = next((by_cell[k] for k in ((pid, tc, y, opt)
                                               for y in nv_modes(tc)
                                               if y != x) if k in by_cell),
                         None)
        else:
            other = by_cell.get((pid, tc, 1 - x, opt))
        d = disp.get((r.get("version", 0), r["primary_atom"]), "")
        if tc in NVIDIA_TOOLCHAINS:
            # Dispositions are per toolchain: an NVIDIA cell
            # reads the audit of its own toolchain and mode (none: no
            # disposition, so no failure reads as confirmed)
            d = _nv_audit(r).get((r.get("version", 0), r["primary_atom"]),
                                 "")
        if pid.endswith("-hostdev") or r.get("scope") == "host+device":
            d = ""  # A pattern program is not the atom's oracle
        legal = r.get("legal", True)
        if legal:
            outcome = r["outcome"]
        else:
            outcome = r["outcome"] if r["outcome"] in (
                "rejected", "harness_error") else "not_rejected"
        reason = _root_reason(r)
        label = _label(r, other, d)
        if (x == HEADLINE and legal and other is None
                and r.get("evidence") == "copy_mode_only"
                and r["outcome"] not in _COMPILE_TIME):
            label += f"; {COPY_NOT_RUN}"
        why, excluded = "", False
        if legal and outcome == "rejected":
            atom = r["primary_atom"]
            listed = confound(atom, tc, reason)
            caveat = confound(atom, tc, reason, CAVEATS)
            line, at_directive = ("", False) if listed or caveat else \
                _line_confound(atom, reason,
                               source_of(pid, atom, r.get("version", 0)))
            if listed or at_directive:
                why, excluded = listed or line, True
                label = f"rejected (not counted: {why})"
            elif caveat or line:
                why = caveat or line
                label = "rejected ‡"
        scope = r.get("scope") or ("host+device" if pid.endswith(
            "-hostdev") else "device")
        use = ""
        if scope != "device":
            from offload.engine.offload_scope import scope_of
            src = source_of(pid, r["primary_atom"], r.get("version", 0))
            use = scope_of(src)[1] if src else ""
        basis = ""
        if legal and r.get("evidence") in NO_ORACLE_TEXT:
            from offload.engine.gen import no_oracle_of
            src = source_of(pid, r["primary_atom"], r.get("version", 0))
            noo = no_oracle_of(src) if src else None
            basis = noo[2] if noo else ""
        rows.append(Row(
            atom=r["primary_atom"], toolchain=tc, xnack=x, outcome=outcome,
            flaky=bool(r.get("flaky")), version=r.get("version", 0),
            program_id=pid, legal=legal, violates=r.get("violates"),
            evidence=r.get("evidence", "construct"), audit=d,
            label=label, reason=reason, confound=why, excluded=excluded,
            needs=tuple(r.get("needs", ())), thp=r.get("thp", ""),
            basis=basis, lang=r.get("lang", "f90"), scope=scope, use=use))
    labels = {(r.program_id, r.toolchain, r.xnack): r.label for r in rows}
    cells = {(r.program_id, r.toolchain, r.xnack): r for r in rows}
    rows = [replace(r, presence_x1=(PRESENCE_X1.get(r.program_id) or {})
                    .get(r.toolchain, "")) if r.xnack == HEADLINE and r.legal
            else r for r in rows]
    def three(r):
        """The portable verdict over the three cells."""
        copy = cells.get((r.program_id, r.toolchain, COPY))
        if _mode_class(r, copy) == "requirement_refused":
            return "requirement_refused"
        v2 = _portable(r, copy)
        if not G90:  # no gfx90a run in this matrix: the two-mode verdict
            return v2
        g = cells.get((r.program_id, g90_of(r.toolchain), COPY))
        return portable3(v2, g.label if g else None)
    rows = [replace(r, copy_label=labels.get(
        (r.program_id, r.toolchain, COPY), NOT_RUN),
        portable=three(r),
        mode_class=_mode_class(r, cells.get((r.program_id, r.toolchain,
                                             COPY))),
        arch_class=_arch_class(r, cells.get((r.program_id, r.toolchain,
                                             COPY)),
                               cells.get((r.program_id, g90_of(r.toolchain),
                                          COPY))))
        if r.xnack == HEADLINE and r.toolchain in TOOLCHAINS else r
        for r in rows]
    rows = [_nv_headline(r, cells) if r.toolchain in NV else r
            for r in rows]
    # A managed cell relabelled by its headline row's class
    rows = [cells[(r.program_id, r.toolchain, r.xnack)]
            if r.toolchain in NV and r.xnack != nv_modes(r.toolchain)[0]
            else r for r in rows]
    order = {t: i for i, (t, _) in enumerate(columns())}

    def mode_rank(r):
        if r.toolchain in NV:
            return nv_modes(r.toolchain).index(r.xnack)
        return -r.xnack
    rows.sort(key=lambda r: (r.version, not r.legal, r.atom, r.program_id,
                             order.get(r.toolchain, 99), mode_rank(r)))
    return annotate_gate(rows)


def _nv_headline(r: "Row", cells: dict) -> "Row":
    """An NVIDIA headline row (the machine's headline mode,
    separate memory) with its other mode's label (managed), its portable
    verdict over both modes and the class of a difference between them;
    other rows unchanged."""
    modes = nv_modes(r.toolchain)
    if r.xnack != modes[0]:
        return r
    other = cells.get((r.program_id, r.toolchain, modes[1])) \
        if len(modes) > 1 else None
    cls = _nv_mode_class(r, other)
    if cls == "managed_shares_storage" and other is not None:
        other = replace(other, label=NV_SHARED_TEXT)
        cells[(other.program_id, other.toolchain, other.xnack)] = other
    port = _nv_portable(r, other) if len(modes) > 1 else _one_mode(r)
    if cls == "managed_shares_storage" and _ok(r.label):
        port = "managed_unverified"
    return replace(r, copy_label=other.label if other else NOT_RUN,
                   portable=port, mode_class=cls)


# The portable verdict of an NVIDIA toolchain: correct in both of
# its machine's modes (separate and managed memory on wingtip). The keys
# are PORTABLE's, the copy-mode role taken by separate memory (x0) and the
# shared one by managed memory (x1).
NV_PORTABLE = {
    "portable": "correct in separate and in managed memory",
    "x1_only": "correct in managed memory only",
    "x0_only": "correct in separate memory only",
    "neither": "an observed failure in both modes",
    "x0_fail_x1_unverified": "failed in separate memory; managed not "
                             "verifiable",
    "x1_fail_x0_unverified": "failed in managed memory; separate not "
                             "verifiable",
    "not_verifiable": "neither mode gives an observable verdict",
    "needs_zero_copy": "the program needs zero-copy memory (unified "
                       "memory, which wingtip does not have) by design",
    "managed_unverified": "correct in separate memory; the managed-memory "
                          "cell is not verifiable (managed_shares_storage)",
    "managed_not_run": "no managed-memory run",
    # a toolchain that runs one memory mode only (GCC: separate memory)
    "one_mode_correct": "correct in the one memory mode the toolchain runs",
    "one_mode_failure": "an observed failure in the one memory mode the toolchain runs",
}


def _one_mode(r: "Row") -> str:
    """The verdict of a toolchain that runs one memory mode only."""
    if not r.legal:
        return ""
    if "zero_copy" in r.needs and not _ok(r.label):
        return "needs_zero_copy"
    return "one_mode_correct" if _ok(r.label) else \
        "one_mode_failure" if _failure(r.label) else "not_verifiable"


def _nv_portable(r: "Row", man: "Row | None") -> str:
    if not r.legal:
        return ""
    if "zero_copy" in r.needs and not _ok(r.label):
        return "needs_zero_copy"
    if man is None:
        return "managed_not_run"
    return portable_of(man.label, r.label, False,
                       r.evidence == "copy_mode_only")


# Classes of a difference between an NVIDIA toolchain's separate
# and managed memory cells (catalog/mode_differences.yaml nvhpc_entries)
NV_MODE_CLASSES = {
    "separate_failure": "correct in managed memory, wrong in separate "
                        "memory, the program's mapping conforming: a "
                        "compiler failure with separate host and device "
                        "memory (the copy-mode failure), with a finding",
    "managed_failure": "correct in separate memory, wrong in managed "
                       "memory: a failure specific to managed memory, with a "
                       "finding",
    "both_wrong": "wrong in both modes, in different ways: not a "
                  "portability result",
    "needs_unified_memory": "the program requires unified memory by design "
                            "(requires unified_shared_memory, self_maps): "
                            "failing without it is not a portability result",
    "requirement_refused": "the runtime or compiler refuses a requires "
                           "directive in one mode (supporting a requirement "
                           "is implementation defined): conforming",
    "intermittent": "a failure that shows in one mode by chance (a race "
                    "or a flaky run), not the mode",
    "not_verifiable": "neither cell gives a verdict the other contradicts "
                      "(unobservable, ignored or a harness error on one "
                      "side): not a portability result",
    "managed_shares_storage": "a copy_mode_only program whose shared-memory "
                              "probe is local data (separate in managed "
                              "memory) while its checked arrays are "
                              "allocatable (managed memory: the device "
                              "shares their storage, which the spec allows): "
                              "the copy-semantics check says nothing in "
                              "managed memory; rerun with the probe on the "
                              "heap it passes (tools/campaigns/nvhpc_managed_probe.py)",
}
# the managed-memory cell of a managed_shares_storage difference
NV_SHARED_TEXT = ("not verifiable in managed memory (the copy-mode check "
                  "reads storage managed memory shares)")


def nv_mode_entry(program_id: str, toolchain: str) -> dict | None:
    """The catalog/mode_differences.yaml nvhpc_entries entry of a
    (program, NVIDIA toolchain)."""
    from fnmatch import fnmatchcase
    for e in MODE_DIFFERENCES.get("nvhpc_entries") or []:
        if any(fnmatchcase(program_id, p) for p in e["programs"]) and any(
                fnmatchcase(toolchain, t) for t in e["toolchains"]):
            return e
    return None


def _nv_mode_class(r: "Row", other: "Row | None") -> str:
    if not r.legal or other is None or _mode_key(r) == _mode_key(other):
        return ""
    e = nv_mode_entry(r.program_id, r.toolchain)
    return e["class"] if e else "unclassified"


def nv_mode_class_problem(cls: str, sep_label: str, man_label: str
                          ) -> str | None:
    """Why an NVIDIA mode class does not fit the separate and managed
    labels of its cell (None when it fits)."""
    fs, fm = _failure(sep_label), _failure(man_label)
    need = {"separate_failure": (True, False),
            "managed_failure": (False, True),
            "both_wrong": (True, True)}.get(cls)
    if need is not None and (fs, fm) != need:
        return (f"class {cls} needs separate "
                f"{'failing' if need[0] else 'not failing'} and managed "
                f"{'failing' if need[1] else 'not failing'}; the cells are "
                f"{sep_label!r} / {man_label!r}")
    if cls in ("needs_unified_memory", "requirement_refused") and not (
            fs or fm):
        return f"class {cls} needs a failing cell"
    return None


# The verdict a user can rely on for portable code is "correct in
# both memory modes" (HSA_XNACK=0: separate host and device memory, as on a
# discrete GPU; HSA_XNACK=1: unified memory, where a missing or wrong map
# often still gives the right answer). Values of Row.portable (headline
# legal rows; "" elsewhere):
PORTABLE = {
    "portable": "correct at HSA_XNACK=0 and at HSA_XNACK=1",
    "x1_only": "correct at HSA_XNACK=1 only (unified memory)",
    "x0_only": "correct at HSA_XNACK=0 only (copy mode)",
    "neither": "an observed failure in both modes (rejected, wrong "
               "answer, crash, host fallback, a probe that did not "
               "terminate, or a presence check failing at HSA_XNACK=1)",
    "x0_fail_x1_unverified": "failed at HSA_XNACK=0; HSA_XNACK=1 not "
                             "verifiable (nothing observable there, or a "
                             "copy_mode_only program whose HSA_XNACK=1 "
                             "check skips what the copy mode tests)",
    "x1_fail_x0_unverified": "failed at HSA_XNACK=1; HSA_XNACK=0 not "
                             "verifiable",
    "requirement_refused": "the runtime refuses a requires directive in one "
                           "mode (supporting a requirement is "
                           "implementation defined, 5.2 §8.2): a conforming "
                           "refusal, not a failure",
    "not_verifiable": "neither mode gives an observable verdict "
                      "(unobservable, accepted and ignored, no oracle, "
                      "unverified, harness error, a rejection not counted)",
    "needs_zero_copy": "the program needs zero-copy memory (HSA_XNACK=1) "
                       "by design; not a portability result",
    "x0_not_run": "no HSA_XNACK=0 run",
    # The third cell, gfx90a (Tioga MI250X, a discrete GPU, at
    # HSA_XNACK=0): "portable" needs it correct too
    "gfx942_only": "correct in both MI300A modes, an observed failure on "
                   "the discrete gfx90a (MI250X)",
    "gfx90a_unverified": "correct in both MI300A modes; the gfx90a cell "
                         "gives no verdict (unobservable, ignored, harness "
                         "error, ...)",
    "gfx90a_not_run": "correct in both MI300A modes; no gfx90a run",
}


def portable3(v2: str, g90_label: str | None) -> str:
    """The portable verdict over the three cells of a compiler:
    `v2`, the two-mode MI300A verdict (portable_of), and the gfx90a cell's
    label (None: no gfx90a row). Only a cell correct in both MI300A modes
    can be portable; it stays so when the gfx90a cell is correct too, else
    it is gfx942_only (an observed failure on gfx90a), gfx90a_unverified or
    gfx90a_not_run. Every other two-mode verdict already says the cell is
    not portable and stands; the gfx90a column and the arch-difference
    class (ARCH_CLASSES) say what gfx90a adds."""
    if v2 != "portable":
        return v2
    if g90_label is None:
        return "gfx90a_not_run"
    if _failure(g90_label):
        return "gfx942_only"
    return "portable" if _ok(g90_label) else "gfx90a_unverified"


MODE_DIFF_FILE = Path(__file__).resolve().parent.parent.parent / "catalog" / \
    "mode_differences.yaml"
# Classes of a difference between the memory modes
MODE_CLASSES = {
    "copy_mode_failure": "correct at HSA_XNACK=1, wrong at 0, and the "
                         "program's mapping is conforming (it would be "
                         "correct with separate host and device memory): a "
                         "compiler copy-mode failure, with a finding",
    "unified_memory_failure": "correct at HSA_XNACK=0, wrong at 1: a "
                              "failure specific to unified memory",
    "needs_unified_memory": "the program requires unified memory by design "
                            "(requires unified_shared_memory or self_maps, "
                            "the self map-type modifier): failing or "
                            "refusing to run at HSA_XNACK=0 is not a "
                            "portability result",
    "requirement_refused": "the runtime refuses a requires directive at "
                           "HSA_XNACK=0 and terminates before the region "
                           "(supporting a requirement is implementation "
                           "defined, 5.2 §8.2): conforming, not a wrong "
                           "answer",
    "both_wrong": "wrong in both modes, in different ways: not a "
                  "portability result",
    "no_finding_yet": "a difference between the modes that no finding explains yet: shown "
                      "in the table and not counted as a compiler failure",
    "x1_oracle_blind": "the program's check runs only in copy mode (its "
                       "HSA_XNACK=1 cell reads correct with copy-mode "
                       "evidence, which checks nothing the mode hides) and "
                       "a copy-independent check (tools/campaigns/presence_x1.py, the "
                       "reproducer) shows the compiler wrong at "
                       "HSA_XNACK=1 too: a failure in both modes, not a "
                       "copy-mode failure",
}


# Classes of a difference between a compiler's MI300A copy-mode
# cell (gfx942, HSA_XNACK=0) and its gfx90a cell (MI250X, HSA_XNACK=0):
# both have separate host and device memory, so a difference is the GPU,
# its runtime path or what the APU's copy mode does not emulate
ARCH_CLASSES = {
    "gfx90a_failure": "correct on MI300A, wrong on gfx90a, the program's "
                      "mapping is conforming: a compiler or runtime failure "
                      "specific to gfx90a (or to the discrete GPU), with a "
                      "finding",
    "x0_emulation_gap": "correct at HSA_XNACK=0 on MI300A, wrong on the "
                        "discrete gfx90a because something reaches device "
                        "code without a map that the APU's copy mode still "
                        "makes accessible: the compiler fails to map it "
                        "(a mapping failure HSA_XNACK=0 on MI300A hides), "
                        "with a finding",
    "gfx942_failure": "wrong at HSA_XNACK=0 on MI300A, correct on gfx90a: "
                      "a failure specific to the MI300A (APU) copy mode, "
                      "with a finding",
    "both_wrong": "wrong on both GPUs, in different ways: not a "
                  "portability result",
    "needs_unified_memory": "the program requires unified memory by "
                            "design; failing or refusing without it is not "
                            "a portability result",
    "requirement_refused": "the runtime refuses a requires directive on "
                           "one GPU (supporting a requirement is "
                           "implementation defined, 5.2 §8.2): conforming",
    "no_finding_yet": "a difference between the GPUs that no finding explains yet: shown "
                      "in the table and not counted as a compiler failure",
    "intermittent": "a failure the finding shows to be intermittent (a "
                    "race): it showed in one cell and not in the other by "
                    "chance; the same program fails on both GPUs in other "
                    "runs",
    "not_verifiable": "neither cell gives a verdict the other contradicts "
                      "(e.g. unobservable on one GPU, ignored or a harness "
                      "error on the other): not a portability result",
}


def load_mode_differences(path: Path = MODE_DIFF_FILE) -> dict:
    """catalog/mode_differences.yaml (arch_entries),
    checked."""
    import yaml
    doc = yaml.safe_load(Path(path).read_text()) or {}
    for e in doc.get("entries") or []:
        if e.get("class") not in MODE_CLASSES:
            raise ValueError(f"{path}: unknown class in {e}")
    for e in doc.get("arch_entries") or []:
        if e.get("class") not in ARCH_CLASSES:
            raise ValueError(f"{path}: unknown arch class in {e}")
    for e in doc.get("nvhpc_entries") or []:  
        if e.get("class") not in NV_MODE_CLASSES:
            raise ValueError(f"{path}: unknown nvhpc class in {e}")
    return doc


MODE_DIFFERENCES = load_mode_differences() if MODE_DIFF_FILE.is_file() \
    else {"entries": []}


def mode_entry(program_id: str, toolchain: str) -> dict | None:
    """The catalog/mode_differences.yaml entry of a (program, toolchain)."""
    from fnmatch import fnmatchcase
    for e in MODE_DIFFERENCES.get("entries") or []:
        if any(fnmatchcase(program_id, p) for p in e["programs"]) and any(
                fnmatchcase(toolchain, t) for t in e["toolchains"]):
            return e
    return None


def arch_entry(program_id: str, toolchain: str) -> dict | None:
    """The catalog/mode_differences.yaml arch_entries entry of a (program,
    gfx942 toolchain)."""
    from fnmatch import fnmatchcase
    for e in MODE_DIFFERENCES.get("arch_entries") or []:
        if any(fnmatchcase(program_id, p) for p in e["programs"]) and any(
                fnmatchcase(base_name(toolchain), t)
                for t in e["toolchains"]):
            return e
    return None


def _arch_class(r: "Row", copy: "Row | None", g90: "Row | None") -> str:
    """The class of a difference between the MI300A copy-mode
    cell and the gfx90a cell of a legal headline row ("" when they agree
    or one is missing)."""
    if r.xnack != HEADLINE or not r.legal or copy is None or g90 is None \
            or _mode_key(copy) == _mode_key(g90):
        return ""
    e = arch_entry(r.program_id, r.toolchain)
    return e["class"] if e else "unclassified"


def _mode_class(r: "Row", copy: "Row | None") -> str:
    if r.xnack != HEADLINE or not r.legal or copy is None or \
            _mode_key(r) == _mode_key(copy):
        return ""
    e = mode_entry(r.program_id, r.toolchain)
    return e["class"] if e else "unclassified"


PRESENCE_X1_FILE = Path(__file__).resolve().parent.parent.parent / "tests" / \
    "data" / "presence_x1_summary.json"
# {program id: {toolchain: outcome}}: the copy-mode programs' presence
# checks run at HSA_XNACK=1 (tools/campaigns/presence_x1.py)
PRESENCE_X1 = (json.loads(PRESENCE_X1_FILE.read_text())["programs"]
               if PRESENCE_X1_FILE.is_file() else {})


def _ok(label: str) -> bool:
    """A cell the dashboard counts as correct (status ok); a
    compile-time probe that terminated as required is a pass too."""
    return label.startswith(("correct on device", "error termination",
                             "compile-time error termination as required"))


COPY_EVIDENCE_X1 = "correct on device (copy-mode evidence"
FAILURE_PREFIXES = ("rejected", "wrong answer", "crash", "fell back",
                    "no error termination", "compile-time probe failed",
                    "fails in copy mode")


def _failure(label: str) -> bool:
    """An observed failure (a counted rejection, a wrong answer, a crash,
    a host fallback, a probe that did not terminate)."""
    return label.startswith(FAILURE_PREFIXES) and \
        not label.startswith("rejected (not counted")


def mode_class_problem(cls: str, x1_label: str, x0_label: str
                       ) -> str | None:
    """Why a memory-mode class does not fit the
    headline (HSA_XNACK=1) and copy-mode labels of its cell (None when it
    fits): the class says which modes fail."""
    f1, f0 = _failure(x1_label), _failure(x0_label)
    need = {"copy_mode_failure": (False, True),
            "x1_oracle_blind": (False, True),
            "unified_memory_failure": (True, False),
            "both_wrong": (True, True)}.get(cls)
    if need is not None and (f1, f0) != need:
        return (f"class {cls} needs HSA_XNACK=1 "
                f"{'failing' if need[0] else 'not failing'} and HSA_XNACK=0 "
                f"{'failing' if need[1] else 'not failing'}; the cells are "
                f"{x1_label!r} / {x0_label!r}")
    if cls in ("needs_unified_memory", "requirement_refused") and not f0:
        return (f"class {cls} needs a failing HSA_XNACK=0 cell; it is "
                f"{x0_label!r}")
    return None


def portable_of(x1_label: str, x0_label: str,
                x1_hidden_failure: bool = False,
                x1_copy_only: bool | None = None) -> str:
    """The portable verdict of a headline label and its copy-mode label.
    A copy_mode_only cell's HSA_XNACK=1 check is skipped under unified
    memory: it counts as correct only next to a correct copy-mode cell,
    never as evidence on its own (`x1_copy_only` comes from
    the program's evidence, not from the label, which an unaudited oracle
    changes; without it the label decides). `x1_hidden_failure`: the
    program's presence checks fail when run at HSA_XNACK=1."""
    if x1_copy_only is None:
        x1_copy_only = x1_label.startswith(COPY_EVIDENCE_X1)

    def state(label, other_ok, copy_only, hidden):
        if hidden or _failure(label):
            return "fail"
        if _ok(label) and (other_ok or not copy_only):
            return "ok"
        return "unv"
    b = state(x0_label, True, False, False)
    a = state(x1_label, b == "ok", x1_copy_only, x1_hidden_failure)
    return {("ok", "ok"): "portable", ("ok", "fail"): "x1_only",
            ("ok", "unv"): "x1_only", ("fail", "ok"): "x0_only",
            ("unv", "ok"): "x0_only", ("fail", "fail"): "neither",
            ("unv", "fail"): "x0_fail_x1_unverified",
            ("fail", "unv"): "x1_fail_x0_unverified"}.get(
                (a, b), "not_verifiable")


def _portable(r: "Row", copy: "Row | None") -> str:
    if r.xnack != HEADLINE or not r.legal:
        return ""
    if copy is None:
        return "x0_not_run"
    if "zero_copy" in r.needs and not _ok(copy.label):
        return "needs_zero_copy"
    hidden = r.presence_x1 == "wrong_answer"
    return portable_of(r.label, copy.label, hidden,
                       r.evidence == "copy_mode_only")


NV_COPY_EVIDENCE_FAMILY = ("correct on device (copy-mode evidence; not "
                           "separable in managed memory)")


def family(label: str) -> str:
    """Coarse category of a cell label, for the summary counts."""
    for prefix, fam in (
            ("correct on device (oracle unaudited)",
             "correct on device (oracle unaudited)"),
            # An NVIDIA managed-memory cell
            # is no HSA_XNACK=1 cell
            ("correct on device (copy-mode evidence; not separable in ",
             NV_COPY_EVIDENCE_FAMILY),
            ("correct on device (copy-mode", "correct on device (copy-mode evidence, HSA_XNACK=1)"),
            ("correct on device", "correct on device"),
            (NO_ORACLE_TEXT["hint_only"],
             "accepted; conforms vacuously (no oracle)"),
            (NO_ORACLE_TEXT["implementation_defined"],
             "implementation-defined (no oracle)"),
            (NO_ORACLE_TEXT["equivalent_default"],
             "equivalent to the default (no oracle)"),
            (LEGALITY_TEXT, "accepted; oracle is the illegal variant"),
            (UNVERIFIED_TEXT, "accepted; unverified"),
            ("compiled and ran", "unobservable"),
            ("rejected (not counted",
             "rejected, not counted (another feature)"),
            ("rejected", "rejected"),
            ("accepted, ignored", "accepted, ignored"),
            ("fell back", "fell back to host"),
            ("wrong answer (confirmed)", "wrong answer (confirmed)"),
            ("wrong answer (oracle unaudited)", "wrong answer (oracle unaudited)"),
            ("wrong answer", "wrong answer (other)"),
            ("crash", "crash"),
            ("fails in copy mode", "needs zero-copy; failed in copy mode"),
            ("harness error", "harness error"),
            (NV_SHARED_TEXT, "not verifiable (managed memory shares the "
             "checked storage)"),
            ("not rejected", "not rejected")):
        if label.startswith(prefix):
            return fam
    return label


# --- claims --------------------------------------------------------------------------

@dataclass(frozen=True)
class Claim:
    source: str
    url: str
    toolchain: str
    claim: str
    version_note: str
    quote: str = ""
    atoms: tuple = ()
    pattern: str | None = None
    form: str | None = None      # compile_error | accepted | None
    general: bool = False        # release-level statement: specific claims win
    versions: tuple | None = None
    status: str = "provisional"
    language: str = "Fortran"
    note: str = ""
    # None for the old per-model claim files (a Fortran row is
    # compared with a claim of any language); a generic claim covers the
    # languages it names unless its document is cross-language
    cross_language: bool | None = None
    spec_version: str = ""
    page: str = ""


@dataclass(frozen=True)
class Mismatch:
    atom: str
    toolchain: str
    claimed: str
    measured: str
    version: int = 0
    xnack: tuple = ()
    source: str = ""
    url: str = ""
    quote: str = ""
    oracle_unaudited: bool = False
    general: bool = False
    reason: str = ""      # harness reason of the first contradicting cell
    confound: str = ""    # listed caveat of a contradicting cell
    language: str = ""    # language the vendor's statement is about
    # The contradicting cells (program_id, toolchain, xnack,
    # outcome), every memory mode and GPU, and the rows' language
    cells: tuple = ()
    lang: str = "f90"
    spec_version: str = ""
    page: str = ""


def _from_generic(d: dict) -> Claim:
    """A report Claim of one generic record (offload.engine.confirm.claims)."""
    atom = d["atom"]
    pat = any(ch in atom for ch in "*?[")
    page = d.get("page", "")
    m = re.search(r"\[([^\]]*)\]\s*$", page)
    return Claim(source=d["source"], url=d["url"], toolchain=d["toolchain"],
                 claim=d["claim"], version_note=m.group(1) if m else page,
                 quote=d["quote"], atoms=() if pat else (atom,),
                 pattern=atom if pat else None, form=d.get("form") or None,
                 general=bool(d.get("general")),
                 versions=tuple(int(v) for v in str(d.get("versions") or "")
                                .split(",") if v) or None,
                 language=d["language"], note=d.get("note", ""),
                 cross_language=bool(d.get("cross_language")),
                 spec_version=str(d.get("spec_version") or ""), page=page)


def load_claims(path: Path) -> list[Claim]:
    """The claims of a file, parsed once per version of it."""
    return list(_claims(str(path), Path(path).stat().st_mtime))


@lru_cache(maxsize=None)
def _claims(path: str, mtime: float) -> tuple:
    return tuple(_parse_claims(Path(path)))


def _parse_claims(path: Path) -> list[Claim]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    entries = data.get("claims") or []
    if entries and "vendor" in entries[0]:
        return [_from_generic(e) for e in entries]
    out = []
    for i, e in enumerate(entries):
        atoms = list(e.get("atoms") or [])
        if e.get("atom"):
            atoms.append(e["atom"])
        c = Claim(source=e["source"], url=e["url"], toolchain=e["toolchain"],
                  claim=e["claim"], version_note=e.get("version_note", ""),
                  quote=e.get("quote", ""), atoms=tuple(atoms),
                  pattern=e.get("pattern"), form=e.get("form"),
                  general=bool(e.get("general", False)),
                  versions=tuple(e["versions"]) if e.get("versions") else None,
                  status=e.get("status", "provisional"),
                  language=e.get("language", "Fortran"),
                  note=e.get("note", ""))
        if c.claim not in CLAIM_VALUES:
            raise ValueError(f"claim {i}: claim must be one of {CLAIM_VALUES}")
        if c.form not in CLAIM_FORMS:
            raise ValueError(f"claim {i}: form must be one of {CLAIM_FORMS}")
        if not (c.atoms or c.pattern):
            raise ValueError(f"claim {i}: needs atom, atoms or pattern")
        out.append(c)
    return out


def _matches(c: Claim, row: Row) -> bool:
    # A claim about a compiler covers its gfx90a twin too
    if c.toolchain != base_name(row.toolchain):
        return False
    if c.versions is not None and row.version not in c.versions:
        return False
    if c.versions is None and row.version >= 60 and c.spec_version and \
            c.spec_version != "6.0":
        return False   # A 5.x feature claim, not the 6.0 form
    if row.lang != "c" and c.cross_language is False and \
            "Fortran" not in c.language:
        return False
    atom = row.atom
    if row.lang == "c":
        # A C row is compared with the claims about C (the
        # language field names C), under its Fortran atom name where the
        # claim lists the do spelling (parallel_for -> parallel_do)
        if "C" not in c.language.replace("C/C++", "C").split() and \
                "C/C++" not in c.language:
            return False
        from offload.engine.c_gen import fortran_atom
        if atom not in c.atoms and not (c.pattern and fnmatchcase(
                atom, c.pattern)):
            atom = fortran_atom(atom)
    return atom in c.atoms or (
        c.pattern is not None and fnmatchcase(atom, c.pattern))


def _state(row: Row) -> str | None:
    """What a legal cell says about support, for claim comparison."""
    if not row.legal or row.outcome == "harness_error":
        return None
    if row.label.startswith("fails in copy mode"):
        return None  # expected for zero-copy programs; not a feature result
    if row.label == NV_SHARED_TEXT:
        return None  # Managed memory shares the checked storage
    if row.excluded:
        return None  # the compiler rejected another feature
    return {"rejected": "rejected", "accepted_ignored": "ignored",
            "fell_back_to_host": "fail", "wrong_answer": "fail",
            "unobservable": "accepted",
            "correct_on_device": "accepted" if row.evidence in UNCREDITED
            else "pass"}.get(row.outcome)


def _disagrees(c: Claim, row: Row) -> bool:
    s = _state(row)
    if s is None:
        return False
    if c.claim == "supported":
        # A failing cell contradicts a support claim only when
        # it counts as a compiler failure (a confirmed gate verdict)
        # (an ungated row keeps its outcome until the gate has seen it,
        # The rule: claims about rows recorded before the gate)
        if _failure(row.label) and not (confirmed_failure(row) or
                                        row.gate == "ungated"):
            return False
        return s in ("rejected", "ignored", "fail")
    if c.claim == "unsupported":
        return s != "rejected" if c.form == "compile_error" else s == "pass"
    return c.form == "accepted" and s == "rejected"   # partial


def claim_groups(table: list[Row], claims: Path | list[Claim]
                 ) -> dict[tuple, list[Row]]:
    """(claim index, atom, version, toolchain) -> the legal rows it covers.

    A general (release-level) claim applies to an atom only when no specific
    claim for the same toolchain covers that atom.
    """
    cl = load_claims(claims) if isinstance(claims, (str, Path)) else claims
    groups: dict[tuple, list[Row]] = defaultdict(list)
    by_tc: dict[str, list[tuple[int, Claim]]] = defaultdict(list)     # a claim covers one toolchain (and its twin)
    for i, c in enumerate(cl):
        by_tc[c.toolchain].append((i, c))
    table_only = _reg().table_only()
    for row in table:
        if not row.legal or row.scope != "device":
            continue  # Host+device patterns are not headline
        if row.toolchain in table_only:
            continue  # a support-table cell only (MI300X, MI350X): no evidence about a claim
        base = base_name(row.toolchain)
        mine = [(i, c) for i, c in by_tc.get(base, ()) if _matches(c, row)]
        hits = [i for i, c in mine if not c.general] or [i for i, c in mine if c.general]
        for i in hits:
            groups[(i, row.atom, row.version, base)].append(row)
    return groups


def _measured(bad: list[Row], rows: list[Row]) -> str:
    twins = [r for r in bad if r.toolchain != base_name(r.toolchain)]
    if twins:   # Name the GPU of a twin's cell
        main = [r for r in bad if r not in twins]
        mrows = [r for r in rows if r.toolchain == base_name(r.toolchain)]
        parts = [_measured(main, mrows)] if main else []
        parts += [f"{_reg().twin_tag(r.toolchain)}: {r.label}" for r in twins]
        return "; ".join(parts)
    labels = {r.label for r in bad}
    if len(labels) == 1 and (len(bad) == len(rows)
                             or "HSA_XNACK=" in bad[0].label):
        return bad[0].label
    return "; ".join(r.label if "HSA_XNACK=" in r.label
                     else f"{_mode_word(r.toolchain, r.xnack)}: {r.label}"
                     for r in sorted(bad, key=lambda r: -r.xnack))


def _oracle_dependent(row: Row) -> bool:
    """A run-time outcome of an atom whose oracle is unaudited. Compile-time
    results (rejected, ignored with a warning) do not depend on the oracle."""
    return (row.audit.startswith("unaudited")
            and row.outcome not in ("rejected", "accepted_ignored"))


def compare_claims(table: list[Row], claims: Path | list[Claim]
                   ) -> list[Mismatch]:
    """Claims the measurements contradict, one Mismatch per claim, atom,
    version and toolchain (both memory modes folded into ``measured``)."""
    cl = load_claims(claims) if isinstance(claims, (str, Path)) else claims
    out = []
    for (i, atom, version, tc), rows in claim_groups(table, cl).items():
        c = cl[i]
        bad = [r for r in rows if _disagrees(c, r)]
        if not bad:
            continue
        claimed = c.claim + (f" ({c.form.replace('_', ' ')})" if c.form
                             else "")
        out.append(Mismatch(
            atom=atom, toolchain=tc, claimed=f"{claimed} [{c.source}]",
            measured=_measured(bad, rows), version=version,
            xnack=tuple(sorted({r.xnack for r in bad}, reverse=True)),
            source=c.source, url=c.url, quote=c.quote,
            oracle_unaudited=any(_oracle_dependent(r) for r in bad),
            general=c.general, reason=bad[0].reason, language=c.language,
            confound=next((r.confound for r in bad if r.confound), ""),
            cells=tuple((r.program_id, r.toolchain, r.xnack, r.outcome)
                        for r in bad),
            lang=bad[0].lang, spec_version=c.spec_version, page=c.page))
    out.sort(key=lambda m: (m.toolchain, m.oracle_unaudited, m.source,
                            m.atom, m.version))
    return out


# --- citations -----------------------------------------------------------------------

@lru_cache(maxsize=None)
def _yaml(path: Path):
    return yaml.safe_load(Path(path).read_text())


def _vstr(version: int) -> str:
    return f"{version // 10}.{version % 10}"


def _spec(version: int) -> str:
    """'OpenMP 5.2' / 'OpenACC 3.4'."""
    from offload.engine.catalog import spec_name
    return spec_name(version)


@lru_cache(maxsize=None)
def _acc_section(number: str) -> str | None:
    """'OpenACC 3.4 §<number>, p.<first page>'."""
    try:
        from offload.engine import spec_text
        secs = spec_text.sections("acc3.4")
    except Exception:
        return None
    for sec in secs.values():
        if sec.number == number:
            return f"OpenACC 3.4 §{number}, p.{sec.first_page}"
    return None


@lru_cache(maxsize=None)
def _spec_section(version: int, name: str) -> str | None:
    """'OpenMP 5.2 §13.8, p.284' for a construct/directive name, or None."""
    try:
        from offload.engine import spec_text
        secs = spec_text.sections(_vstr(version))
    except Exception:  # spec PDF or pdftotext missing: fall back to catalog
        return None
    forms = dict.fromkeys([name, name.replace(" ", "_")])
    for f in forms:
        for suffix in ("", " Construct", " Directive", " Clause"):
            s = secs.get(f + suffix)
            if s is not None:
                return f"OpenMP {_vstr(version)} §{s.number}, p.{s.first_page}"
    return None


_COMPOUND = {50: "Combined Constructs",
             52: "Combined and Composite Directive Names",
             60: "Compound Directive Names"}


# 5.0 clauses without a section of their own, by the construct
# section whose syntax lists them (the 5.0 section titles)
_HOME_50 = {
    "aligned": "simd", "safelen": "simd", "simdlen": "simd",
    "nontemporal": "simd", "collapse": "Worksharing-Loop",
    "schedule": "Worksharing-Loop", "ordered": "Worksharing-Loop",
    "num_threads": "parallel", "num_teams": "teams",
    "thread_limit": "teams", "dist_schedule": "distribute", "bind": "loop",
    "nowait": "target", "device": "target", "is_device_ptr": "target",
    "uses_allocators": "target", "device_type": "declare target",
    "link": "declare target", "use_device_ptr": "target data",
    "use_device_addr": "target data", "unified_address": "requires",
    "unified_shared_memory": "requires", "reverse_offload": "requires",
    "dynamic_allocators": "requires",
}


def atom_citation(atom: str, version: int) -> tuple[str, str]:
    """(citation text, link) for a legal program's primary atom."""
    parts = atom.split(".")
    clauses_path, _, _, LINK = _paths(model_of_atom(atom))
    from offload.engine.catalog import semantic_atoms
    sem = semantic_atoms().get(atom)
    if sem is not None:  # The spec text that defines the behaviour
        cites = sem.citations
        best = [v for v in sorted(cites) if v <= version] or sorted(cites)[:1]
        return cites[best[-1]], LINK["semantic"]
    if parts[0] == "acc" and len(parts) >= 3 and parts[1] == "directive":
        cite = _acc_section(ACC_DIRECTIVE_SECTION.get(parts[2], ""))
        return cite or "TableGen skeleton entry", LINK["skeleton"]
    if len(parts) >= 3 and parts[1] == "clause":
        e = (_yaml(clauses_path).get("clauses") or {}).get(parts[2])
        if e:
            forms = sorted(e["forms"], key=lambda f: f["since"])
            best = [f for f in forms if f["since"] <= version]
            if not best and parts[0] == "omp":
                # A 5.0 clause whose syntax is the 5.2 one has no
                # 5.0 form: cite its 5.0 section, or the section of the
                # construct whose syntax lists it
                own = _spec_section(version, parts[2]) or (
                    _spec_section(version, _HOME_50[parts[2]])
                    if version == 50 and parts[2] in _HOME_50 else None)
                if own:
                    return own, LINK["clauses"]
            best = best or forms[:1]
            return best[-1]["citation"], LINK["clauses"]
        return "catalog clause entry", LINK["clauses"]
    if len(parts) >= 3 and parts[1] == "directive":
        name = parts[2].replace("_", " ")
        cite = _spec_section(version, name)
        if cite is None:
            leaves = [c for w in name.split()
                      if (c := _spec_section(version, w))]
            comp = _spec_section(version, _COMPOUND.get(version, ""))
            if comp and leaves:
                cite = f"{comp} (compound); leaves " + "; ".join(
                    x.split(" ", 2)[2] for x in leaves)
        return cite or "TableGen skeleton entry", LINK["skeleton"]
    return "catalog entry", LINK["skeleton"]


def rule_citation(rule_id: str | None) -> tuple[str, str]:
    """(citation text, link) for an illegal variant's rule (OMP52-...)."""
    if not rule_id:
        return "no rule", LINK["rules"]
    ver, _, rid = rule_id.partition("-")
    model = "acc" if ver.startswith("ACC") else "omp"
    _, rules_path, _, LINK = _paths(model)
    try:
        version = int(ver.removeprefix("OMP").removeprefix("ACC"))
    except ValueError:
        return rule_id, LINK["rules"]
    for r in _yaml(rules_path).get("rules", []):
        if r["id"] == rid:
            spec = r.get("spec", {}).get(version) or {}
            return spec.get("citation", rid), LINK["rules"]
    return rule_id, LINK["rules"]


# --- rendering -----------------------------------------------------------------------

def _md(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _clip(text: str, n: int = 170) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"


# --- The reproduction gate's status of a failing cell ---------------------

GATE_STATES = ("confirmed", "decided", "unchecked", "nondeterministic",
               "decided_not_counted", "ours", "environment", "not_reproduced",
               "illegal", "not_a_failure", "ungated")
GATE_TEXT = {
    "confirmed": "confirmed (own, or inherited from a compile-time "
                 "signature): counted",
    "decided": "decided, counts (a decision with counts_as: "
               "failure): counted",
    "unchecked": "unchecked (not rerun): not counted here",
    "nondeterministic": "nondeterministic: not counted",
    "decided_not_counted": "decided, does not count (a decision)",
    "ours": "ours (a recorded ruling: our build's failure, not the "
            "compiler's): not counted",
    "environment": "environment: not counted",
    "not_reproduced": "not reproduced: not counted",
    "illegal": "illegal: not counted",
    "not_a_failure": "not a failure: not counted",
    "ungated": "ungated (no gate verdict yet): not counted here",
}
COUNTED_STATES = ("confirmed", "decided")


def gate_status(rec: dict | None, decision: dict | None) -> str:
    """The gate column of a failing cell from its verdict record
    (offload.engine.gate.load_verdicts) and its decision
    (offload.engine.gate.load_decisions): ``decided`` (counts_as: failure) or
    ``decided_not_counted`` when a decision names the cell; ``confirmed``
    for its own confirmed verdict or one inherited from a compile-time
    defect signature (an inherited verdict of any other kind reads
    ``unchecked``); else the verdict, or ``ungated``."""
    if decision:
        return "decided" if decision.get("counts_as") == "failure" else \
            "decided_not_counted"
    if rec is None:
        return "ungated"
    v = rec.get("verdict") or "ungated"
    if v == "confirmed" and rec.get("inherited"):
        from offload.engine.gate import COMPILE_CLASSES
        parts = str(rec.get("signature", "")).split("|")
        return "confirmed" if len(parts) > 1 and \
            parts[1] in COMPILE_CLASSES else "unchecked"
    return v


def runtime_ruling(r: Row):
    """The recorded ruling (catalog/rulings.yaml, `decides` naming outcome
    classes) that decides the cell, or None: e.g.
    RUL-HOST-LIBATOMIC (our_bug) or RUL-MAPPED-FLAG-NOT-COPIED-BACK (a
    fell-back-to-host cell that ran on the device: a finding's wrong
    answer)."""
    import re as _re
    from fnmatch import fnmatchcase
    from offload.engine.confirm import registry as REG
    from offload.engine.confirm.facts import family as _family
    for e in REG.entries().values():
        d = e.decides or {}
        outs = d.get("outcome")
        if not d.get("verdict") or not isinstance(outs, list):
            continue
        if r.outcome not in outs:
            continue
        if not any(fnmatchcase(r.program_id, p)
                   for p in e.applies.get("programs", ())):
            continue
        if d.get("families") and _family(r.toolchain) not in d["families"]:
            continue
        if d.get("toolchains") and r.toolchain not in d["toolchains"]:
            continue
        if d.get("reason") and not _re.search(d["reason"], r.reason or ""):
            continue
        return e
    return None


def _ours(r: Row) -> bool:
    """A recorded ruling says the cell's failure is our build's (verdict
    our_bug; the withdrawn complex-reduction link)."""
    e = runtime_ruling(r)
    return e is not None and e.decides.get("verdict") == "our_bug"


# the GCC lane gates its own rows into verdict files of its own (tools/campaigns/gcc_lane.py,
# one per host it ran on), keyed by cell only
LANE_VERDICTS = ROOT / "results" / "gcc"


def _lane_index(paths) -> dict:
    """(kind, ident, toolchain, row key) -> the lane's verdict record of a catalog cell."""
    out = {}
    for p in paths:
        for ln in Path(p).read_text().splitlines() if Path(p).is_file() else ():
            if ln.strip():
                d = json.loads(ln)
                kind, ident, tc, x = d["cell"].split("|")
                out[(kind, ident, tc, int(x))] = d
    return out


def annotate_gate(table: list[Row], verdicts: Path | None = None,
                  decisions: Path | None = None, lanes=None) -> list[Row]:
    """The rows with the gate column set on every failing legal cell
    (_failure of its label); the catalog and the widened catalog are one
    verdict kind (offload.engine.gate._case_index). `lanes`: the GCC lane's
    verdict files (default: those under LANE_VERDICTS when `verdicts` is the
    gate's store); the gate's store wins a cell both hold."""
    from offload.engine import gate as G
    if lanes is None:
        lanes = sorted(LANE_VERDICTS.glob("gate*/verdicts.jsonl")) if verdicts is None else []
    idx = {**_lane_index(lanes), **G._case_index(verdicts)}
    dec = G.load_decisions(decisions)
    out = []
    for r in table:
        if not r.legal or not _failure(r.label):
            out.append(replace(r, gate="") if r.gate else r)
            continue
        if _ours(r):
            out.append(replace(r, gate="ours"))
            continue
        rec = idx.get(("catalog", r.program_id, r.toolchain, int(r.xnack)))
        d = dec.get(rec["cell"]) if rec else None
        out.append(replace(r, gate=gate_status(rec, d)))
    return out


def confirmed_failure(r: Row) -> bool:
    """Whether a support-table cell counts as a compiler failure (the ruling on): a failing legal cell whose gate
    status is ``confirmed`` (its own confirmed rerun, or a confirmed
    verdict inherited from a compile-time signature) or ``decided`` (a
    Decision with counts_as: failure).

    It differs from offload.engine.gate.counts / counts_as_failure on purpose:
    those answer "does the row keep counting in a campaign's counts" and
    keep an ``unchecked`` row (not rerun) and a row the gate has not seen
    at their previous outcome; the support tables answer "is this failure
    confirmed", so an unchecked, ungated, nondeterministic or otherwise
    unconfirmed cell is shown apart and not counted."""
    return r.legal and _failure(r.label) and r.gate in COUNTED_STATES


def gate_section(table: list[Row]) -> list[str]:
    """The Markdown section of the gate column: failing legal cells by
    gate status per column, and the failing cells that do not count."""
    bad = [r for r in table if r.legal and _failure(r.label)]
    order = columns()
    cols = sorted({(r.toolchain, r.xnack) for r in table},
                  key=lambda c: (order.index(c) if c in order else
                                 len(order), c[0], -c[1]))
    head = " | ".join(f"{TC_NAME.get(t, t)} X={x}" if t not in NV else
                      f"{TC_NAME.get(t, t)} {nv_mode_name(t, x)}"
                      for t, x in cols)
    out = ["## Reproduction gate", "",
           "Each failing legal cell (a counted rejection, a wrong answer, a "
           "crash, a host fallback, a failed probe) carries the "
           "reproduction gate's status (offload.engine.gate, "
           "results/gate/verdicts.jsonl, and the decisions of "
           "catalog/gate_queue.yaml): **confirmed** (its own rerun verdict, "
           "or one inherited from a compile-time defect signature), "
           "**decided** (a decision; it counts when the decision "
           "says counts_as: failure), **unchecked** (the gate did not rerun "
           "it), **nondeterministic**, **ours** (a recorded ruling says the "
           "failure is our build's), the other verdicts, or **ungated** (no "
           "verdict yet). A cell counts as a compiler failure only when "
           "confirmed or decided as counting (report.confirmed_failure; the "
           "campaign counts of offload.engine.gate.counts keep unchecked rows at "
           "their previous outcome, a different question); every other "
           "failing cell is listed apart below, and only counted cells (and "
           "ungated ones) contradict a support claim. The CSV's "
           "last column, `gate`, has the status of every failing cell.", "",
           f"| gate | {head} |", "|---|" + "---|" * len(cols)]
    states = [g for g in GATE_STATES if any(r.gate == g for r in bad)]
    for g in states:
        out.append(f"| {GATE_TEXT[g]} | " + " | ".join(
            str(sum(1 for r in bad if r.gate == g and
                    (r.toolchain, r.xnack) == c)) for c in cols) + " |")
    out.append("| failing cells | " + " | ".join(
        str(sum(1 for r in bad if (r.toolchain, r.xnack) == c))
        for c in cols) + " |")
    ruled = [(r, e) for r in bad if (e := runtime_ruling(r)) is not None
             and e.decides.get("verdict") != "our_bug"]
    if ruled:
        out += ["", "### Cells a recorded ruling reads otherwise", "",
                "Counted as above; the label is the harness's outcome, the "
                "ruling (catalog/rulings.yaml) says what the cell is (review "
                "M10: a ran_on_host=1 cell whose region ran on the device "
                "and whose map(tofrom) flag was not copied back is a wrong "
                "answer, not a host fallback).", "",
                "| version | program | toolchain | X | report | ruling |",
                "|---|---|---|---|---|---|"]
        out += [f"| {_vstr(r.version)} | {r.program_id} | "
                f"{TC_NAME.get(r.toolchain, r.toolchain)} | {r.xnack} | "
                f"{_md(_clip(r.label, 60))} | {e.id} |" for r, e in ruled]
    apart = [r for r in bad if not confirmed_failure(r)]
    out += ["", "### Not counted: failing cells without a confirmed verdict "
            "or a counting decision",
            ""]
    if apart:
        out += ["| version | program | toolchain | X | report | gate |",
                "|---|---|---|---|---|---|"]
        out += [f"| {_vstr(r.version)} | {r.program_id} | "
                f"{TC_NAME.get(r.toolchain, r.toolchain)} | {r.xnack} | "
                f"{_md(_clip(r.label, 90))} | {r.gate} |" for r in apart]
    else:
        out.append("None.")
    out.append("")
    return out


CSV_FIELDS = ("version", "program_id", "atom", "legal", "violates",
              "toolchain", "xnack", "outcome", "label", "flaky", "evidence",
              "audit", "needs", "thp", "citation", "reason", "mode",
              "copy_label", "host", "suite_narrow", "basis",
              # The program's language (f90 | c); last, so the
              # earlier columns keep their positions
              "lang",
              # Device | host+device (a pattern program, not the
              # atom's headline)
              "scope",
              # Headline legal rows: the portable verdict
              # (PORTABLE) and the class of a mode difference
              "portable", "mode_class",
              # Presence checks at HSA_XNACK=1
              "presence_x1",
              # The row's GPU arch (gfx942 | gfx90a) and, on
              # headline rows, the class of a gfx90a difference
              "arch", "arch_class",
              # Failing legal cells: the reproduction gate's
              # status (counted as a compiler failure only when confirmed)
              "gate")


def _suite_text(suite: dict | None, atom: str, tc: str) -> str:
    """'n pass / n fail' of the narrow omp_vv tests of an atom, '' when
    none."""
    v = (suite or {}).get((atom, tc))
    return f"{v[0]} pass / {v[1]} fail" if v and sum(v) else ""


def _paths_out(text: str) -> str:
    """A compiler message with its install path named by the install ($NVHPC_26_9), not by where it is."""
    from offload.engine.site.matrix import B
    return B.scrub(text)


def render_csv(table: list[Row], suite: dict | None = None,
               meta: dict | None = None) -> str:
    """One CSV row per cell. `mode`: headline (HSA_XNACK=1) or copy;
    `copy_label` (headline rows): the same program's copy-mode label or
    'not run'; `host`: the node per the run metadata; `suite_narrow`: the
    omp_vv second source for the atom and toolchain."""
    host = program_hosts(meta or {})
    g90_host = g90_hosts(meta or {})
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_FIELDS)
    for r in table:
        cite = (atom_citation(r.atom, r.version)[0] if r.legal
                else rule_citation(r.violates)[0])
        arch = arch_of(r.toolchain)
        twin = r.toolchain in TWINS
        mode = _reg().twin_tag(r.toolchain) if twin else \
            ("headline" if r.xnack == HEADLINE else "copy") \
            if arch == "gfx942" else arch
        nvh = r.toolchain in NV and r.xnack == nv_modes(r.toolchain)[0]
        if r.toolchain in NV:  # E.g. "sm_80 separate"
            mode = f"{arch} {nv_mode_name(r.toolchain, r.xnack)}"
        w.writerow([r.version, r.program_id, r.atom, int(r.legal),
                    r.violates or "", r.toolchain, r.xnack, r.outcome,
                    r.label, int(r.flaky), r.evidence, r.audit,
                    " ".join(r.needs), r.thp, cite, _clip(_paths_out(r.reason), 300),
                    mode, r.copy_label if r.xnack == HEADLINE and
                    r.toolchain not in NV or nvh else "",
                    (host(r.program_id, r.xnack) if arch == "gfx942" and not twin
                     else g90_host(r.program_id) if r.toolchain in G90
                     else "") or "",
                    _suite_text(suite, r.atom, r.toolchain) if r.legal
                    else "", r.basis, r.lang, r.scope, r.portable,
                    r.mode_class, r.presence_x1, arch, r.arch_class,
                    r.gate])
    return buf.getvalue()


def program_hosts(meta: dict):
    """host(program_id, xnack) -> the node its row ran on per the run
    metadata (the mode's run, then its reruns in order), None if not
    recorded."""
    table: dict[tuple, str] = {}
    base: dict[int, str] = {}
    for x in MODES:
        m = meta.get(x) or {}
        if m.get("host"):
            base[x] = m["host"]
        for rr in m.get("reruns", []):
            for p in rr.get("programs", []):
                table[(p, x)] = rr.get("host")
    return lambda pid, x: table.get((pid, x), base.get(x))


def g90_hosts(meta: dict):
    """host(program_id) -> the Tioga node of a program's gfx90a row (Task
    30: the replace runs recorded in meta["g90"]), None if not
    recorded."""
    table: dict[str, str] = {}
    for rr in (meta.get("g90") or {}).get("reruns", []):
        for p in rr.get("programs", []):
            table[p] = rr.get("host")
    return table.get


def _cells(rows: list[Row]) -> dict[tuple, Row]:
    return {(r.toolchain, r.xnack): r for r in rows}


def _mode_key(row: Row) -> tuple:
    """What must differ between the two modes for a dagger: the outcome and
    whether it was a crash, not the label (copy_mode_only labels differ by
    design)."""
    return (row.outcome, row.reason.startswith("crash:"))


def _mode_cells(rows: list[Row], host=None) -> list[str]:
    """Cell texts in column order (per toolchain: headline, copy mode). A
    dagger marks a toolchain whose two modes differ and whose two rows ran
    on different or unrecorded nodes (`host(program_id, xnack)`); a
    copy_mode_only headline cell with a copy-mode row carries COPY_MARK."""
    host = host or (lambda pid, x: None)
    cells = _cells(rows)
    out = []
    for tc in TOOLCHAINS:
        both = [cells.get((tc, x)) for x in MODES] if tc in MI300A else []
        differ = bool(both) and all(both) and _mode_key(both[0]) != _mode_key(both[1])
        if differ:
            h = [host(r.program_id, r.xnack) for r in both]
            differ = None in h or h[0] != h[1]
        for x, r in zip(MODES, both):
            if r is None:
                out.append(NOT_RUN if x == COPY else "n/a")
                continue
            mark = (f" {COPY_MARK}" if x == HEADLINE and r.legal
                    and r.evidence == "copy_mode_only" and both[1]
                    and r.outcome not in _COMPILE_TIME else "")
            out.append(_md(r.label) + mark + (" †" if differ else ""))
        for w in twins_of(tc):  # The gfx90a, MI300X and MI350X cells
            g = cells.get((w, COPY))
            out.append(_md(g.label) if g else NOT_RUN)
    for tc in NV:  # One cell per mode of its machine
        for x in nv_modes(tc):
            r = cells.get((tc, x))
            out.append(_md(r.label) if r else NOT_RUN)
    return out


def _head_modes() -> str:
    cols = [f"{TC_NAME[tc]} {nv_mode_name(tc, x)} (A100)" if tc in NV
            else f"{TC_NAME[tc]} (X=1)" if x == HEADLINE
            else f"{TC_NAME[tc]} (X=0)" if tc in TWINS
            else f"{TC_NAME[tc]} copy mode (X=0)"
            for tc, x in columns()]
    return " | ".join(cols)


COPY_MARK_TEXT = (f"{COPY_MARK} = copy_mode_only: the check separates the "
                  "construct from a no-op only in copy mode, so the cell's "
                  "real check is its copy-mode column.")
DAGGER_TEXT = ("† = the two modes differ for that toolchain and their rows "
               "ran on different (or unrecorded) nodes, so the node may "
               "explain the difference as well as the memory mode.")


def _versions_text(table: list[Row]) -> str:
    """'5.2 and 6.0' (or '5.0, 5.2 and 6.0') for the versions in a table."""
    vs = [_vstr(v) for v in sorted({r.version for r in table})] or [
        "5.2", "6.0"]
    return vs[0] if len(vs) == 1 else ", ".join(vs[:-1]) + " and " + vs[-1]


def _provisional_section(table: list[Row]) -> list[str]:
    model = table_model(table)
    CLAUSES, RULES, OVERRIDES, LINK = _paths(model)
    clauses = _yaml(CLAUSES).get("clauses", {})
    rules = _yaml(RULES).get("rules", [])
    ov = _yaml(OVERRIDES) or {}
    ov_lists = {k: v for k, v in ov.items() if isinstance(v, list)}
    n_ov = sum(len(v) for v in ov_lists.values())
    st = Counter(e.get("status") for e in clauses.values())
    rs = Counter(r.get("status") for r in rules)
    os_ = Counter(e.get("status") for v in ov_lists.values() for e in v)
    ov_clauses = sorted({e["clause"] for e in ov.get("clause_rules", [])})
    ov_dirs = sorted({e["directive"] for k in ("directive_versions",
                                               "directive_spellings")
                      for e in ov.get(k, [])})
    atoms = sorted({r.atom for r in table if r.legal})
    hit_c = [a for a in atoms if a.startswith(f"{model}.clause.")
             and a.split(".")[2] in ov_clauses]
    hit_d = [a for a in atoms if a.startswith(f"{model}.directive.")
             and a.split(".")[2].replace("_", " ") in ov_dirs]
    illegal = sorted({r.violates for r in table if not r.legal and r.violates})
    vers = _versions_text(table)
    return [
        "## Results that depend on provisional rules",
        "",
        "Nothing in the catalog has been reviewed by the maintainer yet, so every "
        "result depends on provisional data:",
        "",
        f"- **Every legal cell** depends on its atom's clause-grammar entry "
        f"([clauses.yaml]({LINK['clauses']}): "
        f"{dict(st)} of {len(clauses)} clauses) and on the generator's "
        "reading of it.",
        f"- **Every illegal-variant cell** depends on the one rule it violates "
        f"([rules.yaml]({LINK['rules']}): {dict(rs)} of {len(rules)} rules; "
        f"{len(illegal)} rule versions exercised here).",
        f"- **Spec overrides** of the TableGen skeleton "
        f"(catalog/{model}/spec_overrides.yaml: {dict(os_)} of {n_ov}) "
        "decide whether a clause is allowed on a directive"
        + (f" at {vers.replace(' and ', ' or ')}" if model == "omp"
           else "") + ". Atoms whose "
        f"clause has an override ({len(hit_c)}): "
        + ", ".join(f"`{a.removeprefix(model + '.')}`" for a in hit_c) + ". "
        f"Directive atoms whose version or spelling is an override "
        f"({len(hit_d)}): "
        + (", ".join(f"`{a.removeprefix(model + '.')}`" for a in hit_d)
           or "none")
        + ".",
        "- **Every vendor claim** in "
        f"[claims.yaml]({LINK['claims']}) is provisional: the mapping from a "
        "vendor's prose to an atom is this project's reading.",
        "",
    ]


def _baseline_section(baseline: list[dict], meta: dict | None = None,
                      c_lang: bool = False) -> list[str]:
    if not baseline:
        return ["## Corpus baseline", "", "No baseline results given.", ""]
    if c_lang:  # The omp_vv C tests
        cnt = Counter((b["toolchain"], b["xnack"], b["status"],
                       b.get("stage", "")) for b in baseline)
        files = len({(b.get("repo"), b.get("path")) for b in baseline})
        lines = [
            "## Corpus baseline (omp_vv C target tests)", "",
            f"{len(baseline)} results ({files} files x toolchain x memory "
            f"mode run). {_baseline_modes(baseline, meta or {})} Each test "
            "is compiled with the compiler's default OpenMP version (5.1) "
            "when its spec directory is 4.5, 5.0 or 5.1, with "
            "-fopenmp-version= its directory for 5.2 and 6.0, and with the "
            "suite's -I ompvv -lm, run once under "
            "OMP_TARGET_OFFLOAD=mandatory. Pass criterion: exit code 0; the "
            "tests are **unaudited** (their self-checks were not "
            "mutation-tested).", "",
            "| toolchain | HSA_XNACK | pass | fail (compile) | fail (run) | "
            "harness error |", "|---|---|---|---|---|---|"]
        for tc, x in columns():
            if not any(b["toolchain"] == tc and b["xnack"] == x
                       for b in baseline):
                continue
            lines.append(
                f"| {TC_NAME[tc]} | {x} | {cnt[(tc, x, 'pass', 'run')]} | "
                f"{cnt[(tc, x, 'fail', 'compile')]} | "
                f"{cnt[(tc, x, 'fail', 'run')]} | "
                f"{sum(v for k, v in cnt.items() if k[:3] == (tc, x, 'harness_error'))} |")
        return lines + [""] + _baseline_mode_flags(baseline)
    cnt = Counter((b["toolchain"], b["xnack"], b["status"], b.get("stage", ""))
                  for b in baseline)
    host = [b for b in baseline if b["status"] == "pass"
            and "passed on the host" in b.get("stdout", "").lower()]
    hc = Counter((b["toolchain"], b["xnack"]) for b in host)
    files = len({(b.get("repo"), b.get("path")) for b in baseline})
    lines = [
        "## Corpus baseline (omp_vv Fortran target tests)",
        "",
        f"{len(baseline)} results ({files} files x toolchain x memory mode "
        f"run). {_baseline_modes(baseline, meta or {})} "
        "Pass criterion: exit code 0 (Global Constraints); these tests are "
        "**unaudited**: their self-checks were not mutation-tested, so a pass "
        "says the program compiled and exited 0, not that the feature works.",
        "",
        "| toolchain | HSA_XNACK | pass | fail (compile) | fail (run) | "
        "of which pass prints 'Test passed on the host' [^host] |",
        "|---|---|---|---|---|---|",
    ]
    for tc, x in columns():
        lines.append(
            f"| {TC_NAME[tc]} | {x} | {cnt[(tc, x, 'pass', 'run')]} | "
            f"{cnt[(tc, x, 'fail', 'compile')]} | "
            f"{cnt[(tc, x, 'fail', 'run')]} | {hc[(tc, x)]} |")
    lines += [
        "",
        f"[^host]: {len(host)} baseline passes print \"Test passed on the "
        "host\". The omp_vv module (ompvv/ompvv.F90) prints \"host\" when its "
        "flag ompvv_isHost is true: the flag starts .true. and only the "
        "test's offloading probe (a target region calling "
        "omp_is_initial_device) sets it, so the message means either that the "
        "probe ran on the initial device or that the test never called the "
        "probe; every run set OMP_TARGET_OFFLOAD=mandatory. Exit code 0 counts "
        "them as passes under the baseline rule; they are not evidence of "
        "device execution. "
        "Files: "
        + ", ".join(sorted({b['path'].rsplit('/', 1)[-1] for b in host}))
        + ".",
        "",
    ]
    return lines + _baseline_mode_flags(baseline)


def _baseline_mode_flags(baseline: list[dict]) -> list[str]:
    """Omp_vv tests whose status differs between the two memory
    modes on a toolchain. The tests are untrusted (not mutation-tested), so
    these are flags for review, never findings."""
    by: dict[tuple, dict] = defaultdict(dict)
    for b in baseline:
        if arch_of(b["toolchain"]) != "gfx942":
            continue  # _baseline_g90_flags
        by[(b["path"], b["toolchain"])][b["xnack"]] = b
    diff = [(p, t, m) for (p, t), m in sorted(by.items())
            if len(m) == 2 and m[0]["status"] != m[1]["status"]]
    out = ["### omp_vv tests whose memory modes differ (flags)", "",
           "omp_vv tests are untrusted (their checks were not "
           "mutation-tested): a test that passes in one mode only is "
           "flagged for review, never reported as a compiler finding.", ""]
    if not diff:
        return out + ["None.", ""] + _baseline_g90_flags(baseline)
    c = Counter((t, m[1]["status"] == "pass") for _, t, m in diff)
    out += ["| toolchain | passes at X=1 only | passes at X=0 only |",
            "|---|---|---|"]
    for t in TOOLCHAINS:
        if c[(t, True)] or c[(t, False)]:
            out.append(f"| {TC_NAME[t]} | {c[(t, True)]} | "
                       f"{c[(t, False)]} |")
    out += ["", "| test | toolchain | X=1 | X=0 |", "|---|---|---|---|"]
    for p, t, m in diff:
        def cell(b):
            return _md(_clip(f"{b['status']} ({b.get('stage', '')}: "
                             f"{b.get('reason', '')})", 120))
        out.append(f"| {p.removeprefix('tests/')} | "
                   f"{TC_NAME.get(t, t)} | {cell(m[1])} | {cell(m[0])} |")
    return out + [""] + _baseline_g90_flags(baseline)


def _baseline_g90_flags(baseline: list[dict]) -> list[str]:
    """Omp_vv tests whose gfx90a status differs from the same
    compiler's MI300A copy-mode (HSA_XNACK=0) status; flags for review,
    never findings (the tests are untrusted)."""
    by: dict[tuple, dict] = defaultdict(dict)
    for b in baseline:
        by[(b["path"], base_name(b["toolchain"]))][
            arch_of(b["toolchain"])] = b
    pairs = [(p, t, m) for (p, t), m in sorted(by.items())
             if "gfx90a" in m and "gfx942" in m]
    if not pairs:
        return []
    diff = [(p, t, m) for p, t, m in pairs
            if m["gfx90a"]["status"] != m["gfx942"]["status"]]
    out = ["### omp_vv tests whose gfx90a result differs from MI300A copy "
           "mode (flags)", "",
           f"{len(diff)} of {len(pairs)} (test, compiler) pairs differ "
           "between MI300A at HSA_XNACK=0 and gfx90a (HSA_XNACK=0). The "
           "tests are untrusted: flags for review, never findings.", ""]
    if not diff:
        return out + ["None.", ""]

    def cell(b):
        return _md(_clip(f"{b['status']} ({b.get('stage', '')}: "
                         f"{b.get('reason', '')})", 120))
    out += ["| test | compiler | MI300A X=0 | gfx90a |", "|---|---|---|---|"]
    for p, t, m in diff:
        out.append(f"| {p.removeprefix('tests/')} | {TC_NAME.get(t, t)} | "
                   f"{cell(m['gfx942'])} | {cell(m['gfx90a'])} |")
    return out + [""]


def _baseline_modes(baseline: list[dict], meta: dict) -> str:
    """Which tests ran in which mode, and on which nodes."""
    by = defaultdict(set)
    for b in baseline:
        by[b["xnack"]].add(b["path"])
    if by[COPY] == by[HEADLINE]:
        text = "Every test ran in both modes"
    else:
        text = (f"Every test ran at HSA_XNACK=1 ({len(by[HEADLINE])} files); "
                f"copy mode ran only the {len(by[COPY])} tests whose result "
                "depends on copy semantics (offload.engine.ompvv.copy_semantics)")
    nodes = []
    for x in MODES:
        m = meta.get(x) or {}
        if m.get("baseline_rows"):
            nodes.append(f"HSA_XNACK={x} with the matrix run on "
                         f"{m.get('host', '?')}")
        for rr in (meta.get(f"baseline{x}") or {}).get("reruns", []):
            nodes.append(f"HSA_XNACK={x} rows of "
                         f"{len(rr.get('baseline_paths', []))} tests rerun on "
                         f"{rr.get('host', '?')} ({rr.get('started', '?')})")
    return text + (" (" + "; ".join(nodes) + ")." if nodes else
                   "; nodes not recorded.")


def _claims_section(table: list[Row], mismatches: list[Mismatch],
                    claims: list[Claim]) -> list[str]:
    groups = claim_groups(table, claims)
    sources: dict[tuple, Claim] = {}
    for c in claims:   # One row per document edition
        sources.setdefault((c.source, c.toolchain), c)
    lines = [
        "## Vendor claims versus measurements",
        "",
        "All claims are **provisional** and cited in "
        f"[claims.yaml]({LINK['claims']}). A claim covers an atom by name or "
        "pattern; a release-level (general) claim applies only where no "
        "specific claim for that toolchain covers the atom. Comparison rules: "
        "`supported` is contradicted by rejected, ignored, fell back, wrong "
        "answer or crash; `unsupported` by correct on device (or, for a "
        "compile-error claim, by anything but rejection); `partial` only when "
        "the vendor says the form is accepted and it is rejected. Cells that "
        "cannot separate the construct (no oracle: hint only, "
        "implementation-defined, equivalent default; legality; unverified; "
        "unobservable) never contradict a claim, except that a crash of such "
        "an atom does (a crash needs no oracle), and they never count as "
        "support; zero-copy programs in copy mode and illegal "
        "variants are not compared. Both memory modes are compared where both "
        "ran.",
        "",
        "### Sources",
        "",
        "| source | toolchain | language of the claim | URL | version note |",
        "|---|---|---|---|---|",
    ]
    for (s, _), c in sources.items():
        lines.append(f"| {s} | {TC_NAME.get(c.toolchain, c.toolchain)} | "
                     f"{c.language} | <{c.url}> | {_md(c.version_note)} |")
    n_groups = len(groups)
    confirmed = [m for m in mismatches if not m.oracle_unaudited]
    unaud = [m for m in mismatches if m.oracle_unaudited]
    lines += [
        "",
        f"{len(claims)} claim entries; {n_groups} (claim, atom, version, "
        f"toolchain) comparisons; {len(mismatches)} mismatches "
        f"({len(confirmed)} from a compile result, a crash, or an audited "
        "oracle, "
        f"{len(unaud)} from a run-time result of an oracle-unaudited atom). "
        "A rejection can come from another feature the program also uses; "
        "the harness reason column shows the compiler's message.",
        "",
    ]

    def table_of(ms: list[Mismatch]) -> list[str]:
        out = ["| toolchain | atom | version | claimed [source] | measured | "
               "harness reason (first contradicting cell) | vendor text |",
               "|---|---|---|---|---|---|---|"]
        for m in ms:
            out.append(
                f"| {TC_NAME.get(m.toolchain, m.toolchain)} | "
                f"`{m.atom.removeprefix('omp.')}` | {_vstr(m.version)} | "
                f"{_md(m.claimed)}{' (general)' if m.general else ''}"
                f"{' (C/C++ table)' if m.language == 'C/C++' and m.lang != 'c' else ''} | "
                f"{_md(m.measured)} | {_md(_clip(m.reason, 110))} | "
                f"[{_md(_clip(m.quote, 90))}]({m.url}) |")
        return out

    caveats = sorted({m.confound for m in mismatches if m.confound})
    lines += ["### Mismatches", ""] + (table_of(confirmed) if confirmed
                                       else ["None."])
    if caveats:
        lines += ["", "‡ Confounded program (generator follow-up): "
                  + "; ".join(caveats) + "."]
    lines += ["", "### Mismatches on oracle-unaudited atoms (not confirmed)",
              "",
              "Run-time outcomes of atoms whose oracle is unaudited (no "
              "toolchain passes the original program). The measured outcome "
              "stands, but these are not confirmed failures.", ""]
    lines += table_of(unaud) if unaud else ["None."]
    lines.append("")
    return lines


def _rerun_winners(modes: dict) -> str:
    """Which rerun produced the final rows of a program rerun more than
    once in one mode (the later run replaced the earlier rows)."""
    parts = []
    for x in MODES:
        last: dict[str, str] = {}
        seen: Counter = Counter()
        for rr in modes.get(x, {}).get("reruns", []):
            for p in rr.get("programs", []):
                seen[p] += 1
                last[p] = rr.get("host", "?")
        multi = sorted(p for p, n in seen.items() if n > 1)
        if multi:
            parts.append(f"HSA_XNACK={x}: " + ", ".join(
                f"`{p}`: {last[p]}" for p in multi))
    if not parts:
        return ""
    return ("- Programs rerun more than once in one mode: their rows come "
            "from the last rerun, " + "; ".join(parts) + ".")


def _stale_audit_note(legal: list[Row]) -> str:
    """One line naming the atoms the audit calls unaudited although a
    toolchain passes them in the matrix."""
    stale = sorted({(r.version, r.atom) for r in legal
                    if r.audit.startswith("unaudited")
                    and r.outcome == "correct_on_device"})
    if not stale:
        return ("- Audit dispositions come from the committed audit run; no "
                "unaudited atom passes in the matrix.")
    names = ", ".join(f"`{a.split('.', 1)[1]}` ({_vstr(v)})"
                      for v, a in stale)
    if all(a.startswith("acc.") for _, a in stale):
        return ("- **The OpenACC audit runs on CCE 19 only**: for these "
                "atoms CCE 19 fails the original while another toolchain "
                "passes it in the matrix, so 'oracle unaudited' does not "
                "mean that no compiler runs the program: " + names + ".")
    return ("- **Audit dispositions predate the explicit -fopenmp-version=60 "
            "run** of AFAR's 6.0 programs, in which AFAR rejected the "
            "originals. For these atoms a toolchain passes the original in "
            "the matrix, so 'oracle unaudited' may not apply (re-audit is a "
            f"follow-up): {names}.")


def _node_counts(table: list[Row], host) -> tuple[int, int, int]:
    """(same node, different nodes, unrecorded) over the (program,
    toolchain) pairs that have both modes."""
    pairs = defaultdict(dict)
    for r in table:
        if r.toolchain in NVIDIA_TOOLCHAINS:  # AMD modes only
            continue
        pairs[(r.program_id, r.toolchain)][r.xnack] = r
    same = diff = unknown = 0
    for (pid, _), m in pairs.items():
        if len(m) < 2:
            continue
        h = [host(pid, x) for x in MODES]
        if None in h:
            unknown += 1
        elif h[0] == h[1]:
            same += 1
        else:
            diff += 1
    return same, diff, unknown


def _modes_provenance(table: list[Row], meta: dict, host) -> list[str]:
    modes = {x: m for x, m in meta.items() if isinstance(x, int)}
    amd = [r for r in table if r.toolchain not in NVIDIA_TOOLCHAINS]
    progs = {r.program_id for r in amd}
    copy = {r.program_id for r in amd if r.xnack == COPY}
    if copy == progs:
        which = "every program (a full two-mode matrix)"
    else:
        which = ("the copy-mode subset only: the copy_mode_only programs and "
                 "the memory-sensitive ones of "
                 "catalog/omp/memory_modes.yaml (offload.engine.run_matrix."
                 "copy_mode_subset)")
    same, diff, unknown = _node_counts(table, host)
    if not amd:
        return []  # An NVIDIA-only table (OpenACC C)

    def run(x):
        m = modes.get(x, {})
        return (f"{m.get('host', '?')} (THP {m.get('thp_seen', '?')}, "
                f"started {m.get('started', '?')})")
    return [
        "- **Headline mode: HSA_XNACK=1 with transparent huge pages** (LC's "
        "example job script) for every program. **Copy mode "
        f"(HSA_XNACK=0)** for {len(copy)} of {len(progs)} programs: "
        f"{which}. A copy-mode column reads '{NOT_RUN}' for the others.",
        f"- HSA_XNACK=1 run on {run(HEADLINE)}; HSA_XNACK=0 run on "
        f"{run(COPY)}. Of the program x toolchain pairs with both modes, "
        f"{same} have both rows from one node, {diff} from different nodes "
        f"and {unknown} from unrecorded nodes; where the modes of the latter "
        "differ, the cells carry a dagger (†).",
    ]


def _g90_provenance(table: list[Row], meta: dict) -> list[str]:
    """Where the gfx90a rows ran."""
    g = [r for r in table if arch_of(r.toolchain) == "gfx90a"]
    if not g:
        return []
    runs = (meta.get("g90") or {}).get("reruns", [])
    # the machine's name, not the node's (<machine>-gpu<n>.<domain> is <machine>)
    hosts = sorted({re.sub(r"-gpu\d+$", "", (rr.get("host") or "?").split(".")[0]) for rr in runs})
    return [
        f"- **gfx90a (Tioga, AMD Instinct MI250X, a discrete GPU): "
        f"HSA_XNACK=0 only** (XNACK is not "
        f"recommended on MI250X), {len({r.program_id for r in g})} "
        f"programs on " + ", ".join(TC_NAME[t] for t in G90) + ", nodes "
        + (", ".join(hosts) if hosts else "not recorded") + "; the same "
        "compiler releases with gfx90a as the offload arch "
        "(--offload-arch=gfx90a, craype-accel-amd-gfx90a for CCE, "
        "-march=gfx90a for GCC's amdgcn offload), the compilers' default "
        "('xnack any') code objects. Each compiler's third column."]


def _gcc_flags_text(c_lang: bool) -> str:
    """GCC's flags on the AMD GPUs (its catalog template), when it has a column."""
    if not any(_reg().toolchains[t].family_id == "gcc" for t in TOOLCHAINS):
        return ""
    t = _reg().toolchains["gcc"]
    flags = t.family.flags["omp"]["c" if c_lang else "f90"].format(
        target="amdgcn-amdhsa", arch="<the GPU's arch>", latomic="")
    return f" GCC: {'gcc' if c_lang else 'gfortran'} {flags} -O2, no version flag."


def _toolchains_text() -> str:
    """The status line's toolchains: the table's columns, by GPU."""
    amd = ", ".join(TC_NAME[t] for t in MI300A)
    other = ", ".join(TC_NAME[t] for t in TOOLCHAINS if t not in MI300A)
    nv = ", ".join(TC_NAME[t] for t in NV)
    return (f"Toolchains: {amd} on the MI300A (gfx942) and each one's other GPUs"
            + (f"; {other} on its other AMD GPUs only (not the MI300A)" if other else "")
            + (f"; {nv} on the A100 (sm_80)" if nv else "")
            + "; -O2, three runs per cell.")


def _twins_provenance(table: list[Row], meta: dict) -> list[str]:
    """Where the rows of the twins on other machines than Tioga ran (MI300X, MI350X)."""
    from offload.engine.confirm.machines import load
    reg, out = _reg(), []
    for m in load().values():
        tws = [t for t in TWINS if reg.toolchains[t].machine == m.name and t not in G90]
        if not tws:
            continue
        runs = (meta.get("twins") or {}).get(m.name, [])
        hosts = sorted({re.sub(r"-gpu\d+$", "", (rr.get("host") or "?").split(".")[0]) for rr in runs})
        progs = {r.program_id for r in table if r.toolchain in tws}
        out.append(
            f"- **{m.arch} ({m.device}, a discrete GPU): copy memory (HSA_XNACK=0) only**, "
            f"{len(progs)} programs on " + ", ".join(TC_NAME[t] for t in tws) + ", nodes "
            + (", ".join(hosts) if hosts else "not recorded") + "; the same compiler releases "
            f"with {m.arch} as the offload arch. A column of its own after the gfx90a "
            "one; it does not enter the portable verdict.")
    return out


def _nv_provenance(table: list[Row], meta: dict) -> list[str]:
    """Where the NVIDIA rows ran."""
    nv = [r for r in table if r.toolchain in NVIDIA_TOOLCHAINS]
    if not nv:
        return []
    runs = (meta.get("nvhpc") or {}).get("reruns", [])
    # the machine's name, not the node's (<machine>-gpu<n>.<domain> is <machine>)
    hosts = sorted({re.sub(r"-gpu\d+$", "", (rr.get("host") or "?").split(".")[0]) for rr in runs})
    comp = sorted({c for rr in runs for c in (rr.get("compilers") or {})
                   .values() if c})
    return [
        f"- **NVIDIA A100 (wingtip, sm_80): "
        + ", ".join(TC_NAME[t] for t in NV) + "**, "
        f"{len({r.program_id for r in nv})} programs; NVHPC in separate memory "
        "(-gpu=mem:separate, the headline mode) and managed memory "
        "(-gpu=mem:managed), each mode its own build; -mp=gpu (OpenACC: "
        "-acc=gpu) -gpu=cc80 -O2, no OpenMP version option (every version "
        "slice compiles with the default)"
        + ("; GCC in separate memory only, -foffload=nvptx-none"
           if any(_reg().toolchains[t].family_id == "gcc" for t in NV) else "")
        + "; no unified memory on that node (not applicable). Host "
        + (", ".join(hosts) if hosts else "not recorded")
        + (f"; {'; '.join(comp)}" if comp else "") + "."]


def render_markdown(table: list[Row], mismatches: list[Mismatch],
                    claims: Path | list[Claim] | None = None,
                    baseline: list[dict] | None = None,
                    meta: dict | None = None,
                    suite: dict | None = None) -> str:
    cl = (load_claims(claims) if isinstance(claims, (str, Path))
          else (claims or []))
    meta = meta or {}
    model = table_model(table)
    LINK = _paths(model)[3]
    acc = model == "acc"
    show_suite = not acc  # omp_vv is an OpenMP suite
    # The headline tables are device offload only; host+device
    # pattern programs have their own section
    legal = [r for r in table if r.legal and r.scope == "device"]
    hostdev = [r for r in table if r.legal and r.scope != "device"]
    illegal = [r for r in table if not r.legal]
    modes = {x: m for x, m in meta.items() if isinstance(x, int)}
    host = program_hosts(meta)
    rocm = sorted({r for r in (meta.get("rocm") or [])})
    intro = [
        "# Support table: OpenMP target offload, free-form Fortran",
        "",
        "Status: **provisional**. Generated by compliance/report.py "
        "(tools/derive/support_table.py) from results/matrix.jsonl, the committed "
        f"oracle audit summary ([oracle-audit.md]({LINK['audit']})) and "
        f"[claims.yaml]({LINK['claims']}). Scope: OpenMP "
        f"{_versions_text(table)} atoms of "
        "the first slice, free-form Fortran only (OpenACC and C are outside "
        f"this slice). {_toolchains_text()}",
        ""]
    c_lang = table_lang(table) == "c"
    if c_lang:
        intro = [
            "# Support table: OpenMP target offload, C11",
            "",
            "Status: **provisional**. Generated by compliance/report.py "
            "(tools/derive/support_table.py --lang c) from results/matrix_c.jsonl, "
            "the committed C oracle audit summary "
            "([oracle-audit-c.md](../reports/oracle-audit-c.md)) and "
            f"[claims.yaml]({LINK['claims']}) (claims about C or C/C++ "
            "only; a claim that names a do compound covers its for twin). "
            f"Scope: OpenMP {_versions_text(table)} atoms of the first "
            "slice in C: the C ports of the Fortran programs "
            "(offload.engine.c_gen, offload.engine.f2c) and the C-only illegal "
            f"variants. {_toolchains_text()} The CSV has the "
            "Fortran table's columns plus `lang` (c here, f90 there).",
            ""]
    if acc and c_lang:
        intro = [
            "# Support table: OpenACC 3.4, C11 (NVIDIA HPC SDK)",
            "",
            "Status: **provisional**. Generated by compliance/report.py "
            "(tools/derive/support_table.py --model acc --lang c) from "
            "results/acc_matrix_c.jsonl and the NVIDIA oracle audit "
            "summaries (tests/data/acc_audit_summary_nvhpc*_c.json). Scope: "
            "the OpenACC 3.4 atoms of the slice in C: the C "
            "ports of the Fortran programs (offload.engine.acc_c_gen, "
            "offload.engine.f2c) without the Fortran-only .eqv./.neqv. "
            "reductions. Toolchains: NVHPC 25.11 and 26.9 nvc -acc=gpu, "
            "NVIDIA A100, separate and managed memory; CCE's C compiler and "
            "AFAR have no OpenACC (results/t37/accprobe) and are not run.",
            ""]
    elif acc:
        intro = [
            "# Support table: OpenACC 3.4, free-form Fortran (CCE)",
            "",
            "Status: **provisional**. Generated by compliance/report.py "
            "(tools/derive/support_table.py --model acc) from "
            "results/acc_matrix.jsonl and the committed oracle audit summary "
            f"([acc-oracle-audit.md]({LINK['audit']})). Scope: the OpenACC "
            "3.4 atoms of the slice (catalog/acc/), free-form Fortran "
            "only. Toolchains: Cray CCE "
            + ", ".join(TC_NAME[t] for t in TOOLCHAINS)
            + " (ftn -h acc -O2), MI300A (gfx942); AFAR (amdflang) does not "
            "support OpenACC and is not run.",
            ""]
    lines = intro + [
        "## Provenance and memory modes",
        "",
        f"- {len(table)} cells: {len(legal)} legal-program cells, "
        f"{len(hostdev)} host+device pattern cells and "
        f"{len(illegal)} illegal-variant cells (program x toolchain x "
        "HSA_XNACK).",
        "- Scope: device offload only. A construct "
        "that runs on the host and whose result never reaches a "
        + ("compute" if acc else "target") + " region is out of scope (the "
        "section 'Out of scope (host execution)' lists those atoms); host "
        "constructs that feed a "
        + ("compute" if acc else "target") + " region the way codes use "
        "them are host+device patterns, reported in their own section and "
        "never as an atom's headline result.",
    ] + _modes_provenance(table, meta, host) + _g90_provenance(
        table, meta) + _twins_provenance(table, meta) + _nv_provenance(table, meta) + [
        f"- **Rerun rows** (HSA_XNACK={x}): {len(rr.get('programs', []))} "
        f"programs rerun on {rr.get('host', '?')} (THP "
        f"{rr.get('thp_seen', '?')}, started {rr.get('started', '?')}) "
        f"after {_public(rr.get('why', 'a change'))}: "
        + (", ".join(rr.get("programs", [])) if len(rr.get("programs", []))
           <= 40 else "(the full list is in the run metadata)") + "."
        + (f" Note: {_public(rr['note'])}." if rr.get("note") else "")
        for x in MODES for rr in modes.get(x, {}).get("reruns", [])
    ] + [w for w in [_rerun_winners(modes)] if w] + [
        ("" if acc and c_lang else  # NVHPC only (its own line)
         "- CCE compiles with -h acc -O2 (OpenMP off)." if acc else
         "- Every toolchain compiles a C program with -fopenmp-version= its "
         "version (both C front ends default to OpenMP 5.1); AFAR: amdclang "
         "-fopenmp --offload-arch=gfx942; CCE: craycc -fopenmp "
         "-fopenmp-targets=amdgcn-amd-amdhsa -Xopenmp-target=amdgcn-amd-amdhsa "
         "-march=gfx942 (the flags the craype-accel-amd-gfx942 module gives "
         "the cc wrapper; craycc -fopenmp alone builds a host-only "
         "executable). CCE 19 accepts -fopenmp-version=60 without a "
         "diagnostic but stays at OpenMP 5.1 (_OPENMP 202011)." if c_lang else
         "- AFAR compiles 6.0 programs with -fopenmp-version=60"
         + (", 5.0 programs with -fopenmp-version=50"
            if any(r.version == 50 for r in table) else "")
         + " and 5.2 "
         "programs with its default; CCE has no version flag (-fopenmp -O2).")
        + _gcc_flags_text(c_lang)
        + (f" ROCm loaded with CCE: {', '.join(rocm)}." if rocm else ""),
        ("- One run per trial: OpenACC has no counterpart of "
         "OMP_TARGET_OFFLOAD, so a failing run is not repeated; host "
         "execution shows as ran_on_host=1 (acc_on_device(acc_device_host) "
         "inside the compute region)." if acc else
         "- `OMP_TARGET_OFFLOAD=mandatory` on the primary run; a failing run "
         "is repeated without it to tell host fallback from a wrong answer."),
        "",
        "## How to read a cell",
        "",
        "- **correct on device**: the check passed and the region ran on the "
        "device; the evidence column says how strong that is: `construct` "
        "(the check depends on the construct), `probe` (a negative probe: "
        "the program names an absent item with the present modifier, so "
        "the run must end in the runtime's error termination; the cell "
        "reads 'error termination as required (negative probe)', and a run "
        "that went on reads 'no error termination (negative probe)'; or a "
        "compile-output probe: an error directive with at(compilation) whose "
        "message must appear as a warning, or whose fatal severity must stop "
        "the compile), "
        "`copy_mode_only` (the check "
        "separates the construct from a no-op only at HSA_XNACK=0; the "
        f"headline cell says so and carries {COPY_MARK}: the real check is "
        f"the copy-mode column, or the cell says '{COPY_NOT_RUN}'); the "
        "categories below have no separating oracle and are never credited "
        "as supported.",
        f"- **{NO_ORACLE_TEXT['hint_only']}** (`hint_only`): the spec lets "
        "an implementation ignore the form (a hint, an assertion the program "
        "makes, or a bound one-at-a-time execution meets); "
        f"**{NO_ORACLE_TEXT['implementation_defined']}** "
        "(`implementation_defined`): the spec leaves the behaviour to the "
        f"implementation; **{NO_ORACLE_TEXT['equivalent_default']}** "
        "(`equivalent_default`): by the spec the form is the behaviour "
        "without it. The cell reads so when the program compiled and ran "
        "cleanly; the spec sentence is in the citation column and in the "
        "section 'Atoms without a separating oracle'. Where the program "
        "checks what the form requires (e.g. the number of teams within "
        "the bounds) a failure reads as a wrong answer.",
        f"- **{LEGALITY_TEXT}** (`legality`): the atom's only effect is a "
        "compile-time restriction (default(none)); its oracle is the illegal "
        "variant in the illegal-variants table.",
        f"- **{UNVERIFIED_TEXT}** (`unverified`): the spec fixes the "
        "behaviour and a deterministic check is possible, but the program "
        "does not have it (the audit disposition says why).",
        "- **wrong answer (confirmed)**: the atom's oracle is audited valid "
        "(a mutant without the construct is killed on at least one "
        "toolchain). **wrong answer (oracle unaudited)** / **oracle "
        "unaudited**: measured outcome, but no toolchain passes the original "
        "program, so the oracle is unaudited; not a confirmed failure.",
        "- **crash: SIGABRT, HSA_XNACK=1 only**: the program aborts in that "
        "memory mode only (shown instead of a plain wrong answer).",
        "- **fails in copy mode: needs zero-copy memory**: the program needs "
        "HSA_XNACK=1; failing at HSA_XNACK=0 is expected and is not a "
        "feature result.",
        _stale_audit_note(legal),
        "- Illegal variants: **rejected** / **not rejected** only; acceptance "
        "of an illegal program is a neutral observation, never a wrong "
        "answer.",
        "",
    ]
    # summary counts
    n_copy = len({r.program_id for r in legal if r.xnack == COPY
                  and r.toolchain not in NV})
    n_legal = len({r.program_id for r in legal})
    lines += ["## Summary (legal-program cells)", "",
              "Headline columns count every program; copy-mode columns count "
              f"only the programs run in copy mode ({n_copy} of {n_legal} "
              "legal programs).", ""]
    for v in sorted({r.version for r in legal}):
        rows = [r for r in legal if r.version == v]
        fams = Counter((family(r.label), r.toolchain, r.xnack) for r in rows)
        names = sorted({f for f, _, _ in fams},
                       key=lambda f: (-sum(n for (g, _, _), n in fams.items()
                                           if g == f), f))
        n_atoms = len({r.atom for r in rows})
        lines += [f"### {_spec(v)} ({n_atoms} atoms)", "",
                  f"| outcome | {_head_modes()} |",
                  "|---|" + "---|" * len(columns())]
        for f in names:
            lines.append(f"| {f} | " + " | ".join(
                str(fams[(f, tc, x)]) for tc, x in columns())
                + " |")
        lines.append("")
    # illegal summary
    lines += ["### Illegal variants", "",
              f"| version | {_head_modes()} |",
              "|---|" + "---|" * len(columns())]
    for v in sorted({r.version for r in illegal}):
        rs = [r for r in illegal if r.version == v]
        lines.append(f"| {_vstr(v)} | " + " | ".join(
            f"{sum(1 for r in rs if r.toolchain == tc and r.xnack == x and r.outcome == 'rejected')}"
            f" rejected / "
            f"{sum(1 for r in rs if r.toolchain == tc and r.xnack == x and r.outcome == 'not_rejected')}"
            " not" for tc, x in columns()) + " |")
    lines.append("")
    lines += gate_section(table)
    # An NVIDIA-only table (OpenACC C) has no AMD mode sections
    amd_rows = any(r.toolchain not in NV for r in table)
    lines += _portable_section(legal) if amd_rows else []
    lines += _nv_portable_section(legal)
    lines += _mode_diff_section(table) if amd_rows else []
    lines += _nv_mode_diff_section(table)
    lines += _arch_diff_section(table)
    lines += _presence_x1_section(legal) if amd_rows else []
    lines += _claims_section(table, mismatches, cl) if cl else []
    # per-atom tables
    for v in sorted({r.version for r in legal}):
        by_atom: dict[str, list[Row]] = defaultdict(list)
        for r in legal:
            if r.version == v:
                by_atom[r.atom].append(r)
        suite_head = (" | ".join(f"omp_vv {TC_NAME[tc]}"
                                 for tc in MI300A) + " | "
                      if show_suite else "")
        lines += [f"## {_spec(v)}: legal programs, one row per atom",
                  "",
                  COPY_MARK_TEXT + " " + DAGGER_TEXT]
        if show_suite:
            lines += ["omp_vv columns (second source, unaudited): narrow "
                      "omp_vv tests that use the atom (at most one base "
                      "clause), passes / fails by exit code, each test read "
                      "at HSA_XNACK=1 or, when its result depends on copy "
                      "semantics, at HSA_XNACK=0; blank when no narrow test "
                      "uses the atom."]
        nv_head = "".join(f"{TC_NAME[t]} portable ("
                          + " and ".join(nv_mode_name(t, x) for x in nv_modes(t)) + ") | "
                          for t in NV)
        lines += ["",
                  f"| atom | evidence | audit | {_head_modes()} | "
                  f"{suite_head}portable ({PORTABLE_HEAD()}) | {nv_head}"
                  "citation |",
                  "|---|---|---|" + "---|" * len(columns())
                  + ("---|" * len(MI300A) if show_suite else "")
                  + "---|" * len(NV) + "---|---|"]
        for atom in sorted(by_atom):
            rows = by_atom[atom]
            if len({r.program_id for r in rows}) > 1:
                raise ValueError(f"several legal programs for {atom} at {v}")
            r0 = rows[0]
            cite, link = atom_citation(atom, v)
            basis = (f"; basis: {_md(r0.basis.split(': ', 1)[0])}"
                     if r0.basis else "")
            suite_cells = (" | ".join(_suite_text(suite, atom, tc)
                                      for tc in MI300A) + " | "
                           if show_suite else "")
            lines.append(
                f"| `{atom.removeprefix(model + '.')}` | {r0.evidence} | "
                f"{AUDIT_TEXT.get(r0.audit, r0.audit)} | "
                + " | ".join(_mode_cells(rows, host)) + " | "
                + suite_cells + _portable_cell(rows) + " | "
                + "".join(_nv_portable_cell(rows, t) + " | " for t in NV)
                + f"[{_md(cite)}]({link}){basis} |")
        lines.append("")
    lines += _no_oracle_section(legal)
    lines += _hostdev_section(hostdev, model, host)
    lines += _out_of_scope_section(table, model)
    # illegal detail
    lines += ["## Illegal variants: one row per rule", "",
              "Each program violates exactly one rule. Cells say only whether "
              "the compiler rejected it. " + DAGGER_TEXT,
              "",
              f"| version | rule | primary atom | {_head_modes()} | rule citation |",
              "|---|---|---|" + "---|" * len(columns()) + "---|"]
    by_prog: dict[str, list[Row]] = defaultdict(list)
    for r in illegal:
        by_prog[r.program_id].append(r)
    for pid in sorted(by_prog, key=lambda p: (by_prog[p][0].version,
                                              by_prog[p][0].violates or "")):
        rows = by_prog[pid]
        r0 = rows[0]
        cite, link = rule_citation(r0.violates)
        lines.append(f"| {_vstr(r0.version)} | {r0.violates} | "
                     f"`{r0.atom.removeprefix(model + '.')}` | "
                     + " | ".join(_mode_cells(rows, host))
                     + f" | [{_md(cite)}]({link}) |")
    lines.append("")
    # failure details
    bad = [r for r in legal if family(r.label) not in (
        "correct on device", "correct on device (copy-mode evidence, HSA_XNACK=1)",
        NV_COPY_EVIDENCE_FAMILY,
        "accepted; conforms vacuously (no oracle)",
        "implementation-defined (no oracle)",
        "equivalent to the default (no oracle)",
        "accepted; oracle is the illegal variant", "accepted; unverified",
        "unobservable")]
    lines += ["## Failure details (legal programs)", "",
              "Every legal cell that is not a pass or an unseparable "
              "acceptance, with its gate status ('-' for a cell "
              "that is no failure) and the harness reason (clipped). "
              "Copy-mode "
              "(X=0) rows exist only for programs run in copy mode.", "",
              "| version | program | toolchain | X | report | gate | reason |",
              "|---|---|---|---|---|---|---|"]
    for r in bad:
        lines.append(f"| {_vstr(r.version)} | {r.program_id} | "
                     f"{TC_NAME.get(r.toolchain, r.toolchain)} | {r.xnack} | "
                     f"{_md(r.label)} | {r.gate or '-'} | "
                     f"{_md(_clip(r.reason))} |")
    lines.append("")
    conf = [r for r in legal if r.confound]
    lines += ["## Confounded rejections", "",
              "**Not counted** (against the atom or in the claims): the "
              "compiler rejected another feature the program needs (a listed "
              "message), or its diagnostic is at an "
              + ("OpenACC" if acc else "OpenMP") + " directive line "
              "that does not carry the atom. **Counted with a caveat (‡)**: "
              "the rejection is the atom's own but needs context (a listed "
              "caveat), or the compiler points at a statement that uses a "
              "variable, not at the clause. Excluded cells are generator "
              "follow-ups.", ""]
    if conf:
        lines += ["| version | program | toolchain | X | counted | why |",
                  "|---|---|---|---|---|---|"]
        lines += [f"| {_vstr(r.version)} | {r.program_id} | "
                  f"{TC_NAME.get(r.toolchain, r.toolchain)} | {r.xnack} | "
                  f"{'no' if r.excluded else 'yes ‡'} | "
                  f"{_md(r.confound)} |" for r in conf]
    else:
        lines.append("None.")
    lines.append("")
    lines += _provisional_section(table)
    if not acc:  # the omp_vv corpus baseline is OpenMP
        lines += _baseline_section(baseline or [], meta, c_lang)
    return "\n".join(lines) + "\n"


def PORTABLE_HEAD() -> str:
    """What the portable column requires (the gfx90a cell too)."""
    return "X0, X1 and gfx90a" if G90 else "X0 and X1"


def _portable_cell(rows: list[Row]) -> str:
    """The toolchains whose headline cell is portable (correct in both
    modes), then 'X1 only: ...' for those correct at HSA_XNACK=1 only."""
    head = [r for r in rows if r.xnack == HEADLINE]
    order = {t: i for i, t in enumerate(TOOLCHAINS)}
    head.sort(key=lambda r: order.get(r.toolchain, 9))

    def names(v):
        return ", ".join(TC_NAME.get(r.toolchain, r.toolchain)
                         + (f" ({r.mode_class})" if r.mode_class and
                            v != "portable" else "")
                         for r in head if r.portable == v)
    parts = [names("portable") or "none"]
    if names("x1_only"):
        parts.append(f"X1 only: {names('x1_only')}")
    if names("x0_only"):
        parts.append(f"X0 only: {names('x0_only')}")
    if names("x0_not_run"):
        parts.append(f"no X0 run: {names('x0_not_run')}")
    if names("gfx942_only"):  
        parts.append(f"MI300A only: {names('gfx942_only')}")
    return "; ".join(parts)


def _nv_portable_cell(rows: list[Row], tc: str) -> str:
    """An NVIDIA toolchain's portable verdict (its headline row),
    with the mode class when the modes differ."""
    head = [r for r in rows if r.toolchain == tc
            and r.xnack == nv_modes(tc)[0]]
    if not head:
        return NOT_RUN
    r = head[0]
    return r.portable + (f" ({r.mode_class})" if r.mode_class else "")


def _nv_portable_section(legal: list[Row]) -> list[str]:
    """Per version, an NVIDIA toolchain's headline cells by
    portable verdict (correct in separate and in managed memory)."""
    if not NV:
        return []
    out = ["## Portable verdict, NVIDIA (separate and managed memory)", "",
           ", ".join(TC_NAME[t] for t in NV)
           + " on an NVIDIA A100 (wingtip, sm_80): the headline "
           "mode is separate memory (-gpu=mem:separate, the compiler's "
           "default: separate host and device copies, the discrete-GPU "
           "mode); managed memory (-gpu=mem:managed) puts dynamically "
           "allocated data in CUDA managed memory. Unified memory "
           "(-gpu=mem:unified) is not applicable on this machine (no HMM: "
           "the runtime refuses to start). Portable = correct in both "
           "modes. Per toolchain, the legal programs' verdicts: "
           + "; ".join(f"**{k}**: {v}" for k, v in NV_PORTABLE.items())
           + ".", ""]
    head = [r for r in legal if r.toolchain in NV
            and r.xnack == nv_modes(r.toolchain)[0]]
    for v in sorted({r.version for r in head}):
        rs = [r for r in head if r.version == v]
        c = Counter((r.portable, r.toolchain) for r in rs)
        out += [f"### {_spec(v)}", "",
                "| verdict | " + " | ".join(TC_NAME[t] for t in NV)
                + " |", "|---|" + "---|" * len(NV)]
        for k in NV_PORTABLE:
            if any(c[(k, t)] for t in NV):
                out.append(f"| {k} | " + " | ".join(
                    str(c[(k, t)]) for t in NV) + " |")
        out.append("")
    return out


def _nv_mode_diff_section(table: list[Row]) -> list[str]:
    """Every legal NVIDIA headline cell whose separate and
    managed cells differ, with the class of the difference."""
    if not NV:
        return []
    rows = [r for r in table if r.legal and r.mode_class
            and r.toolchain in NV]
    cells = {(r.program_id, r.toolchain, r.xnack): r for r in table}
    out = ["## Memory-mode differences, NVIDIA (separate versus managed)",
           "",
           "Legal programs whose NVHPC outcome differs between separate and "
           "managed memory, with the class of the difference "
           "(catalog/mode_differences.yaml nvhpc_entries): "
           + "; ".join(f"**{k}**: {v}" for k, v in NV_MODE_CLASSES.items())
           + "; **unclassified**: no entry yet.", ""]
    if not rows:
        return out + ["None.", ""]
    c = Counter((r.mode_class, r.toolchain) for r in rows)
    out += ["| class | " + " | ".join(TC_NAME[t] for t in NV) + " |",
            "|---|" + "---|" * len(NV)]
    for k in list(NV_MODE_CLASSES) + ["unclassified"]:
        if any(c[(k, t)] for t in NV):
            out.append(f"| {k} | " + " | ".join(str(c[(k, t)]) for t in NV)
                       + " |")
    out += ["", "| version | program | toolchain | separate | managed | "
            "class | finding / why |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        e = nv_mode_entry(r.program_id, r.toolchain) or {}
        m = cells.get((r.program_id, r.toolchain, nv_modes(r.toolchain)[1]))
        why = (f"data/findings/{e['finding']}; " if e.get("finding")
               else "") + " ".join(str(e.get("why", "")).split())
        out.append(f"| {_vstr(r.version)} | {r.program_id} | "
                   f"{TC_NAME.get(r.toolchain, r.toolchain)} | "
                   f"{_md(r.label)} | {_md(m.label if m else '')} | "
                   f"{r.mode_class} | {_md(_clip(why, 300))} |")
    return out + [""]


def _portable_section(legal: list[Row]) -> list[str]:
    """Per version, the headline cells by portable verdict and
    toolchain."""
    out = ["## Portable verdict (correct at HSA_XNACK=0 and 1"
           + (" and on gfx90a)" if G90 else ")"), "",
           "The result a user can rely on for portable code (a discrete GPU "
           "has separate host and device memory) is **correct in both "
           "memory modes**: at HSA_XNACK=1 (unified memory) a missing or "
           "wrong map often still gives the right answer, so a mapping "
           "error shows only at HSA_XNACK=0. "
           + ("**and on the discrete GPU**, Tioga's MI250X "
              "(gfx90a, HSA_XNACK=0, separate HBM): portable = correct on "
              "MI300A at HSA_XNACK=1, at HSA_XNACK=0 and on gfx90a. "
              if G90 else "")
           + "Per toolchain, the legal "
           "programs' verdicts: "
           + "; ".join(f"**{k}**: {v}" for k, v in PORTABLE.items())
           + ".", ""]
    head = [r for r in legal if r.xnack == HEADLINE]
    for v in sorted({r.version for r in head}):
        rs = [r for r in head if r.version == v]
        c = Counter((r.portable, r.toolchain) for r in rs)
        out += [f"### {_spec(v)}", "",
                "| verdict | " + " | ".join(TC_NAME[t] for t in TOOLCHAINS)
                + " |", "|---|" + "---|" * len(TOOLCHAINS)]
        for k in PORTABLE:
            if any(c[(k, t)] for t in TOOLCHAINS):
                out.append(f"| {k} | " + " | ".join(
                    str(c[(k, t)]) for t in TOOLCHAINS) + " |")
        out.append("")
    return out


def _mode_diff_section(table: list[Row]) -> list[str]:
    """Every legal headline cell whose two modes differ, with the
    class of the difference (catalog/mode_differences.yaml)."""
    rows = [r for r in table if r.legal and r.mode_class
            and r.toolchain not in NV]
    copy = {(r.program_id, r.toolchain): r for r in table
            if r.xnack == COPY}
    c = Counter((r.mode_class, r.toolchain) for r in rows)
    out = ["## Memory-mode differences", "",
           "Legal programs (device and host+device) whose outcome differs "
           "between HSA_XNACK=1 and HSA_XNACK=0 on a toolchain, with the "
           "class of the difference (catalog/mode_differences.yaml): "
           + "; ".join(f"**{k}**: {v}" for k, v in MODE_CLASSES.items())
           + "; **unclassified**: no entry yet.", ""]
    if not rows:
        return out + ["None.", ""]
    out += ["| class | " + " | ".join(TC_NAME[t] for t in TOOLCHAINS)
            + " |", "|---|" + "---|" * len(TOOLCHAINS)]
    for k in list(MODE_CLASSES) + ["unclassified"]:
        if any(c[(k, t)] for t in TOOLCHAINS):
            out.append(f"| {k} | " + " | ".join(str(c[(k, t)])
                                               for t in TOOLCHAINS) + " |")
    out += ["", "| version | program | toolchain | X=1 | X=0 | class | "
            "finding / why |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        e = mode_entry(r.program_id, r.toolchain) or {}
        x0 = copy.get((r.program_id, r.toolchain))
        why = (f"data/findings/{e['finding']}; " if e.get("finding")
               else "") + " ".join(str(e.get("why", "")).split())
        out.append(f"| {_vstr(r.version)} | {r.program_id} | "
                   f"{TC_NAME.get(r.toolchain, r.toolchain)} | "
                   f"{_md(r.label)} | {_md(x0.label if x0 else '')} | "
                   f"{r.mode_class} | {_md(_clip(why, 300))} |")
    return out + [""]


def _arch_diff_section(table: list[Row]) -> list[str]:
    """Every legal headline cell whose MI300A copy-mode cell and
    gfx90a cell differ, with the class of the difference."""
    if not G90:
        return []
    rows = [r for r in table if r.legal and r.arch_class]
    cells = {(r.program_id, r.toolchain, r.xnack): r for r in table}
    pairs = [r for r in table if r.legal and r.xnack == HEADLINE
             and (r.program_id, g90_of(r.toolchain), COPY) in cells
             and (r.program_id, r.toolchain, COPY) in cells]
    out = ["## gfx90a (MI250X) versus gfx942 (MI300A) copy mode", "",
           "Both run with separate host and device memory (HSA_XNACK=0); "
           "the MI250X is a discrete GPU (its own HBM), the MI300A an APU "
           "whose copy mode emulates one. Legal programs (device and "
           "host+device) whose gfx90a outcome differs from the MI300A "
           f"copy-mode outcome: {len(rows)} of {len(pairs)} compared "
           "cells, with the class of the difference "
           "(catalog/mode_differences.yaml, arch_entries): "
           + "; ".join(f"**{k}**: {v}" for k, v in ARCH_CLASSES.items())
           + "; **unclassified**: no entry yet.", ""]
    if not rows:
        return out + ["None.", ""]
    c = Counter((r.arch_class, r.toolchain) for r in rows)
    out += ["| class | " + " | ".join(TC_NAME[t] for t in TOOLCHAINS)
            + " |", "|---|" + "---|" * len(TOOLCHAINS)]
    for k in list(ARCH_CLASSES) + ["unclassified"]:
        if any(c[(k, t)] for t in TOOLCHAINS):
            out.append(f"| {k} | " + " | ".join(str(c[(k, t)])
                                               for t in TOOLCHAINS) + " |")
    out += ["", "| version | program | toolchain | MI300A X=1 | MI300A X=0 "
            "| gfx90a | class | finding / why |",
            "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        e = arch_entry(r.program_id, r.toolchain) or {}
        x0 = cells.get((r.program_id, r.toolchain, COPY))
        g = cells.get((r.program_id, g90_of(r.toolchain), COPY))
        why = (f"data/findings/{e['finding']}; " if e.get("finding")
               else "") + " ".join(str(e.get("why", "")).split())
        out.append(f"| {_vstr(r.version)} | {r.program_id} | "
                   f"{TC_NAME.get(r.toolchain, r.toolchain)} | "
                   f"{_md(r.label)} | {_md(x0.label if x0 else '')} | "
                   f"{_md(g.label if g else '')} | {r.arch_class} | "
                   f"{_md(_clip(why, 300))} |")
    return out + [""]


def _presence_x1_section(legal: list[Row]) -> list[str]:
    """Fix: the copy-mode programs whose presence checks were run
    at HSA_XNACK=1 too, and the cells where they fail there."""
    rs = [r for r in legal if r.xnack == HEADLINE and r.presence_x1]
    out = ["## Presence checks at HSA_XNACK=1", "",
           "A copy_mode_only program skips its checks under unified memory, "
           "so its HSA_XNACK=1 cell is no evidence. Presence "
           "(omp_target_is_present) is defined in both modes, so "
           "tools/campaigns/presence_x1.py ran each program with only its presence "
           "checks unguarded at HSA_XNACK=1 (tests/data/"
           "presence_x1_summary.json). A failure there makes the cell not "
           "portable (the portable verdict counts it as an HSA_XNACK=1 "
           "failure).", ""]
    if not rs:
        return out + ["None.", ""]
    c = Counter((r.toolchain, r.presence_x1) for r in rs)
    outs = sorted({r.presence_x1 for r in rs})
    out += ["| outcome | " + " | ".join(TC_NAME[t] for t in TOOLCHAINS)
            + " |", "|---|" + "---|" * len(TOOLCHAINS)]
    out += [f"| {o} | " + " | ".join(str(c[(t, o)]) for t in TOOLCHAINS)
            + " |" for o in outs]
    bad = [r for r in rs if r.presence_x1 == "wrong_answer"
           and r.evidence == "copy_mode_only"]
    out += ["", "Cells whose HSA_XNACK=1 'correct (copy-mode evidence)' "
            "hides a failing presence check: "
            + (", ".join(f"{r.program_id} ({TC_NAME.get(r.toolchain, r.toolchain)})"
                         for r in bad) or "none") + ".", ""]
    return out


def _hostdev_section(rows: list[Row], model: str, host=None) -> list[str]:
    """The host+device pattern programs, one row per program,
    apart from the headline per-atom tables."""
    out = ["## Host+device patterns (not headline results)", "",
           "Host constructs that feed a "
           + ("compute" if model == "acc" else "target") + " region the way "
           "codes use them (an exception to the device-offload scope), one program per "
           "pattern (id ending in -hostdev). Each is judged on its device "
           "result (the check and ran_on_host of the device region); it is "
           "not the atom's oracle (no mutation audit) and never counts as "
           "the atom's support. The atom's headline is its device-only "
           "program in the tables above.", ""]
    if not rows:
        return out + ["None.", ""]
    out += [f"| version | atom | program | realistic use | {_head_modes()} |",
            "|---|---|---|---|" + "---|" * len(columns())]
    by: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by[r.program_id].append(r)
    for pid in sorted(by, key=lambda p: (by[p][0].version, p)):
        rs = by[pid]
        r0 = rs[0]
        out.append(f"| {_vstr(r0.version)} | "
                   f"`{r0.atom.removeprefix(model + '.')}` | {pid} | "
                   f"{_md(r0.use)} | " + " | ".join(_mode_cells(rs, host))
                   + " |")
    return out + [""]


def _out_of_scope_section(table: list[Row], model: str) -> list[str]:
    """The atoms removed from the slice as host tests
    (catalog/<model>/out_of_scope.yaml), with the reason and the spec
    sentence."""
    from offload.engine.catalog import out_of_scope_atoms
    lang = table_lang(table) if table else "f90"
    out = ["## Out of scope (host execution)", "",
           "Atoms whose construct of interest runs only on the host, or "
           "whose effect never reaches a "
           + ("compute" if model == "acc" else "target") + " region: not "
           "device offload, so they have no program, no cell and no "
           f"verdict here (catalog/{model}/out_of_scope.yaml; each sentence "
           "is checked against the spec text).", "",
           "| version | atom | reason | spec |", "|---|---|---|---|"]
    n = 0
    for v in sorted({r.version for r in table}):
        for atom, e in sorted(out_of_scope_atoms(v, lang).items()):
            sp = e["spec"].get(v) or {}
            out.append(f"| {_vstr(v)} | `{atom.removeprefix(model + '.')}` "
                       f"| {_md(' '.join(e['reason'].split()))} | "
                       f"{_md(sp.get('cite', ''))}: \"{_md(sp.get('quote', ''))}\" |")
            n += 1
    if not n:
        out.append("| - | none | - | - |")
    return out + [""]


def _no_oracle_section(legal: list[Row]) -> list[str]:
    """One row per (version, atom) whose program has no separating oracle
, with the spec sentence that makes it so."""
    seen: dict[tuple, Row] = {}
    for r in legal:
        if r.evidence in NO_ORACLE_TEXT:
            seen.setdefault((r.version, r.atom), r)
    model = table_model(legal)
    out = ["## Atoms without a separating oracle", "",
           "No single run can tell these forms from their absence, and the "
           f"spec says why (catalog/{model}/no_oracle.yaml; every sentence is "
           "checked against the spec text). Their cells read as the "
           "category, never as support; a rejection or a wrong answer keeps "
           "its outcome.", "",
           "| version | atom | category | spec basis |", "|---|---|---|---|"]
    for (v, atom), r in sorted(seen.items()):
        out.append(f"| {_vstr(v)} | `{atom.removeprefix(model + '.')}` | "
                   f"{NO_ORACLE_TEXT[r.evidence]} | {_md(r.basis)} |")
    if not seen:
        out.append("| - | none | - | - |")
    return out + [""]


def read_baseline(path: Path) -> list[dict]:
    p = Path(path)
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text().splitlines()
            if line.strip()]


def _is_g90_run(rr: dict) -> bool:
    """A recorded run of gfx90a toolchains only."""
    tcs = rr.get("toolchains") or []
    return bool(tcs) and all(arch_of(t) == "gfx90a" for t in tcs)


def _twin_machine(rr: dict) -> str | None:
    """The machine of a recorded run of twins of one machine other than Tioga
    (MI300X, MI350X) only, else None."""
    reg = _reg()
    tcs = [reg.toolchains.get(t) for t in rr.get("toolchains") or []]
    ms = {t.machine for t in tcs if t and t.twin_of and reg.twin_tag(t.name) != "gfx90a"}
    return ms.pop() if tcs and len(ms) == 1 and all(
        t and t.twin_of and t.machine in ms for t in tcs) else None


def _is_nv_run(rr: dict) -> bool:
    """A recorded run of NVIDIA toolchains only: kept apart
    from the AMD modes' runs."""
    tcs = rr.get("toolchains") or []
    return bool(tcs) and all(t in NVIDIA_TOOLCHAINS for t in tcs)


def read_meta(results: Path) -> dict:
    """Run metadata per memory mode from <results>.xnack{0,1}.jsonl.meta.json
    and the ROCm versions recorded with CCE results."""
    meta: dict = {}
    results = Path(results)
    for x in MODES:
        p = results.with_name(f"{results.stem}.xnack{x}.jsonl.meta.json")
        if p.is_file():
            meta[x] = json.loads(p.read_text())
        stem = "baseline_c" if results.stem.endswith("_c") else "baseline"
        b = results.with_name(f"{stem}.xnack{x}.jsonl.meta.json")
        if b.is_file():
            meta[f"baseline{x}"] = json.loads(b.read_text())
    # reruns written straight into the merged matrix (run_matrix.py rerun
    # --out results/matrix.jsonl) are recorded in its own meta file; each
    # joins its mode's reruns once, in start order
    merged = results.with_name(f"{results.name}.meta.json")
    if merged.is_file():
        for rr in json.loads(merged.read_text()).get("reruns", []):
            x = rr.get("xnack")
            if _is_nv_run(rr):  # Wingtip rows, not an AMD mode's
                meta.setdefault("nvhpc", {}).setdefault("reruns", []).append(
                    rr)
                continue
            if _twin_machine(rr):  # MI300X, MI350X rows, not a mode's
                meta.setdefault("twins", {}).setdefault(_twin_machine(rr), []).append(rr)
                continue
            if x not in MODES:
                continue
            if _is_g90_run(rr):  # Tioga rows, not a mode's
                meta.setdefault("g90", {}).setdefault("reruns", []).append(
                    rr)
                continue
            m = meta.setdefault(x, {})
            have = m.setdefault("reruns", [])
            if any(h.get("started") == rr.get("started") and
                   h.get("host") == rr.get("host") for h in have):
                continue
            have.append(rr)
            have.sort(key=lambda r: r.get("started") or "")
    # Baseline rows replaced in the merged baseline file
    # (run_matrix.py replace --baseline) are recorded in its meta file
    stem = "baseline_c" if results.stem.endswith("_c") else "baseline"
    bmerged = results.with_name(f"{stem}.jsonl.meta.json")
    if bmerged.is_file():
        for rr in json.loads(bmerged.read_text()).get("reruns", []):
            x = rr.get("xnack")
            if _is_nv_run(rr):  
                meta.setdefault("baseline_nvhpc", {}).setdefault(
                    "reruns", []).append(rr)
                continue
            if x not in MODES:
                continue
            if _is_g90_run(rr):
                meta.setdefault("baseline_g90", {}).setdefault(
                    "reruns", []).append(rr)
                continue
            have = meta.setdefault(f"baseline{x}", {}).setdefault(
                "reruns", [])
            if not any(h.get("started") == rr.get("started") and
                       h.get("host") == rr.get("host") for h in have):
                have.append(rr)
    if results.is_file():
        meta["rocm"] = sorted({json.loads(line).get("rocm") or ""
                               for line in results.read_text().splitlines()
                               if line.strip()} - {""})
    return meta


def write_report(results: Path = MATRIX, claims: Path = CLAIMS,
                 audit: Path = AUDIT, baseline: Path = BASELINE,
                 out_md: Path | None = None, out_csv: Path | None = None
                 ) -> tuple[list[Row], list[Mismatch]]:
    """Build the table of `results` and write its Markdown and CSV (C
    results, results/matrix_c.jsonl with C_AUDIT and
    C_BASELINE)."""
    results = Path(results)
    # A changed canary of the campaign stops the report
    from offload.engine import canary
    canary.require_unchanged(
        canary.files_for(results), str(results.name),
        campaign_rows=[json.loads(x) for x in results.read_text()
                       .splitlines() if x.strip()]
        if results.is_file() else None)
    out_md = out_md or results.with_name("support_table.md")
    out_csv = out_csv or results.with_name("support_table.csv")
    table = build_table(results, audit=audit)
    bad = sorted({(r.program_id, r.toolchain) for r in table
                  if r.mode_class == "unclassified"})
    if bad:
        raise ValueError(f"unclassified memory-mode differences (add them "
                         f"to {MODE_DIFF_FILE.name}; NVIDIA: nvhpc_entries)"
                         f": {bad}")
    bad = sorted({f"{r.program_id} {r.toolchain}: {why}" for r in table
                  if r.mode_class and r.mode_class != "unclassified" and
                  (why := (nv_mode_class_problem if r.toolchain in NV else
                           mode_class_problem)(r.mode_class, r.label,
                                               r.copy_label))})
    if bad:
        raise ValueError(f"memory-mode classes the cells contradict "
                         f"(fix {MODE_DIFF_FILE.name}): {bad}")
    bad = sorted({(r.program_id, r.toolchain) for r in table
                  if r.arch_class == "unclassified"})
    if bad:
        raise ValueError(f"unclassified gfx90a versus gfx942 differences "
                         f"(add them to {MODE_DIFF_FILE.name} "
                         f"arch_entries): {bad}")
    mism = compare_claims(table, claims)
    base = read_baseline(baseline)
    meta = read_meta(results)
    from offload.engine.ompvv import suite_verdicts
    suite = suite_verdicts(base, {r.atom for r in table})
    md = render_markdown(table, mism, claims=claims, baseline=base,
                         meta=meta, suite=suite)
    comp = companion_section(results)
    if comp:
        md = md.rstrip("\n") + "\n\n" + "\n".join(comp)
    Path(out_md).write_text(md)
    Path(out_csv).write_text(render_csv(table, suite=suite, meta=meta))
    return table, mism
