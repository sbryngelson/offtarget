"""Run the slice's generated programs over toolchains and memory modes.

run_matrix(atoms, toolchains, xnack, out) generates, for each spec version
in `versions` (default 5.2 and 6.0; 5.0 on request), the programs of the
given atoms (offload.engine.gen.generate) and runs each on every toolchain
under every HSA_XNACK value with offload.engine.harness.run_program (-O2,
three repeats). An atom outside a version's slice is skipped for that
version; an atom in no version is an error.

One JSONL row (harness.Result) per cell is appended to `out` as soon as
it finishes. resume=True skips cells already in `out`; only=ids restricts
the run to those programs. AFAR compiles 6.0 programs with
-fopenmp-version=60 and 5.0 programs with -fopenmp-version=50. Copy mode
(HSA_XNACK=0) runs only for copy_mode_programs, listed in
catalog/omp/memory_modes.yaml."""
from __future__ import annotations

import dataclasses
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Sequence

import yaml

from offload.engine.catalog import model_of, slice_atoms
from offload.engine.gen import Program, generate
from offload.engine.harness import Outcome, Result, run_program
from offload.engine.toolchains import (TOOLCHAINS, Toolchain, base_name,
                                   compiler_version, device_of, registry)

MEMORY_MODES = (Path(__file__).resolve().parent.parent.parent / "catalog" / "omp"
                / "memory_modes.yaml")


def version_flags(toolchain: str, version: int, lang: str = "f90") -> str:
    """The OpenMP version flag `toolchain` gets for programs of `version`
    ("" = the compiler's default): its family's ``version_flags`` of
    catalog/toolchains.yaml (Fortran) and, for a family with
    ``c_version_flag``, ``-fopenmp-version=<version>`` for C (both
    C front ends, AFAR amdclang and CCE craycc, default to OpenMP 5.1,
    ``_OPENMP`` 202011, so a 5.2 or 6.0 program is compiled at its own
    level; CCE 19 craycc accepts ``-fopenmp-version=60`` without a
    diagnostic but stays at 5.1, which the report notes). NVHPC and GCC
    have no OpenMP version option. A toolchain the catalog does not know
    (a test's) is treated as the AMD recipe its name says (Toolchain.kind);
    a gfx90a twin (afar_g90) is its compiler's flags."""
    tc = TOOLCHAINS.get(toolchain)
    if tc is not None:
        fam = tc.family
    else:
        reg = registry()
        kind = "afar" if base_name(toolchain) == "afar" else "cce"
        fam = reg.family_of_kind(kind)
    if lang == "c":
        return f"-fopenmp-version={version}" if fam.c_version_flag else ""
    return fam.version_flags.get(version, "")


def for_version(tc: Toolchain, version: int,
                lang: str | None = None) -> Toolchain:
    """`tc` with the version flag of `version` added to its flags; for an
    OpenACC version (34) the toolchain compiles OpenACC (model "acc"); with
    `lang` the toolchain compiles that language."""
    model = model_of(version)
    if tc.model != model:
        tc = dataclasses.replace(tc, model=model)
    if lang is not None and tc.lang != lang:
        tc = dataclasses.replace(tc, lang=lang)
    vf = version_flags(tc.name, version, tc.lang)
    if not vf:
        return tc
    return dataclasses.replace(tc, extra=f"{tc.extra} {vf}".strip())


def matrix_programs(atoms: Iterable[str], versions: Sequence[int],
                    lang: str = "f90") -> list[tuple[int, Program]]:
    """(version, program) for every version; raises ValueError for an atom
    that is in no requested version's slice. `lang` "c": the C
    programs (offload.engine.c_gen) of the C slice."""
    atoms = sorted(set(atoms))
    per = {v: set(slice_atoms(v, lang=lang)) for v in versions}
    unknown = [a for a in atoms if not any(a in s for s in per.values())]
    if unknown:
        raise ValueError(f"atoms in no slice of {list(versions)}: "
                         + ", ".join(unknown))
    if lang == "c":
        from offload.engine.acc_c_gen import generate_acc_c
        from offload.engine.c_gen import generate_c
        # The OpenACC C programs (version 34)
        return [(v, p) for v in versions
                for p in (generate_acc_c([a for a in atoms if a in per[v]])
                          if model_of(v) == "acc" else
                          generate_c([a for a in atoms if a in per[v]], v))]
    return [(v, p) for v in versions
            for p in generate([a for a in atoms if a in per[v]], v)]


@lru_cache(maxsize=None)
def memory_modes(path: Path = MEMORY_MODES) -> dict:
    """catalog/omp/memory_modes.yaml, checked: the headline and copy
    HSA_XNACK values, and the memory-sensitive atom patterns and program
    ids (each with a reason)."""
    data = yaml.safe_load(Path(path).read_text()) or {}
    ms = data.get("memory_sensitive") or {}
    for kind, key in (("atoms", "pattern"), ("programs", "id")):
        for e in ms.get(kind) or []:
            if not e.get(key) or not e.get("why"):
                raise ValueError(f"{path}: memory_sensitive.{kind} entry "
                                 f"needs {key} and why: {e}")
    if {data.get("headline_xnack"), data.get("copy_xnack")} != {0, 1}:
        raise ValueError(f"{path}: headline_xnack and copy_xnack must be "
                         "1 and 0")
    return data


def copy_mode_programs(programs: Iterable, modes: dict | None = None
                       ) -> set[str]:
    """Ids of the programs that also run in copy mode (HSA_XNACK=0):
    evidence ``copy_mode_only``, a primary atom matching a memory-sensitive
    pattern, or a listed program id. `programs`: Program objects or
    (version, Program) pairs."""
    modes = memory_modes() if modes is None else modes
    ms = modes.get("memory_sensitive") or {}
    pats = [e["pattern"] for e in ms.get("atoms") or []]
    ids = {e["id"] for e in ms.get("programs") or []}
    out = set()
    for p in programs:
        p = p[1] if isinstance(p, tuple) else p
        if (p.evidence == "copy_mode_only" or p.id in ids
                or any(fnmatchcase(p.primary_atom, x) for x in pats)):
            out.add(p.id)
    return out


def copy_mode_subset(versions: Sequence[int] = (52, 60),
                     lang: str = "f90") -> set[str]:
    """``copy_mode_programs`` over every slice program of `versions` (in
    `lang`)."""
    atoms = set().union(*(slice_atoms(v, lang=lang) for v in versions))
    return copy_mode_programs(matrix_programs(atoms, versions, lang))


# Text that makes a program's result depend on the number of
# visible devices (the device clause, device numbers, the device count)
_DEVICE_COUNT = re.compile(r"omp_get_num_devices|omp_get_device_num|"
                           r"omp_get_initial_device|acc_get_num_devices|"
                           r"(?<![\w_])device(?:_num)?\s*\(", re.I)


def device_count_dependent(source: str) -> bool:
    """Whether a program's (or test's) result can depend on how many
    devices the runtime sees (the Tioga runs saw one GCD each,
    such programs are run again with every device visible, as on
    Tuolumne)."""
    return _DEVICE_COUNT.search(source) is not None


def mode_differing(rows: Iterable[dict]) -> set[str]:
    """Programs whose outcome (or crash) differs between HSA_XNACK=1 and 0
    on some toolchain, in matrix rows that have both modes."""
    by: dict[tuple, dict] = {}
    for r in rows:
        by.setdefault((r["program_id"], r["toolchain"]), {})[r["xnack"]] = r

    def key(r):
        return r["outcome"], r.get("reason", "").startswith("crash:")
    return {p for (p, _), m in by.items()
            if 0 in m and 1 in m and key(m[0]) != key(m[1])}


def _key(program_id: str, toolchain: str, xnack: int, opt: str) -> tuple:
    return program_id, toolchain, xnack, opt


def _done(out: Path) -> set[tuple]:
    keys = set()
    if not out.exists():
        return keys
    for line in out.read_text().splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:  # a line cut by a kill
            continue
        keys.add(_key(d["program_id"], d["toolchain"], d["xnack"], d["opt"]))
    return keys


def _clean(out: Path) -> None:
    """Drop a trailing partial line (a kill during a write)."""
    if not out.exists():
        return
    lines = out.read_text().splitlines()
    good = []
    for line in lines:
        try:
            json.loads(line)
            good.append(line)
        except json.JSONDecodeError:
            pass
    out.write_text("".join(f"{line}\n" for line in good))


def _gpu_text() -> str:
    from offload.engine.harness import gpu_text
    return gpu_text()


def _error_result(prog: Program, tc: Toolchain, x: int, opt: str,
                  version: int, err: BaseException) -> Result:
    return Result(program_id=prog.id, primary_atom=prog.primary_atom,
                  atoms=tuple(sorted(prog.atoms)), toolchain=tc.name,
                  xnack=x, opt=opt, outcome=Outcome.harness_error,
                  reason=f"runner_exception: {type(err).__name__}: {err}",
                  flaky=False, flags=f"{tc.flags()} {opt}", rocm=None,
                  device=device_of(tc), compiler=compiler_version(tc),
                  stdout="", stderr="", needs=tuple(prog.needs),
                  evidence=prog.evidence, observable=prog.observable,
                  legal=prog.legal, violates=prog.violates, version=version,
                  model=prog.model, lang="c" if prog.lang == "c" else "f90",
                  machine=tc.machine, arch=tc.arch, gpu=_gpu_text())


def run_matrix(atoms: Iterable[str], toolchains: list[str | Toolchain],
               xnack: list[int], out: Path, *,
               versions: Sequence[int] = (52, 60), opt: str = "-O2",
               repeats: int = 3, timeout_s: int = 120, workers: int = 8,
               flags_note: str = "", resume: bool = False,
               only: Iterable[str] | None = None,
               runner: Callable[..., Result] = run_program,
               progress: Callable[[str], None] | None = None,
               lang: str = "f90") -> int:
    """Run every program of `atoms` (per version) on every toolchain under
    every HSA_XNACK value; append one row per cell to `out` (truncated
    first unless `resume`). `only`: run just these program ids (e.g.
    ``copy_mode_subset()``). Returns the number of rows written by this
    call."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tcs = [TOOLCHAINS[t] if isinstance(t, str) else t for t in toolchains]
    for tc in tcs:  # Tioga runs at HSA_XNACK=0 only
        for x in xnack:
            tc.run_env(x)  # raises ValueError for a mode it does not run
    progs = matrix_programs(atoms, versions, lang)
    if only is not None:
        only = set(only)
        progs = [(v, p) for v, p in progs if p.id in only]
    if resume:
        _clean(out)
        done = _done(out)
    else:
        out.write_text("")
        done = set()
    cells = [(v, p, for_version(tc, v, "c" if p.lang == "c" else "f90")
              .for_mode(x), x)
             for v, p in progs for tc in tcs for x in xnack
             if _key(p.id, tc.name, x, opt) not in done]
    lock = threading.Lock()
    count = [0]

    def job(cell) -> None:
        v, p, tc, x = cell
        try:
            r = runner(p, tc, x, opt, timeout_s=timeout_s, repeats=repeats)
        except Exception as err:  # noqa: BLE001 - one cell, keep going
            r = _error_result(p, tc, x, opt, v, err)
        if flags_note:
            r = dataclasses.replace(r, flags=f"{r.flags} {flags_note}")
        line = json.dumps(dataclasses.asdict(r)) + "\n"
        with lock:
            with out.open("a") as f:
                f.write(line)
            count[0] += 1
            if progress:
                progress(f"{count[0]}/{len(cells)} {p.id} {tc.name} "
                         f"xnack={x}: {r.outcome}")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(job, cells))
    return count[0]


def rerun_programs(program_ids: Iterable[str],
                   toolchains: list[str | Toolchain], xnack: int, out: Path,
                   *, versions: Sequence[int] = (52, 60), lang: str = "f90",
                   **kw) -> int:
    """Run the given programs again on `toolchains` under one HSA_XNACK
    value: their rows in `out` (for those toolchains and that mode) are
    dropped and the cells run again with ``resume`` (every other row is
    kept as it is). For a program whose source changed after the matrix
    run. Returns the number of rows written."""
    ids = set(program_ids)
    tcs = [TOOLCHAINS[t] if isinstance(t, str) else t for t in toolchains]
    names = {tc.name for tc in tcs}
    progs = {p.id: p for _, p in matrix_programs(
        set().union(*(slice_atoms(v, lang=lang) for v in versions)),
        versions, lang)}
    unknown = sorted(ids - set(progs))
    if unknown:
        raise ValueError(f"programs not generated: {', '.join(unknown)}")
    out = Path(out)
    _clean(out)
    kept = [line for line in out.read_text().splitlines()
            if not ((d := json.loads(line))["program_id"] in ids
                    and d["toolchain"] in names and d["xnack"] == xnack)]
    out.write_text("".join(f"{line}\n" for line in kept))
    atoms = {progs[i].primary_atom for i in ids}
    # an illegal variant is generated with its base atom's program, which
    # need not be its primary atom (gen.VARIANT_PRIMARY)
    for i in ids:
        v = progs[i].violates
        if v:
            from offload.engine.gen import VIOLATION_BASE
            if lang == "c":
                from offload.engine.c_gen import c_base_atom
                atoms.add(c_base_atom(v))
            else:
                atoms.add(VIOLATION_BASE[v][0])
    atoms = sorted(atoms)
    return run_matrix(atoms, tcs, [xnack], out, versions=versions,
                      resume=True, lang=lang, **kw)
