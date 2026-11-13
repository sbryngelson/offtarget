"""Tests of the findings: header claims against recorded rows, Fortran line limits, new_finding drafts, corpus validation, toolchain cells and OpenMP 5.0 as a catalog version."""


# ---- The header claims of a finding are checked against recorded rows (offload.engine.finding_claims): ----

import json
from pathlib import Path

import pytest

from offload.engine import finding_claims as C
from offload.engine import finding_header as H
from offload.engine import finding_rows as R

FAIL = "COMPILE_FAIL rc=1\nftn-1: ERROR File = x.f90, Line = 3, Column = 5\n  illegal construct\n"
FAIL2 = "COMPILE_FAIL rc=1\nftn-2: ERROR File = x.f90, Line = 3\n  something else entirely\n"
OK = "RUN_OK rc=0\nRESULT check=pass\n"

CASE = {"id": "demo", "finding": "demo.f90", "symptom": "compile:.", "expect": "out:check=pass",
        "lang": "f90", "model": "omp", "affected": ["cce19", "cce20"],
        "control": "src/demo-control.f90", "control_what": "one change"}


def row(tc, obs, env="a", variant="repro", machine="tuolumne", mode=1, gpu=None):
    r = {"case": "demo", "tc": tc, "machine": machine, "mode": mode, "env": env,
         "variant": variant, "obs": obs}
    if gpu is not None:
        r["gpu"] = gpu
    return r


def rows_for(tc, obs, variant="repro", envs="abcd", **kw):
    return [row(tc, obs, e, variant, **kw) for e in envs]


def header(**bullets):
    lines = ["// # Finding (demo): a demo"]
    for k, v in bullets.items():
        lines.append(f"// - {k.replace('_', ' ')}: {v}")
    return "\n".join(lines) + "\n#include <stdio.h>\nint main(void){return 0;}\n"


def ev(rows, full=False, text="", cases=None):
    return R.evidence_for("demo.f90", text or header(), rows=rows, cases=cases or [CASE], full=full)


def run(text, rows, tcs=("cce19", "cce20"), full=False):
    return C.check("demo.f90", text, tcs, ev(rows, full, text))


def claims(vs):
    return sorted(v.claim for v in vs)


BASE = rows_for("cce19", FAIL) + rows_for("cce20", FAIL)


def test_a_control_with_a_recorded_pass_on_each_failing_compiler_is_fine():
    text = header() + "// site:\n// control: ../vendor/checks/src/other/control/demo-control.f90 one change\n// end site\n"
    rows = BASE + rows_for("cce19", OK, variant="control") \
        + rows_for("cce20", OK, variant="control")
    assert run(text, rows) == []


def test_a_control_with_no_row_on_a_compiler_is_a_violation():
    text = header() + "// site:\n// control: ../vendor/checks/src/other/control/demo-control.f90 one change\n// end site\n"
    rows = BASE + rows_for("cce19", OK, variant="control")
    vs = run(text, rows)
    assert claims(vs) == ["control ../vendor/checks/src/other/control/demo-control.f90"]
    assert "cce20" in vs[0].reason and "no recorded row" in vs[0].reason


def test_a_control_whose_recorded_row_fails_is_a_violation():
    text = header() + "// site:\n// control: ../vendor/checks/src/other/control/demo-control.f90 one change\n// end site\n"
    rows = BASE + rows_for("cce19", OK, variant="control") + rows_for("cce20", FAIL, variant="control")
    vs = run(text, rows)
    assert "the recorded row fails" in vs[0].reason


def test_a_control_only_a_campaign_file_could_hold_is_not_decided_without_results(tmp_path):
    text = header(**{"same-compiler control": "controls/nope.c (correct on the same compiler)"})
    assert run(text, BASE, full=False) == []
    vs = run(text, BASE, full=True)
    assert claims(vs) == ["control controls/nope.c"]


def test_other_families_need_a_passing_row_each():
    text = header(other_families="AFAR compiles and runs it correctly; NVHPC 25.11 rejects it")
    rows = BASE + rows_for("afar", OK)
    assert run(text, rows) == []
    assert claims(run(text, BASE)) == ["other-families afar"]


def test_other_families_ignore_hedged_and_negative_clauses():
    text = header(other_families="NVHPC not run on the reductions; GCC 16.2 fails it another way")
    assert run(text, BASE) == []


def test_explicit_versions_each_need_a_row():
    text = header(other_families="CCE 21.0.4 and AFAR run the file correctly")
    rows = BASE + rows_for("afar", OK)
    assert claims(run(text, rows)) == ["other-families cce21_4"]


def test_gate_four_environments_need_a_failing_row_in_each():
    text = header(gate="the gate's four environments (a-d)")
    rows = rows_for("cce19", FAIL, envs="abd") + rows_for("cce20", FAIL)
    vs = run(text, rows)
    assert claims(vs) == ["gate-envs cce19 mi300a-u"]
    assert "abd" in vs[0].reason


def test_gate_four_environments_hold_per_compiler_not_per_gpu():
    """A compiler confirmed in all four environments on one GPU backs the claim; a failure seen in
    only some environments on another GPU is a separate, undecided observation there."""
    text = header(gate="the gate's four environments (a-d)")
    rows = rows_for("cce19", FAIL, mode=1) + rows_for("cce19", FAIL, envs="a", mode=0) \
        + rows_for("cce19", OK, envs="bcd", mode=0)
    assert run(text, rows) == []
    vs = run(text, rows_for("cce19", FAIL, envs="ab", mode=1) + rows_for("cce19", FAIL, envs="a", mode=0))
    assert claims(vs) == ["gate-envs cce19 mi300a-c", "gate-envs cce19 mi300a-u"]


def test_gate_c_on_another_node_is_checked_where_rows_name_nodes():
    text = header(gate="a-d, (c) on another GPU")
    same = [dict(row("cce19", FAIL, e, machine="wingtip", mode=0, gpu=1), tc="gcc_sm80")
            for e in "abcd"]
    other = [dict(r, gpu=2) if r["env"] == "c" else r for r in same]
    case = dict(CASE, affected=["gcc_sm80"])
    assert claims(C.check("demo.f90", text, ("gcc_sm80",), ev(same, False, text, [case]))) == \
        ["gate-c-node gcc_sm80 a100-s"]
    assert C.check("demo.f90", text, ("gcc_sm80",), ev(other, False, text, [case])) == []


def test_same_way_needs_one_signature():
    text = header(other_families="CCE 19 and CCE 20 fail the same way")
    assert run(text, BASE) == []
    differ = rows_for("cce19", FAIL) + rows_for("cce20", FAIL2)
    vs = run(text, differ)
    assert claims(vs) == ["same-way cce19 cce20"]
    assert "2 signatures" in vs[0].reason


def test_the_same_message_with_and_without_a_bare_file_name_is_one_signature():
    """A site row prints the diagnostic after the case's file name (no directory, so the scrub
    keeps it); a harness row has the path scrubbed: one message, one signature."""
    named = "COMPILE_FAIL rc=1\nsite-x--demo.c:3:7: error: expected addressable lvalue\n"
    bare = "COMPILE_FAIL rc=1\nerror: expected addressable lvalue\n"
    text = header(other_families="CCE 19 and CCE 20 fail the same way")
    assert run(text, rows_for("cce19", named) + rows_for("cce20", bare)) == []


def test_a_bare_file_name_inside_the_diagnostic_is_not_part_of_the_signature():
    """NVFORTRAN names the file after the message, `(x.f90: 12)`: a campaign row's path is
    scrubbed away, a site row's bare file name stays; both are one signature, so a cell with
    campaign and site rows still reproduces identically in a-d (gate-cells)."""
    campaign = "COMPILE_FAIL rc=1\nNVFORTRAN-S-0034-Syntax error at or near identifier simd (<dir>/repro.f90: 12)\n"
    site = "COMPILE_FAIL rc=1\nNVFORTRAN-S-0034-Syntax error at or near identifier simd (site-fuzz--x.f90: 12)\n"
    assert R.row_signature(campaign) == R.row_signature(site)
    text = header(gate="1 of 1 cells reproduce in all four environments (a-d)")
    rows = rows_for("cce19", campaign, envs="ab") + rows_for("cce19", site, envs="cd")
    assert run(text, rows, tcs=("cce19",)) == []


def test_a_row_called_an_ice_without_a_crash_banner_is_signed_by_its_text():
    """The fuzz campaign classes NVFORTRAN's "failed to translate accelerator region" as an ICE;
    the site rows class the same message by its text (a rejection). One message, one signature,
    whatever the row's recorded class; the driver's name is not part of it."""
    msg = "NVFORTRAN-F-0155-Compiler failed to translate accelerator region (see -Minfo messages): Character local variable unsupported on device"
    campaign = f"COMPILE_FAIL rc=1\n--- compile (rc=2) ---\n{msg} (<tmpdir>/x.f90: 7)\n"
    site = f"COMPILE_FAIL rc=2\n{msg} (site-fuzz--x.f90: 51)\n"
    assert R.row_signature(campaign, "ice") == R.row_signature(site, "rejected")
    crash19 = "COMPILE_FAIL rc=1\nclang: error: unable to execute command: Aborted\n"
    crash21 = "COMPILE_FAIL rc=1\ncraycc: error: unable to execute command: Aborted\n"
    assert R.row_signature(crash19, "ice") == R.row_signature(crash21, "ice") == R.row_signature(crash21, "rejected")
    banner = "COMPILE_FAIL rc=1\nftn-7991 ftn: INTERNAL REPRO, File = x.f90, Line = 12\nftn: internal compiler error\n"
    assert R.row_signature(banner, "ice")[0] == "ice"


def test_a_scrubbed_location_before_the_message_is_not_part_of_the_signature():
    """A site row keeps `<dir>:::` where the assembler named file:line:col; the campaign row of
    the same failure has the bare message."""
    site = "COMPILE_FAIL rc=1\n<dir>:126:2: error: too few operands for instruction\n        v_bcnt_u32_b32  v0, v0\n"
    camp = ("COMPILE_FAIL rc=1\n--- compile (rc=1) ---\n<tmpdir>/ccRlCeSn.mkoffload.2.s:126:2: error: too few "
            "operands for instruction\n        v_bcnt_u32_b32  v0, v0\n")
    assert R.row_signature(site, "link") == R.row_signature(camp, "link")
    assert R.row_signature(site) == R.row_signature(camp)


def test_signature_counts_are_recomputed():
    good = header(observed="identical signature on 2 of 2 failing cells")
    bad = header(observed="identical signature on 2 of 3 failing cells")
    assert run(good, BASE) == []
    assert claims(run(bad, BASE)) == ["signature-count"]


def test_counts_are_over_the_gpus_of_the_toolchains_the_header_names():
    """A header naming gcc_g90 (GCC on Tioga's MI250X) counts GCC's MI250X cells, not the cells
    its other GPUs' rows fold into under `gcc`; naming the base takes its machine and its
    non-machine twins (gcc_g90), never the machine twins (gcc_mi300x)."""
    rows = (rows_for("gcc", FAIL, machine="tioga", mode=0) + rows_for("gcc", FAIL, machine="mi300x", mode=0)
            + rows_for("gcc", FAIL, machine="tuolumne", mode=1))
    one = header(observed="identical signature on 1 of 1 failing cells")
    assert run(one, rows, tcs=("gcc_g90",)) == []
    two = header(observed="identical signature on 2 of 2 failing cells")
    assert run(two, rows, tcs=("gcc",)) == []


def test_a_part_file_cited_by_its_machine_name_finds_the_host_named_file(tmp_path):
    """Headers name a gate part file by machine (gate_reruns.part.wingtip.501872.jsonl, host names
    are scrubbed); the file on disk carries the host (gate_reruns.part.wingtip-n1.example.org.501872)."""
    d = tmp_path / "results" / "x"
    d.mkdir(parents=True)
    f = d / "gate_reruns.part.wingtip-n1.example.org.501872.jsonl"
    f.write_text("{}\n")
    (d / "gate_reruns.part.wingtip-n1.example.org.999.jsonl").write_text("{}\n")
    assert R.named_row_files("rows results/x/gate_reruns.part.wingtip.501872.jsonl.", tmp_path) == [f]


def test_a_row_naming_a_findings_old_path_reads_the_file_where_it_is_now(tmp_path):
    """Rows recorded before the moves name docs/findings/x.c or findings/x.c; the program is
    fingerprinted from data/findings/x.c."""
    (tmp_path / "data" / "findings").mkdir(parents=True)
    prog = "int main(void) {\n  return 1;\n}\n"
    (tmp_path / "data" / "findings" / "x.c").write_text("// header\n" + prog)
    rows = [{"file": f, "toolchain": "cce19", "machine": "tuolumne", "xnack": 0, "program_id": "old-name",
             "outcome": "wrong_answer", "reason": "x"} for f in ("docs/findings/x.c", "findings/x.c")]
    got = R.campaign_obs(rows, tmp_path)
    assert [o.fp for o in got] == [R.fingerprint(prog)] * 2


def test_the_scaffolds_cell_count_is_recomputed():
    ok = header(gate="2 of 2 cells reproduce in all four environments (a-d)")
    bad = header(gate="2 of 2 cells reproduce in all four environments (a-d)")
    assert run(ok, BASE) == []
    short = rows_for("cce19", FAIL, envs="abd") + rows_for("cce20", FAIL)
    vs = run(bad, short)
    assert "gate-cells" in claims(vs)


def test_counts_over_cited_campaign_rows_need_those_rows():
    """The scaffold's counts ("N of M cells", "identical signature on N of M failing cells") are
    counts over the rows the header cites. A header that cites campaign row files under results/
    is not judged on them from the committed site rows alone (the malloc finding's flaky copy
    cell fails in 1 of 10 campaign repeats and in none of the four site runs); with results/ it is."""
    text = header(gate="1 of 2 cells reproduce in all four environments (a-d; rows "
                       "results/demo/finding_rows.jsonl)",
                  observed="identical signature on 2 of 2 failing cells")
    site_only = rows_for("cce19", FAIL)      # one failing cell in the site rows
    assert run(text, site_only) == []
    vs = run(text, site_only, full=True)
    assert claims(vs) == ["gate-cells", "signature-count"]
    uncited = header(gate="1 of 2 cells reproduce in all four environments (a-d)")
    assert claims(run(uncited, site_only)) == ["gate-cells"]


def test_a_todo_is_a_violation():
    text = header(rule="TODO(human) cite the specification")
    assert claims(run(text, BASE)) == ["todo line 2"]


def test_gcc_mentions_pick_the_install_by_the_catalog_words():
    """The words that pick a GCC install come from the catalog
    (`mention_words`, an install's and its twins'): "A100" is gcc_sm80, "MI300A" and
    "Tioga"/"MI250X"/"gfx90a" (its twin gcc_g90) gcc, anything else (the device's "PCIe", a
    lowercase "tioga38") is the whole family; the twin's id names its base, and the command
    `gcc` names no toolchain."""
    def tcs(text):
        return [m.tcs for m in H.mentions(text) if m.family == "gcc"]
    assert tcs("GCC 16.2 on the A100") == [("gcc_sm80",)]
    assert tcs("the A100 build of GCC") == [("gcc_sm80",)]
    assert tcs("GCC 16.2 (gfx90a)") == tcs("GCC 16.2 on Tioga") == [("gcc",)]
    assert tcs("GCC 16.2 on the MI300A") == tcs("GCC 16.2 on the MI350X") == [("gcc",)]
    assert tcs("GCC 16.2: PCIe") == tcs("GCC 16.2 on tioga38") == [("gcc", "gcc_sm80")]
    assert tcs("gcc_g90 fails") == [("gcc",)] and tcs("gcc -fopenmp is never evidence") == []


def test_mentions_of_every_committed_finding_equal_masters():
    """The parse of every finding header under findings as master (adfa922)
    parsed it (tests/data/finding_mentions_master.json, dumped from master's
    offload.engine.finding_header.mentions over the files' full text): the catalog's words
    restore the parser exactly. A finding added since is not in the snapshot; a release added
    since joins its family's mentions ("CCE fails" names it too), so toolchains master did not
    know are left out of the comparison."""
    root = Path(__file__).resolve().parent.parent.parent
    want = json.loads((root / "tests" / "data" / "finding_mentions_master.json").read_text())
    known = {t for parses in want.values() for _, tcs, _, _ in parses for t in tcs}
    bad = {}
    for rel, parses in want.items():
        p = root / rel
        if not p.is_file():
            continue
        got = [[m.family, [t for t in m.tcs if t in known], m.explicit, m.pos]
               for m in H.mentions(p.read_text(errors="replace"))]
        if got != parses:
            bad[rel] = [(g, w) for g, w in zip(got, parses) if g != w][:3]
    assert not bad, bad


def test_mentions_read_families_and_versions():
    ms = H.mentions("AFAR and CCE 19/20/21 pass; CCE 21.0.4 too; NVHPC 25.11, GCC 16.2 (gfx90a)")
    got = {(m.family, m.tcs) for m in ms}
    assert ("afar", ("afar",)) in got
    assert ("cce", ("cce19", "cce20", "cce21")) in got
    assert ("cce", ("cce21_4",)) in got
    assert ("nvhpc", ("nvhpc",)) in got
    assert ("gcc", ("gcc",)) in got


def test_header_parse_unfolds_bullets():
    t = "// # Finding (x): title\n// - build: a b\n//   c d\n// - expected: e\nint x;\n"
    h = H.parse(t)
    assert h.title == "title" and h.get("build") == "a b c d" and h.get("expected") == "e"


def test_a_bullet_whose_key_is_not_a_field_ends_the_last_field():
    """`- mechanism (CCE 19.0.0, gdb): ...` (a key with a dot) is a bullet of its own: its
    continuation lines do not belong to the control above it."""
    t = ("! # Finding (x): title\n! - control: ctl.f90 passes\n! - mechanism (CCE 19.0.0, gdb): the\n"
         "!   path <path>/x.f90 of it\nend\n")
    assert H.parse(t).get("control") == "ctl.f90 passes"


def test_named_row_files_follow_the_header(tmp_path):
    d = tmp_path / "results" / "x"
    d.mkdir(parents=True)
    for n in ("a1.jsonl", "a2.jsonl", "gate_c.jsonl"):
        (d / n).write_text("{}\n")
    got = R.named_row_files("rows results/x/a*.jsonl, gate_c.jsonl", tmp_path)
    assert [p.name for p in got] == ["a1.jsonl", "a2.jsonl", "gate_c.jsonl"]


def test_gate_rerun_cells_and_probe_rows_are_read(tmp_path):
    rows = [{"cell": "nested|prog-a|cce19|1", "env": "c", "node": "n2", "outcome": "rejected",
             "reason": "ice: x", "compile_log": "PLEASE submit a bug report"},
            {"file": "ctl.f90", "toolchain": "cce20", "mode": "0", "build": "ok", "rc": "0",
             "out": "wild-check: pass", "err": ""},
            {"file": "bad.f90", "toolchain": "cce20", "mode": "0", "build": "ok", "rc": "0",
             "out": "check=fail", "err": ""}]
    got = R.campaign_obs(rows, tmp_path)
    assert [(o.tc, o.env, o.node, o.pid, o.passed, o.failed) for o in got] == [
        ("cce19", "c", "n2", "prog-a", False, True),
        ("cce20", "", "", "ctl", True, False),
        ("cce20", "", "", "bad", False, True)]


def test_one_control_named_by_two_spellings_is_one_claim():
    text = header(**{"same-compiler control": "controls/c.f90 (data/findings/x/controls/c.f90)"})
    assert claims(run(text, BASE, full=True)) == ["control controls/c.f90"]


def _gate_rows(cell, nodes, tc="cce19", bad_env=None):
    out = []
    for env, node in zip("abcd", nodes):
        out.append({"cell": f"nested|prog-1|{tc}|0", "env": env, "node": node, "outcome": "rejected",
                    "reason": "ice: boom" if env != bad_env else "diagnostic: other",
                    "compile_log": "PLEASE submit a bug report" if env != bad_env else "ftn-1: ERROR unrelated"})
    return out


GATE_TEXT = ("// # Finding (n): t\n// - gate and confirmer: gate (a-d, (c) on another node; "
             "results/n/gate_reruns.jsonl) {n} confirmed\n// - programs (1): prog-1\nint x;\n")


def _gate_ev(tmp_path, rows, text):
    R._FILE_OBS.clear()          # the cache keys on mtime: a rewrite within one tick looks unchanged
    d = tmp_path / "results" / "n"
    d.mkdir(parents=True, exist_ok=True)
    (d / "gate_reruns.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return R.evidence_for("demo.c", text, rows=[], cases=[], full=True, root=tmp_path,
                          findings_dir=tmp_path)


def test_the_campaign_gate_counts_and_nodes_are_recomputed(tmp_path):
    ok = _gate_rows("x", ["n1", "n1", "n2", "n1"])
    text = GATE_TEXT.format(n=1)
    assert C.check("demo.c", text, ("cce19",), _gate_ev(tmp_path, ok, text)) == []
    wrong = GATE_TEXT.format(n=2)
    assert claims(C.check("demo.c", wrong, ("cce19",), _gate_ev(tmp_path, ok, wrong))) == ["gate-counts"]
    same = _gate_rows("x", ["n1", "n1", "n1", "n1"])
    vs = C.check("demo.c", text, ("cce19",), _gate_ev(tmp_path, same, text))
    assert "gate-c-node cce19 mi300a-c" in claims(vs)
    diff = _gate_rows("x", ["n1", "n1", "n2", "n1"], bad_env="d")
    assert claims(C.check("demo.c", text, ("cce19",), _gate_ev(tmp_path, diff, text))) == ["gate-counts"]


def test_the_campaign_gate_counts_only_the_modes_the_finding_names(tmp_path):
    copy = _gate_rows("x", ["n1", "n1", "n2", "n1"])
    unified = [dict(r, cell=r["cell"][:-1] + "1") for r in copy]
    modes = "// - toolchains and modes that fail: cce19; modes: copy; -O2\n"
    text = GATE_TEXT.format(n=1).replace("\n", "\n" + modes, 1)
    assert C.check("demo.c", text, ("cce19",), _gate_ev(tmp_path, copy + unified, text)) == []
    plain = GATE_TEXT.format(n=1)
    assert claims(C.check("demo.c", plain, ("cce19",), _gate_ev(tmp_path, copy + unified, plain))) == \
        ["gate-counts"]


def test_a_sibling_finding_named_in_the_control_line_is_not_a_control(tmp_path):
    (tmp_path / "other-finding.c").write_text("int x;\n")
    text = header(**{"same-compiler control": "other-finding.c is the sibling; controls/c.c is the control"})
    e = R.evidence_for("demo.f90", text, rows=BASE, cases=[CASE], full=True, findings_dir=tmp_path)
    assert claims(C.check("demo.f90", text, ("cce19", "cce20"), e)) == ["control controls/c.c"]


def test_the_control_rows_of_another_case_of_the_same_finding_count():
    """A finding split into several check cases (one control each): every case's control rows
    back the finding's control lines; only the finding's own case gives its repro rows."""
    split = dict(CASE, id="demo-part", control="src/demo-part-control.f90")
    rows = BASE + [dict(r, case="demo-part") for r in rows_for("cce19", OK, variant="control")
                   + rows_for("cce20", OK, variant="control") + rows_for("cce19", OK)]
    text = header() + ("// site:\n// control: ../vendor/checks/src/other/control/demo-part-control.f90 one change\n"
                       "// end site\n")
    e = R.evidence_for("demo.f90", text, rows=rows, cases=[CASE, split], full=False)
    assert C.check("demo.f90", text, ("cce19", "cce20"), e) == []
    assert all(not o.passed for o in e.repro())


def test_a_sibling_finding_in_the_findings_own_directory_is_not_a_control(tmp_path):
    (tmp_path / "oop").mkdir()
    (tmp_path / "oop" / "other-finding.f90").write_text("end\n")
    text = header(**{"same-compiler control": "other-finding.f90 is the sibling; controls/c.c is the control"})
    e = R.evidence_for("oop/demo.f90", text, rows=BASE, cases=[CASE], full=True, findings_dir=tmp_path)
    assert claims(C.check("oop/demo.f90", text, ("cce19", "cce20"), e)) == ["control controls/c.c"]


def test_campaign_rows_match_a_control_by_stem_and_a_repro_by_fingerprint(tmp_path):
    res = tmp_path / "results" / "c"
    res.mkdir(parents=True)
    prog = "#include <stdio.h>\nint main(void){puts(\"x\");return 0;}\n"
    (res / "r1.c").write_text("// first line\n" + prog)
    (res / "ctl-one.c").write_text(prog.replace("x", "y"))
    rows = []
    for tc in ("cce19", "cce20"):
        rows.append({"toolchain": tc, "machine": "tuolumne", "xnack": 1, "file": "results/c/r1.c",
                     "program_id": "r1", "outcome": "rejected", "reason": "diagnostic: bad",
                     "compile_log": "ftn-1: ERROR x", "node": "n1"})
        rows.append({"toolchain": tc, "machine": "tuolumne", "xnack": 1, "file": "results/c/ctl-one.c",
                     "program_id": "ctl-one", "outcome": "correct_on_device", "reason": "check=pass",
                     "stdout": "check=pass\n", "node": "n1"})
    (res / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    text = "// # Finding (c): t\n// - same-compiler control: ctl-one.c (rows results/c/rows.jsonl)\n" + prog
    e = R.evidence_for("demo.c", text, rows=[], cases=[], full=True, root=tmp_path,
                       findings_dir=tmp_path)
    assert {o.tc for o in e.repro() if o.failed} == {"cce19", "cce20"}
    got = e.control("ctl-one.c")
    assert {o.tc for o in got if o.passed} == {"cce19", "cce20"}
    assert C.check("demo.c", text, ("cce19", "cce20"), e) == []
    assert claims(C.check("demo.c", text, ("cce19", "cce20", "afar"), e)) == ["control ctl-one.c"]


def test_twin_rows_fold_into_their_base_on_their_own_gpu():
    """A twin's rows fold into the toolchain it is the twin of, on its own GPU: gcc_g90 into gcc
    and cce21_g90 into cce21, both on mi250x."""
    rows = [{"program": "ctl.c", "toolchain": "gcc_g90", "class": "pass", "rc": 0, "stdout": "ok"},
            {"cell": "fuzz|prog-b|cce21_g90|0", "env": "a", "node": "t1",
             "outcome": "correct_on_device", "reason": "ok"}]
    got = R.campaign_obs(rows)
    assert [(o.tc, o.target, o.pid, o.passed) for o in got] == [
        ("gcc", "mi250x", "ctl", True), ("cce21", "mi250x", "prog-b", True)]


def test_rows_of_a_twin_named_after_its_machine_are_no_header_evidence():
    """The support-table twins (afar_mi300x, gcc_mi350x: named after their machine) are evidence
    nowhere, so a finding's header counts never include their cells; gcc_g90 still is."""
    rows = [{"program": "p.c", "toolchain": tc, "class": "fail", "rc": 1, "stdout": "x"}
            for tc in ("gcc_g90", "gcc_mi300x", "afar_mi350x")]
    assert [(o.tc, o.target) for o in R.campaign_obs(rows)] == [("gcc", "mi250x")]


def test_a_campaign_row_without_a_file_is_matched_by_its_programs_source(tmp_path):
    """A campaign row names its program by id only; the campaign keeps the source in src/<id>.f90
    next to the rows, so a control with the same text (comments aside) is matched by it."""
    res = tmp_path / "results" / "oop" / "main"
    (res / "src").mkdir(parents=True)
    prog = "program p\n  print *, 'x'\nend program p\n"
    (res / "src" / "oop-fam-local.f90").write_text("! generated\n" + prog)
    rows = [{"toolchain": tc, "machine": "tuolumne", "xnack": 0, "program_id": "oop-fam-local",
             "outcome": "correct_on_device", "reason": "check=pass", "stdout": "check=pass\n"}
            for tc in ("cce19", "cce20")]
    (res / "rows.part.x.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (tmp_path / "controls").mkdir()
    (tmp_path / "controls" / "local.f90").write_text("! the control\n" + prog)
    text = ("! # Finding (oop): t\n! - same-compiler control: controls/local.f90 (results/oop/main/"
            "rows.part*.jsonl)\nprogram q\nend program q\n")
    e = R.evidence_for("demo.f90", text, rows=[], cases=[], full=True, root=tmp_path,
                       findings_dir=tmp_path)
    assert {o.tc for o in e.control("controls/local.f90") if o.passed} == {"cce19", "cce20"}
    assert C.check("demo.f90", text, ("cce19", "cce20"), e) == []


# --- A cell the stored row contradicts is not confirmed -------------------------------

def test_a_gate_cell_whose_stored_row_is_another_failure_is_not_confirmed(tmp_path):
    """The four reruns agree among themselves, but the stored run of the cell timed out: the campaign
    gate calls it nondeterministic, so the header may not count it confirmed."""
    rows = _gate_rows("x", ["n1", "n1", "n2", "n1"])
    stored = {"toolchain": "cce19", "machine": "tuolumne", "xnack": 0, "program_id": "prog-1", "file": "x.c",
              "outcome": "wrong_answer", "reason": "timeout", "stdout": "", "compile_log": "", "node": "n1",
              "flags": "-O2"}
    text = GATE_TEXT.format(n=1)
    ev = _gate_ev(tmp_path, rows, text)
    ok = C.gate_cells(ev.obs, {"prog-1"}, ("cce19",))
    assert all(v[0] for v in ok.values())
    d = tmp_path / "results" / "n"
    (d / "stored.jsonl").write_text(json.dumps(stored) + "\n")
    text2 = text.replace("results/n/gate_reruns.jsonl", "results/n/gate_reruns.jsonl, results/n/stored.jsonl")
    ev2 = R.evidence_for("demo.c", text2, rows=[], cases=[], full=True, root=tmp_path, findings_dir=tmp_path)
    got = C.gate_cells(ev2.obs, {"prog-1"}, ("cce19",))
    assert got and not any(v[0] for v in got.values()) and {v[1] for v in got.values()} == {"stored"}


# ---- Every Fortran finding is a legal free-form program: no line over 132 --------------------------------


LIMIT = 132
FINDINGS = Path(__file__).resolve().parent.parent.parent / "data" / "findings"


def test_no_finding_line_exceeds_132_characters():
    bad = []
    for p in sorted(FINDINGS.rglob("*.f90")):
        text = p.read_text(encoding="utf-8")
        for n, ln in enumerate(text.split("\n"), 1):
            if len(ln) > LIMIT:
                bad.append(f"{p.relative_to(FINDINGS)}:{n} ({len(ln)})")
    assert not bad, f"{len(bad)} lines over {LIMIT}: " + ", ".join(bad[:20])


def test_wrapped_fuzz_failure_line_parses_like_the_long_one(tmp_path, monkeypatch):
    from offload.engine.confirm import findings as F
    monkeypatch.setattr(F, "ROOT", tmp_path)
    msg = 'ice: INTERNAL COMPILER ERROR: "x" (v.c, line 5607, version <v>)'
    one = f"! toolchain: cce20 (-O2, HSA_XNACK=1)\n! failure: ice ({msg})\nend\n"
    cut = msg.index("line 5607")
    two = (f"! toolchain: cce20 (-O2, HSA_XNACK=1)\n! failure: ice ({msg[:cut - 1]}\n"
           f"!   {msg[cut:]})\nend\n")
    a, b = tmp_path / "a.f90", tmp_path / "b.f90"
    a.write_text(one)
    b.write_text(two)
    fa, fb = F._fuzz_finding(a), F._fuzz_finding(b)
    assert fa.message == fb.message and fa.sites == fb.sites


# ---- Writers of finding headers keep Fortran lines within 132 characters ------------------------------

import re

from offload.engine import expected as E
from offload.engine import fuzz_min as fm
from offload.engine import fuzz_report as fr
from offload.engine import gen
from offload.engine.confirm import draft as D
from offload.engine.confirm import findings as F

WORDS = " ".join(f"word{i}" for i in range(60))


def _short(text):
    return [ln for ln in text.split("\n") if len(ln) > LIMIT]


def test_fuzz_header_wraps_and_parses_back(tmp_path, monkeypatch):
    sig = 'ice: INTERNAL COMPILER ERROR: "' + WORDS + '" (v.c, line 9, version <v>)'
    fail = fm.Failure("cce20", "ice", sig)
    text = fr.finding_text(7, fail, "fuzz-1", "program p\nend program\n",
                           "v", WORDS, also=("cce19", "cce21"))
    assert not _short(text)
    one = text.replace("\n!   ", " ")
    monkeypatch.setattr(F, "ROOT", tmp_path)
    a, b = tmp_path / "a.f90", tmp_path / "b.f90"
    a.write_text(text)
    b.write_text(one)
    fa, fb = F._fuzz_finding(a), F._fuzz_finding(b)
    assert fa.message == fb.message == sig
    assert fa.toolchains == fb.toolchains == ("cce20", "cce19", "cce21")
    assert F.unfold(text) == one
    assert "! also fails on: cce19, cce21" in F.unfold(text)


def test_every_derivation_parses_back_after_wrapping():
    from offload.engine import hdrwrap
    for (atom, version), (value, body) in gen.derivations().items():
        src = next(iter(gen.generate([atom], version))).source
        wrapped = hdrwrap.wrap_comments(src)
        assert not [x for x in wrapped.split("\n") if x.startswith("!") and len(x) > LIMIT]
        a, b = E.derivation_evidence(src), E.derivation_evidence(wrapped)
        assert (a.value, a.detail) == (b.value, b.detail) == (value, body.strip())


def test_promote_wraps_header_lines(tmp_path):
    long = "- reason: " + WORDS + " " + WORDS
    dr = tmp_path / "d"
    dr.mkdir()
    (tmp_path / "f").mkdir()
    (dr / "finding.md").write_text(f"# Draft finding: x\n\n{long}\n\n## Evidence\n")
    (dr / "program.f90").write_text(
        "! derivation (check=pass): " + WORDS + " " + WORDS + "\n"
        "! observable: no (" + WORDS + " " + WORDS + ")\nprogram p\nend program\n")
    (dr / "result.json").write_text(json.dumps({"case": {
        "program": {"lang": "f90"}, "toolchain": "afar", "outcome": "wrong_answer",
        "mode": "unified", "arch": "gfx942"}}))
    out = D.promote(dr, "x", findings=tmp_path / "f", index=tmp_path / "i.yaml")
    text = out.read_text()
    assert not _short(text)
    assert ("! " + long) in F.unfold(text)


def test_refine_unfolds_only_keyed_continuations():
    lines = ["! toolchain: x", "! observed: a b", "!   c d", "! Legal: p", "!   q"]
    assert fr._unfold_keys(lines) == ["! toolchain: x", "! observed: a b c d",
                                      "! Legal: p", "!   q"]


def test_promote_program_header_round_trips(tmp_path):
    test_promote_wraps_header_lines(tmp_path)
    text = (tmp_path / "f" / "x.f90").read_text()
    ev = E.derivation_evidence(text.split("!\n", 1)[-1] if False else
                               "\n".join(l for l in text.split("\n") if "derivation" in l))
    assert ev.value == "check=pass" and ev.detail == WORDS + " " + WORDS
    assert "! observable: no (" + WORDS + " " + WORDS + ")" in re.sub(r"\n! (?=word)", " ", text)


# ---- tools/new_finding.py: a complete draft finding whose factual lines come from recorded rows; ---------

import importlib.util
import sys

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location("new_finding", ROOT / "tools" / "new_finding.py")
NF = importlib.util.module_from_spec(spec)
sys.modules["new_finding"] = NF
spec.loader.exec_module(NF)

from offload.engine import finding_claims as C  # noqa: E402
from offload.engine import finding_header as H  # noqa: E402
from offload.engine import finding_rows as R  # noqa: E402

PROG = ('#include <stdio.h>\nint main(void)\n{\n  int tot = 0;\n  printf("tot= %d\\n", tot);\n'
        '  printf("RESULT ran_on_host=0 check=%s\\n", tot == 16 ? "pass" : "fail");\n  return 0;\n}\n')
CTL = PROG.replace("int tot = 0;", "int tot = 16;")
ICE = "PLEASE submit a bug report to HPE\n Stack dump: clang::CodeGen::CodeGenModule::EmitGlobalDefinition\n"


def row_4(tc, prog, outcome, env=None, node="n1", xnack=0, log="", out="", machine="tuolumne"):
    d = {"toolchain": tc, "machine": machine, "xnack": xnack, "file": f"results/c/{prog}.c",
         "program_id": prog, "outcome": outcome, "reason": "ice: boom" if outcome == "rejected" else
         "ran_on_host=0 check=pass", "compile_log": log, "stdout": out, "node": node,
         "flags": "-fopenmp -O2"}
    if env:
        d["env"] = env
    return d


@pytest.fixture
def tree(tmp_path):
    res = tmp_path / "results" / "c"
    res.mkdir(parents=True)
    (res / "r1.c").write_text("// reduction\n" + PROG)
    (res / "ctl-one.c").write_text(CTL)
    (tmp_path / "data" / "findings").mkdir(parents=True)
    rows = []
    for tc in ("cce19", "cce20"):
        for xn in (1, 0):
            for env, node in zip("abcd", ("n1", "n1", "n2", "n1")):
                rows.append(row_4(tc, "r1", "rejected", env, node, xn, ICE))
    rows += [row_4("afar", "r1", "correct_on_device", out="tot= 16\nRESULT ran_on_host=0 check=pass\n"),
             row_4("cce19", "ctl-one", "correct_on_device", out="tot= 16\nRESULT ran_on_host=0 check=pass\n"),
             row_4("cce20", "ctl-one", "rejected", log="ftn-9: ERROR other")]
    (res / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return tmp_path


def draft(tree, **kw):
    args = dict(program=tree / "results" / "c" / "r1.c", campaign="demo", rows=[tree / "results" / "c" / "rows.jsonl"],
                controls=[tree / "results" / "c" / "ctl-one.c"], name="cce-c-demo-ice", root=tree)
    args.update(kw)
    return NF.generate(**args)


def test_the_draft_holds_the_facts_the_rows_give(tree):
    d = draft(tree)
    h = H.parse(d.text)
    assert "cce19 (CCE 19.0.0)" in h.get("fail") and "cce20 (CCE 20.0.2)" in h.get("fail")
    assert "unified, copy" in h.get("fail") and "afar" not in h.get("fail")
    assert "failure" in h.fields and "ice" in h.get("failure")
    assert "PLEASE submit a bug report to HPE" in h.get("observed")
    assert "identical signature on 4 of 4 failing cells" in h.get("observed")
    assert "tot= 16" in h.get("expected") and "check=pass" in h.get("expected")
    assert "4 of 4 cells reproduce in all four environments" in h.get("gate")
    assert "another node" in h.get("gate")
    assert "AFAR" in h.get("other") and "correctly" in h.get("other")
    assert "-fopenmp -O2" in h.get("build")


def test_a_control_is_claimed_only_where_a_row_passes(tree):
    d = draft(tree)
    ctl = H.parse(d.text).get("control")
    assert "ctl-one.c" in ctl and "CCE 19.0.0" in ctl
    assert "20" not in ctl.replace("ctl-one", "")      # cce20's control row fails: not claimed
    assert "cce20" in d.notes[0] or "CCE 20.0.2" in d.notes[0]


def test_only_the_judgement_items_are_left_as_todo(tree):
    d = draft(tree)
    todo = [ln for _, ln in H.todos(d.text)]
    kinds = {k for k in ("# Finding", "rule", "legality", "title:", "summary:") for ln in todo if k in ln}
    assert kinds == {"# Finding", "rule", "legality", "title:", "summary:"}
    assert len(todo) == 5
    assert all(MARK in ln for ln in todo for MARK in [H.MARK])


def test_every_factual_line_of_the_draft_is_backed_by_the_rows(tree):
    d = draft(tree)
    ev = R.evidence_for("demo/cce-c-demo-ice.c", d.text, rows=[], cases=[], full=True, root=tree,
                        findings_dir=tree / "data" / "findings")
    vs = C.check("demo/cce-c-demo-ice.c", d.text, ("cce19", "cce20"), ev)
    assert [v.claim.split()[0] for v in vs] == ["todo"] * 5, [v.reason for v in vs]


def test_a_draft_with_a_todo_fails_the_repo_checks(tree):
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import check_findings as CF
    p = tree / "data" / "findings" / "demo"
    p.mkdir(parents=True)
    (p / "x.c").write_text(draft(tree).text)
    assert CF.todo_problems(tree / "data" / "findings", [])


def test_resolving_the_todos_leaves_a_finding_that_passes(tree):
    text = draft(tree).text
    text = text.replace("TODO(human) one-sentence title", "A demo title")
    text = text.replace("TODO(human) the specification requirement, cited with version, section, page and lines",
                        "OpenMP 5.2 §5.8.3 p.150 l.1")
    text = re.sub(r"TODO\(human\)[^\n]*legality[^\n]*", "legal by reading", text)
    text = re.sub(r"(title|summary): TODO\(human\)[^\n]*", r"\1: ok", text)
    assert H.todos(text) == [], H.todos(text)


def test_without_a_passing_row_the_expected_value_is_left_to_a_human(tree):
    only_fail = [json.loads(x) for x in (tree / "results/c/rows.jsonl").read_text().splitlines()
                 if '"correct_on_device"' not in x]
    (tree / "results/c/rows.jsonl").write_text("\n".join(json.dumps(r) for r in only_fail) + "\n")
    d = draft(tree, controls=[])
    assert "TODO(human)" in H.parse(d.text).get("expected")
    assert "other" not in H.parse(d.text).fields


def test_the_observed_line_is_the_crash_banner_not_a_build_note(tree):
    rows = [json.loads(x) for x in (tree / "results/c/rows.jsonl").read_text().splitlines()]
    for r in rows:
        if r["outcome"] == "rejected" and r["program_id"] == "r1":
            r["compile_log"] = "Build config: +assertions\n" + ICE
    (tree / "results/c/rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert "PLEASE submit a bug report to HPE" in H.parse(draft(tree).text).get("observed")


def test_a_compiler_that_fails_another_way_is_not_listed_with_the_others(tree):
    rows = [json.loads(x) for x in (tree / "results/c/rows.jsonl").read_text().splitlines()]
    for r in rows:
        if r["toolchain"] == "cce20" and r["program_id"] == "r1":
            r["compile_log"] = "ftn-77: ERROR something else entirely"
    (tree / "results/c/rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    d = draft(tree, primary=["cce19"])
    h = H.parse(d.text)
    assert "cce20" not in h.get("fail") and "cce20" in h.get("other") and "another way" in h.get("other")
    assert "identical signature on 2 of 2 failing cells" in h.get("observed")
    ev = R.evidence_for("demo/x.c", d.text, rows=[], cases=[], full=True, root=tree,
                        findings_dir=tree / "data" / "findings")
    assert [v.claim.split()[0] for v in C.check("demo/x.c", d.text, ("cce19",), ev)] == ["todo"] * 5


def test_a_toolchain_whose_platform_reports_the_failure_differently_can_be_counted(tree):
    """`same`: a toolchain named with a reason counts as failing this finding's way although its
    rows carry another signature (the CUDA runtime reports GCC's unattached-pointer dereference
    as an illegal memory access, the HSA runtime as a GPU fault); the header lists it among the
    failing toolchains, says so in a `counted as this failure` bullet, and the signature count
    stays what the rows give."""
    rows = [json.loads(x) for x in (tree / "results/c/rows.jsonl").read_text().splitlines()]
    for r in rows:
        if r["toolchain"] == "cce20" and r["program_id"] == "r1":
            r["compile_log"] = "ftn-77: ERROR something else entirely"
    (tree / "results/c/rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    why = "its front end reports the same defect with another diagnostic"
    d = draft(tree, primary=["cce19"], same={"cce20": why})
    h = H.parse(d.text)
    assert "cce20" in h.get("fail") and "another way" not in h.get("other")
    assert why in h.get("counted as this failure") and "cce20" in h.get("counted as this failure")
    assert "identical signature on 2 of 4 failing cells" in h.get("observed")
    assert yaml.safe_load(d.index_entry)[0]["toolchains"] == ["cce19", "cce20"]


def test_a_repro_without_rows_is_refused(tree):
    (tree / "results/c/rows.jsonl").write_text("")
    with pytest.raises(NF.NoRows):
        draft(tree)


def test_the_index_entry_and_the_readme_row(tree):
    d = draft(tree, dir="demo")
    e = yaml.safe_load(d.index_entry)[0]
    assert e["file"] == "demo/cce-c-demo-ice.c" and e["toolchains"] == ["cce19", "cce20"]
    assert e["lang"] == "c" and e["outcome"] == "ice" and e["modes"] == ["unified", "copy"]
    assert e["arch"] == ["gfx942"] and "PLEASE submit a bug report to HPE" in e["message"]
    assert d.readme_row.startswith("| `demo/cce-c-demo-ice.c` | incorrect (compiler failure) | TODO(human)")
    assert "(cce19, cce20)" in d.readme_row


def test_a_run_time_failure_is_drafted_with_its_output(tree):
    rows = [row_4("cce19", "r1", "wrong_answer", env=e, out="tot= 4\nRESULT ran_on_host=0 check=fail\n")
            for e in "abcd"] + [row_4("afar", "r1", "correct_on_device",
                                    out="tot= 16\nRESULT ran_on_host=0 check=pass\n")]
    (tree / "results/c/rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    d = draft(tree, controls=[], dir="demo")
    assert yaml.safe_load(d.index_entry)[0]["outcome"] == "wrong_answer"
    assert "`tot= 4`" in H.parse(d.text).get("observed")


def test_write_puts_the_file_the_controls_and_the_two_entries_in_place(tree):
    fd = tree / "data" / "findings"
    (fd / "index.yaml").write_text("findings:\n  - file: a.c\n    toolchains: [afar]\n")
    (fd / "LOG.md").write_text("# Findings\n\n## Demo\n\n| file | kind | what |\n|---|---|---|\n"
                                  "| `a.c` | incorrect | old |\n\n## Other\n\ntext\n")
    d = draft(tree, dir="demo")
    NF.write(d, root=tree, readme_section="Demo")
    assert (fd / "demo" / "cce-c-demo-ice.c").read_text() == d.text
    assert (fd / "demo" / "controls" / "ctl-one.c").read_text() == CTL
    idx = yaml.safe_load((fd / "index.yaml").read_text())["findings"]
    assert [x["file"] for x in idx] == ["a.c", "demo/cce-c-demo-ice.c"]
    rd = (fd / "LOG.md").read_text()
    assert rd.index("`demo/cce-c-demo-ice.c`") < rd.index("## Other")
    assert rd.index("`demo/cce-c-demo-ice.c`") > rd.index("| `a.c`")


def test_the_site_block_names_the_control_by_a_path_that_exists(tree):
    d = draft(tree, dir="demo")
    NF.write(d, root=tree, readme_section=None)
    from offload.engine.site import header as SH
    sh = SH.parse(tree / "data" / "findings" / "demo" / "cce-c-demo-ice.c")
    assert sh.controls[0][0] == "demo/controls/ctl-one.c"


# --- A toolchain that fails with the top signature is never "another way" -------------

def _rewrite(tree, fn):
    p = tree / "results/c/rows.jsonl"
    rows = [json.loads(x) for x in p.read_text().splitlines()]
    for r in rows:
        fn(r)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_every_family_failing_with_the_top_signature_is_primary(tree):
    """No --primary: AFAR fails exactly like the CCE releases, so it is listed with them and nothing
    is said to fail 'another way'."""
    def fn(r):
        if r["toolchain"] == "afar" and r["program_id"] == "r1":
            r.update(outcome="rejected", reason="ice: boom", compile_log=ICE, stdout="")
    _rewrite(tree, fn)
    h = H.parse(draft(tree).text)
    for tc in ("afar", "cce19", "cce20"):
        assert tc in h.get("fail")
    assert "another way" not in h.get("other")
    e = yaml.safe_load(draft(tree, dir="demo").index_entry)[0]
    assert e["toolchains"] == ["afar", "cce19", "cce20"]


def test_a_named_primary_does_not_hide_an_identically_failing_release(tree):
    """--primary cce19 with cce20 failing identically: cce20 is primary too (never 'another way')."""
    h = H.parse(draft(tree, primary=["cce19"]).text)
    assert "cce19" in h.get("fail") and "cce20" in h.get("fail")
    assert "another way" not in h.get("other")


def test_a_crash_banner_is_the_signature_whatever_the_driver_is_called(tree):
    """CCE 19 reports `clang: error: unable to execute command: Aborted`, CCE 21 `craycc: error: ...`
    over the same PLEASE submit banner: one signature."""
    def fn(r):
        if r["program_id"] == "r1" and r["toolchain"] == "cce19":
            r["compile_log"] = "clang: error: unable to execute command: Aborted\n" + ICE
        if r["program_id"] == "r1" and r["toolchain"] == "cce20":
            r["compile_log"] = "craycc: error: unable to execute command: Aborted\n" + ICE
    _rewrite(tree, fn)
    h = H.parse(draft(tree).text)
    assert "cce19" in h.get("fail") and "cce20" in h.get("fail")
    assert "identical signature on 4 of 4 failing cells" in h.get("observed")


def test_a_toolchain_that_passes_in_one_mode_and_fails_in_another_says_which(tree):
    """'run the file correctly' and 'fail it another way' name the modes when one
    toolchain is in both."""
    def fn(r):
        if r["toolchain"] == "afar" and r["program_id"] == "r1":
            r.update(outcome="wrong_answer", reason="check_fail", stdout="tot= 3\nRESULT ran_on_host=0 check=fail\n",
                     xnack=0)
    _rewrite(tree, fn)
    rows = [json.loads(x) for x in (tree / "results/c/rows.jsonl").read_text().splitlines()]
    rows.append(row_4("afar", "r1", "correct_on_device", xnack=1, out="tot= 16\nRESULT ran_on_host=0 check=pass\n"))
    (tree / "results/c/rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    other = H.parse(draft(tree, primary=["cce19", "cce20"]).text).get("other")
    assert "unified" in other and "copy" in other


def test_a_crash_without_a_banner_is_one_signature_whatever_the_driver_is_called(tree):
    def fn(r):
        if r["program_id"] == "r1" and r["toolchain"] == "cce19":
            r["compile_log"] = "clang: error: unable to execute command: Aborted\n"
        if r["program_id"] == "r1" and r["toolchain"] == "cce20":
            r["compile_log"] = "craycc: error: unable to execute command: Aborted\n"
    _rewrite(tree, fn)
    h = H.parse(draft(tree).text)
    assert "cce19" in h.get("fail") and "cce20" in h.get("fail")
    assert "identical signature on 4 of 4 failing cells" in h.get("observed")


def test_a_toolchain_whose_controls_fail_too_is_not_claimed_as_this_failure(tree):
    """Another family fails with the same signature but also fails the control: its failure is not
    claimed to be the finding's (and is not described as failing 'another way' either)."""
    def fn(r):
        if r["toolchain"] == "afar" and r["program_id"] in ("r1", "ctl-one"):
            r.update(outcome="rejected", reason="ice: boom", compile_log=ICE, stdout="")
    _rewrite(tree, fn)
    rows = [json.loads(x) for x in (tree / "results/c/rows.jsonl").read_text().splitlines()]
    rows.append(row_4("afar", "ctl-one", "rejected", log=ICE))
    (tree / "results/c/rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    d = draft(tree, primary=["cce19"])
    h = H.parse(d.text)
    assert "afar" not in h.get("fail")
    assert "another way" not in h.get("other")
    assert "afar" in h.get("other") and "controls too" in h.get("other")
    assert yaml.safe_load(draft(tree, dir="demo", primary=["cce19"]).index_entry)[0]["toolchains"] == ["cce19", "cce20"]


# ---- Corpus validation of the grammar (offload.engine.corpus_check) --------------------------------------

import csv
import shutil

from offload.engine.corpus_check import (Summary, check_corpus, dg_error_lines,
                                     extract_directives, normalise)

DATA = Path(__file__).resolve().parent.parent / "data"
FIELDS = ["repo", "path", "lang", "model", "kind", "spec_dir",
          "n_directives", "directives"]


def make_corpus(tmp_path, files):
    """files: [(repo, path, kind, fixture-name-or-text)]. Returns index path."""
    root = tmp_path / "corpus"
    rows = []
    for repo, path, kind, src in files:
        dest = root / repo / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if (DATA / src).is_file():
            shutil.copy(DATA / src, dest)
        else:
            dest.write_text(src)
        rows.append({"repo": repo, "path": path, "lang": "fortran",
                     "model": "omp", "kind": kind, "spec_dir": "",
                     "n_directives": 1, "directives": ""})
    (tmp_path / "data" / "index").mkdir(parents=True)
    index = tmp_path / "data" / "index" / "corpus_index.csv"
    with open(index, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return index


def read_rows(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


# --- the brief's tests -------------------------------------------------------

def test_known_good_lines_all_parse(tmp_path):
    index = make_corpus(tmp_path, [("omp_examples", "good.f90", "fragment",
                                    "corpus_good.f90")])
    out = tmp_path / "out.csv"
    s = check_corpus(index, out)
    assert s == Summary(total=20, parsed=20, failed={}), read_rows(out)
    assert read_rows(out) == []


def test_diagnostic_lines_flagged(tmp_path):
    index = make_corpus(tmp_path, [("llvm", "diag.f90", "lit-diagnostic",
                                    "corpus_diag.f90")])
    out = tmp_path / "out.csv"
    s = check_corpus(index, out)
    rows = read_rows(out)
    # three deliberately illegal directives; the two end directives parse
    assert (s.total, s.parsed, s.diagnostic) == (5, 2, 3)
    assert s.failed == {"clause_repeated": 1, "clause_not_allowed": 1,
                        "missing_required": 1}
    assert [(r["line"], r["error_code"], r["diagnostic"]) for r in rows] == [
        ("5", "clause_repeated", "true"), ("12", "clause_not_allowed", "true"),
        ("17", "missing_required", "true")]
    assert all(r["repo"] == "llvm" and r["path"] == "diag.f90" for r in rows)


# --- extraction ------------------------------------------------------------------

def test_extract_reassembles_continuations_across_comments():
    src = ("  x = 1\n"
           "  !$omp target &   ! trailing comment\n"
           "\n"
           "  ! a plain comment between continued lines\n"
           "  !$omp& map(to: a) &\n"
           "  !$omp   map(from: b)\n"
           "  !$omp end target\n"
           "  !$ x = 2\n")
    got = extract_directives(src)
    assert [(d.line, d.fixed_form) for d in got] == [(2, False), (7, False)]
    assert got[0].text == ("  !$omp target &   ! trailing comment\n"
                           "  !$omp& map(to: a) &\n"
                           "  !$omp   map(from: b)")
    assert normalise(got[0].text) == "!$omp target map(to: a) map(from: b)"


def test_extract_fixed_form_sentinels():
    src = ("c$omp target\n"
           "*$OMP target data map(a)\n"
           "c$omp& map(b)\n"
           "      x = 1\n")
    got = extract_directives(src)
    assert [(d.line, d.fixed_form) for d in got] == [(1, True), (2, True)]
    # a fixed-form source file: every sentinel is fixed form, !$omp included
    got = extract_directives("!$omp target\n      x = 1\n", fixed_form=True)
    assert [(d.line, d.fixed_form) for d in got] == [(1, True)]


def test_normalise_folds_case_blanks_and_comments():
    assert normalise("!$OMP  TARGET   MAP(TO: A) ! c") == \
        "!$omp target map(to: a)"


# --- the summary -------------------------------------------------------------------

def test_fixed_form_out_of_slice_and_failures_counted(tmp_path):
    free = ("!$omp parallel\n"            # out of slice
            "!$omp end parallel\n"        # out of slice
            "!$omp target bogus(1)\n"     # in slice, fails
            "!$omp target teams\n"        # in slice, parses
            "!$omp end target teams\n"    # in slice, parses
            "c$omp target\n")             # fixed form in a free-form file
    index = make_corpus(tmp_path, [
        ("gcc", "a.f90", "fragment", free),
        ("gcc", "b.f", "fragment", "!$omp target\nc$omp target data\n"),
    ])
    out = tmp_path / "out.csv"
    s = check_corpus(index, out)
    assert (s.total, s.parsed) == (6, 2)
    assert s.failed == {"unknown_clause": 1, "fixed_form": 3}
    assert s.out_of_slice == 2 and s.diagnostic == 0
    rows = read_rows(out)
    assert [(r["path"], r["line"], r["error_code"], r["diagnostic"])
            for r in rows] == [("a.f90", "3", "unknown_clause", "false"),
                               ("a.f90", "6", "fixed_form", "false"),
                               ("b.f", "1", "fixed_form", "false"),
                               ("b.f", "2", "fixed_form", "false")]
    # without the slice filter the out-of-slice lines are parsed too
    s = check_corpus(index, out, slice_only=False)
    assert s.total == 8 and s.out_of_slice == 0


def test_version_specific_lines_parse_at_either_version(tmp_path):
    src = ("!$omp target_data map(to: a)\n"       # 6.0 spelling only
           "!$omp declare target to(f)\n")        # 5.2 only
    index = make_corpus(tmp_path, [("x", "v.f90", "fragment", src)])
    s = check_corpus(index, tmp_path / "out.csv")
    assert (s.total, s.parsed, s.failed) == (2, 2, {})


def test_gcc_dg_error_annotations_mark_expected_errors(tmp_path):
    src = ('!$omp target bogus(1) ! { dg-error "unknown" }\n'
           "!$omp target nowait &\n"
           "!$omp& nowait\n"
           '! { dg-error "repeated" "" { target *-*-* } .-1 }\n'
           "!$omp target nogroup\n"
           '! { dg-error "x" "" { target *-*-* } 0 }\n')
    assert dg_error_lines(src) == {1, 3}
    index = make_corpus(tmp_path, [("gcc", "e.f90", "fragment", src)])
    out = tmp_path / "out.csv"
    check_corpus(index, out)
    assert [(r["line"], r["expected_error"], r["diagnostic"])
            for r in read_rows(out)] == [("1", "true", "false"),
                                         ("2", "true", "false"),
                                         ("5", "false", "false")]


# ---- CCE ftn's split-CIF-record defect ----------------------------------------------------------------

import ast

from offload.engine import stress_exec as X

CALLS = {"mkdtemp", "TemporaryDirectory", "mkstemp", "NamedTemporaryFile"}
# interpolated values that hold no "-": integer seeds, toolchain names
SAFE = {"seed", "prog.seed", "compiler", "build_prefix(prog.id)"}


def _sources():
    for top in ("offload", "tools"):
        for p in sorted((ROOT / top).rglob("*.py")):
            yield p


def _prefixes(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name not in CALLS:
            continue
        for kw in node.keywords:
            if kw.arg == "prefix":
                yield node.lineno, kw.value


def _literal(value) -> tuple[str, list[str]]:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value, []
    if isinstance(value, ast.JoinedStr):
        text, exprs = "", []
        for part in value.values:
            if isinstance(part, ast.Constant):
                text += part.value
            else:
                exprs.append(ast.unparse(part.value))
                text += "{}"
        return text, exprs
    return "", [ast.unparse(value)]


def test_no_temp_prefix_contains_a_dash():
    bad, seen = [], 0
    for p in _sources():
        for line, value in _prefixes(p):
            seen += 1
            text, exprs = _literal(value)
            where = f"{p.relative_to(ROOT)}:{line}"
            if "-" in text or text.endswith("-"):
                bad.append(f"{where} {text!r}")
            bad += [f"{where} interpolates {e}" for e in exprs if e not in SAFE]
    assert seen > 30, seen          # the scan finds the call sites
    assert not bad, bad


def test_no_build_dir_prefix_ends_in_a_dash():
    for p in _sources():
        for line, value in _prefixes(p):
            text, _ = _literal(value)
            assert not text.endswith("-"), f"{p.relative_to(ROOT)}:{line}"


def test_stress_build_prefix_drops_the_dashes_of_the_program_id():
    # stress program ids carry size and seed as "-12-1": "st-...-12-1-" was
    # the original trigger (data/reports/fuzz-stress.md F2)
    pre = X.build_prefix("tu.plain-omp-12-1")
    assert "-" not in pre and pre.startswith("st_") and pre.endswith("_")
    assert "tu.plain_omp_12_1" in pre
    assert len(X.build_prefix("x" * 100)) <= 3 + 40 + 1


# ---- The presence checks of the copy-mode programs run ---------------------------------------------------




def _tool():
    spec = importlib.util.spec_from_file_location(
        "presence_x1", ROOT / "tools" / "campaigns" / "presence_x1.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_only_presence_checks_lose_their_guard():
    t = _tool()
    f = ("  if (.not. shared_mem) pres = pres .and. omp_target_is_present("
         "c_loc(a), omp_get_default_device()) /= 0\n"
         "  if (.not. shared_mem) pres = pres .and. all(pv == a)\n")
    out = t.unguard(f)
    assert out.splitlines()[0] == ("  pres = pres .and. omp_target_is_present("
                                   "c_loc(a), omp_get_default_device()) /= 0")
    assert out.splitlines()[1].startswith("  if (.not. shared_mem)")
    c = ("  if (!shared_mem) pres = pres && (omp_target_is_present(a, "
         "omp_get_default_device()) == 0);\n")
    assert t.unguard(c) == ("  pres = pres && (omp_target_is_present(a, "
                            "omp_get_default_device()) == 0);\n")


def test_candidates_are_the_programs_with_guarded_presence_checks():
    t = _tool()
    ids = {p.id for _, p in t.candidates()}
    assert "omp52-clause-map-delete" in ids
    assert "omp52-c-clause-map-delete" in ids
    assert all("-hostdev" not in i for i in ids)
    # The six C 5.0 ports joined the 48
    assert len(ids) == 54
    assert "omp50-c-clause-map-delete" in ids


def test_summary_keys_original_ids(tmp_path):
    import json
    t = _tool()
    rows = [{"program_id": "omp52-clause-map-alloc-presx1",
             "toolchain": "afar", "outcome": "wrong_answer"},
            {"program_id": "omp52-clause-map-alloc-presx1",
             "toolchain": "cce19", "outcome": "correct_on_device"}]
    doc = t.summary(rows, {"host": "n"})
    assert doc["programs"] == {"omp52-clause-map-alloc": {
        "afar": "wrong_answer", "cce19": "correct_on_device"}}
    assert doc["run"]["host"] == "n"


def test_summary_only_records_host_date_and_thp(tmp_path):
    import json
    t = _tool()
    out = tmp_path / "p.jsonl"
    out.write_text(json.dumps({"program_id": "x-presx1", "toolchain": "afar",
                               "outcome": "wrong_answer", "thp": "always"})
                   + "\n")
    sm = tmp_path / "s.json"
    assert t.main(["--out", str(out), "--summary", str(sm), "--summary-only",
                   "--run-host", "tuolumne1018",
                   "--run-started", "2026-10-22T07:57:18-07:00"]) == 0
    run = json.loads(sm.read_text())["run"]
    assert run["host"] == "tuolumne1018" and run["thp"] == ["always"]
    assert run["started"] == "2026-10-22T07:57:18-07:00"


# ---- NVIDIA HPC SDK 25.11 on wingtip (A100, sm_80): the toolchain ----------------------------------------

import dataclasses
import os


from offload.engine.confirm import machines as M
from offload.engine.toolchains import (TOOLCHAINS, nvidia_targets,
                                   parse_nvidia_smi, visible_nvidia)

NV = TOOLCHAINS["nvhpc"]
SMI = ("0, GPU-21f40bc2-8897-a490-d1f5-6f37c8f3bf56, 8.0, NVIDIA A100 80GB "
       "PCIe\n1, GPU-143c87a0-b219-2328-2fde-ac6dfaa85bc5, 8.0, NVIDIA A100 "
       "80GB PCIe\n")


def test_nvhpc_toolchain_is_wingtip_sm80():
    assert (NV.machine, NV.arch, NV.kind) == ("wingtip", "sm_80", "nvhpc")
    assert NV.fc.endswith("/nvfortran") and NV.cc.endswith("/nvc")
    assert NV.xnack_modes == (0, 2)
    assert M.machine_of("nvhpc").name == "wingtip"


def test_wingtip_modes_are_compile_flags():
    w = M.load()["wingtip"]
    assert w.modes == ("copy", "managed") and w.headline_mode == "copy"
    assert w.flags("copy") == "-gpu=mem:separate"
    assert w.flags("managed") == "-gpu=mem:managed"
    assert w.env("copy") == {} and w.compile_time_modes
    assert (w.row_key("copy"), w.row_key("managed")) == (0, 2)
    # measured on wingtip: no unified memory (no HMM); data, not a mode
    assert not w.has("unified")
    assert "does not support Unified Memory" in w.not_applicable["unified"]
    with pytest.raises(M.NotApplicable):
        w.flags("unified")
    assert w.scheduler["kind"] == "direct"


def test_amd_modes_stay_run_time():
    tu = M.load()["tuolumne"]
    assert not tu.compile_time_modes and tu.flags("unified") == ""
    for name in ("afar", "cce19", "cce21_g90"):
        tc = TOOLCHAINS[name]
        assert tc.for_mode(tc.xnack_modes[0]) is tc
    assert TOOLCHAINS["afar"].run_env(1) == {"HSA_XNACK": "1"}
    assert TOOLCHAINS["cce20"].run_env(0) == {"HSA_XNACK": "0"}


def test_amd_flags_unchanged():
    """Byte-identical recipes: the flags every stored AMD row records."""
    assert TOOLCHAINS["afar"].flags() == (
        "-fopenmp --offload-arch=gfx942 -L/usr/lib/gcc/x86_64-redhat-linux/8")
    assert TOOLCHAINS["cce19"].flags() == "-fopenmp"
    assert dataclasses.replace(TOOLCHAINS["cce21"], model="acc").flags() \
        == "-h acc"
    assert dataclasses.replace(TOOLCHAINS["afar_g90"], lang="c").flags() \
        == "-fopenmp --offload-arch=gfx90a"
    assert dataclasses.replace(TOOLCHAINS["cce20"], lang="c").flags() == (
        "-fopenmp -fopenmp-targets=amdgcn-amd-amdhsa "
        "-Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942")


def test_nvhpc_flags_per_mode_and_model():
    assert NV.for_mode(0).flags() == "-mp=gpu -gpu=cc80 -gpu=mem:separate"
    assert NV.for_mode(2).flags() == "-mp=gpu -gpu=cc80 -gpu=mem:managed"
    acc = dataclasses.replace(NV, model="acc").for_mode(0)
    assert acc.flags() == "-acc=gpu -gpu=cc80 -gpu=mem:separate"
    c = dataclasses.replace(NV, lang="c").for_mode(2)
    assert c.compile_cmd("a.c", "a.out").split()[0].endswith("/nvc")
    # OpenACC C (offload.engine.acc_c_gen) compiles with nvc -acc
    assert dataclasses.replace(NV, model="acc", lang="c").for_mode(
        0).flags() == "-acc=gpu -gpu=cc80 -gpu=mem:separate"
    with pytest.raises(ValueError):  # the mode must be chosen at compile
        NV.flags()
    with pytest.raises(ValueError):
        NV.for_mode(1)  # no such mode (unified is not applicable)


def test_nvhpc_run_env_selects_nothing_and_refuses_other_build():
    # no mode variable: only the release's own runtime
    assert set(NV.for_mode(2).run_env(2)) == {"LD_LIBRARY_PATH"}
    with pytest.raises(ValueError):
        NV.for_mode(0).run_env(2)
    with pytest.raises(ValueError):
        NV.run_env(1)


def test_no_openmp_version_flag_for_nvhpc():
    from offload.engine.run_matrix import for_version, version_flags
    for v in (50, 52, 60):
        assert version_flags("nvhpc", v) == ""
        assert version_flags("nvhpc", v, "c") == ""
    assert for_version(NV, 60, "c").extra == ""
    assert version_flags("afar", 60) == "-fopenmp-version=60"
    assert version_flags("cce19", 52, "c") == "-fopenmp-version=52"


def test_parse_nvidia_smi_and_visible_devices():
    gpus = parse_nvidia_smi(SMI)
    assert [g[2] for g in gpus] == ["sm_80", "sm_80"]
    assert gpus[0][3] == "NVIDIA A100 80GB PCIe"
    assert visible_nvidia(gpus, None) == gpus
    assert visible_nvidia(gpus, "1") == [gpus[1]]
    assert visible_nvidia(gpus, "GPU-143c87a0") == [gpus[1]]
    assert visible_nvidia(gpus, "") == []
    assert visible_nvidia(gpus, "1,7,0") == [gpus[1]]  # stops at invalid


def test_detect_gpu_falls_back_to_nvidia_smi(monkeypatch):
    from offload.engine import toolchains as T

    class R:
        returncode, stdout = 0, SMI
    monkeypatch.setattr(T, "_GPU", [])
    monkeypatch.setattr(T.Path, "is_file", lambda self: False)
    monkeypatch.setattr(T.subprocess, "run", lambda *a, **k: R())
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    assert T.detect_gpu() == ("sm_80", "NVIDIA A100 80GB PCIe")
    assert T.detect_gpu_count() == 1
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES")
    assert T.detect_gpu_count() == 2


def test_nvidia_targets_from_executable_bytes():
    assert nvidia_targets(b"..sm_80..\x00compute_80 sm_80 xsm_90") == \
        ["sm_80"]


def test_harness_refuses_nvhpc_on_an_amd_node(monkeypatch):
    from offload.engine import harness
    monkeypatch.setattr(harness, "detect_gpu", lambda: ("gfx942", "MI300A"))
    assert "wrong_arch" in harness.wrong_arch(NV)
    monkeypatch.setattr(harness, "detect_gpu", lambda: ("sm_80", "A100"))
    assert harness.wrong_arch(NV) is None


@pytest.mark.needs_linux("setsid")
def test_direct_scheduler_runs_detached_and_reports_state(tmp_path):
    """The no-scheduler runner behind the job interface."""
    import time
    from offload.engine.confirm import jobs as J
    s = J.scheduler_for(M.load()["wingtip"])
    assert isinstance(s, J.DirectScheduler) and s.nice == 10
    s.state_dir = str(tmp_path / "state")
    ok, bad = tmp_path / "ok.sh", tmp_path / "bad.sh"
    ok.write_text("echo hello $GREETING\n")
    bad.write_text("exit 3\n")
    out = tmp_path / "ok.log"
    j1 = s.submit(J.JobSpec(script=str(ok), minutes=1, output=str(out),
                            env={"GREETING": "there"}))
    j2 = s.submit(J.JobSpec(script=str(bad), minutes=1))
    for _ in range(100):
        if {s.status(j1), s.status(j2)} <= {"done", "failed"}:
            break
        time.sleep(0.1)
    assert (s.status(j1), s.status(j2)) == ("done", "failed")
    assert out.read_text().strip() == "hello there"
    with pytest.raises(ValueError):  # the machine's limit
        s.submit(J.JobSpec(script=str(ok), minutes=10_000))
    assert J.inside_job(M.load()["wingtip"])


def test_acc_vv_baseline_selects_fortran_tests_and_compiles_openacc(
        tmp_path):
    """OpenACCV&V (corpus/acc_vv) as a baseline: every Fortran
    test of Tests/ (no OpenMP slice filter), compiled as OpenACC with the
    suite's include file next to it; exit code decides."""
    import csv
    from pathlib import Path
    from offload.engine.baseline import read_baseline, run_baseline, \
        select_files
    from offload.engine.toolchains import Toolchain
    fakes = Path(__file__).parent.parent / "data" / "fakes"
    root = tmp_path / "corpus"
    fields = ["repo", "path", "lang", "model", "kind", "spec_dir",
              "n_directives", "directives"]
    rows = [dict(repo="acc_vv", path="Tests/a.F90", lang="fortran"),
            dict(repo="acc_vv", path="Tests/b.c", lang="c"),
            dict(repo="acc_vv", path="Template/t.F90", lang="fortran")]
    for r in rows:
        f = root / r["repo"] / r["path"]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("! fake\n")
    (root / "acc_vv" / "Tests" / "acc_testsuite.Fh").write_text("! inc\n")
    index = tmp_path / "index.csv"
    with index.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fields)
        w.writeheader()
        for r in rows:
            w.writerow({"model": "acc", "kind": "run", "spec_dir": "",
                        "n_directives": "1", "directives": "parallel", **r})
    assert [r["path"] for r in select_files(index, ["acc_vv"])] == \
        ["Tests/a.F90"]
    # the fake compiler checks the include file is next to the source and
    # echoes its flags; vendor nvhpc on a machine-less arch: flags per mode
    fc = tmp_path / "fc.sh"
    fc.write_text("#!/bin/bash\n[ -f acc_testsuite.Fh ] || exit 7\n"
                  f"exec {fakes}/fake_fc.sh - 0 {fakes}/exe_device_pass.sh "
                  '"$@"\n')
    fc.chmod(0o755)
    tc = dataclasses.replace(NV, fc=str(fc))
    out = tmp_path / "b.jsonl"
    import offload.engine.harness as H
    old = H.wrong_arch
    H.wrong_arch = lambda tc: None
    try:
        run_baseline(index, ["acc_vv"], tc, 2, out, corpus_root=root,
                     workers=1)
    finally:
        H.wrong_arch = old
    (r,) = read_baseline(out)
    assert r["status"] == "pass", r
    assert r["flags"].startswith("-acc=gpu -gpu=cc80 -gpu=mem:managed")


def test_run_lock_serialises_program_runs_not_compiles(tmp_path,
                                                        monkeypatch):
    """COMPLIANT_RUN_SLOTS=1, one program on a GPU at a time
    (threads and processes alike: a file lock); compiles do not wait."""
    import threading
    import time
    from offload.engine import harness
    monkeypatch.setenv("COMPLIANT_RUN_SLOTS", "1")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", f"t{os.getpid()}")
    monkeypatch.setattr(harness.tempfile, "gettempdir",
                        lambda: str(tmp_path))
    log = tmp_path / "log"
    prog = tmp_path / "p.sh"
    prog.write_text(f"#!/bin/bash\necho start >> {log}\nsleep 0.3\n"
                    f"echo end >> {log}\n")
    prog.chmod(0o755)
    run = f"true\nexec {prog}\n"
    ts = [threading.Thread(target=harness._execute,
                           args=(run, tmp_path, 30)) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert log.read_text().split() == ["start", "end"] * 3
    t0 = time.time()  # a compile script never takes the lock
    lock = harness._run_lock_path()
    import fcntl
    with open(lock, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        harness._execute("true\n", tmp_path, 30)
    assert time.time() - t0 < 5


def test_managed_probe_moves_only_the_probe_to_the_heap():
    """tools/campaigns/nvhpc_managed_probe.py changes the shared-memory
    probe (zc) of a copy_mode_only program and nothing else."""
    import importlib.util
    from pathlib import Path
    from offload.engine.c_gen import generate_c
    from offload.engine.gen import generate
    spec = importlib.util.spec_from_file_location(
        "mp", Path(__file__).parent.parent.parent / "tools" /
        "campaigns" /
        "nvhpc_managed_probe.py")
    mp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mp)
    f = next(p for p in generate(["omp.clause.map.to"], 52) if p.legal)
    out = mp.heap_probe(f.source, "f90")
    assert "integer, allocatable :: zc(:)" in out
    assert out.index("allocate(zc(1))") < out.index("zc = 0")
    assert out.replace("integer, allocatable :: zc(:)", "integer :: zc(1)")\
        .replace("  allocate(zc(1))\n", "") == f.source
    c = next(p for p in generate_c(["omp.clause.map.to"], 52) if p.legal)
    out = mp.heap_probe(c.source, "c")
    assert "int *zc = malloc(sizeof(int));" in out
    assert "map(to: zc[0:1])" in out and "#include <stdlib.h>" in out
    a = next(p for p in generate(["acc.directive.data"], 34) if p.legal)
    assert "allocate(zc(1))" in mp.heap_probe(a.source, "f90")


def test_confirmer_knows_nvhpc_runtime_and_ice_texts():
    """The confirmer's presence-abort, runtime-message and ICE-site
    readers know NVHPC's texts (captured on wingtip)."""
    from offload.engine.confirm.facts import PRESENCE_ABORT
    from offload.engine.confirm.findings import RUNTIME_MESSAGE, site_of
    from tests.engine.test_findings_nogpu import message
    assert PRESENCE_ABORT.search(message("nvhpc_acc_run_present"))
    assert RUNTIME_MESSAGE.search(
        "Accelerator Fatal Error: call to cuMemcpyDtoHAsync returned error "
        "700 (CUDA_ERROR_ILLEGAL_ADDRESS): Illegal address during kernel")
    line = next(ln for ln in message("nvhpc_c_ice_internal").splitlines()
                if "Internal compiler error" in ln)
    s = site_of("ice: " + line)
    assert s and s.startswith("nvhpc ") and "Internal compiler error" in s
    assert site_of("ice: x.c, line 7617") == "x.c:7617"


def test_remote_runner_reaches_wingtip_without_a_master():
    """Wingtip has no ssh master: availability is a trivial
    command, the exec gets the machine's ssh options, GPU and run lock."""
    from offload.engine.confirm import execute as X
    calls = []

    def fake(argv, **kw):
        calls.append(argv)

        class R:
            returncode, stdout, stderr = 0, "", ""
        return R()
    rr = X.RemoteRunner(M.load()["wingtip"], runner=fake)
    assert rr.available()
    assert calls[0][-2:] == ["wingtip", "true"] and "BatchMode=yes" in \
        calls[0]
    cmd = rr.command()[-1]
    assert cmd.startswith("cd /home/user/compliant && env "
                          "CUDA_VISIBLE_DEVICES=3 COMPLIANT_RUN_SLOTS=1 "
                          "nice -n 10 ")
    tio = X.RemoteRunner(M.load()["tioga"], runner=fake).command()
    assert tio[:2] == ["ssh", "tio"]  # unchanged


def test_a_file_of_openacc_directives_is_an_openacc_program(tmp_path):
    from offload.engine.confirm import programs as P
    f = tmp_path / "x.f90"
    f.write_text("program p\n!$acc shutdown\nend program p\n")
    assert P.file_ref([str(f)]).model == "acc"
    f.write_text("program p\n!$omp target\n!$omp end target\nend\n")
    assert P.file_ref([str(f)]).model == "omp"


def test_fuzz_gate_verdict_read_from_a_tuolumne_campaign(tmp_path,
                                                          monkeypatch):
    """On wingtip the fuzz legality gate (AFAR flang, gfortran on
    Tuolumne) is read from a campaign Tuolumne ran, matched by seed,
    generator, base groups and model value."""
    import json
    from offload.engine import fuzz_exec as fe
    from offload.engine.fuzz import generate
    g = generate(3, "fuzz-3", ("types",))
    rows = [{"seed": 3, "gen_version": "fuzz-3", "base": ["types"],
             "expected": g.expected, "check": "ok", "check_detail": ""},
            {"seed": 4, "gen_version": "fuzz-3", "base": ["types"],
             "expected": 1, "check": "rules", "check_detail": "x"}]
    p = tmp_path / "programs.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert fe.stored_check(g) is None  # unset: the real gate
    monkeypatch.setenv("COMPLIANT_FUZZ_CHECKS", str(p))
    c = fe.stored_check(g)
    assert c.ok and "stored gate" in c.detail
    assert fe.stored_check(generate(3, "fuzz-3", ("alloc",))) is None


def test_nvhpc269_is_a_second_release_of_the_family():
    """NVHPC 26.9 is a toolchain of its own (like the
    CCE releases), same machine, modes, family and message tables."""
    from offload.engine.toolchains import family, parse_nvhpc_cuda
    t = TOOLCHAINS["nvhpc269"]
    assert "/26.9/compilers/bin/nvfortran" in t.fc
    assert (t.machine, t.arch, t.xnack_modes) == ("wingtip", "sm_80", (0, 2))
    assert family("nvhpc269") == family("nvhpc") == "nvhpc"
    assert M.family_of("nvhpc269") == M.family_of("nvhpc") == "nvhpc"
    assert t.for_mode(2).flags() == "-mp=gpu -gpu=cc80 -gpu=mem:managed"
    assert parse_nvhpc_cuda("x -I/opt/nv/Linux_x86_64/26.9/cuda/13.0/include"
                            " y") == "13.0"


@pytest.mark.needs_results("results/expected/catalog.jsonl")
def test_nvhpc_expected_runs_are_no_records_of_their_own():
    """Results/expected/catalog.nvhpc*.xnack{0,2}.jsonl join the
    catalog record (tools/derive/expected.py nv_of); the confirmer's expected
    records never read them as records (their runs are in another mode)."""
    from offload.engine.confirm import collectors as C
    C._expected_records.cache_clear()
    assert not any(".nvhpc" in p or ".xnack" in p
                   for _, _, _, p in C._expected_records().values())


def test_each_nvhpc_release_runs_with_its_own_runtime_libraries():
    """An inherited LD_LIBRARY_PATH (wingtip's login
    environment: 25.11's lib) overrides an executable's RUNPATH, so every
    NVHPC run sets LD_LIBRARY_PATH to its own release's runtime."""
    from offload.engine.harness import run_script
    from offload.engine.toolchains import TOOLCHAINS
    for name in ("nvhpc", "nvhpc269"):
        tc = TOOLCHAINS[name]
        lib = str(Path(tc.fc).parent.parent / "lib")
        for x in (0, 2):
            assert tc.run_env(x)["LD_LIBRARY_PATH"] == lib
            assert f"export LD_LIBRARY_PATH={lib}" in run_script(
                tc.for_mode(x), "./a.out", x, True)
    assert "26.9" in TOOLCHAINS["nvhpc269"].run_env(0)["LD_LIBRARY_PATH"]


def test_nvhpc_depend_on_target_is_claimed_supported():
    """The guide supports depend
    on the target constructs "as described in 2.17.11" (in, out, inout);
    mutexinoutset and depobj are unsupported, inoutset has no claim."""
    import yaml
    claims = yaml.safe_load(open(Path(__file__).resolve().parent.parent.parent /
                                 "catalog" / "vendor_claims_generic.yaml"))
    got = {(c["toolchain"], c["atom"]): c["claim"] for c in claims["claims"]
           if c["toolchain"] in ("nvhpc", "nvhpc269")
           and c["atom"].startswith("omp.clause.depend")}
    for tc in ("nvhpc", "nvhpc269"):
        for a in ("", ".in", ".out", ".inout"):
            assert got[(tc, "omp.clause.depend" + a)] == "supported"
        assert got[(tc, "omp.clause.depend.mutexinoutset")] == "unsupported"
        assert got[(tc, "omp.clause.depend.depobj")] == "unsupported"
        assert (tc, "omp.clause.depend.inoutset") not in got


# ---- OpenMP 5.0 as a version of the catalog -----------------------------------------------------------



from offload.engine import gen, spec_text
from offload.engine.catalog import slice_atoms
from offload.engine.grammar import GrammarError, parse_directive
from offload.engine.mutate import MutantResult, body_sha
from offload.engine.report import atom_citation
from offload.engine.rules import default_rules, parse_program, violations
from offload.engine.run_matrix import for_version, version_flags
from offload.engine.toolchains import TOOLCHAINS


def src(*lines):
    return "\n".join(["program p", "implicit none",
                      "integer :: i, n, x, s, a(10)"] + list(lines)
                     + ["end program p"]) + "\n"


# --- grammar -----------------------------------------------------------------------

LATER_FORMS = [  # 5.1/5.2 syntax the 5.0 grammar rejects
    "!$omp target map(present, to: a)",
    "!$omp target map(iterator(i = 1:2), to: a(i))",
    "!$omp teams num_teams(2: 4)",
    "!$omp parallel do order(reproducible: concurrent)",
    "!$omp parallel proc_bind(primary)",
    "!$omp requires atomic_default_mem_order(acquire)",
    "!$omp target defaultmap(present: scalar)",
    "!$omp target defaultmap(to: all)",
    "!$omp task depend(inoutset: x)",
    "!$omp target update to(present: a)",
    "!$omp target uses_allocators(traits(t): a)",
    "!$omp target has_device_addr(a)",
    "!$omp declare target enter(a)",
    "!$omp target thread_limit(4)",
    "!$omp distribute order(concurrent)",
    "!$omp target teams distribute parallel do linear(i)",
]


@pytest.mark.parametrize("line", LATER_FORMS)
def test_later_forms_are_not_5_0(line):
    parse_directive(line, "fortran", 52)  # legal 5.2 syntax
    with pytest.raises(GrammarError):
        parse_directive(line, "fortran", 50)


def test_5_2_complex_modifiers_read_as_5_0_expressions():
    """allocator(...) and step(...) are expressions to the 5.0 grammar (a
    function reference), so they give the simple-modifier atoms there."""
    d = parse_directive("!$omp parallel do private(x) "
                        "allocate(allocator(omp_default_mem_alloc): x)",
                        "fortran", 50)
    assert "omp.clause.allocate.allocator_simple_modifier" in d.atoms
    assert "omp.clause.allocate.allocator" not in d.atoms
    d = parse_directive("!$omp parallel do linear(x: step(2))", "fortran", 50)
    assert "omp.clause.linear.step_simple_modifier" in d.atoms
    assert "omp.clause.linear.step" not in d.atoms


def test_5_0_forms_parse_with_their_atoms():
    d = parse_directive("!$omp declare simd(f) linear(val(x, y): 2)",
                        "fortran", 50)
    (c,) = d.clauses
    assert c.args == ["x", "y"] and "val" in c.modifiers
    assert {"omp.clause.linear.val",
            "omp.clause.linear.step_simple_modifier"} <= d.atoms
    d = parse_directive("!$omp target uses_allocators(my_alloc(my_traits))",
                        "fortran", 50)
    assert "omp.clause.uses_allocators.traits" in d.atoms
    assert d.clauses[0].args == ["my_alloc"]
    d = parse_directive("!$omp target uses_allocators(omp_default_mem_alloc)",
                        "fortran", 50)
    assert "omp.clause.uses_allocators.traits" not in d.atoms
    d = parse_directive("!$omp target map(always close to: a)", "fortran", 50)
    assert {"omp.clause.map.always", "omp.clause.map.close"} <= d.atoms


def test_5_0_slice():
    a50, a52 = set(slice_atoms(50)), set(slice_atoms(52))
    # Copyin and device_type.host are out of the device-offload
    # scope (173 and 196 with them)
    assert a50 <= a52 and len(a50) == 169 and len(a52) == 192
    delta = yaml.safe_load((gen.Path(__file__).resolve().parent.parent.parent
                            / "catalog" / "omp" / "omp50_delta.yaml")
                           .read_text())
    assert set(delta["atoms_since"]) == a52 - a50
    assert all(e["since"] in (51, 52) for e in delta["atoms_since"].values())
    assert set(delta["spelling"]) <= a50


# --- the delta catalog's citations --------------------------------------------------

DELTA_PATH = (gen.Path(__file__).resolve().parent.parent.parent / "catalog" / "omp"
              / "omp50_delta.yaml")


def _cites(delta):
    for atom, e in delta["atoms_since"].items():
        yield e["cite"], e.get("quote")
        yield e["cite50"], None
    for e in delta["spelling"].values():
        yield e["cite50"], None
        yield e["cite"], None
    for e in delta["clause_rules"]:
        yield e["cite50"], None
        yield e["cite"], None
    for e in delta["absent_rules"].values():
        yield e["cite50"], None
    for e in delta["legal50_not52"]:
        yield e["cite50"], None
        yield e["cite"], None


@pytest.mark.needs_spec
def test_delta_citations_point_into_the_spec():
    delta = yaml.safe_load(DELTA_PATH.read_text())
    assert delta["status"] == "provisional"
    secs = {}
    for cite, quote in _cites(delta):
        ver, num, page = re.fullmatch(r"OpenMP (5\.[012]) §([\w.]+), p\.(\d+)",
                                      cite).groups()
        if num.startswith("B."):  # appendix: not a numbered section
            lines = spec_text._lines(ver)
            head = [pg for pg, ln in lines if ln.startswith(num + " ")
                    and ". . ." not in ln]
            assert head and head[0] <= int(page) <= head[0] + 3, cite
            text = " ".join(ln for pg, ln in lines
                            if abs(pg - int(page)) <= 1)
            if quote:
                assert re.sub(r"\s+", "", quote) in re.sub(r"\s+", "",
                                                           text), cite
            continue
        if ver not in secs:
            secs[ver] = {s.number: s for s in
                         spec_text.sections(ver).values()}
        sec = secs[ver][num]
        assert sec.first_page <= int(page) <= sec.last_page, cite
        if quote:
            assert re.sub(r"\s+", "", quote) in re.sub(r"\s+", "", sec.text), \
                (cite, quote)


def test_delta_rule_lists_match_rules_yaml():
    delta = yaml.safe_load(DELTA_PATH.read_text())
    rules = yaml.safe_load((DELTA_PATH.parent / "rules.yaml").read_text())
    with52 = {e["id"] for e in rules["rules"] if 52 in e["spec"]
              and e.get("lang") != "c"}  # The C rules are not 5.0
    with50 = {e["id"] for e in rules["rules"] if 50 in e["spec"]
              and e.get("lang") != "c"}  # Tests/test_c50.py
    assert with50 <= with52
    assert set(delta["absent_rules"]) == with52 - with50
    assert set(delta["changed_rules"]) <= with50


@pytest.mark.needs_spec
def test_delta_document_is_current():
    import importlib.util
    path = DELTA_PATH.parent.parent.parent / "tools" / "derive" / "omp50_delta.py"
    spec = importlib.util.spec_from_file_location("omp50_delta", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.DOC_DELTA.read_text() == mod.render_delta()


# --- rules: where 5.0 and 5.2 differ ----------------------------------------------------

def _v(lines, version):
    return violations(parse_program(src(*lines), version), version)


@pytest.mark.parametrize("lines,at50,at52", [
    # inscan: 5.0 lists five constructs, target parallel do is not one
    (["!$omp target parallel do reduction(inscan, +: s)", "do i = 1, n",
      "s = s + 1", "!$omp scan inclusive(s)", "x = s", "end do"],
     ["OMP50-reduction-clause-002"], []),
    # 5.0: enter data needs a map-type, to or alloc
    (["!$omp target enter data map(tofrom: a)"],
     ["OMP50-targetenterdata-map-001"], []),
    (["!$omp target enter data map(a)"],
     ["OMP50-targetenterdata-map-001"], []),
    (["!$omp target exit data map(a)"],
     ["OMP50-targetexitdata-map-001"], []),
    # 5.0: at most one atomic_default_mem_order requires per unit
    (["!$omp requires atomic_default_mem_order(seq_cst)",
      "!$omp requires atomic_default_mem_order(seq_cst)"],
     ["OMP50-requires-clause-001"], []),
    # 5.0: an ordered clause needs perfectly nested loops
    (["!$omp parallel do ordered collapse(2)", "do i = 1, n", "x = 1",
      "do s = 1, n", "end do", "end do"],
     ["OMP50-ordered-loop-005"], []),
    # 5.0: an orphaned loop needs bind only in a procedure
    (["!$omp loop", "do i = 1, n", "end do"], [],
     ["OMP52-loop-nesting-001"]),
])
def test_rules_that_differ_between_5_0_and_5_2(lines, at50, at52):
    assert _v(lines, 50) == at50
    assert _v(lines, 52) == at52


def test_teams_sequential_loop_variable_is_not_predetermined_at_5_0():
    lines = ["!$omp target", "!$omp teams default(none) shared(a, n)",
             "do i = 1, n", "a(i) = 1", "end do", "!$omp end teams",
             "!$omp end target"]
    assert _v(lines, 50) == ["OMP50-default-dsa-001"]
    assert _v(lines, 52) == []
    listed = list(lines)
    listed[1] = "!$omp teams default(none) shared(a, n) private(i)"
    assert _v(listed, 50) == []
    # a nested parallel construct or a loop directive covers the variable
    nested = ["!$omp target", "!$omp teams default(none) shared(a, n)",
              "!$omp parallel do", "do i = 1, n", "a(i) = 1", "end do",
              "!$omp end teams", "!$omp end target"]
    assert _v(nested, 50) == []


def test_linear_modifier_on_a_loop_is_5_0_illegal():
    tree = parse_program(src("!$omp do linear(val(x))", "do i = 1, n",
                             "end do"), 50)
    assert violations(tree, 50) == ["OMP50-linear-clause-002"]
    tree = parse_program(src("!$omp do linear(x: val)", "do i = 1, n",
                             "end do"), 52)
    assert violations(tree, 52) == []


def test_every_5_0_rule_cites_the_5_0_text():
    rules = [r for r in default_rules() if r.version == 50]
    # 124 of both languages or Fortran, 20 C rules (the C 5.0 slice);
    # fortran-oop: 3 Fortran rules (type-bound procedures, type-name lists,
    # declare target procedure names)
    assert len(rules) == 147
    assert len([r for r in rules if r.lang == "c"]) == 20
    assert all(r.citation.startswith("OpenMP 5.0 §") for r in rules)


# --- generator ------------------------------------------------------------------------

def test_5_0_programs():
    progs = [p for p in gen.all_programs(50) if p.scope == "device"]
    legal = [p for p in progs if p.legal]
    assert len(legal) == 169 and len(progs) - len(legal) == 38
    assert all(p.id.startswith("omp50-") for p in progs)
    assert all("(OpenMP 5.0, free-form Fortran)" in p.source for p in progs)
    for p in progs:
        if not p.legal:
            assert p.violates.startswith("OMP50-")
    p52 = {p.primary_atom if p.legal else p.violates.split("-", 1)[1]: p
           for p in gen.all_programs(52) if p.scope == "device"}
    differ = sorted(
        k for p in progs
        if body_sha(p.source) != body_sha(
            p52[(k := p.primary_atom if p.legal
                 else p.violates.split("-", 1)[1])].source))
    assert differ == [
        "numteams-clause-001", "omp.clause.is_device_ptr",
        "omp.clause.linear.ref", "omp.clause.linear.uval",
        "omp.clause.linear.val", "omp.clause.num_teams",
        "omp.clause.use_device_addr", "omp.clause.use_device_ptr",
        "omp.clause.uses_allocators.traits", "omp.directive.target_teams",
        "omp.directive.teams", "reduction-clause-001", "teams-nesting-001",
        "teams-nesting-002", "teams-nesting-003"]


def test_5_0_program_shapes():
    def prog(atom):
        return gen._legal(atom, 50).source
    assert "linear(ref(x))" in prog("omp.clause.linear.ref")
    assert "integer, intent(in) :: x\n" in prog("omp.clause.linear.ref")
    assert "linear(val(x))" in prog("omp.clause.linear.val")
    assert "uses_allocators(my_alloc(my_traits))" in prog(
        "omp.clause.uses_allocators.traits")
    assert "num_teams(1)" in prog("omp.clause.num_teams")
    assert "(nt == 1)" in prog("omp.clause.num_teams")
    s = prog("omp.clause.is_device_ptr")
    assert "subroutine dev_kernel(pa, pb, m, hf)" in s
    assert "call dev_kernel(pa, pb, n, host_flag)" in s
    s = prog("omp.clause.use_device_addr")
    assert "has_device_addr" not in s
    assert "!$omp target data use_device_addr(a, b)" in s
    # 5.0 §2.19.1.1 p.271: no predetermined DO variable in a teams region
    assert "default(none) shared(a, b, nt, host_flag) private(i)" in prog(
        "omp.directive.teams")


def test_no_variant_for_rules_5_0_does_not_have():
    # The loop-nesting-001 variant's orphaned loop is in a declare
    # target procedure, which the 5.0 rule covers, so it has a 5.0 variant
    assert "OMP50-loop-nesting-001" in gen.VIOLATIONS
    assert "OMP50-loop-nesting-001" not in gen.NOT_GENERATABLE_WHY
    assert not [r for r in gen.VIOLATIONS if r.startswith("OMP50-")
                and r.split("-", 1)[1] in ("dnm-clause-001",
                                           "numteams-clause-002")]


# --- version flags, audit reuse, report -------------------------------------------------

def test_afar_compiles_5_0_with_the_version_flag():
    assert version_flags("afar", 50) == "-fopenmp-version=50"
    assert "-fopenmp-version=50" in for_version(TOOLCHAINS["afar"], 50).flags()
    for t in ("cce19", "cce20", "cce21"):
        assert version_flags(t, 50) == ""
        assert for_version(TOOLCHAINS[t], 50).flags() == "-fopenmp"


def _oracle_audit():
    import importlib.util
    path = DELTA_PATH.parent.parent.parent / "tools" / "campaigns" / "oracle_audit.py"
    spec = importlib.util.spec_from_file_location("oracle_audit", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_audit_reuse_copies_only_identical_bodies():
    oa = _oracle_audit()
    progs52 = {p.primary_atom: p for p in oa.audit_programs(52)}
    earlier = [MutantResult(p.id, a, 52, t, "killed", "correct_on_device",
                            "wrong_answer", "r", body_sha=body_sha(p.source))
               for a, p in progs52.items() for t in ("afar", "cce19")]
    reuse = oa.reusable(50, 52, ["afar", "cce19"], earlier)
    progs50 = {p.primary_atom: p for p in oa.audit_programs(50)}
    for atom, rs in reuse.items():
        assert body_sha(progs50[atom].source) == body_sha(
            progs52[atom].source)
        assert {r.version for r in rs} == {50}
        assert all(r.program_id == progs50[atom].id
                   and r.reused_from == progs52[atom].id for r in rs)
    assert "omp.clause.num_teams" in progs50
    assert "omp.clause.num_teams" not in reuse
    assert "omp.clause.use_device_ptr" not in reuse
    # a stale earlier result (other body) is not reused
    stale = [dataclasses.replace(r, body_sha="x") if r.primary_atom ==
             "omp.directive.target" else r for r in earlier]
    assert "omp.directive.target" not in oa.reusable(
        50, 52, ["afar", "cce19"], stale)


@pytest.mark.needs_spec
def test_5_0_atoms_cite_the_5_0_text():
    for atom in slice_atoms(50):
        cite = atom_citation(atom, 50)[0]
        assert cite.startswith("OpenMP 5.0 §") or atom.startswith(
            "omp.directive."), (atom, cite)
    assert atom_citation("omp.clause.aligned", 50)[0].startswith(
        "OpenMP 5.0 §2.9.3.1")
    assert atom_citation("omp.clause.aligned", 52)[0] == \
        "OpenMP 5.2 §5.11, p.169"


def test_support_table_csv_has_5_0_rows_and_keeps_5_2(tmp_path):
    import json
    from offload.engine.report import build_table, render_csv

    def row(pid, atom, version):
        return {"program_id": pid, "primary_atom": atom, "atoms": [atom],
                "toolchain": "afar", "xnack": 1, "opt": "-O2",
                "outcome": "correct_on_device",
                "reason": "ran_on_host=0 check=pass", "flaky": False,
                "flags": "-O2", "rocm": None, "stdout": "", "stderr": "",
                "needs": [], "evidence": "construct", "observable": True,
                "legal": True, "violates": None, "version": version,
                "thp": "always"}

    def csv(rows, name):
        m = tmp_path / name
        m.write_text("".join(json.dumps(r) + "\n" for r in rows))
        a = tmp_path / "audit.json"
        a.write_text(json.dumps({"versions": {}}))
        return render_csv(build_table(m, audit=a)).splitlines()

    r52 = row("omp52-directive-target", "omp.directive.target", 52)
    r50 = row("omp50-directive-target", "omp.directive.target", 50)
    only52 = csv([r52], "m52.jsonl")
    both = csv([r50, r52], "m.jsonl")
    assert both[0] == only52[0]  # same columns
    assert [x for x in both if ",omp52-" in x] == only52[1:]
    (line50,) = [x for x in both if ",omp50-" in x]
    assert line50.startswith("50,omp50-directive-target,")


def test_audit_reuse_states_the_flags_the_reused_results_had():
    """Reused 5.2 results were compiled without AFAR's
    5.0 flag; the settings line must say so (CCE has no version flag)."""
    oa = _oracle_audit()
    note = oa.reuse_caveat(["afar", "cce19"], [50], 52)
    assert "afar" in note and "-fopenmp-version=50" in note
    assert "5.2" in note or "version 52" in note
    assert "cce19" in note and "exact" in note
    meta = {"reused_from": 52, "reused_programs": 121, "versions": [50],
            "settings": "HSA_XNACK=0, toolchains afar, cce19 (run_matrix."
            "for_version: afar 50: -fopenmp-version=50; cce19 50: default)"}
    s = oa.settings_with_reuse(meta, ["afar", "cce19"])
    assert s.startswith(meta["settings"]) and note in s
    assert oa.settings_with_reuse(dict(meta, settings=s),
                                  ["afar", "cce19"]) == s   # idempotent
    assert oa.settings_with_reuse({"settings": "x"}, ["afar"]) == "x"
    summary = {"versions": {}, "run": {"full": True, "merged": True,
                                       "versions": [50], "reused_from": 52,
                                       "reused_programs": 121}}
    text = "\n".join(oa.render_dispositions(summary))
    assert "121 programs reuse the version 52 results" in text
    assert "-fopenmp-version=50" in text


def test_a_proposal_goes_to_proposed_with_its_rows_and_no_index_entry(tmp_path):
    """An outside contributor's finding: the program in data/findings/proposed/, its rows beside it,
    its controls in proposed/controls/, and no index or log entry (nothing publishes it)."""
    fd = tmp_path / "data" / "findings"
    fd.mkdir(parents=True)
    (fd / "index.yaml").write_text("findings: []\n")
    rows = tmp_path / "rows.jsonl"
    rows.write_text('{"toolchain": "gcc"}\n')
    ctl = tmp_path / "ctl.c"
    ctl.write_text("int main(void){return 0;}\n")
    d = NF.Draft(rel="gcc/x-rejected.c", text="// header\nint main(void){return 1;}\n", index_entry="- file: x",
                 readme_row="| x |", controls=[(str(ctl), "x-ok.c")])
    done = NF.write(d, tmp_path, proposal=True, rows=[str(rows)])
    assert (fd / "proposed" / "x-rejected.c").read_text() == d.text
    assert (fd / "proposed" / "x-rejected.rows.jsonl").read_text() == rows.read_text()
    assert (fd / "proposed" / "controls" / "x-ok.c").is_file()
    assert (fd / "index.yaml").read_text() == "findings: []\n" and len(done) == 3
