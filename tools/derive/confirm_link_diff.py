#!/usr/bin/env python3
"""The confirmer's links (findings.dedupe,
related=True, the default keyword: the confirmer's call) on the stored rows
that a change to the linking could touch, under 439620b's offload/engine/confirm/findings.py
and data/findings/index.yaml (read from git) and under the working tree's.
Rows: every run_error "exit_status: 1" row, every AFAR row of the wrong
group, every row naming the dist_schedule chunk finding, of
results/confirm/batch_full, batch_s1.final and batch_widen.

    python3 -I tools/derive/confirm_link_diff.py      # prints the rows that differ
"""
import importlib.util, json, re, subprocess, sys, tempfile
from pathlib import Path
MAIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(MAIN))
from offload.engine.confirm import findings as NEW
from offload.engine.confirm import programs as P

def old_module():
    src = subprocess.run(["git", "show", "439620b:compliance/confirm/findings.py"],
                         cwd=MAIN, capture_output=True, text=True, check=True).stdout
    idx = subprocess.run(["git", "show", "439620b:docs/findings/index.yaml"],
                         cwd=MAIN, capture_output=True, text=True, check=True).stdout
    src = src.replace("from compliance", "from offload.engine").replace("import compliance", "import offload.engine")   # the package was renamed
    d = Path(tempfile.mkdtemp())
    (d / "old_findings.py").write_text(src)
    spec = importlib.util.spec_from_file_location("old_findings", d / "old_findings.py")
    m = importlib.util.module_from_spec(spec); sys.modules["old_findings"] = m; spec.loader.exec_module(m)
    fd = d / "data" / "findings"
    fd.mkdir(parents=True)
    for x in (MAIN / "data" / "findings").iterdir():
        if x.name != "index.yaml":
            (fd / x.name).symlink_to(x)
    (fd / "index.yaml").write_text(idx)
    m.ROOT = d
    fs = m.load_index(fd / "index.yaml")
    return m, fs

def norm(f):
    return re.sub(r"^.*?(?:data/findings/|/tmp[^/]*/[^/]*/)", "", f)

fuzz_meta = {}
def fuzz_text(prog, origin):
    m = re.match(r"(results/fuzz/[^#]+)#seed=(\d+)", origin or "")
    if not m:
        return None
    path = MAIN / m.group(1)
    if path not in fuzz_meta:
        fuzz_meta[path] = {json.loads(l)["seed"]: json.loads(l) for l in path.read_text().splitlines()}
    r = fuzz_meta[path].get(int(m.group(2)))
    if r is None:
        return None
    from offload.engine.fuzz import generate
    return generate(int(m.group(2)), r["gen_version"], tuple(r.get("base") or ())).source

def text_of(c):
    prog = c["program"]
    if prog["kind"] == "catalog":
        p = P.catalog_program(prog["ident"]); return p.source if p else None
    if prog["kind"] == "ompvv":
        s = MAIN / "corpus" / "omp_vv" / prog["ident"]
        return s.read_text(errors="replace") if s.is_file() else None
    if prog["kind"] == "fuzz":
        return fuzz_text(prog, (c.get("source") or {}).get("origin"))
    return None

def links(mod, idx, c, text):
    hits = mod.dedupe(c["toolchain"], c["program"]["lang"], c["outcome"], c["reason"],
                      text, c["program"]["ident"], c["mode"], findings=idx,
                      arch=c["arch"], output="", related=True, opt=c.get("opt", ""))
    return [(h["kind"], norm(h["file"]), h["why"]) for h in hits]

def compare() -> list:
    """The stored rows whose links differ: [{case, old, new}]."""
    old_mod, old_idx = old_module()
    new_idx = NEW.load_index()
    n = diff = skipped = 0
    out = []
    for b in ("batch_full", "batch_s1.final", "batch_widen"):
        for ln in (MAIN / "results" / "confirm" / f"{b}.jsonl").open():
            r = json.loads(ln); c = r["case"]
            exit1 = c["outcome"] == "run_error" and re.match(r"exit_status: 1\b", c.get("reason") or "")
            afar_wrong = c["toolchain"].startswith("afar") and c["outcome"] in ("wrong_answer", "fell_back_to_host")
            if not (exit1 or afar_wrong or "dist-schedule-chunk" in ln):
                continue
            text = text_of(c)
            if text is None:
                skipped += 1; continue
            n += 1
            a, bb = links(old_mod, old_idx, c, text), links(NEW, new_idx, c, text)
            if a != bb:
                diff += 1; out.append({"case": c["case_id"], "old": a, "new": bb})
    return out


def main() -> int:
    out = compare()
    for x in out:
        print(json.dumps(x)[:600])
    print(f"{len(out)} rows differ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
