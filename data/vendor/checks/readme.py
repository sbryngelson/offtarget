"""Docs/vendor/README.md (written by render.py)."""
import re
from collections import Counter, defaultdict
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def findings_list():
    """The findings the packets cover (checks/findings.txt, a committed snapshot of
    data/findings/index.yaml and data/findings/fuzz/, so the README renders the same from a clean checkout)."""
    return [l.strip() for l in (HERE / "findings.txt").read_text().splitlines()
            if l.strip() and not l.startswith("#")]


def write(d, reports, disp, vendor_status, TCNAME, TIERSHORT, vkey=None):
    case_of = {}
    for cid, c in d.cases.items():
        case_of.setdefault(c["finding"], cid)
    rep_of = defaultdict(list)          # (finding, vendor) -> [(report, role)]
    for r in reports:
        prim = d.cases[r["primary"]]["finding"] if r["primary"] in d.cases else None
        for f in r.get("findings", []):
            rep_of[(f, r["vendor"])].append((r, "reproducer" if f == prim else "variant"))
    # a finding that is the reproducer of one report and a variant of another is listed by the first
    for k in rep_of:
        rep_of[k].sort(key=lambda x: (x[1] != "reproducer", x[0]["status"] != "draft"))
    rows = []
    unassigned = []
    for f in findings_list():
        cid = case_of.get(f)
        vends = set(v for (ff, v) in rep_of if ff == f)
        vends |= set(v for (ff, v) in disp.MANUAL if ff == f)
        if cid:
            cv = d.cases[cid]["vendor"]
            vends |= set(cv if isinstance(cv, list) else [cv])
        if not vends:
            vends = {"?"}
        for v in sorted(vends):
            verdict = "-"
            if cid and v in ("amd", "hpe", "nvidia"):
                vv, newest, fixed_in, tcs = vendor_status(cid, v)
                verdict = (f"{vv} ({TCNAME[newest]})" if newest and vv != "fixed"
                           else f"fixed in {TCNAME[fixed_in]}" if vv == "fixed" else vv)
            if (f, v) in rep_of:
                r, role = rep_of[(f, v)][0]
                status = r["status"] + (" (variant)" if role == "variant" else "")
                if role == "variant" and cid and v in ("amd", "hpe", "nvidia"):
                    key = cid
                    for var in r.get("variants", []):
                        if var["case"] == cid:
                            key = vkey(r, var)
                            break
                    vv0, nw0, fx0, _ = vendor_status(key, v)
                    verdict = (vv0 if vv0 == "not_reproduced" else f"fixed in {TCNAME[fx0]}" if vv0 == "fixed"
                               else f"{vv0} ({TCNAME[nw0]})" if nw0 else vv0)
                    if vv0 in ("not_reproduced", "not run"):
                        status = "held: not reproducible (not in the draft)"
                    elif vv0 == "fixed":
                        status = f"fixed in {TCNAME[fx0]} (shown in the report as a variant)"
                rows.append((f, v, TIERSHORT[r["tier"]], status, f"[{r['stem']}]({v}/{r['stem']}.md)"
                             if r["status"] == "draft" and not status.startswith("held") else r["stem"],
                             verdict, r.get("why", "")))
            elif (f, v) in disp.MANUAL:
                st, why = disp.MANUAL[(f, v)]
                rows.append((f, v, "-", st, "-", verdict, why))
            elif cid and v in ("amd", "hpe", "nvidia"):
                vv, newest, fixed_in, tcs = vendor_status(cid, v)
                if vv == "fixed":
                    note = getattr(disp, "FIXED_NOTE", {}).get((f, v))
                    rows.append((f, v, "-", f"fixed in {TCNAME[fixed_in]}", "-", verdict,
                                 f"{TCNAME[newest]} shows it, {TCNAME[fixed_in]} does not"
                                 + (f"; {note}" if note else "")))
                elif vv == "not_reproduced":
                    rows.append((f, v, "-", "held: not reproducible", "-", verdict,
                                 "no rerun reproduced the recorded failure"))
                elif vv == "not run":
                    rows.append((f, v, "-", "held: not run", "-", verdict, ""))
                elif vv == "confirmed":
                    rows.append((f, v, "-", "UNASSIGNED", "-", verdict, ""))
                    unassigned.append((f, v))
                else:
                    rows.append((f, v, "-", f"held: {vv}", "-", verdict,
                                 "the reruns do not agree with each other (gate)"))
            else:
                rows.append((f, v, "-", "UNASSIGNED", "-", verdict, ""))
                unassigned.append((f, v))
    VN = {"amd": "AMD", "hpe": "HPE", "nvidia": "NVIDIA", "?": "?"}
    cnt = Counter()
    for r in reports:
        cnt[(r["vendor"], r["tier"], r["status"] if r["status"] in ("draft", "held") else "fixed")] += 1
    d0, d1 = d.dates()
    L = ["# Vendor report packets (drafts)", ""]
    L.append("Draft bug reports for NVIDIA (NVHPC), HPE (CCE) and AMD (AFAR), one file per report, written "
             "for the maintainer to read and decide what to file. Nothing here has been sent, filed, posted or "
             "emailed. Each draft names the compilers and installs it was checked on; any text may be "
             "changed before it is used.")
    L += ["", "- [NVIDIA packet](nvidia/index.md)", "- [HPE packet](hpe/index.md)", "- [AMD packet](amd/index.md)", ""]
    L += ["## How each report was checked", ""]
    L.append(f"- Every finding file was re-run on {d0}" + (f" to {d1}" if d1 != d0 else "") + " on the current installs: AFAR 24.3.0 (amdflang/"
             "amdclang 24.0.0git) and CCE 19.0.0, 20.0.2, 21.0.3 and 21.0.4 (the newest installed) on MI300A "
             "(Tuolumne, gfx942) at HSA_XNACK=1 and 0 and on MI250X (Tioga, gfx90a) at HSA_XNACK=0; NVHPC "
             "25.11 and 26.9 on an A100 (wingtip) in separate and managed memory. The reproducer is the "
             "finding file with the catalog's comments removed (`checks/build.py`); for some generated "
             "(fuzz) programs it is a hand reduction (unused declarations, modules and procedures removed; "
             "`text` in `checks/cases.yaml`), kept only where the reduced program still shows the defect. "
             "A generated program's constant `ran_on_host=0` field is dropped from its output line. The "
             "text in each draft is the text that was compiled; each result row records the hash of the "
             "source it ran, and rows of an older source are not used.")
    L.append("- Reproduction gate (the environments of `tools/campaigns/gate.py` "
             "were applied by hand, `checks/run_checks.py`): (a) a build directory "
             "`harness_<8 hex>`, (b) a directory named with upper-case letters only (`GATE` + 14 letters), "
             "(c) as (a) on a second node (wingtip: a second GPU), (d) a second compile and run in (a). "
             "`confirmed`: every environment shows the defect; a report is drafted only when its reproducer "
             "is confirmed on the vendor's newest release that shows it (CCE 21.0.4, NVHPC 26.9, AFAR "
             "24.3.0). MI250X runs are (a) and (d).")
    L.append("- Control: the same program with one change (named in each draft) gives the expected result on "
             "the same compiler; it was run in the same four environments.")
    L.append("- Legality: each draft restates the finding's basis in one line. No compiler under test, and "
             "never gfortran or gcc, is a legality witness. Spec quotes were checked against the text of the "
             "specification PDFs (`spec/`), with printed page numbers (`offload.engine.spec_text`).")
    L.append("- A defect that the newest release no longer shows is listed as fixed, not drafted. CCE 19/20-"
             "only defects are therefore not in the HPE packet.")
    L.append("- Runs: `checks/results-compact/` (committed; one JSON line per compile and run, without "
             "compile logs, host names or private paths), `checks/summary.json`; "
             "`python3 -I data/vendor/checks/render.py` regenerates every page from committed files only "
             "(the finding list is the snapshot `checks/findings.txt`), so a clean checkout renders the same "
             "pages. `build.py pack` makes the compact files from the full local `checks/results/` (git-ignored).")
    L.append("- Errors found in the finding files on the way (claims the reruns contradict, citation pages): "
             "[errata-for-findings.md](errata-for-findings.md); data/findings/ was not edited.")
    L += ["", "## Counts", ""]
    L += ["| vendor | tier | drafts | held | fixed |", "|---|---|---|---|---|"]
    for v in ("nvidia", "hpe", "amd"):
        for t in (1, 2, 3, 4):
            a, h, fx = cnt[(v, t, "draft")], cnt[(v, t, "held")], cnt[(v, t, "fixed")]
            if a or h or fx:
                L.append(f"| {VN[v]} | {TIERSHORT[t]} | {a} | {h} | {fx} |")
    for v in ("nvidia", "hpe", "amd"):
        tot = sum(cnt[(v, t, "draft")] for t in (1, 2, 3, 4))
        L.append(f"| {VN[v]} | all | {tot} | {sum(cnt[(v, t, 'held')] for t in (1, 2, 3, 4))} | "
                 f"{sum(cnt[(v, t, 'fixed')] for t in (1, 2, 3, 4))} |")
    L += ["", "Reports group findings that share a cause; held and fixed reports would be counted above (none "
          "after the reruns). Findings per vendor and status (a finding listed in two packets counts in each):", ""]
    fc = Counter()
    for f, v, t, st, rp, ver, why in rows:
        key = st.replace(" (variant)", "")
        key = "held: not reproducible" if key.startswith("held: not reproducible") else key
        fc[(v, key)] += 1
    L += ["| vendor | status | findings |", "|---|---|---|"]
    for (v, st), n in sorted(fc.items()):
        L.append(f"| {VN[v]} | {st} | {n} |")
    L += ["", "## Every finding", ""]
    L.append("One row per finding and vendor. Status: draft (a report of the packet; `variant` when the "
             "finding is listed inside another report), held (with why), fixed, or not a report. Gate: the "
             "verdict of the finding's own reproducer on the vendor's newest release that shows it.")
    L += ["", "| finding | vendor | tier | status | report | gate | note |", "|---|---|---|---|---|---|---|"]
    for f, v, t, st, rp, ver, why in rows:
        L.append(f"| `{f}` | {VN[v]} | {t} | {st} | {rp} | {ver} | {why} |")
    (HERE.parent / "README.md").write_text("\n".join(L) + "\n")
    if unassigned:
        print("UNASSIGNED:", unassigned)
    return rows
