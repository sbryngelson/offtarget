"""Harvest programs from the ROCm/aomp test suites beyond test/smoke and test/smoke-fails.

* The Makefile suites (``SMOKE_SUITES``: smoke-fort, smoke-fort-dev,
  smoke-fort-fails, smoke-fort-limbo, smoke-dev, smoke-limbo, smoke-training,
  omp5, usm) are read, filtered and converted with offload.engine.harvest.inventory.aomp_record,
  filters.classify and convert.convert. Program ids start ``h2-aomp-``.
  smoke-asan is left out because its programs are erroneous on purpose.
* test/fortran-map-tests holds single self-checking Fortran files (``map_test``).
  The oracle is the exit status (STOP n or ERROR STOP on a wrong result) plus the
  ``Test Passed`` line, or without a STOP the ``Test Failed`` / ``Test Passed``
  pair. A file with no self-check is dropped.
The repository is Apache-2.0; a file's own SPDX line (fortran-map-tests: MIT) is
recorded when present."""
from __future__ import annotations

import hashlib
import re

from offload.engine.harvest import checks as K
from offload.engine.harvest import convert as HC
from offload.engine.harvest import filters as HF

SMOKE_SUITES = ("smoke-fort", "smoke-fort-dev", "smoke-fort-fails",
                "smoke-fort-limbo", "smoke-dev", "smoke-limbo",
                "smoke-training", "omp5", "usm")
REPO_LICENSE = "Apache-2.0 (ROCm/aomp LICENSE)"
URL = "https://github.com/ROCm/aomp/blob/{commit}/test/{path}"


def spdx(text: str) -> str | None:
    m = re.search(r"SPDX-License-Identifier:\s*([\w.+-]+(?:\s+WITH\s+[\w.+-]+)?)",
                  text)
    return m.group(1) if m else None


def license_of(text: str) -> str:
    s = spdx(text)
    return f"{s} (the file's SPDX line; repository {REPO_LICENSE})" if s \
        else REPO_LICENSE


def relabel(src: str, lang: str) -> str:
    """The first header line of a program converted by tools/campaigns/harvest.py names this task."""
    old = "Harvested test (tools/campaigns/harvest.py convert; do not edit)"
    new = "Harvested test (tools/campaigns/harvest2.py aomp; do not edit)"
    return src.replace(old, new, 1)


# --- fortran-map-tests -------------------------------------------------------------------

_STOP = re.compile(r"^\s*(?:if\s*\(.*\)\s*)?(?:error\s+stop|stop\s+[1-9]\d*)\b",
                   re.I | re.M)
_PASSED = re.compile(r"print\s*\*\s*,\s*['\"][^'\"]*Test\s+passed", re.I)
_FAILED = re.compile(r"print\s*\*\s*,\s*['\"][^'\"]*Test\s+failed", re.I)


def map_test(path: str, text: str, commit: str) -> dict:
    """The record of one test/fortran-map-tests file: reasons, checks."""
    code = HF._strip_comments(text, "f90")
    reasons = list(HF.source_reasons(text, "f90", "omp"))
    stop = bool(_STOP.search(code))
    passed, failed = bool(_PASSED.search(code)), bool(_FAILED.search(code))
    checks: list[str] = []
    word = "Test passed" if re.search(r"Test passed", code) else "Test Passed"
    if stop:
        if passed:
            checks = [f"CHECK: {word}"]
    elif passed and failed:
        checks = ["CHECK-NOT: Test Failed", f"CHECK: {word}"]
    else:
        reasons.append("no_self_check")
    if re.search(r"^\s*#", text, re.M) and not path.endswith(".F90"):
        reasons.append("preprocessor")
    if not re.search(r"^\s*program\s+\w+", code, re.I | re.M):
        reasons.append("no_main")
    return {"id": f"aomp/{path}", "rel": path, "source": "aomp",
            "suite": path.split("/")[0], "lang": "f90", "model": "omp",
            "commit": commit, "license": license_of(text),
            "url": URL.format(commit=commit[:12], path=path),
            "project": "ROCm/aomp", "reasons": reasons, "checks": checks,
            "stop": stop}


def convert_map_test(r: dict, text: str) -> dict:
    cs = K.parse_checks("\n".join("! " + c for c in r["checks"]),
                        ("CHECK",)) if r["checks"] else []
    v = {"flags": [], "prefixes": ["CHECK"] if cs else []}
    src, edits = HC.convert_f(text, cs, v)
    version, gerr = HC.spec_version(text, "f90", [], "omp")
    oracle = "filecheck" if cs else "exit_status"
    modes = ["unified"] if re.search(r"requires\b[^\n]*unified_shared_memory",
                                     text, re.I) else ["copy", "unified"]
    head = [
        "Harvested test (tools/campaigns/harvest2.py aomp; do not edit)",
        f"source: {r['url']}",
        f"license: {r['license']}",
        f"original sha256: {hashlib.sha256(text.encode()).hexdigest()}",
        f"modes: {', '.join(modes)}",
        f"spec version: OpenMP {version // 10}.{version % 10} (the grammar "
        "reads every directive at it)",
        "expected: exit status 0 (the test's own check: STOP n or ERROR STOP "
        "on a wrong result)" if r["stop"] else "expected: exit status 0",
    ]
    if cs:
        head[-1] += (f"; the output matches {len(cs)} CHECK lines (its "
                     "Test Passed / Test Failed lines)")
    head += ["self-check: RESULT ran_on_host=<0|1> check=<pass|fail>",
             "edits: " + "; ".join(edits + ["self-check appended"])]
    src = "\n".join("! " + ln for ln in head) + "\n" + src
    stem = r["rel"].rsplit(".", 1)[0]
    pid = "h2-aomp-" + re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower()
    return {"id": pid, "record": r["id"], "lang": "f90", "model": "omp",
            "version": version, "source": src, "oracle": oracle,
            "checks": len(cs), "prefixes": ["CHECK"] if cs else [],
            "modes": modes, "edits": edits, "grammar_errors": gerr,
            "url": r["url"], "license": r["license"], "project": "ROCm/aomp",
            "suite": r["suite"], "commit": r["commit"], "gpl": False,
            "original_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "source_kind": "test-suite"}
