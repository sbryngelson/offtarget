"""The reproduction gate: a failure counts only after the tools reproduce it.

Each failing campaign row is rerun in four environments (``environments``):
(a) its original build directory and node, (b) a differently named build
directory, (c) the path of (a) on another node or GPU, (d) a second run in
(a). ``verdict(row, reruns)`` returns ``not_reproduced``, ``nondeterministic``
(an environment disagrees with itself), ``confirmed`` (every valid rerun
matches the row) or ``environment`` (the environments differ). ``unchecked``
marks a failure not rerun, ``illegal`` a program violating a rule. A
``harness_error`` rerun or one killed by signal 9 is not valid.
``plan`` fits the reruns into a GPU-second budget (``cost_s``): one failure
per new compile-time signature, then run-time failures round-robin, then up
to ``per_signature`` more. ``inherit`` copies a signature's verdict to its
unrerun rows. Campaign kinds are in ``KINDS``. The gate adds verdicts and
never deletes rows; ``counts_as_failure`` tells which count."""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from pathlib import Path

from offload.engine.root import ROOT  # noqa: E402
RESULTS = ROOT / "results" / "gate"
VERDICTS = ("confirmed", "environment", "nondeterministic",
            "not_reproduced", "unchecked", "illegal", "not_a_failure")
REVIEW = ("environment", "nondeterministic", "not_reproduced")
# most doubtful first: the verdict a signature's unsampled rows inherit
WORST_FIRST = ("nondeterministic", "environment", "not_reproduced",
               "confirmed")
COMPILE_CLASSES = ("rejected", "ice", "accepted_ignored")
ENVS = ("a", "b", "c", "d")
PASSING = ("correct_on_device", "unobservable")
NOT_EVIDENCE = ("harness_error", "skipped")
# a capacity limit the runtime reports (offload.engine.harness.CAPACITY): a
# break point, never a compiler failure (the decisions)
CAPACITY_CLASSES = ("capacity",)
PER_SIGNATURE = 3

# a stored row of any format -> the confirmer's outcome classes
# (offload.engine.confirm.model.OUTCOMES) plus the stress limits
_CLS = {"agree": "correct_on_device", "compile_reject": "rejected",
        "ice": "ice", "wrong_code": "wrong_answer",
        "host_fallback": "fell_back_to_host", "harness_error":
        "harness_error", "timeout": "timeout", "run_timeout": "timeout",
        "compile_timeout": "timeout", "compile_oom": "compile_oom",
        "probe_rejected": "correct_on_device",
        "probe_accepted": "wrong_answer", "skipped": "skipped",
        "prerun_refused": "refused"}


# --- what a row says ----------------------------------------------------------------

def outcome_class(d: dict) -> str:
    """The outcome class of a row of any format: a harness Result
    (``outcome``, ``reason``), a fuzz or stress result (``cls``), a
    confirmer Run (``outcome`` already a class)."""
    cls = _outcome_class(d)
    if cls in ("crash", "run_error", "timeout") and not _compile_side(d):
        from offload.engine.harness import capacity_message
        # (a stress rerun keeps its run output in compile_log)
        text = "\n".join(str(d.get(k) or "") for k in (
            "output", "stdout", "stderr", "reason", "compile_log"))
        if capacity_message(str(d.get("toolchain") or ""), text):
            return "capacity"
    return cls


def _compile_side(d: dict) -> bool:
    return "compile" in str(d.get("reason") or "")[:40]


def _outcome_class(d: dict) -> str:
    if "cls" in d and d.get("cls"):
        cls, reason = d["cls"], d.get("reason") or ""
        if cls == "run_error":
            return "crash" if reason.startswith("crash") else "run_error"
        return _CLS.get(cls, cls)
    from offload.engine.confirm.model import outcome_of_result
    try:
        return outcome_of_result(d.get("outcome", ""), d.get("reason", ""))
    except ValueError:
        return d.get("outcome", "")


def _head(reason: str) -> str:
    return (reason or "").split("; repeats")[0].split("; note:")[0]


def message_key(reason: str) -> str:
    """A compiler message without positions, paths, names, numbers and
    version hashes (the confirmer's message key)."""
    from offload.engine.confirm.decisions import _msg_key
    text = re.sub(r"version \S+", "version", _head(reason))
    text = text.split("; also:")[0]
    # names a build derives from the file's path or inode (clang's
    # __omp_offloading_<dev>_<file id>_<function>_l<line>) and hashes
    text = re.sub(r"__omp_offloading_\w+", "__omp_offloading_", text)
    text = re.sub(r"\b[0-9a-fA-F]{8,}\b", "H", text)
    short = _msg_key(text)
    # the confirmer's key keeps 120 characters: the hash of the whole
    # normalised message tells apart diagnostics whose difference comes
    # later ("... \")\" was expected but found \":\"")
    t = re.sub(r"File = [^|]*\|", "", text)
    t = re.sub(r"ftn: ERROR \S+", "ftn: ERROR", t)
    t = re.sub(r'loc\("[^"]*":\d+:\d+\)', "loc", t)
    t = re.sub(r"<tmpdir>\S*|/\S+", "<path>", t)
    t = re.sub(r'"[A-Za-z0-9_$%]+"', '"X"', t)
    t = re.sub(r"0x[0-9a-fA-F]+|\d+", "N", t)
    full = " ".join(t.split("; repeats")[0].split())
    if len(full) <= 120:
        return short
    return f"{short}#{hashlib.sha1(full.encode()).hexdigest()[:8]}"


# an ICE line that names no defect: the driver's or the front end's own
# report that something crashed (which of them a run prints first, and
# how its lines wrap, depends on the build path's length and the output
# kept), so two ICE observations with one of these are the same failure
_GENERIC_ICE = re.compile(r"PLEASE submit a bug report|frontend command "
                          r"failed|terminated due to receipt of signal|"
                          r"ftn: INTERNAL|unable to execute command|"
                          r"TERMINATED by signal")
# CCE's quoted ICE message; a long build path can cut the line inside the
# quotes (no closing quote: the key ends with "...")
_CCE_ICE_MSG = re.compile(r'INTERNAL COMPILER ERROR:\s*"([^"]*)("?)')


def generic(key: str) -> bool:
    """An ICE key that names no defect (a generic crash report)."""
    return bool(_GENERIC_ICE.search(key or ""))


def _ice_msg(key: str) -> tuple[str, bool] | None:
    """(message, cut) of a CCE ICE key, None for another key."""
    m = re.match(r'ICE "(.*?)(\.\.\.)?"?(?: @ .*)?$', key or "")
    if not m:
        return None
    return m.group(1), bool(m.group(2))


_ICE_FINDINGS: list | None = None


def ice_findings() -> list:
    """[(toolchains, message regex, file)] of the findings index's ICE
    findings that carry a message pattern (data/findings/index.yaml)."""
    global _ICE_FINDINGS
    if _ICE_FINDINGS is None:
        import yaml
        idx = ROOT / "data" / "findings" / "index.yaml"
        out = []
        if idx.is_file():
            doc = yaml.safe_load(idx.read_text()) or {}
            for f in next(iter(doc.values()), []) if isinstance(
                    doc, dict) else doc:
                if f.get("outcome") == "ice" and f.get("message"):
                    try:
                        out.append((set(f.get("toolchains") or ()),
                                    re.compile(f["message"]), f["file"]))
                    except re.error:
                        continue
        _ICE_FINDINGS = out
    return _ICE_FINDINGS


def same_finding(a: str, b: str, toolchain: str | None = None
                 ) -> str | None:
    """The finding whose message pattern matches both ICE keys (of
    `toolchain`, when given), or None. CCE's character-map ICE
    prints one of three messages by build path; its finding's pattern
    names all three."""
    for tcs, rx, f in ice_findings():
        if toolchain and tcs and toolchain not in tcs:
            continue
        if rx.search(a) and rx.search(b):
            return f
    return None


def same(a: tuple, b: tuple, toolchain: str | None = None) -> bool:
    """Two observations (class, key) are the same failure: equal, or two
    ICEs whose message is the same (a message cut by a wrapped line is
    compared by its prefix) or of which one names no defect (a generic
    crash report: within one program's reruns only; generic reports never
    key an inherited verdict)."""
    if a == b:
        return True
    if a[0] != b[0] or a[0] != "ice":
        return False
    if generic(a[1]) or generic(b[1]):
        return True
    ma, mb = _ice_msg(a[1]), _ice_msg(b[1])
    if ma and mb:
        (ta, ca), (tb, cb) = ma, mb
        if ta == tb:
            return True
        if ca and len(ta) >= 15 and tb.startswith(ta):
            return True
        if cb and len(tb) >= 15 and ta.startswith(tb):
            return True
    elif a[1].split(" @ ")[0] == b[1].split(" @ ")[0]:
        return True
    # two ICEs whose messages one finding's pattern matches
    return same_finding(a[1], b[1], toolchain) is not None


# the kinds whose programs print named values beside their check line
# (catalog-style programs and the data-environment programs)
VALUE_KINDS = ("catalog", "widen", "canary", "dataenv", "oop", "nested")
_PRINTED = re.compile(r"^\s*([A-Za-z_][\w()%.,:]*)\s*=\s*(-?\d[\d.eE+-]*)\s*$",
                      re.M)


def printed_values(stdout: str) -> str:
    """The `name= value` lines a program printed (not its RESULT line), as
    `name=value` pairs in order: '' when it printed none."""
    out = [f"{m.group(1)}={m.group(2)}" for m in _PRINTED.finditer(
        stdout or "") if "RESULT" not in m.group(0)]
    return " ".join(out)


def failure_key(d: dict, cls: str | None = None) -> str:
    """What must stay the same for a failure to count as reproduced: a
    compile failure's message key, a crash's signal, a run error's kind,
    a wrong answer's value (a checksum that changes from run to run is
    nondeterminism), a host fallback, a timeout."""
    cls = cls or outcome_class(d)
    reason = _head(d.get("reason") or "")
    if cls in ("rejected", "ice", "accepted_ignored", "refused"):
        if cls == "ice":
            # CCE's quoted message ("<message> @ <site>": the site may be
            # cut off when a long build path wraps the line), else the
            # compiler-source site or stack frame, else the message
            from offload.engine.confirm import findings as FI
            site = FI.site_of(reason)
            m = _CCE_ICE_MSG.search(reason)
            if m:
                text = m.group(1).rstrip() + ("" if m.group(2) else "...")
                return f"ICE \"{text}\"" + (f" @ {site}" if site else "")
            if site:
                return site
        return message_key(reason)
    if cls == "crash":
        m = re.search(r"\b(SIG[A-Z]+|signal \d+)", reason)
        return m.group(1) if m else "crash"
    if cls == "run_error":
        first = reason.split(";")[0]
        return re.sub(r"0x[0-9a-fA-F]+", "0x", first)[:80] or "run_error"
    if cls == "wrong_answer":
        value = d.get("value")
        if value is None and d.get("checksum") is not None:
            value = f"checksum={d['checksum']}"
        if value is None:
            from offload.engine.confirm.model import value_of
            value = value_of(d.get("stdout") or "")[0]
        bad = d.get("bad_kernels")
        key = f"{value or 'wrong'}" + (f" kernels={','.join(bad)}"
                                       if bad else "")
        # (the review): a program of a kind
        # with per-program signatures that prints its values beside the
        # check keeps them in the key, so repeats that print different
        # values are nondeterminism, not one confirmed `check=fail`
        vals = printed_values(d.get("stdout") or "") \
            if d.get("kind") in VALUE_KINDS else ""
        return key + (f" {vals}" if vals else "")
    if cls == "timeout":
        return "compile_timeout" if "compile" in reason else "timeout"
    return cls


def observe(d: dict) -> tuple[str, str]:
    """(outcome class, failure key) of a row."""
    cls = outcome_class(d)
    return cls, failure_key(d, cls)


def is_failure(cls: str) -> bool:
    return cls not in PASSING and cls not in NOT_EVIDENCE and \
        cls not in CAPACITY_CLASSES


def _flaky(d: dict) -> bool:
    if d.get("flaky"):
        return True
    runs = d.get("runs")
    if isinstance(runs, list) and len(runs) > 1 and all(
            isinstance(r, dict) for r in runs):
        return len({(r.get("outcome"), r.get("value")) for r in runs}) > 1
    return False


def reread(toolchain: str, cls: str, reason: str, compile_log: str,
           lang: str = "f90") -> tuple[str, str] | None:
    """(class, reason) of a stored compile failure read from its compile
    output with the current message tables (offload.engine.harness: every
    message, the worst class), when that differs from the stored class;
    None when it does not, or there is nothing to read. A
    rejection followed by a front end's crash is an ICE."""
    from offload.engine import harness
    if cls not in ("rejected", "ice", "harness_error") or \
            not (compile_log or "").strip():
        return None
    if cls == "harness_error" and not (reason or "").startswith(
            "unclassified_compile_failure"):
        return None
    found = harness.classify_message(toolchain, compile_log,
                                     harness.CATEGORY_ORDER[:-1], lang)
    if found is None:
        return None
    cat, line = found
    if cat == "environment":
        new = ("harness_error", f"environment: {line}")
    else:
        new = ("ice" if cat == "ice" else "rejected",
               f"{harness.CODES[cat]}: {line}")
    # a changed class, or a changed kind of message within it (a
    # diagnostic the tables now read as not implemented)
    if new[0] != cls or (reason or "").split(":", 1)[0] != \
            new[1].split(":", 1)[0]:
        return new
    return None


def compile_section(stderr: str) -> str:
    """The compile output a harness row keeps in its stderr."""
    m = re.search(r"--- compile \(rc=[^)]*\) ---\n(.*?)(?:\n--- run |\Z)",
                  stderr or "", re.S)
    return m.group(1) if m else ""


# --- environments ---------------------------------------------------------------------

# Campaign kinds: the build-directory prefix of a kind's runs
# (no "-": tests/engine/test_findings.py) and its signature mode, the
# "feature" a run-time failure's signature carries: "atom" (a catalog-style
# program id without its version prefix: the versions of one program),
# "program" (the program itself: a random or generated program has no
# feature shared with another), "axis" (a stress axis). An undeclared kind
# is an error (KeyError).
KINDS: dict[str, dict] = {
    "catalog": {"prefix": "harness_", "signature": "atom"},
    "widen": {"prefix": "harness_", "signature": "atom"},
    "canary": {"prefix": "harness_", "signature": "atom"},
    "fuzz": {"prefix": "fuzz_", "signature": "program"},
    "stress": {"prefix": "st_", "signature": "program"},
    "evidence": {"prefix": "confirm_", "signature": "program"},
    "file": {"prefix": "confirm_", "signature": "program"},
    "ompvv": {"prefix": "baseline_", "signature": "program"},
    # The data-environment catalog (tools/dataenv/dataenv.py gate)
    "dataenv": {"prefix": "dataenv_", "signature": "program"},
    # fortran-oop: the derived-type and OOP families (tools/campaigns/oop.py gate)
    "oop": {"prefix": "oop_", "signature": "program"},
    # nested-data: pointer-linked structures in C and Fortran (tools/campaigns/nested.py)
    "nested": {"prefix": "nested_", "signature": "program"},
    # kernel-body statements (tools/campaigns/kbody.py): a wrong answer's key is the
    # failing observables, not their values (the failure is not deterministic)
    "kbody": {"prefix": "kbody_", "signature": "program"},
}
SIGNATURE_MODES = ("atom", "program", "axis")


def register_kind(name: str, prefix: str, signature: str) -> dict:
    """Declare a campaign kind (its build-directory prefix and signature
    mode); a kind that exists with other values is an error."""
    if "-" in prefix or not prefix.endswith("_"):
        raise ValueError(f"prefix {prefix!r}: no '-', ends with '_'")
    if signature not in SIGNATURE_MODES:
        raise ValueError(f"signature mode {signature!r}: one of "
                         f"{SIGNATURE_MODES}")
    want = {"prefix": prefix, "signature": signature}
    if KINDS.get(name, want) != want:
        raise ValueError(f"campaign kind {name} is declared otherwise: "
                         f"{KINDS[name]}")
    KINDS[name] = want
    return want


def kind_of(row: dict) -> dict:
    k = row.get("kind")
    if k not in KINDS:
        raise KeyError(f"undeclared campaign kind {k!r}: declare it in "
                       "offload.engine.gate.KINDS (register_kind)")
    return KINDS[k]


PREFIX = {k: v["prefix"] for k, v in KINDS.items()}


def gate_tmp() -> str:
    """The node-local parent of the gate's build directories (GATE_TMP,
    else STRESS_TMP, else the system temporary directory); a network
    file system is refused (CCE fails to build there and the build path
    changes CCE ftn's behaviour)."""
    import subprocess
    import tempfile
    d = os.environ.get("GATE_TMP") or os.environ.get("STRESS_TMP") or \
        tempfile.gettempdir()
    os.makedirs(d, exist_ok=True)
    fs = subprocess.run(["stat", "-f", "-c", "%T", d], capture_output=True,
                        text=True).stdout.strip().lower()
    if fs in ("lustre", "nfs", "gpfs", "nfs4", "fuse.sshfs") or \
            d.startswith(("/p/", "/usr/workspace", "/g/g")):
        raise RuntimeError(f"gate build root {d} is on {fs or 'a network '}"
                           "file system: use node-local storage")
    return d


def cell_id(row: dict) -> str:
    """A stable identifier of a failing cell (its campaign, program,
    toolchain, mode and variant)."""
    if row.get("cell"):
        return row["cell"]
    parts = [row.get("campaign", ""), row.get("kind", ""),
             str(row.get("ident") or row.get("program_id") or
                 row.get("id") or ""), row.get("toolchain", ""),
             str(row.get("mode", row.get("xnack", ""))),
             row.get("variant", "") or row.get("opt", "")]
    return "|".join(parts)


def _tag(row: dict) -> str:
    return hashlib.sha256(cell_id(row).encode()).hexdigest()[:8]


def _letters(tag: str, n: int = 14) -> str:
    """`n` upper case letters derived from a hex tag (no digit)."""
    h = hashlib.sha256(tag.encode()).digest()
    return "".join(chr(ord("A") + b % 26) for b in h[:n])


def environments(row: dict, root: str | None = None) -> list[dict]:
    """The four environments of one failure: dicts with ``env`` (a-d),
    ``path`` (the build directory), ``node`` ("same": the row's node or a
    node of its machine; "other": another node), ``environment`` (what
    differs from the original: "original", "build_dir", "node") and
    ``repeat`` (0, or 1 for the second run in (a))."""
    root = root if root is not None else gate_tmp()
    orig = row.get("build_dir") or ""
    if orig and orig != "-" and os.path.isabs(orig):
        a_path = orig
    else:
        a_path = os.path.join(root, kind_of(row)["prefix"] + _tag(row))
    b_path = os.path.join(root, "GATE" + _letters(_tag(row)))
    return [
        {"env": "a", "path": a_path, "node": "same",
         "environment": "original", "repeat": 0},
        {"env": "b", "path": b_path, "node": "same",
         "environment": "build_dir", "repeat": 0},
        {"env": "c", "path": a_path, "node": "other",
         "environment": "node", "repeat": 0},
        {"env": "d", "path": a_path, "node": "same",
         "environment": "original", "repeat": 1},
    ]


def _group(env: str) -> str:
    """(a) and (d) are one environment (two runs)."""
    return "a" if env in ("a", "d") else env


# --- the verdict ----------------------------------------------------------------------

def killed(d: dict) -> bool:
    """A run ended by SIGKILL: an external kill or the OOM killer of the
    job's memory cgroup (the gate's parallel reruns can exhaust a node's
    memory), not the program's own behaviour."""
    head = _head(d.get("reason") or "")
    return "SIGKILL" in head or bool(re.search(
        r"(?:TERMINATED by |killed by |receipt of )signal 9\b", head)) or \
        str(d.get("checksum")) == "SIGKILL"


# one-host machines: their (c) is another GPU of the host, so a rerun's node
# keeps its ":gpuN"; on every other machine (c) is another compute node, so
# a GPU or GCD of (a)'s node is no node change (parity-10-29)
from offload.engine.confirm.machines import load as _machines  # noqa: E402
ONE_HOST = tuple(m.name for m in _machines().values() if m.one_host)


def node_key(node: str | None) -> str:
    """The part of a rerun's node that (c) must change: the host (Tuolumne,
    Tioga: "tioga39:gpu5" -> "tioga39"), or host and GPU on a one-host
    machine (``ONE_HOST``)."""
    node = node or ""
    host = node.split(":", 1)[0]
    return node if host.split("-", 1)[0].split(".", 1)[0] in ONE_HOST \
        else host


def valid_reruns(reruns: list[dict], row: dict | None = None
                 ) -> list[dict]:
    """The reruns that are evidence: not a harness error, not killed by
    signal 9 unless the stored row was too, and an environment (c) only
    on another node than (a) and in the path of (a) (a (c) in
    another path confounds node and path; kept only when no (c) in (a)'s
    path exists)."""
    keep_killed = row is not None and killed(row)
    if row is not None:
        # a rerun is read as its row's kind and toolchain (the failure key
        # of a value kind keeps the printed values)
        reruns = [r if r.get("kind") and r.get("toolchain") else
                  {**r, "kind": r.get("kind") or row.get("kind"),
                   "toolchain": r.get("toolchain") or row.get("toolchain")}
                  for r in reruns]
    out = [r for r in reruns if outcome_class(r) not in NOT_EVIDENCE
           and (keep_killed or not killed(r))]
    a_paths = {r.get("path") for r in out if r.get("env") in ("a", "d")
               and r.get("path")}
    # a (c) on the node (wingtip: GPU) of the row's (a) is no node change
    a_nodes = {node_key(r.get("node")) for r in out
               if r.get("env") in ("a", "d") and r.get("node")}
    out = [r for r in out if r.get("env") != "c" or not r.get("node")
           or node_key(r.get("node")) not in a_nodes]
    same_c = [r for r in out if r.get("env") == "c" and
              r.get("path") in a_paths]
    if same_c:
        out = [r for r in out if r.get("env") != "c" or r in same_c]
    return out


def _version(tb: str | None) -> str:
    return (tb or "").split(" [modules")[0].strip()


def changed_since(row: dict, reruns: list[dict]) -> str | None:
    """What the stored row's provenance says changed since it ran: the
    toolchain build (version banner) or the run environment (env_hash),
    when both sides recorded it; None when nothing recorded differs (a row
    recorded before these fields existed records neither: it is a run of (a))."""
    then = _version(row.get("toolchain_build"))
    now = {_version(r.get("toolchain_build")) for r in reruns
           if r.get("toolchain_build")}
    if then and now and then not in now:
        return f"toolchain build: {then} then, {'; '.join(sorted(now))} now"
    eh = row.get("env_hash")
    ehs = {r.get("env_hash") for r in reruns if r.get("env_hash")}
    if eh and ehs and eh not in ehs:
        return "run environment (env_hash) differs"
    return None


def _distinct(obs: list, toolchain: str | None = None) -> list:
    out = []
    for o in obs:
        if not any(same(o, x, toolchain) for x in out):
            out.append(o)
    return out


def verdict(row: dict, reruns: list[dict]) -> str:
    """The gate's verdict on one failing row (see the module docstring).
    A row whose stored repeats disagree is nondeterministic without a
    rerun; otherwise raises ValueError when no rerun is valid."""
    if _flaky(row):
        return "nondeterministic"
    valid = valid_reruns(reruns, row)
    if not valid:
        raise ValueError("no valid rerun: the row has no verdict")
    obs = [observe(r) for r in valid]
    if not any(is_failure(c) for c, _ in obs):
        return "not_reproduced"
    if any(_flaky(r) for r in valid):
        return "nondeterministic"
    orig = observe(row)
    tc = row.get("toolchain")
    changed = changed_since(row, valid)
    groups: dict[str, list] = defaultdict(list)
    if not changed:
        groups["a"].append(orig)            # the stored row ran in (a)
    for r, o in zip(valid, obs):
        groups[_group(r.get("env", "a"))].append(o)
    if any(not same(g[0], o, tc) for g in groups.values() for o in g[1:]):
        return "nondeterministic"
    # values that scatter: three or more distinct failures, or (b) and (c)
    # differing with neither equal to (a)
    if len(_distinct(obs + ([] if changed else [orig]), tc)) >= 3:
        return "nondeterministic"
    ga, gb, gc = groups.get("a"), groups.get("b"), groups.get("c")
    if ga and gb and gc and not same(gb[0], gc[0], tc) and \
            not same(ga[0], gb[0], tc) and not same(ga[0], gc[0], tc):
        return "nondeterministic"
    if all(same(o, orig, tc) for o in obs):
        return "confirmed"
    return "environment"


_CLASSES = (("lower", r"[a-z]"), ("upper", r"[A-Z]"), ("digit", r"\d"),
            ("underscore", r"_"), ("dash", r"-"), ("dot", r"\."))


def _path_traits(path: str) -> set:
    name = path or ""
    out = {f"has {k}" for k, rx in _CLASSES if re.search(rx, name)}
    if re.search(r"-1(?!\d)", name):
        out.add("has '-1' not followed by a digit")
    out.add(f"length {len(name)}")
    return out


def condition(row: dict, reruns: list[dict]) -> str:
    """What separates the failing environments from the others (for an
    ``environment`` verdict): the build directory (and the character
    classes only the failing paths have), the node, the toolchain build,
    or the original run alone. A person pins it down (data/reports/
    gate.md)."""
    valid = valid_reruns(reruns, row)
    orig = observe(row)
    ch = changed_since(row, valid)
    tc = row.get("toolchain")
    same_ = [r for r in valid if same(observe(r), orig, tc)]
    other = [r for r in valid if not same(observe(r), orig, tc)]
    parts = []
    if not same_ and ch:
        return ("changed since: " + ch + "; every rerun gives "
                + ", ".join(sorted({f'{c} ({k[:60]})' for c, k in map(
                    observe, valid)})))
    if not same_:
        tb_then = row.get("toolchain_build") or "not recorded"
        tb_now = sorted({r.get("toolchain_build") or "not recorded"
                         for r in valid})
        parts.append(
            "original run only: every rerun gives "
            + ", ".join(sorted({f'{c} ({k[:60]})' for c, k in map(
                observe, valid)}))
            + f"; toolchain then: {tb_then}; now: {'; '.join(tb_now)}")
        return "; ".join(parts)
    envs_same = sorted({r.get("env", "?") for r in same_})
    envs_other = sorted({r.get("env", "?") for r in other})
    paths_s = sorted({r.get("path") or r.get("build_dir") or "" for r in
                      same_})
    paths_o = sorted({r.get("path") or r.get("build_dir") or "" for r in
                      other})
    if set(paths_s).isdisjoint(paths_o):
        # the characters of the part of the paths that differs (below
        # their common parent)
        allp = [p for p in paths_s + paths_o if p]
        common = os.path.commonpath(allp) if len(allp) > 1 else ""

        def part(p: str) -> str:
            return p[len(common):] if common and p.startswith(common) \
                else p
        ts = set.intersection(*[_path_traits(part(p)) for p in paths_s]) \
            if paths_s else set()
        to = set.union(*[_path_traits(part(p)) for p in paths_o]) \
            if paths_o else set()
        only = sorted(t for t in ts - to if not t.startswith("length"))
        parts.append(f"build directory: the failure in {paths_s} "
                     f"(env {','.join(envs_same)}), "
                     f"{', '.join(sorted({observe(r)[0] for r in other}))}"
                     f" in {paths_o} (env {','.join(envs_other)})"
                     + (f"; only the failing paths: {', '.join(only)}"
                        if only else ""))
    nodes_s = sorted({r.get("node") or "" for r in same_})
    nodes_o = sorted({r.get("node") or "" for r in other})
    if set(nodes_s).isdisjoint(nodes_o) and any(nodes_s) and any(nodes_o):
        parts.append(f"node: the failure on {nodes_s}, not on {nodes_o}")
    tb_s = {r.get("toolchain_build") for r in same_}
    tb_o = {r.get("toolchain_build") for r in other}
    if tb_s.isdisjoint(tb_o) and any(tb_s) and any(tb_o):
        parts.append(f"toolchain build: {sorted(tb_s)} vs {sorted(tb_o)}")
    return "; ".join(parts) or (
        f"no recorded difference between env {','.join(envs_same)} and "
        f"env {','.join(envs_other)}")


def judge(row: dict, reruns: list[dict]) -> dict:
    """The verdict with its context: ``legality_review``, ``condition``
    (environment verdicts), the environments seen and missing, whether (c)
    really ran on another node, and every rerun's outcome."""
    v = verdict(row, reruns)
    valid = valid_reruns(reruns, row)
    if v == "nondeterministic" and _flaky(row) and not valid:
        # not rerun: its own stored repeats disagree; counted, not queued
        # (the review queue holds rerun rows)
        return {"verdict": v, "legality_review": False, "envs": [],
                "missing": list(ENVS), "node_distinct": False,
                "original": "|".join(observe(row)), "reruns": [],
                "own_repeats": True}
    seen = sorted({r.get("env") for r in valid})
    nodes = {r.get("env"): r.get("node") for r in valid}
    out = {"verdict": v, "legality_review": v in REVIEW,
           "envs": seen, "missing": sorted(set(ENVS) - set(seen)),
           "node_distinct": bool(nodes.get("c")) and
           node_key(nodes.get("c")) not in
           (node_key(nodes.get("a")), node_key(nodes.get("d"))),
           "original": "|".join(observe(row)),
           "reruns": [{"env": r.get("env"),
                       "outcome": "|".join(observe(
                           {**r, "kind": r.get("kind") or row.get("kind"),
                            "toolchain": r.get("toolchain") or
                            row.get("toolchain")}))[:200],
                       "path": r.get("path", ""), "node": r.get("node", "")}
                      for r in reruns]}
    ch = changed_since(row, valid)
    if ch:
        out["changed_since"] = ch
    if _flaky(row):
        out["own_repeats"] = True
    if v == "environment":
        out["condition"] = condition(row, reruns)
        out["needs_condition"] = True
    return out


# --- the budget -----------------------------------------------------------------------

def inheritable(row: dict) -> bool:
    """A failure whose verdict another row of its signature may stand for:
    a compile-time failure whose key names its defect (a diagnostic's
    message key, an ICE's message or compiler-source site); never a
    run-time failure or a generic crash report."""
    cls, key = observe(row)
    return cls in COMPILE_CLASSES and not generic(key)


def signature(row: dict) -> str:
    """The signature of a failure: toolchain, outcome class and failure
    key; a compile-time failure whose key names no defect, and every
    run-time failure, also carry the program's feature (the kind's
    signature mode, ``KINDS``: catalog-style atom, the program, or the
    stress axis)."""
    if row.get("signature"):
        return row["signature"]
    cls, key = observe(row)
    tc = row.get("toolchain", "")
    if cls in COMPILE_CLASSES and not generic(key):
        return f"{tc}|{cls}|{key}"
    return f"{tc}|{cls}|{feature(row)}|{key}"


def feature(row: dict) -> str:
    mode = kind_of(row)["signature"]
    ident = str(row.get("ident", ""))
    if mode == "atom":
        return re.sub(r"^(?:omp|acc)\d\d-", "", ident)
    if mode == "axis":
        return str(row.get("axis", "")).split(".")[0] + "|" + ident
    return ident


def coarse(row: dict) -> str:
    """The round-robin group of a run-time failure for sampling: toolchain,
    class and the campaign's run or variant (never a signature)."""
    cls, _ = observe(row)
    loc = row.get("locator") or {}
    grp = loc.get("run") or loc.get("variant") or row.get("axis") or \
        feature(row)
    return f"{row.get('toolchain', '')}|{cls}|{grp}"


# estimated wall seconds of one rerun (compile, or compile and run) by
# compiler family when the row has no recorded time
# (gcc: GCC 16.2 with offloading; its compiles measured 0.3 s (Tioga) and
# 0.8 s (wingtip) median over the catalog, results/gcc/<tc>/sweep.*.jsonl;
# 2 s allows for the gate's concurrent load)
from offload.engine.toolchains import registry as _registry  # noqa: E402
COMPILE_S = {f.id: f.compile_s for f in _registry().families.values()}
RUN_S = 10.0
KILL_AFTER_S = 10
COMPILE_LIMIT_S = {"catalog": 900, "widen": 900, "canary": 900,
                   "fuzz": 600, "stress": 900, "evidence": 900,
                   "file": 900, "dataenv": 900, "ompvv": 900, "oop": 900,
                   "nested": 900, "kbody": 900}


def cost_s(row: dict) -> float:
    """Estimated wall seconds of one rerun of a row: its recorded compile
    and run times when it has them; a compile timeout at the compile
    limit, a run timeout at the run limit, each plus the kill-after (review
    cost model)."""
    from offload.engine.confirm.machines import family_of
    try:
        fam = family_of(row.get("toolchain", ""))
    except Exception:
        fam = "cce"
    comp = float(row.get("compile_s") or COMPILE_S.get(fam, 30.0))
    cls = outcome_class(row)
    reason = row.get("reason") or ""
    if cls == "timeout" and "compile" in reason:
        return float(COMPILE_LIMIT_S.get(row.get("kind"), 900)) + \
            KILL_AFTER_S
    if cls in ("rejected", "ice", "accepted_ignored", "compile_oom"):
        return comp
    if cls == "timeout":
        return comp + float(row.get("timeout_s") or 300) + KILL_AFTER_S
    return comp + float(row.get("run_s") or RUN_S)


def plan(rows: list[dict], budget_s: float, per_signature: int = PER_SIGNATURE,
         known: set | frozenset = frozenset(), cost=cost_s,
         envs: int = len(ENVS), overhead_s: float = 0.0) -> dict:
    """Which rows to rerun under `budget_s` (each row costs
    ``envs * cost(row)``; `overhead_s`, the queue and idle-tail allowance
    of the runs, is spent first). Returns ``{"rows": [...], "spent_s",
    "total_s", "over_budget", "budget_s"}``; each row dict gets ``sample``:
    "own" (its stored repeats disagree: nondeterministic, no rerun), "all"
    (within budget, every row), "new" (the first row of a compile-time
    defect signature not in `known`), "runtime" (a run-time or generic
    failure chosen round-robin), "sampled" (up to `per_signature` per
    compile-time signature), "inherited" (not rerun; takes its signature's
    verdict) or "unchecked" (not rerun; no verdict to inherit)."""
    rows = [dict(r) for r in rows]
    for r in rows:
        r["signature"] = signature(r)
    own = [r for r in rows if _flaky(r)]
    for r in own:
        r["sample"] = "own"
    todo = [r for r in rows if not _flaky(r)]
    total = overhead_s + sum(envs * cost(r) for r in todo)
    if total <= budget_s:
        for r in todo:
            r["sample"] = "all"
        return {"rows": rows, "spent_s": total, "total_s": total,
                "over_budget": False, "budget_s": budget_s}
    spent = overhead_s
    chosen: dict[int, str] = {}

    def take(r, how) -> bool:
        nonlocal spent
        c = envs * cost(r)
        if spent + c > budget_s:
            return False
        chosen[id(r)] = how
        spent += c
        return True
    groups: dict[str, list] = {}
    for r in sorted((r for r in todo if inheritable(r)),
                    key=lambda r: (r["signature"], cell_id(r))):
        groups.setdefault(r["signature"], []).append(r)
    order = sorted(groups, key=lambda sg: hashlib.sha256(
        sg.encode()).hexdigest())
    for sig in order:                       # tier 1: every new defect
        if sig not in known:
            take(groups[sig][0], "new")
    over = any(sig not in known and id(groups[sig][0]) not in chosen
               for sig in order)
    rt: dict[str, list] = {}                # tier 2: run-time, round-robin
    for r in sorted((r for r in todo if not inheritable(r)),
                    key=lambda r: (coarse(r), hashlib.sha256(
                        cell_id(r).encode()).hexdigest())):
        rt.setdefault(coarse(r), []).append(r)
    rorder = sorted(rt, key=lambda g: hashlib.sha256(g.encode()).hexdigest())
    k = 0
    while any(k < len(rt[g]) for g in rorder):
        for g in rorder:
            if k < len(rt[g]):
                take(rt[g][k], "runtime")
        k += 1
    for k in range(per_signature):          # tier 3: more per signature
        for sig in order:
            g = groups[sig]
            if k < len(g) and id(g[k]) not in chosen:
                take(g[k], "sampled")
    for r in todo:
        r["sample"] = chosen.get(id(r)) or (
            "inherited" if inheritable(r) else "unchecked")
    return {"rows": rows, "spent_s": spent, "total_s": total,
            "over_budget": over, "budget_s": budget_s}


def inherit(planned: list[dict], verdicts: dict) -> dict:
    """Verdicts for every planned row: a rerun row's own (``verdicts``:
    cell id -> verdict); a row whose stored repeats disagree,
    ``nondeterministic`` on its own evidence; an inheritable row that was
    not rerun (or whose rerun gave no verdict), its signature's worst
    verdict among the rerun rows, marked ``inherited``; every other row
    not rerun, ``unchecked``."""
    by_sig: dict[str, list] = defaultdict(list)
    for r in planned:
        v = verdicts.get(cell_id(r))
        # only a rerun verdict passes on (not_a_failure, illegal: the
        # row's own reading)
        if v in WORST_FIRST and r.get("sample") not in ("inherited",
                                                         "unchecked", "own"):
            by_sig[r["signature"]].append(v)
    out = {}
    for r in planned:
        cid = cell_id(r)
        if _flaky(r):
            out[cid] = {"verdict": "nondeterministic", "inherited": False,
                        "own_repeats": True}
            continue
        if cid in verdicts and r.get("sample") not in ("inherited",
                                                       "unchecked"):
            out[cid] = {"verdict": verdicts[cid], "inherited": False}
            continue
        vs = by_sig.get(r["signature"]) if inheritable(r) else None
        if vs:
            worst = min(vs, key=WORST_FIRST.index)
            out[cid] = {"verdict": worst, "inherited": True,
                        "from": len(vs)}
        else:
            out[cid] = {"verdict": "unchecked", "inherited": False}
    return out


# --- reading verdicts -----------------------------------------------------------------

VERDICTS_FILE = RESULTS / "verdicts.jsonl"


def load_verdicts(path: Path | None = None) -> dict:
    """cell id -> verdict record of the gate's store (later lines win)."""
    path = Path(path) if path else VERDICTS_FILE
    out = {}
    if not path.is_file():
        return out
    for ln in path.read_text().splitlines():
        if ln.strip():
            d = json.loads(ln)
            out[d["cell"]] = d
    return out


_BY_CASE: dict = {}


def _case_index(path: Path | None = None) -> dict:
    """(kind, ident, toolchain, row key) -> verdict record; the catalog
    and the widened catalog are one confirmer kind ("catalog")."""
    key = str(path or VERDICTS_FILE)
    p = Path(key)
    stamp = p.stat().st_mtime if p.is_file() else None
    hit = _BY_CASE.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    idx = {}
    for d in load_verdicts(p).values():
        kind = "catalog" if d.get("kind") in ("catalog", "widen") else \
            d.get("kind")
        idx[(kind, str(d.get("ident")), d.get("toolchain"),
             int(d.get("xnack") or 0))] = d
    _BY_CASE[key] = (stamp, idx)
    return idx


def verdict_of_case(case, path: Path | None = None) -> dict | None:
    """The gate's verdict record of a confirmer case's own cell, or None
    (not gated)."""
    from offload.engine.confirm import machines as M
    try:
        x = M.load()[case.machine].row_key(case.mode)
    except Exception:
        return None
    return _case_index(path).get((case.program.kind, case.program.ident,
                                  case.toolchain, int(x)))


# The decisions on the review queue: one per rerun row, keyed by its
# cell id; a decision applies to the row it names only and never to the
# rows that inherit from it (they keep the gate's own semantics)
DECISIONS_FILE = ROOT / "catalog" / "gate_queue.yaml"


def load_decisions(path: Path | None = None) -> dict:
    """cell id -> {verdict, counts_as, group, finding, k} of the decided
    review queue (catalog/gate_queue.yaml); {} when there is none."""
    import yaml
    path = Path(path) if path else DECISIONS_FILE
    if not path.is_file():
        return {}
    doc = yaml.safe_load(path.read_text()) or {}
    return {e["cell"]: {"decision": e.get("verdict"),
                        "counts_as": e.get("counts_as"),
                        "group": e.get("group"),
                        "finding": e.get("finding") or "",
                        "k": e.get("k")}
            for e in doc.get("entries", []) if e.get("cell")}


def counts(v: dict | None) -> bool | None:
    """Whether a verdict record makes its row count as a compiler
    failure: a decision's ``counts_as`` first, else the
    verdict (``confirmed``, or ``unchecked``: the row keeps its previous
    outcome, flagged); None for no record."""
    if v is None:
        return None
    if v.get("counts_as") in ("failure", "none"):
        return v["counts_as"] == "failure"
    return v.get("verdict") in ("confirmed", "unchecked")


def counts_as_failure(row: dict, verdicts: dict | None = None) -> bool:
    """Whether a failing row counts as a compiler failure: its gate
    verdict is ``confirmed`` (own or inherited); a row the gate has not
    seen keeps its outcome (results recorded before the gate
    count until it has been run over them)."""
    if not is_failure(outcome_class(row)):
        return False
    v = (verdicts if verdicts is not None else load_verdicts()).get(
        cell_id(row))
    if v is None:
        g = row.get("gate") or ""
        return g in ("", "pending", "confirmed", "n/a")
    # a decided row counts as its decision says; an unchecked row keeps
    # its previous outcome (flagged); an illegal program's failure never
    # counts
    return bool(counts(v))


def hook(queue: Path):
    """A harness gate hook (offload.engine.harness.GATE_HOOKS) that appends
    every failing Result to `queue` as one JSON line."""
    import dataclasses

    def append(res) -> None:
        d = dataclasses.asdict(res)
        with open(queue, "a") as fh:
            fh.write(json.dumps(d) + "\n")
    return append
