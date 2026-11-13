"""Delta debugging of failing stress programs down to a minimal reproducer,
before the confirmer. The big program stays reproducible from its spec
(axis, size, seed, model, layout).

The failure to keep (`Target`) is the row's toolchain, memory mode and
build variant with: for wrong_code, the class and a kernel still printing
a value other than the Python model's; for ice and the compile_* classes,
the class and the message key (offload.engine.confirm.decisions._msg_key) of
the first diagnostic; for run_error, run_timeout and host_fallback, the
class and the failure kind (signal or exit status).

Steps: (1) keep the kernels whose K line was wrong, else ddmin over the
kernel list; (2) apply each kernel's `smaller` variants to a fixpoint;
(3) for compile failures only, remove kernel body lines one at a time
while the failure stays and the candidate passes the legality gate."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from offload.engine import stress as S
from offload.engine import stress_exec as X

COMPILE_CLASSES = ("ice", "compile_reject", "compile_oom", "compile_timeout")


def msg_key(reason: str) -> str:
    from offload.engine.confirm.decisions import _msg_key
    return _msg_key(reason)


@dataclass
class Target:
    toolchain: str
    mode: int
    variant: str
    cls: str
    key: str

    @staticmethod
    def of(row: dict) -> "Target":
        return Target(row["toolchain"], row["mode"], row["variant"],
                      row["cls"], failure_key(row["cls"], row["reason"]))


def failure_key(cls: str, reason: str) -> str:
    if cls in COMPILE_CLASSES:
        return msg_key(reason)
    if cls in ("run_error", "run_timeout"):
        return re.sub(r"\d+", "N", reason.split(";")[0].split(":")[0])
    return cls


@dataclass
class MinResult:
    prog: object
    steps: list = field(default_factory=list)
    calls: int = 0
    reproduced: bool = True


def _same(prog, t: Target, lim: X.Limits, log) -> tuple[bool, dict]:
    rows = X.execute(prog, t.toolchain, (t.mode,), t.variant, lim)
    r = rows[0]
    ok = r.cls == t.cls and (
        failure_key(r.cls, r.reason) == t.key if t.cls in COMPILE_CLASSES +
        ("run_error", "run_timeout") else True)
    if t.cls == "wrong_code":
        ok = ok and bool(r.bad_kernels)
    log(f"  {'keep' if ok else 'drop'} {prog.id} {len(prog.kernels)} "
        f"kernels {prog.lines} lines: {r.cls} {r.reason[:80]}")
    return ok, r.as_dict()


def _program(meta: dict, kernels: list):
    if meta.get("lang") == "c":
        from offload.engine import stress_c as C
        for j, k in enumerate(kernels, 1):
            pass
        return C.assemble_c(meta["axis"], meta["size"], meta["seed"],
                            kernels, meta["layout"])
    return S.rebuild(meta, kernels)


def minimize(prog, row: dict, lim: X.Limits | None = None, log=print,
             max_calls: int = 120, budget_s: float = 1500) -> MinResult:
    import time
    deadline = time.time() + budget_s
    t = Target.of(row)
    lim = lim or X.Limits(compile_s=min(900, int(row.get("limits", {}).get(
        "compile_s", 900))))
    meta = prog.meta()
    meta["lang"] = prog.lang
    res = MinResult(prog)
    calls = 0
    ok, r0 = _same(prog, t, lim, log)
    calls += 1
    if not ok:
        res.reproduced = False
        res.steps.append(f"does not reproduce: {r0['cls']} {r0['reason']}")
        return res
    ks = list(prog.kernels)
    # 1. kernels
    if t.cls == "wrong_code" and r0["bad_kernels"]:
        bad = [k for k in ks if k.name in r0["bad_kernels"]]
        cand = _program(meta, bad)
        good, _ = _same(cand, t, lim, log)
        calls += 1
        if good:
            ks = bad
            res.steps.append(f"kernels: kept the {len(bad)} wrong ones")
    n = 2
    while len(ks) > 1 and calls < max_calls and time.time() < deadline:
        chunk = max(1, len(ks) // n)
        parts = [ks[i:i + chunk] for i in range(0, len(ks), chunk)]
        reduced = False
        for i, part in enumerate(parts):
            for cand_ks in (part, [k for p in parts[:i] + parts[i + 1:]
                                   for k in p]):
                if not cand_ks or len(cand_ks) == len(ks):
                    continue
                good, _ = _same(_program(meta, cand_ks), t, lim, log)
                calls += 1
                if good:
                    ks = cand_ks
                    reduced = True
                    break
            if reduced or (calls >= max_calls or time.time() >= deadline):
                break
        if reduced:
            n = max(2, n - 1)
        elif chunk == 1:
            break
        else:
            n = min(len(ks), n * 2)
    res.steps.append(f"kernels: {len(prog.kernels)} -> {len(ks)}")
    # 2. kernel variants
    changed = True
    while changed and calls < max_calls and time.time() < deadline:
        changed = False
        for idx, k in enumerate(ks):
            for s in k.smaller():
                cand_ks = ks[:idx] + [s] + ks[idx + 1:]
                try:
                    cand = _program(meta, cand_ks)
                except Exception:
                    continue
                good, _ = _same(cand, t, lim, log)
                calls += 1
                if good:
                    res.steps.append(f"{k.describe()} -> {s.describe()}")
                    ks = cand_ks
                    changed = True
                    break
                if (calls >= max_calls or time.time() >= deadline):
                    break
            if changed or (calls >= max_calls or time.time() >= deadline):
                break
    final = _program(meta, ks)
    # 3. statements (compile failures)
    if t.cls in COMPILE_CLASSES and calls < max_calls and time.time() < deadline:
        final, c3, st = _statements(final, t, lim, log, max_calls - calls,
                                    deadline)
        calls += c3
        res.steps += st
    res.prog, res.calls = final, calls
    return res


class _Text:
    """A program given as text (step 3's candidates)."""

    def __init__(self, base, files):
        self.__dict__.update(base.__dict__)
        self.files = files

    @property
    def lines(self):
        return sum(t.count("\n") for _, t in self.files)

    @property
    def source(self):
        return "".join(f"{S.FILE_MARK}{n}\n{t}" for n, t in self.files)

    def meta(self):
        m = dict(self.base_meta)
        m["files"] = len(self.files)
        return m


def _statements(prog, t: Target, lim, log, budget: int,
                deadline: float = float("inf")):
    import time
    steps, calls = [], 0
    files = list(prog.files)
    base_meta = prog.meta()
    for fi, (name, text) in enumerate(files):
        if calls >= budget:
            break
        lines = text.split("\n")
        k = 0
        while k < len(lines) and calls < budget and time.time() < deadline:
            ln = lines[k].strip()
            removable = ln and not ln.startswith((
                "module", "end", "contains", "subroutine", "function",
                "program", "use ", "implicit", "integer", "type", "class",
                "logical", "!", "#", "}", "{", "void", "int ", "static",
                "struct", "do ", "if ", "else", "call st_cksum", "print"))
            if not removable:
                k += 1
                continue
            cand_lines = lines[:k] + lines[k + 1:]
            cand_files = files[:fi] + [(name, "\n".join(cand_lines))] + \
                files[fi + 1:]
            cand = _Text(prog, cand_files)
            cand.base_meta = base_meta
            g = X.gate(cand, rules=False)
            if g["stage"] != "ok":
                k += 1
                continue
            good, _ = _same(cand, t, lim, log)
            calls += 1
            if good:
                lines = cand_lines
                files = cand_files
                steps.append(f"statement removed: {ln[:60]}")
            else:
                k += 1
    out = _Text(prog, files)
    out.base_meta = base_meta
    return out, calls, steps


def save(res: MinResult, row: dict, out: Path) -> Path:
    d = out / f"{row['id']}-{row['toolchain']}-{row['mode']}-{row['variant']}"
    d.mkdir(parents=True, exist_ok=True)
    for name, text in res.prog.files:
        (d / name).write_text(text)
    (d / "min.json").write_text(json.dumps({
        "row": {k: row[k] for k in ("id", "toolchain", "mode", "variant",
                                    "cls", "reason", "bad_kernels")},
        "steps": res.steps, "calls": res.calls,
        "reproduced": res.reproduced,
        "kernels": [k.describe() for k in getattr(res.prog, "kernels", [])],
        "lines": res.prog.lines}, indent=1))
    return d
