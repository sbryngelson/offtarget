#!/usr/bin/env python3
"""Render the vendor packets (data/vendor/<vendor>/) from the
report texts (reports-<vendor>.yaml), the cases (cases.json, src/) and the
check runs (results/*.jsonl), and the overview (data/vendor/README.md and
each vendor's index.md).

    python3 -I data/vendor/checks/render.py

Every output line, result and gate verdict in a packet comes from the runs;
the YAML holds only what a person wrote (title, description, expected
result, spec text, workaround, impact, legality). A report is written as a
draft only when its reproducer is confirmed by the gate on the vendor's
newest release that shows it; otherwise it is listed as held or fixed."""
import difflib
import fnmatch
import hashlib
import json
import re
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
VENDOR = HERE.parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import build  # noqa: E402
import dispositions  # noqa: E402

VTC = {"amd": ["afar"], "hpe": ["cce19", "cce20", "cce21", "cce21_4"],
       "nvidia": ["nvhpc", "nvhpc269"]}
NEWEST = {v: list(reversed(t)) for v, t in VTC.items()}
PRIM = {"amd": "tuolumne", "hpe": "tuolumne", "nvidia": "wingtip"}
VNAME = {"amd": "AMD", "hpe": "HPE", "nvidia": "NVIDIA"}
TCNAME = {"afar": "AFAR 24.3.0", "cce19": "CCE 19.0.0", "cce20": "CCE 20.0.2",
          "cce21": "CCE 21.0.3", "cce21_4": "CCE 21.0.4", "nvhpc": "NVHPC 25.11",
          "nvhpc269": "NVHPC 26.9"}
ALLTC = ["afar", "cce19", "cce20", "cce21", "cce21_4", "nvhpc", "nvhpc269"]
MACH = {"tuolumne": "MI300A", "tioga": "MI250X", "wingtip": "A100"}
TIERS = {1: "wrong answer", 2: "crash, internal compiler error, hang or link failure",
         3: "rejection of a legal program", 4: "lower tier"}
TIERSHORT = {1: "1 wrong answer", 2: "2 crash/ICE/hang/link", 3: "3 rejection", 4: "4 lower tier"}
NOISE = re.compile(r"^(Due to MODULEPATH|The following have been reloaded|\s+\d+\) \S+/\S+|"
                   r"Lmod |Inactive Modules|\s*$|Unloading|Loading|Activating|Warning:\s*$|"
                   r"\s*Headers and libraries from cray-libsci|timeout: the monitored command dumped core)")


SHA = {}
scrub = build.scrub


def mode_name(machine, mode):
    if machine == "wingtip":
        return {0: "separate", 2: "managed"}.get(mode, str(mode))
    return f"XNACK={mode}"


class Data:
    def __init__(self):
        self.cases = {c["id"]: c for c in json.loads((HERE / "cases.json").read_text())}
        self.rows = []
        for ln in build.result_lines(source="compact"):
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if "obs" in r and r.get("case") in self.cases:
                c = self.cases[r["case"]]
                if "sha" in r and c.get(r["variant"]):
                    cur = SHA.setdefault(c[r["variant"]], hashlib.sha256(
                        (HERE / c[r["variant"]]).read_bytes()).hexdigest()[:12])
                    if r["sha"] != cur:
                        continue
                self.rows.append(r)
        self.by = defaultdict(list)
        for r in self.rows:
            self.by[(r["case"], r["variant"], r["tc"], r["machine"], r.get("mode"))].append(r)
        self.ver = defaultdict(dict)
        for ln in build.result_lines(only="versions", source="compact"):
            d = json.loads(ln)
            if "tc" in d:
                self.ver[d["machine"]] = d

    def cell(self, cid, var, tc, mach, mode):
        rs = self.by.get((cid.split("@")[0], var, tc, mach, mode), [])
        per = defaultdict(list)
        for r in rs:
            per[r["env"]].append(build.classify(self.cases[cid], r["obs"], var))
        per = {e: v for e, v in per.items()}
        return rs, per, (build.verdict(per) if per else None)

    def cells(self, cid, var, tcs, machines=("tuolumne", "tioga", "wingtip")):
        out = []
        for tc in tcs:
            for mach in machines:
                for mode in (1, 0, 2):
                    rs, per, v = self.cell(cid, var, tc, mach, mode)
                    if rs:
                        out.append((tc, mach, mode, rs, per, v))
        return out

    def hosts(self, cid):
        h = defaultdict(set)
        for r in self.rows:
            if r["case"] == cid:
                h[r["env"]].add(r.get("host", "?"))
        return h

    def dates(self):
        ds = sorted(r["date"][:10] for r in self.rows if r.get("date"))
        return (ds[0], ds[-1]) if ds else ("", "")


def outline(obs, n=12):
    stage, _, body = obs.partition("\n")
    lines = [l.rstrip() for l in body.splitlines() if not NOISE.match(l)]
    lines = [scrub(l) for l in lines]
    if stage.startswith("COMPILE"):
        keep = [l for l in lines if re.search(
            r"Error message|Assertion|assert|undefined|free\(\)|TERMINATED|INTERNAL|internal compiler|"
            r"LLVM ERROR|PLEASE submit|error:|ERROR|Fatal|fatal error|signal|"
            r"error|Error|ftn-\d|NVFORTRAN-|NVC\+\+-|abort|Abort|failed", l)
            and not re.search(r"WARNING|warning:|Warning", l)]
        lines = keep or lines
    lines = [l[:200] for l in lines]
    if len(lines) > n:
        lines = lines[:n - 1] + [f"... ({len(lines) - n + 1} more lines)"]
    return stage, lines


def short(obs, row=None):
    stage, lines = outline(obs, 4)
    if stage.startswith("COMPILE_TIMEOUT"):
        lim = f" after {round((row or {}).get('compile_s') or 0)} s" if (row or {}).get("compile_s") else ""
        return f"the compile does not finish (killed{lim})"
    if stage.startswith("COMPILE_FAIL"):
        msg = next((l.strip() for l in lines if l.strip()), "")
        return "the build fails: `" + msg[:150].replace("`", "'") + "`"
    if stage.startswith("RUN_TIMEOUT"):
        lim = f" after {round((row or {}).get('run_s') or 0)} s" if (row or {}).get("run_s") else ""
        return f"the run does not finish (killed{lim})"
    if stage.startswith("NOT_APPLICABLE"):
        return "not applicable"
    if stage.startswith("HARNESS"):
        return "no result (harness error)"
    sig = re.search(r"signal=(\d+)", stage)
    rc = re.search(r"rc=(-?\d+)", stage)
    out = "; ".join(l.strip() for l in lines if l.strip())[:400].replace("`", "'")
    if stage.startswith("RUN_OK"):
        return f"prints `{out}`" if out else "runs, exit status 0"
    what = f"signal {sig.group(1)}" if sig else f"exit status {rc.group(1) if rc else '?'}"
    return f"the run ends with {what}" + (f": `{out}`" if out else "")


def gate_label(per):
    envs = "".join(e for e in "abcd" if e in per)
    classes = set(sum(per.values(), []))
    if classes == {"R"}:
        return ("confirmed" if envs == "abcd" else "reproduced") + f" ({' '.join(envs)})"
    if classes == {"P"}:
        return f"correct ({' '.join(envs)})"
    if classes <= {"NA"}:
        return "n/a"
    return " ".join(f"{e}:{''.join(per[e])}" for e in "abcd" if e in per)


WORD = {"R": "defect", "P": "correct", "X": "another failure", "NA": "n/a", "H": "no result"}


def describe(case_key, var, rs):
    """'correct: prints ...', 'defect: ...', or, when the runs differ, each result with its count."""
    d = Data.instance
    case = d.cases[case_key]
    runs = sorted(rs, key=lambda r: r["env"])
    cls = [build.classify(case, r["obs"], var) for r in runs]
    keep = [(c, r) for c, r in zip(cls, runs) if c not in ("NA", "H")]
    if not keep:
        return None
    res = OrderedDict()
    shown = {}
    for c, r in keep:
        txt = short(r["obs"], r)
        k = (c, re.sub(r"0x[0-9a-fA-F]+|node-\d+|\(nil\)", "#", txt))   # addresses differ run to run
        shown.setdefault(k, txt)
        res[k] = res.get(k, 0) + 1
    res = OrderedDict(((c, shown[(c, t)]), n) for (c, t), n in res.items())
    if len(res) == 1:
        (c, txt), = res
        if c == "P" and var == "control" and str(case.get("control_expect", "")).startswith("compile:"):
            return f"as expected for the control: {txt}"
        return f"{WORD.get(c, c)}: {txt}"
    n = len(keep)
    if len({c for c, _ in res}) == 1:
        c = next(iter(res))[0]
        return (f"{WORD.get(c, c)} (the output varies over {n} runs): "
                + "; ".join(f"{txt} ({k} of {n})" for (_, txt), k in res.items()))
    nr = sum(1 for c, _ in keep if c == "R")
    head = f"varies: defect in {nr} of {n} runs" if nr else f"varies over {n} runs"
    return head + "; " + "; ".join(f"{WORD.get(c, c)} ({k} of {n}): {txt}" for (c, txt), k in res.items())


def grouped_table(cells, show_gate=True, case_key=None, var="repro"):
    groups = OrderedDict()
    for tc, mach, mode, rs, per, v in cells:
        classes = tuple(sorted(set(sum(per.values(), []))))
        if classes == ("NA",):
            continue
        key0 = case_key or rs[0]["case"]
        res = describe(key0, var, rs) or "no result"
        key = (tc, res)
        groups.setdefault(key, []).append((mach, mode, gate_label(per)))
    out = ["| compiler | GPU, memory mode | result | gate |", "|---|---|---|---|"]
    for (tc, res), where in groups.items():
        w = []
        for mach in ("tuolumne", "tioga", "wingtip"):
            ms = list(dict.fromkeys(mode_name(m, mo) for m, mo, _ in where if m == mach))
            if ms:
                w.append(f"{MACH[mach]} {', '.join(ms)}")
        gates = list(dict.fromkeys(g for _, _, g in where))
        out.append(f"| {TCNAME[tc]} | {'; '.join(w)} | {res} | {'; '.join(gates)} |")
    if len(out) == 2:
        out.append("| (no runs) | | | |")
    return out


def rep_obs(rs):
    env_a = [r for r in rs if r["env"] == "a"] or rs
    return env_a[0]["obs"]


def vendor_status(cid, vend):
    """(verdict, newest reproducing toolchain, fixed_in, reproducing toolchains) of a case
    on the vendor's primary machine."""
    d = Data.instance
    mach = PRIM[vend]
    rep_tcs = []
    verdict_of = {}
    any_rows = False
    for tc in NEWEST[vend]:
        cells = [c for c in d.cells(cid, "repro", [tc], (mach,)) if c[5] not in (None, "no_rows")]
        if cells:
            any_rows = True
        vs = [c[5] for c in cells if c[5] != "not_reproduced"]
        if vs:
            rep_tcs.append(tc)
            order = ["nondeterministic", "environment", "confirmed_partial", "confirmed"]
            verdict_of[tc] = next(v for v in order if v in vs)
    if not any_rows:
        return "not run", None, None, []
    if not rep_tcs:
        return "not_reproduced", None, None, []
    newest = rep_tcs[0]
    order = NEWEST[vend]
    if order.index(newest) > 0:
        fixed_in = order[order.index(newest) - 1]
        # a release between can still have no rows; take the oldest release newer than newest
        return "fixed", newest, fixed_in, rep_tcs
    return verdict_of[newest], newest, None, rep_tcs


def fence(lang):
    return {"c": "c", "f90": "fortran"}[lang]


def command(case, tc, machine, var="repro"):
    d = Data.instance
    rs = [r for r in d.rows if r["case"] == case["id"] and r["tc"] == tc and
          r["machine"] == machine and r["variant"] == var and r.get("cmd")]
    if not rs:
        return None
    cmd = rs[0]["cmd"]
    cmd = re.sub(r"[^\s'\"]*/therock-afar-24\.3\.0-multiarch-10\.1\.0-592954c/bin/",
                 "$AFAR/bin/", cmd)
    cmd = re.sub(r"/opt/nvidia/hpc_sdk/Linux_x86_64/25\.11/compilers/bin/", "", cmd)
    cmd = re.sub(r"/fastscratch/\S+/26\.9/compilers/bin/", "", cmd)
    cmd = re.sub(r"\$NVHPC_(25_11|26_9)/compilers/bin/", "", cmd)
    cmd = cmd.replace(" -L/usr/lib/gcc/x86_64-redhat-linux/8", "")
    fam = "afar" if tc == "afar" else "nvhpc" if tc.startswith("nvhpc") else "cce"
    lines = []
    if fam == "cce":
        v = {"cce19": ("19.0.0", "6.4.3"), "cce20": ("20.0.2", "6.4.3"), "cce21": ("21.0.3", "7.2.0"),
             "cce21_4": ("21.0.4", "7.2.0")}[tc]
        lines.append(f"module load cce/{v[0]} craype-accel-amd-gfx942 rocm/{v[1]}")
        lines.append("module unload cray-mpich")
    if fam == "nvhpc":
        rel = "25.11" if tc == "nvhpc" else "26.9"
        lines.append(f"export LD_LIBRARY_PATH=$NVHPC_{rel.replace('.', '_')}/compilers/lib  # the release's own runtime")
    lines.append(cmd)
    env = []
    if fam != "nvhpc":
        env.append("HSA_XNACK=1")
    if case.get("model") != "acc":
        env.append("OMP_TARGET_OFFLOAD=mandatory")
    for k, v in (case.get("run_env") or {}).items():
        env.append(f"{k}={v}")
    lines.append(" ".join(env + ["./repro"]))
    return "\n".join(lines)


def diff(a, b, name, what="control"):
    return "\n".join(difflib.unified_diff(a.splitlines(), b.splitlines(), name,
                                          f"{name} ({what})", lineterm="", n=1))


def version_line(tc, lang="f90"):
    d = Data.instance
    m = "wingtip" if tc.startswith("nvhpc") else "tuolumne"
    tcs = d.ver.get(m, {}).get("tc", {})
    v = tcs.get(tc + ":c", "") if lang == "c" else tcs.get(tc, "")
    if not v:
        raise SystemExit(f"no recorded version of {tc} ({lang}) on {m}")
    first = [l for l in v.splitlines() if l.strip() and not NOISE.match(l)]
    if tc == "afar":
        lv = next((l for l in first if "version" in l.lower()), "")
        return (f"`{lv.strip()}`; {'amdclang' if lang == 'c' else 'amdflang'} of the AFAR 24.3.0 drop "
                "(therock-afar-24.3.0-multiarch-10.1.0-592954c), installed as $AFAR")
    if tc.startswith("cce"):
        lv = next((l for l in first if re.search(r"Version|version \d", l)), "")
        v_, r_ = {"cce19": ("19.0.0", "6.4.3"), "cce20": ("20.0.2", "6.4.3"),
                  "cce21": ("21.0.3", "7.2.0"), "cce21_4": ("21.0.4", "7.2.0")}[tc]
        return f"`{lv.strip()}` (module cce/{v_}, craype-accel-amd-gfx942, rocm/{r_}, cray-mpich unloaded)"
    lv = next((l for l in first if re.search(r"\d+\.\d+-\d", l)), "")
    where = ("$NVHPC_25_11 = /opt/nvidia/hpc_sdk/Linux_x86_64/25.11" if tc == "nvhpc"
             else "$NVHPC_26_9 = a user install of the 26.9 release (<prefix>/Linux_x86_64/26.9)")
    return f"`{lv.strip()}`; {where}; each release run with its own runtime libraries"


def system_line(vend, tioga):
    d = Data.instance
    if vend == "nvidia":
        w = d.ver.get("wingtip", {})
        drv = w.get("nvidia-smi", "").splitlines()
        return ("GPU: NVIDIA A100 80GB PCIe (sm_80, `-gpu=cc80`)" +
                (f", driver {drv[-1].split(',')[-1].strip()}" if len(drv) > 1 else "") +
                f"; OS: {(w.get('os') or 'Ubuntu 24.04').split('=')[-1].strip(chr(34))}; "
                "memory modes `-gpu=mem:separate` and `-gpu=mem:managed`")
    t = d.ver.get("tuolumne", {})
    osn = (t.get("os") or "").split("=")[-1].strip('"')
    s = (f"GPU: AMD Instinct MI300A (gfx942, an APU), HSA_XNACK=1 (unified memory) and HSA_XNACK=0 "
         f"(copy mode); OS: {osn} (TOSS 4), kernel {t.get('kernel', '')}")
    if tioga:
        s += "; also AMD Instinct MI250X (gfx90a, a discrete GPU) at HSA_XNACK=0, the same OS"
    return s


def render_report(rep, verdict, newest):
    d = Data.instance
    case = d.cases[rep["primary"]]
    lang = case["lang"]
    src = (HERE / case["repro"]).read_text()
    vend = rep["vendor"]
    fname = case.get("filename") or Path(case["finding"]).name
    cells_all = d.cells(case["id"], "repro", VTC[vend])
    tioga = any(c[1] == "tioga" for c in cells_all)
    L = [f"# {rep['title']}", ""]
    L.append(f"*Draft for {VNAME[vend]}. Tier: {TIERS[rep['tier']]}. "
             f"Gate verdict on {TCNAME[newest]}: {verdict}.*")
    L += ["", "## Description", "", rep["summary"].strip(), "", "## Environment", ""]
    rep_tcs = [t for t in VTC[vend] if any(c[0] == t and c[5] not in (None, "not_reproduced")
                                           for c in cells_all)]
    for tc in rep_tcs or VTC[vend]:
        L.append(f"- {TCNAME[tc]}: {version_line(tc, lang)}")
    L.append(f"- {system_line(vend, tioga)}")
    if vend == "amd" and lang == "f90":
        L.append("- AFAR Fortran links also pass `-L/usr/lib/gcc/x86_64-redhat-linux/8` (the system GCC 8 "
                 "runtime directory on these nodes; a site link path, not part of the defect).")
    fl = case.get("flags") or {}
    fam = {"amd": "afar", "hpe": "cce", "nvidia": "nvhpc"}[vend]
    extra = " ".join(v for k, v in fl.items() if k in ("all", fam))
    L.append(f"- Flags: `{case.get('opt', '-O2')}`" + (f" and `{extra}`" if extra else "") +
             ". One source file, built and run in a node-local directory.")
    L += ["", "## Reproducer", "", f"`{fname}`:", "", f"```{fence(lang)}", src.rstrip(), "```", ""]
    L += ["## Steps to reproduce", ""]
    cmd = command(case, newest, PRIM[vend])
    if cmd:
        L += ["```sh", cmd.replace(case["id"] + (".c" if lang == "c" else ".f90"), fname)
              .replace(" stress.f90", " stress.f90"), "```"]
        modes = sorted({c[2] for c in cells_all if c[0] == newest and c[1] == PRIM[vend]
                        and c[5] not in (None, "not_reproduced")}, reverse=True)
        L.append("")
        if vend != "nvidia":
            L.append("The defect shows at " + " and ".join(f"HSA_XNACK={m}" for m in modes) +
                     (" (the other mode is correct)." if len(modes) == 1 else "."))
        else:
            L.append("The defect shows with " + " and ".join(f"`-gpu=mem:{mode_name('wingtip', m)}`"
                                                             for m in sorted(modes)) + ".")
        if case.get("build_dir"):
            bd = case["build_dir"]["repro"]["a"]
            L.append("")
            L.append(f"Build directory (the defect depends on it): `/tmp/cce-cif/` followed by 202 letters `a` "
                     f"and `-1aa` ({len(bd)} characters); compile there as `stress.f90`.")
        L.append("")
    L += ["## Expected result", "", rep["expected"].strip(), "", "## Actual result", ""]
    if rep.get("actual"):
        L += [rep["actual"].strip(), ""]
    L += grouped_table(cells_all)
    ob = next((c for c in cells_all if c[0] == newest and c[1] == PRIM[vend]
               and c[5] not in (None, "not_reproduced")), None)
    if ob:
        tc, mach, mode, rs, per, v = ob
        stage, lines = outline(rep_obs(rs), 16)
        L += ["", f"Output, {TCNAME[tc]}, {MACH[mach]} {mode_name(mach, mode)}:", "", "```"]
        L += lines
        if stage.startswith("RUN"):
            sig = re.search(r"signal=(\d+)", stage)
            rc = re.search(r"rc=(-?\d+)", stage)
            L.append(f"[signal {sig.group(1)}]" if sig else f"[exit status {rc.group(1) if rc else '?'}]")
        elif stage.startswith("COMPILE_TIMEOUT"):
            L.append("[killed: the compile did not finish]")
        else:
            L.append("[the build fails]")
        L.append("```")
    L += ["", "## Specification", ""]
    for s in rep.get("spec", []):
        L.append(f"{s['ref']}:")
        L.append("")
        L += [f"> {q}" for q in s["quote"].rstrip().splitlines()]
        L.append("")
    if rep.get("vendor_doc"):
        L += [f"Vendor documentation: {rep['vendor_doc'].strip()}", ""]
    L += ["## Control (same compiler, one change)", ""]
    if case.get("control"):
        ctl = (HERE / case["control"]).read_text()
        L.append(f"The control: {case.get('control_what', '').strip()}.")
        L.append("")
        if case.get("control_opt"):
            L += [f"Build flags `{case['control_opt']}` instead of `{case.get('opt', '-O2')}`.", ""]
        if "control_flags" in case:
            L += ["Built without the extra flag.", ""]
        if case.get("control_run_env"):
            L += ["Run with " + " ".join(f"`{k}={v}`" for k, v in case["control_run_env"].items()) + ".", ""]
        if case.get("build_dir"):
            L += [f"Build directory `/tmp/cce-cif/` + 202 letters `a` + `-2aa` (the same length).", ""]
        dd = diff(src, ctl, fname)
        if dd.strip():
            L += ["```diff", dd, "```", ""]
        ccells = d.cells(case["id"], "control", rep_tcs or VTC[vend])
        fx = (case.get("control_run_env") or {}).get("HSA_XNACK")
        if fx is not None:   # the control forces the mode: report the mode it ran in
            ccells = [(t, m, int(fx), rs, per, v) for t, m, mo, rs, per, v in ccells]
        L += grouped_table(ccells, var="control")
    else:
        L.append(rep.get("control_note", "None."))
    L += ["", "## Other compilers", ""]
    L += others(case["id"], vend, rep.get("others_word"))
    if rep.get("others_note"):
        L += ["", rep["others_note"].strip()]
    L.append("")
    shown = [v for v in rep.get("variants", []) if not held_variant(rep, v)]
    if shown:
        L += ["## Variants" + (" (the same shape; a shared cause is inferred, not shown)"
                               if rep.get("variants_inferred") else " (the same defect)"), ""]
        for v in shown:
            L += variant(rep, v)
    L += ["## Workaround", "", rep.get("workaround", "None known.").strip(), "",
          "## Impact", "", rep.get("impact", "").strip(), ""]
    if rep.get("upstream"):
        L += ["## Upstream", "", rep["upstream"].strip(), ""]
    L += ["## Checks", ""]
    d0, d1 = d.dates()
    where_c = {"amd": "on another node", "hpe": "on another node",
               "nvidia": "on another GPU of the same host"}[vend]
    L.append(f"- Run on {d0}" + (f" to {d1}" if d1 != d0 else "") + " on the current installs, in four "
             "environments: (a) a build directory with a short lower-case hexadecimal name, (b) a build "
             "directory named with upper-case letters only, of another length, (c) as (a), " + where_c +
             ", (d) a second compile and run in (a)." + f" Gate verdict on {TCNAME[newest]}: **{verdict}**."
             + (" The MI250X runs are environments (a) and (d) only." if tioga else ""))
    if case.get("build_dir"):
        L.append("- This defect depends on the build path, so environment (b) keeps the `-1` at the same "
                 "offset (202 letters `B` and `-1BB`) and the control uses `-2`.")
    L.append(f"- Legality: {rep['legality'].strip()} No compiler under test, gfortran or gcc was used as a "
             "legality witness.")
    L.append("- Forms named in the description but not shown in the tables (other spellings, flags, "
             "releases) come from the earlier investigation of the finding and were not rerun for this draft.")
    if rep.get("notes"):
        L.append(f"- {rep['notes'].strip()}")
    L += ["", "Found by systematic testing.", ""]
    return "\n".join(L)


def others(cid, vend, words=None):
    """Other vendors' compilers on the reproducer. `words` (report key others_word) overrides the
    label of a toolchain or toolchain@mode (fnmatch), e.g. where a run is not a valid witness."""
    d = Data.instance
    rows = [c for c in d.cells(cid, "repro", [t for t in ALLTC if t not in VTC[vend]])]
    out = []
    groups = OrderedDict()
    for tc, mach, mode, rs, per, v in rows:
        classes = tuple(sorted(set(sum(per.values(), []))))
        if classes == ("NA",):
            continue
        res = describe(cid, "repro", rs) or "no result: "
        word, _, rest = res.partition(": ")
        word = "the same defect" + word[6:] if word.startswith("defect") else word
        for pat, w in (words or {}).items():
            if fnmatch.fnmatch(f"{tc}@{mode}", pat) or fnmatch.fnmatch(tc, pat):
                word = w
                break
        groups.setdefault((tc, word, rest), []).append(f"{MACH[mach]} {mode_name(mach, mode)}")
    for (tc, word, rest), where in groups.items():
        out.append(f"- {TCNAME[tc]} ({', '.join(where)}): {word}; {rest}")
    if not out:
        out.append("- No other compiler ran this program (OpenACC: AFAR has none; NVHPC runs are listed only where made).")
    return out


def vkey(rep, v):
    """The case key of a variant: the case, or a copy with the report's own symptom/expect."""
    d = Data.instance
    cid = v["case"]
    if (v.get("symptom") or v.get("expect")) and cid in d.cases:
        i = rep.get("variants", []).index(v)
        key = f"{cid}@{rep['vendor']}{i}"
        d.cases[key] = dict(d.cases[cid], **{k: v[k] for k in ("symptom", "expect") if k in v})
        return key
    return cid


def held_variant(rep, v):
    """A variant that no rerun reproduced on this vendor's compilers stays out of the draft
    (it is listed as held in the index and the README)."""
    if v["case"] not in Data.instance.cases:
        return False
    return vendor_status(vkey(rep, v), rep["vendor"])[0] in ("not_reproduced", "not run")


def expected_of(case):
    e = case.get("expect", "")
    m = re.match(r"outre:(RESULT checksum=-?\d+)\\b$", e)
    if m:
        return f"`{m.group(1)}`"
    if e.startswith("out:"):
        return f"`{e[4:]}`"
    return None


def variant(rep, v):
    d = Data.instance
    cid = v["case"]
    case = d.cases.get(cid)
    out = [f"### {v.get('title', cid)}", "", v["note"].strip(), ""]
    if case is None:
        return out
    key = vkey(rep, v)
    src = (HERE / case["repro"]).read_text()
    if v.get("max_lines") == 0:
        pass
    elif len(src.splitlines()) <= int(v.get("max_lines", 45)):
        out += [f"```{fence(case['lang'])}", src.rstrip(), "```", ""]
    else:
        out += [f"(Source: {len(src.splitlines())} lines; available on request.)", ""]
    sym = d.cases[key]["symptom"]
    wrongish = any(str(x).startswith("wrong") for x in (sym if isinstance(sym, list) else [sym]))
    exp = v.get("expected") or (expected_of(case) if wrongish else None)
    if exp:
        out += [f"Expected: {exp.strip()}", ""]
    elif wrongish:
        print("WARNING: no expected value for wrong-answer variant", rep["vendor"], cid)
    cells = [c for c in d.cells(key, "repro", VTC[rep["vendor"]]) if c[2] in v.get("modes", (0, 1, 2))]
    out += grouped_table(cells, case_key=key)
    out.append("")
    if v.get("o0_case"):
        out += [f"The same program built at `-O0` (CCE):", ""]
        out += grouped_table(d.cells(v["o0_case"], "repro", VTC[rep["vendor"]]), case_key=v["o0_case"])
        out.append("")
    if v.get("show_control") and case.get("control"):
        ctl = (HERE / case["control"]).read_text()
        out += [f"{v.get('control_label', 'Control')}: {case.get('control_what', '').strip()}.", ""]
        fname = case.get("filename") or cid + (".c" if case["lang"] == "c" else ".f90")
        dd = diff(src, ctl, fname, "control" if not v.get("control_label") else "one change")
        if dd.strip():
            out += ["```diff", dd, "```", ""]
        out += grouped_table(d.cells(cid, "control", VTC[rep["vendor"]]), case_key=cid, var="control")
        out.append("")
    return out


def main():
    Data.instance = d = Data()
    reports = []
    for vend in ("nvidia", "hpe", "amd"):
        p = HERE / f"reports-{vend}.yaml"
        reps = yaml.safe_load(p.read_text()) if p.is_file() else []
        outdir = VENDOR / vend
        outdir.mkdir(exist_ok=True)
        for f in outdir.glob("*.md"):
            f.unlink()
        for i, r in enumerate(reps):
            r["vendor"], r["order"] = vend, i
            r["stem"] = r.get("file") or Path(d.cases[r["primary"]]["finding"]).stem
            verdict, newest, fixed_in, tcs = vendor_status(r["primary"], vend)
            r["verdict"], r["newest"], r["tcs"] = verdict, newest, tcs
            if verdict == "confirmed":
                r["status"] = "draft"
                (outdir / f"{r['stem']}.md").write_text(render_report(r, verdict, newest))
            elif verdict == "fixed":
                r["status"] = f"fixed in {TCNAME[fixed_in]}"
                r["why"] = (f"{TCNAME[newest]} and older show it; {TCNAME[fixed_in]}"
                            f"{' and newer' if NEWEST[vend].index(fixed_in) > 0 else ''} do not")
            elif verdict == "not run":
                r["status"] = "held"
                r["why"] = "not run yet"
            else:
                r["status"] = "held"
                r["why"] = f"gate verdict {verdict}" + (f" on {TCNAME[newest]}" if newest else "")
            reports.append(r)
    rows = write_readme(reports)
    for vend in ("nvidia", "hpe", "amd"):
        write_index(vend, [r for r in reports if r["vendor"] == vend],
                    [x for x in rows if x[1] == vend and not x[3].startswith("draft")])
    (HERE / "reports.json").write_text(json.dumps(
        [{k: r.get(k) for k in ("vendor", "stem", "tier", "status", "verdict", "newest", "tcs",
                                "why", "primary", "title", "order", "findings")}
         for r in reports], indent=1) + "\n")
    print(len(reports), "reports;", sum(r["status"] == "draft" for r in reports), "drafts")


def write_index(vend, reps, rows=()):
    reps = sorted(reps, key=lambda r: (r["tier"], r["order"]))
    L = [f"# {VNAME[vend]} packet: draft bug reports", ""]
    L.append("Each draft is self-contained; read it before anything is filed. Order: tier (wrong answer, "
             "then crash/internal error/hang/link failure, then rejection of a legal program, then lower "
             "tier), then impact. Held and fixed items are listed after the drafts with the reason.")
    L += ["", "| # | tier | report | status | gate |", "|---|---|---|---|---|"]
    n = 0
    for r in reps:
        if r["status"] != "draft":
            continue
        n += 1
        L.append(f"| {n} | {TIERSHORT[r['tier']]} | [{r['title']}]({r['stem']}.md) | draft | "
                 f"{r['verdict']} on {TCNAME[r['newest']]} |")
    rest = [r for r in reps if r["status"] != "draft"]
    if rest:
        L += ["", "Not drafted:", "", "| tier | item | status | why |", "|---|---|---|---|"]
        for r in rest:
            L.append(f"| {TIERSHORT[r['tier']]} | {r['title']} | {r['status']} | {r.get('why', '')} |")
    if rows:
        L += ["", "Findings not in this packet (each with the reason; README.md has every finding):", "",
              "| finding | status | note |", "|---|---|---|"]
        for f, v, t, st, rp, ver, why in rows:
            L.append(f"| `{f}` | {st} | {why} |")
    (VENDOR / vend / "index.md").write_text("\n".join(L) + "\n")


def write_readme(reports):
    import readme
    return readme.write(Data.instance, reports, dispositions, vendor_status, TCNAME, TIERSHORT, vkey)


if __name__ == "__main__":
    main()
