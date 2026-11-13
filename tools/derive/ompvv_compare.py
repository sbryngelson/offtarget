#!/usr/bin/env python3
"""Compare the omp_vv baseline with the support table, per atom.

    python3 -I tools/derive/ompvv_compare.py
    python3 -I tools/derive/ompvv_compare.py --lang c

Each omp_vv test in results/baseline.jsonl is tagged with the catalog atoms it
uses (offload.engine.ompvv.atoms_of). A copy-semantics test
(offload.engine.ompvv.copy_semantics) is read at HSA_XNACK=0 against our copy-mode
outcome; others at HSA_XNACK=1 against our headline outcome. gfx90a toolchains
use our gfx90a cell. Writes results/ompvv_compare.csv and prints, over
"narrow" tests (at most one base clause), ``ours_ok_suite_fails`` (we say
correct_on_device, every suite test fails) and ``ours_bad_suite_passes`` (we
say rejected, wrong_answer, fell_back_to_host or accepted_ignored, a suite test
passes). ``--lang c`` uses results/baseline_c.jsonl and support_table_c.csv,
and writes results/ompvv_compare_c.csv.
"""
import argparse
import collections
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine.ompvv import (COPY_XNACK, HEADLINE_XNACK,  # noqa: E402,F401
                              atoms_of, clause_items, copy_semantics,
                              directive_lines)
from offload.engine.toolchains import arch_of  # noqa: E402

BASELINE = ROOT / "results" / "baseline.jsonl"
TABLE = ROOT / "results" / "support_table.csv"
OUT = ROOT / "results" / "ompvv_compare.csv"
PATHS = {"f90": (BASELINE, TABLE, OUT),
         "c": (ROOT / "results" / "baseline_c.jsonl",
               ROOT / "results" / "support_table_c.csv",
               ROOT / "results" / "ompvv_compare_c.csv")}

OK = "correct_on_device"
BAD = {"rejected", "wrong_answer", "fell_back_to_host", "accepted_ignored"}
MODE_NAME = {HEADLINE_XNACK: "headline", COPY_XNACK: "copy"}


def read_mode(toolchain: str, test_mode: int) -> int:
    """The HSA_XNACK value a test is read at on a toolchain: its own mode,
    or HSA_XNACK=0 for a gfx90a toolchain."""
    return test_mode if arch_of(toolchain) == "gfx942" else COPY_XNACK


def mode_name(toolchain: str, mode: int) -> str:
    return MODE_NAME[mode] if arch_of(toolchain) == "gfx942" else \
        arch_of(toolchain)


def flag_of(ours, narrow):
    """The disagreement flag of one comparison ('' = none)."""
    if ours == OK and narrow[1] and not narrow[0]:
        return "ours_ok_suite_fails"
    if ours in BAD and narrow[0]:
        return "ours_bad_suite_passes"
    return ""


def ours_from(table) -> dict:
    """(version, atom, toolchain, xnack) -> our outcome, from the legal
    device programs of a support-table CSV (a host+device
    pattern program is not its atom's result)."""
    ours = {}
    for r in table:
        if r["legal"] != "1" or (r.get("scope") or "device") != "device":
            continue
        ours[(r["version"], r["atom"], r["toolchain"], r["xnack"])] = \
            r["outcome"]
    return ours


def ours_in_mode(ours, key, mode):
    """Our outcome for a comparison in `mode` (see the module docstring)."""
    o = ours.get(key + (str(mode),))
    if o is None and mode == COPY_XNACK:
        h = ours.get(key + (str(HEADLINE_XNACK),))
        if h == "rejected":
            return h
    return o


def compare(lang: str = "f90"):
    """(rows, flags, narrow, tests, copy_tests): the compared cells, the
    flagged ones, and the narrow suite tests of each (atom,
    toolchain, read mode) with their status: narrow[(atom, tc, mode)] =
    [(path, status)]."""
    baseline, table_path, _ = PATHS[lang]
    table = list(csv.DictReader(open(table_path)))
    dir_names = {r["atom"][len("omp.directive."):] for r in table
                 if r["atom"].startswith("omp.directive.") and
                 r["atom"].count(".") == 2}
    cl_names = {r["atom"][len("omp.clause."):] for r in table
                if r["atom"].startswith("omp.clause.") and
                r["atom"].count(".") == 2}
    all_atoms = {r["atom"] for r in table}
    ours = ours_from(table)

    # suite verdicts, each test in its mode
    tests = collections.defaultdict(dict)  # path -> (tc, xnack) -> status
    for line in open(baseline):
        b = json.loads(line)
        if b["repo"] != "omp_vv" or b["status"] == "harness_error":
            continue
        tests[b["path"]][(b["toolchain"], b["xnack"])] = b["status"]

    per = collections.defaultdict(lambda: collections.defaultdict(
        lambda: {"all": [0, 0], "narrow": [0, 0]}))
    copy_tests = []
    narrow_tests = collections.defaultdict(list)
    for path, res in tests.items():
        text = (ROOT / "corpus" / "omp_vv" / path).read_text(errors="replace")
        mode = COPY_XNACK if copy_semantics(text) else HEADLINE_XNACK
        if mode == COPY_XNACK:
            copy_tests.append(path)
        dirs, cls = atoms_of(text, dir_names, cl_names, all_atoms)
        tags = [("omp.directive." + d) for d in dirs] + sorted(cls)
        narrow = len({c for c in cls if c.count(".") == 2}) <= 1
        for atom in tags:
            for (tc, xn), st in res.items():
                m = read_mode(tc, mode)
                if xn != m:
                    continue
                for kind in ("all",) + (("narrow",) if narrow else ()):
                    cell = per[atom][(tc, m)][kind]
                    cell[0 if st == "pass" else 1] += 1
                if narrow:
                    narrow_tests[(atom, tc, m)].append((path, st))

    rows, flags = [], []
    for atom in sorted(per):
        for (tc, mode), d in sorted(per[atom].items()):
            for ver in ("52", "60"):
                o = ours_in_mode(ours, (ver, atom, tc), mode)
                if o is None:
                    continue
                n = d["narrow"]
                flag = flag_of(o, n)
                rows.append({"version": ver, "atom": atom, "toolchain": tc,
                             "mode": mode_name(tc, mode), "xnack": mode,
                             "ours": o,
                             "suite_pass": d["all"][0],
                             "suite_fail": d["all"][1],
                             "narrow_pass": n[0], "narrow_fail": n[1],
                             "flag": flag})
                if flag:
                    flags.append(rows[-1])
    return rows, flags, dict(narrow_tests), tests, copy_tests


def render_csv(rows) -> str:
    """The CSV text of the compared cells (results/ompvv_compare*.csv)."""
    import io
    fh = io.StringIO(newline="")
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return fh.getvalue()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lang", choices=sorted(PATHS), default="f90")
    args = ap.parse_args(argv)
    out = PATHS[args.lang][2]
    rows, flags, _, tests, copy_tests = compare(args.lang)
    with open(out, "w", newline="") as fh:
        fh.write(render_csv(rows))
    print(f"{len(tests)} suite tests ({len(copy_tests)} read in copy mode), "
          f"{len(rows)} atom/toolchain/mode cells compared, {len(flags)} "
          f"flagged -> {out}")
    print(collections.Counter(f["flag"] for f in flags))
    for f in flags:
        print("  {version} {toolchain} {mode} {atom}: ours={ours} "
              "narrow {narrow_pass}p/{narrow_fail}f [{flag}]".format(**f))


if __name__ == "__main__":
    sys.exit(main())
