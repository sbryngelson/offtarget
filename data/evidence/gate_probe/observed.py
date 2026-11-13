"""What the probe runs observed per review-queue entry (index k of
data/evidence/gate_probe/jobs.queue()): class counts of every run of the entry's own
program on its own toolchain and mode (probe jobs ``KK/orig``), and of the
gate-runner reruns (data/evidence/gate_probe/gate_rerun.py)."""
from __future__ import annotations

import json
import re
import signal
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def expected_of(rec: dict, item: dict):
    loc = item.get("locator") or {}
    if item["kind"] == "fuzz":
        return loc.get("expected")
    if item["kind"] == "evidence":
        m = re.search(r"checksum=(-?\d+)", loc["ref"].get("expected", ""))
        return int(m.group(1)) if m else None
    if item["kind"] == "stress":
        import sys
        sys.path.insert(0, str(ROOT))
        from offload.engine import gate_stored as GS
        p = GS.stress_program(loc)
        return p.expected if p else None
    return None


def classify(run: dict, expected) -> str:
    if run.get("timed_out"):
        return "timeout"
    out = run.get("stdout") or ""
    m = re.search(r"RESULT checksum=(-?\d+)", out)
    c = re.search(r"RESULT ran_on_host=\d check=(\w+)", out)
    rc = run.get("rc")
    if rc is not None and rc < 0:
        try:
            sig = signal.Signals(-rc).name
        except ValueError:
            sig = f"signal {-rc}"
        val = f" after cs={m.group(1)}" if m else ""
        return f"crash {sig}{val}"
    if rc not in (0, None) and not (m or c):
        return f"exit {rc}"
    if c:
        return "pass" if c.group(1) == "pass" else "wrong (check=fail)"
    if m:
        if expected is not None and int(m.group(1)) == int(expected):
            return "pass"
        return "wrong"
    return f"exit {rc}"


def probe_counts(files, k: int, expected) -> Counter:
    out = Counter()
    for f in files:
        p = Path(f)
        if not p.is_file():
            continue
        for ln in p.read_text().splitlines():
            d = json.loads(ln)
            if d.get("step") != "run" or not d["id"].startswith(f"{k:02d}/orig"):
                continue
            out[classify(d, expected)] += 1
    return out


def gate_rerun_counts(files, k: int) -> Counter:
    out = Counter()
    for f in files:
        p = Path(f)
        if not p.is_file():
            continue
        for ln in p.read_text().splitlines():
            d = json.loads(ln)
            if d.get("k") == k:
                out[d["observed"].split("|")[0] + (
                    " " + d["observed"].split("|")[1][:30]
                    if d["observed"].startswith(("crash", "run_error"))
                    else "")] += 1
    return out


def _value(run: dict, expected) -> str:
    """The class of a run with its value (two wrong answers with different
    values are different outcomes)."""
    c = classify(run, expected)
    m = re.search(r"RESULT checksum=(-?\d+)", run.get("stdout") or "")
    if c == "wrong" and m:
        return f"wrong {m.group(1)}"
    return c


def within_one_environment(files, k: int, expected) -> str:
    """What the probe's repeated runs in one build directory on one node
    showed (the maintainer's question, 2026-10-26: is a disagreement
    between environments really an environment, or nondeterminism within
    one?): per directory, whether its runs agree."""
    per = {}
    for f in files:
        p = Path(f)
        if not p.is_file():
            continue
        for ln in p.read_text().splitlines():
            d = json.loads(ln)
            if d.get("step") != "run" or \
                    not d["id"].startswith(f"{k:02d}/orig"):
                continue
            key = (d["node"], d["dir"].rsplit("/", 1)[-1])
            per.setdefault(key, Counter())[_value(d, expected)] += 1
    if not per:
        return ""
    vary = {k_: c for k_, c in per.items() if len(c) > 1}
    runs = sum(sum(c.values()) for c in per.values())
    if not vary:
        outs = sorted({next(iter(c)) for c in per.values()})
        return (f"{len(per)} directories, {runs} runs: each directory "
                f"agrees with itself ({'; '.join(outs)[:160]})"
                + ("" if len(outs) == 1 else "; the directories differ"))
    parts = [f"{d}: " + ", ".join(f"{o} x{n}" for o, n in c.most_common())
             for (_, d), c in sorted(vary.items())]
    return (f"{len(per)} directories, {runs} runs: the runs in one "
            f"directory disagree ({'; '.join(parts)[:400]})")
