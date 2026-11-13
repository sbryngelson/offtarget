"""Tests of the reproduction gate (offload.engine.gate, gate_run) and of offload.engine.run_matrix with the fake compiler."""


# ---- The reproduction gate (offload.engine.gate, offload.engine.gate_run) --------------------------------

import where
import sys
from pathlib import Path

import pytest

from offload.engine import gate as G
from offload.engine import gate_run as GR
from offload.engine import harness
from offload.engine.gen import Program
from offload.engine.toolchains import Toolchain

FAKES = Path(__file__).parent.parent / "data" / "fakes"
MESSAGES = Path(__file__).parent.parent / "data" / "messages"
ICE = where.message("cce_ice_ordered")


def prog(pid="omp52-gate-probe") -> Program:
    return Program(id=pid, lang="fortran", source="! fake\n",
                   atoms=frozenset({"omp.directive.target"}),
                   primary_atom="omp.directive.target", legal=True,
                   violates=None, observable=True)


def script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)
    return path


def marker_compiler(tmp: Path, marker: str) -> Toolchain:
    """Fails with CCE's ICE message when an argument (the source path)
    contains `marker`, else 'compiles' a passing program."""
    fc = script(tmp / "fc.sh", f"""out=""
for a in "$@"; do [ "$prev" = "-o" ] && out=$a; prev=$a; done
case "$*" in
  *{marker}*) sed '1,/^==== verbatim output below ====$/d' {ICE} >&2
     exit 1 ;;
esac
cp {FAKES}/exe_device_pass.sh "$out"; chmod +x "$out"
""")
    return Toolchain("cce19", "", str(fc))


def counter_compiler(tmp: Path) -> Toolchain:
    """Compiles a program that fails on odd runs and passes on even
    ones (a counter file outside the build directory)."""
    count = tmp / "count"
    count.write_text("0")
    exe = script(tmp / "exe.sh", f"""n=$(cat {count}); n=$((n+1))
echo $n > {count}
if [ $((n % 2)) -eq 1 ]; then echo "RESULT ran_on_host=0 check=fail"
else echo "RESULT ran_on_host=0 check=pass"; fi
""")
    fc = script(tmp / "fc.sh", f"""out=""
for a in "$@"; do [ "$prev" = "-o" ] && out=$a; prev=$a; done
cp {exe} "$out"; chmod +x "$out"
""")
    return Toolchain("afar", "", str(fc))


def always_ice(tmp: Path) -> Toolchain:
    return marker_compiler(tmp, "/")      # every path has a "/"


def original(tc, tmp: Path, build_dir: Path | None = None) -> dict:
    import dataclasses
    res = harness.run_program(prog(), tc, 1, timeout_s=20, repeats=1,
                              build_dir=build_dir)
    d = dataclasses.asdict(res)
    d.update({"kind": "catalog", "ident": res.program_id, "campaign": "t",
              "mode": "unified"})
    return d


def run_all(row, tc, root: Path) -> list[dict]:
    """The four environments here; (c) stands for another node (its
    node renamed: a (c) on (a)'s node is no evidence)."""
    out = [GR.rerun_program(prog(), tc, 1, env, timeout_s=20)
           for env in G.environments(row, str(root))]
    for r in out:
        if r["env"] == "c":
            r["node"] = "another-node"
    return out


def test_environments_are_four_with_a_different_character_mix(tmp_path):
    row = {"kind": "catalog", "ident": "omp52-x", "toolchain": "cce19",
           "mode": "unified", "campaign": "catalog"}
    envs = G.environments(row, str(tmp_path))
    assert [e["env"] for e in envs] == ["a", "b", "c", "d"]
    for e in envs:
        assert set(e) >= {"path", "node", "environment", "repeat"}
    a, b, c, d = envs
    assert a["path"] == c["path"] == d["path"] != b["path"]
    assert (a["node"], c["node"], d["node"]) == ("same", "other", "same")
    assert (a["repeat"], d["repeat"]) == (0, 1)
    name_a, name_b = Path(a["path"]).name, Path(b["path"]).name
    assert name_a.startswith("harness_") and "-" not in name_a
    assert name_b.isalpha() and name_b.isupper()
    assert len(name_a) != len(name_b)
    # a recorded build directory is the original environment itself
    row["build_dir"] = "/tmp/x-1y/st_k"
    assert G.environments(row, str(tmp_path))[0]["path"] == "/tmp/x-1y/st_k"


def test_verdict_confirmed(tmp_path):
    tc = always_ice(tmp_path)
    row = original(tc, tmp_path)
    assert row["outcome"] == "rejected" and row["reason"].startswith("ice:")
    reruns = run_all(row, tc, tmp_path / "gate")
    assert G.verdict(row, reruns) == "confirmed"
    j = G.judge(row, reruns)
    assert j["legality_review"] is False and j["missing"] == []


def test_verdict_environment_dir_name(tmp_path):
    tc = marker_compiler(tmp_path, "mk1q")
    root = tmp_path / "gate"
    row = original(tc, tmp_path, build_dir=root / "harness_mk1q")
    assert row["outcome"] == "rejected"
    assert row["build_dir"] == str(root / "harness_mk1q")
    reruns = run_all(row, tc, root)
    got = {r["env"]: r["outcome"] for r in reruns}
    assert got == {"a": "rejected", "b": "correct_on_device",
                   "c": "rejected", "d": "rejected"}
    assert G.verdict(row, reruns) == "environment"
    j = G.judge(row, reruns)
    assert j["legality_review"] is True and j["needs_condition"]
    assert "build directory" in j["condition"]
    assert "has digit" in j["condition"]       # only the failing path


def test_verdict_nondeterministic(tmp_path):
    tc = counter_compiler(tmp_path)
    row = original(tc, tmp_path)               # run 1: fails
    assert row["outcome"] == "wrong_answer"
    reruns = run_all(row, tc, tmp_path / "gate")   # a pass, b fail, ...
    assert [r["outcome"] for r in reruns] == [
        "correct_on_device", "wrong_answer", "correct_on_device",
        "wrong_answer"]
    assert G.verdict(row, reruns) == "nondeterministic"
    assert G.judge(row, reruns)["legality_review"] is True


def test_nondeterministic_is_checked_before_environment():
    """(a) and (d) disagree and (b) differs too: the same
    environment disagrees with itself, so not 'environment'."""
    row = {"outcome": "wrong_answer", "reason": "check_fail: x"}
    reruns = [{"env": "a", "outcome": "wrong_answer", "reason": "check_fail"},
              {"env": "b", "outcome": "correct_on_device", "reason": ""},
              {"env": "c", "outcome": "wrong_answer", "reason": "check_fail"},
              {"env": "d", "outcome": "correct_on_device", "reason": ""}]
    assert G.verdict(row, reruns) == "nondeterministic"
    # a checksum that changes between runs in one environment
    row = {"cls": "wrong_code", "reason": "x", "checksum": 5}
    reruns = [{"env": e, "cls": "wrong_code", "reason": "x", "checksum": c}
              for e, c in (("a", 5), ("b", 5), ("c", 5), ("d", 7))]
    assert G.verdict(row, reruns) == "nondeterministic"
    # a flaky rerun (its own repeats disagreed)
    reruns = [{"env": e, "outcome": "wrong_answer", "reason": "check_fail",
               "flaky": e == "c"} for e in "abcd"]
    assert G.verdict({"outcome": "wrong_answer", "reason": "check_fail"},
                     reruns) == "nondeterministic"


def test_not_reproduced_sets_legality_review(tmp_path):
    tc = marker_compiler(tmp_path, "never-in-a-path")
    row = {"kind": "catalog", "ident": "omp52-gate-probe", "campaign": "t",
           "toolchain": "cce19", "mode": "unified", "outcome": "rejected",
           "reason": "ice: INTERNAL COMPILER ERROR"}
    reruns = run_all(row, tc, tmp_path / "gate")
    assert all(r["outcome"] == "correct_on_device" for r in reruns)
    assert G.verdict(row, reruns) == "not_reproduced"
    j = G.judge(row, reruns)
    assert j["legality_review"] is True


def test_harness_errors_are_not_evidence():
    row = {"outcome": "rejected", "reason": "diagnostic: x"}
    bad = [{"env": e, "outcome": "harness_error", "reason": "environment"}
           for e in "abcd"]
    with pytest.raises(ValueError):
        G.verdict(row, bad)
    ok = bad[:3] + [{"env": "d", "outcome": "rejected",
                     "reason": "diagnostic: x"}]
    assert G.verdict(row, ok) == "confirmed"
    assert G.judge(row, ok)["missing"] == ["a", "b", "c"]


def test_a_stored_row_that_differs_from_every_rerun_is_nondeterministic():
    """The stored row is a run of (a); when it differs from every
    rerun and its provenance shows no change, (a) disagrees with itself.
    Only a recorded change (toolchain build, run environment) makes it
    'environment', named changed_since."""
    row = {"outcome": "rejected", "reason": "diagnostic: ftn-100 x"}
    reruns = [{"env": e, "outcome": "rejected",
               "reason": "ice: INTERNAL COMPILER ERROR \"y\""}
              for e in "abcd"]
    assert G.verdict(row, reruns) == "nondeterministic"
    old = dict(row, toolchain_build="Cray Fortran 19.0.0 [modules: none]")
    new = [dict(r, toolchain_build="Cray Fortran 19.0.1 [modules: x]")
           for r in reruns]
    assert G.verdict(old, new) == "environment"
    j = G.judge(old, new)
    assert j["changed_since"].startswith("toolchain build: Cray Fortran "
                                         "19.0.0 then")
    assert j["condition"].startswith("changed since: toolchain build")
    same_tb = [dict(r, toolchain_build="Cray Fortran 19.0.0 [modules: y]")
               for r in reruns]
    assert G.verdict(old, same_tb) == "nondeterministic"


def test_scattered_values_are_nondeterministic():
    """Runs a and d agree, b and c give two other values."""
    row = {"cls": "wrong_code", "reason": "x", "checksum": 1}
    rr = [{"env": e, "cls": "wrong_code", "reason": "x", "checksum": c}
          for e, c in (("a", 1), ("b", 2), ("c", 3), ("d", 1))]
    assert G.verdict(row, rr) == "nondeterministic"
    # b differs from a, c agrees with a: an environment (b's path)
    rr = [{"env": e, "cls": "wrong_code", "reason": "x", "checksum": c}
          for e, c in (("a", 1), ("b", 2), ("c", 1), ("d", 1))]
    assert G.verdict(row, rr) == "environment"


def _rows(sig: str, n: int, cost: float = 10.0) -> list[dict]:
    return [{"cell": f"{sig}-{k}", "signature": sig, "cost": cost,
             "outcome": "rejected", "reason": sig} for k in range(n)]


def test_budget_sampling_and_inheritance():
    rows = _rows("s1", 10) + _rows("s2", 1) + _rows("s3", 5) + \
        _rows("s4", 4)
    cost = lambda r: r["cost"]                    # noqa: E731
    # within the budget: every row, no sampling
    p = G.plan(rows, 4 * 10 * 20, cost=cost)
    assert {r["sample"] for r in p["rows"]} == {"all"}
    assert not p["over_budget"]
    # above it: one of each new signature (s4 is known: not "new"), then
    # up to 3 per signature round-robin while the budget lasts
    p = G.plan(rows, 4 * 10 * 7, cost=cost, known={"s4"})
    by = {}
    for r in p["rows"]:
        by.setdefault(r["signature"], []).append(r["sample"])
    assert by["s1"].count("new") == by["s2"].count("new") == \
        by["s3"].count("new") == 1 and "new" not in by["s4"]
    rerun = {s: sum(x != "inherited" for x in v) for s, v in by.items()}
    assert rerun == {"s1": 2, "s2": 1, "s3": 2, "s4": 2}   # 7 rows
    assert p["spent_s"] <= p["budget_s"] and not p["over_budget"]
    assert all(v <= G.PER_SIGNATURE for v in rerun.values())
    # the budget is a hard stop: tier 1 is cut too, and
    # that is reported; a signature without a rerun row leaves its rows
    # unchecked
    p2 = G.plan(rows, 4 * 10 * 2, cost=cost)
    assert p2["over_budget"]
    assert sum(r["sample"] == "new" for r in p2["rows"]) == 2
    got2 = G.inherit(p2["rows"], {r["cell"]: "confirmed" for r in p2["rows"]
                                  if r["sample"] == "new"})
    assert sorted({v["verdict"] for v in got2.values()}) == [
        "confirmed", "unchecked"]
    # inheritance: the worst verdict of the signature's rerun rows
    verdicts = {}
    for r in p["rows"]:
        if r["sample"] != "inherited":
            verdicts[r["cell"]] = "confirmed"
    first_s1 = next(r["cell"] for r in p["rows"]
                    if r["signature"] == "s1" and r["sample"] != "inherited")
    verdicts[first_s1] = "not_reproduced"
    got = G.inherit(p["rows"], verdicts)
    s1 = [got[r["cell"]] for r in p["rows"] if r["signature"] == "s1"]
    inh = [v for v in s1 if v["inherited"]]
    assert len(inh) == 8 and all(v["verdict"] == "not_reproduced"
                                 for v in inh)
    s3 = [got[r["cell"]] for r in p["rows"] if r["signature"] == "s3"]
    assert {v["verdict"] for v in s3} == {"confirmed"}
    assert sum(v["inherited"] for v in s3) == 3


def test_signature_groups_toolchain_class_and_message():
    a = {"toolchain": "cce19", "outcome": "rejected",
         "reason": "diagnostic: ftn-1234 ftn: ERROR | Object \"A\" bad 3"}
    b = dict(a, reason="diagnostic: ftn-1234 ftn: ERROR | Object \"B\" bad 9")
    c = dict(a, toolchain="cce20")
    assert G.signature(a) == G.signature(b) != G.signature(c)
    w1 = {"toolchain": "afar", "outcome": "wrong_answer", "kind": "catalog",
          "ident": "omp52-clause-map-x", "reason": "check_fail: r"}
    w2 = dict(w1, ident="omp50-clause-map-x")
    w3 = dict(w1, ident="omp52-clause-map-y")
    assert G.signature(w1) == G.signature(w2) != G.signature(w3)


def test_counts_as_failure_only_when_confirmed():
    row = {"cell": "c1", "outcome": "rejected", "reason": "diagnostic: x"}
    assert G.counts_as_failure(row, {})          # not gated yet: counts
    assert G.counts_as_failure(row, {"c1": {"verdict": "confirmed"}})
    for v in G.REVIEW:
        assert not G.counts_as_failure(row, {"c1": {"verdict": v}})
    assert not G.counts_as_failure(dict(row, outcome="correct_on_device"),
                                   {})


def test_gate_hook_receives_every_failing_row(tmp_path):
    import json
    q = tmp_path / "queue.jsonl"
    harness.GATE_HOOKS.append(G.hook(q))
    try:
        original(always_ice(tmp_path), tmp_path)
        original(marker_compiler(tmp_path, "never-in-a-path"), tmp_path)
    finally:
        harness.GATE_HOOKS.clear()
    rows = [json.loads(x) for x in q.read_text().splitlines()]
    assert [r["outcome"] for r in rows] == ["rejected"]
    assert rows[0]["gate"] == "pending"


def test_stored_row_is_read_with_the_current_message_tables():
    """A classifier fix (a rejection followed by a front end's crash is an
    ICE) is listed as a reclassification and is not taken for an
    environment difference."""
    from offload.engine import gate_report as GP
    log = where.message("nvhpc_acc_fort2_crash").read_text().split(
        "==== verbatim output below ====\n", 1)[1]
    item = {"cell": "catalog|acc34-clause-gang|nvhpc|0", "kind": "catalog",
            "ident": "acc34-clause-gang", "toolchain": "nvhpc",
            "outcome": "rejected", "compile_log": log,
            "reason": "diagnostic: NVFORTRAN-S-0155-Invalid atomic update "
                      "expression  (<tmpdir>/acc34-clause-gang.f90: 33)"}
    it = GP.reclassify(item)
    assert it["reclassified"]["outcome"] == "rejected"
    assert it["reason"].startswith("ice: ") and "TERMINATED" in it["reason"]
    reruns = [{"env": e, "outcome": "rejected", "reason": it["reason"]}
              for e in "abcd"]
    # the old reading: the stored row ran in (a) and differs from it
    assert G.verdict(item, reruns) == "nondeterministic"
    assert G.verdict(it, reruns) == "confirmed"         # the current one


def test_the_gate_verdicts_are_an_input_of_the_confirmer_batch():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "regenerate", Path(__file__).resolve().parent.parent.parent / "tools" /
        "regenerate.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    assert {"results/gate/verdicts.jsonl", "offload/engine/gate.py",
            "offload/engine/prerun.py"} <= set(R.BATCH_INPUTS)


def test_a_rerun_killed_by_sigkill_is_not_evidence():
    """The OOM killer (or an external kill) ends a rerun with SIGKILL:
    no evidence about the program, unless the stored row was killed too."""
    row = {"outcome": "wrong_answer", "reason": "check_fail: x"}
    reruns = [{"env": e, "outcome": "wrong_answer", "reason": "check_fail"}
              for e in "abc"] + [{"env": "d", "outcome": "wrong_answer",
                                  "reason": "crash: SIGKILL; without "
                                            "mandatory: crash: SIGKILL"}]
    assert G.verdict(row, reruns) == "confirmed"
    assert G.judge(row, reruns)["missing"] == ["d"]
    killed_row = {"outcome": "wrong_answer", "reason": "crash: SIGKILL"}
    assert G.verdict(killed_row, reruns) == "nondeterministic"


def test_report_lists_every_reclassified_row(tmp_path, monkeypatch):
    """A changed verdict on stored data is never silent: the change log
    lists every row the gate reclassifies (own and inherited verdicts
    other than confirmed), with the old and the new outcome; the review
    queue lists the rerun rows, legality and determinism first."""
    import json
    from offload.engine import gate_report as GP
    out, docs = tmp_path / "gate", tmp_path / "docs"
    monkeypatch.setattr(GP, "OUT", out)
    monkeypatch.setattr(GP, "CHANGES", docs / "gate-changes")
    monkeypatch.setattr(GP, "DOC", docs / "gate.md")
    monkeypatch.setattr(GP, "findings_affected", lambda recs: {})
    d = out / "catalog"
    (d / "reruns").mkdir(parents=True)
    base = {"campaign": "catalog", "kind": "catalog", "toolchain": "cce19",
            "machine": "tuolumne", "xnack": 1, "mode": "unified",
            "outcome": "wrong_answer", "reason": "check_fail: x",
            "stdout": "RESULT ran_on_host=0 check=fail", "locator": {}}
    plan = [dict(base, cell=f"c{k}", ident=f"omp52-p{k}",
                 signature="sig", sample="sampled" if k < 2 else
                 "inherited") for k in range(4)]
    (d / "plan.jsonl").write_text("".join(json.dumps(r) + "\n"
                                          for r in plan))
    (d / "plan.json").write_text(json.dumps({
        "signatures": 1, "budget_gpu_h": 1, "planned_gpu_h": 1,
        "sample": {}, "by_machine": {}, "date": "x"}))
    rr = [{"cell": "c0", "env": e, "outcome": "wrong_answer",
           "reason": "check_fail: x", "stdout": "RESULT ran_on_host=0 "
           "check=fail", "seconds": 1} for e in "abcd"]
    rr += [{"cell": "c1", "env": e, "outcome": "correct_on_device",
            "reason": "", "seconds": 1} for e in "abcd"]
    (d / "reruns" / "n.jsonl").write_text("".join(json.dumps(r) + "\n"
                                                  for r in rr))
    res = GP.report(["catalog"], prerun=False)
    assert res["queue"] == 1
    tsv = (docs / "gate-changes" / "catalog.tsv").read_text().splitlines()
    rows = {ln.split("\t")[0]: ln.split("\t") for ln in tsv[1:]}
    # c0 confirmed; c2, c3 (run-time failures not rerun) unchecked: they
    # keep their outcome, so they are no reclassification
    assert set(rows) == {"c1"}
    assert rows["c1"][3] == "not_reproduced" and rows["c1"][4] == "no"
    assert "a:correct_on_device" in rows["c1"][5]
    assert rows["c1"][2].startswith("wrong_answer")
    md = (docs / "gate.md").read_text()
    assert "### not_reproduced: `c1`" in md and "- legality:" in md
    v = [json.loads(x) for x in (out / "verdicts.jsonl").read_text()
         .splitlines()]
    assert {x["cell"]: x["verdict"] for x in v} == {
        "c0": "confirmed", "c1": "not_reproduced", "c2": "unchecked",
        "c3": "unchecked"}


def test_stress_bug_counts_take_only_confirmed_rows():
    from offload.engine import stress_report as SR
    prog = {"id": "p1", "gate": {"stage": "ok"}, "elision": None,
            "lines": 10, "kernels": []}
    rows = [{"id": "p1", "toolchain": t, "mode": 1, "variant": "O2",
             "cls": "ice", "reason": "ice: INTERNAL COMPILER ERROR x",
             "legality": "legal", "axis": "nest", "size": 4,
             "model": "omp", "lang": "f90"} for t in ("cce19", "cce20")]
    assert sum(f["rows"] for f in SR.findings({"p1": prog}, rows,
                                               {}).values()) == 2
    v = {"stress|p1|cce19|1|O2": {"verdict": "environment"},
         "stress|p1|cce20|1|O2": {"verdict": "confirmed"}}
    got = SR.findings({"p1": prog}, rows, v)
    assert sum(f["rows"] for f in got.values()) == 1
    assert sum(f["unconfirmed"] for f in got.values()) == 1


def test_ice_reports_that_differ_only_in_form_are_the_same_failure():
    """A long build path wraps CCE's ICE line (the site moves to the next
    line), a run prints the driver's crash report instead of the defect's
    line, a clang offloading function name carries the file's id: none of
    these is another failure (seen in the stored-data run)."""
    site = ('ice: INTERNAL COMPILER ERROR:  "Unhandled expression type in '
            'conversion" (/workspace/crayftn/pdgcs/v_expr_fort.c, line 551, '
            'version cc4d36e4)')
    cut = 'ice: INTERNAL COMPILER ERROR:  "Unhandled expression type in ' \
        'conversion" (/tmp/GATEABCDEFGHIJKLMN/a/very/long/path/prog.f90'
    row = {"outcome": "rejected", "reason": site}
    rr = [{"env": e, "outcome": "rejected", "reason": r}
          for e, r in (("a", site), ("b", cut), ("c", site), ("d", site))]
    assert G.verdict(row, rr) == "confirmed"
    gen = {"outcome": "rejected", "reason": "ice: clang: error: clang "
           "frontend command failed due to signal (use -v)"}
    please = {"outcome": "rejected", "reason": "ice: PLEASE submit a bug "
              "report to HPE at https://support.hpe.com/"}
    assert G.verdict(please, [dict(gen, env=e) for e in "abcd"]) == \
        "confirmed"
    other = {"outcome": "rejected", "reason": 'ice: INTERNAL COMPILER '
             'ERROR:  "Too few arguments on the stack" (v_fei.c, line 9)'}
    # another ICE in every rerun: (a) disagrees with the stored row
    assert G.verdict(row, [dict(other, env=e) for e in "abcd"]) == \
        "nondeterministic"
    a = ("rejected", G.message_key(
        "not_implemented: error: p.c:31:5: in function "
        "__omp_offloading_14_29a90fbb_main_l28 void (ptr): unsupported"))
    b = ("rejected", G.message_key(
        "not_implemented: error: p.c:31:5: in function "
        "__omp_offloading_14_29b0f02a_main_l28 void (ptr): unsupported"))
    assert a == b


def test_flaky_rows_are_nondeterministic_whatever_they_inherit():
    """A row whose stored repeats disagree is nondeterministic
    on its own evidence, rerun or not."""
    rows = [{"cell": f"c{k}", "kind": "catalog", "ident": f"omp52-p{k}",
             "toolchain": "cce19", "outcome": "rejected",
             "reason": "diagnostic: ftn-1 ftn: ERROR x"} for k in range(3)]
    rows[2]["flaky"] = True
    p = G.plan(rows, 4 * 10.0, cost=lambda r: 10.0)
    by = {r["cell"]: r["sample"] for r in p["rows"]}
    assert by["c2"] == "own"
    got = G.inherit(p["rows"], {next(c for c, s in by.items()
                                     if s == "new"): "confirmed"})
    assert got["c2"] == {"verdict": "nondeterministic", "inherited": False,
                         "own_repeats": True}
    assert G.verdict(rows[2], []) == "nondeterministic"


def test_run_time_failures_never_inherit():
    """A run-time failure, or an ICE whose key is a generic
    crash report, that was not rerun is unchecked."""
    rt = [{"cell": f"f{k}", "kind": "fuzz", "ident": f"s1:{k}",
           "toolchain": "cce21", "cls": "run_error",
           "reason": "crash: SIGSEGV", "locator": {"run": "s1"}}
          for k in range(5)]
    gen = [{"cell": f"g{k}", "kind": "fuzz", "ident": f"s1:{9 + k}",
            "toolchain": "cce21", "cls": "ice", "locator": {"run": "s1"},
            "reason": "ice: ftn-7991 ftn: INTERNAL | \"optcg was "
            "terminated due to receipt of signal 06: Aborted.\""}
           for k in range(3)]
    assert not any(G.inheritable(r) for r in rt + gen)
    assert len({G.signature(r) for r in gen}) == 3     # per program
    p = G.plan(rt + gen, 4 * 10.0 * 2, cost=lambda r: 10.0)
    samples = {r["cell"]: r["sample"] for r in p["rows"]}
    assert sorted(samples.values()).count("runtime") == 2
    rerun = [c for c, s in samples.items() if s == "runtime"]
    got = G.inherit(p["rows"], {c: "confirmed" for c in rerun})
    assert {c: v["verdict"] for c, v in got.items() if c not in rerun} == {
        c: "unchecked" for c in samples if c not in rerun}
    assert G.counts_as_failure(rt[0], {"f0": {"verdict": "unchecked"}})
    assert not G.counts_as_failure(rt[0], {"f0": {"verdict": "illegal"}})


def test_a_cce_message_cut_inside_its_quotes_is_the_same_ice():
    """A long build path cuts the line inside the quoted
    message; it is compared by its prefix, not split off."""
    full = ('ice: INTERNAL COMPILER ERROR:  "Unhandled expression type in '
            'get base or dv mapping" (/workspace/crayftn/pdgcs/'
            'v_expr_fort.c, line 551, version x)')
    cut = 'ice: INTERNAL COMPILER ERROR:  "Unhandled expression type in ' \
        'get base or dv m'
    row = {"outcome": "rejected", "reason": full}
    rr = [{"env": e, "outcome": "rejected", "reason": r}
          for e, r in (("a", full), ("b", cut), ("c", full), ("d", full))]
    assert G.observe({"outcome": "rejected", "reason": cut})[1].endswith(
        '..."')
    assert G.verdict(row, rr) == "confirmed"
    other = ('ice: INTERNAL COMPILER ERROR:  "Unhandled expression type in '
             'conversion" (v_expr_fort.c, line 552)')
    assert not G.same(G.observe(row), G.observe(
        {"outcome": "rejected", "reason": other}))


def test_campaign_kinds_are_declared():
    """Every kind declares its prefix and signature mode; an
    undeclared kind is an error; the dataenv kind is declared with
    per-program signatures."""
    import pytest as _pt
    with _pt.raises(KeyError):
        G.signature({"kind": "newkind", "toolchain": "afar",
                     "outcome": "wrong_answer", "reason": "check_fail"})
    with _pt.raises(KeyError):
        G.environments({"kind": "newkind", "ident": "x"}, "/tmp")
    d = {"kind": "dataenv", "ident": "dataenv-r12-f", "toolchain": "cce19",
         "outcome": "wrong_answer", "reason": "check_fail: x",
         "stdout": "RESULT ran_on_host=0 check=fail"}
    assert G.KINDS["dataenv"] == {"prefix": "dataenv_",
                                  "signature": "program"}
    assert G.signature(d) == "cce19|wrong_answer|dataenv-r12-f|check=fail"
    assert "-" not in G.KINDS["dataenv"]["prefix"]
    with _pt.raises(ValueError):
        G.register_kind("dataenv", "dataenv_", "atom")
    assert G.register_kind("dataenv", "dataenv_", "program")


def test_cost_prices_timeouts_at_their_limit():
    to = {"kind": "evidence", "toolchain": "cce19", "outcome": "timeout",
          "reason": "compile_timeout"}
    assert G.cost_s(to) == 900 + 10
    rt = {"kind": "catalog", "toolchain": "cce19",
          "outcome": "wrong_answer", "reason": "timeout", "timeout_s": 120}
    assert G.cost_s(rt) == 30 + 120 + 10


def test_a_front_end_killed_by_signal_9_is_not_evidence():
    row = {"cls": "ice", "reason": "ice: nvfortran-Fatal-/x/fort2 "
           "TERMINATED by signal 9"}
    assert G.killed(row)
    assert not G.killed({"cls": "ice", "reason": "ice: nvfortran-Fatal-"
                         "/x/fort2 TERMINATED by signal 11"})


def test_long_messages_keep_their_tail():
    """Two diagnostics that differ after 120 characters."""
    head = "diagnostic: ftn-100 ftn: ERROR | Unexpected syntax while " \
        "parsing the DIRECTIVE statement : \"INDIRECT, LINK, TO or " \
        "DEVICE_TYPE\" was expected but found "
    a, b = G.message_key(head + '")".'), G.message_key(head + '":".')
    assert a != b


def _compile_campaign(tmp_path, monkeypatch, decisions: str):
    """Three CCE rejections of one diagnostic (inheritable): c0 rerun and
    not reproduced, c1 and c2 inherit; c3 a run-time failure rerun and
    confirmed, c4 a run-time failure not rerun (unchecked)."""
    import json
    from offload.engine import gate_report as GP
    out, docs = tmp_path / "gate", tmp_path / "docs"
    monkeypatch.setattr(GP, "OUT", out)
    monkeypatch.setattr(GP, "CHANGES", docs / "gate-changes")
    monkeypatch.setattr(GP, "DOC", docs / "gate.md")
    monkeypatch.setattr(GP, "findings_affected", lambda recs: {})
    dec = tmp_path / "gate_queue.yaml"
    dec.write_text(decisions)
    monkeypatch.setattr(G, "DECISIONS_FILE", dec)
    d = out / "catalog"
    (d / "reruns").mkdir(parents=True)
    rej = {"campaign": "catalog", "kind": "catalog", "toolchain": "cce19",
           "machine": "tuolumne", "xnack": 1, "mode": "unified",
           "outcome": "rejected", "locator": {},
           "reason": "diagnostic: ftn-1 ftn: ERROR P | Bad clause"}
    run = dict(rej, outcome="wrong_answer", reason="check_fail: x",
               stdout="RESULT ran_on_host=0 check=fail")
    plan = [dict(rej, cell=f"c{k}", ident=f"omp52-p{k}") for k in range(3)]
    plan += [dict(run, cell="c3", ident="omp52-q3"),
             dict(run, cell="c4", ident="omp52-q4")]
    (d / "plan.jsonl").write_text("".join(json.dumps(r) + "\n"
                                          for r in plan))
    (d / "plan.json").write_text(json.dumps({
        "signatures": 2, "budget_gpu_h": 1, "planned_gpu_h": 1,
        "sample": {}, "by_machine": {}, "date": "x"}))
    rr = [{"cell": "c0", "env": e, "outcome": "correct_on_device",
           "reason": "", "seconds": 1} for e in "abcd"]
    rr += [{"cell": "c3", "env": e, "outcome": "wrong_answer",
            "reason": "check_fail: x", "stdout": "RESULT ran_on_host=0 "
            "check=fail", "seconds": 1} for e in "abcd"]
    (d / "reruns" / "n.jsonl").write_text("".join(json.dumps(r) + "\n"
                                                  for r in rr))
    return GP, out, docs


def test_a_decision_applies_to_its_own_row_only(tmp_path, monkeypatch):
    """The decisions (catalog/gate_queue.yaml, keyed by cell): a
    decided row leaves the queue and counts as its decision says; the rows
    that inherit from it keep the gate's own semantics; the queue lists
    only undecided rows (new since the review)."""
    import json
    GP, out, docs = _compile_campaign(tmp_path, monkeypatch, """
entries:
- {k: '0', cell: c0, verdict: nondeterministic_defect, counts_as: failure,
   group: g, finding: x.f90}
- {k: '1', cell: c3, verdict: unspecified, counts_as: none, group: h}
""")
    res = GP.report(["catalog"], prerun=False)
    v = {x["cell"]: x for x in map(json.loads, (out / "verdicts.jsonl")
                                   .read_text().splitlines())}
    assert v["c0"]["verdict"] == "not_reproduced"
    assert v["c0"]["decision"] == "nondeterministic_defect"
    assert G.counts(v["c0"]) is True
    # the inheritors: the gate's own semantics (the worst verdict of their
    # signature's rerun rows), never the decision
    for c in ("c1", "c2"):
        assert v[c]["verdict"] == "not_reproduced" and v[c]["inherited"]
        assert "decision" not in v[c] and G.counts(v[c]) is False
    assert v["c3"]["verdict"] == "confirmed" and G.counts(v["c3"]) is False
    assert v["c4"]["verdict"] == "unchecked" and G.counts(v["c4"]) is True
    assert res["queue"] == 0 and res["new_queue"] == []
    md = (docs / "gate.md").read_text()
    assert "2 rows carry a decision" in md
    # counts_as_failure honours the decision
    assert G.counts_as_failure({"campaign": "catalog", "kind": "catalog",
                                "outcome": "wrong_answer", "cell": "c3"},
                               {"c3": v["c3"]}) is False


def test_an_undecided_review_row_is_new(tmp_path, monkeypatch):
    GP, out, docs = _compile_campaign(tmp_path, monkeypatch, "entries: []\n")
    res = GP.report(["catalog"], prerun=False)
    assert res["new_queue"] == ["c0"]


def test_r04b_honours_a_decision():
    """Rule R04b's predicate (gate_unconfirmed) reads offload.engine.gate.counts:
    a decided row counts as its decision says; unchecked keeps its
    outcome."""
    assert G.counts({"verdict": "environment", "counts_as": "failure"})
    assert not G.counts({"verdict": "confirmed", "counts_as": "none"})
    assert G.counts({"verdict": "unchecked"})
    assert not G.counts({"verdict": "illegal"})
    assert G.counts(None) is None


def test_ices_one_finding_names_are_the_same_failure():
    """CCE's character-map ICE prints one of three messages by
    build path; its finding's index pattern names all three
    (fuzz/s1-8634-cce21.f90), so the gate calls the reruns confirmed."""
    a = ('ice: INTERNAL COMPILER ERROR:  "Unhandled expression type in get '
         'base or dv mem" (v_expr.c, line 9)')
    b = 'ice: INTERNAL COMPILER ERROR:  "unexpected type in TYPE_DEREF" (x)'
    oa = G.observe({"outcome": "rejected", "reason": a})
    ob = G.observe({"outcome": "rejected", "reason": b})
    assert G.same_finding(oa[1], ob[1], "cce21") == "fuzz/s1-8634-cce21.f90"
    assert G.same(oa, ob, "cce21")
    assert not G.same(oa, ob, "afar")
    row = {"outcome": "rejected", "reason": a, "toolchain": "cce21"}
    rr = [{"env": e, "outcome": "rejected", "reason": r}
          for e, r in (("a", a), ("b", b), ("c", a), ("d", a))]
    assert G.verdict(row, rr) == "confirmed"


def test_a_capacity_limit_is_no_failure():
    """The runtime's capacity messages (CCE 'Large args not
    supported', AFAR 'Too many arguments in kmp_invoke_microtask') are a
    capacity break point, not a compiler failure."""
    from offload.engine import stress_exec as SX
    cce = {"cls": "run_error", "reason": "exit_status: 1",
           "toolchain": "cce19", "output": "ACC: libcrayacc/acc_hw_amd.c:"
           "1783 CRAY_ACC_ERROR - Large args not supported\n"}
    afar = {"cls": "run_timeout", "reason": "run_timeout",
            "toolchain": "afar", "output": "Too many arguments in "
            "kmp_invoke_microtask, aborting execution.\n"}
    for row in (cce, afar):
        assert G.outcome_class(row) == "capacity"
        assert not G.is_failure("capacity")
        assert not G.counts_as_failure(row, {})
    other = dict(cce, output="Segmentation fault")
    assert G.outcome_class(other) == "run_error"

    class Ex:
        rc, timed_out = 1, False
        stdout = ""
        stderr = "ACC: x CRAY_ACC_ERROR - Large args not supported"
    assert SX.judge(None, Ex(), "cce21")[0] == "capacity"


def _tool():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gate_tool", Path(__file__).resolve().parent.parent.parent / "tools" /
        "campaigns" /
        "gate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gate_tool"] = mod      # the worker processes import it
    spec.loader.exec_module(mod)
    return mod


def test_the_budget_is_a_hard_stop_and_c_reuses_a_path(tmp_path,
                                                        monkeypatch):
    """`tools/campaigns/gate.py run` starts nothing
    once the campaign's ledger reaches its budget, records its own
    GPU-hours, scales the limits with its workers, and runs (c) in the
    path of the recorded (a)."""
    import argparse
    import concurrent.futures
    import functools
    import json
    import multiprocessing
    T = _tool()
    # the workers must see this test's patches: forked, whatever the platform's default start method
    monkeypatch.setattr(concurrent.futures, "ProcessPoolExecutor", functools.partial(
        concurrent.futures.ProcessPoolExecutor, mp_context=multiprocessing.get_context("fork")))
    out = tmp_path / "gate"
    monkeypatch.setattr(T, "OUT", out)
    monkeypatch.setattr(T, "LEDGER", out / "ledger.jsonl")
    monkeypatch.setenv("GATE_TMP", str(tmp_path / "root"))
    monkeypatch.setattr(G, "gate_tmp", lambda: str(tmp_path / "root"))
    seen = []

    def fake(item, env):
        import os
        return {"env": env["env"], "path": env["path"],
                "outcome": "rejected", "reason": "diagnostic: x",
                "factor": os.environ.get("GATE_LOAD_FACTOR")}
    monkeypatch.setattr(T.GS, "rerun", fake)
    d = out / "catalog"
    (d / "reruns").mkdir(parents=True)
    row = {"cell": "c0", "campaign": "catalog", "kind": "catalog",
           "ident": "omp52-p", "toolchain": "cce19", "machine": "tuolumne",
           "xnack": 1, "outcome": "rejected", "reason": "diagnostic: x",
           "sample": "new"}
    (d / "plan.jsonl").write_text(json.dumps(row) + "\n")
    (d / "reruns" / "old.jsonl").write_text(json.dumps(
        {"cell": "c0", "env": "a", "path": "/tmp/x_gate_9_0/harness_p",
         "outcome": "rejected", "reason": "diagnostic: x",
         "node": "elsewhere"}) + "\n")
    a = argparse.Namespace(campaign="catalog", machine="tuolumne",
                           envs="c", workers=16, limit_s=0, shard=None,
                           budget_gpu_h=1.0, gpus=4, concurrent=1)
    (out / "ledger.jsonl").write_text(json.dumps(
        {"campaign": "catalog", "gpu_h": 1.0}) + "\n")
    assert T.cmd_run(a) == 0
    assert len(list((d / "reruns").glob("*.jsonl"))) == 1   # nothing ran
    (out / "ledger.jsonl").write_text("")
    monkeypatch.setattr(T.os, "makedirs", lambda *x, **k: None)
    assert T.cmd_run(a) == 0
    new = [json.loads(x) for p in (d / "reruns").glob("*.jsonl")
           if p.name != "old.jsonl" for x in p.read_text().splitlines()]
    assert [(r["env"], r["path"], r["factor"]) for r in new] == [
        ("c", "/tmp/x_gate_9_0/harness_p", "2.0")]
    led = [json.loads(x) for x in (out / "ledger.jsonl").read_text()
           .splitlines()]
    assert led[-1]["campaign"] == "catalog" and led[-1]["gpus"] == 4
    # done: nothing more; and a row whose (a) ran on this node is left
    # to another node's job
    assert T.cmd_run(a) == 0
    for p in (d / "reruns").glob("*.jsonl"):
        if p.name != "old.jsonl":
            p.unlink()
    monkeypatch.setattr(T, "_here", lambda: "elsewhere")
    assert T.cmd_run(a) == 0
    assert not any(p.read_text().strip() for p in
                   (d / "reruns").glob("*.jsonl") if p.name != "old.jsonl")


API_IN_LOOP = """program p
  use omp_lib
  implicit none
  integer :: i, a(100)
  !$omp target teams loop map(from: a)
  do i = 1, 100
    a(i) = omp_get_team_num()
  end do
  print *, a(1)
end program p
"""

RACY = """program p
  implicit none
  integer :: i
  real(8) :: a(100), s
  a = 1.0d0
  s = 0.0d0
  !$omp target teams distribute parallel do map(to: a) map(tofrom: s)
  do i = 1, 100
    s = s + a(i)
  end do
  print *, s
end program p
"""


def test_the_rules_pass_makes_illegal_programs_illegal(tmp_path,
                                                       monkeypatch):
    """An ICE of a program that calls an OpenMP routine in a
    loop region (order_concurrent_no_api_calls) is illegal; a racy
    program's run-time failure is illegal, its compile failure is kept."""
    import json
    from offload.engine import gate_report as GP
    out = tmp_path / "gate"
    monkeypatch.setattr(GP, "OUT", out)
    monkeypatch.setattr(G, "DECISIONS_FILE", tmp_path / "none.yaml")
    d = out / "fuzz"
    d.mkdir(parents=True)
    base = {"campaign": "fuzz", "kind": "fuzz", "machine": "wingtip",
            "toolchain": "nvhpc", "xnack": 0, "mode": "managed"}
    plan = [dict(base, cell="f0", ident="s:0", locator={"seed": 0},
                 cls="ice", reason="ice: nvfortran-Fatal-x TERMINATED by "
                 "signal 11"),
            dict(base, cell="f1", ident="s:1", locator={"seed": 1},
                 cls="wrong_code", reason="checksum=1 expected=2"),
            dict(base, cell="f2", ident="s:1", locator={"seed": 1},
                 cls="compile_reject", reason="diagnostic: x",
                 toolchain="nvhpc269")]
    (d / "plan.jsonl").write_text("".join(json.dumps(r) + "\n"
                                          for r in plan))
    texts = {0: API_IN_LOOP, 1: RACY}
    monkeypatch.setattr(GP, "_program_of", lambda rec, it: (
        texts[it["locator"]["seed"]], "f90", "omp"))
    n = GP.rules_pass("fuzz", workers=2)
    assert n == {"illegal": 2, "race_compile_failure_kept": 1}
    bad = {x["cell"]: x["why"] for x in map(json.loads, (
        d / "illegal.jsonl").read_text().splitlines())}
    assert set(bad) == {"f0", "f1"}
    assert "rules: violates" in bad["f0"] and "race:" in bad["f1"]
    recs, st = GP.judge_campaign("fuzz")
    v = {r["cell"]: r["verdict"] for r in recs}
    assert v == {"f0": "illegal", "f1": "illegal", "f2": "unchecked"}


def test_a_c_on_the_node_of_a_is_no_evidence():
    """(c) is another node; one on (a)'s node is dropped, and
    a (c) in (a)'s path wins over one elsewhere."""
    a = {"env": "a", "path": "/t/x", "node": "n1", "outcome": "rejected",
         "reason": "diagnostic: x"}
    c_same_node = dict(a, env="c")
    c_other_path = dict(a, env="c", node="n2", path="/t/y")
    c_good = dict(a, env="c", node="n2")
    assert G.valid_reruns([a, c_same_node]) == [a]
    assert G.valid_reruns([a, c_other_path]) == [a, c_other_path]
    assert G.valid_reruns([a, c_other_path, c_good]) == [a, c_good]


def test_c_on_another_gcd_of_a_multi_node_machine_is_no_node_change():
    """Parity: on Tioga (and Tuolumne) (c) is another compute
    node: a GCD of (a)'s node ("tioga39:gpu6" beside "tioga39:gpu5") is
    dropped and not node-distinct; on wingtip, one host, another GPU is."""
    a = {"env": "a", "path": "/t/x", "node": "tioga39:gpu5",
         "outcome": "rejected", "reason": "diagnostic: x",
         "kind": "fuzz", "toolchain": "gcc_g90"}
    b = dict(a, env="b", path="/t/Y")
    d = dict(a, env="d")
    c_gcd = dict(a, env="c", node="tioga39:gpu6")
    c_node = dict(a, env="c", node="tioga38:gpu0")
    assert G.valid_reruns([a, c_gcd]) == [a]
    assert G.valid_reruns([a, c_node]) == [a, c_node]
    assert G.judge(a, [a, b, c_gcd, d])["node_distinct"] is False
    assert G.judge(a, [a, b, c_node, d])["node_distinct"] is True
    w = dict(a, node="wingtip-a.example.edu:gpu2")
    w_c = dict(w, env="c", node="wingtip-a.example.edu:gpu0")
    assert G.valid_reruns([w, w_c]) == [w, w_c]
    assert G.node_key("tioga39:gpu5") == G.node_key("tioga39") == "tioga39"
    assert G.node_key(w["node"]) != G.node_key(w_c["node"])


def test_printed_values_make_a_value_kind_nondeterministic():
    """(the review): a data-environment or
    catalog-style program that prints its values beside `check=fail`
    keeps them in its failure key: repeats with different values are
    nondeterministic, not one confirmed `check=fail`; the same values
    are confirmed; a kind without per-program values (fuzz) is unchanged."""
    def run(env, v):
        return {"env": env, "outcome": "wrong_answer", "reason": "x",
                "stdout": f"a= {v}\nb= 3\nRESULT ran_on_host=0 check=fail"}
    for kind in ("dataenv", "catalog", "widen"):
        row = dict(run("a", 0), kind=kind, toolchain="afar")
        assert G.failure_key(row) == "check=fail a=0 b=3"
        assert G.verdict(row, [run(e, v) for e, v in (
            ("a", 0), ("b", 17038), ("c", 82972), ("d", 104571))]) == \
            "nondeterministic", kind
        assert G.verdict(row, [run(e, 0) for e in "abcd"]) == "confirmed"
    fz = dict(run("a", 0), kind="fuzz", toolchain="afar")
    assert G.failure_key(fz) == "check=fail"
    assert G.printed_values("\tgrid=[1, 1, 1]\nrptr=0, wptr=2\n") == ""


def test_an_own_repeats_row_passes_nothing_on_and_the_store_says_how(
        tmp_path, monkeypatch):
    """A row nondeterministic on its own stored repeats
    with no rerun is labelled `own`, so its verdict never reaches the rows
    of its signature (they stay unchecked/inherit from rerun rows only);
    the verdict store's `sample` says how each row got its verdict."""
    import json
    GP, out, docs = _compile_campaign(tmp_path, monkeypatch, "entries: []\n")
    d = out / "catalog"
    plan = [json.loads(x) for x in (d / "plan.jsonl").read_text()
            .splitlines()]
    # c1 and c2 share c0's signature; make c0 own-flaky with no rerun
    plan[0]["flaky"] = True
    (d / "plan.jsonl").write_text("".join(json.dumps(r) + "\n"
                                          for r in plan))
    (d / "reruns" / "n.jsonl").write_text("".join(
        json.dumps(r) + "\n" for r in map(json.loads, (
            d / "reruns" / "n.jsonl").read_text().splitlines())
        if r["cell"] != "c0"))
    GP.report(["catalog"], prerun=False)
    v = {x["cell"]: x for x in map(json.loads, (out / "verdicts.jsonl")
                                   .read_text().splitlines())}
    assert v["c0"]["verdict"] == "nondeterministic"
    assert v["c0"]["sample"] == "own"
    for c in ("c1", "c2"):
        assert v[c]["verdict"] == "unchecked" and v[c]["sample"] == \
            "inherited", v[c]
    assert v["c3"]["sample"] == "rerun" and v["c4"]["sample"] == "unchecked"


# ---- Tests of offload.engine.run_matrix with the fake compiler -------------------------------------------

import json


from offload.engine.catalog import slice_atoms
from offload.engine.gen import generate
from offload.engine.harness import read_jsonl
from offload.engine.run_matrix import run_matrix, version_flags

ATOMS = ["omp.directive.target", "omp.clause.map.always"]


def fake_tc(name: str, exe: str = "exe_device_pass.sh") -> Toolchain:
    return Toolchain(name, "", f"{FAKES}/fake_fc.sh - 0 {FAKES / exe}")


def programs(version: int, atoms=ATOMS):
    wanted = [a for a in atoms if a in slice_atoms(version)]
    return list(generate(wanted, version))


def test_matrix_writes_one_row_per_cell(tmp_path):
    out = tmp_path / "matrix.jsonl"
    tcs = [fake_tc("afar"), fake_tc("cce19")]
    n = run_matrix(ATOMS, tcs, [1, 0], out, versions=(52, 60), workers=4,
                   repeats=1, timeout_s=20)
    progs = programs(52) + programs(60)
    assert n == len(progs) * 2 * 2
    rows = read_jsonl(out)
    assert len(rows) == n
    cells = {(r.version, r.program_id, r.toolchain, r.xnack) for r in rows}
    want = {(int(p.id[3:5]), p.id, t, x) for p in progs
            for t in ("afar", "cce19") for x in (1, 0)}
    assert cells == want
    assert all(r.outcome == "correct_on_device" for r in rows
               if r.observable)


def test_afar_60_programs_get_explicit_version_flag(tmp_path):
    out = tmp_path / "matrix.jsonl"
    run_matrix(ATOMS, [fake_tc("afar"), fake_tc("cce19")], [0], out,
               versions=(52, 60), workers=2, repeats=1, timeout_s=20)
    rows = read_jsonl(out)
    for r in rows:
        has = "-fopenmp-version=60" in r.flags.split()
        assert has == (r.toolchain == "afar" and r.version == 60), r.flags
        assert "-fopenmp-version=52" not in r.flags  # 5.2 = AFAR default
    assert version_flags("afar", 60) == "-fopenmp-version=60"
    assert version_flags("afar", 52) == ""
    assert version_flags("cce19", 60) == ""  # CCE has no version flag


def test_flags_note_recorded_in_every_row(tmp_path):
    out = tmp_path / "matrix.jsonl"
    run_matrix(ATOMS[:1], [fake_tc("afar")], [1], out, versions=(52,),
               workers=2, repeats=1, timeout_s=20,
               flags_note="thp=unavailable")
    rows = read_jsonl(out)
    assert rows and all(r.flags.endswith(" thp=unavailable") for r in rows)


def test_resume_skips_finished_cells(tmp_path):
    out = tmp_path / "matrix.jsonl"
    tc = fake_tc("afar")
    first = run_matrix(ATOMS[:1], [tc], [0], out, versions=(52,),
                       workers=2, repeats=1, timeout_s=20)
    lines = out.read_text().splitlines()
    # a run cut short: drop the last row and resume
    out.write_text("\n".join(lines[:-1]) + "\n")
    again = run_matrix(ATOMS[:1], [tc], [0], out, versions=(52,),
                       workers=2, repeats=1, timeout_s=20, resume=True)
    assert again == 1
    rows = read_jsonl(out)
    assert len(rows) == first
    assert len({(r.program_id, r.toolchain, r.xnack) for r in rows}) == first


def test_rows_are_written_as_they_finish(tmp_path):
    """With one worker, cell k starts only after the k-1 earlier rows are
    complete lines in the output file."""
    from offload.engine.harness import run_program
    out = tmp_path / "matrix.jsonl"
    seen = []

    def runner(prog, tc, xnack, *a, **kw):
        text = out.read_text()
        assert text == "" or text.endswith("\n")
        seen.append([json.loads(line)["program_id"]
                     for line in text.splitlines()])
        return run_program(prog, tc, xnack, *a, **kw)
    n = run_matrix(ATOMS, [fake_tc("afar")], [0], out, versions=(52,),
                   workers=1, repeats=1, timeout_s=20, runner=runner)
    assert n >= 2 and len(seen) == n
    assert [len(s) for s in seen] == list(range(n))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == n
    assert [r["program_id"] for r in rows] == seen[-1] + [rows[-1]["program_id"]]


def test_unknown_atom_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="omp.clause.nonsense"):
        run_matrix(["omp.clause.nonsense"], [fake_tc("afar")], [0],
                   tmp_path / "m.jsonl", versions=(52,))


def test_rerun_programs_replaces_only_their_rows(tmp_path):
    from offload.engine.run_matrix import rerun_programs
    out = tmp_path / "matrix.jsonl"
    tcs = [fake_tc("afar"), fake_tc("cce19")]
    n = run_matrix(ATOMS, tcs, [0], out, versions=(52,), workers=2,
                   repeats=1, timeout_s=20)
    before = [json.loads(line) for line in out.read_text().splitlines()]
    target = before[0]["program_id"]
    keep = [r for r in before if r["program_id"] != target]
    m = rerun_programs([target], tcs, 0, out, versions=(52,), workers=2,
                       repeats=1, timeout_s=20)
    after = [json.loads(line) for line in out.read_text().splitlines()]
    assert m == 2 and len(after) == n
    assert [r for r in after if r["program_id"] != target] == keep
    assert sorted(r["toolchain"] for r in after
                  if r["program_id"] == target) == ["afar", "cce19"]
    with pytest.raises(ValueError, match="nonsense"):
        rerun_programs(["omp52-nonsense"], tcs, 0, out, versions=(52,))


# --- Headline mode and the copy-mode subset ---------------------------------

def test_copy_mode_programs_from_evidence_and_memory_sensitive_list():
    from offload.engine.gen import Program
    from offload.engine.run_matrix import copy_mode_programs

    def prog(pid, atom, evidence="construct"):
        return Program(id=pid, lang="fortran", source="", atoms=frozenset(),
                       primary_atom=atom, legal=True, violates=None,
                       observable=True, evidence=evidence)
    modes = {"headline_xnack": 1, "copy_xnack": 0, "memory_sensitive": {
        "atoms": [{"pattern": "omp.clause.unified_shared_memory*",
                   "why": "x"}],
        "programs": [{"id": "p-listed", "why": "y"}]}}
    progs = [prog("p-copy", "omp.clause.map.to", "copy_mode_only"),
             prog("p-usm", "omp.clause.unified_shared_memory.required"),
             prog("p-listed", "omp.directive.target"),
             prog("p-plain", "omp.clause.map.to")]
    assert copy_mode_programs(progs, modes) == {"p-copy", "p-usm",
                                                "p-listed"}
    assert copy_mode_programs([(52, p) for p in progs], modes) == {
        "p-copy", "p-usm", "p-listed"}


def test_committed_memory_modes_cover_the_owner_list():
    from offload.engine.run_matrix import copy_mode_subset, matrix_programs
    from offload.engine.catalog import slice_atoms
    subset = copy_mode_subset()
    progs = {p.id: p for _, p in matrix_programs(
        set(slice_atoms(52)) | set(slice_atoms(60)), (52, 60))}
    cmo = {i for i, p in progs.items() if p.evidence == "copy_mode_only"}
    assert cmo <= subset
    for pid in ("omp52-clause-map-present", "omp60-clause-map-present",
                "omp52-clause-map-mapper", "omp60-clause-map-mapper",
                "omp52-clause-unified_shared_memory",
                "omp60-clause-unified_shared_memory-required",
                "omp60-clause-unified_shared_memory-directive_name",
                "omp52-illegal-mapitem-map-001"):
        assert pid in subset, pid
    assert len(subset) < len(progs) / 2


def test_memory_modes_entries_need_a_reason(tmp_path):
    from offload.engine.run_matrix import memory_modes
    p = tmp_path / "m.yaml"
    p.write_text("headline_xnack: 1\ncopy_xnack: 0\nmemory_sensitive:\n"
                 "  atoms:\n    - pattern: omp.clause.map.present\n")
    with pytest.raises(ValueError, match="why"):
        memory_modes(p)


def test_mode_differing_compares_outcome_and_crash():
    from offload.engine.run_matrix import mode_differing

    def r(pid, x, outcome, reason=""):
        return {"program_id": pid, "toolchain": "afar", "xnack": x,
                "outcome": outcome, "reason": reason}
    rows = [r("same", 1, "correct_on_device"), r("same", 0,
                                                 "correct_on_device"),
            r("diff", 1, "correct_on_device"), r("diff", 0, "wrong_answer"),
            r("crash", 1, "wrong_answer", "crash: SIGABRT"),
            r("crash", 0, "wrong_answer", "check_fail"),
            r("one", 1, "rejected")]
    assert mode_differing(rows) == {"diff", "crash"}


def test_run_matrix_only_restricts_programs(tmp_path):
    out = tmp_path / "m.jsonl"
    progs = programs(52)
    keep = {progs[0].id}
    n = run_matrix(ATOMS, [fake_tc("afar")], [0], out, versions=(52,),
                   workers=2, repeats=1, timeout_s=20, only=keep)
    assert n == 1
    assert {r.program_id for r in read_jsonl(out)} == keep


def _tool_2():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "run_matrix_tool",
        Path(__file__).resolve().parent.parent.parent / "tools" / "campaigns" / "run_matrix.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_merge_copy_mode_subset_shape(tmp_path, capsys):
    from offload.engine.catalog import slice_atoms
    from offload.engine.run_matrix import copy_mode_subset, matrix_programs
    tool = _tool_2()
    progs = [p for _, p in matrix_programs(
        set(slice_atoms(52)) | set(slice_atoms(60)), (52, 60))]
    subset = copy_mode_subset()

    def row(p, tc, x):
        return {"program_id": p.id, "toolchain": tc, "xnack": x,
                "version": int(p.id[3:5]), "legal": p.legal,
                "outcome": "correct_on_device"}
    x1 = [row(p, tc, 1) for p in progs for tc in ("afar", "cce19")]
    x0 = [row(p, tc, 0) for p in progs if p.id in subset
          for tc in ("afar", "cce19")]
    f1, f0 = tmp_path / "x1.jsonl", tmp_path / "x0.jsonl"
    f1.write_text("".join(json.dumps(r) + "\n" for r in x1))
    f0.write_text("".join(json.dumps(r) + "\n" for r in x0))
    args = ["merge", "--copy-mode-subset", "--inputs", str(f1), str(f0),
            "--out", str(tmp_path / "m.jsonl")]
    assert tool.main(args) == 0
    # a full copy-mode file is not the subset shape ...
    full0 = [row(p, tc, 0) for p in progs for tc in ("afar", "cce19")]
    f0.write_text("".join(json.dumps(r) + "\n" for r in full0))
    assert tool.main(args) == 1
    assert "unexpected" in capsys.readouterr().out
    # ... but the old full two-mode merge accepts it
    assert tool.main(args[:1] + args[2:]) == 0
    # a missing subset program fails
    f0.write_text("".join(json.dumps(r) + "\n" for r in x0[2:]))
    assert tool.main(args) == 1


def test_replace_swaps_rows_in_place_and_records_the_run(tmp_path, capsys):
    """Rows of a separate run replace the matching cells of the
    full file in place (same position), new cells are appended, every other
    row is kept, and the input run's metadata joins the out file's reruns."""
    tool = _tool_2()

    def row(pid, tc, x, outcome):
        return {"program_id": pid, "toolchain": tc, "xnack": x, "opt": "-O2",
                "outcome": outcome}
    full = [row("p1", "afar", 1, "correct_on_device"),
            row("p1", "afar", 0, "wrong_answer"),
            row("p2", "afar", 1, "correct_on_device")]
    out = tmp_path / "matrix.work.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in full))
    new = tmp_path / "x0.jsonl"
    new.write_text(json.dumps(row("p1", "afar", 0, "correct_on_device"))
                   + "\n" + json.dumps(row("p2", "afar", 0, "rejected"))
                   + "\n")
    Path(str(new) + ".meta.json").write_text(json.dumps(
        {"host": "tuolumne1", "xnack": 0, "thp_seen": "always",
         "started": "2026-10-22T10:00:00", "toolchains": ["afar"]}))
    assert tool.main(["replace", "--out", str(out), "--inputs", str(new),
                      "--why", "Full copy mode"]) == 0
    rows = [json.loads(ln) for ln in out.read_text().splitlines()]
    assert [(r["program_id"], r["xnack"], r["outcome"]) for r in rows] == [
        ("p1", 1, "correct_on_device"), ("p1", 0, "correct_on_device"),
        ("p2", 1, "correct_on_device"), ("p2", 0, "rejected")]
    meta = json.loads(Path(str(out) + ".meta.json").read_text())
    rr = meta["reruns"][-1]
    assert rr["host"] == "tuolumne1" and rr["xnack"] == 0
    assert rr["programs"] == ["p1", "p2"] and rr["rows"] == 2
    assert rr["why"] == "Full copy mode"
    assert "replaced 1, added 1" in capsys.readouterr().out


def test_replace_baseline_rows_by_path(tmp_path):
    tool = _tool_2()

    def row(path, tc, x, status):
        return {"path": path, "toolchain": tc, "xnack": x, "status": status}
    out = tmp_path / "baseline.work.jsonl"
    out.write_text(json.dumps(row("t/a.F90", "cce19", 1, "pass")) + "\n"
                   + json.dumps(row("t/a.F90", "cce19", 0, "fail")) + "\n")
    new = tmp_path / "b.jsonl"
    new.write_text(json.dumps(row("t/a.F90", "cce19", 0, "pass")) + "\n")
    assert tool.main(["replace", "--baseline", "--out", str(out),
                      "--inputs", str(new), "--why", "x"]) == 0
    rows = [json.loads(ln) for ln in out.read_text().splitlines()]
    assert [r["status"] for r in rows] == ["pass", "pass"]
    rr = json.loads(Path(str(out) + ".meta.json").read_text())["reruns"][-1]
    assert rr["baseline_paths"] == ["t/a.F90"] and rr["baseline_rows"] == 1


def test_replace_refuses_duplicate_input_cells(tmp_path, capsys):
    tool = _tool_2()
    r = {"program_id": "p1", "toolchain": "afar", "xnack": 0, "opt": "-O2",
         "outcome": "x"}
    out = tmp_path / "m.jsonl"
    out.write_text(json.dumps(r) + "\n")
    new = tmp_path / "n.jsonl"
    new.write_text(json.dumps(r) + "\n" + json.dumps(r) + "\n")
    assert tool.main(["replace", "--out", str(out), "--inputs", str(new),
                      "--why", "x"]) == 1
    assert out.read_text() == json.dumps(r) + "\n"
    assert "duplicate" in capsys.readouterr().out


def test_replace_refuses_to_shrink_and_leaves_the_file(tmp_path, capsys):
    """Duplicated cells in --out would make the output
    shorter; replace refuses and the file stays as it was."""
    tool = _tool_2()
    r = {"program_id": "p1", "toolchain": "afar", "xnack": 0, "opt": "-O2",
         "outcome": "x"}
    out = tmp_path / "m.jsonl"
    text = json.dumps(r) + "\n" + json.dumps(dict(r, outcome="y")) + "\n"
    out.write_text(text)
    new = tmp_path / "n.jsonl"
    new.write_text(json.dumps(dict(r, outcome="z")) + "\n")
    assert tool.main(["replace", "--out", str(out), "--inputs", str(new),
                      "--why", "x"]) == 1
    assert out.read_text() == text
    assert "shrink" in capsys.readouterr().out
    assert not list(tmp_path.glob("*.tmp"))


# --- Gfx90a twins -------------------------------------------------

def g90_tc(name: str, exe: str = "exe_device_pass.sh") -> Toolchain:
    import dataclasses
    return dataclasses.replace(fake_tc(name, exe), arch="gfx90a",
                               machine="tioga", xnack_modes=(0,))


def test_gfx90a_twin_gets_its_compilers_version_flag(tmp_path, monkeypatch):
    from offload.engine import harness
    monkeypatch.setattr(harness, "detect_gpu", lambda: ("", ""))
    out = tmp_path / "matrix.jsonl"
    run_matrix(ATOMS, [g90_tc("afar_g90"), g90_tc("cce19_g90")], [0], out,
               versions=(52, 60), workers=2, repeats=1, timeout_s=20)
    rows = read_jsonl(out)
    assert {r.toolchain for r in rows} == {"afar_g90", "cce19_g90"}
    for r in rows:
        has = "-fopenmp-version=60" in r.flags.split()
        assert has == (r.toolchain == "afar_g90" and r.version == 60)
        assert r.arch == "gfx90a" and r.machine == "tioga"
    assert version_flags("afar_g90", 60) == "-fopenmp-version=60"


def test_gfx90a_twin_refuses_xnack1(tmp_path):
    with pytest.raises(ValueError, match="HSA_XNACK"):
        run_matrix(ATOMS, [g90_tc("afar_g90")], [1], tmp_path / "m.jsonl",
                   versions=(52,), workers=1, repeats=1, timeout_s=20)


def test_device_count_dependent_sources():
    """The Tioga runs saw one GCD each (ROCR_VISIBLE_DEVICES); a
    program whose result can depend on the number of devices is run again
    with every device visible."""
    from offload.engine.run_matrix import device_count_dependent
    assert device_count_dependent("dev = omp_get_num_devices() - 1")
    assert device_count_dependent("!$omp target device(dev) map(to: a)")
    assert device_count_dependent("#pragma omp target device (1)")
    assert device_count_dependent("dn = omp_get_device_num()")
    assert not device_count_dependent("!$omp target map(to: a)\n"
                                      "x = omp_is_initial_device()")
    assert not device_count_dependent("!$omp declare target device_type(any)")


def test_device_count_patterns_fix_round_1():
    """omp_get_initial_device (equals the device count) and the
    OpenACC device number / count."""
    from offload.engine.run_matrix import device_count_dependent
    assert device_count_dependent("if (omp_get_initial_device() == d)")
    assert device_count_dependent("!$acc set device_num(1)")
    assert device_count_dependent("n = acc_get_num_devices(acc_device_radeon)")


def test_gpu_count_from_rocminfo():
    from offload.engine.toolchains import gpu_count
    text = ("  Name:  AMD EPYC\n  Name:   gfx90a  \n  Marketing Name: X\n"
            "  Name:   gfx90a  \n")
    assert gpu_count(text) == 2 and gpu_count("") == 0
