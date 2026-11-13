#!/usr/bin/env python3
"""First-cut index of the reference corpora under ../corpus.

One CSV row per source file that contains OpenMP/OpenACC directives, plus a
coverage report of the TableGen catalog directives (data/index/seed/*.json) against
the directives the corpus actually uses.  Directive extraction is a regex
heuristic, so counts are approximate.
"""
import csv, json, os, re, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORPUS = os.path.join(ROOT, "corpus")
OUT = os.path.join(ROOT, "data", "index")

LANG = {".c": "c", ".h": "c", ".cpp": "c++", ".cc": "c++", ".cxx": "c++",
        ".f": "fortran", ".f90": "fortran", ".f03": "fortran",
        ".f08": "fortran", ".for": "fortran"}

# C pragma, Fortran free-form (!$), fixed-form (c$ / *$ in column 1)
RX = {
    "omp": re.compile(r"^\s*(?:#\s*pragma\s+omp|[!cC*]\$omp)\s+(?!&)(.*)$", re.I),
    "acc": re.compile(r"^\s*(?:#\s*pragma\s+acc|[!cC*]\$acc)\s+(?!&)(.*)$", re.I),
}


def catalog(path, model):
    d = json.load(open(path))
    names = {}
    for k, v in d.items():
        if isinstance(v, dict) and "Directive" in v.get("!superclasses", []):
            for s in v.get("spellings", []):
                sp = d[s["def"]]
                names[sp["spelling"].replace("_", " ").lower()] = (
                    sp["minVersion"], sp["maxVersion"])
    return names


CAT = {m: catalog(os.path.join(OUT, "seed", m + ".json"), m) for m in RX}
WORDS = {m: {w for n in CAT[m] for w in n.split()} | {"end"} for m in RX}


def directive(rest, model):
    toks = re.findall(r"[a-z_]+", rest.lower().split("(")[0])
    out = []
    for t in toks:
        t = t.replace("_", " ")
        if all(w in WORDS[model] for w in t.split()):
            out.append(t)
        else:
            break
    if out and out[0] == "end":
        out = out[1:]
    name = " ".join(out)
    # trim trailing words until it matches a catalog spelling
    while name and name not in CAT[model]:
        name = name.rsplit(" ", 1)[0] if " " in name else ""
    return name


def kind(repo, rel, text):
    low = rel.lower()
    if "RUN:" in text and ("// expected-" in text or "ERROR:" in text
                           or "-verify" in text or "FileCheck" in text):
        return "lit-diagnostic" if ("expected-" in text or "ERROR:" in text) else "lit-compile"
    if "RUN:" in text:
        return "lit-run" if "%libomptarget" in text or "%t" in text else "lit-compile"
    if re.search(r"\bmain\b|\bprogram\b", text, re.I):
        return "run"
    return "fragment"


def scan_repo(repo):
    """(index rows, model -> directive names used) of corpus/<repo>."""
    rows, used = [], {m: set() for m in RX}
    for dp, dn, fn in os.walk(os.path.join(CORPUS, repo)):
        dn[:] = [d for d in dn if d != ".git"]
        for f in fn:
            ext = os.path.splitext(f)[1].lower()
            if ext not in LANG:
                continue
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, os.path.join(CORPUS, repo))
            try:
                text = open(full, errors="replace").read()
            except OSError:
                continue
            found = {m: collections.Counter() for m in RX}
            for line in text.splitlines():
                for m, rx in RX.items():
                    g = rx.match(line)
                    if g:
                        found[m][directive(g.group(1), m) or "?"] += 1
            for m in RX:
                if not found[m]:
                    continue
                used[m] |= set(found[m])
                ver = re.search(r"(?:^|/)(\d\.\d)(?:/|$)", rel)
                rows.append({
                    "repo": repo, "path": rel, "lang": LANG[ext], "model": m,
                    "kind": kind(repo, rel, text),
                    "spec_dir": ver.group(1) if ver else "",
                    "n_directives": sum(found[m].values()),
                    "directives": ";".join(sorted(k for k in found[m] if k != "?")),
                })
    return rows, used


def index_repo(repo):
    """The index rows of corpus/<repo> (tools/regenerate.py checks the
    committed omp_vv rows against them)."""
    return scan_repo(repo)[0]


def main():
    rows, used = [], {m: collections.defaultdict(set) for m in RX}
    for repo in sorted(os.listdir(CORPUS)):
        r, u = scan_repo(repo)
        rows += r
        for m in RX:
            for dname in u[m]:
                used[m][dname].add(repo)
    with open(os.path.join(OUT, "corpus_index.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

    print("files with directives, by repo x model x language")
    tab = collections.Counter((r["repo"], r["model"], r["lang"]) for r in rows)
    for k in sorted(tab):
        print("  %-13s %-4s %-8s %5d" % (*k, tab[k]))
    print("\nkind counts:", dict(collections.Counter(r["kind"] for r in rows)))

    cov = []
    for m in RX:
        miss = []
        for name, (lo, hi) in sorted(CAT[m].items()):
            repos = sorted(used[m].get(name, ()))
            cov.append({"model": m, "directive": name, "min_ver": lo,
                        "max_ver": hi if hi < 10**6 else "", "n_repos": len(repos),
                        "repos": ";".join(repos)})
            if not repos:
                miss.append(name)
        print("\n%s: %d catalog spellings, %d never seen in corpus"
              % (m, len(CAT[m]), len(miss)))
        print("  unseen:", ", ".join(miss))
        stray = sorted(set(used[m]) - set(CAT[m]) - {"?"})
        print("  seen but not in catalog (parser noise or catalog gaps):", ", ".join(stray))
    with open(os.path.join(OUT, "directive_coverage.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cov[0]))
        w.writeheader(); w.writerows(cov)


if __name__ == "__main__":
    sys.exit(main())
