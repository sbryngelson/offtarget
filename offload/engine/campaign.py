"""The campaign interface: what a campaign of generated programs declares, and
the generic steps that take it through gen, prerun, witness, legality, run,
gate, confirm, report and a findings plan. The steps call the existing
machinery (offload.engine.harness, gate, prerun, confirm).

A campaign is one module that defines a ``Campaign`` subclass and one entry
in ``MODULES`` (docs/tooling/contributing.md, "Add a campaign"). It declares its
programs (``programs(seed, n, **opts)``, deterministic, each a frozen object
with ``id``, ``lang``, ``model``, ``version``, ``source``, ``expected``,
``legality``, ``why``, ``cites`` and ``harness()``), its labels (``defined``,
``unspecified``, ``illegal``, ``pending``; only ``gated(p)`` programs are
gated and confirmed), its gate kind, the cell identity (``cell``) and its
``Capabilities``. Only the runner (``HarnessRunner``) compiles or runs
anything; the other steps read and write results/<name>/<run>/.
"""
from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import os
import re
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS = ROOT / "results"

# --- JSONL files with per-writer parts ------------------------------------------------


def _parts(path: Path) -> list[Path]:
    """`path` and its per-writer parts (``<stem>.part.<node>.<pid>.jsonl``),
    oldest first: a retry reads after the row it replaces."""
    return ([path] if path.is_file() else []) + sorted(
        path.parent.glob(f"{path.stem}.part.*{path.suffix}"),
        key=lambda p: (p.stat().st_mtime_ns, p.name))


def read_jsonl(path: Path) -> list[dict]:
    """The rows of a JSONL file and its parts; a line that does not parse
    (an interrupted write) is skipped, so its work is redone."""
    out = []
    for p in _parts(Path(path)):
        for ln in p.read_text().splitlines():
            if ln.strip():
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
    return out


_LOCK = threading.Lock()


def append_jsonl(path: Path, rows: list[dict]) -> None:
    """Append to this process's own part of `path` (appends from two nodes
    to one file interleave on a network file system)."""
    path = Path(path)
    part = path.parent / (f"{path.stem}.part.{os.uname().nodename}."
                          f"{os.getpid()}{path.suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, open(part, "a") as fh:
        fh.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# --- capabilities: what the catalog lets a campaign express ---------------------------


def mode_name(row_key: int) -> str:
    """The campaigns' name of a memory mode by its stored row key:
    ``copy`` for the copy mode, ``unified`` for unified and (NVHPC) managed
    memory, which the campaigns treat as one mode (catalog/machines.yaml)."""
    from offload.engine.confirm import machines as M
    for m in M.load().values():
        for mode in m.modes:
            if m.row_key(mode) == row_key:
                return "copy" if mode == "copy" else "unified"
    raise KeyError(f"no memory mode has row key {row_key}")


@dataclass(frozen=True)
class Capabilities:
    """What a campaign expresses, and where it is measured. ``families``
    maps a machine (catalog/machines.yaml) to the compiler family ids
    (catalog/toolchains.yaml ``families``) measured there, or ``None`` for
    every family with a toolchain on that machine; ``regression`` includes
    the releases measured only against another (``regression_of``). The
    toolchains and row keys are computed from the catalog, in its order."""
    langs: tuple[str, ...]            # "c", "f90"
    models: tuple[str, ...]           # "omp", "acc"
    families: dict = field(default_factory=dict)   # machine -> families | None
    regression: bool = False
    draw_options: tuple[str, ...] = ()  # the keyword options of programs()

    def machines(self) -> tuple[str, ...]:
        from offload.engine.confirm import machines as M
        return tuple(m for m in M.load() if m in self.families)

    def toolchains(self, machine: str) -> tuple[str, ...]:
        from offload.engine.toolchains import registry
        fams = self.families.get(machine)
        out = []
        for name, tc in registry().toolchains.items():
            if tc.machine != machine:
                continue
            if tc.regression_of is not None and not self.regression:
                continue
            if fams is not None and tc.family_id not in fams:
                continue
            if not any(tc.family.why_unsupported(m, l) is None
                       for m in self.models for l in self.langs):
                continue
            out.append(name)
        return tuple(out)

    def modes(self, machine: str) -> tuple[int, ...]:
        """The stored row keys of the machine's memory modes, ascending."""
        from offload.engine.confirm import machines as M
        m = M.load()[machine]
        return tuple(sorted(m.row_key(x) for x in m.modes))

    def targets(self) -> dict[str, tuple[list[str], list[int]]]:
        """machine -> (toolchains, row keys): the campaign drivers' TARGETS."""
        return {m: (list(self.toolchains(m)), list(self.modes(m)))
                for m in self.machines()}

    def check(self) -> list[str]:
        """Problems (empty when consistent): an unknown machine or family,
        a machine with no toolchain for the campaign."""
        from offload.engine.confirm import machines as M
        from offload.engine.toolchains import registry
        reg = registry()
        out = []
        for machine, fams in self.families.items():
            if machine not in M.load():
                out.append(f"machine {machine} is not in catalog/machines.yaml")
                continue
            for f in fams or ():
                if f not in reg.families:
                    out.append(f"family {f} is not in catalog/toolchains.yaml")
            if not self.toolchains(machine):
                out.append(f"no toolchain of {machine} compiles the campaign")
        for m in self.models:
            if m not in ("omp", "acc"):
                out.append(f"unknown model {m}")
        for l in self.langs:
            if l not in ("c", "f90"):
                out.append(f"unknown language {l}")
        return out


# --- the campaign -------------------------------------------------------------------

LABELS = ("defined", "unspecified", "illegal", "pending")
FAILING_OK = ("correct_on_device", "unobservable")
# a front end's rejection that names a feature it lacks is no legality
# verdict (the compiler does not implement it; it says nothing about the
# program): the messages the campaigns recorded (tools/campaigns/oop.py's list)
NOT_A_VERDICT = re.compile(
    r"not yet implemented|not supported|unimplemented feature|not allowed "
    r"on device|unrecognized openmp directive|nvvmcompileprogram|failed to "
    r"translate accelerator region|no device symbol|unsupported accelerator code"
    # a diagnostic whose subject is the default mapper CCE generates
    # (default$mapper$<type>$<module>): about the compiler's code, not the
    # program's (section 8)
    r"|ERROR default\$mapper\$\S*, File", re.I)


class Campaign:
    """The interface. A campaign module subclasses it, sets the class
    attributes and defines ``programs``; the other methods have defaults
    that read the program objects' fields."""
    name: str = ""                     # results/<name>/, the row's `campaign`
    kind: str = ""                     # the gate kind (default: name)
    prefix: str = ""                   # the gate's build-directory prefix (default: <kind>_)
    signature: str = "program"         # offload.engine.gate SIGNATURE_MODES
    labels: tuple = LABELS
    caps: Capabilities = Capabilities(("f90",), ("omp",))
    printed_values: bool = True        # the programs print `name= value` lines (VALUE_KINDS)
    compile_limit_s: int = 900         # the gate's compile limit (COMPILE_LIMIT_S)
    not_a_verdict: re.Pattern = NOT_A_VERDICT
    fe_timeout_s: int = 600            # one front-end check in prerun
    timeout_s: int = 120               # a run's default time limit
    opt: str = "-O2"
    doc: str = ""                      # where the campaign is written up
    hand_listed: bool = False          # programs() ignores the draw: gen writes no meta.json
    # a campaign of real code (hecbench): the programs of a run are read back from its
    # programs.jsonl (`programs_from_records`), so a machine without the draw's inputs runs
    # them; `src_name` names the file `gen` writes for a program
    stored_programs: bool = False
    # run names whose results nobody reads (a sealed half): report, cluster, confirm and
    # findings-plan refuse them (tools/campaign.py)
    sealed_runs: tuple = ()

    def make_runner(self):
        """The runner of the steps that compile or run (the harness's by default)."""
        return HarnessRunner(self)

    def src_name(self, p) -> str:
        return f"{p.id}.{self.ext(p)}"

    def programs_from_records(self, rows: list) -> list:
        raise NotImplementedError

    def gate_filter(self, items: list, rows: list) -> list:
        """The failing cells worth a gate run, given every row of the run (all machines'): a
        campaign whose evidence needs more than the gate (hecbench: a witness family) drops
        the cells that cannot become evidence."""
        return items

    def is_sealed(self, programs: list) -> bool:
        """Whether a run of these programs is a sealed set's (its results are read by its scorer
        only): by its content, never by its name. Default: no campaign has sealed runs."""
        return False

    def bind_run(self, run_dir, programs: list) -> None:
        """Attach what the run directory holds to its programs (hecbench: the
        pre-run's serial host reference)."""

    # -- programs --
    def programs(self, seed: int = 0, n: int = 0, **opts) -> list:
        raise NotImplementedError

    def expected(self, p) -> dict:
        return dict(p.expected)

    def legality(self, p) -> str:
        return p.legality

    def spec_rows(self, p) -> list:
        return [dict(r) if isinstance(r, dict) else dict(r) for r in p.cites]

    def record(self, p) -> dict:
        """The programs.jsonl row of a program (the generic layer adds
        ``sha``)."""
        return {"id": p.id, "lang": p.lang, "model": p.model,
                "version": p.version, "legality": self.legality(p),
                "why": p.why, "expected": self.expected(p),
                "cites": self.spec_rows(p), "title": getattr(p, "title", "")}

    def harness(self, p):
        return p.harness()

    def ext(self, p) -> str:
        return "c" if p.lang == "c" else "f90"

    def modes_of(self, p) -> tuple:
        """The memory modes (``copy``, ``unified``) the program's expected
        values hold in."""
        return tuple(getattr(p, "modes", ("copy", "unified")))

    def gated(self, p) -> bool:
        """Whether a failure of the program is a candidate finding (gated
        and confirmed) rather than an observation."""
        return self.legality(p) == "defined"

    def unknown_why(self, p) -> str:
        """The confirmer's reason for an ungated program's cell."""
        return f"{self.legality(p)}: {p.why}"[:300]

    def parse_observed(self, stdout: str) -> dict:
        return {m.group(1): int(m.group(2)) for m in
                re.finditer(r"^(\w+)= (-?\d+)\s*$", stdout or "", re.M)}

    # -- rows --
    def row_tags(self, p) -> dict:
        """What the campaign adds to every result row of the program."""
        return {"lang": p.lang, "model": p.model, "legality": self.legality(p)}

    def gate_tags(self, r: dict) -> dict:
        """What the campaign adds to a gate item made from result row `r`."""
        return {}

    # -- report --
    def short_id(self, p) -> str:
        return p.id

    def mark(self, p) -> str:
        """The matrix's label column: nothing for a defined program."""
        return {"defined": "", "pending": "P", "unspecified": "U",
                "illegal": "N"}.get(self.legality(p), "?")

    def facets(self, p) -> set:
        """The ``axis=value`` items a failure cluster's members may share
        (``clusters``); by default the program's family and variant."""
        return {f"{k}={getattr(p, k)}" for k in ("family", "variant")
                if getattr(p, k, None) is not None}

    # -- derived --
    @property
    def gate_kind(self) -> str:
        return self.kind or self.name

    @property
    def gate_prefix(self) -> str:
        return self.prefix or f"{self.gate_kind}_"

    def cell(self, pid: str, toolchain: str, xnack) -> str:
        return f"{self.gate_kind}|{pid}|{toolchain}|{xnack}"

    def check(self) -> list[str]:
        out = self.caps.check()
        if not self.name:
            out.append("no name")
        if not set(self.labels) <= set(LABELS):
            out.append(f"labels not among {LABELS}: {self.labels}")
        return out


# --- the registry ---------------------------------------------------------------------

# campaign name -> the module that defines and registers it (one line per
# campaign: the registry entry of docs/tooling/contributing.md, "Add a campaign")
MODULES: dict[str, str] = {
    "nested": "offload.engine.campaigns.nested",
    "oop": "offload.engine.campaigns.oop",
    "hecbench": "offload.engine.campaigns.hecbench",
}
_REGISTERED: dict[str, Campaign] = {}


def register(camp: Campaign) -> Campaign:
    """Register a campaign (a module does this at import): its gate kind
    is declared to offload.engine.gate (register_kind, VALUE_KINDS,
    COMPILE_LIMIT_S); its declarations are checked."""
    from offload.engine import gate as GT
    problems = camp.check()
    if problems:
        raise ValueError(f"campaign {camp.name or '?'}: " + "; ".join(problems))
    new_kind = camp.gate_kind not in GT.KINDS
    GT.register_kind(camp.gate_kind, camp.gate_prefix, camp.signature)
    if camp.printed_values and camp.gate_kind not in GT.VALUE_KINDS:
        GT.VALUE_KINDS = (*GT.VALUE_KINDS, camp.gate_kind)
    GT.COMPILE_LIMIT_S.setdefault(camp.gate_kind, camp.compile_limit_s)
    if new_kind:
        _ADDED_KINDS[camp.name] = camp.gate_kind
    old = _REGISTERED.get(camp.name)
    if old is not None and (type(old).__module__, type(old).__name__) != \
            (type(camp).__module__, type(camp).__name__):
        raise ValueError(f"campaign {camp.name} is registered twice "
                         f"({type(old).__module__} and {type(camp).__module__})")
    _REGISTERED[camp.name] = camp
    return camp


def get(name: str) -> Campaign:
    """The registered campaign `name` (its module imported on demand)."""
    if name not in _REGISTERED:
        mod = MODULES.get(name)
        if mod is None:
            raise KeyError(f"unknown campaign {name!r}: one of "
                           f"{', '.join(names())} (offload.engine.campaign.MODULES)")
        m = importlib.import_module(mod)
        if name not in _REGISTERED:        # imported before and unregistered since
            importlib.reload(m)
        if name not in _REGISTERED:
            raise KeyError(f"{mod} registers no campaign named {name!r}")
    return _REGISTERED[name]


def names() -> tuple[str, ...]:
    return tuple(dict.fromkeys([*MODULES, *_REGISTERED]))


def unregister(name: str) -> None:
    """Forget a campaign registered by a test, and the gate kind it added."""
    from offload.engine import gate as GT
    _REGISTERED.pop(name, None)
    if name not in _BUILTIN:
        MODULES.pop(name, None)
    kind = _ADDED_KINDS.pop(name, None)
    if kind is not None:
        GT.KINDS.pop(kind, None)
        GT.COMPILE_LIMIT_S.pop(kind, None)
        GT.VALUE_KINDS = tuple(k for k in GT.VALUE_KINDS if k != kind)


_BUILTIN = frozenset(MODULES)
_ADDED_KINDS: dict[str, str] = {}


# --- runners --------------------------------------------------------------------------


def _fe(ok, why: str, not_a_verdict: re.Pattern):
    """A front end's verdict: None (no verdict) when it rejected the program
    for a feature it lacks."""
    if ok is None:
        return None
    if ok:
        return True
    return None if not_a_verdict.search(why or "") else False


class HarnessRunner:
    """The real runner: offload.engine.prerun (the rules and AFAR's front end:
    a Tuolumne compute node), offload.engine.confirm.witness (the independent
    checker, on its machine inside the cap), offload.engine.harness.run_program
    (this node's toolchains) and offload.engine.gate_run.rerun_program (the
    gate's environments). Nothing here runs on a login node."""
    parallel = "process"      # prerun and run may fork

    def __init__(self, camp: Campaign):
        self.camp = camp

    def prerun(self, p) -> dict:
        from offload.engine import prerun
        r_ok, r_why = prerun.rules_witness(p)
        f_ok, f_why = prerun.frontend_witness(p, timeout_s=self.camp.fe_timeout_s)
        why = list(r_why) + [w for w in f_why if f_ok is not True]
        if r_ok is not None and f_ok is not None and r_ok != f_ok:
            why.append("witnesses disagree: legality review")
        return {"id": p.id, "ok": bool(r_ok and f_ok), "reasons": why,
                "rules": r_ok, "rules_why": r_why, "afar_fe": f_ok,
                "afar_why": f_why}

    def witness(self, p) -> dict:
        from offload.engine.confirm import witness as W
        sha = sha256(p.source)
        try:
            return W.check(p.id, p.source, p.lang, sha, model=p.model)
        except Exception as e:            # ssh or checker trouble: no verdict
            return {"program": p.id, "sha256": sha, "result": "error",
                    "message": f"{type(e).__name__}: {e}"[:300]}

    def _tc(self, toolchain: str, version: int, lang: str):
        from offload.engine import run_matrix
        from offload.engine.toolchains import TOOLCHAINS
        return run_matrix.for_version(TOOLCHAINS[toolchain], version, lang)

    def run(self, prog, toolchain: str, xnack: int, *, version: int,
            timeout_s: int, opt: str = "-O2") -> dict:
        from offload.engine import harness
        tc = self._tc(toolchain, version, prog.lang)
        r = harness.run_program(prog, tc, xnack, opt, timeout_s=timeout_s,
                                repeats=3)
        return dataclasses.asdict(r)

    def rerun(self, prog, toolchain: str, xnack: int, env: dict, *,
              version: int, timeout_s: int, opt: str = "-O2") -> dict:
        from offload.engine import gate_run as GR
        tc = self._tc(toolchain, version, prog.lang)
        rr = GR.rerun_program(prog, tc, xnack, env, opt, timeout_s=timeout_s,
                              compile_timeout_s=self.camp.compile_limit_s)
        if os.environ.get("COMPLIANT_RUN_SLOTS"):   # wingtip: (c) is another GPU
            rr["node"] = f"{rr.get('node', '')}:gpu" \
                f"{os.environ.get('CUDA_VISIBLE_DEVICES', 'all')}"
        return rr


# --- the generic steps over one campaign run -------------------------------------------

_META_KEYS = ("gate_budget_s",)      # meta.json keys that are not draw options


def _prerun_task(args):
    """A pre-run check in a worker process (the process pool pickles the
    arguments, not the campaign)."""
    camp_name, d, label, pid = args
    run = Run(get(camp_name), Path(d), label)
    p = run.programs({pid})[0]
    return run.camp.make_runner().prerun(p)


class Run:
    """One run of a campaign: its directory and the steps over it."""

    def __init__(self, camp: Campaign, d: Path, label: str = "",
                 cache: dict | None = None):
        self.camp = camp
        self.d = Path(d)
        self.label = label or str(self.d)
        self._cache = cache if cache is not None else {}

    @property
    def sealed(self) -> bool:
        """The run holds a sealed set's programs (``Campaign.is_sealed``), or carries a name in
        ``Campaign.sealed_runs``: no step logs a count of its failures or refusals."""
        if self.d.name in self.camp.sealed_runs:
            return True
        try:
            return self.camp.is_sealed(self.programs())
        except (OSError, ValueError):
            return False

    # -- programs --
    def meta(self) -> dict:
        try:
            return json.loads((self.d / "meta.json").read_text())
        except FileNotFoundError:
            return {}

    def draw(self, meta: dict, fresh: bool = False) -> list:
        if self.camp.stored_programs and not fresh:
            rows = read_jsonl(self.d / "programs.jsonl")
            if rows:
                return self.camp.programs_from_records(rows)
        opts ={k: meta[k] for k in self.camp.caps.draw_options if k in meta}
        return self.camp.programs(meta.get("seed", 0), meta.get("n", 0), **opts)

    def programs(self, ids=None) -> list:
        """The run's programs: the draw regenerated from meta.json and
        checked against programs.jsonl's hashes."""
        key = str(self.d)
        if key not in self._cache:
            ps = self.draw(self.meta())
            stored = {r["id"]: r["sha"] for r in
                      read_jsonl(self.d / "programs.jsonl")}
            for p in ps:
                sha = sha256(p.source)
                if stored.get(p.id, sha) != sha:
                    raise SystemExit(f"{p.id}: the generator changed since "
                                     f"`gen` (sha differs)")
            self.camp.bind_run(self.d, ps)
            self._cache[key] = ps
        return [p for p in self._cache[key] if not ids or p.id in ids]

    def gen(self, seed: int, n: int, **opts) -> int:
        """Draw the programs and write meta.json, programs.jsonl and src/."""
        bad = set(opts) - set(self.camp.caps.draw_options)
        if bad:
            raise ValueError(f"{self.camp.name}: unknown draw options "
                             f"{sorted(bad)} (declared: "
                             f"{self.camp.caps.draw_options})")
        (self.d / "src").mkdir(parents=True, exist_ok=True)
        meta = {"n": n, "seed": seed, **opts}
        if not self.camp.hand_listed:
            (self.d / "meta.json").write_text(json.dumps(meta))
        self._cache.pop(str(self.d), None)
        ps = self.draw(meta, fresh=True)       # a new draw, not the stored programs
        rows = []
        for p in ps:
            (self.d / "src" / self.camp.src_name(p)).write_text(p.source)
            rows.append({**self.camp.record(p), "sha": sha256(p.source)})
        (self.d / "programs.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
        return len(rows)

    # -- legality --
    def prerun(self, runner=None, workers: int = 8, log=print) -> dict:
        """offload.engine.prerun's two witnesses over every program (resumable);
        returns the rows by id."""
        from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, \
            as_completed
        out = self.d / "prerun.jsonl"
        done = {r["id"] for r in read_jsonl(out)}
        todo = [p for p in self.programs() if p.id not in done]
        if runner is None or getattr(runner, "parallel", "") == "process":
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futs = [pool.submit(_prerun_task, (self.camp.name, str(self.d),
                                                   self.label, p.id))
                        for p in todo]
                for f in as_completed(futs):
                    append_jsonl(out, [f.result()])
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for r in pool.map(runner.prerun, todo):
                    append_jsonl(out, [r])
        self._cache.pop(str(self.d), None)       # the programs bind the new rows (bind_run)
        rows = {r["id"]: r for r in read_jsonl(out)}
        if self.sealed:
            log("prerun done")                  # no count of refused programs for a sealed run
            return rows
        for r in rows.values():
            if not r["ok"]:
                log("refused", r["id"], "; ".join(r["reasons"])[:300])
        log(f"{len(rows)} checked, {sum(1 for r in rows.values() if not r['ok'])} refused")
        return rows

    def witness(self, runner=None, workers: int = 4, log=print) -> dict:
        """The independent checker's compile-only verdict per program
        (catalog/machines.yaml independent_checkers; over ssh inside the
        cap), at most 4 at once (the wingtip compile limit); resumable."""
        from concurrent.futures import ThreadPoolExecutor
        runner = runner or self.camp.make_runner()
        out = self.d / "witness.jsonl"
        done = {r["program"] for r in read_jsonl(out) if r.get("result") != "error"}
        todo = [p for p in self.programs() if p.id not in done]
        with ThreadPoolExecutor(max_workers=min(workers, 4)) as pool:
            for r in pool.map(runner.witness, todo):
                append_jsonl(out, [r])
                log(r["program"], r["result"], r.get("message", "")[:120])
        return {r["program"]: r for r in read_jsonl(out)}

    def legality_table(self) -> dict:
        """program id -> {rules, afar_fe, nvhpc_fe, cce_fe, legality,
        legal_for: {family: bool}, prerun, nvhpc_message}: a program is
        legal for a compiler family when the rules accept it, a front end
        of another family accepts it and none of another family rejects it
        with a diagnostic (a rejection that names a missing feature is no
        verdict). The front ends: the pre-run's (AFAR), the independent
        checker's (NVHPC, witness.jsonl) and CCE's (any CCE row that
        compiled). A family under test only (GCC) never witnesses."""
        from offload.engine.toolchains import registry
        reg = registry()
        nav = self.camp.not_a_verdict
        pre = {r["id"]: r for r in read_jsonl(self.d / "prerun.jsonl")}
        wit = {r["program"]: r for r in read_jsonl(self.d / "witness.jsonl")}
        cce: dict = {}
        for r in self.rows():
            tc = reg.toolchains.get(r["toolchain"])
            if tc is None or tc.family_id != "cce":
                continue
            # a link failure comes after the front end accepted it; a
            # diagnostic is a rejection unless it names a missing feature;
            # any compile wins
            reason = str(r.get("reason", ""))
            pid = r["program_id"]
            if r["outcome"] not in ("rejected", "harness_error") or \
                    reason.startswith("link_undefined"):
                cce[pid] = True
            elif r["outcome"] == "rejected" and reason.startswith("diagnostic") \
                    and not nav.search(reason) and cce.get(pid) is not True:
                cce[pid] = False
            else:
                cce.setdefault(pid, None)
        out = {}
        for p in self.programs():
            r = pre.get(p.id) or {}
            rules = r.get("rules")
            afar = _fe(r.get("afar_fe"), "; ".join(r.get("afar_why") or []), nav)
            w = wit.get(p.id, {})
            nv = _fe({"accept": True, "reject": False}.get(w.get("result")),
                     w.get("message", ""), nav)
            fe = {"afar": afar, "nvhpc": nv, "cce": cce.get(p.id)}
            legal_for = {}
            for fam in reg.families:
                others = [v for f, v in fe.items() if f != fam and v is not None]
                legal_for[fam] = bool(rules) and any(others) and all(others)
            out[p.id] = {"rules": rules, "afar_fe": afar, "nvhpc_fe": nv,
                         "cce_fe": cce.get(p.id), "legality": self.camp.legality(p),
                         "legal_for": legal_for,
                         "prerun": (r.get("rules_why", []) + r.get("afar_why", []))[:4],
                         "nvhpc_message": w.get("message", "")}
        return out

    def legality(self, log=print) -> dict:
        leg = self.legality_table()
        (self.d / "legality.json").write_text(json.dumps(leg, indent=1, sort_keys=True))
        n_all = sum(1 for r in leg.values() if all(r["legal_for"].values()))
        for pid, r in leg.items():
            if not all(r["legal_for"].values()) or r["legality"] != "defined":
                log(pid, r["legality"], "rules", r["rules"], "afar_fe", r["afar_fe"],
                    "nvhpc_fe", r["nvhpc_fe"], "|", r["nvhpc_message"][:100], "|",
                    "; ".join(r["prerun"])[:160])
        log(f"{len(leg)} programs; {n_all} legal for every family")
        return leg

    def prerun_ok(self) -> set:
        """The programs the rules accept (a front-end refusal is a
        measurement: the run shows which compilers reject them). Without a
        stored pre-run the rules witness runs here (pure Python)."""
        from offload.engine import prerun
        stored = {r["id"]: r.get("rules") for r in read_jsonl(self.d / "prerun.jsonl")}
        ok = set()
        for p in self.programs():
            v = stored.get(p.id)
            if v is None:
                v = prerun.rules_witness(p)[0]
            if v:
                ok.add(p.id)
        return ok

    # -- runs --
    def rows(self) -> list[dict]:
        """The run's rows, one per (program, toolchain, row key): the last
        written."""
        last = {}
        for r in read_jsonl(self.d / "rows.jsonl"):
            last[(r["program_id"], r["toolchain"], r["xnack"])] = r
        return list(last.values())

    def cells(self, progs, toolchains, modes, ok: set) -> list[tuple]:
        """(program, toolchain, row key) of the runs: a program the rules
        accept, on a toolchain whose family compiles its model and
        language (catalog/toolchains.yaml ``unsupported``), in a mode its
        expected values hold in."""
        from offload.engine.toolchains import TOOLCHAINS
        out = []
        for p in progs:
            if p.id not in ok:
                continue
            for t in toolchains:
                tc = TOOLCHAINS[t]
                if tc.family.why_unsupported(p.model, self.camp.ext(p)):
                    continue
                for x in modes:
                    if x in tc.xnack_modes and mode_name(x) in self.camp.modes_of(p):
                        out.append((p, t, x))
        return out

    def run_one(self, runner, p, t: str, x: int, timeout_s: int) -> dict:
        t0 = time.time()
        try:
            d = runner.run(self.camp.harness(p), t, x, version=p.version,
                           timeout_s=timeout_s, opt=self.camp.opt)
        except Exception as e:          # a harness failure, not the program's
            d = {"program_id": p.id, "toolchain": t, "xnack": x,
                 "outcome": "harness_error", "reason": f"harness: {e}"[:300]}
        d.update(campaign=self.camp.name, mode=mode_name(x),
                 expected=self.camp.expected(p),
                 observed=self.camp.parse_observed(d.get("stdout", "")),
                 task_s=round(time.time() - t0, 1), **self.camp.row_tags(p))
        d["stdout"] = (d.get("stdout") or "")[-2000:]
        d["stderr"] = (d.get("stderr") or "")[-3000:]
        return d

    def run(self, machine: str, runner=None, toolchains=None, modes=None,
            ids=None, legal_only: bool = False, workers: int = 8,
            shard: str | None = None, timeout_s: int | None = None,
            limit_s: float = 3000, log=print) -> int:
        """Compile and run the programs on the machine's toolchains through
        the harness, resumable (a cell with a row is not run again), in a
        fixed shuffled order (a run cut short covers every axis), bounded
        by `limit_s`; ``shard`` ``k/m`` takes every m-th remaining cell."""
        import random
        from concurrent.futures import ThreadPoolExecutor, as_completed
        runner = runner or self.camp.make_runner()
        ok = self.prerun_ok()
        if not ok:
            log("no program has a rules verdict: run `prerun` first")
            return 2
        tcs = list(toolchains) if toolchains else list(self.camp.caps.toolchains(machine))
        modes = list(modes) if modes else list(self.camp.caps.modes(machine))
        out = self.d / "rows.jsonl"
        done = {(r["program_id"], r["toolchain"], r["xnack"]) for r in read_jsonl(out)}
        progs = self.programs(set(ids) if ids else None)
        if legal_only:
            progs = [p for p in progs if self.camp.gated(p)]
        timeout_s = timeout_s or self.camp.timeout_s
        jobs = [(p, t, x) for p, t, x in self.cells(progs, tcs, modes, ok)
                if (p.id, t, x) not in done]
        random.Random(7).shuffle(jobs)
        if shard:
            k, m = (int(v) for v in shard.split("/"))
            jobs = jobs[k::m]
        if not self.sealed:
            log(f"{len(jobs)} runs to do ({len(done)} done)")
        end = time.time() + limit_s
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(lambda j=j: None if time.time() > end
                                else self.run_one(runner, *j, timeout_s))
                    for j in jobs]
            for f in as_completed(futs):
                r = f.result()
                if r is not None:
                    append_jsonl(out, [r])
        log("done")
        return 0

    # -- the reproduction gate --
    def gate_items(self, machine: str | None = None) -> list[dict]:
        """The failing rows of gated programs as gate items (one machine,
        or all)."""
        from offload.engine.gate_stored import machine_of
        byid = {p.id: p for p in self.programs()}
        out = []
        for r in self.rows():
            if r["outcome"] in FAILING_OK or r["outcome"] == "harness_error":
                continue
            p = byid.get(r["program_id"])
            if p is None or not self.camp.gated(p):
                continue                       # observations are not gated
            m = machine_of(r["toolchain"])
            if machine and m != machine:
                continue
            out.append({**{k: r.get(k) for k in (
                "outcome", "reason", "flaky", "build_dir", "node",
                "toolchain_build", "toolchain", "xnack", "mode")},
                "campaign": self.camp.name, "kind": self.camp.gate_kind,
                "machine": m, "ident": r["program_id"], "opt": self.camp.opt,
                "timeout_s": self.camp.timeout_s,
                "stdout": r.get("stdout") or "",
                "compile_log": (r.get("stderr") or "")[-3000:],
                "cell": self.camp.cell(r["program_id"], r["toolchain"], r["xnack"]),
                **self.camp.gate_tags(r)})
        only = self.d / "gate_only.json"       # a run that gates a chosen set of cells (hecbench t120):
        if only.is_file():                     # the list decides, with the witnesses of another run's rows
            keep = set(json.loads(only.read_text()))
            return [it for it in out if it["cell"] in keep]
        return self.camp.gate_filter(out, self.rows())

    def gate_budget(self) -> float | None:
        """The gate's budget (summed rerun seconds), kept in meta.json so
        every later command plans the same sample; None: every failing row."""
        return self.meta().get("gate_budget_s")

    def set_gate_budget(self, budget_s: float) -> None:
        meta = self.meta()
        meta["gate_budget_s"] = budget_s
        (self.d / "meta.json").write_text(json.dumps(meta))

    def gate_plan(self, items: list[dict] | None = None) -> dict:
        from offload.engine import gate as GT
        items = self.gate_items() if items is None else items
        total = sum(len(GT.ENVS) * GT.cost_s(it) for it in items) + 1
        return GT.plan(items, budget_s=self.gate_budget() or total)

    @staticmethod
    def node_share(items: list[dict], mode: str | None, here: str,
                   stored_on: str | None = None) -> list[dict]:
        """The rows this gate job takes by the node they were stored on:
        "same" (a, b, d in place), "other" ((c)), "any" or None (no
        placement), narrowed to the rows stored on the comma-separated
        nodes `stored_on`."""
        if mode == "same":
            items = [it for it in items if it.get("node") == here]
        elif mode == "other":
            items = [it for it in items if it.get("node") != here]
        if stored_on:
            keep = set(stored_on.split(","))
            items = [it for it in items if it.get("node") in keep]
        return items

    def gate(self, machine: str, runner=None, envs: str = "a,b,c,d",
             node: str | None = None, stored_on: str | None = None,
             shard: str | None = None, root: str | None = None,
             workers: int = 8, timeout_s: int | None = None,
             budget_s: float | None = None, log=print) -> int:
        """Rerun this machine's share of the planned failing rows in the
        gate's environments (offload.engine.gate.environments, gate_run);
        resumable per (cell, environment)."""
        from concurrent.futures import ThreadPoolExecutor
        from offload.engine import gate as GT
        runner = runner or self.camp.make_runner()
        byid = {p.id: p for p in self.programs()}
        if budget_s:
            self.set_gate_budget(budget_s)
        # the plan covers every machine's rows (as `verdicts` plans them);
        # this run takes its machine's share
        planned = self.gate_plan()
        items = [r for r in planned["rows"] if r["machine"] == machine
                 and r["sample"] in ("all", "new", "runtime", "sampled")]
        if node or stored_on:
            from offload.engine.provenance import node as here
            items = self.node_share(items, node, here(), stored_on)
        if shard:
            k, m = (int(v) for v in shard.split("/"))
            items = items[k::m]
        out = self.d / "gate_reruns.jsonl"
        done = {(r["cell"], r["env"]) for r in read_jsonl(out)}
        want = envs.split(",")
        jobs = []
        for it in items:
            es = [e for e in GT.environments(it, root or None)
                  if e["env"] in want and (it["cell"], e["env"]) not in done]
            if es:
                jobs.append((it, es))
        if not self.sealed:                 # a sealed run's gate logs no count of failing rows
            log(f"{len(planned['rows'])} failing rows, {len(items)} here, "
                f"{sum(len(j[1]) for j in jobs)} reruns")
        timeout_s = timeout_s or self.camp.timeout_s

        def one(job):
            it, es = job
            p = byid[it["ident"]]
            for e in es:
                rr = runner.rerun(self.camp.harness(p), it["toolchain"],
                                  int(it["xnack"]), e, version=p.version,
                                  timeout_s=timeout_s, opt=self.camp.opt)
                append_jsonl(out, [{**rr, "cell": it["cell"]}])
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, jobs))
        return 0

    def verdicts(self) -> dict:
        """cell -> the gate's judgement (offload.engine.gate.judge, inherit)
        with the planned item."""
        from offload.engine import gate as GT
        reruns = defaultdict(list)
        for r in read_jsonl(self.d / "gate_reruns.jsonl"):
            reruns[r["cell"]].append(r)
        planned = self.gate_plan()["rows"]
        judged = {}
        for it in planned:
            try:
                judged[it["cell"]] = GT.judge(it, reruns[it["cell"]])
            except ValueError:
                pass
        final = GT.inherit(planned, {c: j["verdict"] for c, j in judged.items()})
        out = {}
        for it in planned:
            c = it["cell"]
            f = final.get(c, {"verdict": "unchecked", "inherited": False})
            rec = {**judged.get(c, {}), **f, "item": it}
            rec["own"] = c in judged and not f.get("inherited") and \
                f["verdict"] == judged[c]["verdict"]
            out[c] = rec
        return out

    # -- report --
    def cls(self, r: dict) -> str:
        """The outcome class of a row (offload.engine.gate.observe)."""
        from offload.engine import gate as GT
        return GT.observe({**r, "kind": self.camp.gate_kind})[0]

    def summary(self) -> dict:
        ps = {p.id: p for p in self.programs()}
        rs = self.rows()
        by_tc = defaultdict(Counter)
        for r in rs:
            p = ps.get(r["program_id"])
            if p is None or not self.camp.gated(p):
                continue
            by_tc[(r["toolchain"], mode_name(r["xnack"]))][self.cls(r)] += 1
        v = self.verdicts()
        return {"rows": len(rs),
                "by_toolchain": {f"{t}|{m}": dict(c) for (t, m), c in by_tc.items()},
                "gate": dict(Counter(x["verdict"] for x in v.values()))}

    def matrix(self) -> str:
        """Markdown: one row per program, one column per toolchain and
        mode (ok, WA, rej, ICE, crash, run, TO, host, ign, harn; ``*``
        marks a cell the gate confirmed, ``?`` one it did not)."""
        v = self.verdicts()
        rs = self.rows()
        order = toolchain_order()
        cols = sorted({(r["toolchain"], mode_name(r["xnack"])) for r in rs},
                      key=lambda c: (order.get(c[0], 99), c[1] != "copy"))
        cell = {}
        for r in rs:
            c = SHORT.get(self.cls(r), self.cls(r))
            if c != "ok":
                g = v.get(self.camp.cell(r["program_id"], r["toolchain"],
                                         r["xnack"]), {}).get("verdict")
                c += "*" if g == "confirmed" else "?" if g else ""
            cell[(r["program_id"], r["toolchain"], mode_name(r["xnack"]))] = c
        head = ["program", "spec"] + [f"{t} {m[0]}" for t, m in cols]
        L = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        for p in self.programs():
            L.append("| " + " | ".join(
                [self.camp.short_id(p), self.camp.mark(p)] +
                [cell.get((p.id, t, m), "") for t, m in cols]) + " |")
        return "\n".join(L)

    def report(self, log=print) -> dict:
        s = self.summary()
        log(json.dumps(s, indent=1, sort_keys=True))
        (self.d / "matrix.md").write_text(self.matrix() + "\n")
        log("matrix ->", self.d / "matrix.md")
        return s

    # -- clusters of failures --
    def row_signature(self, r: dict) -> str:
        return row_signature(r, self.cls(r))

    def clusters(self) -> list[dict]:
        """Failures of gated programs grouped by (toolchain, mode,
        signature), with the facets the members share and the passing
        programs of the same toolchain and mode mostly lack, and how many
        the gate confirmed."""
        ps = {p.id: p for p in self.programs()}
        ver = self.verdicts()
        rs = [r for r in self.rows()
              if r["program_id"] in ps and self.camp.gated(ps[r["program_id"]])]
        ok = defaultdict(list)
        bad = defaultdict(list)
        for r in rs:
            key = (r["toolchain"], mode_name(r["xnack"]))
            cls = self.cls(r)
            if cls in FAILING_OK:
                ok[key].append(r["program_id"])
            elif cls != "harness_error":
                v = ver.get(self.camp.cell(r["program_id"], r["toolchain"],
                                           r["xnack"]), {}).get("verdict")
                bad[key + (self.row_signature(r),)].append((r["program_id"], v))
        out = []
        for key, members in bad.items():
            tc, mode, sig = key
            ids = [m[0] for m in members]
            mem = [self.camp.facets(ps[i]) for i in ids]
            pas = [self.camp.facets(ps[i]) for i in ok[(tc, mode)]]
            share = []
            for item in sorted(set().union(*mem)):
                f_in = sum(item in m for m in mem) / len(mem)
                f_out = (sum(item in m for m in pas) / len(pas)) if pas else 0
                if f_in >= 0.8 and f_out <= f_in - 0.4:
                    share.append((item, round(f_in, 2), round(f_out, 2)))
            out.append({"toolchain": tc, "mode": mode, "signature": sig,
                        "n": len(ids),
                        "confirmed": sum(1 for m in members if m[1] == "confirmed"),
                        "programs": sorted(ids), "discriminators": share})
        return sorted(out, key=lambda c: (-c["n"], c["toolchain"]))

    def cluster(self, log=print) -> list[dict]:
        cs = self.clusters()
        (self.d / "clusters.json").write_text(json.dumps(cs, indent=1))
        for c in cs:
            log(f"{c['n']:4d} ({c['confirmed']:3d} conf)  {c['toolchain']:9s} "
                f"{c['mode']:8s} {c['signature']}")
            log("        ", "; ".join(f"{i} {f}/{g}" for i, f, g in
                                      c["discriminators"][:8]))
        return cs

    # -- the confirmer --
    def cell_legality(self, p, toolchain: str, leg: dict):
        """The confirmer's legality of a cell: legal when the program's
        behaviour is defined (its label, whatever ``gated`` says: an
        unspecified program's failure may be confirmed as an observation,
        never as a compiler bug) and it is legal for the toolchain's family
        (the rules and a front end of another family); unknown (the
        legality review, never a compiler bug) otherwise."""
        from offload.engine.confirm.legality import Legality
        from offload.engine.toolchains import TOOLCHAINS
        r = leg[p.id]
        if self.camp.legality(p) != "defined":
            return Legality("unknown", self.camp.unknown_why(p))
        fam = TOOLCHAINS[toolchain].kind
        if r["legal_for"].get(fam):
            fes = [f for f in ("afar", "nvhpc", "cce") if f != fam and r.get(f"{f}_fe")]
            return Legality("legal", "two witnesses: the rules (compliance."
                            "rules) and the front end of " + ", ".join(fes) +
                            " (not under test for this case)")
        return Legality("unknown", "no front end of another family accepted it, "
                        "or one rejected it with a diagnostic")

    def confirm(self, log=print) -> list[dict]:
        """The confirmer (offload.engine.confirm.engine, stored evidence only)
        over every failing row of a gated program, with the gate's verdicts
        and the legality above -> confirm.jsonl. The gate reads this run's
        verdicts only while it runs: the module's own file is put back."""
        from offload.engine import gate as GT
        saved = GT.VERDICTS_FILE
        try:
            return self._confirm(log)
        finally:
            GT.VERDICTS_FILE = saved

    def _confirm(self, log) -> list[dict]:
        from offload.engine import gate as GT
        from offload.engine.confirm import engine as EN
        from offload.engine.confirm import ingest as IG
        from offload.engine.confirm import programs as P
        from offload.engine.confirm.collectors import Context
        from offload.engine.confirm.store import Store
        d = self.d
        ps = {p.id: p for p in self.programs()}
        leg = self.legality_table()
        ver = self.verdicts()
        gv = d / "gate_verdicts.file.jsonl"
        with open(gv, "w") as fh:
            for c, v in ver.items():
                it = v["item"]
                fh.write(json.dumps({"cell": c, "kind": "file", "ident": it["ident"],
                                     "toolchain": it["toolchain"], "xnack": it["xnack"],
                                     "verdict": v["verdict"]}) + "\n")
        GT.VERDICTS_FILE = gv
        rows_ = []
        for r in self.rows():
            p = ps.get(r["program_id"])
            if p is None or not self.camp.gated(p):
                continue
            try:
                row = IG.row_of_result(r, f"{self.label}/rows.jsonl")
            except KeyError:
                continue
            rows_.append(dataclasses.replace(row, kind="file"))
        ctx = Context(IG.Index(rows_), Store(d / "confirm_evidence.jsonl"),
                      allow_run=False)
        vby = {(v["item"]["ident"], v["item"]["toolchain"],
                IG._mode(v["item"]["toolchain"], v["item"]["xnack"])[1]): v["verdict"]
               for v in ver.values()}
        refs, out = {}, []
        for x in rows_:
            if x.outcome in (*FAILING_OK, "harness_error"):
                continue
            p = ps[x.ident]
            if x.ident not in refs:
                refs[x.ident] = P.file_ref(
                    [str(d / "src" / f"{x.ident}.{self.camp.ext(p)}")], "check=pass",
                    label=x.ident, version=p.version)
            case = IG.case_of_row(x, refs[x.ident])
            try:
                res = EN.confirm(case, ctx, legality=self.cell_legality(p, x.toolchain, leg),
                                 minimize=False, draft=False)
            except Exception as e:
                res = {"verdict": "error", "rule": "", "reason": f"{e}"[:300]}
            out.append({"program": x.ident, "toolchain": x.toolchain, "mode": x.mode,
                        "outcome": x.outcome, "verdict": res.get("verdict"),
                        "rule": res.get("rule"), "reason": (res.get("reason") or "")[:400],
                        "gate": vby.get((x.ident, x.toolchain, x.mode)),
                        "findings": [f.get("file") for f in res.get("findings") or []],
                        "related": [f.get("file") for f in res.get("related") or []],
                        "legality": (res.get("legality") or {}).get("status")})
        (d / "confirm.jsonl").write_text("".join(
            json.dumps(o, sort_keys=True) + "\n" for o in out))
        log(len(out), "cases;", Counter(o["verdict"] for o in out))
        return out

    # -- the findings plan --
    def findings_plan(self, log=print) -> str:
        """A plan, not a finding: every cluster of confirmed failures of
        gated programs with its programs, the confirmer's verdicts on them
        and the tools/new_finding.py command that drafts the finding once a
        person has reduced one program and made its controls
        (docs/tooling/contributing.md, "Add a finding"). Written to
        findings_plan.md; nothing under findings is touched."""
        conf = {}
        for o in read_jsonl(self.d / "confirm.jsonl"):
            conf[(o["program"], o["toolchain"], o["mode"])] = o
        L = [f"# {self.camp.name}: candidate findings of {self.label}", "",
             "A cluster is one (toolchain, mode, failure signature) over the gated programs; "
             "only the cells the gate confirmed count. Reduce one program per cluster "
             "(tools/reduce.py), make controls, then draft with the command given.", ""]
        n = 0
        for c in self.clusters():
            if not c["confirmed"]:
                continue
            n += 1
            vs = Counter(conf.get((pid, c["toolchain"], c["mode"]), {}).get("verdict", "-")
                         for pid in c["programs"])
            first = c["programs"][0]
            ext = self.camp.ext({p.id: p for p in self.programs()}[first])
            L += [f"## {n}. {c['toolchain']} {c['mode']}: {c['signature']}", "",
                  f"- programs: {c['n']} ({c['confirmed']} confirmed): "
                  + ", ".join(c["programs"][:12]) + (" ..." if c["n"] > 12 else ""),
                  "- confirmer: " + ", ".join(f"{k} {v}" for k, v in sorted(vs.items())),
                  "- shared facets: " + (", ".join(f"{i} ({f}/{g})" for i, f, g in
                                                   c["discriminators"][:8]) or "none"),
                  f"- draft: `python3 -I tools/new_finding.py REDUCTION.{ext} --campaign "
                  f"{self.camp.name} --rows {self.label}/rows.jsonl --control CTL.{ext} "
                  f"--name SLUG --dir data/findings/{self.camp.name}`", ""]
        if n == 0:
            L.append("No confirmed failure of a gated program.")
        text = "\n".join(L).rstrip() + "\n"
        (self.d / "findings_plan.md").write_text(text)
        log(f"{n} candidate clusters -> {self.d / 'findings_plan.md'}")
        return text


SHORT = {"correct_on_device": "ok", "wrong_answer": "WA", "rejected": "rej",
         "ice": "ICE", "crash": "crash", "run_error": "run", "timeout": "TO",
         "fell_back_to_host": "host", "accepted_ignored": "ign",
         "harness_error": "harn", "unobservable": "ok"}


def toolchain_order() -> dict[str, int]:
    """The report columns' order: the catalog's, arch twins last."""
    from offload.engine.toolchains import registry
    reg = registry()
    names_ = [n for n, t in reg.toolchains.items() if t.twin_of is None] + \
        [n for n, t in reg.toolchains.items() if t.twin_of is not None]
    return {n: i for i, n in enumerate(names_)}


def norm_reason(text: str) -> str:
    """A failure's first line with paths, addresses and numbers removed."""
    t = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    t = re.sub(r"<tmpdir>|/\S+", "<path>", t)
    t = re.sub(r"\b0x[0-9a-f]+\b", "<addr>", t)
    t = re.sub(r"\d+", "N", t)
    return t[:140]


def row_signature(r: dict, cls: str) -> str:
    """A failure's signature for clustering: a wrong answer names the
    expected values that differ, anything else its class and reason."""
    if cls == "wrong_answer":
        exp, obs = r.get("expected") or {}, r.get("observed") or {}
        bad = sorted(k for k in exp if obs.get(k) != exp[k])
        return "wrong:" + ",".join(bad) if bad else "wrong:?"
    return f"{cls}:{norm_reason(r.get('reason', ''))}"


def run_dir(camp: Campaign, name: str, results: Path | None = None) -> Path:
    return Path(results or RESULTS) / camp.name / name


def run_label(camp: Campaign, name: str) -> str:
    return f"results/{camp.name}/{name}"
