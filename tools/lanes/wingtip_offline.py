#!/usr/bin/env python3
"""The manifest side of the wingtip offline lane (tools/lanes/wingtip_offline.sh;
docs/tooling/wingtip.md). Each CPU-only step the lane can run is an entry of
tools/lanes/wingtip_offline.yaml: its command, time limit, inputs (paths or
globs relative to the repository root; `?` marks an optional input, `@NAME`
an input group) and outputs (copied back after a successful run).

    python3 -I tools/lanes/wingtip_offline.py list | check
    python3 -I tools/lanes/wingtip_offline.py plan|shell STEP [ARGS...]
    python3 -I tools/lanes/wingtip_offline.py inputs|outputs STEP [--under results]
    python3 -I tools/lanes/wingtip_offline.py trace-report STEP DIR [--root R]
    python3 -I tools/lanes/wingtip_offline.py trace-gaps REPORT
    python3 -I tools/lanes/wingtip_offline.py exec-check DIR

`inputs` and `outputs` print NUL-separated paths. `trace-report` and
`trace-gaps` compare the files a traced run opened with the manifest.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST = ROOT / "tools" / "lanes" / "wingtip_offline.yaml"
# git-ignored inputs that live in the shared data directory on wingtip
SHARED = ("results", "corpus", "spec")
# a sealed benchmark set (data/bench/<set>/SEAL) that is not scored yet never
# leaves Tuolumne; the scored ones are listed here
SPENT = Path("catalog") / "sealed_spent.yaml"
STEP_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ManifestError(Exception):
    pass


def load(path: Path = MANIFEST) -> dict:
    import yaml
    data = yaml.safe_load(Path(path).read_text())
    if Path(path) == MANIFEST and isinstance(data, dict):
        sys.path.insert(0, str(ROOT))
        try:
            from offload.engine import localcfg
            data = localcfg.overlay("wingtip_offline.yaml", data)      # this user's data_root and lane_root
        except ImportError:                 # a bare copy of the lane's tools
            pass
    if not isinstance(data, dict) or "steps" not in data:
        raise ManifestError(f"{path}: no steps")
    return data


def _groups(inputs, data: dict) -> list[str]:
    """`@NAME` entries replaced by the manifest's `groups: NAME: [...]`."""
    out = []
    for i in inputs:
        if i.startswith("@"):
            g = (data.get("groups") or {}).get(i[1:])
            if g is None:
                raise ManifestError(f"no input group {i}")
            out += [x for x in _groups(g, data) if x not in out]
        elif i not in out:
            out.append(i)
    return out


def step(name: str, data: dict | None = None) -> dict:
    data = data or load()
    if name not in data["steps"]:
        raise ManifestError(f"unknown step {name!r}; steps: "
                            + ", ".join(sorted(data["steps"])))
    d = dict(data.get("defaults") or {})
    d.update(data["steps"][name])
    d["name"] = name
    d["inputs"] = _groups(d.get("inputs") or [], data)
    # `inputs_from: [STEP | all]`: those steps' own inputs too
    for other in d.get("inputs_from") or []:
        for n in ([k for k in data["steps"] if k != name]
                  if other == "all" else [other]):
            if n not in data["steps"]:
                raise ManifestError(f"{name}: inputs_from {n}: no such step")
            d["inputs"] += [i for i in _groups(data["steps"][n].get(
                "inputs") or [], data) if i not in d["inputs"]]
    d.setdefault("outputs", [])
    d.setdefault("env", [])
    return d


def expand(patterns, root: Path = ROOT) -> tuple[list[str], list[str]]:
    """(paths, missing): every pattern's matches relative to root, sorted
    and unique; a pattern without a match is missing unless it starts
    with `?`."""
    found, missing = set(), []
    for pat in patterns:
        optional = pat.startswith("?")
        pat = pat.lstrip("?")
        if glob.has_magic(pat):
            hits = glob.glob(pat, root_dir=str(root), recursive=True)
        else:
            hits = [pat] if os.path.lexists(Path(root) / pat) else []
        if not hits and not optional:
            missing.append(pat)
        found.update(h.rstrip("/") for h in hits)
    return sorted(found), missing


def under(paths, prefix: str | None) -> list[str]:
    """The paths below a shared directory (relative to it), or with
    prefix None those outside every shared directory."""
    out = []
    for p in paths:
        top, _, rest = p.partition("/")
        if prefix is None:
            if top not in SHARED:
                out.append(p)
        elif top == prefix:
            out.append(rest or ".")     # the whole shared directory
    return out


def subst(path: str, env=None) -> str:
    """${VAR:-default} of an output path, from the step's environment."""
    env = os.environ if env is None else env
    return re.sub(r"\$\{([A-Z][A-Z0-9_]*):-([^}]*)\}",
                  lambda m: env.get(m[1]) or m[2], path)


def _size(root: Path, rel: str) -> int:
    p = Path(root) / rel
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return p.stat().st_size if p.exists() else 0


def plan(name: str, args=(), root: Path = ROOT, data=None) -> dict:
    s = step(name, data)
    files, missing = expand(s["inputs"], root)
    return {"step": name, "doc": s.get("doc", ""),
            "cmd": list(s["cmd"]) + list(args), "limit_s": int(s["limit"]),
            "env": list(s["env"]), "inputs": files, "missing": missing,
            "bytes": sum(_size(root, f) for f in files),
            "outputs": [subst(o) for o in s["outputs"]],
            "tuolumne_only": s.get("tuolumne_only", "")}


def shell(name: str, data=None) -> str:
    """Lines for `eval` in the runner: LIMIT, GUARD (1: the step fails
    when it tries to run a program wingtip does not have), ENV_OK (the
    variables the step accepts) and the CMD array."""
    s = step(name, data)
    return "\n".join([f"LIMIT={int(s['limit'])}",
                      f"GUARD={0 if s.get('exec_guard') is False else 1}",
                      "ENV_OK=" + shlex.quote(" ".join(s["env"])),
                      "CMD=(" + " ".join(shlex.quote(c) for c in s["cmd"])
                      + ")"]) + "\n"


def sealed_unspent(root: Path = ROOT) -> list[str]:
    """data/bench/<set> of every sealed set (data/bench/<set>/SEAL exists) that
    catalog/sealed_spent.yaml does not list as scored. Fails closed: an
    unreadable list counts no set as scored."""
    import yaml
    try:
        spent = set(yaml.safe_load((Path(root) / SPENT).read_text())
                    ["spent"] or ())
    except Exception:
        spent = set()
    return sorted(f"data/bench/{p.parent.name}" for p in
                  (Path(root) / "data" / "bench").glob("*/SEAL")
                  if p.parent.name not in spent)


def under_sealed(path: str, sealed) -> bool:
    path = path.lstrip("?").rstrip("/")
    return any(path == s or path.startswith(s + "/") for s in sealed)


def code_files(paths, root: Path = ROOT) -> tuple[list[str], list[str]]:
    """(the paths that may be copied to wingtip, the sealed unscored sets
    left out)."""
    sealed = sealed_unspent(root)
    return [p for p in paths if not under_sealed(p, sealed)], sealed


def check(data=None, root: Path = ROOT) -> list[str]:
    """Problems of the manifest (empty: fine); the inputs under results/
    are only checked where results/ exists."""
    data = data or load()
    bad = []
    for name in data["steps"]:
        if not STEP_NAME.match(name):
            bad.append(f"{name}: bad step name")
            continue
        s = step(name, data)
        for k in ("cmd", "limit", "doc"):
            if not s.get(k):
                bad.append(f"{name}: no {k}")
        if not isinstance(s.get("cmd"), list):
            bad.append(f"{name}: cmd is not a list")
            continue
        script = next((c for c in s["cmd"] if c.startswith("tools/")), None)
        if script and not (root / script).is_file():
            bad.append(f"{name}: {script} does not exist")
        if not 0 < int(s["limit"]) <= 6 * 3600:
            bad.append(f"{name}: limit {s['limit']} outside (0, 6 h]")
        for e in s["env"]:
            if not ENV_NAME.match(e):
                bad.append(f"{name}: bad env name {e}")
        for o in s["outputs"]:
            if o.startswith(("/", "?")) or ".." in o.split("/"):
                bad.append(f"{name}: output {o} is not a tree path")
            if o.startswith(("results/fresh2", "data/bench/fresh2")):
                bad.append(f"{name}: output {o} is sealed")
        have_results = (root / "results").is_dir()
        ins = [p for p in s["inputs"] if have_results or
               p.lstrip("?").split("/")[0] != "results"]
        _, missing = expand(ins, root)
        bad += [f"{name}: input {m} matches nothing" for m in missing]
        sealed = sealed_unspent(root)
        bad += [f"{name}: input {i} is in a sealed, unscored set (stays on "
                "Tuolumne)" for i in s["inputs"] if under_sealed(i, sealed)]
    return bad


# --- trace-report ----------------------------------------------------------

_CALL = re.compile(r'^(?:\[pid\s+\d+\]\s+)?(?:\d+\s+)?'
                   r'(openat|open|stat|lstat|newfstatat|statx|access|'
                   r'faccessat2?|readlink|execve)\((?:AT_FDCWD|\d+)?,?\s*'
                   r'"([^"]+)"(.*)$')


_FORK = re.compile(r"^(?:clone3?|vfork|fork)\(.*\)\s+=\s+(\d+)\b")
_CHDIR = re.compile(r'^chdir\("([^"]+)"\)\s+=\s+0\b')


def _pid_files(trace_dir: Path) -> dict:
    """{pid: lines} of `strace -ff -o DIR/t` (files t.<pid>); a file
    without a pid suffix (one -o file) under the key of its name."""
    out = {}
    for f in sorted(Path(trace_dir).glob("*")):
        if f.is_file():
            key = f.suffix[1:] if f.suffix[1:].isdigit() else f.name
            out[key] = f.read_text(errors="replace").splitlines()
    return out


def _with_cwd(files: dict, start: str):
    """(line, cwd) of every traced line: each process starts in the cwd
    its parent had when it forked it (the run's own process in `start`)
    and follows its chdir calls, so a relative path is read against the
    right directory (a test that runs in its own temporary directory)."""
    born, order = {}, []
    for key, lines in files.items():
        for ln in lines:
            m = _FORK.match(ln)
            if m:
                born[m.group(1)] = key
    todo = [k for k in files if k not in born]
    start_cwd = {k: start for k in todo}
    while todo:
        key = todo.pop()
        order.append(key)
        cwd = start_cwd[key]
        for ln in files[key]:
            m = _CHDIR.match(ln)
            if m:
                cwd = os.path.normpath(os.path.join(cwd, m.group(1)))
            m = _FORK.match(ln)
            if m and m.group(1) in files and m.group(1) not in start_cwd:
                start_cwd[m.group(1)] = cwd
                todo.append(m.group(1))
            yield ln, cwd
    for key in files:            # a process whose parent was not traced
        if key not in start_cwd:
            for ln in files[key]:
                yield ln, start


def traced_paths(trace_dir: Path, lane: str,
                 data: str | None = None) -> dict[str, set[str]]:
    """{"read": opened files, "missing": paths looked up but absent,
    "exec": programs run, "exec_failed": programs whose execve failed}
    from the strace files of a run: the paths under the lane (the copy's
    root) or under the data directory (its results/, corpus/, spec/),
    relative to the lane."""
    out = {"read": set(), "missing": set(), "exec": set(),
           "exec_failed": set()}
    roots = [lane.rstrip("/") + "/"]
    if data:
        roots.append(data.rstrip("/") + "/")
    for ln, cwd in _with_cwd(_pid_files(trace_dir), lane.rstrip("/")):
        m = _CALL.match(ln)
        if not m:
            continue
        call, path, rest = m.groups()
        if call == "execve":
            out["exec_failed" if "= -1" in rest else "exec"].add(path)
            continue
        if not path.startswith("/"):
            path = os.path.join(cwd, path)
        base = next((r for r in roots if path.startswith(r)), None)
        if base is None:
            continue
        rel = os.path.normpath(path[len(base):])
        if rel.split("/")[0] not in SHARED:
            continue
        if "ENOENT" in rest:
            out["missing"].add(rel)
        elif "= -1" not in rest and call in ("openat", "open"):
            if "O_DIRECTORY" in rest:
                out["read"].add(rel + "/")
            else:
                out["read"].add(rel)
        elif "= -1" not in rest and "S_IFREG" in rest:
            # a file's presence checked (Path.exists, is_file): the step
            # may decide differently without it
            out["read"].add(rel)
    return out


def covered(path: str, patterns) -> bool:
    """Whether a manifest pattern names the path (itself, a directory
    above it, or a glob matching it)."""
    path = path.rstrip("/")
    for pat in patterns:
        pat = pat.lstrip("?").rstrip("/")
        if path == pat or path.startswith(pat + "/"):
            return True
        if glob.has_magic(pat):
            rx = glob.translate(pat, recursive=True, include_hidden=True)
            if re.match(rx, path):
                return True
            # a directory the glob's matches live in (listed by the step)
            if re.match(glob.translate(pat + "/**", recursive=True,
                                       include_hidden=True), path):
                return True
    return False


def trace_report(name: str, trace_dir: Path, lane: str,
                 data_dir: str | None = None, data=None) -> dict:
    s = step(name, data)
    t = traced_paths(trace_dir, lane, data_dir)
    pats = s["inputs"] + [subst(o) for o in s["outputs"]]

    def parent_listed(p):
        # a directory opened only to walk to its files, or a parent of
        # a named input
        return p.endswith("/") and any(
            q.lstrip("?").startswith(p) for q in pats)
    return {"step": name,
            "unlisted_reads": sorted(p for p in t["read"]
                                     if not covered(p, pats)
                                     and not parent_listed(p)),
            "missing_lookups": sorted(p for p in t["missing"]
                                      if not covered(p, pats)),
            "exec": sorted(t["exec"]),
            "missing_programs": missing_programs(t),
            "compilers": compilers_run(t)}


# compilers and their drivers: wingtip's (Ubuntu gcc/gfortran 13.3.0,
# NVHPC) are not Tuolumne's (Red Hat 13.3.1, AFAR, CCE), so a step that
# runs one there (a base-language legality check, an elided program)
# could decide differently
COMPILER = re.compile(r"^(gfortran|gcc|g\+\+|cc|c\+\+|cpp|f951|cc1|cc1plus|"
                      r"collect2|ld|ld\.gold|as|nvfortran|nvc|nvc\+\+|ftn|"
                      r"crayftn|craycc|CC|[a-z]*flang[-a-z]*|[a-z]*clang"
                      r"[-+a-z]*)(-\d+(\.\d+)*)?$")


def missing_programs(t: dict) -> list[str]:
    """Programs the step tried to run that do not exist here (an AFAR or
    CCE front end, /usr/tce): an execve that failed for every directory it
    was tried in (a PATH search fails in the directories before the one
    that has it)."""
    ran = {os.path.basename(p) for p in t["exec"]}
    return sorted(p for p in t["exec_failed"]
                  if os.path.basename(p) not in ran)


def compilers_run(t: dict) -> list[str]:
    return sorted(p for p in t["exec"]
                  if COMPILER.match(os.path.basename(p)))


def exec_report(trace_dir: Path) -> list[str]:
    """What the guard refuses: programs missing here, compilers run here."""
    t = traced_paths(trace_dir, "/nonexistent")
    return [f"tried to run {p}, which this host does not have"
            for p in missing_programs(t)] + \
        [f"ran the compiler {p}, which differs from Tuolumne's"
         for p in compilers_run(t)]


def trace_gaps(report: dict, root: Path = ROOT) -> list[str]:
    """What a traced run says the manifest lacks: the files it read that
    the step does not name, and the paths it looked up and did not find
    there that this tree has."""
    return [f"read, not in the manifest: {p}" for p in
            report["unlisted_reads"]] + \
        [f"looked up, absent there, present here: {p}" for p in
         report["missing_lookups"] if os.path.lexists(Path(root) / p)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("plan")
    p.add_argument("step")
    p.add_argument("args", nargs=argparse.REMAINDER)
    p.add_argument("--json", action="store_true")
    for k in ("inputs", "outputs"):
        q = sub.add_parser(k)
        q.add_argument("step")
        q.add_argument("--under", choices=SHARED + ("code",))
        if k == "outputs":
            q.add_argument("--existing", action="store_true")
    q = sub.add_parser("shell")
    q.add_argument("step")
    q = sub.add_parser("trace-report")
    q.add_argument("step")
    q.add_argument("dir", type=Path)
    q.add_argument("--root", default=str(ROOT))
    q.add_argument("--data")
    q = sub.add_parser("trace-gaps")
    q.add_argument("report", type=Path)
    q = sub.add_parser("exec-check")
    q.add_argument("dir", type=Path)
    sub.add_parser("check")
    sub.add_parser("code-files", help="filter a NUL-separated path list "
                   "(stdin) to what may be copied to wingtip")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "code-files":
            paths = [p for p in sys.stdin.buffer.read().decode()
                     .split("\0") if p]
            keep, sealed = code_files(paths)
            for x in sealed:
                print(f"not copied: {x}/ (sealed, not scored in {SPENT})",
                      file=sys.stderr)
            sys.stdout.write("".join(p + "\0" for p in keep))
            return 0
        if a.cmd == "list":
            data = load()
            for n in data["steps"]:
                s = step(n, data)
                print(f"{n:18} {s['limit']:>6} s  {s['doc']}")
            return 0
        if a.cmd == "trace-gaps":
            gaps = trace_gaps(json.loads(a.report.read_text()))
            print("\n".join(gaps) if gaps else "the manifest names every "
                  "git-ignored file the step used")
            return 1 if gaps else 0
        if a.cmd == "exec-check":
            miss = exec_report(a.dir)
            print("\n".join(miss)) if miss else None
            return 1 if miss else 0
        if a.cmd == "check":
            bad = check()
            print("\n".join(bad) or "manifest ok")
            return 1 if bad else 0
        if a.cmd == "shell":
            sys.stdout.write(shell(a.step))
            return 0
        if a.cmd == "plan":
            pl = plan(a.step, a.args)
            if a.json:
                print(json.dumps(pl, indent=1))
            else:
                print(f"step     {pl['step']}: {pl['doc']}")
                print(f"command  {shlex.join(pl['cmd'])}")
                print(f"limit    {pl['limit_s']} s (timeout --kill-after=10,"
                      " nice, compliant.slice)")
                if pl["env"]:
                    print(f"env      accepts {' '.join(pl['env'])}")
                print(f"inputs   {len(pl['inputs'])} paths, "
                      f"{pl['bytes'] / 1e6:.1f} MB")
                for f in pl["inputs"]:
                    print(f"  < {f}")
                for m in pl["missing"]:
                    print(f"  MISSING {m}")
                for o in pl["outputs"]:
                    print(f"  > {o}")
            return 1 if pl["missing"] else 0
        if a.cmd == "inputs":
            files, missing = expand(step(a.step)["inputs"])
            if missing:
                print(f"{a.step}: missing inputs: {', '.join(missing)}",
                      file=sys.stderr)
                return 1
            sealed = [f for f in files if under_sealed(f, sealed_unspent())]
            if sealed:
                print(f"{a.step}: inputs in a sealed, unscored set: "
                      f"{', '.join(sealed)} (they stay on Tuolumne)",
                      file=sys.stderr)
                return 1
        if a.cmd == "outputs":
            outs = [subst(o) for o in step(a.step)["outputs"]]
            files = expand(["?" + o.lstrip("?") for o in outs])[0] \
                if a.existing else [o.lstrip("?") for o in outs]
        if a.cmd in ("inputs", "outputs"):
            if a.under:
                files = under(files, None if a.under == "code" else a.under)
            sys.stdout.write("".join(f + "\0" for f in files))
            return 0
        if a.cmd == "trace-report":
            r = trace_report(a.step, a.dir, a.root, a.data)
            print(json.dumps(r, indent=1))
            return 1 if r["unlisted_reads"] else 0
    except ManifestError as e:
        print(e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
