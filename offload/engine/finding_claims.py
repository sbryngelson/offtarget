"""Check a finding's header claims against the recorded rows
(tools/repo/check_findings.py, rows from offload.engine.finding_rows).

* ``control <path>``: every control the header names has a passing row on each
  compiler it is claimed for.
* ``other-families <tc>``: each toolchain in a positive ``other families:``
  clause has a passing row of the program.
* ``gate-envs``, ``gate-c-node``: a header saying the gate ran in four environments (a-d) has,
  per failing compiler, a GPU with a failing row in each, and (c) differs from (a) in node.
* ``gate-cells``, ``signature-count``: the stated counts match the rows. Headers
  citing campaign files under results/ are judged only with results/ present.
* ``same-way <tcs>``: toolchains said to "fail the same way" have failing rows
  with one signature (offload.engine.site.matrix.signature).
* ``todo``: no TODO(human) is left.
A claim whose rows no available source holds is not reported, and ``full`` is False."""
from __future__ import annotations

import re
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass

from offload.engine import finding_header as H
from offload.engine import finding_rows as R
from offload.engine.finding_rows import Evidence

ENVS = "abcd"
_ENVS = re.compile(r"\(a-d\b|four environments|environments a-d|a, b, c, d|all four\b", re.I)
_CNODE = re.compile(r"\(c\)[^.;]*?another\s+(node|GPU|GCD|host)", re.I)
_SAME = re.compile(r"\bthe same way\b|\b(?:identical|same) signature\b|\bfail(?:s)? alike\b", re.I)
_GATE_CELLS = re.compile(r"(\d+) of (\d+) cells reproduce in all four environments")
_SIG_CELLS = re.compile(r"identical signature on (\d+) of (\d+) failing cells")
_ELSEWHERE = re.compile(r"catalog|harvest|upstream|\bcontrols?\b|non-holdout|\bleads?\b", re.I)
_CONF = re.compile(r"(\d+)\s+(?:cells?\s+)?confirmed|confirmed\s*\(?(\d+)\)?")
_NCELLS = re.compile(r"(\d+)\s+(?:related\s+|campaign\s+|gate\s+)*cells?\b")
_PATHS = re.compile(r"[\w./-]+\.(?:f90|c|F90|f)\b")
_CITED_ROWS = re.compile(r"\bresults/[\w./*-]*\.jsonl\b")   # a campaign row file the header cites


@dataclass(frozen=True)
class Violation:
    finding: str
    claim: str
    reason: str

    @property
    def key(self) -> tuple:
        return (self.finding, self.claim)


_FILE_PREFIX = re.compile(r"(?m)^[\w.+-]+\.(?:c|h|cc|cpp|f|f90|f95|f03|f08)(?::\d+)*:\s*", re.I)


def _sig(o) -> tuple:
    """A row's signature for "the same way": a diagnostic printed after a bare file name (the
    check case's copy of the program; the scrub drops only paths with a directory) and the same
    diagnostic without it are one; a compiler crash is named by its banner or message, not by the
    driver that reports it (offload.engine.finding_rows.row_signature)."""
    return R.row_signature(_FILE_PREFIX.sub("", o.obs), o.cls)


def _tcs_of(text: str, default: tuple) -> tuple:
    ms = H.mentions(text)
    if not ms:
        return tuple(default)
    out = []
    for m in ms:
        out += [t for t in m.tcs if t not in out]
    return tuple(out)


def _cells(obs, pred):
    cells = defaultdict(list)
    for o in obs:
        if pred(o):
            cells[(o.tc, o.target)].append(o)
    return cells


def _controls(header: H.Header, text: str, fdir=None, base=None) -> list[tuple[str, str]]:
    """(control path, the text that claims it) from the header and the site: block. A file
    name that is another finding (a sibling the control line refers to, relative to the
    findings directory or to the finding's own directory `base`) is not a control."""
    out = []
    ctl = header.get("control")
    dirs = [d for d in (fdir, base) if d is not None]
    if ctl:
        for p in _PATHS.findall(ctl):
            q = Path(p)
            if any((d / q).is_file() for d in dirs) and "controls" not in q.parts:
                continue
            out.append((p, ctl))
    for m in re.finditer(r"^\s*(?://|!)\s?control:\s*(\S+)\s*(.*)$", text, re.M):
        out.append((m.group(1), m.group(2)))
    seen = set()     # the same file named by two spellings is one control
    return [x for x in out if not (Path(x[0]).name in seen or seen.add(Path(x[0]).name))]


def _gpus_of(tcs: tuple) -> set | None:
    """The targets of the toolchains a header names: each one's machine, and for a base its twins
    other than the machine twins (gcc: Tuolumne and gcc_g90's Tioga, not gcc_mi300x's MI300X).
    None when a name is not a registered toolchain (no restriction)."""
    from offload.engine.site import matrix as M
    from offload.engine.toolchains import registry
    reg = registry()
    machines = set()
    for t in tcs:
        if t not in reg.toolchains:
            return None
        machines.add(reg.toolchains[t].machine)
        machines |= {reg.toolchains[w].machine for w in reg.twins_of(t) if w not in reg.machine_twins()}
    return {tg for (mach, _mode), tg in M.TARGETS.items() if mach in machines}


def check(rel: str, text: str, tcs: tuple, ev: Evidence) -> list[Violation]:
    """The violations of one finding file. `tcs`: its failing toolchains (the index), each as
    the site's toolchain (a twin is its base's: the rows are keyed so); the counts are over the
    GPUs of the toolchains named (``_gpus_of``)."""
    gpus = _gpus_of(tcs) if tcs else None
    tcs = tuple(dict.fromkeys(R.site_tc(t) for t in tcs))
    h = H.parse(text)
    out: list[Violation] = []

    def v(claim, reason):
        out.append(Violation(rel, claim, reason))

    for n, ln in H.todos(text):
        v(f"todo line {n}", f"unresolved {H.MARK}: {ln[:100]}")

    repro = ev.repro()
    passes = {(o.tc) for o in repro if o.passed}
    decided = ev.full or ev.has_site     # some source could hold the program's rows
    # the scaffold's counts are counts over the rows the header cites: when those are campaign
    # files under results/, the committed site rows alone cannot give them (full mode can)
    counted = ev.full or (decided and not _CITED_ROWS.search(text))
    own = [o for o in repro if not tcs or o.tc in tcs and (gpus is None or o.target in gpus)]

    # controls
    for path, claim_text in _controls(h, text, ev.findings_dir, ev.base):
        rows = ev.control(path)
        if rows is None:
            continue
        want = [t for t in _tcs_of(claim_text, tcs) if t in tcs or not tcs] or list(tcs)
        if rows and all(o.src == "site-rows" for o in rows):
            want = [t for t in want if t in ev.control_tcs] or want   # the checks run it there
        have = {o.tc for o in rows if o.passed}
        failing = {o.tc for o in rows if o.failed} - have
        lacking = [t for t in want if t not in have]
        if lacking:
            why = ", ".join(f"{t} ({'the recorded row fails' if t in failing else 'no recorded row'})"
                            for t in lacking)
            v(f"control {path}", f"no recorded passing row of the control on {why}")

    # other families
    other = h.get("other") if decided else ""
    seen_tc: set = set()
    for cl in H.clauses(re.sub(r"\([^()]*\)", "", other)):
        if not H.positive(cl) or _ELSEWHERE.search(cl):
            continue
        for m in H.mentions(cl):
            if set(m.tcs) & set(tcs):
                continue     # the finding's own compiler: such a clause is about a control or another program
            need = list(m.tcs) if m.explicit else [None]
            for tc in need:
                if tc is None:
                    ok = any(t in passes for t in m.tcs)
                    name = m.family
                else:
                    ok, name = tc in passes, tc
                if name in seen_tc or ok:
                    continue
                seen_tc.add(name)
                v(f"other-families {name}",
                  f"the header says {name} runs it correctly; no recorded passing row of the "
                  "program on it")

    # gate
    gate = h.get("gate") if decided else ""
    fails = _cells(repro, lambda o: o.failed)
    if gate and _ENVS.search(gate):
        # per compiler: one GPU where it failed in all four backs the claim; a GPU where it failed
        # in only some is an undecided observation there, not the gate's
        envs_of = {k: {o.env for o in os_ if o.env} for k, os_ in fails.items()}
        confirmed = {tc for (tc, _), envs in envs_of.items() if set(ENVS) <= envs}
        for (tc, tg), os_ in sorted(fails.items()):
            envs = envs_of[tc, tg]
            if envs and not set(ENVS) <= envs and tc not in confirmed:
                v(f"gate-envs {tc} {tg}", f"the header claims the four gate environments; "
                  f"{tc} on {tg} has failing rows in {''.join(sorted(envs))} only")
    cn = _CNODE.search(gate) if gate else None
    if cn:
        for (tc, tg), os_ in sorted(fails.items()):
            a = {o.node for o in os_ if o.env == "a" and o.node}
            c = {o.node for o in os_ if o.env == "c" and o.node}
            if a and c and not (c - a):
                v(f"gate-c-node {tc} {tg}", f"(c) is claimed on another {cn.group(1)}; the "
                  f"rows of (a) and (c) name the same one ({sorted(a)[0]})")
    for m in _GATE_CELLS.finditer((gate + " " + (h.get("observed") or "")) if counted else ""):
        got = _gate_cells(own)
        if got is not None and (int(m.group(1)), int(m.group(2))) != got:
            v("gate-cells", f"the header says {m.group(1)} of {m.group(2)} cells reproduce in all "
              f"four environments; the rows give {got[0]} of {got[1]}")

    # the campaign gate's counts, from the gate rows of the programs the header lists
    ids = _program_ids(h.get("programs"))
    if ids and _CONF.search(gate):
        got = gate_cells(ev.obs, ids, tcs, _modes(h.get("fail")))
        if got:
            conf = sum(1 for c in got.values() if c[0])
            cm = _CONF.search(gate)
            nm = _NCELLS.search(gate)
            if cm and int(cm.group(1) or cm.group(2)) != conf:
                v("gate-counts", f"the header says {cm.group(1) or cm.group(2)} confirmed; the gate "
                  f"rows of its programs give {conf} of {len(got)} cells confirmed in a-d")
            elif nm and int(nm.group(1)) != len(got):
                v("gate-counts", f"the header says {nm.group(1)} cells; the gate rows of its "
                  f"programs hold {len(got)}")
            for (pid, tc, tg), (ok, why) in sorted(got.items()):
                if why == "node" and cn:
                    v(f"gate-c-node {tc} {tg}", f"(c) is claimed on another {cn.group(1)}; the gate "
                      f"rows of {pid} put (a) and (c) on the same one")
                    break

    # identical signatures
    for field in ("other", "gate", "observed", "failure"):
        for cl in H.clauses(h.get(field) if decided else ""):
            sc = _SIG_CELLS.search(cl)
            if sc and not counted:
                continue
            if sc:
                fl = _cells(own, lambda o: o.failed)
                sigs = Counter(_sig(o) for os_ in fl.values() for o in os_[:1])
                top = sigs.most_common(1)[0][1] if sigs else 0
                if (int(sc.group(1)), int(sc.group(2))) != (top, len(fl)):
                    v("signature-count", f"the header says identical signature on {sc.group(1)} "
                      f"of {sc.group(2)} failing cells; the rows give {top} of {len(fl)}")
                continue
            if not _SAME.search(cl) or H.HEDGE.search(cl):
                continue
            ms = H.mentions(cl)
            # a family named without versions means the finding's own toolchains of it
            named = tuple(dict.fromkeys(
                t for m in ms for t in ((set(m.tcs) & set(tcs)) if not m.explicit and set(m.tcs) & set(tcs)
                                        else m.tcs)))
            if len(named) < 2:
                named = tuple(dict.fromkeys(named + tuple(tcs)))
            if len(named) < 2:
                continue
            rows = [o for o in repro if o.failed and o.tc in named]
            missing = [t for t in named if not any(o.tc == t for o in rows)]
            sigs = {_sig(o) for o in rows}
            claim = "same-way " + " ".join(sorted(named))
            if missing and len(missing) < len(named):
                v(claim, "fail the same way: no recorded failing row of the program on "
                  + ", ".join(missing))
            elif len(sigs) > 1:
                v(claim, f"fail the same way: the failing rows have {len(sigs)} signatures "
                  f"({'; '.join(sorted(f'{a}: {b[:50]}' for a, b in sigs))})")
            elif not rows:
                v(claim, "fail the same way: no recorded failing row of the program")
    # one entry per (finding, claim): the first reason stands
    seen, uniq = set(), []
    for x in out:
        if x.key not in seen:
            seen.add(x.key)
            uniq.append(x)
    return uniq


def _program_ids(text: str) -> set:
    """The ids in a ``programs (N): a, b, c`` bullet (up to the first ';' or '(')."""
    head = re.split(r"[;(]", text, maxsplit=1)[0]
    return {x for x in re.findall(r"[A-Za-z][\w.-]*\d[\w.-]*|[A-Za-z][\w-]+-[\w-]+", head)}


_MODES = re.compile(r"\bmodes?:\s*([a-z ,]+)", re.I)


def _modes(fail: str) -> set:
    """The memory modes the `toolchains and modes that fail` line names after `modes:` (none:
    every mode)."""
    m = _MODES.search(fail or "")
    words = re.findall(r"unified|copy|managed|separate", m.group(1).lower()) if m else []
    return {"copy" if w == "separate" else w for w in words}


def gate_cells(obs, ids: set, tcs: tuple = (), modes: set = frozenset()) -> dict:
    """(program, toolchain, target) -> (confirmed, why) for the programs `ids`, from the gate
    reruns (rows with an environment): confirmed when a, b, c and d all fail with one signature, the
    stored run of the cell (when the rows hold it) fails with that signature too,
    and (c) ran on another node than (a) (a GPU of a one-host machine counts as a node).
    `modes`: only the cells of these memory modes (the finding's), when given."""
    from offload.engine.gate import node_key
    cells = defaultdict(lambda: defaultdict(list))
    stored = defaultdict(list)
    for o in obs:
        if o.pid in ids and o.src == "campaign-rows" and (not tcs or o.tc in tcs) and (not modes or o.mode in modes):
            if o.env in tuple(ENVS):
                cells[(o.pid, o.tc, o.target)][o.env].append(o)
            elif not o.env and o.variant == "repro":
                stored[(o.pid, o.tc, o.target)].append(o)
    out = {}
    for k, envs in cells.items():
        allobs = [o for os_ in envs.values() for o in os_]
        if not set(ENVS) <= set(envs):
            out[k] = (False, "envs")
        elif not all(o.failed for o in allobs) or len({o.sig for o in allobs}) != 1:
            out[k] = (False, "signature")
        elif stored.get(k) and not any(s_.failed and s_.cls == allobs[0].cls for s_ in stored[k]):
            # the campaign gate calls a cell whose stored run is another outcome class (a timeout
            # against four run errors) nondeterministic; the message may differ (a truncated symbol)
            out[k] = (False, "stored")
        else:
            a = {node_key(o.node) for o in envs["a"] if o.node}
            c = {node_key(o.node) for o in envs["c"] if o.node}
            out[k] = (False, "node") if a and c and not (c - a) else (True, "")
    return out


def _gate_cells(repro) -> tuple | None:
    """(cells that fail identically in all of a-d, cells that fail) from the repro rows."""
    fl = _cells(repro, lambda o: o.failed)
    if not fl or not any(o.env for os_ in fl.values() for o in os_):
        return None
    ok = 0
    for os_ in fl.values():
        envs = {o.env for o in os_}
        if set(ENVS) <= envs and len({o.sig for o in os_}) == 1:
            ok += 1
    return ok, len(fl)
