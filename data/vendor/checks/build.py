#!/usr/bin/env python3
"""Build the vendor packets' checks.

    python3 -I data/vendor/checks/build.py src      # cases.yaml -> src/, cases.json
    python3 -I data/vendor/checks/build.py summary  # results/*.jsonl -> summary.json

src: a case's reproducer is its finding file (data/findings/) with the
catalog's comments removed, then the case's `edits` (or its `text`, a hand
reduction). Its control is the reproducer with the case's `control` edits,
or a named file trimmed the same way. Constant ran_on_host fields and
unused omp_is_initial_device imports are dropped.
summary: each result row is matched against its case's `repro` and `pass`
patterns, and each (case, toolchain, mode) gets the gate verdict over
environments a, b, c, d (offload/engine/gate.py): confirmed, nondeterministic,
environment or not_reproduced. Patterns: compile:RE, hang, crash:RE,
runhang, wrong[:RE], out:S, ok, re:RE."""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FINDINGS = ROOT / "data" / "findings"


def trim(text: str, lang: str) -> str:
    out = []
    if lang == "c":
        text = re.sub(r"/\*.*?\*/\n?", "", text, flags=re.S)
        for ln in text.splitlines():
            if ln.lstrip().startswith("//"):
                continue
            out.append(ln.rstrip())
    else:
        for ln in text.splitlines():
            s = ln.lstrip()
            if s.startswith("!") and not s.startswith("!$") and \
                    not s.lower().startswith("!dir$"):
                continue
            out.append(ln.rstrip())
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out) + "\n"


def apply_edits(text: str, edits, where: str) -> str:
    for old, new in edits or []:
        n = text.count(old)
        if n != 1:
            raise SystemExit(f"{where}: edit {old!r} occurs {n} times")
        text = text.replace(old, new)
    return text


RAN0 = re.compile(r"print '\(a,i0,a,i0\)', ('RESULT checksum=', .+?), ' ran_on_host=', 0$", re.M)


RANMAX = re.compile(r"print '\(a,i0,a,i0\)', ('RESULT checksum=', .+?), ' ran_on_host=', max\(\w+(?:, \w+)*, 0\)$", re.M)


def drop_literal_flag(text: str, lang: str) -> str:
    if lang != "f90":
        return text
    text = RAN0.sub(r"print '(a,i0)', \1", text)
    if not re.search(r"omp_is_initial_device\s*\(", text, re.I):   # a flag that nothing sets
        text = RANMAX.sub(r"print '(a,i0)', \1", text)
    if len(re.findall(r"omp_is_initial_device", text, re.I)) == 1:
        text = re.sub(r"^\s*use omp_lib, only: omp_is_initial_device\n", "", text, flags=re.M | re.I)
    text = re.sub(r"(use omp_lib, only: .*?), omp_is_initial_device$",
                  lambda m: m.group(0) if len(re.findall("omp_is_initial_device", text)) > 1 else m.group(1),
                  text, flags=re.M)
    return text


def load():
    return yaml.safe_load((HERE / "cases.yaml").read_text())


def lang_of(path: str) -> str:
    return "c" if path.endswith(".c") else "f90"


def cmd_src():
    cases = load()
    seen = set()
    out = []
    for c in cases:
        cid = c["id"]
        if cid in seen:
            raise SystemExit(f"duplicate case {cid}")
        seen.add(cid)
        f = FINDINGS / c["finding"]
        lang = lang_of(c["finding"])
        raw = f.read_text()
        model = c.get("model") or ("acc" if re.search(r"^\s*(!\$acc|#pragma acc)", raw, re.M | re.I)
                                   else "omp")
        if "text" in c:
            text = c["text"].rstrip() + "\n"
        else:
            text = raw if c.get("trim") is False else trim(raw, lang)
        text = apply_edits(text, c.get("edits"), cid)
        ext = ".c" if lang == "c" else ".f90"
        d = HERE / "src" / (re.match(r"cce|fuzz|afar|nvhpc", cid).group(0) if re.match(r"cce|fuzz|afar|nvhpc", cid) else "other")
        d.mkdir(parents=True, exist_ok=True)
        rp = d / (cid + ext)
        rp.write_text(drop_literal_flag(text, lang))
        rec = {k: v for k, v in c.items() if k not in ("control", "edits", "text")}
        rec.update(lang=lang, model=model, repro=str(rp.relative_to(HERE)))
        ctl = c.get("control")
        if ctl:
            if "text" in ctl:
                ct = ctl["text"].rstrip() + "\n"
            elif "file" in ctl:
                ct = trim((ROOT / ctl["file"]).read_text(), lang)
                ct = apply_edits(ct, ctl.get("edits"), cid + " control")
            else:
                ct = apply_edits(text, ctl["edits"], cid + " control")
            (d / "control").mkdir(exist_ok=True)
            cp = d / "control" / (cid + "-control" + ext)
            cp.write_text(drop_literal_flag(ct, lang))
            rec["control"] = str(cp.relative_to(HERE))
            rec["control_what"] = ctl.get("what", "")
        out.append(rec)
    (HERE / "cases.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"{len(out)} cases, {sum(1 for r in out if r.get('control'))} controls")


def matches(pat: str, obs: str) -> bool:
    stage = obs.split(" ", 1)[0].split("\n", 1)[0]
    body = obs.split("\n", 1)[1] if "\n" in obs else ""
    kind, _, arg = pat.partition(":")
    if kind == "compile":
        return stage == "COMPILE_FAIL" and re.search(arg, body, re.S) is not None
    if kind == "hang":
        return stage == "COMPILE_TIMEOUT"
    if kind == "crash":
        return stage == "RUN_FAIL" and (arg in ("", ".") or re.search(arg, body, re.S) is not None)
    if kind == "runhang":
        return stage == "RUN_TIMEOUT"
    if kind == "out":
        return stage == "RUN_OK" and arg in body
    if kind == "outre":
        return stage == "RUN_OK" and re.search(arg, body, re.S) is not None
    if kind == "ok":   # ran to completion and its own self-check, if it prints one, passed
        return stage == "RUN_OK" and re.search(r"\bcheck=fail\b", body) is None
    if kind == "re":
        return re.search(arg, obs, re.S) is not None
    raise ValueError(pat)


def classify(case, obs: str, variant: str = "repro") -> str:
    """R reproduces, P passes, X something else, NA not applicable."""
    if variant == "control":
        case = dict(case, **{k[8:]: v for k, v in case.items() if k.startswith("control_")})
    if obs.startswith("NOT_APPLICABLE"):
        return "NA"
    if obs.startswith("HARNESS_ERROR"):
        return "H"
    pats = case["symptom"] if isinstance(case["symptom"], list) else [case["symptom"]]
    passp = case.get("expect", "ok")
    stage = obs.split(" ", 1)[0]
    if matches(passp, obs):
        return "P"
    for p in pats:
        if p.startswith("wrong"):
            _, _, arg = p.partition(":")
            sig = re.search(r"^RUN_FAIL rc=-?\d+ signal=", obs) is not None
            if stage in ("RUN_OK", "RUN_FAIL") and not sig and \
                    (not arg or re.search(arg, obs, re.S)):
                return "R"
        elif matches(p, obs):
            return "R"
    return "X"


def verdict(per_env: dict) -> str:
    """per_env: env -> list of classes (R/P/X) over its rows."""
    valid = {e: [c for c in v if c not in ("H", "NA")] for e, v in per_env.items()}
    valid = {e: v for e, v in valid.items() if v}
    if not valid:
        return "no_rows"
    if not any("R" in v for v in valid.values()):
        return "not_reproduced"
    if any(len(set(v)) > 1 for v in valid.values()):
        return "nondeterministic"
    a, d = valid.get("a"), valid.get("d")
    if a and d and set(a) != set(d):
        return "nondeterministic"
    if all(set(v) == {"R"} for v in valid.values()):
        return "confirmed" if all(e in valid for e in "abcd") else "confirmed_partial"
    return "environment"


def result_lines(skip=("versions",), only=None, source="raw"):
    """The result rows: the raw files (results/*.jsonl, git-ignored) or, with source="compact" or
    when there are no raw files, the committed compact copies (results-compact/, what render.py reads,
    so a clean checkout renders the same pages)."""
    import gzip
    raw = sorted((HERE / "results").glob("*.jsonl"))
    if raw and source == "raw":
        for f in raw:
            if (only and f.name.startswith(only)) or (not only and not f.name.startswith(skip)):
                yield from (l for l in f.read_text().splitlines() if l.strip())
        return
    for f in sorted((HERE / "results-compact").glob("*.jsonl.gz")):
        if (only and f.name.startswith(only)) or (not only and not f.name.startswith(skip)):
            with gzip.open(f, "rt") as fh:
                yield from (l for l in fh.read().splitlines() if l.strip())


# committed and vendor-facing text names no user, host or private path
SCRUB = [(re.compile(r"[^\s'\"]*/therock-afar-24\.3\.0-multiarch-10\.1\.0-592954c"), "$AFAR"),     # wherever the release is installed
         (re.compile(r"/fastscratch/[^/\s]+/nvhpc/Linux_x86_64/26\.9"), "$NVHPC_26_9"),
         (re.compile(r"/opt/nvidia/hpc_sdk/Linux_x86_64/25\.11"), "$NVHPC_25_11"),
         (re.compile(r"/tmp/[\w.-]*-t44/(harness_[0-9a-f]{8}|GATE[A-Z]{14})/[^/\s]+/"), "<dir>/"),
         (re.compile(r"/tmp/cce-cif/\S+?/"), "<dir>/"),
         (re.compile(r"/tmp/[\w.-]*-t44/\S*"), "<dir>"),
         (re.compile(r"/(g/g\d+|nethome|p/lustre5|p/vast1|fastscratch|usr/workspace|work1|var/tmp)/[A-Za-z0-9_]+\b"), "<home>"),
         (re.compile(r"\b(tuolumne\d+|tioga\d+|wingtip-gpu\d+(\.cc\.gatech\.edu)?)\b"), "<host>")]


def scrub(t):
    for rx, rp in SCRUB:
        t = rx.sub(rp, t)
    return t




def cmd_summary():
    cases = {c["id"]: c for c in json.loads((HERE / "cases.json").read_text())}
    rows = []
    for ln in result_lines():
        r = json.loads(ln)
        if r.get("case") in cases and "obs" in r and "machine" in r:
            if r.get("variant") == "control" and not cases[r["case"]].get("control"):
                continue    # a control dropped from its case (its rows stay in the results)
            rows.append(r)
    cells = defaultdict(lambda: defaultdict(list))
    for r in rows:
        c = cases[r["case"]]
        cls = classify(c, r["obs"], r["variant"])
        key = (r["case"], r["variant"], r["tc"], r["machine"], r.get("mode"))
        cells[key][r["env"]].append(cls)
    summ = defaultdict(dict)
    for (cid, var, tc, mach, mode), per_env in cells.items():
        k = f"{var}|{tc}|{mach}|{mode}"
        summ[cid][k] = {"verdict": verdict(per_env),
                        "envs": {e: "".join(v) for e, v in sorted(per_env.items())}}
    (HERE / "summary.json").write_text(json.dumps(summ, indent=1, sort_keys=True) + "\n")
    print(f"{len(rows)} rows, {len(summ)} cases")


def cmd_pack():
    """results/*.jsonl -> results-compact/*.jsonl.gz (committed; render.py reads only these): the
    compile log, host name and build directory are dropped, and the observation, the command and the
    version strings are scrubbed of users, hosts and private paths (scrub)."""
    import gzip
    out = HERE / "results-compact"
    out.mkdir(exist_ok=True)
    for f in sorted((HERE / "results").glob("*.jsonl")):
        rows = []
        for ln in f.read_text().splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            for k in ("compile_log", "host", "build_dir"):
                r.pop(k, None)
            for k in ("obs", "cmd", "os"):
                if isinstance(r.get(k), str):
                    r[k] = scrub(r[k])
            if isinstance(r.get("tc"), dict):
                r["tc"] = {k: scrub(v) for k, v in r["tc"].items()}
            rows.append(json.dumps(r, sort_keys=True))
        with open(out / (f.name + ".gz"), "wb") as raw_fh, \
                gzip.GzipFile(filename="", mode="wb", fileobj=raw_fh, mtime=0) as fh:
            fh.write(("\n".join(rows) + "\n").encode())
        print(f.name, len(rows))


if __name__ == "__main__":
    {"src": cmd_src, "summary": cmd_summary, "pack": cmd_pack}[sys.argv[1]]()
