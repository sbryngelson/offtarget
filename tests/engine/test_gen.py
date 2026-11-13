"""Tests of the program generator (offload.engine.gen).

The base-language check runs gfortran (an approved checker only, never a
test target) as ``gfortran -std=<level> -fsyntax-only`` WITHOUT -fopenmp,
so every OpenMP directive is a comment and only the Fortran is checked.
It is marked ``gfortran`` (select with ``-m gfortran``, skip with
``-m "not gfortran"``); it runs by default.
"""
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import pytest

from offload.engine import gen
from offload.engine.catalog import semantic_atoms, slice_atoms
from offload.engine.grammar import parse_directive
from offload.engine.rules import (acc_rules, default_rules, parse_program,
                              violations)

VERSIONS = (50, 52, 60)
CONTROLS = Path(__file__).resolve().parent.parent / "data" / "controls"
RESULT = re.compile(r"print '\(a,i0,a,a\)', 'RESULT ran_on_host=', host_flag, "
                    r"' check=', merge\('pass', 'fail', ok\)")


@lru_cache(maxsize=None)
def programs(version: int) -> tuple:
    return tuple(gen.generate(slice_atoms(version), version))


def legal(version):
    """The atoms' device-only programs (host+device patterns are
    extra programs, tests/test_offload.py)."""
    return [p for p in programs(version) if p.legal and p.scope == "device"]


def illegal(version):
    return [p for p in programs(version) if not p.legal]


@pytest.mark.parametrize("version", VERSIONS)
def test_every_slice_atom_has_a_program(version):
    covered = {p.primary_atom for p in legal(version)}
    skipped = set(gen.UNGENERATABLE.get(version, {}))
    assert skipped <= set(slice_atoms(version))
    assert covered == set(slice_atoms(version)) - skipped
    assert len(legal(version)) == len(covered)  # one per atom
    assert len(skipped) <= 5  # small, and each with a reason
    assert all(gen.UNGENERATABLE[version][a].strip() for a in skipped)


@pytest.mark.parametrize("version", VERSIONS)
def test_legal_programs_have_no_violations(version):
    bad = {}
    for p in legal(version):
        assert p.violates is None
        found = violations(parse_program(p.source, version), version)
        if found:
            bad[p.id] = found
    assert bad == {}


@pytest.mark.parametrize("version", VERSIONS)
def test_illegal_violates_exactly_one(version):
    progs = illegal(version)
    assert progs
    bad = {}
    for p in progs:
        found = violations(parse_program(p.source, version), version)
        if found != [p.violates]:
            bad[p.id] = (p.violates, found)
    assert bad == {}
    assert {p.violates for p in progs} == {
        r for r in gen.VIOLATIONS if r.startswith(f"OMP{version}-")}


def test_every_static_rule_has_a_transform():
    # OpenMP and OpenACC rules share VIOLATIONS
    rules = default_rules() + acc_rules()
    static = {r.id for r in rules if r.check == "static"}
    runtime = {r.id for r in rules if r.check == "runtime"}
    assert static == set(gen.VIOLATIONS) | set(gen.NOT_GENERATABLE)
    assert not set(gen.VIOLATIONS) & set(gen.NOT_GENERATABLE)
    assert not (set(gen.VIOLATIONS) | set(gen.NOT_GENERATABLE)) & runtime
    assert all(isinstance(why, str) and why.strip()
               for why in gen.NOT_GENERATABLE_WHY.values())
    assert set(gen.NOT_GENERATABLE_WHY) == set(gen.NOT_GENERATABLE)


@pytest.mark.parametrize("version", VERSIONS)
def test_programs_self_report(version):
    for p in programs(version):
        assert p.lang == "fortran"
        assert len(RESULT.findall(p.source)) == 1, p.id
        assert "use omp_lib, only: " in p.source
        assert "omp_is_initial_device()" in p.source
        # no other output statements
        assert len(re.findall(r"^\s*(print|write)\b", p.source, re.M)) == 1


@pytest.mark.parametrize("version", VERSIONS)
def test_primary_atom_in_atoms(version):
    for p in programs(version):
        assert p.primary_atom in p.atoms, p.id
        tree = parse_program(p.source, version)
        parsed = set().union(*(d.atoms for d in tree.directives),
                             *(d.atoms for d in tree.ends.values()))
        # a semantic atom (no directive carries it) is the one addition
        if p.primary_atom in semantic_atoms():
            assert p.primary_atom not in parsed, p.id
            parsed.add(p.primary_atom)
        assert p.atoms == frozenset(parsed), p.id


# programs whose check must depend on a data-mapping construct: a presence
# assertion (omp_target_is_present) or a present map
PRESENCE_ATOMS = {
    "omp.directive.target_data", "omp.directive.target_enter_data",
    "omp.directive.target_exit_data", "omp.clause.map.alloc",
    "omp.clause.map.release", "omp.clause.map.delete",
    "omp.clause.map.storage", "omp.clause.nogroup",
    "omp.clause.nogroup.do_not_synchronize", "omp.clause.nogroup.directive_name",
    "omp.clause.transparent", "omp.clause.transparent.impex_type",
    "omp.clause.transparent.directive_name"}
COPY_MODE_ONLY = {
    "omp.directive.target_update", "omp.clause.use_device_ptr",
    "omp.clause.is_device_ptr", "omp.clause.use_device_addr"}
# Has_device_addr is unverified (an oracle is possible, not
# written); its directive-name form names the only taker (equivalent default)
UNVERIFIED = {"omp.clause.has_device_addr"}
ZERO_COPY = {"omp.clause.unified_shared_memory",
             "omp.clause.unified_shared_memory.required",
             "omp.clause.unified_shared_memory.directive_name",
             "omp.clause.self_maps", "omp.clause.self_maps.required",
             "omp.clause.self_maps.directive_name", "omp.clause.map.self",
             "omp.clause.defaultmap.self"}


@pytest.mark.parametrize("version", VERSIONS)
def test_evidence_and_needs(version):
    by_atom = {p.primary_atom: p for p in legal(version)}
    for p in programs(version):
        assert p.evidence in gen.EVIDENCE, p.id
        assert set(p.needs) <= set(gen.NEEDS), p.id
        assert f"! evidence: {p.evidence}" in p.source
        assert ("! needs: " + (", ".join(p.needs) or "none")) in p.source
    for atom in PRESENCE_ATOMS & set(by_atom):
        assert by_atom[atom].evidence == "copy_mode_only", atom
        src = by_atom[atom].source
        assert "omp_target_is_present(" in src \
            or re.search(r"map\(present\b", src), atom
    for atom in COPY_MODE_ONLY & set(by_atom):
        assert by_atom[atom].evidence == "copy_mode_only", atom
    for atom in UNVERIFIED & set(by_atom):
        assert by_atom[atom].evidence == "unverified", atom
        assert "! clause not checked: has_device_addr" in by_atom[atom].source
    assert "c_associated(c_loc(a), ha)" in by_atom[
        "omp.clause.use_device_addr"].source
    for atom, p in by_atom.items():
        if atom.startswith(("omp.clause.to.", "omp.clause.from.")) \
                or atom in ("omp.clause.to", "omp.clause.from"):
            assert p.evidence in ("copy_mode_only", "unverified", "probe",
                                  "equivalent_default"), atom
    for atom in ZERO_COPY & set(by_atom):
        assert by_atom[atom].needs == ("zero_copy",), atom
    for p in programs(version):  # legal and illegal
        assert gen.needs_zero_copy(p.source) == ("zero_copy" in p.needs), p.id
    for atom, p in by_atom.items():
        if atom.startswith(("omp.clause.nogroup", "omp.clause.transparent")):
            clause = atom.split(".")[2]
            assert f"! clause not checked: {clause}" in p.source, atom
            assert not p.observable, atom
        if "workdistribute" in atom and atom.startswith("omp.directive"):
            assert "! unverified: no toolchain compiles this" in p.source
    for atom in ("omp.clause.use_device_ptr", "omp.clause.is_device_ptr"):
        assert by_atom[atom].needs == ("device_c_f_pointer",), atom


@pytest.mark.parametrize("version", VERSIONS)
def test_probe_programs_read_a_device_copy(version):
    """A probe program's construct reads on_dev, whose device copy only the
    probe region sets: a host fallback of the construct fails the check."""
    probes = [p for p in legal(version) if "ran_on_host: probe" in p.source]
    assert probes
    for p in probes:
        assert "!$omp declare target(on_dev)" in p.source
        assert "omp.clause.to" not in p.atoms \
            and "omp.clause.enter" not in p.atoms, p.id
        assert "omp.directive.declare_target" in p.atoms
        assert re.search(r"b(\(i\))? = 2\*a(\(i\))? \+ on_dev", p.source)
        assert "if (all(b == 2*a)) host_flag = 1" in p.source


@pytest.mark.parametrize("version", VERSIONS)
def test_program_metadata(version):
    ids = [p.id for p in programs(version)]
    assert len(ids) == len(set(ids))
    for p in programs(version):
        assert p.std in gen.STD_LEVELS
        assert f"! observable: {'yes' if p.observable else 'no'}" in p.source
        assert ("! legal: yes" in p.source) == p.legal
    assert any(not p.observable for p in legal(version))


def test_generate_filters_atoms_and_is_deterministic():
    atoms = ["omp.directive.target", "omp.clause.thread_limit"]
    a = list(gen.generate(atoms, 52))
    b = list(gen.generate(atoms, 52))
    assert a == b
    assert {p.primary_atom for p in a if p.legal} == set(atoms)
    assert {p.violates for p in a if not p.legal} == {
        r for r, (base, _) in gen.VIOLATION_BASE.items()
        if r.startswith("OMP52-") and base in atoms}


def test_generate_rejects_unknown_atom():
    with pytest.raises(gen.GenError):
        list(gen.generate(["omp.clause.no_such_clause"], 52))


@pytest.mark.parametrize("version", VERSIONS)
def test_dnm_family_names_a_constituent(version):
    progs = [p for p in legal(version)
             if p.primary_atom.endswith(".directive_name")]
    dnm = {a for a in slice_atoms(version) if a.endswith(".directive_name")}
    assert {p.primary_atom for p in progs} == dnm
    # 5.2: only if takes a directive-name modifier; 6.0: 55 clauses, less
    # copyin's (out of the device-offload scope)
    assert len(dnm) == {50: 1, 52: 1, 60: 54}[version]
    for p in progs:
        clause = p.primary_atom.split(".")[2]
        lines = [line for line in _directive_lines(p.source)
                 if f"omp.clause.{clause}.directive_name"
                 in parse_directive(line, "fortran", version).atoms]
        assert len(lines) == 1, p.id


def _directive_lines(source):
    out, cur = [], []
    for line in source.splitlines():
        if line.lstrip().lower().startswith("!$omp") or cur:
            cur.append(line)
            if not line.rstrip().endswith("&"):
                out.append("\n".join(cur))
                cur = []
    return out


# --- control programs -------------------------------------------------------

def test_control_programs():
    for name in ("host_fallback", "wrong_answer", "hang"):
        src = (CONTROLS / f"{name}.f90").read_text()
        tree = parse_program(src, 52)
        assert violations(tree, 52) == [], name
        assert len(RESULT.findall(src)) == 1, name
    assert "if(.false.)" in (CONTROLS / "host_fallback.f90").read_text()


# --- base-language legality (gfortran without -fopenmp) -----------------------

GFORTRAN = shutil.which("gfortran") or "/usr/tce/bin/gfortran"
HAVE_GFORTRAN = Path(GFORTRAN).is_file()
gfortran_only = pytest.mark.skipif(
    not HAVE_GFORTRAN, reason="gfortran (the base-language checker) is not "
    "installed")


@pytest.fixture(scope="session")
def omp_lib_stub(tmp_path_factory):
    """Directory with omp_lib.mod built from gen.OMP_LIB_STUB (a
    declaration-only module for base-language checking; no compiler's
    OpenMP module is used). pytest removes it with the session's tmp
    directories."""
    d = tmp_path_factory.mktemp("omp_lib_stub")
    src = d / "omp_lib_stub.f90"
    src.write_text(gen.OMP_LIB_STUB)
    subprocess.run([GFORTRAN, "-std=f2008", "-fsyntax-only", "-J", str(d),
                    str(src)], check=True, capture_output=True, text=True,
                   cwd=d)
    assert (d / "omp_lib.mod").is_file()
    return str(d)


def _syntax(prog, stub: str) -> tuple[str, int, str]:
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "p.f90"
        f.write_text(prog.source)
        res = subprocess.run(
            [GFORTRAN, f"-std={prog.std}", "-fsyntax-only", f"-I{stub}",
             "-J", d, str(f)], capture_output=True, text=True, cwd=d)
    return prog.id, res.returncode, res.stderr


def test_omp_lib_stub_declares_every_name_used():
    for v in VERSIONS:
        for p in programs(v):
            only = re.search(r"use omp_lib, only: (.*)", p.source).group(1)
            names = {x.strip() for x in only.split(",")}
            assert names <= gen.OMP_LIB_STUB_NAMES, (p.id, names)
    for name in gen.OMP_LIB_STUB_NAMES:
        assert re.search(rf"\b{name}\b", gen.OMP_LIB_STUB), name


@pytest.mark.gfortran
@gfortran_only
@pytest.mark.parametrize("version", VERSIONS)
def test_programs_legal_in_base_language(version, omp_lib_stub):
    progs = list(programs(version))
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda p: _syntax(p, omp_lib_stub), progs))
    bad = {pid: err for pid, rc, err in results if rc != 0}
    assert bad == {}


@pytest.mark.gfortran
@gfortran_only
def test_controls_legal_in_base_language(omp_lib_stub):
    for f in sorted(CONTROLS.glob("*.f90")):
        with tempfile.TemporaryDirectory() as d:
            res = subprocess.run([GFORTRAN, "-std=f2008", "-fsyntax-only",
                                  f"-I{omp_lib_stub}", "-J", d, str(f)],
                                 capture_output=True, text=True, cwd=d)
        assert res.returncode == 0, (f.name, res.stderr)


# declare target: the oracle must depend on the directive ---------------------------

DT_VARIABLE_ATOMS = {
    50: ["omp.directive.declare_target", "omp.clause.link"],  # no enter
    52: ["omp.directive.declare_target", "omp.clause.enter", "omp.clause.link"],
    60: ["omp.directive.declare_target", "omp.clause.enter",
         "omp.clause.enter.directive_name", "omp.clause.link",
         "omp.clause.link.directive_name", "omp.clause.local",
         "omp.clause.local.directive_name"],
}
DT_PROCEDURE_ATOMS = {
    50: ["omp.clause.device_type", "omp.clause.device_type.any",
         "omp.clause.device_type.nohost"],
    52: ["omp.clause.device_type", "omp.clause.device_type.any",
         "omp.clause.device_type.nohost"],
    60: ["omp.clause.device_type", "omp.clause.device_type.any",
         "omp.clause.device_type.nohost",
         "omp.clause.device_type.directive_name"],
}


@pytest.mark.parametrize("version", VERSIONS)
def test_declare_target_variable_programs_need_the_device_copy(version):
    """A first target region sets dv on the device with no map clause; the
    checked region reads it. Without the directive dv is implicitly
    firstprivate, the write is lost and the check fails (mutation-checked
    on AFAR and CCE, HSA_XNACK 0 and 1)."""
    by_atom = {p.primary_atom: p for p in legal(version)}
    for atom in DT_VARIABLE_ATOMS[version]:
        p = by_atom[atom]
        # a directive-name modifier naming the declare target directive
        # itself is the form without it (equivalent default)
        assert p.observable and p.evidence == (
            "equivalent_default" if atom.endswith(".directive_name")
            else "construct"), atom
        assert re.search(r"!\$omp target\n\s*dv = 5\n\s*!\$omp end target",
                         p.source), atom
        assert "b(i) = 2*a(i) + dv - 4" in p.source, atom
        assert not re.search(r"map\([^)]*\bdv\b[^)]*\)\s*map\(tofrom: "
                             r"host_flag\)", p.source), atom
        assert atom in p.atoms


@pytest.mark.parametrize("version", VERSIONS)
def test_declare_target_procedure_programs_are_not_observable(version):
    """f is referenced in a target construct, so it is implicitly declare
    target (5.2 §13.8 p.285, 6.0 §15.8 p.461): the directive on f cannot
    be told from its absence in a one-file program."""
    by_atom = {p.primary_atom: p for p in legal(version)}
    for atom in DT_PROCEDURE_ATOMS[version]:
        p = by_atom[atom]
        assert not p.observable, atom
        assert "implicitly declare target" in p.source, atom


def test_enter_automap_checks_the_host_copy_in_copy_mode():
    p = next(x for x in legal(60) if x.primary_atom ==
             "omp.clause.enter.automap")
    assert p.evidence == "copy_mode_only"
    assert "if (.not. shared_mem) pres = pres .and. all(pv == a)" in p.source


@pytest.mark.parametrize("version", VERSIONS)
def test_defaultmap_present_lists_the_loop_variable(version):
    # without private(i), AFAR's runtime requires the predetermined-private
    # loop variable i to be present ("device mapping required by 'present'
    # ... (4 bytes)") and aborts
    if "omp.clause.defaultmap.present" not in slice_atoms(version):
        pytest.skip("defaultmap(present) is 5.1")
    p = {q.primary_atom: q for q in legal(version)}[
        "omp.clause.defaultmap.present"]
    line = next(x for x in p.source.splitlines() if "defaultmap(" in x)
    assert "private(i)" in line


def test_ref_ptee_program_maps_the_pointer_it_dereferences():
    # 6.0 §7.9.5: with ref_ptee the map applies to the pointee only, so a
    # region that dereferences p needs p itself mapped (ref_ptr, attached to
    # the pointee that ref_ptee made present)
    p = {q.primary_atom: q for q in legal(60)}["omp.clause.map.ref_ptee"]
    lines = [x.strip() for x in p.source.splitlines()]
    assert "!$omp target enter data map(ref_ptee, to: p)" in lines
    region = next(x for x in lines if x.startswith("!$omp target map("))
    assert "map(ref_ptr, to: p)" in region and "ref_ptee" not in region
    assert "!$omp target exit data map(ref_ptee, release: p)" in lines


# --- oracle validity: the committed audit summary -------------------------

SUMMARY = Path(__file__).resolve().parent.parent / "data" / "oracle_audit_summary.json"
EVIDENCED = ("construct", "copy_mode_only", "probe")
ACCEPTED = ("valid", "unaudited_no_passing_original")


@lru_cache(maxsize=None)
def audit_summary() -> dict:
    import json
    return json.loads(SUMMARY.read_text())


@pytest.mark.parametrize("version", VERSIONS)
def test_audit_summary_matches_generator(version):
    """The summary covers exactly the generator's legal programs at the
    version, audited as generated (same body), so no atom or changed
    program slips in unaudited."""
    from offload.engine.mutate import body_sha
    s = audit_summary()["versions"][str(version)]
    by_atom = {p.primary_atom: p for p in legal(version)}
    assert set(s) == set(by_atom)
    stale = {a: s[a]["program"] for a, p in by_atom.items()
             if s[a]["program"] != p.id
             or s[a]["body_sha"] != body_sha(p.source)
             or s[a]["evidence"] != p.evidence
             or s[a]["observable"] != p.observable}
    assert stale == {}


@pytest.mark.parametrize("version", VERSIONS)
def test_every_observable_atom_is_audited_valid(version):
    """Every observable program whose evidence is construct or
    copy_mode_only belongs to an atom the audit validated (mutant killed
    on at least one toolchain in copy mode), or to one no toolchain passes
    (unaudited); an evidence="unverified" program says why in its header
    (gen.UNVERIFIED), a no-oracle program carries its category as its
    disposition with the reason and the spec basis, a legality
    program names its rule."""
    doc = audit_summary()
    s = doc["versions"][str(version)]
    bad = {}
    for p in legal(version):
        e = s.get(p.primary_atom, {})
        disp = e.get("disposition")
        if p.evidence == "unverified":
            unv = gen.unverified_of(p.source)
            if unv is None or unv[0] not in gen.UNVERIFIED or \
                    disp != f"unverified_{unv[0]}" or not unv[1].strip():
                bad[p.primary_atom] = ("unverified", disp, unv)
        elif p.evidence in gen.NO_ORACLE:
            noo = gen.no_oracle_of(p.source)
            if noo is None or noo[0] != p.evidence or disp != p.evidence \
                    or not noo[1].strip() or not noo[2].strip() \
                    or noo[2] not in e.get("reason", ""):
                bad[p.primary_atom] = ("no oracle", disp, noo)
        elif p.evidence == "legality":
            rid = gen.legality_of(p.source)
            if disp != "legality" or not rid or rid not in e["reason"]:
                bad[p.primary_atom] = ("legality", disp, rid)
        elif p.observable and p.evidence in EVIDENCED:
            if disp not in ACCEPTED:
                bad[p.primary_atom] = (disp, e.get("toolchains"))
            elif disp == "valid" and "killed" not in \
                    e["toolchains"].values():
                bad[p.primary_atom] = ("valid without a kill", e)
            elif disp != "valid" and "correct_on_device" in \
                    e["originals"].values():
                bad[p.primary_atom] = ("unaudited but an original passed", e)
        else:
            assert gen.unverified_of(p.source) is None, p.id
            assert gen.no_oracle_of(p.source) is None, p.id
    assert bad == {}
    assert doc["run"].get("full") is True, "summary not from one full audit"


@pytest.mark.parametrize("version", VERSIONS)
def test_bind_thread_runs_every_iteration_on_every_thread(version):
    # bind(thread) inside a parallel region: each thread runs all n
    # iterations (tot(thread) == n); without bind the team shares them
    p = {q.primary_atom: q for q in legal(version)}["omp.clause.bind.thread"]
    assert p.observable and p.evidence == "construct"
    lines = [x.strip() for x in p.source.splitlines()]
    k = lines.index("!$omp loop bind(thread)")
    assert any(x.startswith("!$omp parallel ") for x in lines[:k])
    assert "all(tot(1:min(nthr, 1024)) == n)" in p.source


@pytest.mark.parametrize("version", VERSIONS)
def test_unverified_programs_that_check_nothing_are_unobservable(version):
    # observable=True on a program without an audited oracle only where its
    # check tests what the atom requires: num_teams lower bound, monotonic
    # order, default(shared: all) on a task, and directive-name
    # forms whose base program has an audited oracle
    for p in legal(version):
        if p.evidence in gen.AUDITED or not p.observable:
            continue
        assert p.primary_atom in (
            "omp.clause.num_teams.lower_bound",
            "omp.clause.schedule.monotonic", "omp.clause.default.all",
            # The check tests what dist_schedule(static) requires
            "omp.clause.dist_schedule", "omp.clause.dist_schedule.static",
            "omp.clause.schedule", "omp.clause.schedule.static") or \
            p.primary_atom.endswith(".directive_name"), p.primary_atom


# --- generator infrastructure must not be what is rejected ---------------------------------------------

def _prog(atom, version):
    (p,) = [p for p in gen.generate([atom], version)
            if p.legal and p.scope == "device"]
    return p


@pytest.mark.parametrize("atom", [
    "omp.clause.device_type", "omp.clause.device_type.any",
    "omp.clause.device_type.nohost"])
def test_procedure_declare_target_uses_to_at_52(atom):
    """CCE 19 rejects the enter spelling (ftn-1725); `to` is valid (if
    deprecated) at 5.2, so the 5.2 program does not depend on enter. At 6.0
    `to` is no longer allowed on declare target and enter stays."""
    src = _prog(atom, 52).source.lower()
    lines = [ln for ln in src.splitlines() if "declare target" in ln]
    assert lines and all("enter(" not in ln for ln in lines), lines
    assert any(re.search(r"declare target to\(", ln) for ln in lines)
    src60 = _prog(atom, 60).source.lower()
    assert "declare target enter(" in src60


def test_hygiene_default_none_needs_tablegen_permission():
    from offload.engine.gen_templates import hygiene
    # default on target teams distribute simd at 5.2 comes only from a
    # provisional spec override; AFAR rejects it there
    assert hygiene("target teams distribute simd", 52, ["a"]) == ""
    assert hygiene("target teams distribute", 52, ["a"]).startswith(
        "default(none)")
    src = _prog("omp.directive.target_teams_distribute_simd", 52).source
    assert "default(" not in src.lower()


@pytest.mark.parametrize("atom", ["omp.clause.uses_allocators.memspace",
                                  "omp.clause.uses_allocators.traits"])
@pytest.mark.parametrize("version", [52, 60])
def test_allocator_handle_has_a_data_sharing_attribute(atom, version):
    """CCE 19 ftn-1510: under default(none) the allocator handle my_alloc
    named in allocate(my_alloc: t) must have a data-sharing attribute."""
    src = _prog(atom, version).source.lower()
    (line,) = [ln for ln in src.splitlines() if "allocate(my_alloc" in ln]
    if "default(none)" in line:
        m = re.search(r"shared\(([^)]*)\)", line)
        assert m and "my_alloc" in [x.strip() for x in m.group(1).split(",")]


# --- / 15: every atom without an audited oracle carries its category ---------

# (agreed): the forms no run can separate carry a no-oracle
# category (gen.NO_ORACLE) as their evidence, with the spec basis;
# "unverified" (gen.UNVERIFIED) only where an oracle is possible and
# missing; default(none) is a legality atom. atom -> expected evidence (an
# unverified one as "unverified:<kind>"), both versions where the atom
# exists; each reason is in the program header and
# data/reports/oracle-audit.md.
DNM_EQUIVALENT = [
    "aligned", "allocate", "bind", "collapse", "default", "defaultmap",
    "depend", "device", "dist_schedule", "enter", "firstprivate", "from",
    "has_device_addr", "in_reduction", "induction", "is_device_ptr",
    "lastprivate", "linear", "link", "local", "map", "message",
    "nontemporal", "num_teams", "num_threads", "order", "ordered", "private",
    "proc_bind", "reduction", "replayable", "safelen", "schedule",
    "severity", "shared", "simdlen", "thread_limit", "to", "use_device_addr",
    "use_device_ptr", "uses_allocators"]
T15_EXPECTED = {
    # The corrected check also accepts the implementation-defined
    # default distribution (AFAR, CCE 19)
    "omp.clause.dist_schedule": "implementation_defined",
    "omp.clause.dist_schedule.static": "implementation_defined",
    # The same reading for schedule(static)
    "omp.clause.schedule": "implementation_defined",
    "omp.clause.schedule.static": "implementation_defined",
    # loop and team parameters
    "omp.clause.schedule.dynamic": "unverified:oracle_not_written",
    "omp.clause.schedule.guided": "unverified:oracle_not_written",
    "omp.clause.schedule.runtime": "unverified:oracle_not_written",
    "omp.clause.schedule.auto": "implementation_defined",
    "omp.clause.schedule.simd": "implementation_defined",
    "omp.clause.schedule.monotonic": "implementation_defined",
    "omp.clause.schedule.nonmonotonic": "equivalent_default",
    "omp.clause.proc_bind": "implementation_defined",
    "omp.clause.proc_bind.close": "implementation_defined",
    "omp.clause.proc_bind.master": "implementation_defined",
    "omp.clause.proc_bind.primary": "implementation_defined",
    "omp.clause.proc_bind.spread": "implementation_defined",
    "omp.clause.ordered.n": "equivalent_default",
    "omp.clause.num_teams.lower_bound": "implementation_defined",
    "omp.clause.bind": "construct",
    "omp.clause.aligned": "hint_only",
    "omp.clause.aligned.alignment": "hint_only",
    "omp.clause.nontemporal": "hint_only",
    "omp.clause.safelen": "hint_only",
    "omp.clause.simdlen": "hint_only",
    "omp.clause.map.close": "hint_only",
    "omp.clause.order": "implementation_defined",
    "omp.clause.order.concurrent": "implementation_defined",
    "omp.clause.order.reproducible": "unverified:oracle_not_written",
    "omp.clause.order.unconstrained": "equivalent_default",
    "omp.clause.nowait": "implementation_defined",
    "omp.clause.nowait.do_not_synchronize": "equivalent_default",
    "omp.clause.has_device_addr": "unverified:oracle_not_written",
    "omp.clause.map.self": "unverified:oracle_not_written",
    "omp.clause.map.ref_ptr_ptee": "equivalent_default",
    "omp.clause.uses_allocators.traits": "unverified:oracle_not_written",
    "omp.clause.uses_allocators.memspace": "equivalent_default",
    "omp.clause.reduction.default": "equivalent_default",
    "omp.clause.linear.val": "equivalent_default",
    "omp.clause.defaultmap.default": "equivalent_default",
    "omp.clause.device.device_num": "equivalent_default",
    "omp.clause.replayable.replayable_expression": "equivalent_default",
    "omp.clause.default.none": "legality",
    "omp.clause.default.shared": "construct",
    "omp.clause.default.all": "equivalent_default",
    "omp.directive.parallel_loop": "construct",
    "omp.directive.teams_loop": "construct",
    "omp.clause.nowait.directive_name": "implementation_defined",
    **{f"omp.clause.{c}.directive_name": "equivalent_default"
       for c in DNM_EQUIVALENT},
}


def _category(p) -> str:
    if p.evidence == "unverified":
        unv = gen.unverified_of(p.source)
        return f"unverified:{unv[0] if unv else '?'}"
    return p.evidence


@pytest.mark.parametrize("version", VERSIONS)
def test_task15_categories(version):
    """Each triaged atom's program has the expected evidence category and,
    for a no-oracle or unverified one, a non-empty reason (and a basis)."""
    by_atom = {p.primary_atom: p for p in legal(version)}
    bad = {}
    # At 5.0 linear's val modifier is for declare simd only (5.0
    # §2.9.2 p.107), so its program is the declare simd form, like ref
    expected = dict(T15_EXPECTED, **({"omp.clause.linear.val": "construct"}
                                     if version == 50 else {}))
    for atom, kind in expected.items():
        p = by_atom.get(atom)
        if p is None:
            continue
        if _category(p) != kind:
            bad[atom] = (_category(p), kind)
        if p.evidence in gen.NO_ORACLE:
            noo = gen.no_oracle_of(p.source)
            if not noo[1].strip() or not noo[2].startswith("OpenMP "):
                bad[atom] = ("no reason or basis", noo)
    assert bad == {}
    # every program without an audited oracle is listed
    rest = {a: _category(p) for a, p in by_atom.items()
            if p.evidence not in gen.AUDITED and a not in expected}
    assert rest == {}


@pytest.mark.parametrize("version", VERSIONS)
def test_no_oracle_programs_quote_the_spec(version):
    """A no-oracle program's basis is the first citation of its basis id
    in catalog/omp/no_oracle.yaml at the program's version."""
    for p in legal(version):
        noo = gen.no_oracle_of(p.source)
        if p.evidence not in gen.NO_ORACLE:
            assert noo is None, p.id
            continue
        assert noo[0] == p.evidence
        texts = {gen.basis_text(b, version) for b, e in
                 gen.no_oracle_bases().items() if version in e}
        assert noo[2] in texts, p.id


@pytest.mark.needs_spec
def test_no_oracle_bases_quote_the_spec_verbatim():
    """Every citation in catalog/omp/no_oracle.yaml names a section of the
    spec text, a page inside it, and a sentence that occurs there verbatim
    (whitespace aside)."""
    import re as _re
    from offload.engine import spec_text
    vtext = {50: "5.0", 52: "5.2", 60: "6.0"}
    bases = gen.no_oracle_bases()
    assert bases
    for bid, by in bases.items():
        assert by, bid
        for v, cites in by.items():
            assert cites, (bid, v)
            for c in cites:
                a = _re.fullmatch(rf"OpenMP {vtext[v]} Appendix A, p\.(\d+)",
                                  c["cite"])
                if a:
                    # The implementation-defined behaviours of
                    # Appendix A (no numbered section in spec_text): the
                    # sentence is on that page
                    page = " ".join(t for pg, t in spec_text._lines(vtext[v])
                                    if pg == int(a.group(1)))
                    assert _re.sub(r"\s+", "", c["quote"]) in \
                        _re.sub(r"\s+", "", page), (bid, c["cite"])
                    continue
                m = _re.fullmatch(rf"OpenMP {vtext[v]} §([\d.]+), p\.(\d+)",
                                  c["cite"])
                assert m, (bid, c["cite"])
                secs = [x for x in spec_text.sections(vtext[v]).values()
                        if x.number == m.group(1)]
                assert len(secs) == 1, (bid, c["cite"])
                sec = secs[0]
                assert sec.first_page <= int(m.group(2)) <= sec.last_page, \
                    (bid, c["cite"])
                assert _re.sub(r"\s+", "", c["quote"]) in \
                    _re.sub(r"\s+", "", sec.text), (bid, c["cite"])


def test_unverified_is_reserved_for_missing_oracles():
    assert set(gen.UNVERIFIED) == {"needs_other_infrastructure",
                                   "oracle_not_written"}
    assert set(gen.NO_ORACLE) == {"hint_only", "implementation_defined",
                                  "equivalent_default"}
    assert set(gen.NO_ORACLE) | {"legality", "unverified"} <= \
        set(gen.EVIDENCE)


def test_task12_reduction_directive_name_is_conforming():
    """reduction(do, ...) on target teams distribute parallel do left the
    teams sharing s (their do reductions race) and, under default(none),
    s without a data-sharing attribute on teams and parallel: the family
    member is reduction(do, ...) on parallel do in a target region, which
    6.0 §19.2 makes the same as the unmodified clause."""
    p = _prog("omp.clause.reduction.directive_name", 60)
    (line,) = [ln.strip() for ln in p.source.splitlines()
               if "reduction(" in ln and ln.strip().startswith("!$omp")]
    assert line.startswith("!$omp parallel do ")
    assert "default(" not in line and "reduction(do, +: s)" in line
    code = [ln for ln in p.source.lower().splitlines()
            if not ln.startswith("! ")]
    assert not any("teams" in ln for ln in code)


# --- Batch 3: present modifiers as negative probes ---------------------------

PRESENT_PROBES = {"omp.clause.map.present": "map(present, to: a)",
                  "omp.clause.to.present": "to(present: a)",
                  "omp.clause.from.present": "from(present: b)"}


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("atom", sorted(PRESENT_PROBES))
def test_present_modifier_is_a_negative_probe(atom, version):
    """The program names an absent item with the present modifier, which
    the spec answers with runtime error termination (5.2 §5.8.3 p.152,
    §5.9 p.165; 6.0 §7.9.6 p.283, §7.10 p.296): it must end there; a run
    that continues sets `continued` and prints check=fail."""
    if atom not in slice_atoms(version):
        pytest.skip("the present modifier is 5.1")
    p = _prog(atom, version)
    assert (p.evidence, p.expect, p.observable) == ("probe",
                                                    "error_termination", True)
    assert gen.unverified_of(p.source) is None
    assert "! expect: error_termination" in p.source
    lines = [x.strip() for x in p.source.splitlines()]
    (k,) = [i for i, x in enumerate(lines)
            if x.startswith("!$omp") and PRESENT_PROBES[atom] in x]
    # the standard kernel (device evidence) runs and unmaps a and b first;
    # nothing enters a or b, so the item is absent at the probe
    assert any(x.startswith("!$omp target map(to: a) map(from: b)")
               for x in lines[:k])
    assert "enter data" not in p.source and "target data" not in p.source
    assert lines[k + (5 if atom.endswith("map.present") else 1)] \
        == "continued = .true."
    assert "ok = all(b == ref) .and. (.not. continued)" in p.source


def test_expect_values_are_known():
    assert set(gen.EXPECT) == {"result", "error_termination",
                               "compile_message", "compile_error"}
    for v in VERSIONS:
        assert {p.expect for p in programs(v)} <= set(gen.EXPECT)
        assert all(p.evidence == "probe" for p in programs(v)
                   if p.expect != "result" and p.legal)


# --- oracles where the triage missed one ---------------------------------------------------------------

ROUND1_EVIDENCE = {
    "omp.directive.parallel_do_simd": "construct",
    "omp.directive.teams_distribute_simd": "construct",
    "omp.directive.teams_distribute_parallel_do_simd": "construct",
    "omp.clause.bind.parallel": "construct",
    "omp.clause.bind.teams": "construct",
    "omp.clause.to.mapper": "copy_mode_only",
    "omp.clause.from.mapper": "copy_mode_only",
    "omp.clause.defaultmap.all": "copy_mode_only",
    "omp.clause.default": "construct",
    "omp.clause.message": "probe",
    "omp.clause.severity": "probe",
    "omp.clause.severity.warning": "probe",
    "omp.clause.severity.fatal": "probe",
}


@pytest.mark.parametrize("version", VERSIONS)
def test_round1_atoms_have_an_oracle(version):
    by_atom = {p.primary_atom: p for p in legal(version)}
    bad = {a: (by_atom[a].evidence, by_atom[a].observable)
           for a, ev in ROUND1_EVIDENCE.items() if a in by_atom
           and (by_atom[a].evidence != ev or not by_atom[a].observable)}
    assert bad == {}


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("atom,query", [
    ("omp.directive.parallel_do_simd", "nthr = omp_get_num_threads()"),
    ("omp.directive.teams_distribute_simd", "nt = omp_get_num_teams()"),
    ("omp.directive.teams_distribute_parallel_do_simd",
     "nt = omp_get_num_teams()")])
def test_simd_compound_directives_query_the_team_in_the_loop(atom, query,
                                                             version):
    """A simd region may call the OpenMP API (only SIMDizable constructs
    are restricted, 5.2 §10.4, 6.0 §12.4); the loop's first iteration
    records the team size or league size."""
    src = _prog(atom, version).source
    lines = [x.strip() for x in src.splitlines()]
    k = next(i for i, x in enumerate(lines) if x.startswith("!$omp ")
             and atom.split(".")[-1].replace("_", " ") in x)
    assert any(query in x for x in lines[k:k + 6])
    assert "on_dev" not in src  # no separate probe region


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("atom,bind,outer", [
    ("omp.clause.bind.parallel", "bind(parallel)", "!$omp parallel"),
    ("omp.clause.bind.teams", "bind(teams)", "!$omp teams")])
def test_bind_programs_use_an_orphaned_loop(atom, bind, outer, version):
    """Without bind an orphaned loop binds to the encountering thread (5.2
    §11.7.1, 6.0 §13.8.1), so each thread (team) would run every
    iteration; with it the team (league) shares them."""
    src = _prog(atom, version).source
    lines = [x.strip() for x in src.splitlines()]
    k = lines.index(f"!$omp loop {bind}")
    sub = max(i for i, x in enumerate(lines[:k]) if x.startswith("subroutine"))
    assert "!$omp declare target" in lines[sub:k]
    assert any(x.startswith(outer) for x in lines if x.startswith("!$omp"))
    assert any(x.startswith("if (omp_get_") and "call work(omp_get_" in x
               for x in lines)
    assert "(sum(tot) == n)" in src
    # Each iteration writes its own element (no counter shared
    # by the loop's iterations, which may run concurrently)
    assert "hit(i, t) = hit(i, t) + 1" in lines and "mine" not in src


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("atom", ["omp.clause.bind.thread", "omp.clause.bind"])
def test_bind_thread_programs_count_without_a_race(atom, version):
    """The loop construct's iterations may execute concurrently
    (5.2 §11.7 p.257), so the bind(thread) programs record each iteration in
    its own element of hit and sum the columns on the host."""
    src = _prog(atom, version).source
    assert "mine" not in src
    assert any("hit(i, " in x and "+ 1" in x for x in src.splitlines())
    assert "tot(k) = tot(k) + hit(i, k)" in src


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("atom", ["omp.clause.schedule",
                                  "omp.clause.dist_schedule"])
def test_static_without_chunk_checks_only_what_the_spec_fixes(atom, version):
    """Without a chunk size the static schedule fixes
    contiguous chunks, at most one per owner (5.2 §11.5.3 p.252, §11.6.1
    p.256); the Note (p.253) calls ceil(n/p) chunks and q / q - 1 splits
    alike compliant, so no size is checked. Both atoms are no-oracle
    implementation_defined (checked) by the same reading."""
    p = _prog(atom, version)
    src = p.source
    assert "_hi" not in src and "_lo" not in src and "count(" not in src
    assert "any(" in src and ">= 0 .and." in src
    assert p.evidence == "implementation_defined" and p.observable


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("atom,clause", [
    ("omp.clause.to.mapper", "to(mapper(mm): s)"),
    ("omp.clause.from.mapper", "from(mapper(mm): s)")])
def test_motion_mapper_names_a_one_component_mapper(atom, clause, version):
    src = _prog(atom, version).source
    assert "map(q%v)" in src and clause in src and "mapper(default)" \
        not in src


@pytest.mark.parametrize("version", VERSIONS)
def test_defaultmap_all_and_base_default_forms(version):
    if version == 50:
        pytest.skip("the all variable-category is 5.2")
    assert "defaultmap(to: all)" in _prog("omp.clause.defaultmap.all",
                                          version).source
    src = _prog("omp.clause.default", version).source
    assert "default(private)" in src and "default(none)" not in src


@pytest.mark.parametrize("atom,sev,expect", [
    ("omp.clause.message", "warning", "compile_message"),
    ("omp.clause.severity", "warning", "compile_message"),
    ("omp.clause.severity.warning", "warning", "compile_message"),
    ("omp.clause.severity.fatal", "fatal", "compile_error")])
def test_error_directive_probes(atom, sev, expect):
    """message/severity (6.0) on an error directive with at(compilation):
    the compiler must show the message (warning) or stop (fatal)."""
    p = _prog(atom, 60)
    assert (p.evidence, p.expect, p.token) == ("probe", expect,
                                                gen.PROBE_TOKEN)
    assert f'!$omp error at(compilation) severity({sev}) ' \
        f'message("{gen.PROBE_TOKEN}")' in p.source


def test_dnm_message_and_severity_keep_the_parallel_do_base():
    for a in ("omp.clause.message.directive_name",
              "omp.clause.severity.directive_name"):
        src = _prog(a, 60).source
        assert "!$omp error" not in src and "!$omp parallel do" in src


# --- Fortran character variables are aggregates (semantic atom) ------

@pytest.mark.parametrize("version", VERSIONS)
def test_defaultmap_character_program(version):
    """No defaultmap clause: ch and s (character) must come back from the
    device (aggregates, implicitly tofrom), k (integer scalar) must not
    (firstprivate)."""
    p = {q.primary_atom: q for q in legal(version)}[
        "omp.clause.defaultmap.character"]
    assert p.id == f"omp{version}-clause-defaultmap-character"
    assert p.observable and p.evidence == "construct" and not p.needs
    assert "defaultmap" not in p.source.split("program gen_prog", 1)[1]
    for decl in ("character :: ch", "character(len=4) :: s", "integer :: k"):
        assert decl in p.source
    assert "ch = 'b'" in p.source and "s = 'wxyz'" in p.source \
        and "k = 2" in p.source
    assert "(ch == 'b') .and. (s == 'wxyz') .and. (k == 1)" in p.source
    assert "! semantic atom: no defaultmap clause" in p.source


def test_only_semantic_atoms_skip_the_carried_atom_check():
    from offload.engine import gen_templates as T
    with pytest.raises(gen.GenError, match="does not exercise"):
        gen._program("omp.clause.defaultmap.scalar", 52,
                      T.defaultmap_character_prog(52))


def test_derivations_are_written_into_the_header():
    """Catalog/omp/derivations.yaml entries appear as one
    `! derivation (<value>): ...` header line of the legal program of each
    listed atom and version, with that version's citations, and leave the
    audited body unchanged."""
    import yaml
    from offload.engine.expected import derivation_evidence
    from offload.engine.gen import DERIVATIONS
    doc = yaml.safe_load(DERIVATIONS.read_text())
    assert doc["entries"]
    for e in doc["entries"]:
        for v in e["versions"]:
            p = _prog(e["atom"], v)
            ev = derivation_evidence(p.source)
            assert ev.value == e["value"], (e["atom"], v)
            assert "{cite:" not in ev.detail and f"{str(v)[0]}." in ev.detail
            heads = [x for x in p.source.splitlines() if x.startswith("!")]
            assert sum(x.startswith("! derivation") for x in heads) == 1


def test_no_derivation_rests_on_a_project_ruling():
    """A derivation is a second source only if it
    derives from the spec text alone, not from this project's reading of
    it (the oracle's own interpretation would make trust circular)."""
    import yaml
    from offload.engine.gen import DERIVATIONS
    doc = yaml.safe_load(DERIVATIONS.read_text())
    for e in doc["entries"]:
        low = e["text"].lower()
        assert not re.search(r"\btask \d|ruling|reports|this "
                             r"project|our reading", low), e["atom"]


@pytest.mark.parametrize("version", (52, 60))
def test_inner_leaf_clause_expressions_are_listed_under_default_none(version):
    """(triage of the clang rejection of omp52-c-clause-if-
    directive_name): on a combined construct a clause split to an inner
    leaf has its expression evaluated inside the outer leaves (5.2 §17.2
    p.340), and default(none) applies to every leaf that permits it (teams,
    parallel), so a variable in if(parallel: ...) is referenced in the
    teams construct and must be listed (5.2 §5.4.1)."""
    import re
    from offload.engine.gen import generate
    (p,) = [p for p in generate(["omp.clause.if.directive_name"], version)
            if p.legal]
    line = " ".join(p.source.replace("&\n", " ").split())
    m = re.search(r"shared\(([^)]*)\)", line)
    assert m and "use_dev" in [x.strip() for x in m.group(1).split(",")]
