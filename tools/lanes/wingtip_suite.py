#!/usr/bin/env python3
"""The test suite's CPU-only part on wingtip, in parallel, and the list of
what is left for Tuolumne (the `tests` step of tools/lanes/wingtip_offline.yaml).

    tools/lanes/wingtip_offline.sh tests [PYTEST TARGETS...]          # Tuolumne
    python3 -I tools/lanes/wingtip_suite.py [TARGETS...]              # on wingtip

Runs pytest with `-m "not gpu"` minus the `tuolumne_tests`, with pytest-xdist
or round-robin shards, then the step's `serial_tests` alone. WORKERS (default
8) sets the parallelism. Writes results/offline/suite/<lane>.<time>/:
  summary.json   counts, mode, workers, seconds, host
  wingtip.txt    node ids that passed here
  tuolumne.txt   node ids left for Tuolumne, one per line
  failed.txt     failures and errors
  junit*.xml     pytest's reports
Exit 1 on a failure, an error, or a skip for want of a git-ignored input."""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
import wingtip_offline as WO  # noqa: E402

# a skip that means the lane lacked one of its inputs
DATA_GAP = ("needs git-ignored inputs", "results/", "git-ignored",
            "inputs absent")


def in_targets(nid: str, targets) -> bool:
    """Whether pytest TARGETS (directories, files, node ids) select the
    test `nid` (a node id or its prefix)."""
    f = nid.split("::")[0]
    for t in targets:
        t = t.rstrip("/")
        if "::" in t:
            if nid.startswith(t) or t.startswith(nid):
                return True
        elif f == t or f.startswith(t + "/"):
            return True
    return False


def have_xdist() -> bool:
    try:
        import xdist  # noqa: F401
        return True
    except ImportError:
        return False


def nodeid(classname: str, name: str, root: Path = ROOT) -> str:
    """tests.test_x.TestY + test_z[p] -> tests/test_x.py::TestY::test_z[p]."""
    parts = classname.split(".")
    for i in range(len(parts), 0, -1):
        f = "/".join(parts[:i]) + ".py"
        if (root / f).is_file():
            return "::".join([f] + parts[i:] + [name])
    return "::".join(["/".join(parts) + ".py", name])


def read_junit(paths) -> list[dict]:
    out = []
    for p in paths:
        if not Path(p).is_file():
            continue
        for tc in ET.parse(p).getroot().iter("testcase"):
            r = {"id": nodeid(tc.get("classname", ""), tc.get("name", "")),
                 "time": float(tc.get("time") or 0), "outcome": "passed",
                 "reason": ""}
            for tag in ("failure", "error", "skipped"):
                e = tc.find(tag)
                if e is not None:
                    r["outcome"] = {"failure": "failed"}.get(tag, tag)
                    r["reason"] = (e.get("message") or "")[:300]
                    break
            out.append(r)
    return out


def classify(rows, gpu_ids, named) -> dict:
    """{"wingtip": passed here, "failed": failed or errored here,
    "tuolumne": [(id, why)] left for Tuolumne, "gaps": skipped for want
    of a lane input}."""
    res = {"wingtip": [], "failed": [], "tuolumne": [], "gaps": []}
    for r in rows:
        if r["outcome"] == "passed":
            res["wingtip"].append(r["id"])
        elif r["outcome"] in ("failed", "error"):
            res["failed"].append((r["id"], r["reason"]))
        else:
            res["tuolumne"].append((r["id"], "skipped on wingtip: "
                                    + r["reason"]))
            if any(k in r["reason"] for k in DATA_GAP):
                res["gaps"].append((r["id"], r["reason"]))
    res["tuolumne"] += [(i, "gpu marker") for i in sorted(gpu_ids)]
    res["tuolumne"] += [(i, why) for i, why in sorted(named.items())]
    return res


def pytest_cmd(*args) -> list[str]:
    return [sys.executable, "-I", "-m", "pytest", "-p", "no:cacheprovider",
            *args]


def collect(targets, marker: str) -> list[str]:
    r = subprocess.run(pytest_cmd("--collect-only", "-q", "-m", marker,
                                  *targets), cwd=ROOT, capture_output=True,
                       text=True, timeout=600)
    return [ln.strip() for ln in r.stdout.splitlines()
            if "::" in ln and not ln.startswith(" ")]


def shard_files(targets, n: int) -> list[list[str]]:
    files = []
    for t in targets:
        p = ROOT / t
        files += sorted(str(f.relative_to(ROOT)) for f in p.glob(
            "test_*.py")) if p.is_dir() else [t]
    return [s for s in (files[k::n] for k in range(n)) if s]


def main(argv=None) -> int:
    targets = list(argv if argv is not None else sys.argv[1:]) or ["tests"]
    workers = int(os.environ.get("WORKERS") or 16)
    st = WO.step("tests")
    named = {i: w for i, w in (st.get("tuolumne_tests") or {}).items()
             if in_targets(i, targets)}
    serial = [i for i in (st.get("serial_tests") or {})
              if in_targets(i, targets)]
    stamp = time.strftime("%Y%m%dT%H%M%S")
    out = ROOT / "results" / "offline" / "suite" / f"{ROOT.name}.{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    base = Path(os.environ.get("TMPDIR") or "/tmp") / f"wingtip-suite-{os.getpid()}"
    desel = [a for i in list(named) + serial for a in ("--deselect", i)]
    common = ["-m", "not gpu", "-q", "-rfE", *desel]
    t0 = time.time()
    gpu_ids = collect(targets, "gpu")
    if have_xdist():
        mode = f"xdist -n {workers} --dist worksteal"
        junits = [out / "junit.xml"]
        cmd = pytest_cmd("-n", str(workers), "--dist", "worksteal",
                         f"--basetemp={base}", f"--junitxml={junits[0]}",
                         *common, *targets)
        print("$ pytest", " ".join(a for a in cmd[4:] if a != "--deselect"
                                   and a not in named and a not in serial),
              f"({len(named)} left for Tuolumne, {len(serial)} run alone "
              "after)", flush=True)
        subprocess.run(cmd, cwd=ROOT)
    else:
        shards = shard_files(targets, workers)
        mode = f"{len(shards)} file shards"
        junits = [out / f"junit.{k}.xml" for k in range(len(shards))]

        def one(k):
            return subprocess.run(
                pytest_cmd(f"--basetemp={base}.{k}",
                           f"--junitxml={junits[k]}", *common, *shards[k]),
                cwd=ROOT, capture_output=True, text=True)
        with cf.ThreadPoolExecutor(len(shards)) as ex:
            for k, r in enumerate(ex.map(one, range(len(shards)))):
                print(f"--- shard {k}: exit {r.returncode}\n"
                      + r.stdout[-2000:], flush=True)
    if serial:
        # tests that must run alone (they count this user's processes)
        junits.append(out / "junit.serial.xml")
        cmd = pytest_cmd(f"--basetemp={base}.serial", f"--junitxml={junits[-1]}",
                         "-m", "not gpu", "-q", "-rfE", *serial)
        print(f"$ pytest {' '.join(serial)} (alone)", flush=True)
        subprocess.run(cmd, cwd=ROOT)
    rows = read_junit(junits)
    import shutil
    for d in [base, *base.parent.glob(base.name + ".*")]:
        shutil.rmtree(d, ignore_errors=True)
    res = classify(rows, gpu_ids, {i: w for i, w in named.items()})
    secs = round(time.time() - t0)
    (out / "wingtip.txt").write_text("".join(i + "\n" for i in
                                             res["wingtip"]))
    (out / "tuolumne.txt").write_text("".join(
        f"{i}\n" for i, _ in res["tuolumne"]))
    (out / "tuolumne_why.tsv").write_text("".join(
        f"{i}\t{w}\n" for i, w in res["tuolumne"]))
    (out / "failed.txt").write_text("".join(
        f"{i}\t{w}\n" for i, w in res["failed"]))
    summary = {"host": socket.gethostname(), "mode": mode,
               "workers": workers, "targets": targets, "seconds": secs,
               "ran_on_wingtip": len(res["wingtip"]),
               "failed_on_wingtip": len(res["failed"]),
               "left_for_tuolumne": len(res["tuolumne"]),
               "input_gaps": res["gaps"], "out": str(out.relative_to(ROOT))}
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    for i, w in res["failed"]:
        print("FAILED", i, w[:200])
    return 1 if res["failed"] or res["gaps"] else 0


if __name__ == "__main__":
    sys.exit(main())
