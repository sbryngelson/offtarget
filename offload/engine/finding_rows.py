"""The recorded rows behind a finding's header claims.

Two kinds of rows hold what a finding's program did:

* the site/vendor-check rows (data/vendor/checks/results-compact and results-site, committed):
  keyed by a check case (the finding's repro, and its control when the case has one), with the
  gate environment (a-d) and the observation text (offload.engine.site.matrix reads them);
* campaign rows (results/<campaign>/..., git-ignored): harness rows and gate reruns, matched
  to a program by its fingerprint (the program text without comments) or by its program id (the
  file stem).

Both are read into ``Obs`` records so a claim is checked against one kind of record.
``Evidence`` is what a finding has: ``full`` says the git-ignored rows were searched (results/
exists); without them a claim about a program only they could cover is not decided.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from offload.engine.site import matrix as M

from offload.engine.root import ROOT  # noqa: E402
RESULTS = ROOT / "results"
MODE_OF_TARGET = {"mi300a-u": "unified", "mi300a-c": "copy", "mi250x": "copy",
                  "a100-s": "copy", "a100-m": "managed"}
_TARGET_OF = {k: v for k, v in M.TARGETS.items()}


# a compiler's own crash banner, most telling first
ICE_BANNERS = [re.compile(x, re.I) for x in (r"PLEASE submit", r"internal compiler error", r"\bINTERNAL\b",
                                              r"Assertion .* failed", r"LLVM ERROR", r"Stack dump")]


_DRIVER = re.compile(r"^(?:clang|craycc|crayftn|ftn|cc1|cc1plus|f951|flang|amdflang|nvc|nvfortran)(?:-\d+)?:\s*")
# a location the scrubber left as a placeholder (`<dir>:126:2: error: ...` -> `<dir>::: error: ...`)
_PLACEHOLDER_LOC = re.compile(r"^<[\w-]+>(?::\d*)+\s*")


def row_signature(obs: str, cls: str = "") -> tuple:
    """offload.engine.site.matrix.signature, except for a compiler crash: the compiler's own crash
    banner (PLEASE submit..., internal compiler error) names it. A compile failure's signature
    is its text whatever class the row recorded (a campaign's "ice" for NVFORTRAN's "failed to
    translate" and a site row's rejection of the same message are one), without the driver that
    reports it (`clang: error: unable to execute command: Aborted` on CCE 19 and 20,
    `craycc: error: ...` on CCE 21 are one crash)."""
    sig = M.signature(obs)
    if cls == "ice" or sig[0] == "ice":
        for rx in ICE_BANNERS:
            line = next((x for x in obs.splitlines()[1:] if rx.search(x)), None)
            if line:
                return "ice", M._norm(line)
    if sig[0] in ("ice", "reject", "link"):
        return sig[0], _DRIVER.sub("", _PLACEHOLDER_LOC.sub("", sig[1]))
    return sig


@dataclass(frozen=True)
class Obs:
    tc: str
    target: str
    env: str          # a-d, or "" when the row names none
    node: str         # node or GPU, "" when unknown
    passed: bool
    failed: bool
    obs: str          # "<STAGE> rc=..\n<output>" (offload.engine.site.matrix.signature reads it)
    src: str          # where the row came from
    variant: str = "repro"       # repro | control (site rows)
    pid: str = ""     # campaign program id, or the check case
    fp: str = ""      # fingerprint of the program text (campaign rows)
    control: str = ""  # the vendor control path a site control row ran (src/<id>-control.f90)
    cls: str = ""     # the outcome class: ice, rejected, wrong_answer, crash, run_error, ... or correct
    cmd: str = ""     # the build flags or command the row recorded
    path: str = ""    # the row file a campaign row came from

    @property
    def sig(self) -> tuple:
        return row_signature(self.obs, self.cls)

    @property
    def mode(self) -> str:
        return MODE_OF_TARGET.get(self.target, "")


def fingerprint(text: str, lang: str | None = None) -> str:
    """sha256 of a program with its comment lines and blank lines removed (the vendor checks'
    ``trim``), so a finding file and the reduction it was copied from have the same one."""
    lang = lang or ("c" if re.search(r"^\s*#\s*include|^\s*int\s+main", text, re.M) else "f90")
    return hashlib.sha256(M.B.trim(text, lang).encode()).hexdigest()[:16]


# --- site rows ------------------------------------------------------------------------

_SIG_CLS = {"ice": "ice", "link": "rejected", "reject": "rejected", "crash": "crash",
            "wrong": "wrong_answer"}


def site_obs(case: dict, rows: list[dict]) -> list[Obs]:
    out = []
    for r in rows:
        if r.get("case") != case["id"]:
            continue
        tc = r.get("tc")
        target = M.TARGETS.get((r.get("machine"), str(r.get("mode"))))
        if tc not in M.VERSIONS or target is None:
            continue
        variant = r.get("variant", "repro")
        cls = M.B.classify(case, r["obs"], variant)
        if cls in ("NA", "H"):
            continue
        out.append(Obs(tc, target, r.get("env", ""),
                       # a GPU index names a node only on a one-host machine (offload.engine.gate.ONE_HOST)
                       str(r["gpu"]) if r.get("gpu") is not None and r.get("machine") == "wingtip" else "",
                       cls == "P", cls != "P", r["obs"], "site-rows", variant, case["id"], "",
                       case.get("control", "") if variant == "control" else "",
                       "correct" if cls == "P" else _SIG_CLS.get(M.signature(r["obs"])[0], "run_error"),
                       M.B.scrub(str(r.get("cmd") or ""))))
    return out


# --- campaign rows --------------------------------------------------------------------

def _stage_text(d: dict, cls: str) -> str:
    out = "\n".join(str(d.get(k) or "") for k in ("stdout",) if d.get(k))
    comp = str(d.get("compile_log") or d.get("stderr") or "")
    reason = str(d.get("reason") or "")
    if cls in ("rejected", "ice", "compile_oom"):
        return "COMPILE_FAIL rc=1\n" + (comp or reason)
    if cls == "timeout" and "compile" in reason[:40]:
        return "COMPILE_TIMEOUT\n"
    m = re.search(r"SIG(\w+)", reason)
    if cls in ("crash", "run_error"):
        return f"RUN_FAIL rc=-1{' signal=' + m.group(1) if m and cls == 'crash' else ''}\n" + \
               (out or reason)
    if cls == "timeout":
        return "RUN_TIMEOUT\n"
    return "RUN_OK rc=0\n" + (out or reason)


_BAD_OUT = re.compile(r"\bfail\b|\bFAIL\b|mismatch|\bwrong\b", re.I)


def normalize_row(d: dict) -> dict:
    """A row of the other formats in harness-row terms: a gate rerun keyed by ``cell``
    ("kind|ident|toolchain|xnack"), and an ad-hoc probe row (``build``, ``rc``, ``out``; the
    fresh-drafts runs)."""
    if "cell" in d and "toolchain" not in d and str(d["cell"]).count("|") >= 3:
        _, ident, tc, xn = str(d["cell"]).split("|")[:4]
        d = dict(d, toolchain=tc, program_id=ident, xnack=int(xn) if xn.lstrip("-").isdigit() else 0)
    if "program" in d and "class" in d and "outcome" not in d and d.get("toolchain"):
        # the parity probes (results/parity/<machine>/<tc>/probes.jsonl): class pass | wrong | ...
        oc = {"pass": "correct_on_device", "wrong": "wrong_answer"}.get(d["class"], "run_error")
        d = dict(d, outcome=oc, reason=str(d["class"]), program_id=Path(str(d["program"])).stem,
                 xnack=d.get("xnack", 0))
    if "build" in d and "outcome" not in d and d.get("toolchain"):
        out, err = str(d.get("out") or ""), str(d.get("err") or "")
        if d["build"] != "ok":
            oc, why = "rejected", "diagnostic: " + (err or str(d["build"]))[:200]
        elif str(d.get("rc")) not in ("0", "None"):
            oc, why = "run_error", f"exit_status: {d.get('rc')}"
        elif _BAD_OUT.search(out):
            oc, why = "wrong_answer", out[:120]
        else:
            oc, why = "correct_on_device", out[:120]
        d = dict(d, outcome=oc, reason=why, stdout=out, compile_log=err if oc == "rejected" else "")
    return d


def _src_of(srcdir: Path | None, pid: str) -> Path | None:
    """The campaign's copy of program `pid` (results/<campaign>/<run>/src/<pid>.<ext>), if any."""
    if srcdir is None or not pid:
        return None
    for ext in (".f90", ".F90", ".c"):
        p = srcdir / (pid + ext)
        if p.is_file():
            return p
    return None


# where a path recorded in older rows lives now (docs/findings -> findings -> data/findings, and
# the same for vendor and the reports, once docs/review)
MOVED = (("docs/findings/", "data/findings/"), ("findings/", "data/findings/"),
         ("docs/vendor/", "data/vendor/"), ("vendor/", "data/vendor/"),
         ("docs/review/", "data/reports/"), ("reports/", "data/reports/"))


def current_path(f: str, root: Path = ROOT) -> Path:
    """The file a row's recorded path names, where it is now (``MOVED``)."""
    p = root / f
    if not p.is_file():
        for old, new in MOVED:
            if f.startswith(old) and (root / (new + f[len(old):])).is_file():
                return root / (new + f[len(old):])
    return p


def campaign_obs(rows: list[dict], root: Path = ROOT, srcdir: Path | None = None) -> list[Obs]:
    """Observations from harness rows and gate reruns (any row with a toolchain, an outcome and
    a program id or file). A row that names its program by id only is fingerprinted from the
    campaign's source copy in `srcdir` (the src/ next to the row file) when there is one."""
    from offload.engine import gate as G
    from offload.engine.toolchains import TOOLCHAINS, registry
    twins = registry().machine_twins()     # support-table cells, no finding's evidence
    out, fps = [], {}
    for d in rows:
        d = normalize_row(d)
        tc = d.get("toolchain")
        if not tc or tc in twins or not (d.get("program_id") or d.get("file") or d.get("ident")):
            continue
        tc = site_tc(tc)
        if tc not in M.VERSIONS:
            continue
        cls = G.outcome_class(d)
        if cls in G.NOT_EVIDENCE or cls in G.CAPACITY_CLASSES or cls == "refused":
            continue
        raw_tc = d["toolchain"]
        machine = d.get("machine") or (TOOLCHAINS[raw_tc].machine if raw_tc in TOOLCHAINS else "")
        target = M.TARGETS.get((machine, str(d.get("xnack", d.get("mode", 0)))))
        if target is None:
            continue
        pid = str(d.get("program_id") or d.get("ident") or Path(str(d.get("file", ""))).stem)
        fp = ""
        f = d.get("file")
        if not f:
            src = _src_of(srcdir, pid)
            f = str(src) if src is not None else None
        if f:
            if f not in fps:
                p = current_path(f, root)
                try:
                    fps[f] = fingerprint(p.read_text()) if p.is_file() else ""
                except (OSError, UnicodeDecodeError):
                    fps[f] = ""
            fp = fps[f]
        passed = cls in G.PASSING and cls != "unobservable"
        out.append(Obs(tc, target, str(d.get("env", "")), str(d.get("node") or ""), passed,
                       G.is_failure(cls), _stage_text(d, cls), "campaign-rows", "repro", pid, fp, "",
                       "correct" if passed else cls, str(d.get("flags") or "")))
    return out


def site_tc(tc: str) -> str:
    """The site's toolchain of a row's or a header's toolchain: itself, or the toolchain a twin
    is the twin of (cce21_g90 -> cce21, gcc_g90 -> gcc)."""
    from offload.engine.toolchains import base_name
    return tc if tc in M.VERSIONS else base_name(tc)


def load_jsonl(paths) -> list[dict]:
    rows = []
    for p in paths:
        try:
            for ln in Path(p).read_text(errors="replace").splitlines():
                if ln.strip().startswith("{"):
                    try:
                        rows.append(json.loads(ln))
                    except ValueError:
                        pass
        except OSError:
            pass
    return rows


_PATH = re.compile(r"results/[\w./*{},-]+")


def named_row_files(text: str, root: Path = ROOT) -> list[Path]:
    """The row files a header names: `results/...` paths and globs (a bare `gate_reruns*.jsonl`
    after one names a file in the same directory). Only .jsonl files that exist. A gate part file
    named by its machine (gate_reruns.part.wingtip.501872.jsonl) is the one on disk whose name
    adds the host to the machine (gate_reruns.part.wingtip-n1.<domain>.501872.jsonl)."""
    out, last_dir = [], None
    text = re.sub(r"<[\w-]+>", "*", text)      # results/parity/<machine>/<tc>/probes.jsonl
    for m in _PATH.finditer(text):
        tok = m.group(0).rstrip(".,;)")
        if "/" in tok:
            last_dir = tok.rsplit("/", 1)[0]
        if not tok.endswith(".jsonl") and "*" not in tok:
            continue
        pats = [tok]
        # "gate_reruns*.jsonl, gate_c.jsonl": later bare names live in the same directory
        for extra in re.findall(r"(?<![/\w.])([\w*-]+\.jsonl)", text[m.end(): m.end() + 120]):
            if last_dir:
                pats.append(f"{last_dir}/{extra}")
        for pat in pats:
            hits = sorted(root.glob(pat))
            if not hits:     # a part file cited by machine; on disk it carries the host name
                hits = sorted(root.glob(re.sub(r"(\.part\.[A-Za-z][\w-]*)(\.\d+\.jsonl)$", r"\1[.-]*\2", pat)))
            out += hits
    return list(dict.fromkeys(p for p in out if p.is_file() and p.suffix == ".jsonl"))


_FILE_OBS: dict = {}


def _file_obs(path: Path, root: Path) -> list[Obs]:
    key = (str(path), str(root), path.stat().st_mtime_ns)
    if key not in _FILE_OBS:
        src = path.parent / "src"
        _FILE_OBS[key] = [dataclasses.replace(o, path=str(path))
                          for o in campaign_obs(load_jsonl([path]), root,
                                                src if src.is_dir() else None)]
    return _FILE_OBS[key]


# --- evidence for one finding ----------------------------------------------------------

@dataclass
class Evidence:
    obs: list = field(default_factory=list)
    full: bool = False            # the git-ignored rows were searched
    fp: str = ""                  # fingerprint of the finding's program
    stem: str = ""
    case_control: str = ""        # the vendor check's control path, if the finding has a case
    control_tcs: tuple = ()       # the toolchains the check ran its control on
    has_site: bool = False        # the finding has a check case with rows
    row_files: tuple = ()
    findings_dir: Path = ROOT / "data" / "findings"
    base: Path = ROOT / "data" / "findings"      # the directory control paths are relative to

    def repro(self) -> list[Obs]:
        return [o for o in self.obs if o.variant == "repro" and
                ((o.src == "site-rows") or o.fp == self.fp or o.pid == self.stem)]

    def control(self, path: str) -> list[Obs] | None:
        """Observations of the control file `path` (None: no recorded source could hold any)."""
        path = path.strip()
        site = [o for o in self.obs if o.variant == "control" and o.control and
                (path.endswith(o.control) or o.control.endswith(Path(path).name))]
        stem = Path(path).stem
        cfp = ""
        for cand in (self.base / path, self.findings_dir / path, ROOT / path):
            if cand.is_file():
                cfp = fingerprint(cand.read_text())
                break
        camp = [o for o in self.obs if o.src == "campaign-rows" and o.variant == "repro" and
                (o.pid == stem or (cfp and o.fp == cfp))]
        if site or camp:
            return site + camp
        if self.case_control and path.endswith(Path(self.case_control).name):
            return []
        return [] if self.full else None


def evidence_for(rel: str, text: str, *, entry: dict | None = None, rows: list | None = None,
                 cases: list | None = None, full: bool | None = None, root: Path = ROOT,
                 findings_dir: Path | None = None, campaign: list | None = None) -> Evidence:
    """The evidence for the finding `rel` (path under findings) with file text `text`."""
    fdir = findings_dir or root / "data" / "findings"
    rows = M._rows() if rows is None else rows
    cases = M._cases() if cases is None else cases
    stem = Path(rel).stem
    fid = rel.rsplit(".", 1)[0]
    case = M.case_for(fid, cases) or (M.derive_case(entry) if entry else None)
    ev = Evidence(full=(root / "results").is_dir() if full is None else full,
                  fp=fingerprint(text), stem=stem, findings_dir=fdir,
                  base=(fdir / rel).parent)
    if case is not None:
        ev.obs += site_obs(case, rows)
        ev.has_site = bool(ev.obs)
        ev.case_control = case.get("control", "") or ""
        aff = {a.split("@")[0] for a in case.get("affected") or []}
        # a regression release goes with its headline toolchain (cce21_4 with cce21)
        from offload.engine.toolchains import REGRESSION_TOOLCHAINS
        aff |= {r for r, head in REGRESSION_TOOLCHAINS.items() if head in aff}
        ev.control_tcs = tuple(sorted({site_tc(t) for t in aff}))
        # a finding split into several check cases (one control each): their control rows too
        for c in cases:
            if c is not case and c.get("control") and c["finding"].rsplit(".", 1)[0] == fid:
                ev.obs += [o for o in site_obs(c, rows) if o.variant == "control"]
    if ev.full:
        files = named_row_files(text, root)
        ev.row_files = tuple(str(f) for f in files)
        if campaign is not None:
            ev.obs += campaign_obs(campaign, root)
        for f in ([] if campaign is not None else files):
            ev.obs += _file_obs(f, root)
    return ev
