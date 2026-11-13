"""Dev-half report of the ``hecbench`` campaign (data/reports/hecbench.md).

Gives outcome classes per toolchain and memory mode, the failures that
count as evidence, their signatures, and which are already findings.
A row's class is the gate's outcome class (``offload.engine.gate.outcome_class``),
with link-time build failures split off as ``link_failure``. A program that
no toolchain could build because a header or library is missing is moved to
the excluded programs (``non_compiler_programs``).

A failing cell is evidence only when the reproduction gate confirmed it and
a compiler of another family ran the program correctly in the same memory
mode (``witnessed``). A failure signature is (compiler family, class,
normalized message or output line) of an evidence cell.

``dev_rows`` refuses the run directory of the sealed half."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from offload.engine import gate as GT

CLASSES = ("ok", "compile_reject", "ice", "link_failure", "run_error", "crash", "timeout",
           "wrong_answer", "harness_error")
FAILING = tuple(c for c in CLASSES if c not in ("ok", "harness_error"))
NON_COMPILER = re.compile(
    r"file not found|cannot open (?:source|include|input) file|no such file or directory|"
    r"fatal error: [^\n]*: No such|link_undefined_symbol: other symbol|"
    r"could not find|Cannot open include file", re.I)


def row_class(r: dict) -> str:
    """The table class of a result row."""
    cls = GT.outcome_class({**r, "kind": "hecbench"})
    reason = str(r.get("reason") or "")
    if cls in ("rejected", "ice"):
        if cls == "ice":
            return "ice"
        return "link_failure" if r.get("stage") == "link" or reason.startswith("link_undefined") \
            else "compile_reject"
    return {"correct_on_device": "ok", "unobservable": "ok"}.get(cls, cls if cls in CLASSES else "harness_error")


def non_compiler_programs(rows: list[dict]) -> dict:
    """program id -> why: every attempted cell of the program fails to compile or link on a
    missing header, file or library symbol."""
    by = defaultdict(list)
    for r in rows:
        by[r["program_id"]].append(r)
    out = {}
    for pid, rs in by.items():
        att = [r for r in rs if row_class(r) != "harness_error"]
        if att and all(row_class(r) in ("compile_reject", "link_failure") and
                       NON_COMPILER.search(str(r.get("reason") or "")) for r in att):
            out[pid] = "a header or library is missing on every toolchain: " + \
                str(att[0].get("reason"))[:100]
    return out


def timeout_cells(rows: list[dict], withheld: set) -> list[tuple]:
    """(program, toolchain, row key) of the cells that timed out in a *run* (not in a compile) at the
    original limit, programs of a withheld licence class left out, in a fixed order."""
    out = {(r["program_id"], r["toolchain"], r["xnack"]) for r in rows
           if r["program_id"] not in withheld and row_class(r) == "timeout"
           and str(r.get("reason") or "").startswith("timeout:")}
    return sorted(out)


def timeout_verdict(r: dict) -> str:
    """How a cell fared at the longer limit: ``finished ok`` (a slow kernel), ``finished failing``
    (it ends, and fails some other way: a candidate for the gate) or ``still timing out``."""
    cls = row_class(r)
    if cls == "ok":
        return "finished ok"
    if cls == "timeout" and str(r.get("reason") or "").startswith("timeout:"):
        return "still timing out"
    return "finished failing"


def family_of(toolchain: str) -> str:
    from offload.engine.toolchains import registry
    return registry().toolchains[toolchain].family_id


def witnessed(row: dict, rows_of_program: list[dict], mode_of) -> list[str]:
    """The compiler families other than the row's whose cells for the same program were
    correct on the device, in the row's own memory mode."""
    fam, mode = family_of(row["toolchain"]), mode_of(row["xnack"])
    out = set()
    for r in rows_of_program:
        f = family_of(r["toolchain"])
        if f == fam or row_class(r) != "ok":
            continue
        if mode_of(r["xnack"]) != mode:
            continue
        out.add(f)
    return sorted(out)


# the runtime or driver message a crash or a run error carries (the first one in the output)
RUNTIME_MSG = re.compile(
    r"Memory access fault by GPU|CRAY_ACC_ERROR[^\n]{0,50}|Libomptarget (?:error|fatal)[^\n]{0,50}|"
    r"libgomp: [^\n]{0,50}|hip\w*Error\w*|hipStreamSynch\w*|GCN Kernel Aborted|Segmentation fault|"
    r"Floating point exception|terminate called after throwing[^\n]{0,40}|std::bad_alloc|"
    r"illegal memory access|out of memory|HSA_STATUS_ERROR\w*|Unhandled exception|Aborted", re.I)


def signature_key(r: dict) -> str:
    cls = row_class(r)
    reason = str(r.get("reason") or "")
    if cls in ("crash", "run_error"):
        m = RUNTIME_MSG.search(reason)
        if cls == "run_error":
            code = re.match(r"exit_status=(\d+)", reason)
            head = f"exit_status={code.group(1)}" if code else "run_error"
        else:
            head = GT.failure_key({**r, "kind": "hecbench"}, cls)
        msg = re.sub(r"0x[0-9a-fA-F]+|\d+", "N", m.group(0).strip()) if m else "no runtime message"
        return f"{head}: {msg}"
    if cls == "wrong_answer":
        head = re.sub(r"\d+(\.\d+)?([eE][-+]?\d+)?", "N", reason.split(";")[0])
        return head[:90]
    if cls == "link_failure":
        if reason.startswith("link_undefined_symbol"):
            return re.sub(r"symbol \S+", "symbol X", reason.split(";")[0])[:90]
        return GT.failure_key({**r, "kind": "hecbench"}, "rejected")
    return GT.failure_key({**r, "kind": "hecbench"}, {"compile_reject": "rejected", "link_failure": "rejected"}.get(cls, cls))


def split_cells(rows: list[dict], verdicts: dict, mode_of, cell_of, excluded: set,
                envs: dict | None = None) -> dict:
    """{'evidence': [...], 'unconfirmed': [...]} cells (dicts: the row, its class, signature
    key, family, verdict, witnesses, reason). ``envs`` (cell -> the gate environments that
    ran for it): a verdict a cell earned itself (not inherited from its signature) counts only
    when all four of a, b, c, d ran; the gate judges the reruns it has, and a job cut short
    leaves some cells with fewer."""
    by = defaultdict(list)
    for r in rows:
        by[r["program_id"]].append(r)
    ev, un = [], []
    for r in rows:
        cls = row_class(r)
        if cls in ("ok", "harness_error") or r["program_id"] in excluded:
            continue
        cid = cell_of(r["program_id"], r["toolchain"], r["xnack"])
        vd = verdicts.get(cid) or {}
        v = vd.get("verdict", "unchecked")
        if v == "confirmed" and envs is not None and not vd.get("inherited") and \
                not {"a", "b", "c", "d"} <= set(envs.get(cid, ())):
            v = "incomplete"
        wit = witnessed(r, by[r["program_id"]], mode_of)
        cell = {"row": r, "class": cls, "key": signature_key(r), "family": family_of(r["toolchain"]),
                "verdict": v, "witnesses": wit, "mode": mode_of(r["xnack"])}
        if v == "confirmed" and wit:
            ev.append(cell)
        else:
            if not wit:
                cell["why_not"] = "no compiler of another family ran the program correctly in this mode"
            else:
                cell["why_not"] = "the gate did not confirm it (" + (
                    "only environments " + ",".join(sorted(envs.get(cid, ()))) + " ran" if v == "incomplete"
                    else v) + ")"
            un.append(cell)
    return {"evidence": ev, "unconfirmed": un}


def signatures(cells: list[dict]) -> list[dict]:
    """The evidence cells grouped by (family, class, key)."""
    g = defaultdict(lambda: {"programs": set(), "toolchains": set(), "modes": set(), "reason": ""})
    for c in cells:
        k = (c["family"], c["class"], c["key"])
        g[k]["programs"].add(c["row"]["program_id"])
        g[k]["toolchains"].add(c["row"]["toolchain"])
        g[k]["modes"].add(c["mode"])
        g[k]["reason"] = g[k]["reason"] or str(c["row"].get("reason") or "")
    out = [{"family": k[0], "class": k[1], "key": k[2], **{a: sorted(b) if isinstance(b, set) else b
                                                          for a, b in v.items()}}
           for k, v in g.items()]
    return sorted(out, key=lambda s: (-len(s["programs"]), s["family"], s["class"], s["key"]))


def existing_findings(sig: dict, index: list[dict], related: bool = False) -> list[str]:
    """The files of data/findings/index.yaml that explain a signature: the same outcome
    class, a toolchain of the same family and a message pattern the signature's message
    matches. A finding without a message pattern (a run-time failure keyed by its
    constructs) is only *related* (same family and outcome class): ``related=True`` returns
    those instead."""
    from offload.engine.toolchains import registry
    fams = registry().toolchains
    # a link failure is a rejection, or (the offload assembler refusing the compiler's own output) an ICE
    want = {"compile_reject": ("rejected",), "link_failure": ("rejected", "ice")}.get(sig["class"], (sig["class"],))
    out = []
    for f in index:
        if f.get("outcome") not in want:
            continue
        if not any(t in fams and fams[t].family_id == sig["family"] for t in f.get("toolchains") or ()):
            continue
        pat = f.get("message")
        same = bool(pat) and message_matches(pat, sig["reason"])
        if same == related:
            continue            # exact: the message matches; related: every other finding of the
        out.append(f["file"])   # family and outcome class (a finding keyed by constructs included)
    return out


_VOLATILE = re.compile(r"0x[0-9a-fA-F]+|\d+")


def _norm(text: str) -> str:
    """A message without addresses, handles, node ids and numbers."""
    return " ".join(_VOLATILE.sub("N", text).split())


def message_matches(pattern: str, reason: str) -> bool:
    """Whether a finding's message (a regular expression, or a literal captured from one run with
    its addresses and node ids) matches a signature's reason: as a pattern, or as a literal after
    both sides lose their numbers and addresses (the literal's first 30 characters must occur)."""
    try:
        if re.search(pattern, reason):
            return True
    except re.error:
        pass
    lit = _norm(pattern)[:30]
    return len(lit) >= 15 and lit in _norm(reason)


def merge_same_programs(sigs: list[dict]) -> list[dict]:
    """Signatures of one family over the same set of programs are one failure seen through two
    outcome classes (a GPU fault is a crash on one release and a runtime error on another): the
    first stays, the others are listed in ``also``, and its toolchains and modes are the union."""
    out: dict = {}
    for s in sigs:
        k = (s["family"], tuple(s["programs"]))
        if k not in out:
            out[k] = {**s, "also": []}
            continue
        m = out[k]
        m["also"].append({"class": s["class"], "key": s["key"]})
        m["toolchains"] = sorted(set(m["toolchains"]) | set(s["toolchains"]))
        m["modes"] = sorted(set(m["modes"]) | set(s["modes"]))
    return list(out.values())


def outcome_table(rows: list[dict], mode_of, excluded: set) -> list[dict]:
    """[{toolchain, mode, built, <class>: n ...}] over the programs not excluded."""
    cnt = defaultdict(Counter)
    for r in rows:
        if r["program_id"] in excluded:
            continue
        c = row_class(r)
        k = (r["toolchain"], mode_of(r["xnack"]))
        cnt[k][c] += 1
        if c not in ("compile_reject", "ice", "link_failure", "harness_error"):
            cnt[k]["built"] += 1
    return [{"toolchain": t, "mode": m, **{c: cnt[(t, m)].get(c, 0) for c in ("built",) + CLASSES}}
            for (t, m) in sorted(cnt)]


def markdown_table(table: list[dict]) -> str:
    cols = ["toolchain", "mode", "built"] + list(CLASSES)
    L = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in table:
        L.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(L)
