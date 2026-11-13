"""The legality gate: is a program legal, illegal or unknown.
Catalog programs, fuzz programs that passed offload.engine.fuzz.check and illegal
catalog variants are legal or illegal by construction. ``unknown`` goes to
human review: a checker could not run, or the program is a corpus test, is
outside the device-offload scope, or is a user file the strict checkers reject.

Checkers: for Fortran, the offload scope, offload.engine.rules and gfortran
-std=f2008 -fsyntax-only; for C, the same scope and rules and gcc -std=c11
-fsyntax-only. The front ends in catalog/machines.yaml ``frontend_checkers``
never check their own compiler family, and count only if another checker agrees.

Any other program is ``legal`` only when two independent witnesses accept it
and ``illegal`` only when both reject it: the rules (offload.engine.rules,
offload.engine.prerun.EXTRA) and a front end not under test (for AFAR, NVHPC's
verdict in catalog/legality_witness.yaml). Otherwise it is ``unknown``.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from offload.engine.confirm import machines as M
from offload.engine.confirm import programs as P
from offload.engine.confirm.model import ProgramRef

GCC = shutil.which("gcc") or "/usr/bin/gcc"


@dataclass(frozen=True)
class Legality:
    status: str                    # legal | illegal | unknown
    basis: str
    checks: dict = field(default_factory=dict, hash=False, compare=False)
    rulings: tuple = ()

    def to_dict(self) -> dict:
        return {"status": self.status, "basis": self.basis,
                "checks": dict(self.checks), "rulings": list(self.rulings)}


def _frontend(lang: str, under_test) -> str | None:
    """The front-end checker of a language, None when it belongs to a
    compiler family under test."""
    for name, d in M.frontend_checkers().items():
        if d.get("lang") == lang:
            if d.get("family") in set(under_test or ()):
                return None
            return name
    return None


def _note(checks: dict, name: str, why: str | None) -> str:
    if why:
        checks[name] = why[:300]
        return (f"; {name} rejects it ({why[:120]}), which alone does not "
                "count (RUL-NO-SELF-CHECK)")
    if name:
        checks[name] = "ok"
    return ""


def _rules_extra(text: str, lang: str, model: str) -> list[str]:
    """The restriction checks and the race rule of offload.engine.prerun on
    one source ([] when the rules cannot read it)."""
    from offload.engine import prerun as PR
    from offload.engine.rules import parse_program
    try:
        tree = parse_program(text, 34 if model == "acc" else 52,
                             "c" if lang == "c" else None)
    except Exception:
        return []
    return [f"race: {r}" for r in PR.races(tree, text, lang)] + \
        [f"restriction: {r}" for r in PR.extra(text, lang, tree)]


def _second_witness(ref: ProgramRef, lang: str, under_test, checks: dict,
                    frontend_why) -> tuple[str | None, bool | None]:
    """(witness, accepted) of the second witness: the front end not under
    test (its verdict `frontend_why`: None accepted, else the error), or,
    when it is (an AFAR case), NVHPC's stored verdict on the program's
    source (catalog/legality_witness.yaml); (None, None) when there is
    none."""
    fe = _frontend(lang, under_test)
    if fe is not None:
        if frontend_why == "could not run":
            return None, None
        return fe, frontend_why is None
    from offload.engine.confirm import witness as W
    fam = sorted(set(under_test or ()))[0] if under_test else None
    v = W.verdict_of(ref.ident, ref.sha or "", fam)
    if v is None:
        return None, None
    checks[v[0]] = v[1]
    return v[0], v[1] == "accept"


def _two(checks: dict, rules_why: str | None, second: str | None,
         second_ok: bool | None, base: str, rulings=()) -> Legality:
    """The verdict of the two witnesses."""
    if second is None:
        what = f"violates {rules_why}" if rules_why else "the rules accept it"
        return Legality("unknown", f"one witness only ({what}); no second "
                        "independent witness (the front end is under test "
                        "and no other machine's verdict is stored): legality"
                        " review", checks, tuple(rulings) or (
                            "RUL-NO-SELF-CHECK",))
    if rules_why and not second_ok:
        return Legality("illegal", f"violates {rules_why}; {second} rejects"
                        " it too", checks, tuple(rulings))
    if rules_why or not second_ok:
        return Legality("unknown", "witnesses disagree: the rules "
                        + (f"say it violates {rules_why}" if rules_why else
                           "accept it") + f", {second} "
                        + ("accepts it" if second_ok else
                           f"rejects it ({checks.get(second, '')[:120]})")
                        + ": legality review", checks,
                        tuple(rulings) or ("RUL-NO-SELF-CHECK",))
    return Legality("legal", f"legal by two witnesses (the rules and "
                    f"{second}; {base})", checks, tuple(rulings))


def _fortran(text: str, kind: str, under_test, ref=None) -> Legality:
    from offload.engine import fuzz
    from offload.engine.offload_scope import SCOPE_HOST_DEVICE, scope_of
    hostdev = scope_of(text)[0] == SCOPE_HOST_DEVICE
    checks: dict = {}
    try:
        if not hostdev:
            why = fuzz.check_scope(text)
            if why:
                return Legality("unknown", "outside the device-offload "
                                f"scope: {why[:200]}", {"scope": why},
                                ("RUL-SCOPE-STRUCTURAL",))
        why = fuzz.check_rules(text)
        checks["rules"] = why or "ok"
        if why and why.startswith(("GrammarError", "ProgramError")):
            return Legality("unknown", f"offload.engine.rules cannot read it: "
                            f"{why[:200]}", checks)
        model = "acc" if re.search(r"^\s*!\$acc\b", text, re.M | re.I) \
            and not re.search(r"^\s*!\$omp\b", text, re.M | re.I) \
            else "omp"
        more = _rules_extra(text, "f90", model)
        if more:
            checks["rules"] = "; ".join(([why] if why else []) + more)
            why = checks["rules"]
        if why and ref is None:
            return Legality("illegal", f"violates {why}", checks)
        rules_why = why
        why = fuzz.check_gfortran(text)
        checks["gfortran"] = why or "ok"
        if why:
            # a generated program is f2008 by construction; a user file
            # may use a newer standard
            if kind == "fuzz":
                return Legality("illegal", f"gfortran: {why[:200]}", checks)
            return Legality("unknown", f"gfortran -std=f2008 rejects it: "
                            f"{why[:200]}", checks)
        if fuzz.is_fuzz3(text):
            why = fuzz.check_defined(text)
            checks["defined"] = why or "ok"
            if why:
                return Legality("illegal", why[:200], checks)
        fe = _frontend("f90", under_test)
        fe_why = None
        if fe and model == "omp":
            fe_why = fuzz.check_flang(text)
        elif fe:            # OpenACC: the flang front end with -fopenacc
            from offload.engine import prerun as PR
            ok, msgs = PR.frontend_witness((text, "f90", "acc"))
            fe_why = None if ok else ("could not run" if ok is None
                                      else (msgs or ["rejected"])[0])
        if fe:
            checks[fe] = fe_why or "ok"
    except fuzz.CheckerError as e:
        return Legality("unknown", f"checker could not run: {e}",
                        {"error": str(e)})
    if ref is None:         # the generators' own gate (one-witness form)
        note = _note(checks, fe, fe_why if fe else None)
        return Legality("legal", "legal by the checkers (scope, "
                        "offload.engine.rules, gfortran -std=f2008"
                        + (f", {fe}" if fe else "") + ")" + note, checks,
                        ("RUL-NO-SELF-CHECK",) if note or not fe else ())
    second, ok2 = _second_witness(ref, "f90", under_test, checks, fe_why)
    return _two(checks, rules_why, second, ok2,
                "base language: gfortran -std=f2008 -fsyntax-only")


def _gcc(text: str) -> str | None:
    with tempfile.TemporaryDirectory(prefix="confirm_gcc_") as d:
        (Path(d) / "t.c").write_text(text)
        res = subprocess.run([GCC, "-std=c11", "-fsyntax-only",
                              "-Wno-unknown-pragmas", "t.c"], cwd=d,
                             capture_output=True, text=True, timeout=120)
    if res.returncode == 0:
        return None
    errs = [ln for ln in res.stderr.splitlines() if "error" in ln]
    return (errs[0] if errs else res.stderr[:200]).strip()


def _c(text: str, version: int, kind: str, under_test,
       ref=None) -> Legality:
    from offload.engine.clang_oracle import ClangError, syntax_check
    from offload.engine.grammar import GrammarError
    from offload.engine.offload_scope import (SCOPE_HOST_DEVICE, host_constructs,
                                          scope_of)
    from offload.engine.rules import ProgramError, parse_program, violations
    checks: dict = {}
    v = version or 52
    if scope_of(text)[0] != SCOPE_HOST_DEVICE:
        try:
            host = host_constructs(text, v, "c")
        except (GrammarError, ProgramError) as e:
            return Legality("unknown", f"offload.engine.rules cannot read it: "
                            f"{str(e).splitlines()[0][:200]}", checks)
        if host:
            return Legality("unknown", "outside the device-offload scope: "
                            + "; ".join(f"{h.directive} at line {h.line}"
                                        for h in host), checks,
                            ("RUL-SCOPE-STRUCTURAL",))
    try:
        found = violations(parse_program(text, v, lang="c"), v)
    except (GrammarError, ProgramError) as e:
        return Legality("unknown", f"offload.engine.rules cannot read it: "
                        f"{str(e).splitlines()[0][:200]}", checks)
    found = list(found) + _rules_extra(text, "c", "omp")
    checks["rules"] = found or "ok"
    if found and ref is None:
        return Legality("illegal", f"violates {', '.join(found)}", checks)
    rules_why = ", ".join(found) or None
    base = _gcc(text)
    checks["gcc"] = base or "ok"
    if base:
        return Legality("unknown", f"gcc -std=c11 rejects it: {base}",
                        checks)
    fe = _frontend("c", under_test)
    why = None
    if fe:
        try:
            sc = syntax_check(text, v)
            why = None if sc.ok else (sc.errors[0] if sc.errors
                                      else "rejected")
        except ClangError as e:
            checks[fe] = f"could not run: {e}"
    if ref is None:
        note = _note(checks, fe, why)
        return Legality("legal", "legal by the checkers (scope, "
                        "offload.engine.rules, gcc -std=c11"
                        + (f", {fe}" if fe else "") + ")" + note,
                        checks, ("RUL-NO-SELF-CHECK",) if note or not fe
                        else ())
    if fe:
        checks[fe] = checks.get(fe) or why or "ok"
    fe_state = "could not run" if fe and str(checks.get(fe, "")).startswith(
        "could not run") else why
    second, ok2 = _second_witness(ref, "c", under_test, checks, fe_state)
    return _two(checks, rules_why, second, ok2,
                "base language: gcc -std=c11 -fsyntax-only")


def gate(ref: ProgramRef, fuzz_check: str | None = None,
         under_test=()) -> Legality:
    """The legality of a program. `fuzz_check`: the stored
    offload.engine.fuzz.check stage of a fuzz program; `under_test`: the
    compiler families whose cases these are (their front-end checker is
    not used)."""
    if ref.kind == "catalog":
        if not ref.legal_claim:
            return Legality("illegal", "an illegal catalog variant (tests "
                            "rejection, not a device result)")
        from offload.engine import widen
        if widen.is_wide(ref.ident):
            # A widened program's generator
            return Legality("legal", "legal by construction: "
                            "offload.engine.widen checks every program against "
                            "the offload scope, the catalog rules and the "
                            "base language (gfortran / gcc -fsyntax-only; "
                            "no offload compiler)")
        return Legality("legal", "legal by construction: offload.engine.gen / "
                        "c_gen / acc_gen check every program against the "
                        "catalog rules and the offload scope as it is "
                        "built (no compiler)")
    if ref.kind == "fuzz" and fuzz_check is not None:
        if fuzz_check == "ok" and ref.text:
            # A known generator defect found after the campaign
            # (offload.engine.fuzz.generator_defects): the program is not legal
            from offload.engine import fuzz
            bad = fuzz.generator_defects(ref.text)
            if bad:
                return Legality("illegal", "generator defect: " + bad[0],
                                rulings=("RUL-FUZZ-G1-ILLEGAL",)
                                if bad[0].startswith("G1:") else ())
        if fuzz_check == "ok":
            return Legality("legal", "legal by construction: "
                            "offload.engine.fuzz.check (scope, rules, gfortran, "
                            "definedness, AFAR flang) passed")
        if fuzz_check == "flang":
            # AFAR flang's rejection alone never decides, but
            # the definedness check after it did not run
            return Legality("unknown", "fuzz check stopped at AFAR flang "
                            "(its rejection alone does not count, "
                            "RUL-NO-SELF-CHECK); the definedness check did "
                            "not run", rulings=("RUL-NO-SELF-CHECK",))
        if fuzz_check == "error":
            return Legality("unknown", "a fuzz checker could not run")
        return Legality("illegal", f"fuzz check stage {fuzz_check}")
    if ref.kind == "ompvv":
        return Legality("unknown", "omp_vv stays untrusted (ruling A): "
                        "its legality is the suite's claim, which the "
                        "confirmer does not take", rulings=(
                            "RUL-OMPVV-UNTRUSTED",))
    if P.split_files(ref.text):
        if ref.lang == "c":
            return Legality("unknown", "a C program set: no checker reads "
                            "several translation units")
    # A file (finding, benchmark, reproducer) needs two witnesses
    two = ref if ref.kind not in ("catalog", "fuzz", "ompvv") else None
    if ref.lang == "c":
        return _c(ref.text, ref.version, ref.kind, under_test, two)
    return _fortran(ref.text, ref.kind, under_test, two)
