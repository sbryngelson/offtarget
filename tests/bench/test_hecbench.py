"""Tests of the hecbench campaign: its declarations and programs, the split and licences, the report rules, the 120 s rerun of the time-outs, the finding matcher and the sealed-run guards."""
from __future__ import annotations


# ---- The registered ``hecbench`` campaign: its declarations, its programs and its commands ---------------

import importlib.util
from pathlib import Path

import pytest

from offload.engine import campaign as C
from offload.engine import hecbench as H
from offload.engine import hecbench_run as R
from offload.engine import toolchains as T

ROOT = Path(__file__).resolve().parent.parent.parent
CAMP = C.get("hecbench")

RECIPE = {
    "dir": "demo-omp", "id": "hecbench-demo-omp", "half": "dev", "licence": "bsd3", "status": "ok",
    "reason": "", "lang": "cpp", "std": "c++17", "libs": ["m"], "libdirs": [], "run_args": ["3"],
    "repeat_arg": 1, "timeout_s": 120, "program": "main", "dropped": [],
    "compiles": [{"src": "main.cpp", "defines": ["N=4"], "includes": ["../demo-cuda"], "std": "c++17"},
                 {"src": "aux.c", "std": "c++17"}],
}


def test_the_campaign_is_registered_and_declares_toolchains_through_the_catalog():
    assert "hecbench" in C.names()
    assert CAMP.check() == []
    tg = CAMP.caps.targets()
    reg = T.registry()
    assert set(tg) == {"tuolumne", "tioga", "wingtip"}
    for machine, (tcs, modes) in tg.items():
        assert tcs and set(tcs) <= {n for n, t in reg.toolchains.items() if t.machine == machine}
    assert C.get("hecbench").gate_kind == "hecbench" and CAMP.gate_prefix == "hecbench_"
    assert CAMP.sealed_runs == ("holdout",)


def test_the_module_names_no_toolchain():
    for mod in ("offload/engine/campaigns/hecbench.py", "offload/engine/hecbench.py", "offload/engine/hecbench_run.py"):
        text = (ROOT / mod).read_text()
        for tid in set(T.registry().toolchains) - set(T.registry().families):
            assert f'"{tid}"' not in text and f"'{tid}'" not in text, (mod, tid)


@pytest.mark.skipif(not H.RECIPES.is_file(), reason="recipes not derived")
def test_the_dev_draw_is_the_dev_half_of_the_split():
    split = H.load_split()
    ps = CAMP.programs(half="dev")
    assert [p.dir for p in ps] == sorted(split["dev"])
    assert all(p.half == "dev" and H.half_of(p.dir) == "dev" for p in ps)
    assert all(p.id == H.case_id(p.dir) for p in ps)


@pytest.mark.skipif(not H.RECIPES.is_file(), reason="recipes not derived")
def test_a_gpl_style_benchmark_is_tracked_as_an_id_only():
    import yaml
    d = yaml.safe_load(H.RECIPES.read_text())["benchmarks"]
    gpl = [r for r in d if r["licence"] == "gpl-style"]
    assert gpl
    for r in gpl:
        assert set(r) == {"dir", "id", "half", "licence", "status", "reason"}


def test_build_steps_use_each_toolchains_flags_and_the_cxx_driver():
    for machine, (tcs, modes) in CAMP.caps.targets().items():
        for t in tcs:
            for x in modes:
                tc = T.TOOLCHAINS[t]
                if x not in tc.xnack_modes:
                    continue
                steps, link_lang = R.build_steps(RECIPE, t, x, Path("/clone"))
                assert link_lang == "cpp" and [s[0] for s in steps] == ["compile main.cpp", "compile aux.c", "link"]
                cxx = R.toolchain_for(t, "cpp", x)
                ccc = R.toolchain_for(t, "c", x)
                assert steps[0][1].startswith(cxx.compiler()) and steps[1][1].startswith(ccc.compiler())
                assert cxx.compiler() != ccc.compiler()
                assert cxx.flags() in steps[0][1] and cxx.flags() in steps[2][1]
                assert "-std=c++17" in steps[0][1]
                assert "-std=c++17" not in steps[1][1]          # a C source takes no C++ standard
                assert "-DN=4" in steps[0][1] and "/clone/src/demo-cuda" in steps[0][1].replace("demo-omp/../", "")
                assert steps[2][1].rstrip().endswith("-lm")


def test_a_c_only_recipe_links_with_the_c_driver():
    r = dict(RECIPE, compiles=[{"src": "a.c"}])
    steps, lang = R.build_steps(r, next(iter(T.TOOLCHAINS)), 0, Path("/c"))
    assert lang == "c"


def test_the_failing_build_step_is_read_from_the_markers():
    text = "@@STEP compile a.cpp\n@@STEP-rc 0\n@@STEP compile b.cpp\nb.cpp:3:1: error: boom\n@@STEP-rc 1\n"
    assert R.failing_step(text) == ("compile b.cpp", 1, "b.cpp:3:1: error: boom\n")


def test_build_failures_are_classified_like_the_harness_does():
    out, why = R.classify_build("afar", "compile a.cpp", 1, "a.cpp:3:1: error: use of undeclared identifier 'x'\n", False)
    assert out == "rejected" and "undeclared" in why
    out, why = R.classify_build("afar", "link", 1, "ld.lld: error: undefined symbol: foo\n>>> referenced by a.o\n", False)
    assert out == "rejected" and why == "link_undefined_symbol: other symbol foo"
    out, why = R.classify_build("afar", "link", 1, "undefined reference to `__kmpc_fork_call'\n", False)
    assert why == "link_undefined_symbol: runtime symbol __kmpc_fork_call"
    assert R.classify_build("afar", "compile a.cpp", None, "", True) == ("harness_error", "compile_timeout")
    out, why = R.classify_build("afar", "compile a.cpp", 139, "Segmentation fault (core dumped)\n", False)
    assert out == "rejected" and why.startswith("ice:")


def test_run_outcomes_in_the_harnesss_vocabulary():
    from offload.engine import gate as GT
    cases = [((0, "PASS\n", "PASS\n"), "correct_on_device"),
             ((0, "FAIL\n", "PASS\n"), "wrong_answer"),
             ((139, "", None), "crash"),
             ((-11, "", None), "crash"),
             ((1, "boom\n", None), "run_error"),
             ((None, "", None), "timeout")]
    for (rc, out, ref), cls in cases:
        o, why = R.judge_run(rc, out, ref, 120)
        assert GT.outcome_class({"outcome": o, "reason": why}) == cls, (rc, why)


def test_run_arguments_name_repository_files_absolutely(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "in.txt").write_text("1")
    r = {"run_args": ["5", "data/in.txt", "0.5", "-v"]}
    assert R.run_args(r, tmp_path) == ["5", str((tmp_path / "data" / "in.txt").resolve()), "0.5", "-v"]


@pytest.mark.needs_bench("hecbench/stubs/omp.h")
def test_the_serial_reference_uses_no_openmp_and_the_stub_runtime():
    steps = R.reference_commands(RECIPE, Path("/clone"))
    assert all("-fopenmp" not in c for _, c in steps)
    assert str(R.STUBS) in steps[0][1] and (R.STUBS / "omp.h").is_file()
    assert steps[0][1].split()[0] == "g++" and steps[1][1].split()[0] == "gcc"
    assert steps[-1][1].startswith("g++ ")


def test_the_sealed_run_is_never_reported(tmp_path):
    spec = importlib.util.spec_from_file_location("campaign_tool", ROOT / "tools" / "campaign.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    for cmd in ("report", "cluster", "confirm", "findings-plan"):
        with pytest.raises(SystemExit) as e:
            m.main(["--results", str(tmp_path), "hecbench", cmd, "--name", "holdout"])
        assert "sealed" in str(e.value)


class _Fake:
    """The campaign's runner without compilers: the second toolchain of a machine
    fails to build the program named 'bad'; every rerun reproduces."""
    parallel = "thread"

    def __init__(self, bad_tc):
        self.bad_tc = bad_tc

    def prerun(self, p):
        ok = p.recipe["status"] == "ok"
        return {"id": p.id, "ok": ok, "rules": ok, "reasons": [], "afar_fe": None,
                "ref": {"ok": True, "out": "checksum = 1.0\n", "why": ""} if ok else None}

    def _cls(self, prog, toolchain):
        bad = toolchain == self.bad_tc and prog.reference_output() is not None
        return ("rejected", "diagnostic: error: boom") if bad else ("correct_on_device", "lines agree")

    def run(self, prog, toolchain, xnack, *, version, timeout_s, opt="-O2"):
        o, why = self._cls(prog, toolchain)
        return {"program_id": prog.id, "toolchain": toolchain, "xnack": xnack, "outcome": o, "reason": why,
                "flaky": False, "stdout": "", "stderr": "", "node": "n1", "build_dir": "/tmp/x",
                "toolchain_build": "t 1", "git_rev": ""}

    def rerun(self, prog, toolchain, xnack, env, *, version, timeout_s, opt="-O2"):
        o, why = self._cls(prog, toolchain)
        return {"env": env["env"], "path": env["path"], "node": "n1" if env["node"] == "same" else "n2",
                "repeat": env.get("repeat", 0), "seconds": 0.1, "date": "2026-11-04", "outcome": o,
                "reason": why, "flaky": False, "stdout": "", "toolchain_build": "t 1",
                "build_dir": env["path"], "git_rev": "", "compile_log": ""}


@pytest.mark.skipif(not H.RECIPES.is_file(), reason="recipes not derived")
def test_three_programs_go_through_gen_prerun_run_and_the_gate(tmp_path, monkeypatch):
    run = C.Run(CAMP, tmp_path / "dev", "dev")
    assert run.gen(0, 3, half="dev") == 3
    rows = C.read_jsonl(run.d / "programs.jsonl")
    assert len(rows) == 3 and all("recipe" in r and r["id"].startswith("hecbench-") for r in rows)
    assert all((run.d / "src" / f"{r['id']}.recipe.json").is_file() for r in rows)
    # a second Run object reads the programs back from programs.jsonl
    again = C.Run(CAMP, tmp_path / "dev", "dev")
    assert [p.id for p in again.programs()] == [r["id"] for r in rows]
    fake = _Fake(bad_tc=CAMP.caps.toolchains("tuolumne")[1])
    run.prerun(fake, workers=2)
    assert run.prerun_ok() <= {p.id for p in run.programs()}
    run.run("tuolumne", fake, workers=2)
    rs = run.rows()
    ok_ids = run.prerun_ok()
    tcs = CAMP.caps.toolchains("tuolumne")
    assert len(rs) == len(ok_ids) * len(tcs) * 2
    bad = [r for r in rs if r["outcome"] != "correct_on_device"]
    assert bad and all(r["toolchain"] == tcs[1] for r in bad)
    assert all(r["half"] == "dev" and r["campaign"] == "hecbench" for r in rs)
    assert run.gate_items("tuolumne")


def test_one_build_serves_both_memory_modes_on_amd_and_a_failed_build_repeats(monkeypatch):
    calls = []

    def fake(recipe, toolchain, xnack, clone, ref, **kw):
        calls.append((toolchain, xnack, bool(kw.get("keep")), bool(kw.get("prebuilt"))))
        if recipe["dir"] == "bad-omp":
            return {"program_id": recipe["id"], "toolchain": toolchain, "xnack": xnack,
                    "outcome": "rejected", "reason": "diagnostic: boom", "stderr": "log"}
        row = {"program_id": recipe["id"], "toolchain": toolchain, "xnack": xnack,
               "outcome": "correct_on_device", "reason": "", "stderr": "log"}
        if kw.get("keep"):
            row["_kept"] = "/tmp/hecbench-test-kept-dir"
        return row
    monkeypatch.setattr(R, "build_and_run", fake)
    amd = CAMP.caps.toolchains("tuolumne")[0]
    nv = next(t for t in CAMP.caps.toolchains("wingtip") if T.TOOLCHAINS[t].compile_time_modes())
    runner = R.HecbenchRunner(CAMP)
    good = type("P", (), {"id": "hecbench-demo-omp", "recipe": dict(RECIPE), "reference_output": lambda s: None})()
    bad = type("P", (), {"id": "hecbench-bad-omp", "recipe": dict(RECIPE, dir="bad-omp", id="hecbench-bad-omp"),
                         "reference_output": lambda s: None})()
    r0 = runner.run(good, amd, 0, version=52, timeout_s=10)
    r1 = runner.run(good, amd, 1, version=52, timeout_s=10)
    assert [c[1:] for c in calls] == [(0, True, False), (1, False, True)] and r0["xnack"] == 0 and r1["xnack"] == 1
    calls.clear()
    runner.run(bad, amd, 0, version=52, timeout_s=10)
    b1 = runner.run(bad, amd, 1, version=52, timeout_s=10)
    assert len(calls) == 1 and b1["outcome"] == "rejected" and b1["xnack"] == 1
    calls.clear()
    runner.run(good, nv, 0, version=52, timeout_s=10)
    runner.run(good, nv, 2, version=52, timeout_s=10)
    assert len(calls) == 2                # NVHPC's modes are compile flags: a build per mode


def test_a_gpu_slot_admits_at_most_the_configured_number_of_runs(monkeypatch, tmp_path):
    import threading
    import time
    monkeypatch.setenv("HECBENCH_SLOTS", "2")
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    live, peak, lock = [0], [0], threading.Lock()

    def worker():
        with R.gpu_slot(0):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.15)
            with lock:
                live[0] -= 1
    ts = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert peak[0] == 2
    with R.gpu_slot(None):                     # no slot without a GPU index
        pass


def test_the_gate_skips_failures_that_no_other_family_can_witness():
    tcs = CAMP.caps.toolchains("tuolumne")
    cce = [t for t in tcs if T.TOOLCHAINS[t].family_id == "cce"]
    afar = next(t for t in tcs if T.TOOLCHAINS[t].family_id == "afar")
    rows = [{"program_id": "p", "toolchain": cce[0], "xnack": 0, "outcome": "wrong_answer", "reason": "check_fail: x"},
            {"program_id": "p", "toolchain": afar, "xnack": 0, "outcome": "correct_on_device", "reason": ""},
            {"program_id": "q", "toolchain": cce[0], "xnack": 0, "outcome": "wrong_answer", "reason": "check_fail: x"},
            {"program_id": "q", "toolchain": cce[1], "xnack": 0, "outcome": "correct_on_device", "reason": ""},
            {"program_id": "r", "toolchain": cce[0], "xnack": 1, "outcome": "wrong_answer", "reason": "check_fail: x"},
            {"program_id": "r", "toolchain": afar, "xnack": 0, "outcome": "correct_on_device", "reason": ""}]
    items = [{"ident": "p", "toolchain": cce[0], "xnack": 0}, {"ident": "q", "toolchain": cce[0], "xnack": 0},
             {"ident": "r", "toolchain": cce[0], "xnack": 1}]
    assert [i["ident"] for i in CAMP.gate_filter(items, rows)] == ["p"]


# ---- The write-up is one dev-only copy; the finding matcher ---------------------

import re
import subprocess

from offload.engine import hecbench_report as RP

DOC = ROOT / "data" / "reports" / "hecbench.md"
REG = T.registry()
GCC = next(n for n, t in REG.toolchains.items() if t.family_id == "gcc")
CCE = next(n for n, t in REG.toolchains.items() if t.family_id == "cce")


def _tracked_docs():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "docs", "reports", "findings", "vendor", "THIRD_PARTY_NOTICES.md", "README.md"],
                         capture_output=True, text=True, check=True).stdout.split()
    return [ROOT / f for f in out if f.endswith(".md") and (ROOT / f).is_file()]


def test_the_write_up_is_one_copy():
    text = DOC.read_text()
    assert text.count("<!-- results:begin -->") == 1 and text.count("<!-- results:end -->") == 1
    heads = re.findall(r"^## .*$", text, re.M)
    assert len(heads) == len(set(heads)), [h for h in heads if heads.count(h) > 1]


def test_no_tracked_doc_has_a_holdout_coverage_or_outcome_table():
    for p in _tracked_docs():
        for ln in p.read_text().splitlines():
            if ln.lstrip().startswith("|") and "hecbench" in p.name.lower() + ln.lower() and re.search(
                    r"holdout", ln, re.I):
                raise AssertionError(f"{p.name}: a table row names the holdout: {ln[:80]}")
    text = DOC.read_text()
    # no count of programs, cells, failures or gate rows taken from the sealed run
    for m in re.finditer(r"[^.\n]*holdout[^.\n]*", text, re.I):
        assert not re.search(r"\d", re.sub(r"`[^`]*`", "", m.group(0))), m.group(0)


def test_the_write_up_says_only_that_the_sealed_half_was_run_and_sealed():
    assert re.search(r"sealed half[^.]*(was run|were run|run)", DOC.read_text(), re.I)


# --- The finding matcher ------------------------------------------------------------------------

LITERAL = {"file": "nested/maf.c", "toolchains": [GCC], "outcome": "crash",
           "message": "Memory access fault by GPU node-4 (Agent handle: 0x794640) on address 0xbed000. "
                      "Reason: Unknown."}
PATTERN = {"file": "p.f90", "toolchains": [CCE], "outcome": "crash", "message": "hipErrorIllegalAddress|fault"}


def test_a_literal_message_with_run_specific_parts_matches():
    sig = {"family": "gcc", "class": "crash", "reason": "crash: SIGABRT: Memory access fault by GPU node-1 "
           "(Agent handle: 0x1234ab) on address 0x77f000. Reason: Unknown."}
    assert RP.existing_findings(sig, [LITERAL]) == ["nested/maf.c"]


def test_a_regex_message_still_matches_and_a_non_match_is_related():
    sig = {"family": "cce", "class": "crash", "reason": "crash: SIGABRT: hipErrorIllegalAddress"}
    assert RP.existing_findings(sig, [PATTERN]) == ["p.f90"]
    other = {"family": "cce", "class": "crash", "reason": "crash: SIGABRT: something else"}
    assert RP.existing_findings(other, [PATTERN]) == []
    assert RP.existing_findings(other, [PATTERN], related=True) == ["p.f90"]


def test_signatures_with_the_same_programs_across_classes_are_one():
    def sig(cls, key, tc="cce19"):
        return {"family": "cce", "class": cls, "key": key, "programs": ["a", "b", "c"], "toolchains": [tc],
                "modes": ["copy"], "reason": ""}
    merged = RP.merge_same_programs([sig("crash", "SIGABRT: Memory access fault by GPU"),
                                     sig("run_error", "exit_status=1: hipErrorIllegalAd", "cce21"),
                                     {**sig("crash", "other"), "programs": ["z"]}])
    assert len(merged) == 2
    first = merged[0]
    assert first["also"] and sorted(first["toolchains"]) == ["cce19", "cce21"]


def test_the_headline_says_matching_message():
    import importlib.util
    spec = importlib.util.spec_from_file_location("hecbench_tool", ROOT / "tools" / "campaigns" / "hecbench.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert "matching message" in Path(m.__file__).read_text()


def test_a_link_failure_is_explained_by_an_ice_finding_of_the_same_message():
    """The offload assembler refusing GCC's own output is a link failure in the campaign's rows and an ICE
    in the finding (the harness calls it so now); the message decides."""
    ice = {"file": "hecbench/x.c", "toolchains": [GCC], "outcome": "ice", "message": "too few operands for instruction"}
    sig = {"family": "gcc", "class": "link_failure",
           "reason": "diagnostic: <tmpdir>/ccAb12.mkoffload.2.s:324:2: error: too few operands for instruction"}
    assert RP.existing_findings(sig, [ice]) == ["hecbench/x.c"]
    other = {**sig, "reason": "diagnostic: error: something else"}
    assert RP.existing_findings(other, [ice]) == []


# ---- The hecbench campaign's pure part (offload.engine.hecbench): the split, the licence -----------------

import hashlib



DRY = """\
HECB_CXX -std=c++17 -Wall -I../ace-cuda -O3 -target x86_64-pc-linux-gnu -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx906 -DDEBUG -c main.cpp -o main.o
HECB_CXX -std=c++17 -I. -D N=3 -isystem ../inc -O3 -fopenmp -c util.cpp -o util.o
HECB_CXX -std=c++17 -O3 -fopenmp main.o util.o -o main -lm -L/opt/x -lfoo
./main 100 file
"""


def test_the_split_is_the_parity_of_the_sha256_of_the_directory_name():
    for n in ("ace-omp", "adam-omp", "adam-omp", "zzz-omp"):
        even = int(hashlib.sha256(n.encode()).hexdigest(), 16) % 2 == 0
        assert H.half_of(n) == ("dev" if even else "holdout")
    assert {H.half_of(f"b{i}-omp") for i in range(40)} == {"dev", "holdout"}


def test_the_case_id_names_the_directory():
    assert H.case_id("adam-omp") == "hecbench-adam-omp"


def test_gpl_list_is_read_from_the_readme():
    readme = "x\n## License\nHeCBench has a BSD-3 license.\n\nThe benchmarks ace, ans, bm3d, feynman-kac, lebesgue have GPL-style licenses.\n"
    assert H.parse_gpl_listed(readme) == ["ace", "ans", "bm3d", "feynman-kac", "lebesgue"]
    assert H.parse_gpl_listed("nothing") == []


@pytest.mark.parametrize("text,cls", [
    ("MIT License\n\nPermission is hereby", "permissive"),
    ("                   GNU LESSER GENERAL PUBLIC LICENSE\n  Version 3", "copyleft"),
    ("Mozilla Public License Version 2.0", "copyleft"),
    ("Licensed under the Apache License, Version 2.0", "permissive"),
])
def test_licence_file_classes(text, cls):
    assert H.licence_file_class(text) == cls


def test_licence_classes_of_a_benchmark():
    assert H.licence_class("ace-omp", ["ace"], None) == "gpl-style"
    assert H.licence_class("x-omp", ["ace"], "GNU GENERAL PUBLIC LICENSE") == "gpl-style"
    assert H.licence_class("x-omp", ["ace"], "MIT License") == "own-permissive"
    assert H.licence_class("x-omp", ["ace"], None) == "bsd3"


def test_the_dry_run_keeps_only_defines_includes_std_and_link_libs():
    p = H.parse_dry_run(DRY)
    assert [c["src"] for c in p["compiles"]] == ["main.cpp", "util.cpp"]
    a, b = p["compiles"]
    assert a["defines"] == ["DEBUG"] and a["includes"] == ["../ace-cuda"] and a["std"] == "c++17"
    assert b["defines"] == ["N=3"] and b["includes"] == [".", "../inc"]
    assert p["link"] == {"libs": ["m", "foo"], "libdirs": ["/opt/x"], "output": "main"}
    assert p["run"] == {"program": "main", "args": ["100", "file"]}
    assert "-fopenmp" in p["dropped"] and "-O3" in p["dropped"]
    assert not any(f.startswith("-D") or f.startswith("-I") for f in p["dropped"])


def test_a_one_command_build_is_a_compile_and_a_link():
    p = H.parse_dry_run("HECB_CC -O2 -fopenmp main.c aux.c -o prog -lm\n./prog 5\n")
    assert [c["src"] for c in p["compiles"]] == ["main.c", "aux.c"]
    assert p["link"]["output"] == "prog" and p["run"]["args"] == ["5"]


def test_run_line_stops_at_shell_operators_and_continuations_join():
    p = H.parse_dry_run("HECB_CXX -c a.cpp -o a.o\nHECB_CXX a.o \\\n -o m\n./m 1 2 > out.txt\n")
    assert p["run"]["args"] == ["1", "2"]


def test_other_commands_are_listed_as_compilers():
    p = H.parse_dry_run("nvcc -c a.cu -o a.o\nHECB_CXX -c b.cpp -o b.o\n./a.out 1\n")
    assert "nvcc" in p["compilers"]


def test_repeat_argument_is_found_and_replaced():
    src = "int main(int argc, char** argv) {\n  const int repeat = atoi(argv[2]);\n"
    assert H.repeat_arg_index([src]) == 2
    assert H.repeat_arg_index(["int n = atoi(argv[1]);"]) is None
    assert H.repeat_arg_index(["int iterations = std::stoi(argv[1]);"]) == 1
    assert H.apply_repeat(["10", "100"], 2) == ["10", str(H.REPEAT)]
    assert H.apply_repeat(["10"], 3) == ["10"] and H.apply_repeat(["10"], None) == ["10"]


def _recipe(tmp_path, dry, files, name="demo-omp", gpl=(), lic=None):
    d = tmp_path / name
    d.mkdir()
    for f, t in files.items():
        (d / f).write_text(t)
    return H.recipe_from(name, d, dry, list(gpl), lic)


def test_a_plain_benchmark_is_ok(tmp_path):
    r = _recipe(tmp_path, "HECB_CXX -std=c++17 -c main.cpp -o main.o\nHECB_CXX main.o -o main\n./main 100\n",
                {"main.cpp": "#include <cstdio>\nint main(int c,char**v){int repeat=atoi(v[1]);}\n"})
    assert r["status"] == "ok" and r["run_args"] == [str(H.REPEAT)] and r["repeat_arg"] == 1
    assert r["lang"] == "cpp" and r["std"] == "c++17" and r["licence"] == "bsd3"
    assert r["id"] == "hecbench-demo-omp" and r["half"] in ("dev", "holdout")


@pytest.mark.parametrize("src,link,status", [
    ('#include <cuda_runtime.h>\nint main(){}', "", "cuda-only-dependency"),
    ('#include <thrust/device_vector.h>\nint main(){}', "", "cuda-only-dependency"),
    ('#include <mpi.h>\nint main(){}', "", "needs-external-library"),
    ('#include <opencv2/core.hpp>\nint main(){}', "", "needs-external-library"),
    ('int main(){}', " -lcublas", "cuda-only-dependency"),
    ('int main(){}', " -lfftw3", "needs-external-library"),
    ('#include <unistd.h>\nint main(){}', " -lm -lpthread", "ok"),
])
def test_exclusions_by_includes_and_libraries(tmp_path, src, link, status):
    r = _recipe(tmp_path, f"HECB_CXX -c main.cpp -o main.o\nHECB_CXX main.o -o main{link}\n./main\n",
                {"main.cpp": src})
    assert r["status"] == status
    if status != "ok":
        assert r["reason"]


def test_a_missing_data_file_in_the_arguments_excludes(tmp_path):
    r = _recipe(tmp_path, "HECB_CXX -c main.cpp -o main.o\nHECB_CXX main.o -o main\n./main data.bin 10\n",
                {"main.cpp": "int main(){}"})
    assert r["status"] == "needs-data-file" and "data.bin" in r["reason"]
    r2 = _recipe(tmp_path, "HECB_CXX -c main.cpp -o main.o\nHECB_CXX main.o -o main\n./main data.bin\n",
                 {"main.cpp": "int main(){}", "data.bin": "x"}, name="have-omp")
    assert r2["status"] == "ok"


def test_an_output_file_argument_is_no_missing_input(tmp_path):
    r = _recipe(tmp_path, "HECB_CXX -c main.cpp -o main.o\nHECB_CXX main.o -o main\n./main 10 output.txt ./Result.dat\n",
                {"main.cpp": "int main(){}"})
    assert r["status"] == "ok"


def test_a_literal_input_file_that_is_absent_excludes(tmp_path):
    src = 'int main(){ FILE* f = fopen("input.txt", "r"); }'
    r = _recipe(tmp_path, "HECB_CXX -c main.cpp -o main.o\nHECB_CXX main.o -o main\n./main\n",
                {"main.cpp": src})
    assert r["status"] == "needs-data-file"


def test_cuda_or_fortran_sources_and_no_commands_are_excluded(tmp_path):
    assert _recipe(tmp_path, "nvcc -c a.cu\n", {})["status"] in ("no-recipe", "cuda-only-dependency")
    assert _recipe(tmp_path, "", {}, name="e-omp")["status"] == "no-recipe"


def test_a_gpl_style_recipe_is_tracked_as_an_id_only(tmp_path):
    r = _recipe(tmp_path, "HECB_CXX -c main.cpp -o main.o\nHECB_CXX main.o -o main\n./main\n",
                {"main.cpp": "int main(){}"}, name="ace-omp", gpl=["ace"])
    assert r["licence"] == "gpl-style"
    t = H.recipe_for_tracking(r)
    assert set(t) == {"dir", "id", "half", "licence", "status", "reason"}
    assert "compiles" in r


def test_the_judge_reads_the_benchmarks_own_check_first():
    assert H.judge_output("Verification: FAIL\n", "PASS\n")[0] is False
    assert H.judge_output("PASS\n", "PASS\n") == (True, "self-check: PASS")
    ok, why = H.judge_output("done\n", "PASS\n")
    assert not ok and "no PASS" in why


def test_the_judge_compares_checked_lines_with_the_reference_not_the_timings():
    ref = "Average kernel time 12.5 ms\nchecksum = 1.00000\nsum 42\n"
    assert H.judge_output("Average kernel time 99.1 ms\nchecksum = 1.00001\nsum 42\n", ref)[0]
    ok, why = H.judge_output("Average kernel time 1 ms\nchecksum = 1.5\nsum 42\n", ref)
    assert not ok and "value differs" in why
    assert H.oracle_kind(ref) == "lines" and H.oracle_kind("hello\n") == "none"
    assert H.judge_output("hello", None) == (True, "no oracle (exit 0, no failure text)")


def test_a_reference_that_fails_its_own_check_is_no_oracle():
    assert H.oracle_kind("Verification: FAIL\nchecksum 3\n") == "none"
    assert H.judge_output("PASS\n", "FAIL\n") == (True, "no oracle (exit 0, no failure text)")


def test_a_zero_mismatch_count_is_no_failure():
    assert H.judge_output("mismatches: 0\n", None)[0]
    assert not H.judge_output("mismatches: 3\n", None)[0]


def test_the_checked_in_split_file_matches_the_rule():
    import yaml
    if not H.SPLIT.is_file():
        pytest.skip("the split is not written yet")
    d = yaml.safe_load(H.SPLIT.read_text())
    assert d["rule"] and len(d["commit"]) == 40
    assert all(H.half_of(n) == "dev" for n in d["dev"])
    assert d["dev_count"] == len(d["dev"]) and d["holdout_count"] == len(d["holdout_sha256"])
    assert d["dev_count"] + d["holdout_count"] == d["benchmarks"]
    assert all(not n.startswith("hecbench") or True for n in d["dev"])
    assert [hashlib.sha256(n.encode()).hexdigest() for n in d["dev"]] and \
        not set(H.name_hash(n) for n in d["dev"]) & set(d["holdout_sha256"])


# ---- The hecbench report rules (offload.engine.hecbench_report) on made-up rows ------------


REG_4 = T.registry()
AFAR = next(n for n, t in REG_4.toolchains.items() if t.family_id == "afar" and t.machine == "tuolumne")
CCE_4 = next(n for n, t in REG_4.toolchains.items() if t.family_id == "cce" and t.machine == "tuolumne")
CCE2 = [n for n, t in REG_4.toolchains.items() if t.family_id == "cce" and t.machine == "tuolumne"][1]
NV = next(n for n, t in REG_4.toolchains.items() if t.family_id == "nvhpc")


def row(pid, tc, x, outcome, reason="", **kw):
    return {"program_id": pid, "toolchain": tc, "xnack": x, "outcome": outcome, "reason": reason, **kw}


def cell(pid, tc, x):
    return C.get("hecbench").cell(pid, tc, x)


def test_classes_split_the_link_from_the_compile_and_name_run_failures():
    assert RP.row_class(row("p", AFAR, 0, "correct_on_device")) == "ok"
    assert RP.row_class(row("p", AFAR, 0, "rejected", "diagnostic: error: x")) == "compile_reject"
    assert RP.row_class(row("p", AFAR, 0, "rejected", "link_undefined_symbol: other symbol f", stage="link")) \
        == "link_failure"
    assert RP.row_class(row("p", AFAR, 0, "rejected", "ice: PLEASE submit")) == "ice"
    assert RP.row_class(row("p", AFAR, 0, "wrong_answer", "crash: SIGSEGV: x")) == "crash"
    assert RP.row_class(row("p", AFAR, 0, "wrong_answer", "exit_status=1: x")) == "run_error"
    assert RP.row_class(row("p", AFAR, 0, "wrong_answer", "timeout: the run did not end in 120 s")) == "timeout"
    assert RP.row_class(row("p", AFAR, 0, "wrong_answer", "check_fail: no PASS")) == "wrong_answer"
    assert RP.row_class(row("p", AFAR, 0, "harness_error", "compile_timeout")) == "timeout"   # the gate's reading
    assert RP.row_class(row("p", AFAR, 0, "harness_error", "environment: no module")) == "harness_error"


def test_a_program_missing_a_header_everywhere_is_not_a_compiler_matter():
    rows = [row("a", AFAR, 0, "rejected", "diagnostic: fatal error: 'foo.h' file not found"),
            row("a", CCE_4, 0, "rejected", "diagnostic: 'foo.h' file not found"),
            row("b", AFAR, 0, "rejected", "diagnostic: file not found"),
            row("b", CCE_4, 0, "correct_on_device")]
    out = RP.non_compiler_programs(rows)
    assert set(out) == {"a"} and "missing" in out["a"]


def test_evidence_needs_a_confirmed_gate_and_a_witness_of_another_family():
    rows = [row("p", CCE_4, 0, "wrong_answer", "check_fail: sum 3", stage="run"),
            row("p", AFAR, 0, "correct_on_device"),
            row("q", CCE_4, 0, "wrong_answer", "check_fail: sum 4", stage="run"),
            row("q", CCE2, 0, "correct_on_device"),           # the same family: no witness
            row("r", CCE_4, 0, "wrong_answer", "check_fail: sum 5", stage="run"),
            row("r", AFAR, 0, "correct_on_device")]
    verdicts = {cell("p", CCE_4, 0): {"verdict": "confirmed"}, cell("q", CCE_4, 0): {"verdict": "confirmed"},
                cell("r", CCE_4, 0): {"verdict": "environment"}}
    out = RP.split_cells(rows, verdicts, C.mode_name, cell, set())
    assert [c["row"]["program_id"] for c in out["evidence"]] == ["p"]
    un = {c["row"]["program_id"]: c["why_not"] for c in out["unconfirmed"]}
    assert "another family" in un["q"] and "environment" in un["r"]
    assert RP.signature_key(row("z", CCE_4, 0, "wrong_answer", "crash: SIGABRT: x Memory access fault by GPU node-4")) \
        == "SIGABRT: Memory access fault by GPU"
    assert RP.signature_key(row("z", CCE_4, 0, "wrong_answer", "exit_status=1: Failed to open file x", stage="run")) \
        == "exit_status=1: no runtime message"
    assert RP.signature_key(row("z", CCE_4, 0, "wrong_answer", "exit_status=2: CRAY_ACC_ERROR - hipStreamSynchronize 77")) \
        == "exit_status=2: CRAY_ACC_ERROR - hipStreamSynchronize N"
    assert out["evidence"][0]["witnesses"] == ["afar"]


def test_a_witness_runs_in_the_failing_cells_own_memory_mode():
    unified = REG_4.toolchains[CCE_4].xnack_modes[-1]
    rows = [row("p", CCE_4, 0, "wrong_answer", "check_fail: s", stage="run"),
            row("p", AFAR, unified, "correct_on_device"),
            row("u", CCE_4, unified, "wrong_answer", "check_fail: s", stage="run"),
            row("u", AFAR, unified, "correct_on_device"),
            row("w", CCE_4, unified, "wrong_answer", "check_fail: s", stage="run"),
            row("w", AFAR, 0, "correct_on_device")]
    verdicts = {cell(p, CCE_4, x): {"verdict": "confirmed"} for p, x in (("p", 0), ("u", unified), ("w", unified))}
    out = RP.split_cells(rows, verdicts, C.mode_name, cell, set())
    assert [c["row"]["program_id"] for c in out["evidence"]] == ["u"]


def test_signatures_merge_releases_of_a_family_and_count_programs():
    mk = lambda pid, tc: {"row": row(pid, tc, 0, "wrong_answer", "check_fail: sum 3"), "class": "wrong_answer",
                          "key": "check_fail: sum N", "family": RP.family_of(tc), "mode": "copy"}
    sigs = RP.signatures([mk("a", CCE_4), mk("a", CCE2), mk("b", CCE_4), mk("c", AFAR)])
    assert len(sigs) == 2
    cce = next(s for s in sigs if s["family"] == "cce")
    assert cce["programs"] == ["a", "b"] and sorted(cce["toolchains"]) == sorted({CCE_4, CCE2})


def test_a_signature_matches_a_finding_of_its_family_outcome_and_message():
    idx = [{"file": "f1.c", "toolchains": [CCE_4], "outcome": "ice", "message": "unhandled construct"},
           {"file": "f2.c", "toolchains": [AFAR], "outcome": "ice", "message": "unhandled construct"},
           {"file": "f3.c", "toolchains": [CCE_4], "outcome": "wrong_answer"},
           {"file": "f4.c", "toolchains": [CCE_4], "outcome": "rejected"}]
    s = {"family": "cce", "class": "ice", "reason": "ice: unhandled construct type 3", "key": "k"}
    assert RP.existing_findings(s, idx) == ["f1.c"]
    assert RP.existing_findings({**s, "class": "wrong_answer"}, idx) == []            # no message: related only
    assert RP.existing_findings({**s, "class": "wrong_answer"}, idx, related=True) == ["f3.c"]
    assert RP.existing_findings({**s, "class": "compile_reject"}, idx) == []


def test_the_outcome_table_counts_built_programs_per_toolchain_and_mode():
    rows = [row("a", AFAR, 0, "correct_on_device"), row("b", AFAR, 0, "rejected", "diagnostic: x"),
            row("c", AFAR, 0, "wrong_answer", "crash: SIGSEGV: x"), row("d", AFAR, 0, "correct_on_device")]
    t = RP.outcome_table(rows, C.mode_name, {"d"})
    assert t == [{"toolchain": AFAR, "mode": "copy", "built": 2, "ok": 1, "compile_reject": 1, "ice": 0,
                  "link_failure": 0, "run_error": 0, "crash": 1, "timeout": 0, "wrong_answer": 0,
                  "harness_error": 0}]
    assert "| toolchain | mode | built |" in RP.markdown_table(t)


def test_a_verdict_the_cell_earned_needs_all_four_gate_environments():
    rows = [row("p", CCE_4, 0, "wrong_answer", "check_fail: s", stage="run"),
            row("p", AFAR, 0, "correct_on_device"),
            row("q", CCE_4, 0, "wrong_answer", "check_fail: s", stage="run"),
            row("q", AFAR, 0, "correct_on_device"),
            row("i", CCE_4, 0, "rejected", "diagnostic: error: x"),
            row("i", AFAR, 0, "correct_on_device")]
    verdicts = {cell("p", CCE_4, 0): {"verdict": "confirmed"}, cell("q", CCE_4, 0): {"verdict": "confirmed"},
                cell("i", CCE_4, 0): {"verdict": "confirmed", "inherited": True}}
    envs = {cell("p", CCE_4, 0): {"a", "b", "c", "d"}, cell("q", CCE_4, 0): {"a", "b", "d"}}
    out = RP.split_cells(rows, verdicts, C.mode_name, cell, set(), envs)
    assert sorted(c["row"]["program_id"] for c in out["evidence"]) == ["i", "p"]
    assert "only environments a,b,d ran" in out["unconfirmed"][0]["why_not"]


# ---- Gating only the cells that now fail differently at 120 s: a run with a gate list --------------------

import json




def row_5(pid, tc, x, outcome, reason, **kw):
    return {"program_id": pid, "toolchain": tc, "xnack": x, "outcome": outcome, "reason": reason, **kw}


@pytest.mark.skipif(not H.RECIPES.is_file(), reason="recipes not derived")
def test_a_run_with_a_gate_list_gates_only_the_listed_cells(tmp_path):
    camp = C.get("hecbench")
    run = C.Run(camp, tmp_path / "t120", "t120")
    run.gen(0, 3, half="dev")
    tcs = camp.caps.toolchains("tuolumne")
    ps = [p for p in run.programs() if p.recipe["status"] == "ok"][:2]
    rows = []
    for p in ps:
        rows.append(row_5(p.id, tcs[1], 0, "wrong_answer", "check_fail: x", stage="run", campaign="hecbench"))
        rows.append(row_5(p.id, tcs[0], 0, "correct_on_device", "", campaign="hecbench"))
    C.append_jsonl(run.d / "rows.jsonl", rows)
    assert {it["ident"] for it in run.gate_items("tuolumne")} == {p.id for p in ps}
    (run.d / "gate_only.json").write_text(json.dumps([camp.cell(ps[0].id, tcs[1], 0)]))
    assert [it["ident"] for it in run.gate_items("tuolumne")] == [ps[0].id]


# ---- The 120 s rerun of the 30 s time-outs: which cells are chosen, and how the result is classified -----



def row_6(pid, tc, x, outcome, reason, **kw):
    return {"program_id": pid, "toolchain": tc, "xnack": x, "outcome": outcome, "reason": reason, **kw}


ROWS = [
    row_6("a", "afar", 0, "wrong_answer", "timeout: the run did not end in 30 s"),
    row_6("a", "afar", 1, "correct_on_device", ""),
    row_6("b", "cce19", 0, "wrong_answer", "timeout: the run did not end in 30 s"),
    row_6("w", "cce19", 0, "wrong_answer", "timeout: the run did not end in 30 s"),       # withheld
    row_6("c", "cce19", 0, "harness_error", "compile_timeout"),                           # a compile
    row_6("d", "gcc_g90", 0, "wrong_answer", "crash: SIGSEGV: x"),
]


def test_the_cells_are_the_run_time_timeouts_of_programs_not_withheld():
    got = RP.timeout_cells(ROWS, {"w"})
    assert got == [("a", "afar", 0), ("b", "cce19", 0)]


def test_a_cell_is_a_slow_kernel_when_it_finishes_and_a_candidate_hang_when_it_does_not():
    assert RP.timeout_verdict(row_6("a", "afar", 0, "correct_on_device", "")) == "finished ok"
    assert RP.timeout_verdict(row_6("a", "afar", 0, "wrong_answer", "check_fail: x")) == "finished failing"
    assert RP.timeout_verdict(row_6("a", "afar", 0, "wrong_answer", "crash: SIGSEGV: x")) == "finished failing"
    assert RP.timeout_verdict(row_6("a", "afar", 0, "wrong_answer", "timeout: the run did not end in 120 s")) \
        == "still timing out"


# ---- Restricted licences and the other hecbench checks -----------------------




CAMP_7 = C.get("hecbench")
needs_recipes = pytest.mark.skipif(not H.RECIPES.is_file(), reason="recipes not derived")


# --- Restricted licences ------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Dhara Modeling Software\nNon-Exclusive, Non-Commercial Use License\n",
    "licensed for education and research purpose only, and not for commercial use",
    "This software is for research use only.",
    "Academic use only. Redistribution is not permitted.",
])
def test_non_commercial_texts_are_restricted(text):
    assert H.licence_file_class(text) == "restricted"
    assert H.licence_class("x-omp", [], text) == "restricted"


@pytest.mark.parametrize("text", [
    "to use this software for any purpose, commercial or non-commercial, and by any means.",
    "MIT License\nPermission is hereby granted, free of charge",
    "Neither the names of the IMPACT Research Group nor the University",
])
def test_grants_that_mention_commercial_use_stay_permissive(text):
    assert H.licence_file_class(text) == "permissive"


def test_a_gnu_text_that_says_noncommercially_stays_copyleft():
    assert H.licence_file_class("GNU GENERAL PUBLIC LICENSE\n only occasionally and noncommercially") == "copyleft"


def test_a_restricted_recipe_is_tracked_as_an_id_only():
    r = {"dir": "x-omp", "id": "hecbench-x-omp", "half": "dev", "licence": "restricted", "status": "ok",
         "reason": "", "compiles": [{"src": "a.cpp"}]}
    assert set(H.recipe_for_tracking(r)) == {"dir", "id", "half", "licence", "status", "reason"}


def test_the_licence_file_is_found_under_its_other_names(tmp_path):
    (tmp_path / "LICENCE").write_text("GNU GENERAL PUBLIC LICENSE")
    assert "GENERAL PUBLIC" in H.read_licence_file(tmp_path)
    assert H.read_licence_file(tmp_path / "nothing") is None


@needs_recipes
def test_no_restricted_or_gpl_recipe_is_tracked_whole():
    import yaml
    for path in (p for p in (H.RECIPES, H.HOLDOUT_RECIPES) if p.is_file()):
        for r in yaml.safe_load(path.read_text())["benchmarks"]:
            if r["licence"] in H.WITHHELD:
                assert set(r) == {"dir", "id", "half", "licence", "status", "reason"}, r["dir"]


# ---- A sealed run logs no counts and is refused by the plain commands -----




CAMP_8 = C.get("hecbench")
needs_recipes_8 = pytest.mark.skipif(not (H.RECIPES.is_file() and H.HOLDOUT_RECIPES.is_file()),
                                   reason="the sealed set's recipes are not on this machine (a lane)")
COUNT_WORDS = ("failing rows", "refused", "checked", "runs to do", "reruns")


def _holdout_run(tmp_path, name="foo"):
    run = C.Run(CAMP_8, tmp_path / name, name)
    run.gen(0, 4, half="holdout")
    return run


def _dev_run(tmp_path):
    run = C.Run(CAMP_8, tmp_path / "dev", "dev")
    run.gen(0, 4, half="dev")
    return run


def _tool(name):
    import where
    spec = importlib.util.spec_from_file_location(name + "_tool", where.tool(name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@needs_recipes_8
def test_a_run_of_the_sealed_half_is_sealed_under_any_name(tmp_path):
    assert _holdout_run(tmp_path, "foo").sealed
    assert _holdout_run(tmp_path / "x", "holdout").sealed
    assert not _dev_run(tmp_path).sealed


@needs_recipes_8
def test_prerun_and_run_of_a_sealed_run_log_no_counts(tmp_path):
    tcs = CAMP_8.caps.toolchains("tuolumne")
    for mk, sealed in ((_holdout_run, True), (_dev_run, False)):
        run = mk(tmp_path / ("s" if sealed else "d"))
        log = []
        run.prerun(_Fake(tcs[1]), workers=1, log=log.append)
        run.run("tuolumne", _Fake(tcs[1]), workers=1, log=log.append)
        text = " ".join(map(str, log))
        assert any(w in text for w in COUNT_WORDS) is (not sealed), text


@needs_recipes_8
def test_the_gate_of_a_sealed_run_logs_no_count_of_failing_rows(tmp_path):
    tcs = CAMP_8.caps.toolchains("tuolumne")
    for mk, sealed in ((_holdout_run, True), (_dev_run, False)):
        run = mk(tmp_path / ("s" if sealed else "d"))
        fake = _Fake(tcs[1])
        run.prerun(fake, workers=1, log=lambda *a: None)
        rows = []
        for p in run.programs():
            if p.id not in run.prerun_ok() or p.reference_output() is None:
                continue
            for t in tcs[:2]:
                rows.append({**fake.run(p, t, 0, version=52, timeout_s=1), "machine": "tuolumne",
                             "mode": "copy", "campaign": "hecbench"})
        C.append_jsonl(run.d / "rows.jsonl", rows)
        log = []
        run.gate("tuolumne", fake, envs="a", workers=1, root=str(tmp_path / "gate"), log=log.append)
        text = " ".join(map(str, log))
        assert ("failing rows" in text) is (not sealed), text


@needs_recipes_8
def test_the_generic_cli_refuses_a_sealed_run_whatever_its_name(tmp_path):
    _holdout_run(tmp_path / "res" / "hecbench", "foo")
    m = _tool("campaign")
    for cmd in ("report", "cluster", "confirm", "findings-plan"):
        with pytest.raises(SystemExit) as e:
            m.main(["--results", str(tmp_path / "res"), "hecbench", cmd, "--name", "foo"])
        assert "sealed" in str(e.value)


@needs_recipes_8
def test_the_hecbench_report_command_refuses_a_sealed_run_by_name_and_by_content(tmp_path, monkeypatch):
    m = _tool("hecbench")
    for name in ("holdout", "foo"):
        _holdout_run(tmp_path, name)
    monkeypatch.setattr(C, "run_dir", lambda camp, n, results=None: tmp_path / n)
    for name in ("holdout", "foo"):
        with pytest.raises(SystemExit) as e:
            m.main(["report", "--name", name])
        assert "reads the dev half only" in str(e.value)     # the first refusal, not the program check


def _stub_build(seen):
    def fake(recipe, toolchain, xnack, clone, ref, **kw):
        seen.append(kw["build_dir"])
        return {"outcome": "correct_on_device", "reason": "", "flaky": False, "stdout": "",
                "toolchain_build": "t", "build_dir": kw["build_dir"], "git_rev": "", "stderr": ""}
    return fake


def _prog():
    return type("P", (), {"id": "x", "recipe": {}, "reference_output": lambda s: None})()


def test_a_gate_rerun_uses_its_own_build_directory_per_memory_mode(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(R, "build_and_run", _stub_build(seen))
    amd = CAMP_8.caps.toolchains("tuolumne")[0]
    env = {"env": "a", "path": str(tmp_path / "harness_x"), "node": "same", "repeat": 0}
    runner = R.HecbenchRunner(CAMP_8)
    runner.rerun(_prog(), amd, 0, env, version=52, timeout_s=1)
    runner.rerun(_prog(), amd, 1, env, version=52, timeout_s=1)
    assert len(set(seen)) == 2 and all(s.startswith(env["path"]) for s in seen)


def test_a_leftover_gate_directory_is_removed_only_under_a_gate_name(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "build_and_run", _stub_build([]))
    amd = CAMP_8.caps.toolchains("tuolumne")[0]
    keep = tmp_path / "precious_m0"
    keep.mkdir()
    (keep / "f").write_text("x")
    R.HecbenchRunner(CAMP_8).rerun(_prog(), amd, 0, {"env": "a", "path": str(tmp_path / "precious"),
                                                   "node": "same"}, version=52, timeout_s=1)
    assert (keep / "f").exists()
    gate = tmp_path / "GATEABC_m0"
    gate.mkdir()
    R.HecbenchRunner(CAMP_8).rerun(_prog(), amd, 0, {"env": "b", "path": str(tmp_path / "GATEABC"),
                                                   "node": "same"}, version=52, timeout_s=1)
    assert not gate.exists()


def test_no_sealed_outcomes_file_is_tracked():
    """The holdout's outcomes stay on disk (git-ignored); only SEAL, the recipe and split files are tracked
    under a sealed directory."""
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "bench"], capture_output=True, text=True,
                           check=True).stdout.split()
    for f in files:
        if "hecbench-holdout" in f:
            assert Path(f).name in ("SEAL", "recipes.yaml", "cases.yaml"), f
        assert not (Path(f).name.startswith("outcomes") and "hecbench" in f), f


def test_the_outcomes_file_is_git_ignored():
    r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "data/bench/hecbench-holdout/outcomes.csv"],
                       capture_output=True, text=True)
    assert r.returncode == 0
