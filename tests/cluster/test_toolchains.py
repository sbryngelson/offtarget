import os
import re
import sys
import subprocess
from pathlib import Path

import pytest

from offload.engine.toolchains import TOOLCHAINS, loaded_rocm_version

ROOT = Path(__file__).parent.parent.parent
DEV_F90 = Path(__file__).parent.parent / "data" / "dev.f90"


def test_commands_are_self_contained():
    prelude = TOOLCHAINS["cce19"].prelude
    assert "module load cce/19.0.0 craype-accel-amd-gfx942 rocm/6.4.3" in \
        prelude
    assert "|" not in prelude


def test_cce_preludes_pin_versions_and_unload_mpich():
    """Every CCE prelude names its compiler and ROCm
    versions (no site default) and unloads cray-mpich, whose GPU transport
    library (libmpi_gtl_hsa) the site's 2026-10-22 PE update built against
    ROCm 7 (CCE 19/20 executables then failed to load with rocm/6.4.3)."""
    import re
    for name, rocm in (("cce19", "6.4.3"), ("cce20", "6.4.3"),
                       ("cce21", "7.2.0")):
        pre = TOOLCHAINS[name].prelude
        assert re.search(r"module load cce/\d+\.\d+\.\d+ ", pre)
        assert f" rocm/{rocm}" in pre
        assert pre.strip().endswith("module unload cray-mpich")


def test_cce21_4_is_a_pinned_regression_toolchain():
    """Cce/21.0.4 (the Tuolumne site default from 2026-10-22) is
    a toolchain of its own for regression mode, pinned like cce21 (same
    ROCm, cray-mpich unloaded), never a headline column."""
    from offload.engine.toolchains import (GFX942_TOOLCHAINS,
                                       REGRESSION_TOOLCHAINS, family)
    tc = TOOLCHAINS["cce21_4"]
    assert "module load cce/21.0.4 craype-accel-amd-gfx942 rocm/7.2.0" \
        in tc.prelude
    assert tc.prelude.strip().endswith("module unload cray-mpich")
    assert (tc.arch, tc.machine, tc.xnack_modes) == ("gfx942", "tuolumne",
                                                     (0, 1))
    assert tc.base == "cce21_4" and family("cce21_4") == "cce19"
    assert "cce21_4" not in GFX942_TOOLCHAINS
    assert REGRESSION_TOOLCHAINS["cce21_4"] == "cce21"


def test_afar_has_quadmath_path():
    cmd = TOOLCHAINS["afar"].compile_cmd("a.f90", "a.out")
    assert "-L/usr/lib/gcc/x86_64-redhat-linux/8" in cmd
    assert "--offload-arch=gfx942" in cmd


def test_run_env():
    tc = TOOLCHAINS["afar"]
    assert tc.run_env(1)["HSA_XNACK"] == "1"
    assert tc.run_env(0)["HSA_XNACK"] == "0"


def test_rocm_version_recorded():
    assert re.match(r"^\d+\.\d+", loaded_rocm_version(TOOLCHAINS["cce19"]))
    assert loaded_rocm_version(TOOLCHAINS["afar"]) is None


@pytest.mark.gpu
@pytest.mark.parametrize("xnack", [1, 0])
@pytest.mark.parametrize("name", ["afar", "cce19"])
def test_device_smoke(name, xnack, tmp_path):
    tc = TOOLCHAINS[name]
    exe = tmp_path / "dev.out"
    build = subprocess.run(
        ["bash", "-c", tc.compile_cmd(str(DEV_F90), str(exe))],
        capture_output=True, text=True, cwd=tmp_path)
    assert build.returncode == 0, build.stderr
    env = {**os.environ, **tc.run_env(xnack),
           "OMP_TARGET_OFFLOAD": "mandatory"}
    run_cmd = f"{tc.prelude}\n{exe}" if tc.prelude else str(exe)
    # a hung run fails the test instead of blocking the suite (the AFAR HSA_XNACK=1 smoke run hung once for 20 min)
    run = subprocess.run(["bash", "-c", run_cmd], capture_output=True, text=True,
                         env=env, cwd=tmp_path, timeout=300)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "ran_on_host=0"


CLEAN_ENV = {"PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"]}


@pytest.mark.gpu
def test_cce_works_in_clean_env(tmp_path):
    """The recipe must not rely on the caller's shell having `module`."""
    tc = TOOLCHAINS["cce19"]
    exe = tmp_path / "dev.out"
    build = subprocess.run(
        ["env", "-i", *(f"{k}={v}" for k, v in CLEAN_ENV.items()), "bash", "-c",
         tc.compile_cmd(str(DEV_F90), str(exe))],
        capture_output=True, text=True, cwd=tmp_path)
    assert build.returncode == 0, build.stderr
    run = subprocess.run(
        ["env", "-i", *(f"{k}={v}" for k, v in CLEAN_ENV.items()),
         "OMP_TARGET_OFFLOAD=mandatory", "bash", "-c",
         f"{tc.prelude}\n{exe}"],
        capture_output=True, text=True, cwd=tmp_path)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "ran_on_host=0"
    probe = subprocess.run(
        ["env", "-i", *(f"{k}={v}" for k, v in CLEAN_ENV.items()),
         sys.executable, "-I", "-c",
         f"import sys; sys.path.insert(0, {str(ROOT)!r});"
         "from offload.engine.toolchains import *;"
         "print(loaded_rocm_version(TOOLCHAINS['cce19']))"],
        capture_output=True, text=True, cwd=ROOT)
    assert probe.returncode == 0, probe.stderr
    assert re.match(r"^\d+\.\d+", probe.stdout)


def test_flags_are_public():
    for tc in TOOLCHAINS.values():
        # An NVHPC build is for one memory mode (a compile flag)
        tc = tc.for_mode(tc.xnack_modes[0])
        assert f"{tc.flags()} -O2 " in tc.compile_cmd("a.f90", "a.out")


# --- The machine/arch axis (Tioga MI250X, gfx90a) ----------------

def test_gfx90a_toolchains_mirror_the_gfx942_ones():
    from offload.engine.toolchains import ARCH_SUFFIX, base_name
    for name in ("afar", "cce19", "cce20", "cce21"):
        g = TOOLCHAINS[f"{name}_g90"]
        assert g.arch == "gfx90a" and g.machine == "tioga"
        assert TOOLCHAINS[name].arch == "gfx942"
        assert TOOLCHAINS[name].machine == "tuolumne"
        assert base_name(g.name) == name and base_name(name) == name
        assert g.name == name + ARCH_SUFFIX["gfx90a"]


def test_gfx90a_flags_target_gfx90a():
    from offload.engine.toolchains import Toolchain
    import dataclasses
    a = TOOLCHAINS["afar_g90"]
    cmd = a.compile_cmd("a.f90", "a.out")
    assert "--offload-arch=gfx90a " in cmd and "gfx942" not in cmd
    # Tioga has no libquadmath dev link where AFAR looks (seen in a smoke run)
    assert "-L/usr/lib/gcc/x86_64-redhat-linux/8" in cmd
    assert "/opt/afar/" in a.fc
    ac = dataclasses.replace(a, lang="c")
    assert "--offload-arch=gfx90a" in ac.flags()
    cc = dataclasses.replace(TOOLCHAINS["cce19_g90"], lang="c")
    assert "-march=gfx90a" in cc.flags() and "gfx942" not in cc.flags()
    assert TOOLCHAINS["cce19_g90"].flags() == "-fopenmp"
    acc = dataclasses.replace(TOOLCHAINS["cce20_g90"], model="acc")
    assert acc.flags() == "-h acc"
    with pytest.raises(ValueError):
        dataclasses.replace(a, model="acc").flags()
    # by name: tests/cluster/test_reports.py reloads offload.engine.toolchains, which makes a new class
    assert type(a).__name__ == Toolchain.__name__ and dataclasses.is_dataclass(a)


def test_gfx90a_preludes_pin_versions_and_unload_mpich():
    for name, rocm in (("cce19", "6.4.3"), ("cce20", "6.4.3"),
                       ("cce21", "7.2.0")):
        pre = TOOLCHAINS[f"{name}_g90"].prelude
        assert "craype-accel-amd-gfx90a" in pre and "gfx942" not in pre
        assert f" rocm/{rocm}" in pre
        assert pre.strip().endswith("module unload cray-mpich")
        assert "|" not in pre


def test_gfx90a_runs_at_xnack0_only():
    """XNACK is not recommended on MI250X; Tioga
    runs at HSA_XNACK=0 only (set explicitly)."""
    g = TOOLCHAINS["afar_g90"]
    assert g.run_env(0)["HSA_XNACK"] == "0"
    with pytest.raises(ValueError):
        g.run_env(1)
    # the AFAR runtime libraries are found at run time on Tioga
    assert "/opt/afar/" in g.run_env(0)["LD_LIBRARY_PATH"]


def test_family_and_device_of_gfx90a_toolchains():
    from offload.engine.toolchains import device_of, family
    assert family("cce21_g90") == "cce19"
    assert family("afar_g90") == "afar"
    assert device_of(TOOLCHAINS["afar_g90"]) == "gfx90a (AMD Instinct MI250X)"
    assert device_of(TOOLCHAINS["cce19"]) == "gfx942 (AMD Instinct MI300A)"


def test_parse_rocminfo_gpu():
    from offload.engine.toolchains import parse_rocminfo
    text = ("  Name:                    AMD EPYC 7A53 64-Core Processor\n"
            "  Marketing Name:          AMD EPYC 7A53 64-Core Processor\n"
            "  Name:                    gfx90a                             \n"
            "  Uuid:                    GPU-1234                           \n"
            "  Marketing Name:          AMD Instinct MI250X                \n"
            "      Name:                    amdgcn-amd-amdhsa--gfx90a:"
            "sramecc+:xnack-\n")
    assert parse_rocminfo(text) == ("gfx90a", "AMD Instinct MI250X")
    assert parse_rocminfo("no agents") == ("", "")


def test_code_object_targets_reads_the_triples():
    from offload.engine.toolchains import code_object_targets
    assert code_object_targets(
        b"xx\0amdgcn-amd-amdhsa--gfx90a\0yy") == ["amdgcn-amd-amdhsa--gfx90a"]
    assert code_object_targets(
        b"amdgcn-amd-amdhsa--gfx90a:xnack-\0") == [
            "amdgcn-amd-amdhsa--gfx90a:xnack-"]
    assert code_object_targets(b"nothing") == []


def test_toolchain_meta_records_modules_and_code_object(tmp_path):
    """Run metadata: the modules a prelude loads and the code-object
    target of a compiled smoke program."""
    from offload.engine.toolchains import Toolchain, toolchain_meta
    fakes = Path(__file__).parent.parent / "data" / "fakes"
    exe = tmp_path / "fake_exe"
    exe.write_bytes(b"#!/bin/sh\n# amdgcn-amd-amdhsa--gfx90a\necho hi\n")
    tc = Toolchain("cce19_g90", "", f"{fakes}/fake_fc.sh - 0 {exe}",
                   arch="gfx90a", machine="tioga", xnack_modes=(0,))
    m = toolchain_meta(tc, tmp_path)
    assert m["arch"] == "gfx90a" and m["machine"] == "tioga"
    assert m["device"] == "gfx90a (AMD Instinct MI250X)"
    assert m["modules"] == []
    assert m["code_object"] == ["amdgcn-amd-amdhsa--gfx90a"]


def test_parse_module_list():
    from offload.engine.toolchains import parse_module_list
    text = ("Currently Loaded Modules:\ncce/19.0.0\ncraype-accel-amd-gfx90a\n"
            "rocm/6.4.3\n\n")
    assert parse_module_list(text) == ["cce/19.0.0",
                                       "craype-accel-amd-gfx90a",
                                       "rocm/6.4.3"]


def test_arch_of_an_unknown_toolchain_raises():
    """No default arch for a name the registry does
    not know (an `nvhpc` toolchain was recorded as gfx942)."""
    from offload.engine.toolchains import arch_of
    assert arch_of("afar") == "gfx942" and arch_of("cce21_g90") == "gfx90a"
    assert arch_of("cce21_4") == "gfx942"
    assert arch_of("nvhpc") == "sm_80"  # Registered
    with pytest.raises(KeyError, match="unknown toolchain xlf"):
        arch_of("xlf")


def test_toolchain_registry_is_consistent():
    """Every registered toolchain has a machine in catalog/machines.yaml
    with its arch, is listed there (or is a regression toolchain), and is
    a support-table column (or the gfx90a twin of one)."""
    from offload.engine.toolchains import check_registry
    assert check_registry() == []


def _catalog_with(tmp_path, **entries):
    """A copy of catalog/toolchains.yaml with `entries` added, loaded."""
    import yaml
    from offload.engine import toolchains as T
    data = yaml.safe_load(T.CATALOG.read_text())
    data["toolchains"].update(entries)
    p = tmp_path / "toolchains.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_check_registry_names_an_unregistered_toolchain(tmp_path):
    """A toolchain on a machine catalog/machines.yaml lacks, with no
    canaries, that is no support-table column (a gfx90a toolchain that is
    not a twin): check_registry names each problem."""
    from offload.engine import toolchains as T
    reg = T.load(_catalog_with(tmp_path, xlf={
        "family": "cce", "version": "1.0", "machine": "nvidia", "arch": "gfx90a",
        "modes": ["copy"], "label": "XLF", "lane": "tuolumne",
        "modules": {"cce": "1.0", "rocm": "7.2.0"}}))
    problems = "\n".join(T.check_registry(reg))
    assert "xlf" in problems and "machine nvidia" in problems
    assert "support-table column" in problems
    assert "no canaries" in problems


# --- the catalog (catalog/toolchains.yaml) --------------------------------

def test_the_catalog_is_the_registry():
    """offload.engine.toolchains reads catalog/toolchains.yaml: the module's
    lists are the catalog's, every toolchain names a family of the catalog
    and a machine of catalog/machines.yaml."""
    from offload.engine import toolchains as T
    from offload.engine.confirm import machines as M
    reg = T.registry()
    assert list(reg.toolchains) == list(T.TOOLCHAINS)
    for name, tc in reg.toolchains.items():
        assert tc.family_id in reg.families, name
        assert tc.machine in M.load(), name
        assert tc.lane in reg.lanes()
    # the gfx942 toolchains of the families that witness for each other (GCC is under test only)
    witness = tuple(t for t in reg.of_machine("tuolumne")
                    if reg.toolchains[t].family_id not in reg.under_test_only())
    assert T.GFX942_TOOLCHAINS == witness and "gcc" in reg.of_arch("gfx942")
    assert T.NVIDIA_TOOLCHAINS == reg.of_gpu("nvidia")
    # the lists are derivations of the catalog's attributes, not literals (a new release
    # changes them without a test edit)
    assert T.REGRESSION_TOOLCHAINS == reg.regression() == {
        n: t.regression_of for n, t in reg.toolchains.items() if t.regression_of}
    assert set(reg.under_test_only()) == {f.id for f in reg.families.values() if f.under_test_only}
    assert reg.merged() == tuple(n for n in reg.headline() if reg.toolchains[n].merged_key)
    assert "cce21_4" in reg.regression() and "gcc" in reg.under_test_only()


def test_labels_versions_and_twins_come_from_the_catalog():
    from offload.engine import toolchains as T
    reg = T.registry()
    assert reg.label("cce19") == "CCE 19"
    assert reg.label("cce19_g90") == "CCE 19 gfx90a"    # a twin: its base's label and arch
    assert reg.label("gcc_sm80") == "GCC 16.2"
    v = reg.versions()
    assert v["afar"] == ("afar", "AFAR 24.3.0", 0)
    assert v["cce21_4"] == ("cce", "21.0.4", 3)
    assert v["gcc"][2] == v["gcc_sm80"][2] == 0           # one release, two installs
    assert "cce19_g90" not in v                           # the site keys cells by machine
    assert reg.twins()["cce21_g90"] == "cce21" and reg.twin("afar", "gfx90a") == "afar_g90"
    assert T.TOOLCHAINS["gcc"].targets() == ("mi300a-u", "mi300a-c", "mi250x", "mi300x", "mi350x")
    assert reg.twins_of("gcc") == ("gcc_g90", "gcc_mi300x", "gcc_mi350x") and "gcc_g90" not in v
    assert T.TOOLCHAINS["afar"].targets() == ("mi300a-u", "mi300a-c", "mi250x", "mi300x", "mi350x")
    assert reg.family_order() == ("cce", "afar", "nvhpc", "gcc")


def test_a_twin_on_a_machine_of_the_same_arch_is_named_after_the_machine(tmp_path):
    """A twin on a machine whose arch has no twin suffix (MI300X is gfx942, as MI300A) is
    named <base>_<machine>; a twin on gfx90a keeps the arch's suffix. Both strip to the base,
    and a compiler's twins come in catalog order."""
    from offload.engine import toolchains as T
    twin = {"family": "afar", "version": "24.3.0", "arch": "gfx942", "modes": ["copy"],
            "twin_of": "afar", "lane": "tuolumne", "install": {"default": "/opt/afar"},
            "fc": "{root}/bin/amdflang", "cc": "{root}/bin/amdclang"}
    reg = T.registry()
    assert reg.twins_of("afar") == ("afar_g90", "afar_mi300x", "afar_mi350x")
    assert reg.base_of("afar_mi300x") == "afar" and reg.base_of("afar_g90") == "afar"
    assert reg.base_of("afar") == "afar" and reg.base_of("not_registered_g90") == "not_registered"
    assert reg.twin_tag("afar_g90") == "gfx90a" and reg.twin_tag("afar_mi300x") == "mi300x"
    assert reg.twin_key("afar_g90") == "_g90" and reg.twin_key("afar_mi300x") == "_mi300x"
    assert reg.label("afar_mi300x") == "AFAR MI300X" and reg.label("afar_g90") == "AFAR gfx90a"
    assert "afar_mi300x" not in reg.of_arch("gfx942")      # an arch's toolchains are no twins
    with pytest.raises(ValueError, match="is named afar_g90 or afar_tioga"):
        T.load(_catalog_with(tmp_path, afar_x=dict(twin, machine="tioga", arch="gfx90a")))
    with pytest.raises(ValueError, match="is named afar_mi300x"):
        T.load(_catalog_with(tmp_path, afar_x=dict(twin, machine="mi300x")))


def test_run_targets_are_the_machines_of_a_toolchain_and_its_twins():
    """The can-use cells a compiler can have: its machine's modes and its twins' (any other
    GPU is n/a there, not unknown)."""
    from offload.engine import toolchains as T
    reg = T.registry()
    assert reg.run_targets("afar") == ("mi300a-u", "mi300a-c", "mi250x", "mi300x", "mi350x")
    assert reg.run_targets("cce19") == ("mi300a-u", "mi300a-c", "mi250x")
    assert reg.run_targets("cce21_4") == ("mi300a-u", "mi300a-c")
    assert reg.run_targets("nvhpc") == ("a100-s", "a100-m")


def test_flags_come_from_the_family_templates():
    import dataclasses
    from offload.engine import toolchains as T
    assert "-march=gfx942" in dataclasses.replace(T.TOOLCHAINS["cce21"], lang="c").flags()
    assert T.TOOLCHAINS["gcc_sm80"].for_mode(0).flags().endswith(
        "-foffload-options=nvptx-none=-latomic")
    assert "latomic" not in T.TOOLCHAINS["gcc_g90"].flags()
    assert "-gpu=cc80" in T.TOOLCHAINS["nvhpc"].for_mode(0).flags()
    assert T.TOOLCHAINS["cce19"].family.name == "CCE"
    with pytest.raises(ValueError, match="does not support OpenACC"):
        dataclasses.replace(T.TOOLCHAINS["afar"], model="acc").flags()


def test_public_paths_of_the_site_commands():
    from offload.engine import toolchains as T
    afar, nv, gcc = (T.TOOLCHAINS[n] for n in ("afar", "nvhpc", "gcc_sm80"))
    assert afar.public(f"{T.AFAR_BIN}/amdflang -O2") == "$AFAR/bin/amdflang -O2"
    assert afar.public(f"{T.AFAR_BIN_G90}/amdclang") == "$AFAR/bin/amdclang"   # the Tioga copy too
    assert nv.public(f"{T.NVHPC_BIN}/nvfortran -mp=gpu") == "nvfortran -mp=gpu"
    assert nv.public(dict(nv.env)["LD_LIBRARY_PATH"]) == "$NVHPC_25_11/compilers/lib"
    assert gcc.public(dict(gcc.env)["LD_LIBRARY_PATH"]) == "$GCC_16_2/lib64"


def test_a_bad_catalog_is_refused(tmp_path):
    import yaml
    from offload.engine import toolchains as T
    data = yaml.safe_load(T.CATALOG.read_text())

    def refused(edit, match):
        d = yaml.safe_load(yaml.safe_dump(data))
        edit(d)
        p = tmp_path / "t.yaml"
        p.write_text(yaml.safe_dump(d))
        with pytest.raises(ValueError, match=match):
            T.load(p)
    refused(lambda d: d["toolchains"]["cce19"].update(family="xlf"), "unknown family")
    refused(lambda d: d["toolchains"]["cce19"].update(modes=["managed"]), "no managed mode")
    refused(lambda d: d["toolchains"]["cce19"].pop("label"), "no label")
    refused(lambda d: d["toolchains"]["cce19_g90"].update(twin_of="cce20"), "is named cce20_g90")
    refused(lambda d: d["families"]["cce"].pop("flags"), "no flags")
    refused(lambda d: d["toolchains"]["cce19"].pop("modules"), "names {cce}")


def test_another_catalog_through_the_environment(tmp_path, monkeypatch):
    """COMPLIANT_TOOLCHAINS points the registry at another catalog (the
    fake-compiler proof, tests/cluster/test_reports.py)."""
    from offload.engine import toolchains as T
    p = _catalog_with(tmp_path, cce99={
        "family": "cce", "version": "99.0.0", "machine": "tuolumne", "arch": "gfx942",
        "modes": ["unified", "copy"], "label": "CCE 99", "lane": "tuolumne",
        "modules": {"cce": "99.0.0", "rocm": "7.2.0"}})
    monkeypatch.setenv(T.CATALOG_ENV, str(p))
    T.reset()
    try:
        reg = T.registry()
        assert "cce99" in reg.toolchains
        assert "module load cce/99.0.0 craype-accel-amd-gfx942 rocm/7.2.0" in \
            reg.toolchains["cce99"].prelude
        assert "cce99" in reg.of_machine("tuolumne")
    finally:
        monkeypatch.delenv(T.CATALOG_ENV)
        T.reset()
    assert "cce99" not in T.registry().toolchains
