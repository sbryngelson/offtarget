"""Independent legality witnesses (amendment
of RUL-UNSUPPORTED-EVERYWHERE): a compiler that is not under test (catalog/machines.yaml
``independent_checkers``: only an
offload compiler not under test, e.g. NVHPC or upstream LLVM clang/flang,
never gfortran/gcc; never a toolchain under test)
compiles a program with ``-fsyntax-only``. The results are data
(catalog/legality_witness.yaml: program, sha256 of the source checked,
checker and its version, accept/reject, message, date), written by
``tools/confirm.py witness`` and read by the rules (``accepted``), so the
offline batch stays deterministic.

gfortran/gcc -fopenmp are not
trusted for offload legality; the checker list is empty and R12a cannot
fire until a replacement witness is named."""
from __future__ import annotations

import datetime
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import re

import yaml

from offload.engine import localcfg

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA = ROOT / "catalog" / "legality_witness.yaml"


def validate(entries: dict) -> dict:
    """An independent legality witness is
    another *offload compiler* that is not under test (NVHPC once it runs,
    or upstream LLVM clang/flang), flagged ``witness_only: true`` with
    ``kind: offload_compiler``; never a toolchain under test,
    never gfortran/gcc. Raises ValueError on an entry that is not one."""
    from offload.engine.toolchains import TOOLCHAINS
    under_test = {Path(c.split()[0]).name for t in TOOLCHAINS.values()
                  for c in (t.fc, t.cc) if c}
    roots = under_test_roots()
    for name, c in entries.items():
        if c.get("witness_only") is not True or \
                c.get("kind") != "offload_compiler":
            raise ValueError(f"independent checker {name}: only an offload "
                             "compiler flagged witness_only: true (kind: "
                             "offload_compiler) may witness legality")
        exe = Path(str(c.get("command", "")).split()[0]).name \
            if c.get("command") else ""
        path = _resolve(str(c.get("command", "")).split()[0]) \
            if c.get("command") else None
        fam = c.get("family")
        # GCC: a family under test only (GCC) never witnesses,
        # nor does any program of its installs, whatever its name
        from offload.engine.confirm.machines import under_test_only
        from offload.engine.toolchains import GCC_TOOLCHAINS, TOOLCHAINS as _T
        gcc_roots = {Path(_T[t].fc).resolve().parent.parent
                     for t in GCC_TOOLCHAINS}
        if fam in under_test_only() or (path is not None and any(
                path == r or r in path.parents for r in gcc_roots)):
            raise ValueError(f"independent checker {name}: a compiler under "
                             "test only (GCC) is never a legality witness")
        if fam is not None:
            # a compiler under test of another machine (NVHPC) may witness
            # the cases of other families; `family` names its own, whose
            # cases it never witnesses (accepted(family=...))
            from offload.engine.confirm.machines import family_of
            members = {family_of(t) for t in TOOLCHAINS}
            if fam not in members:
                raise ValueError(f"independent checker {name}: family "
                                 f"{fam} is not a compiler family")
            if fam in ("afar", "cce"):
                raise ValueError(f"independent checker {name}: an AMD "
                                 "family is never a witness")
        elif name in TOOLCHAINS or exe in under_test or (
                path is not None and any(path == r or r in path.parents
                                         for r in roots)):
            raise ValueError(f"independent checker {name}: a toolchain "
                             "under test is never its own witness "
                             "(ruling D)")
        if exe in ("gfortran", "gcc") or name in ("gfortran", "gcc"):
            raise ValueError(f"independent checker {name}: gfortran/gcc "
                             "are not trusted for offload legality (owner, "
                             "2026-10-23)")
        if c.get("lang") not in ("f90", "c"):
            raise ValueError(f"independent checker {name}: lang f90 or c")
    return dict(entries)


def _resolve(cmd: str) -> Path | None:
    import shutil
    found = cmd if "/" in cmd else shutil.which(cmd)
    return Path(found).resolve() if found else None


def under_test_roots() -> set:
    """The install roots of the toolchains under test (the
    executable name is not enough; AFAR's internal lib/llvm/bin/flang and
    CCE's cce-clang are the compilers under test too): the directory above
    the `bin` of an absolute compiler path, and /opt/cray/pe/cce/<version>
    of each `module load cce/<version>` prelude."""
    import re
    from offload.engine.toolchains import TOOLCHAINS
    out = set()
    for t in TOOLCHAINS.values():
        for c in (t.fc, t.cc):
            if c and c.startswith("/"):
                out.add(Path(c).resolve().parent.parent)
        for v in re.findall(r"\bcce/(\S+)", t.prelude or ""):
            out.add(Path("/opt/cray/pe/cce") / v)
    return out


def checkers(data: dict | None = None) -> dict:
    """The configured witnesses (catalog/machines.yaml
    ``independent_checkers``), validated; empty now, so R12a is dormant."""
    d = data if data is not None else localcfg.overlay("machines.yaml", yaml.safe_load(
        (ROOT / "catalog" / "machines.yaml").read_text()))
    return validate(dict(d.get("independent_checkers") or {}))


@lru_cache(maxsize=None)
def _rows(path: str = str(DATA)) -> tuple:
    p = Path(path)
    if not p.is_file():
        return ()
    return tuple((yaml.safe_load(p.read_text()) or {}).get("witnesses")
                 or ())


def accepted(ident: str, sha: str = "", family: str | None = None
             ) -> str | None:
    """The checker (with version) that accepted the program's current
    source, or None. Only a checker listed in catalog/machines.yaml
    ``independent_checkers`` counts (gfortran and
    gcc -fopenmp are withdrawn; with the list empty nothing is accepted).
    A checker of compiler family `family` (the case's) never
    counts."""
    active = {k: v for k, v in checkers().items()
              if family is None or v.get("family") != family}
    for r in _rows():
        if r.get("calibrates"):
            continue  # an illegal variant run for calibration, not a witness
        if r["checker"] in active and r["program"] == ident and \
                r["result"] == "accept" and (not sha or r["sha256"] == sha):
            if uncalibrated(r, active):
                continue
            return f"{r['checker']} {r['version']}"
    return None


def verdict_of(ident: str, sha: str = "", family: str | None = None
               ) -> tuple[str, str] | None:
    """(checker with version, "accept" | "reject") of the stored
    verdict of an independent checker not of `family` on the program's
    current source (an accept only when calibrated, as ``accepted``); an
    accept wins over a reject of another release; None when there is
    none. The second legality witness of a case whose own front end is
    under test (offload.engine.confirm.legality, two witnesses): a witness
    from another machine."""
    acc = accepted(ident, sha, family)
    if acc:
        return acc, "accept"
    active = {k: v for k, v in checkers().items()
              if family is None or v.get("family") != family}
    for r in _rows():
        if r.get("calibrates") or r["checker"] not in active:
            continue
        if r["program"] == ident and (not sha or r["sha256"] == sha) and \
                r["result"] == "reject":
            return f"{r['checker']} {r['version']}", "reject"
    return None


def uncalibrated(row: dict, active: dict | None = None) -> list[str]:
    """(ruling R2): the illegal catalog
    variants of the accepted program's primary atom that a checker of the
    same compiler family also accepted (catalog/legality_witness.yaml rows
    with ``calibrates``). A compiler that accepts the illegal variants of
    a program family says nothing about the legality of its legal
    programs, so such an accept is no witness (NVHPC: nvc compiles the
    illegal C defaultmap(none) variants)."""
    active = active if active is not None else checkers()
    fam = (active.get(row["checker"]) or {}).get("family", row["checker"])
    atom = row.get("atom") or atom_of(row["program"])
    if not atom:
        return []
    return sorted(r["program"] for r in _rows()
                  if r.get("calibrates") == atom and r["result"] == "accept"
                  and (active.get(r["checker"]) or {}).get(
                      "family", r["checker"]) == fam)


@lru_cache(maxsize=None)
def atom_of(pid: str) -> str:
    """The primary atom of a catalog program ("" if not generated)."""
    from offload.engine.confirm.programs import catalog_program
    prog = catalog_program(pid)
    return getattr(prog, "primary_atom", "") if prog is not None else ""


def illegal_variants(pid: str) -> list[tuple[str, str, str]]:
    """The illegal catalog programs (id, lang, source) of the program's
    primary atom, in every version and language of its model: the
    calibration set of a witness accept (ruling R2)."""
    from offload.engine.confirm.programs import _catalog, catalog_program
    prog = catalog_program(pid)
    if prog is None:
        return []
    atom = prog.primary_atom
    slices = ([(34, "f90")] if prog.model == "acc" else
              [(50, "f90"), (52, "f90"), (60, "f90"), (52, "c"), (60, "c")])
    out = []
    for v, lang in slices:
        try:
            progs = _catalog(v, lang)
        except Exception:
            continue
        out += [(q.id, "c" if q.lang == "c" else "f90", q.source)
                for q in progs.values()
                if not q.legal and q.primary_atom == atom
                and q.model == prog.model]
    return sorted(out)


def _version(cmd: str) -> str:
    out = subprocess.run(cmd.split(), capture_output=True, text=True)
    first = (out.stdout or "").splitlines()[0] if out.stdout else ""
    import re
    m = re.search(r"\d+\.\d+\.\d+", first)
    return m.group(0) if m else first


def names_for(lang: str, model: str = "omp") -> list[str]:
    """The configured checkers of a language and model (NVHPC
    26.9 and 25.11, one family: either one's accept is the witness)."""
    return [k for k, v in checkers().items()
            if v["lang"] == ("c" if lang == "c" else "f90")
            and v.get("model", "omp") == model]


def check(ident: str, source: str, lang: str, sha: str,
          model: str = "omp", name: str | None = None) -> dict:
    """Run the language's (and model's, ``model`` of the entry,
    default omp; `name`: that checker) independent checker on a source
    (ValueError when the language has none)."""
    found = [(k, v) for k, v in checkers().items()
             if k in names_for(lang, model) and (name is None or k == name)]
    if not found:
        raise ValueError(f"no independent legality checker for {lang} "
                         "(catalog/machines.yaml independent_checkers)")
    name, c = found[0]
    if c.get("machine"):  # The checker lives on another machine
        return _check_remote(ident, source, lang, sha, name, c)
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / ("t.c" if lang == "c" else "t.f90")
        src.write_text(source)
        r = subprocess.run(c["command"].split() + [str(src)], cwd=d,
                           capture_output=True, text=True, timeout=300)
        err = (r.stderr or "").replace(str(src), src.name)
    msg = " | ".join(x.strip() for x in err.splitlines()
                     if "error" in x.lower())[:300]
    return {"program": ident, "sha256": sha, "checker": name,
            "version": _version(c["version"]), "command": public(c["command"]),
            "result": "accept" if r.returncode == 0 else "reject",
            "message": public(msg),
            "date": datetime.date.today().isoformat()}


_SITE_PATH = re.compile(r"/(?:fastscratch|nethome|p/(?:lustre\d|vast\d))/[A-Za-z0-9_-]+")


def public(text: str) -> str:
    """A recorded command or message without the directory of the machine it ran on."""
    return _SITE_PATH.sub("$SITE", text)


def _ssh(machine) -> list[str]:
    a = machine.access
    return ["ssh", *(a.get("ssh_options") or ()), a["ssh"]]


def capped(machine, command: str) -> str:
    """`command` inside the machine's cap (catalog/machines.yaml
    access ``cap``, relative to its root: wingtip's compliant.slice,
    docs/tooling/wingtip.md); unchanged on a machine without one."""
    a = machine.access
    cap = a.get("cap") if isinstance(a, dict) else None
    return f"{a['root']}/{cap} {command}" if cap else command


def remote_command(machine, command: str, fn: str) -> str:
    """The shell line that checks `fn` (the source on stdin) with
    `command` in a fresh temporary directory of the machine."""
    return (f"d=$(mktemp -d) && cd $d && cat > {fn} && "
            f"{capped(machine, command)} {fn}; rc=$?; cd / && rm -rf $d; "
            "exit $rc")


def _check_remote(ident, source, lang, sha, name, c) -> dict:
    """The checker of another machine (catalog/machines.yaml
    ``machine``), run over its ssh access in a fresh temporary directory
    there; the source goes on stdin."""
    import shlex
    from offload.engine.confirm.machines import load
    m = load()[c["machine"]]
    fn = "t.c" if lang == "c" else "t.f90"
    remote = remote_command(m, c["command"], fn)
    r = subprocess.run(_ssh(m) + [remote], input=source,
                       capture_output=True, text=True, timeout=600)
    if r.returncode == 255:
        raise RuntimeError(f"ssh to {m.name} failed: {r.stderr[-200:]}")
    err = r.stdout + r.stderr
    msg = " | ".join(x.strip() for x in err.splitlines()
                     if re.search(r"error|NVFORTRAN-[SFW]|NVC\+\+-[SFW]",
                                  x, re.I))[:300]
    # a compiler that drops what it does not know with a warning (NVHPC:
    # "Unrecognized OpenMP directive", "OpenMP feature ... not yet
    # implemented") has not accepted the program: no witness
    from offload.engine.harness import classify_message
    ign = classify_message(c["family"], err, ("ignored",), lang) \
        if r.returncode == 0 else None
    v = subprocess.run(_ssh(m) + [capped(m, c["version"])],
                       capture_output=True,
                       text=True, timeout=120)
    first = next((ln for ln in v.stdout.splitlines() if ln.strip()), "")
    return {"program": ident, "sha256": sha, "checker": name,
            "version": first.strip(), "command": public(c["command"]),
            "result": ("ignored" if ign else "accept") if r.returncode == 0
            else "reject",
            "message": msg, "date": datetime.date.today().isoformat()}


EMPTY = (
    "# Generated by `tools/confirm.py witness`. Maintainer ruling 2026-10-23\n"
    "# (final review 3): gfortran -fopenmp and gcc -fopenmp are not trusted\n"
    "# for offload legality and are withdrawn as independent witnesses\n"
    "# (catalog/machines.yaml independent_checkers is empty), so there is no\n"
    "# witness and rule R12a cannot fire. The witnesses\n"
    "# are in the git history of this file. Do not edit.\n"
    "witnesses: []\n")


def write(rows: list[dict], path: Path = DATA) -> None:
    old = {(r["program"], r["checker"]): r for r in _rows(str(path))}
    for r in rows:
        old[(r["program"], r["checker"])] = r
    Path(path).write_text(
        "# Generated by `tools/confirm.py witness`:\n"
        "# independent legality checkers (not under test) on programs every\n"
        "# compiler family rejects. Do not edit.\n" +
        yaml.safe_dump({"witnesses": sorted(old.values(), key=lambda r: (
            r["program"], r["checker"]))}, sort_keys=False, width=1000))
    _rows.cache_clear()
