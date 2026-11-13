"""The standing rules (docs/tooling/contributing.md says which ones a test can
hold) as tests. Each rule_* test names the rule and the offender when it fails.

Violations that existed when this file was written are listed, with a
reason each, in catalog/standing_rules_baseline.yaml (a ratchet: a new
offender fails, and so does an entry that is fixed but still listed). The
rules about sealed sets and what the confirmer takes as a witness have
behavioural tests elsewhere; docs/tooling/contributing.md cross-references them.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

from tests import standing_rules as SR
from tests import standing_rules_scans as SC
from tests.standing_rules import ROOT, RULES, rel

# --- helpers shared by the rule tests -----------------------------------------------


def _text(path: str) -> str:
    return (ROOT / path).read_text(errors="replace")


@lru_cache(maxsize=1)
def _machines() -> dict:
    return yaml.safe_load(_text("catalog/machines.yaml"))


def _families() -> list[str]:
    """The compiler families (catalog/toolchains.yaml)."""
    from offload.engine.toolchains import registry
    return list(registry().families)


def _under_test_only() -> set[str]:
    """The families that are never a legality witness (catalog/toolchains.yaml)."""
    from offload.engine.toolchains import registry
    return set(registry().under_test_only())


def _finding_files() -> list[Path]:
    return [p for p in SR.walk("data/findings", suffixes=(".f90", ".c"))
            if "/controls/" not in rel(p)]


@lru_cache(maxsize=1)
def _all_lines() -> dict[str, list[SR.Line]]:
    return {rel(p): SR.lines_of(p) for p in
            SR.shell_files() + SR.python_files() + SR.doc_files()}


@lru_cache(maxsize=1)
def _pdebug() -> dict[str, dict[str, str]]:
    """rule id -> {file: evidence}"""
    out: dict[str, dict[str, str]] = {"pdebug-batch": {}, "pdebug-job-name": {},
                                      "pdebug-chained": {}}
    for path, lines in _all_lines().items():
        for rule, ev in SC.pdebug_scan(lines).items():
            out[rule][path] = ev
    return out


# --- the machinery itself ---------------------------------------------------------------

def test_every_rule_has_a_test_and_a_row_in_contributing():
    doc = _text("docs/tooling/contributing.md")
    mine = set(globals())
    missing = []
    for rid in RULES:
        fn = "test_rule_" + rid.replace("-", "_")
        if fn not in mine and not any(
                n.startswith(fn) for n in mine):
            missing.append(f"{rid}: no test named {fn}*")
        if f"`{rid}`" not in doc:
            missing.append(f"{rid}: not in docs/tooling/contributing.md's rules table")
    assert not missing, "\n".join(missing)


def test_baseline_entries_are_well_formed():
    entries = SR.load_baseline()
    bad, seen = [], set()
    for e in entries:
        key = (e.get("rule"), e.get("offender"))
        if e.get("rule") not in RULES:
            bad.append(f"{key}: unknown rule")
        if not isinstance(e.get("offender"), str) or not e["offender"]:
            bad.append(f"{key}: no offender")
        if not str(e.get("reason", "")).strip():
            bad.append(f"{key}: no reason")
        if key in seen:
            bad.append(f"{key}: listed twice")
        seen.add(key)
    assert not bad, "catalog/standing_rules_baseline.yaml:\n" + "\n".join(bad)


def test_the_ratchet_names_new_offenders_and_fixed_entries(tmp_path):
    f = tmp_path / "b.yaml"
    f.write_text(yaml.safe_dump({"entries": [
        {"rule": "pdebug-batch", "offender": "tools/old.sh", "reason": "x"}]}))
    SR.ratchet("pdebug-batch", {"tools/old.sh": "e"}, f)        # as listed
    with pytest.raises(AssertionError) as new:
        SR.ratchet("pdebug-batch", {"tools/old.sh": "e", "tools/new.sh": "ev"}, f)
    assert "pdebug-batch" in str(new.value) and "tools/new.sh" in str(new.value)
    assert "tools/old.sh" not in str(new.value)
    with pytest.raises(AssertionError) as gone:
        SR.ratchet("pdebug-batch", {}, f)
    assert "tools/old.sh" in str(gone.value) and "remove" in str(gone.value)


def test_scans_never_walk_the_sealed_sets():
    assert SR.walk("bench") == [] and SR.walk("data/bench/fresh2") == []
    assert "bench" in SR.PRUNE and "results" in SR.PRUNE
    seen = {rel(p) for p in SR.shell_files() + SR.python_files() + SR.doc_files()}
    assert not [p for p in seen if p.startswith(("data/bench/", "results/", "corpus/"))]


def test_the_scans_see_the_repository():
    """A scan over an empty file list passes every rule: guard the lists."""
    assert len(SR.shell_files()) > 50 and len(SR.python_files()) > 100
    assert len(SR.doc_files()) > 3 and len(_finding_files()) > 150
    calls = SR.lines_of(ROOT / "tools/jobs/run_oop_pdebug.sh")
    assert any(SR.pdebug_calls(l.text) for l in calls)
    assert "tools/jobs/wingtip_cap.sh" in {rel(p) for p in SR.walk("tools", suffixes=(".sh",))}


# --- detectors on synthetic violations ------------------------------------------------------

def _lines(text: str, suffix: str, tmp_path: Path) -> list[SR.Line]:
    p = tmp_path / ("t" + suffix)
    p.write_text(text)
    return [l._replace(path="t" + suffix) for l in SR.lines_of(p)]


def test_pdebug_detectors(tmp_path):
    sh = _lines("# Submit: flux batch -q pdebug -N1 -t 60 \\\n#    tools/x.sh\n"
                "flux run -q pdebug -N1 -n1 -t 10m tools/y.sh\n"
                "flux run -q pdebug -n1 --job-name=compile-ok a.sh && "
                "flux run -q pdebug -n1 --job-name=compile-ok b.sh\n", ".sh", tmp_path)
    got = SC.pdebug_scan(sh)
    assert set(got) == {"pdebug-batch", "pdebug-job-name", "pdebug-chained"}
    assert SC.pdebug_scan(_lines(
        "flux batch -q pbatch -N1 x.sh\nflux run -q pdebug -n1 "
        "--job-name=compile-test-x y.sh\n", ".sh", tmp_path)) == {}
    loop = _lines("for i in 1 2; do\n  flux run -q pdebug --job-name=compile-a x.sh\n"
                  "done\n", ".sh", tmp_path)
    assert "pdebug-chained" in SC.pdebug_scan(loop)
    md = _lines("```\nflux run -q pdebug --job-name=compile-a a\n"
                "flux run -q pdebug --job-name=compile-b b\n```\n", ".md", tmp_path)
    assert "pdebug-chained" in SC.pdebug_scan(md)
    one = _lines("run `flux batch -q pdebug -N1 x` or not\n", ".md", tmp_path)
    assert "pdebug-batch" in SC.pdebug_scan(one)


def test_module_pipe_detector():
    assert SC.module_pipe("module load rocm 2>&1 | tee log")
    assert SC.module_pipe("module swap a b | cat")
    assert not SC.module_pipe("module load rocm || exit 1")
    assert not SC.module_pipe("module load rocm\nls | wc -l")


def test_git_detectors():
    assert SC.git_destructive_shell("git stash") == "stash"
    assert SC.git_destructive_shell("cd $X && git checkout -f v1") == "checkout"
    assert SC.git_destructive_shell('git -C "$MAIN" reset --hard') == "reset"
    assert SC.git_destructive_shell("git -C $CLONE checkout abc") is None
    assert SC.git_destructive_shell("git status; git worktree add x") is None
    assert SC.git_destructive_argv(["git", "clean", "-fd"], None) == "clean"
    assert SC.git_destructive_argv(["git", "-C", "ROOT", "restore", "."], None)
    assert SC.git_destructive_argv(["git", "-C", "str(dst)", "checkout", "x"], None) is None
    assert SC.git_destructive_argv(["git", "show", "HEAD:x"], "ROOT") is None
    assert SC.git_destructive_argv(["git", "reset", "x"], "ROOT") == "reset"


def test_filing_detectors(tmp_path):
    for bad in ("gh issue create -R a/b", "gh pr comment 3 -b hi",
                "gh api repos/a/b/issues -f title=x", "gh api -X POST x",
                "curl -X POST https://h/x", "curl --data @f https://h",
                "curl -d x https://h", "mail -s s someone", "git push origin x",
                "cat f | mailx -s s a"):
        assert SC.external_write_line(bad), bad
    for ok in ("gh issue list -R a/b", "gh api --paginate repos/a/b/issues",
               "curl -sSL https://h/f -o f", "echo mail", "git pull"):
        assert not SC.external_write_line(ok), ok
    f = tmp_path / "w.py"
    f.write_text("import requests, smtplib\nrequests.post('u')\n"
                 "urlopen(req, data=b'x')\nurlopen(req)\n")
    kinds = [k for _, k in SC.external_write_python(f)]
    assert "smtplib" in kinds and "requests.post" in kinds
    assert "urlopen(data/method)" in kinds and len(kinds) == 3


def test_wait_detectors(tmp_path):
    assert SC.shell_wait_loops("while :; do\n  sleep 5\ndone\n")
    assert SC.shell_wait_loops("until ready; do\n  sleep 5\ndone\n")
    assert SC.shell_wait_loops("while [ -f lock ]; do\n  sleep 5\ndone\n")
    assert not SC.shell_wait_loops(
        'END=$(( $(date +%s) + 60 ))\nwhile :; do\n  [ "$(date +%s)" -gt "$END" ] && break\n'
        "  sleep 5\ndone\n")
    assert not SC.shell_wait_loops("while IFS=, read -r a b; do\n  echo $a\ndone < f\n")
    f = tmp_path / "w.py"
    f.write_text("import time\nwhile True:\n    time.sleep(1)\n")
    assert SC.python_wait_loops(f)
    f.write_text("import time\nt=time.monotonic()\nwhile True:\n    time.sleep(1)\n"
                 "    if time.monotonic() - t > 5: break\n")
    assert not SC.python_wait_loops(f)


def test_legality_prose_detectors():
    hdr = ("! x\n! - legality: the rules accept it; GCC 16.2 compiles and runs it; "
           "CCE is also fine.\n!   more text.\nprogram p\n")
    ((n, blk),) = SC.legality_blocks(hdr)
    assert n == 2 and "more text" in blk
    assert SC.gcc_as_witness(blk) and "GCC 16.2 compiles" in SC.gcc_as_witness(blk)[0]
    assert not SC.gcc_as_witness("no gfortran or gcc is a legality witness")
    assert not SC.gcc_as_witness("GCC is a compiler under test only and never a "
                                 "legality witness.")
    assert not SC.gcc_as_witness("for the gcc cells: the rules accept it")
    assert not SC.gcc_as_witness("the base-language check, gfortran -std=f2008, is a syntax check")
    fuzz = "! Legal OpenMP 5.2: offload.engine.rules accepts it;\n!   AFAR flang front end accepts it.\n"
    assert SC.own_family_witness("1131-afar.f90", "! toolchain: afar (-O2)\n" + fuzz)
    assert not SC.own_family_witness("1131-cce20.f90", "! toolchain: cce20\n" + fuzz)
    assert not SC.own_family_witness(
        "x-afar.f90", "! toolchain: afar\n! Legal: the rules; the AFAR flang front end, "
                      "is the compiler under test and is not counted.\n")


def test_site_copy_detectors():
    assert SC.first_person("We found it; our result, my view, I think")
    assert not SC.first_person("The compiler appears to behave incorrectly.")
    assert not SC.first_person("The specification defines no device-side I/O semantics.")   # I/O is no pronoun
    assert "we" not in SC.html_text("<p>ok</p><pre>we</pre><script>we</script>")
    assert SC.js_strings("const a = 'x y'; // we\n/* our */ f(\"z\")") == ["x y", "z"]


# --- rule: no-gcc-witness -----------------------------------------------------------------

GCC_CMD = re.compile(r"\b(?:gfortran|gcc|g\+\+)\b")
GCC_BIN = {"gcc", "gfortran", "g++", "GFORTRAN", "GCC", "CC"}


def _gcc_witness_offenders() -> dict[str, str]:
    found: dict[str, str] = {}
    m = _machines()
    under = set(_under_test_only())
    for sect in ("independent_checkers", "frontend_checkers"):
        for name, cfg in (m.get(sect) or {}).items():
            blob = f"{name} {cfg.get('command', '')} {cfg.get('family', '')}"
            if GCC_CMD.search(blob) or cfg.get("family") in under:
                found[f"catalog/machines.yaml:{sect}.{name}"] = blob[:100]
    for row in yaml.safe_load(_text("catalog/legality_witness.yaml"))["witnesses"]:
        blob = f"{row.get('checker')} {row.get('command', '')}"
        if GCC_CMD.search(blob) or str(row.get("checker", "")).startswith("gcc"):
            found[f"catalog/legality_witness.yaml:{row['checker']}"] = blob[:100]
    for p in SR.python_files():
        for line, argv, _ in SR.command_lists(p):
            exe = argv[0].rsplit("/", 1)[-1]
            if exe in GCC_BIN and any(a in ("-fopenmp", "-fopenacc") or
                                      a.startswith(("-fopenmp=", "-fopenacc=")) for a in argv):
                found.setdefault(rel(p), f"{rel(p)}:{line}: {' '.join(argv)[:90]}")
    for p in SR.shell_files():
        if "gcc" in p.name:       # the GCC lanes run GCC as the compiler under test
            continue
        for ln in SR.lines_of(p):
            if ln.kind == "code" and re.search(
                    r"\b(?:gfortran|gcc|g\+\+)\b[^|;&]*-fopen(?:mp|acc)", ln.text):
                found.setdefault(rel(p), f"{ln.path}:{ln.no}: {ln.text[:90]}")
    for p in _finding_files():
        text = p.read_text(errors="replace")
        for line, blk in SC.legality_blocks(text):
            bad = SC.gcc_as_witness(blk)
            if bad:
                found[rel(p)] = f"{rel(p)}:{line}: {bad[0][:100]}"
    return found


def test_rule_no_gcc_witness():
    SR.ratchet("no-gcc-witness", _gcc_witness_offenders())


# --- rule: no-own-checker -------------------------------------------------------------------

def _own_checker_offenders() -> dict[str, str]:
    found: dict[str, str] = {}
    m = _machines()
    fams, under = set(_families()), set(_under_test_only())
    for name, cfg in (m.get("independent_checkers") or {}).items():
        why = []
        if cfg.get("family") not in fams:
            why.append("family is not a compiler family")
        if cfg.get("family") in under:
            why.append("family is under test only")
        if cfg.get("kind") != "offload_compiler" or cfg.get("witness_only") is not True:
            why.append("not kind: offload_compiler with witness_only: true")
        if why:
            found[f"catalog/machines.yaml:independent_checkers.{name}"] = "; ".join(why)
    for name, cfg in (m.get("frontend_checkers") or {}).items():
        if cfg.get("family") not in fams:
            found[f"catalog/machines.yaml:frontend_checkers.{name}"] = \
                "its family is not a compiler family"
    known = set(m.get("independent_checkers") or {})
    for row in yaml.safe_load(_text("catalog/legality_witness.yaml"))["witnesses"]:
        if row["checker"] not in known:
            found[f"catalog/legality_witness.yaml:{row['checker']}"] = \
                "a checker machines.yaml does not define"
    for p in _finding_files():
        bad = SC.own_family_witness(p.name, p.read_text(errors="replace"))
        if bad:
            found[rel(p)] = f"{rel(p)}: {bad[0]}"
    return found


def test_rule_no_own_checker():
    SR.ratchet("no-own-checker", _own_checker_offenders())


def test_shared_front_ends_are_never_each_others_witness():
    """catalog/machines.yaml `shared_frontends` (AFAR and upstream llvm: one
    front end) arrives with the llvm branch; once there, no
    independent_checkers entry may belong to a family of a group while
    the case's family is in the same group (offload.engine.confirm.witness)."""
    m = _machines()
    groups = m.get("shared_frontends")
    if not groups:
        pytest.skip("catalog/machines.yaml has no shared_frontends yet (wt/t51)")
    fams = set(_families())
    for g in (groups.values() if isinstance(groups, dict) else groups):
        assert len(g) >= 2 and set(g) <= fams | set(m["independent_checkers"]), g


# --- rule: no-ompvv-oracle -----------------------------------------------------------------

WITNESS_MODULES = ("offload/engine/prerun.py", "offload/engine/rules.py",
                   "offload/engine/confirm/witness.py", "offload/engine/flang_oracle.py",
                   "offload/engine/clang_oracle.py", "offload/engine/gen.py",
                   "offload/engine/c_gen.py", "offload/engine/acc_gen.py",
                   "offload/engine/acc_c_gen.py")
OMPVV = re.compile(r"omp_?vv", re.I)


def _ompvv_offenders() -> dict[str, str]:
    import ast
    found: dict[str, str] = {}
    if OMPVV.search(_text("catalog/legality_witness.yaml")):
        found["catalog/legality_witness.yaml"] = "names omp_vv"
    m = _machines()
    for sect in ("independent_checkers", "frontend_checkers"):
        if OMPVV.search(json.dumps(m.get(sect) or {})):
            found[f"catalog/machines.yaml:{sect}"] = "names omp_vv"
    for mod in WITNESS_MODULES:
        tree = ast.parse(_text(mod))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "")] + [a.name for a in node.names]
            if any(re.search(r"ompvv|baseline|corpus_check", n) for n in names):
                found[mod] = f"{mod}:{node.lineno}: imports {names}"
        for line, s in SC.python_strings(ROOT / mod):
            if OMPVV.search(s) and not re.search(r"untrusted|never|not trusted", s, re.I):
                found.setdefault(mod, f"{mod}:{line}: {s[:80]!r}")
    for p in _finding_files():
        for line, blk in SC.legality_blocks(p.read_text(errors="replace")):
            if OMPVV.search(blk):
                found[rel(p)] = f"{rel(p)}:{line}: legality names omp_vv"
    return found


def test_rule_no_ompvv_oracle():
    SR.ratchet("no-ompvv-oracle", _ompvv_offenders())


# --- rules: the flux queues --------------------------------------------------------------------

def test_rule_pdebug_batch():
    SR.ratchet("pdebug-batch", _pdebug()["pdebug-batch"])


def test_rule_pdebug_job_name():
    SR.ratchet("pdebug-job-name", _pdebug()["pdebug-job-name"])


def test_rule_pdebug_chained():
    SR.ratchet("pdebug-chained", _pdebug()["pdebug-chained"])


def test_rule_no_module_pipe():
    found = {}
    for path, lines in _all_lines().items():
        for ln in lines:
            if SC.module_pipe(ln.text):
                found.setdefault(path, f"{path}:{ln.no}: {ln.text[:100]}")
    SR.ratchet("no-module-pipe", found)


# --- rule: no-shared-tree-git ------------------------------------------------------------------

def test_rule_no_shared_tree_git():
    found = {}
    for p in SR.shell_files():
        for ln in SR.lines_of(p):
            if ln.kind == "code" and SC.git_destructive_shell(ln.text):
                found.setdefault(rel(p), f"{ln.path}:{ln.no}: {ln.text[:100]}")
    for p in SR.python_files():
        for line, argv, cwd in SR.command_lists(p):
            sub = SC.git_destructive_argv(argv, cwd)
            if sub:
                found.setdefault(rel(p), f"{rel(p)}:{line}: git {sub} ...")
    SR.ratchet("no-shared-tree-git", found)


# --- rule: no-external-filing ------------------------------------------------------------------

def test_rule_no_external_filing():
    found = {}
    for p in SR.shell_files() + SR.python_files():
        for ln in SR.lines_of(p):
            if ln.kind in ("code", "string") and SC.external_write_line(ln.text):
                found.setdefault(rel(p), f"{ln.path}:{ln.no}: {ln.text[:100]}")
    for p in SR.python_files():
        for line, what in SC.external_write_python(p):
            found.setdefault(rel(p), f"{rel(p)}:{line}: {what}")
        for line, argv, _ in SR.command_lists(p):
            if SC.external_write_line(" ".join(argv)):
                found.setdefault(rel(p), f"{rel(p)}:{line}: {' '.join(argv)[:90]}")
    SR.ratchet("no-external-filing", found)


# --- rule: bounded-waits ------------------------------------------------------------------------

def test_rule_bounded_waits():
    found = {}
    for p in SR.shell_files():
        for line, head in SC.shell_wait_loops(p.read_text(errors="replace")):
            found.setdefault(rel(p), f"{rel(p)}:{line}: {head[:90]}")
    for p in SR.python_files():
        for line, head in SC.python_wait_loops(p):
            found.setdefault(rel(p), f"{rel(p)}:{line}: {head}")
    SR.ratchet("bounded-waits", found)


# --- rule: wingtip-cap (the vendor packet's scripts; tools/ is test_wingtip_cap.py) ---------

def test_rule_wingtip_cap():
    from tests.cluster.test_lanes import SOURCE, SOFT, HARD, code_lines, hard_cap, runs_on_wingtip
    found = {}
    for p in SR.walk("data/vendor/checks", suffixes=(".sh",)):
        text = p.read_text(errors="replace")
        if p.name == "wingtip_cap.sh":
            continue
        soft = [ln for ln in code_lines(text) if SOURCE.match(ln) and (
            SOFT.search(SOURCE.match(ln).group(1)) or not HARD.search(SOURCE.match(ln).group(1)))]
        if soft:
            found[rel(p)] = f"{rel(p)}: {soft[0].strip()[:90]} (no `|| exit 1`)"
        elif runs_on_wingtip(p, text) and not hard_cap(text):
            found[rel(p)] = f"{rel(p)}: runs on wingtip without the cap"
    mine, theirs = ROOT / "tools/jobs/wingtip_cap.sh", ROOT / "data/vendor/checks/wingtip_cap.sh"
    if theirs.is_file() and theirs.read_bytes() != mine.read_bytes():
        found[rel(theirs)] = "differs from tools/jobs/wingtip_cap.sh (the cap's one copy)"
    SR.ratchet("wingtip-cap", found)


# --- rule: gate-c-other-node ----------------------------------------------------------------------

@pytest.mark.needs_results("results/gate/catalog/reruns")
def test_rule_gate_c_other_node():
    from offload.engine.gate import node_key
    cells: dict[tuple, dict] = {}
    for f in sorted((ROOT / "results/gate").glob("*/reruns/*.jsonl")):
        for ln in f.read_text(errors="replace").splitlines():
            if '"env"' not in ln:
                continue
            r = json.loads(ln)
            node = node_key(r.get("node"))
            if not node or r.get("env") not in ("a", "b", "c", "d"):
                continue
            c = cells.setdefault((r.get("campaign") or f.parent.parent.name, r.get("cell")),
                                 {"abd": set(), "c": set()})
            c["c" if r["env"] == "c" else "abd"].add(node)
    found = {f"{camp}:{cell}": f"(c) ran only on {sorted(v['c'])}, where (a)/(b)/(d) ran"
             for (camp, cell), v in cells.items() if v["c"] and v["c"] <= v["abd"]}
    assert cells, "no gate reruns read"
    SR.ratchet("gate-c-other-node", found)


# --- rules: site copy -----------------------------------------------------------------------------------

SITE_PY = ("tools/site/site_build.py", "offload/engine/site/data.py", "offload/engine/site/header.py",
           "offload/engine/site/matrix.py", "offload/engine/site/scrub.py")


def _site_module():
    spec = importlib.util.spec_from_file_location("site_build_rules", ROOT / "tools/site/site_build.py")
    sb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sb)
    return sb


def _first_person_offenders(build_dir: Path, built_site_data: Path) -> dict[str, str]:
    from offload.engine.site import data as D
    from offload.engine.site import header as H
    found: dict[str, str] = {}

    def note(key: str, text: str) -> None:
        hits = SC.first_person(text)
        if hits:
            found.setdefault(key, f"{key}: {hits[0]!r} in {text[:80]!r}")

    note("site/templates", " ".join(SC.html_text(p.read_text()) for p in
                                    SR.walk("site/templates", suffixes=(".html",))))
    for p in SR.walk("site/static", suffixes=(".js",)):
        for s in SC.js_strings(p.read_text()):
            note(rel(p), s)
    for mod in SITE_PY:
        for line, s in SC.python_strings(ROOT / mod):
            note(f"{mod}", s)
    for p in _finding_files():
        h = H.parse(p)
        if not D.published({"header": h}):
            continue
        mixed = h.disposition[1] if h.disposition and h.disposition[0] == "mixed" else ""
        for field, val in (("title", h.title), ("summary", h.summary),
                           ("workaround", h.workaround), ("found_in", h.found_in),
                           ("mixed reason", mixed),
                           ("control", " ".join(d for _, d in h.controls))):
            note(f"{rel(p)} site: {field}", val or "")
    # the pages the builder writes from the real data
    shutil.copytree(built_site_data, build_dir, dirs_exist_ok=True)      # the data, built once for the run
    _site_module().render(build_dir)
    for p in sorted(build_dir.rglob("*.html")):
        note("built page " + p.relative_to(build_dir).as_posix(), SC.html_text(p.read_text()))
    return found


def test_rule_no_first_person(tmp_path, built_site_data):
    SR.ratchet("no-first-person", _first_person_offenders(tmp_path, built_site_data))


OWNER_CELL_WORDS = {"behaves incorrectly", "not supported", "correct", "unknown", "n/a",
                    "fails another way"}


def test_rule_site_cell_words():
    sb = _site_module()
    found = {}
    words = set(sb.STATE_WORD.values()) | {"not supported"}
    if words != OWNER_CELL_WORDS:
        found["tools/site/site_build.py"] = f"STATE_WORD has {sorted(words ^ OWNER_CELL_WORDS)}"
    for js, var in (("site/static/issues.js", "STATE_WORD"), ("site/static/canuse.js", "CU_WORD")):
        m = re.search(r"const %s = \{(.*?)\};" % var, _text(js), re.S)
        vals = set(re.findall(r":\s*'([^']+)'", m.group(1))) if m else set()
        extra = vals - OWNER_CELL_WORDS
        if not m or extra:
            found[js] = f"{var}: {sorted(extra) or 'not found'}"
    SR.ratchet("site-cell-words", found)


# --- rule: no-ai-attribution ------------------------------------------------------------------------------

def test_rule_no_ai_attribution():
    if not (ROOT / ".git").exists():
        pytest.skip("no git history here (a lane copy without a repository)")
    r = subprocess.run(["git", "-C", str(ROOT), "log", "--format=%H%x00%an <%ae>%x00%cn <%ce>%x00%B%x01"],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not r.stdout.strip():
        pytest.skip("git log gives no history here: " + r.stderr[:100])
    found = {}
    for rec in r.stdout.split("\x01"):
        if not rec.strip():
            continue
        sha, author, committer, body = rec.strip("\n").split("\x00", 3)
        hit = SC.ATTRIBUTION.search(body) or re.search(
            r"claude|anthropic", author + committer, re.I)
        if hit:
            subject = body.strip().splitlines()[0][:70] if body.strip() else ""
            found[sha[:10]] = f"{sha[:10]} {subject!r}: {hit.group(0).strip()[:70]}"
    SR.ratchet("no-ai-attribution", found)


# --- rule: no-tracked-symlink -------------------------------------------------------------------

def _git(tree, *args):
    r = subprocess.run(["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_tracked_symlink_detector(tmp_path):
    tree = tmp_path / "t"
    tree.mkdir()
    _git(tree, "init", "-q")
    (tree / "d").mkdir()
    (tree / "real.txt").write_text("x")
    (tree / "results").symlink_to("/somewhere/shared/results")      # root link
    (tree / "d" / "abs").symlink_to("/etc/hosts")                    # absolute target
    (tree / "d" / "rel").symlink_to("../real.txt")                   # relative, below the root: fine
    _git(tree, "add", "-A")
    _git(tree, "commit", "-qm", "x")
    found = SC.symlink_offenders(SC.tracked_symlinks(tree))
    assert sorted(found) == ["d/abs", "results"], found
    assert SC.symlink_offenders([("d/rel", "../real.txt")]) == {}


def test_the_repository_ignore_file_ignores_a_symlink_named_like_the_shared_directories(tmp_path):
    """`results/` (a trailing slash) matches directories only, so a worktree's `results`
    symlink was not ignored and `git add -A` committed it."""
    tree = tmp_path / "t"
    tree.mkdir()
    _git(tree, "init", "-q")
    (tree / ".gitignore").write_text(_text(".gitignore"))
    for name in ("results", "spec", "corpus"):
        (tree / name).symlink_to("/p/shared/" + name)
        r = subprocess.run(["git", "-C", str(tree), "check-ignore", "-q", name], capture_output=True)
        assert r.returncode == 0, f".gitignore does not ignore a symlink {name}: write /{name}, not {name}/"


def test_rule_no_tracked_symlink():
    if not (ROOT / ".git").exists():
        pytest.skip("no git history here (a lane copy without a repository)")
    found = SC.symlink_offenders(SC.tracked_symlinks(ROOT))
    SR.ratchet("no-tracked-symlink", found)
