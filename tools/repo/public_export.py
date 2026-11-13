#!/usr/bin/env python3
"""Build the public repository's tree from this one.

    python3 -I tools/repo/public_export.py OUT [--commit "message" --author "Name <email>"]

Copies the tracked files into OUT (a new or empty directory) except those `public_exclude.txt` names: the
vendor report drafts and the benchmark sets. The generated reports are scrubbed in the copy. Then it scans every file of OUT for private
text (the committers' user names, an internal host, work-item labels, disclosure notes) and exits 1 if any is left. With --commit it makes OUT a git repository
with that one commit.
"""
import argparse
import fnmatch
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
EXCLUDE = Path(__file__).with_name("public_exclude.txt")
# files that replace their private version in the public tree, at the same path
OVERLAY = Path(__file__).with_name("public_overlay")

TEXT = (".py", ".sh", ".md", ".yaml", ".yml", ".json", ".txt", ".toml", ".cfg", ".ini", ".js", ".mjs", ".css",
        ".html", ".f90", ".f", ".F90", ".c", ".h", ".cpp", ".csv", ".tsv", ".jsonl")
# the files whose job is to find or remove private text: their examples of it stay (a user name never does)
LABEL_EXAMPLES = ("offload/engine/site/scrub.py", "offload/engine/textclean.py", "tools/repo/scrub_vocab.py",
                  "tools/repo/public_export.py", "tests/test_scrub_vocab.py", "tests/site/test_site_inputs.py",
                  "tools/repo/path_allowlist.txt")
LABEL = re.compile(r"\bTask \d+[a-z]?\b")
DISCLOSURE = re.compile(r"[Nn]ot reported to (?:HPE|AMD|NVIDIA|the vendor)|NOT REPORTED|drafts?, not sent|, not sent\b")


def leak_pattern() -> re.Pattern:
    from offload.engine.site.scrub import private_names
    names = "|".join(re.escape(n) for n in private_names())
    # user names are lower case; the capitalised surname (a copyright line, an author) is not a user name
    return re.compile(rf"(?<![A-Za-z])(?:s?(?:{names})\d*)(?![A-Za-z])|cc\.gatech\.edu|wingtip-gpu\d")


def label_free(text: str) -> str:
    """Work-item labels out of a text: a parenthesised label, a label opening a sentence, a possessive one."""
    text = re.sub(r"\s*\((?:Task|task) \d+[a-z]?\b[^()\n]*\)", "", text)
    text = re.sub(r"\bTask \d+[a-z]?(?: fix round \d+)?(?:'s)?\s*[:,]\s*([a-z])", lambda m: m.group(1).upper(), text)
    text = re.sub(r"\bTask \d+[a-z]?(?: fix round \d+)?(?:'s)?\s*[:,]\s*", "", text)
    return re.sub(r"\b(?:the |its |a )?Task \d+[a-z]?(?: fix round \d+)?(?:'s)?\s*", "", text)


def scrub(text: str, names: re.Pattern) -> str:
    """Private text out of a generated file's copy: personal paths and user names, the internal host, labels."""
    text = label_free(text)
    text = re.sub(r"wingtip-gpu\d+(?:\.cc\.gatech\.edu)?", "wingtip", text)
    text = re.sub(r"/(?:p/(?:lustre|vast)\d|g/g\d+|nethome|fastscratch|usr/workspace|work\d|var/tmp)/[\w.-]*?"
                  + names.pattern + r"[\w.-]*(?:/[\w.-]*?" + names.pattern + r"[\w.-]*)?", "<site>", text)
    return names.sub("<user>", text)


# generated from git-ignored measurements, or records of what was run where, which hold this site's host and
# path names: scrubbed in the copy
GENERATED = ("data/reports/", "data/evidence/", "data/vendor/checks/probe/", "data/vendor/checks/run_")

BENCH_README = """# data/bench

The benchmark sets are not published: much of their code comes from other projects, and the held-out sets are
kept unread for a later evaluation.
"""


def patterns() -> list[str]:
    return [ln.strip() for ln in EXCLUDE.read_text().splitlines() if ln.strip() and not ln.startswith("#")]


RULINGS = "data/reports/rulings.md"
RULINGS_HEAD = """# Rulings

How the specification is read, and how results are judged, where the text leaves a choice or the measurements
needed one. Each item below is a ruling the bug confirmer applies; `catalog/rulings.yaml` names it by id and quotes
it, and `offload/engine/confirm/registry.py` checks the quotes against this file.
"""


def curated_rulings(text: str) -> str:
    """The rulings file as published: its sections, each with only the rulings the registry quotes; the review
    notes and the record of how the work was run stay in the maintainers' copy."""
    from offload.engine.confirm import registry as R
    quotes = [re.sub(r"\s+", " ", e.rulings_md).lower() for e in R.load().values()]
    out, section, kept = [RULINGS_HEAD], None, []
    def flush():
        if section and kept:
            out.append("\n" + section + "\n\n" + "\n".join(kept) + "\n")
    bullets: list[list[str]] = []      # each ruling with its continuation lines
    for ln in text.splitlines()[1:]:
        if ln.startswith("  ") and bullets and bullets[-1][0].startswith("- "):
            bullets[-1].append(ln)
        else:
            bullets.append([ln])
    for b in bullets:
        ln = b[0]
        if ln.startswith("## "):
            flush()
            title = re.sub(r"^## (?:Final review \d+ leftovers, |Final review \d+ \(([\d-]+)\): fixes of the whole-branch review)",
                           lambda m: "## " + (f"Fixes ({m.group(1)})" if m.group(1) else ""), ln)
            title = re.sub(r" \((?:maintainer|owner) (?:ruling|decision),? ?([\d-]*)\)", "", title)
            section, kept = title[:3] + title[3:4].upper() + title[4:], []
        elif ln.startswith("- ") and any(q[:50] in re.sub(r"\s+", " ", " ".join(x.strip() for x in b)).lower() for q in quotes):
            kept.append("\n".join(b))
    flush()
    return "".join(out)


def selection() -> list[str]:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    pats = patterns()
    return [f for f in files if f and (not any(fnmatch.fnmatch(f, p) for p in pats))]


def leaks(out: Path) -> dict[str, list[str]]:
    names = leak_pattern()
    found = {}
    for p in sorted(out.rglob("*")):
        if not p.is_file() or ".git" in p.parts or not p.name.endswith(TEXT):
            continue
        rel = str(p.relative_to(out))
        # the maintainer's public handle in a repository or GitHub Pages link is public on purpose
        text = re.sub(r"github\.com/[\w.-]+|\b[\w-]+\.github\.io\b|\b[\w-]+/compiler-bugs\b", "",
                      p.read_text(errors="replace"))
        hits = {m.group(0) for m in names.finditer(text) if not m.group(0).startswith(("cc.", "wingtip"))
                or rel not in LABEL_EXAMPLES}
        if rel not in LABEL_EXAMPLES:
            hits |= {m.group(0) for m in LABEL.finditer(text)} | {m.group(0) for m in DISCLOSURE.finditer(text)}
        if hits:
            found[rel] = sorted(hits)[:5]
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--commit", help="make OUT a git repository with this one commit")
    ap.add_argument("--author", default="", help='"Name <email>" of that commit')
    a = ap.parse_args(argv)
    out = Path(a.out)
    if out.exists() and any(out.iterdir()):
        sys.exit(f"{out} exists and is not empty")
    files = selection()
    names = leak_pattern()
    for f in files:
        (out / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, out / f, follow_symlinks=False)
        if f == RULINGS:
            (out / f).write_text(curated_rulings((out / f).read_text()))
        if f.startswith(GENERATED) and f.endswith(TEXT):
            (out / f).write_text(scrub((out / f).read_text(errors="replace"), names))
    for src in sorted(p for p in OVERLAY.rglob("*") if p.is_file()):
        dest = out / src.relative_to(OVERLAY)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    (out / "data" / "bench").mkdir(parents=True, exist_ok=True)
    (out / "data" / "bench" / "README.md").write_text(BENCH_README)
    bad = leaks(out)
    print(f"{len(files)} files to {out}; private text in {len(bad)} files")
    for f, hits in list(bad.items())[:40]:
        print(f"  {f}: {', '.join(hits)}")
    if bad:
        return 1
    if a.commit:
        git = ["git", "-C", str(out)]
        subprocess.run(git + ["init", "-q", "-b", "master"], check=True)
        subprocess.run(git + ["add", "-A", "-f"], check=True)   # tracked files under an ignored name too
        who = ["-c", f"user.name={a.author.split('<')[0].strip()}", "-c", f"user.email={a.author.split('<')[-1].rstrip('>')}"] \
            if "<" in a.author else []
        subprocess.run(["git"] + who + ["-C", str(out), "commit", "-q", "-m", a.commit], check=True)
        print("committed", subprocess.run(git + ["rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
