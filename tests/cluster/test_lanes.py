"""Tests of the scripts that run on wingtip, the wingtip offline lane, and the split of tests between lanes (tools/lanes/tioga_suite.py)."""


# ---- Every script that runs on wingtip (a shared host without a GPU) ------------------------------------------

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS = ROOT / "tools"
EXEMPT = {
    "tools/jobs/wingtip_cap.sh": "the cap itself",
    "tools/jobs/wingtip_capped.sh": "the one-command wrapper of the cap",
    "tools/lanes/wingtip_sync.sh": "runs on the login node (rsync over ssh); "
                             "it starts nothing on wingtip",
}
NVHPC = re.compile(r"/opt/nvidia/hpc_sdk|/fastscratch/\S*nvhpc|"
                   r"\bnvfortran\b|\bnvc\+\+|\bnvc\b|\$\{?NVHPC(?:269)?_BIN")
SOURCE = re.compile(r"^\s*(?:\.|source)\s+.*?wingtip_cap\.sh\S*(.*)$")
HARD = re.compile(r"\|\|\s*(?:exit\b|\{[^}]*\bexit\b)")
SOFT = re.compile(r"\|\|\s*(?:true\b|:)")
CAPPED_CALL = re.compile(r"^\s*(?:exec\s+)?\S*wingtip_capped\.sh\s+\S")


def code_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def runs_on_wingtip(p: Path, text: str) -> bool:
    r = rel(p)
    if "wingtip" in Path(r).name or "/wingtip/" in r:
        return True
    return any(NVHPC.search(ln) for ln in code_lines(text))


def hard_cap(text: str) -> bool:
    for ln in code_lines(text):
        m = SOURCE.match(ln)
        if m and HARD.search(m.group(1)) and not SOFT.search(m.group(1)):
            return True
        if CAPPED_CALL.match(ln):
            return True
    return False


def parent_round_script(p: Path) -> Path | None:
    """roundN/run.sh for roundN/src/<id>/compile.sh."""
    parts = p.relative_to(ROOT).parts
    if p.name != "compile.sh" or "src" not in parts:
        return None
    i = parts.index("src")
    run = ROOT.joinpath(*parts[:i], "run.sh")
    return run if run.is_file() else None


def wingtip_scripts():
    for p in sorted(TOOLS.rglob("*.sh")):
        if rel(p) in EXEMPT:
            continue
        text = p.read_text(errors="replace")
        if runs_on_wingtip(p, text):
            yield p, text


def test_the_detection_finds_the_known_wingtip_scripts():
    names = {rel(p) for p, _ in wingtip_scripts()}
    assert {"tools/jobs/run_wingtip.sh", "tools/jobs/run_wingtip_gate.sh",
            "tools/jobs/run_mfc.sh" if "tools/jobs/run_mfc.sh" in names else
            "tools/jobs/run_wingtip.sh"} <= names
    # the recorded runs under data/evidence are records, not tools: they are not scanned
    # Tuolumne scripts that only name an NVHPC toolchain are not wingtip's
    assert "tools/jobs/run_gate.sh" not in names
    assert "tools/jobs/run_regen_confirm.sh" not in names


def test_every_wingtip_script_runs_inside_the_cap():
    bad = []
    for p, text in wingtip_scripts():
        if hard_cap(text):
            continue
        parent = parent_round_script(p)
        if parent and hard_cap(parent.read_text()) and \
                "compile.sh" in parent.read_text():
            continue
        bad.append(rel(p))
    assert not bad, ("wingtip scripts without a hard cap (source "
                     "tools/jobs/wingtip_cap.sh with `|| exit 1`): " +
                     ", ".join(bad))


def test_no_script_softens_the_cap():
    soft = []
    for p in sorted(TOOLS.rglob("*.sh")):
        for ln in code_lines(p.read_text(errors="replace")):
            m = SOURCE.match(ln)
            if m and (SOFT.search(m.group(1)) or not HARD.search(
                    m.group(1))):
                soft.append(f"{rel(p)}: {ln.strip()}")
    assert not soft, "\n".join(soft)


def test_hard_cap_reading():
    assert hard_cap('. "$(dirname "$0")/wingtip_cap.sh" || exit 1\n')
    assert hard_cap('. x/wingtip_cap.sh || { echo no >&2; exit 1; }\n')
    assert not hard_cap('. "$(dirname "$0")/wingtip_cap.sh"\n')
    assert not hard_cap('. x/wingtip_cap.sh 2>/dev/null || true\n')
    assert not hard_cap('# . x/wingtip_cap.sh || exit 1\n')
    assert hard_cap('exec tools/jobs/wingtip_capped.sh bash run.sh\n')


SSH_ARGV = re.compile(r"""\[\s*["']ssh["']|["']ssh["']\s*,|["']ssh\s""")
CAP_REF = re.compile(r"capped\(|wingtip_capped|get\(\s*[\"']cap[\"']\s*\)|"
                     r"\[\s*[\"']cap[\"']\s*\]")


def test_every_python_ssh_caller_routes_through_the_cap():
    """Found by a scan, not by name. Every module under
    offload/engine/ and tools/ that builds an ssh command line (an argv
    starting with "ssh", or a string "ssh ...") reads the machine's cap
    (catalog/machines.yaml access.cap) or calls wingtip_capped.sh."""
    found, bad = [], []
    for p in sorted(list((ROOT / "offload" / "engine").rglob("*.py")) +
                    list(TOOLS.rglob("*.py"))):
        code = "\n".join(ln for ln in p.read_text(errors="replace")
                         .splitlines() if not ln.lstrip().startswith("#"))
        if SSH_ARGV.search(code):
            found.append(rel(p))
            if not CAP_REF.search(code):
                bad.append(rel(p))
    assert "offload/engine/confirm/execute.py" in found and \
        "offload/engine/confirm/witness.py" in found
    assert not bad, bad


def test_python_ssh_commands_to_wingtip_run_inside_the_cap():
    """The confirmer's remote runs and the legality witness reach wingtip
    over ssh from Python: their command lines go through the cap too."""
    from offload.engine.confirm import execute as X
    from offload.engine.confirm import machines as M
    from offload.engine.confirm import witness as W
    m = M.load()["wingtip"]
    assert m.access["cap"] == "tools/jobs/wingtip_capped.sh"
    assert (ROOT / m.access["cap"]).is_file()
    cmd = X.RemoteRunner(m, runner=lambda *a, **k: None).command()[-1]
    assert " tools/jobs/wingtip_capped.sh " in cmd and cmd.index(
        "wingtip_capped.sh") < cmd.index("confirm.py exec")
    line = W.remote_command(m, "nvc -c", "t.c")
    assert f"{m.access['root']}/tools/jobs/wingtip_capped.sh nvc -c t.c" in line
    # a machine without a cap is unchanged
    tio = M.load()["tioga"]
    assert "wingtip_capped" not in X.RemoteRunner(
        tio, runner=lambda *a, **k: None).command()[-1]


def _run_cap(tmp_path, home_has_user_dir, slice_file, host):
    import subprocess
    home = tmp_path / "home"
    if home_has_user_dir:
        (home / ".config" / "systemd" / "user").mkdir(parents=True)
    else:
        home.mkdir(parents=True)
    if slice_file:
        (home / ".config" / "systemd" / "user" / "compliant.slice").write_text(
            "[Slice]\n")
    script = tmp_path / "s.sh"
    script.write_text(f'. "{TOOLS}/jobs/wingtip_cap.sh" || exit 7\necho RAN\n')
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home),
           "COMPLIANT_HOSTNAME": host}
    a = subprocess.run(["bash", str(script)], env=env, capture_output=True,
                       text=True, timeout=60)
    b = subprocess.run(["bash", str(TOOLS / "jobs" / "wingtip_capped.sh"), "echo",
                        "RAN"], env=env, capture_output=True, text=True,
                       timeout=60)
    return a, b


def test_the_cap_refuses_to_run_uncapped_on_wingtip(tmp_path):
    """On wingtip (host wingtip*, or ~/.config/systemd/user)
    without the slice file both cap scripts fail instead of running the
    work uncapped; elsewhere they stay no-ops."""
    for has_dir, host in ((False, "wingtip3"), (True, "tuolumne1001")):
        a, b = _run_cap(tmp_path / f"{has_dir}{host}", has_dir, False, host)
        assert a.returncode == 7 and "RAN" not in a.stdout, a
        assert b.returncode == 1 and "RAN" not in b.stdout, b
        assert "refusing to run uncapped" in a.stderr + b.stderr
    a, b = _run_cap(tmp_path / "off", False, False, "tuolumne1001")
    assert (a.returncode, a.stdout.strip()) == (0, "RAN")
    assert (b.returncode, b.stdout.strip()) == (0, "RAN")


# ---- The wingtip offline lane (tools/lanes/wingtip_offline.sh) ---------------------------------------

import where
import importlib.util
import os
import shutil
import subprocess
import sys
import time

import pytest
import yaml

sys.path[:0] = [str(TOOLS / a) for a in ("lanes", "jobs", "dataenv", "wild", "campaigns", "derive", "site", "repo")] + [str(TOOLS)]
import wingtip_offline as WO  # noqa: E402
import wingtip_suite as WS  # noqa: E402


def _tool(name):
    spec = importlib.util.spec_from_file_location(f"_wo_{name}",
                                                  where.tool(f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rel_2(p) -> str:
    return str(Path(p).relative_to(ROOT))


# --- the manifest ----------------------------------------------------------

def test_the_manifest_is_well_formed():
    # a clone without results/ has no step inputs to match
    assert [e for e in WO.check() if (ROOT / "results").is_dir() or not e.endswith("matches nothing")] == []
    data = WO.load()
    assert data["host"] == "wingtip"
    assert data["data_root"].startswith("/scratch/")
    for name in data["steps"]:
        s = WO.step(name, data)
        assert s["doc"] and s["cmd"] and s["limit"] > 0


@pytest.mark.needs_results("results/confirm/batch_full.jsonl")
def test_every_step_input_exists_in_the_tree():
    data = WO.load()
    for name in data["steps"]:
        files, missing = WO.expand(WO.step(name, data)["inputs"])
        assert not missing, (name, missing)
        # the shared inputs are git-ignored measurements, never the
        # sealed set
        assert not [f for f in files if f.startswith(
            ("results/fresh2", "data/bench/fresh2"))], name


def test_outputs_land_where_the_tuolumne_steps_write():
    from offload.engine.confirm import backlog as B
    from offload.engine.confirm import findings as FI
    from offload.engine.confirm import triage as T
    from offload.engine.confirm import validate as V
    cf = _tool("confirm")
    rg = _tool("regenerate")
    cbc = _tool("confirm_batch_changes")
    C = ROOT / "results" / "confirm"
    want = {
        "confirm-backlog": [B.DOC],
        "confirm-index": [FI.INDEX],
        "confirm-triage": [T.OUT, cf.TRIAGE_DOC, cf.UPSTREAM],
        "confirm-validate": [V.OUT, V.DOC, C / "validation_nvhpc.jsonl"],
        "confirm-decide": [C / "batch_s1.final.jsonl"],
        "confirm-batch": [C / "batch_full.jsonl", C / "batch_s1.jsonl",
                          C / "batch_s1.final.jsonl", rg.STAMP, cbc.TSV],
        "widen-batch": [C / "batch_widen.jsonl", rg.WIDEN_STAMP, cbc.TSV],
        "tests": [ROOT / "results" / "offline" / "suite"],
    }
    data = WO.load()
    for name, paths in want.items():
        outs = [WO.subst(o, {}) for o in WO.step(name, data)["outputs"]]
        for p in paths:
            assert rel_2(p) in outs, (name, rel_2(p), outs)
    # every output is a tree path the pull maps back: results/ outputs
    # into results/, the others into this tree (tracked files)
    tracked = set(subprocess.run(["git", "ls-files"], cwd=ROOT,
                                 capture_output=True, text=True)
                  .stdout.split()) if (ROOT / ".git").exists() else None
    for name in data["steps"]:
        for o in WO.step(name, data)["outputs"]:
            o = WO.subst(o, {})
            if o.split("/")[0] in WO.SHARED:
                continue
            if tracked is not None:
                assert o in tracked, (name, o)


def test_the_regenerate_scripts_write_what_the_manifest_pulls():
    """The batch scripts' own output paths are in the manifest."""
    text = (TOOLS / "jobs" / "run_regen_confirm.sh").read_text()
    for frag in ("batch_full.jsonl", "batch_s1.jsonl",
                 "batch_s1.final.jsonl", "pre-$TAG.jsonl",
                 "$D/$TAG.full.jsonl"):
        assert frag in text
    outs = WO.step("confirm-batch")["outputs"]
    assert "results/confirm/shards/${TAG:-regen}.*" in outs
    assert "results/confirm/batch_full.pre-${TAG:-regen}.jsonl" in outs
    assert 'TAG=${TAG:-regen}' in text and "D=results/confirm/shards" in text
    w = (TOOLS / "jobs" / "run_widen_confirm.sh").read_text()
    assert "TAG=${TAG:-widen}" in w and "batch_widen.pre-$TAG.jsonl" in w
    assert "results/confirm/batch_widen.pre-${TAG:-widen}.jsonl" in \
        WO.step("widen-batch")["outputs"]


def test_expand_and_under(tmp_path):
    (tmp_path / "results" / "a").mkdir(parents=True)
    (tmp_path / "results" / "a" / "x.jsonl").write_text("1")
    (tmp_path / "results" / "a" / "y.jsonl").write_text("2")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "d.md").write_text("3")
    files, missing = WO.expand(["results/a/*.jsonl", "docs/d.md",
                                "results/none.jsonl", "?results/opt.jsonl",
                                "?results/b/*"], tmp_path)
    assert files == ["docs/d.md", "results/a/x.jsonl", "results/a/y.jsonl"]
    assert missing == ["results/none.jsonl"]
    assert WO.under(files, "results") == ["a/x.jsonl", "a/y.jsonl"]
    assert WO.under(files, None) == ["docs/d.md"]
    # a whole shared directory (spec) is its root
    assert WO.under(["spec", "spec/openmp/x.pdf"], "spec") == [
        ".", "openmp/x.pdf"]
    assert WO.subst("r/${TAG:-regen}.*", {}) == "r/regen.*"
    assert WO.subst("r/${TAG:-regen}.*", {"TAG": "t50"}) == "r/t50.*"


def test_shell_lines_quote_the_command():
    data = {"defaults": {"limit": 60}, "steps": {"s": {
        "doc": "d", "cmd": ["bash", "-c", "echo 'a b' && true"],
        "env": ["TAG"]}}}
    out = WO.shell("s", data)
    ns = subprocess.run(["bash", "-c", out + 'printf "%s|" "$LIMIT" '
                         '"$ENV_OK" "${CMD[@]}"'], capture_output=True,
                        text=True).stdout
    assert ns == "60|TAG|bash|-c|echo 'a b' && true|"


# --- trace report ----------------------------------------------------------

def test_relative_paths_follow_each_process_cwd(tmp_path):
    """A child forked after its parent's chdir starts there; its own
    chdir moves it; a relative lookup is judged against that directory."""
    lane = "/home/u/lane"
    (tmp_path / "t.10").write_text(
        'openat(AT_FDCWD, "results/a.jsonl", O_RDONLY) = 3\n'
        'chdir("/tmp/work") = 0\n'
        'clone3({flags=CLONE_VM, exit_signal=SIGCHLD}, 88) = 11\n'
        f'chdir("{lane}/sub") = 0\n'
        'clone(child_stack=NULL, flags=SIGCHLD) = 12\n')
    (tmp_path / "t.11").write_text(
        'newfstatat(AT_FDCWD, "results", 0x1, 0) = -1 ENOENT (No such file '
        'or directory)\n'
        f'chdir("{lane}") = 0\n'
        'openat(AT_FDCWD, "results/b.jsonl", O_RDONLY) = 3\n')
    (tmp_path / "t.12").write_text(
        'openat(AT_FDCWD, "../results/c.jsonl", O_RDONLY) = 3\n')
    t = WO.traced_paths(tmp_path, lane)
    assert t["read"] == {"results/a.jsonl", "results/b.jsonl",
                         "results/c.jsonl"}
    assert t["missing"] == set()


def test_the_trace_report_names_unlisted_reads(tmp_path):
    lane, data = "/home/u/lane", "/fs/data"
    (tmp_path / "t.100").write_text(
        f'openat(AT_FDCWD, "{lane}/results/support_table.csv", O_RDONLY'
        '|O_CLOEXEC) = 3\n'
        f'openat(AT_FDCWD, "{lane}/results/gate/verdicts.jsonl", O_RDONLY)'
        ' = 4\n'
        f'openat(AT_FDCWD, "{data}/results/confirm/x.jsonl", O_RDONLY) = 5\n'
        f'newfstatat(AT_FDCWD, "{lane}/results/expected/c1.jsonl", '
        '0x7ff, 0) = -1 ENOENT (No such file or directory)\n'
        f'openat(AT_FDCWD, "{lane}/tools/x.py", O_RDONLY) = 6\n'
        f'openat(AT_FDCWD, "{lane}/results/fuzz", O_RDONLY|O_DIRECTORY) = 7\n'
        f'newfstatat(AT_FDCWD, "{lane}/spec/openmp-5.2.pdf", {{st_mode=S_IFREG'
        '|0644, st_size=5, ...}, 0) = 0\n'
        f'newfstatat(AT_FDCWD, "{lane}/results/fuzz/b1", {{st_mode=S_IFDIR'
        '|0755, st_size=5, ...}, 0) = 0\n'
        'openat(AT_FDCWD, "results/rel.jsonl", O_RDONLY) = 8\n'
        'execve("/usr/bin/gfortran", ["gfortran"], 0x1 /* 3 vars */) = 0\n'
        'execve("/usr/local/bin/gfortran", ["gfortran"], 0x1) = -1 ENOENT\n')
    data_m = {"steps": {"s": {"doc": "d", "cmd": ["x"], "limit": 1,
                              "inputs": ["results/support_table.csv",
                                         "results/fuzz/*/programs.jsonl"],
                              "outputs": ["results/confirm/x.jsonl"]}}}
    r = WO.trace_report("s", tmp_path, lane, data, data=data_m)
    assert r["unlisted_reads"] == ["results/gate/verdicts.jsonl",
                                   "results/rel.jsonl", "spec/openmp-5.2.pdf"]
    assert r["missing_lookups"] == ["results/expected/c1.jsonl"]
    assert r["exec"] == ["/usr/bin/gfortran"]
    assert WO.covered("results/fuzz/b1/programs.jsonl",
                      ["results/fuzz/*/programs.jsonl"])
    assert WO.covered("results/a/b/c", ["results/a"])
    assert not WO.covered("results/ab", ["results/a"])
    # back here: a file absent there but present in this tree is a gap
    (tmp_path / "tree" / "results" / "expected").mkdir(parents=True)
    (tmp_path / "tree" / "results" / "expected" / "c1.jsonl").write_text("")
    assert WO.trace_gaps(r, tmp_path / "tree") == [
        "read, not in the manifest: results/gate/verdicts.jsonl",
        "read, not in the manifest: results/rel.jsonl",
        "read, not in the manifest: spec/openmp-5.2.pdf",
        "looked up, absent there, present here: results/expected/c1.jsonl"]


# --- the orchestrator: dry run and refusal -----------------------------------

def _fake(tmp_path, name, body):
    p = tmp_path / name
    p.write_text("#!/bin/bash\n" + body)
    p.chmod(0o755)
    return p


def _env(tmp_path, **kw):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "HOME": str(tmp_path / "home"), "TMPDIR": str(tmp_path),
           "COMPLIANT_HOSTNAME": "tuolumne1001",
           "WINGTIP_OFFLINE_PY": sys.executable}
    (tmp_path / "home").mkdir(exist_ok=True)
    env.update(kw)
    return env


@pytest.mark.needs_results("results/confirm/batch_full.jsonl")
def test_the_dry_run_plans_without_contacting_wingtip(tmp_path):
    calls = tmp_path / "calls"
    ssh = _fake(tmp_path, "ssh", f'echo ssh "$@" >> {calls}; exit 1\n')
    rsync = _fake(tmp_path, "rsync", f'echo rsync "$@" >> {calls}; exit 1\n')
    r = subprocess.run(["bash", str(TOOLS / "lanes" / "wingtip_offline.sh"),
                        "--dry-run", "site-inputs"], cwd=ROOT,
                       env=_env(tmp_path, WINGTIP_OFFLINE_SSH=str(ssh),
                                WINGTIP_OFFLINE_RSYNC=str(rsync)),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert "command  python3 -I tools/site/site_inputs.py" in r.stdout
    assert "  < results/dash/atoms.json" in r.stdout
    assert "  > site/inputs/citations.json" in r.stdout
    assert "dry run: nothing copied or run" in r.stdout
    assert not calls.exists()


def test_an_unknown_step_is_a_usage_error(tmp_path):
    r = subprocess.run(["bash", str(TOOLS / "lanes" / "wingtip_offline.sh"),
                        "--dry-run", "no-such-step"], cwd=ROOT,
                       env=_env(tmp_path), capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 2 and "unknown step" in r.stderr


@pytest.mark.needs_results("results/confirm/batch_full.jsonl")
def test_it_refuses_when_wingtip_has_no_cap(tmp_path):
    """The pre-flight finds no compliant.slice: nothing is copied or run."""
    calls = tmp_path / "calls"
    ssh = _fake(tmp_path, "ssh", f'echo ssh "$@" >> {calls}\n'
                'echo "ENV_OK"; exit 0\n')       # no CAP_OK
    rsync = _fake(tmp_path, "rsync", f'echo rsync "$@" >> {calls}\n')
    r = subprocess.run(["bash", str(TOOLS / "lanes" / "wingtip_offline.sh"),
                        "site-inputs"], cwd=ROOT,
                       env=_env(tmp_path, WINGTIP_OFFLINE_SSH=str(ssh),
                                WINGTIP_OFFLINE_RSYNC=str(rsync)),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 1
    assert "refused" in r.stderr and "compliant.slice" in r.stderr
    lines = calls.read_text().splitlines()
    assert len(lines) == 1 and "compliant.slice" in lines[0]
    assert not [x for x in lines if x.startswith("rsync")]


# --- the wingtip half -------------------------------------------------------

def _lane(tmp_path, manifest: dict):
    """A lane: the runner, the cap, the manifest module and a manifest."""
    lane = tmp_path / "lane"
    (lane / "tools").mkdir(parents=True)
    (lane / "tools" / "jobs").mkdir()
    (lane / "tools" / "lanes").mkdir()
    for f in ("lanes/wingtip_offline_run.sh", "jobs/wingtip_cap.sh",
              "lanes/wingtip_offline.py"):
        shutil.copy(TOOLS / f, lane / "tools" / f)
    (lane / "tools" / "lanes" / "wingtip_offline.yaml").write_text(
        yaml.safe_dump(manifest))
    data = tmp_path / "data"
    (data / "env" / "bin").mkdir(parents=True)
    (data / "env" / "bin" / "python").symlink_to(sys.executable)
    (data / "env" / "bin" / "python3").symlink_to(sys.executable)
    return lane, data


MAN = {"host": "wingtip", "data_root": "/x", "lane_root": "/y",
       "defaults": {"limit": 60},
       "steps": {"echo": {"doc": "d", "limit": 3, "env": ["SLEEP"],
                          "cmd": ["bash", "-c",
                                  'echo "hi $1" > out.txt; '
                                  'echo r > results/r.txt; '
                                  'sleep "${SLEEP:-0}"', "x"],
                          "outputs": ["out.txt", "results/r.txt",
                                      "results/never.txt"]},
                 "afar": {"doc": "d", "limit": 30, "outputs": ["out.txt"],
                          "cmd": ["bash", "-c", "echo x > out.txt; "
                                  "/no/such/afar/amdflang -v; exit 0"]},
                 "probe": {"doc": "d", "limit": 30, "exec_guard": False,
                           "cmd": ["bash", "-c",
                                   "/no/such/afar/amdflang -v; exit 0"]}}}


def _run(lane, data, tmp_path, *args, home=None, host="tuolumne1001"):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "HOME": str(home or tmp_path / "home"),
           "COMPLIANT_HOSTNAME": host, "WINGTIP_OFFLINE_DATA": str(data)}
    Path(env["HOME"]).mkdir(exist_ok=True)
    return subprocess.run(["bash", str(lane / "tools" /
                                       "lanes" /
                                       "wingtip_offline_run.sh"), *args],
                          env=env, capture_output=True, text=True,
                          timeout=120)


def test_the_runner_runs_a_step_and_lists_its_outputs(tmp_path):
    lane, data = _lane(tmp_path, MAN)
    r = _run(lane, data, tmp_path, "--prepare")
    assert r.returncode == 0, r.stderr
    assert (lane / "results").resolve() == (data / "results").resolve()
    r = _run(lane, data, tmp_path, "echo", "arg")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (lane / "out.txt").read_text() == "hi arg\n"
    assert (data / "results" / "r.txt").is_file()
    assert (lane / ".offline" / "outputs.list").read_bytes() == \
        b"out.txt\0results/r.txt\0"
    assert "limit 3 s" in r.stdout and "exit 0 after" in r.stdout


def test_the_runner_kills_a_step_at_its_limit(tmp_path):
    lane, data = _lane(tmp_path, MAN)
    _run(lane, data, tmp_path, "--prepare")
    t0 = time.time()
    r = _run(lane, data, tmp_path, "--env", "SLEEP=60", "echo")
    assert r.returncode == 124 and time.time() - t0 < 30
    r = _run(lane, data, tmp_path, "--env", "OTHER=1", "echo")
    assert r.returncode == 2 and "does not take OTHER" in r.stderr


def _traced() -> bool:
    try:
        return any(ln.split()[1] != "0" for ln in
                   Path("/proc/self/status").read_text().splitlines()
                   if ln.startswith("TracerPid:"))
    except OSError:
        return False


@pytest.mark.skipif(not shutil.which("strace") or _traced(),
                    reason="needs strace, and not to be traced already")
def test_the_guard_fails_a_step_that_runs_a_missing_program(tmp_path):
    """A step that tries to run what wingtip does not have (an AFAR front
    end) fails with 3 and its outputs are not listed for the pull; a step
    with exec_guard false only reports it."""
    lane, data = _lane(tmp_path, MAN)
    _run(lane, data, tmp_path, "--prepare")
    r = _run(lane, data, tmp_path, "afar")
    assert r.returncode == 3, r.stdout + r.stderr
    assert "/no/such/afar/amdflang" in r.stderr
    assert "belongs on Tuolumne" in r.stderr
    r = _run(lane, data, tmp_path, "probe")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "/no/such/afar/amdflang" in r.stderr
    r = _run(lane, data, tmp_path, "echo")
    assert r.returncode == 0 and "tried to run" not in r.stderr


def test_exec_report_names_programs_missing_everywhere(tmp_path):
    (tmp_path / "exec").write_text(
        '5 execve("/usr/local/bin/git", ["git"], 0x1) = -1 ENOENT (No such '
        'file or directory)\n'
        '5 execve("/usr/bin/git", ["git"], 0x1) = 0\n'
        '6 execve("/p/afar/bin/amdflang", ["amdflang"], 0x1) = -1 ENOENT '
        '(No such file or directory)\n'
        '7 execve("/usr/bin/python3", ["python3"], 0x1) = 0\n')
    (tmp_path / "exec2").write_text(
        '8 execve("/usr/bin/gfortran", ["gfortran"], 0x1) = 0\n'
        '8 execve("/usr/libexec/gcc/x86_64-linux-gnu/13/f951", ["f951"], '
        '0x1) = 0\n'
        '9 execve("/usr/bin/git", ["git"], 0x1) = 0\n')
    assert WO.exec_report(tmp_path) == [
        "tried to run /p/afar/bin/amdflang, which this host does not have",
        "ran the compiler /usr/bin/gfortran, which differs from Tuolumne's",
        "ran the compiler /usr/libexec/gcc/x86_64-linux-gnu/13/f951, which "
        "differs from Tuolumne's"]
    for name in ("amdflang", "amdclang++", "flang-new", "clang-21",
                 "gcc-13", "cc1plus", "nvfortran"):
        assert WO.COMPILER.match(name), name
    for name in ("git", "python3", "bash", "date", "seq", "ldd"):
        assert not WO.COMPILER.match(name), name


def test_the_runner_refuses_on_wingtip_without_the_slice(tmp_path):
    lane, data = _lane(tmp_path, MAN)
    home = tmp_path / "wingtip-home"
    (home / ".config" / "systemd" / "user").mkdir(parents=True)
    r = _run(lane, data, tmp_path, "echo", home=home, host="wingtip3")
    assert r.returncode == 1
    assert "refusing to run uncapped" in r.stderr
    assert not (lane / "out.txt").exists()
    assert not (lane / ".offline").exists()


def test_prepare_prunes_files_no_longer_in_the_tree(tmp_path):
    lane, data = _lane(tmp_path, MAN)
    (lane / "old.py").write_text("x")
    (lane / "tools" / "__pycache__").mkdir()
    (lane / "tools" / "__pycache__" / "a.pyc").write_text("x")
    (lane / ".offline").mkdir()
    keep = ["tools/lanes/wingtip_offline_run.sh", "tools/jobs/wingtip_cap.sh",
            "tools/lanes/wingtip_offline.py", "tools/lanes/wingtip_offline.yaml"]
    (lane / ".offline" / "files.list").write_bytes(
        b"".join(k.encode() + b"\0" for k in keep))
    (data / "results").mkdir()
    (data / "results" / "kept.jsonl").write_text("x")
    r = _run(lane, data, tmp_path, "--prepare")
    assert r.returncode == 0, r.stderr
    assert "pruned old.py" in r.stdout and not (lane / "old.py").exists()
    assert (lane / "tools" / "__pycache__" / "a.pyc").exists()
    assert (lane / "results" / "kept.jsonl").exists()
    assert all((lane / k).exists() for k in keep)


def test_the_lane_scripts_are_capped():
    for f in ("wingtip_offline.sh", "wingtip_offline_run.sh"):
        assert hard_cap((TOOLS / "lanes" / f).read_text()), f


# --- the suite runner -------------------------------------------------------

def test_the_suite_reads_junit_and_splits_the_work(tmp_path):
    (tmp_path / "j.xml").write_text(
        '<testsuites><testsuite>'
        '<testcase classname="tests.cluster.test_reports" name="test_a" time="1"/>'
        '<testcase classname="tests.cluster.test_reports" name="test_b[x]">'
        '<failure message="boom"/></testcase>'
        '<testcase classname="tests.engine.test_findings_afar" name="test_c">'
        '<skipped message="no AFAR front end here"/></testcase>'
        '<testcase classname="tests.cluster.test_reports" name="test_d">'
        '<skipped message="needs git-ignored inputs, missing: results/x"/>'
        '</testcase></testsuite></testsuites>')
    rows = WS.read_junit([tmp_path / "j.xml"])
    assert [r["id"] for r in rows] == [
        "tests/cluster/test_reports.py::test_a", "tests/cluster/test_reports.py::test_b[x]",
        "tests/engine/test_findings_afar.py::test_c", "tests/cluster/test_reports.py::test_d"]
    res = WS.classify(rows, ["tests/engine/test_findings_nogpu.py::test_gpu"],
                      {"tests/engine/test_canary.py": "an MI300A"})
    assert res["wingtip"] == ["tests/cluster/test_reports.py::test_a"]
    assert res["failed"] == [("tests/cluster/test_reports.py::test_b[x]", "boom")]
    ids = [i for i, _ in res["tuolumne"]]
    assert ids == ["tests/engine/test_findings_afar.py::test_c",
                   "tests/cluster/test_reports.py::test_d",
                   "tests/engine/test_findings_nogpu.py::test_gpu", "tests/engine/test_canary.py"]
    assert [i for i, _ in res["gaps"]] == ["tests/cluster/test_reports.py::test_d"]


def test_the_suite_leaves_only_targeted_tests_for_tuolumne():
    assert WS.in_targets("tests/engine/test_findings_nogpu.py::test_x", ["tests"])
    assert WS.in_targets("tests/engine/test_findings_nogpu.py::test_x",
                         ["tests/engine/test_findings_nogpu.py"])
    assert WS.in_targets("tests/engine/test_findings_nogpu.py::test_x",
                         ["tests/engine/test_findings_nogpu.py::test_x"])
    assert not WS.in_targets("tests/engine/test_findings_nogpu.py::test_x",
                             ["tests/cluster/test_reports.py"])
    assert not WS.in_targets("tests/engine/test_findings_nogpu.py::test_x",
                             ["tests/engine/test_findings_nogpu.py::test_y"])


def test_the_suite_shards_files_round_robin():
    shards = WS.shard_files(["tests"], 4)
    files = sorted(f for s in shards for f in s)
    assert files == sorted(rel_2(f) for f in (ROOT / "tests").glob(
        "test_*.py"))
    assert len(shards) == 4 and max(map(len, shards)) - \
        min(map(len, shards)) <= 1


def test_the_tuolumne_tests_exist():
    """Every test the `tests` step leaves for Tuolumne or runs alone by
    name exists, and no listed name is the prefix of another test's name
    (pytest --deselect matches node id prefixes)."""
    st = WO.step("tests")
    listed = set(st.get("tuolumne_tests") or {}) | \
        set(st.get("serial_tests") or {})
    for nid, why in list((st.get("tuolumne_tests") or {}).items()) + \
            list((st.get("serial_tests") or {}).items()):
        f = nid.split("::")[0]
        assert (ROOT / f).is_file(), nid
        if "::" in nid:
            name = nid.split("::")[-1].split("[")[0]
            defs = re.findall(r"^def (test_\w+)", (ROOT / f).read_text(),
                              re.M)
            assert name in defs, nid
            # a longer name it is a prefix of is deselected too: listed
            assert {f"{f}::{d}" for d in defs if d.startswith(name)} <= \
                listed, nid
        assert why


# --- sealed benchmark sets never leave Tuolumne ----------------------------

def test_sealed_unscored_sets_are_left_out(tmp_path):
    (tmp_path / "catalog").mkdir()
    (tmp_path / "catalog" / "sealed_spent.yaml").write_text(
        "spent: [fresh]\n")
    for d, sealed in (("fresh", True), ("holdout", True), ("open", False),
                      ("holdout-public", False)):
        (tmp_path / "data" / "bench" / d).mkdir(parents=True)
        if sealed:
            (tmp_path / "data" / "bench" / d / "SEAL").write_text("")
    assert WO.sealed_unspent(tmp_path) == ["data/bench/holdout"]
    paths = ["data/bench/fresh/a.c", "data/bench/holdout/SEAL", "data/bench/holdout/x.c",
             "data/bench/holdout-public/y.c", "data/bench/open/z.c", "tools/t.py"]
    keep, sealed = WO.code_files(paths, tmp_path)
    assert keep == ["data/bench/fresh/a.c", "data/bench/holdout-public/y.c",
                    "data/bench/open/z.c", "tools/t.py"]
    assert sealed == ["data/bench/holdout"]
    # fails closed: without a readable list no sealed set counts as scored
    (tmp_path / "catalog" / "sealed_spent.yaml").write_text("spent: [")
    assert WO.sealed_unspent(tmp_path) == ["data/bench/fresh", "data/bench/holdout"]


@pytest.mark.needs_bench("fresh/SEAL", "fresh2/SEAL")
def test_the_spent_list_names_sealed_sets():
    spent = yaml.safe_load((ROOT / WO.SPENT).read_text())["spent"]
    assert {"fresh", "fresh2"} <= set(spent)
    for x in spent:
        assert (ROOT / "data" / "bench" / x / "SEAL").is_file(), x
    # every step input stays outside the sealed, unscored sets
    assert not [e for e in WO.check() if "sealed" in e]


def _sealed_repo(tmp_path):
    """A small tree with the two copy scripts, a scored sealed set, an
    unscored one and an unsealed one."""
    root = tmp_path / "tree"
    for f in ("tools/lanes/wingtip_sync.sh", "tools/lanes/wingtip_offline.sh",
              "tools/lanes/wingtip_offline.py", "tools/jobs/wingtip_cap.sh",
              "catalog/sealed_spent.yaml"):
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / f, root / f)
    for d in ("offload", "catalog"):        # the scripts read the machine's access settings through the package
        shutil.copytree(ROOT / d, root / d, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    (root / "tools" / "lanes" / "wingtip_offline.yaml").write_text(yaml.safe_dump({
        "host": "wingtip", "data_root": "/d", "lane_root": "/l",
        "steps": {"noop": {"doc": "d", "cmd": ["true"], "limit": 10}}}))
    for d, sealed in (("fresh", True), ("holdout", True),
                      ("holdout-public", False)):
        (root / "data" / "bench" / d).mkdir(parents=True)
        (root / "data" / "bench" / d / "case.c").write_text("int x;\n")
        if sealed:
            (root / "data" / "bench" / d / "SEAL").write_text("sealed\n")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C",
           str(root)]
    subprocess.run(git[:1] + ["init", "-q", str(root)], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "t"], check=True)
    fake = tmp_path / "bin"
    fake.mkdir()
    cap = tmp_path / "copied"
    _fake(fake, "ssh", 'echo CAP_OK; echo ENV_OK\n')
    _fake(fake, "rsync", 'for a in "$@"; do case "$a" in --files-from=-) '
          f'cat >> {cap} ;; --files-from=*) cat "${{a#--files-from=}}" '
          f'>> {cap} ;; esac; done; exit 0\n')
    env = {"PATH": f"{fake}:{os.path.dirname(sys.executable)}:"
           + os.environ.get("PATH", "/usr/bin:/bin"),
           "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
           "COMPLIANT_HOSTNAME": "tuolumne1001", "OFFLOAD_LOCAL": os.environ["OFFLOAD_LOCAL"],
           "WINGTIP_OFFLINE_PY": sys.executable}
    return root, env, cap


@pytest.mark.parametrize("cmd", [["tools/lanes/wingtip_sync.sh", "push"],
                                 ["tools/lanes/wingtip_offline.sh", "--no-pull",
                                  "noop"]])
def test_no_copy_to_wingtip_carries_an_unscored_sealed_set(tmp_path, cmd):
    root, env, cap = _sealed_repo(tmp_path)
    r = subprocess.run(["bash", *cmd], cwd=root, env=env,
                       capture_output=True, text=True, timeout=120)
    copied = cap.read_text().split("\0") if cap.exists() else []
    assert "data/bench/fresh/case.c" in copied, r.stdout + r.stderr
    assert "data/bench/holdout-public/case.c" in copied
    assert not [p for p in copied if p.startswith("data/bench/holdout/")]
    assert "not copied: data/bench/holdout/" in r.stderr


# ---- tools/lanes/tioga_suite.py: which tests the wingtip lane leaves for Tioga --------------------------


sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
import tioga_suite as TS  # noqa: E402


def test_the_longest_prefix_decides():
    assert TS.classify("tests/engine/test_findings_nogpu.py::test_compile_error_is_"
                       "rejected[afar-afar_syntax_error]")[0] == "tioga-nogpu"
    assert TS.classify("tests/engine/test_findings_nogpu.py::test_hang_control_times_out_"
                       "at_baseline_opt[afar]")[0] == "mi300a"
    assert TS.classify("tests/cluster/test_toolchains.py::test_rocm_version_"
                       "recorded")[0] == "tioga"
    assert TS.classify("tests/cluster/test_toolchains.py::test_device_smoke"
                       "[afar-1]")[0] == "mi300a"


def test_an_unlisted_test_stays_on_tuolumne():
    cls, why = TS.classify("tests/test_new_thing.py::test_x")
    assert cls == "tuolumne" and why


def test_sealed_and_holdout_tests_stay_on_tuolumne():
    for nid in ("tests/bench/test_holdout_exposure.py::test_no_tracked_file_names_"
                "an_unexcluded_case[sset0]",
                "tests/bench/test_harvest_known.py::test_the_holdout_is_an_unspent_"
                "sealed_set_the_lanes_leave_out",
                "tests/engine/test_check_findings.py::test_committed_violations_are_"
                "a_subset_of_the_full_ones"):
        assert TS.classify(nid)[0] == "sealed"
    assert "sealed" not in TS.ON_TIOGA and "mi300a" not in TS.ON_TIOGA


def test_every_rule_names_a_test_that_exists():
    for prefix in TS.RULES:
        f, _, func = prefix.partition("::")
        path = ROOT / f
        assert path.is_file(), prefix
        if func:
            assert re.search(rf"^def {re.escape(func)}\(", path.read_text(),
                             re.M), prefix
    for cls, _ in TS.RULES.values():
        assert cls in TS.CLASSES


def test_split_writes_one_list_per_class(tmp_path):
    ids = ["tests/engine/test_fuzz_afar.py::test_compare_agree",
           "tests/engine/test_acc.py::test_acc_run_is_a_single_trial",
           "tests/engine/test_canary.py::test_hang_canary_ended_by_the_timeout",
           "tests/test_new.py::test_x"]
    src = tmp_path / "tuolumne.txt"
    src.write_text("".join(i + "\n" for i in ids))
    assert TS.main(["split", str(src), str(tmp_path / "lists")]) == 0
    got = {p.stem: p.read_text().split() for p in
           (tmp_path / "lists").glob("*.txt")}
    assert got == {"tioga-afar": [ids[0]], "tioga-nogpu": [ids[1]],
                   "mi300a": [ids[2]], "tuolumne": [ids[3]]}


def test_the_copy_leaves_out_every_holdout_and_sealed_set():
    keep = TS.copy_files(["tools/a.py", "data/bench/wild/x.f90",
                          "data/bench/harvest-holdout/p.c",
                          "data/bench/harvest2-holdout/q.c",
                          "data/bench/harvest-known-holdout/r.f90"])
    assert keep == ["tools/a.py", "data/bench/wild/x.f90"]


JUNIT = """<?xml version="1.0"?><testsuites><testsuite>
<testcase classname="tests.engine.test_c" name="test_clang_oracle_compare"/>
<testcase classname="tests.engine.test_acc" name="test_acc_run_is_a_single_trial">
 <failure message="environment: wrong_arch"/></testcase>
<testcase classname="tests.cluster.test_toolchains" name="test_device_smoke[afar-0]"/>
<testcase classname="tests.cluster.test_toolchains" name="test_device_smoke[afar-1]">
 <skipped message="no GPU"/></testcase>
</testsuite></testsuites>"""


def test_left_after_tioga_is_every_id_not_passed_there(tmp_path):
    (tmp_path / "a.xml").write_text(JUNIT)
    ids = ["tests/engine/test_c.py::test_clang_oracle_compare",
           "tests/engine/test_acc.py::test_acc_run_is_a_single_trial",
           "tests/cluster/test_toolchains.py::test_device_smoke",
           "tests/engine/test_gen.py::test_y[50]"]
    res = TS.after_tioga(ids, [tmp_path / "a.xml"])
    assert res["passed"] == ["tests/engine/test_c.py::test_clang_oracle_compare",
                             "tests/cluster/test_toolchains.py::test_device_smoke"
                             "[afar-0]"]
    assert [i for i, _ in res["failed"]] == [
        "tests/engine/test_acc.py::test_acc_run_is_a_single_trial"]
    # a node id is done only when every test it names passed; one that
    # did not run there stays as it was
    assert res["left"] == ["tests/engine/test_acc.py::test_acc_run_is_a_single_"
                           "trial",
                           "tests/cluster/test_toolchains.py::test_device_smoke"
                           "[afar-1]",
                           "tests/engine/test_gen.py::test_y[50]"]
