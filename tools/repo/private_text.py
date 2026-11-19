#!/usr/bin/env python3
"""Private text out of the tree: the committers' user names, personal paths, the internal host, work-item labels
and disclosure notes.

    python3 -I tools/repo/private_text.py            # list the files that hold any; exit 1 if one does
    python3 -I tools/repo/private_text.py --write    # first scrub the generated files in place, then list

The generated files (GENERATED: reports and run records written from git-ignored measurements) are scrubbed: a
personal path becomes <site>, a user name <user>, the internal host `wingtip`. Every other file is only reported;
fix it by hand. The user names are taken from git and the login (offload/engine/site/scrub.py), never written down.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

TEXT = (".py", ".sh", ".md", ".yaml", ".yml", ".json", ".txt", ".toml", ".cfg", ".ini", ".js", ".mjs", ".css",
        ".html", ".f90", ".f", ".F90", ".c", ".h", ".cpp", ".csv", ".tsv", ".jsonl")
# the files whose job is to find or remove private text: their examples of it stay (a user name never does)
LABEL_EXAMPLES = ("offload/engine/site/scrub.py", "offload/engine/textclean.py", "tools/repo/scrub_vocab.py",
                  "tools/repo/private_text.py", "tests/test_scrub_vocab.py", "tests/site/test_site_inputs.py",
                  "tests/test_private_text.py", "tools/repo/path_allowlist.txt")
LABEL = re.compile(r"\bTask \d+[a-z]?\b")
DISCLOSURE = re.compile(r"[Nn]ot reported to (?:HPE|AMD|NVIDIA|the vendor)|NOT REPORTED|drafts?, not sent|, not sent\b")
# generated from git-ignored measurements, or records of what was run where, which hold this site's host and
# path names
GENERATED = ("data/reports/", "data/evidence/", "data/vendor/checks/probe/", "data/vendor/checks/run_")


def leak_pattern() -> re.Pattern:
    from offload.engine.site.scrub import private_names
    names = "|".join(re.escape(n) for n in private_names()) or "(?!)"
    # user names are lower case; the capitalised surname (a copyright line, an author) is not a user name
    return re.compile(rf"(?<![A-Za-z])(?:s?(?:{names})\d*)(?![A-Za-z])|cc\.gatech\.edu|wingtip-gpu\d")


def label_free(text: str) -> str:
    """Work-item labels out of a text: a parenthesised label, a label opening a sentence, a possessive one."""
    text = re.sub(r"\s*\((?:Task|task) \d+[a-z]?\b[^()\n]*\)", "", text)
    text = re.sub(r"\bTask \d+[a-z]?(?: fix round \d+)?(?:'s)?\s*[:,]\s*([a-z])", lambda m: m.group(1).upper(), text)
    text = re.sub(r"\bTask \d+[a-z]?(?: fix round \d+)?(?:'s)?\s*[:,]\s*", "", text)
    return re.sub(r"\b(?:the |its |a )?Task \d+[a-z]?(?: fix round \d+)?(?:'s)?\s*", "", text)


def scrub(text: str, names: re.Pattern) -> str:
    """Private text out of a generated file: personal paths and user names, the internal host, labels."""
    text = label_free(text)
    text = re.sub(r"wingtip-gpu\d+(?:\.cc\.gatech\.edu)?", "wingtip", text)
    text = re.sub(r"/(?:p/(?:lustre|vast)\d|g/g\d+|nethome|fastscratch|usr/workspace|work\d|var/tmp)/[\w.-]*?"
                  + names.pattern + r"[\w.-]*(?:/[\w.-]*?" + names.pattern + r"[\w.-]*)?", "<site>", text)
    return names.sub("<user>", text)


def tree_files(root: Path) -> list[str]:
    """Tracked and new (not ignored) files: the links to the private checkout are ignored, so never looked at."""
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
                         capture_output=True, text=True, check=True).stdout
    return [f for f in out.split("\0") if f and f.endswith(TEXT) and (root / f).is_file()
            and not (root / f).is_symlink()]


def scrub_generated(root: Path) -> list[str]:
    names, changed = leak_pattern(), []
    for f in tree_files(root):
        if f.startswith(GENERATED):
            old = (root / f).read_text(errors="replace")
            new = scrub(old, names)
            if new != old:
                (root / f).write_text(new)
                changed.append(f)
    return changed


def leaks(root: Path) -> dict[str, list[str]]:
    names = leak_pattern()
    found = {}
    for rel in tree_files(root):
        # the maintainer's public handle in a repository or GitHub Pages link is public on purpose
        text = re.sub(r"github\.com/[\w.-]+|\b[\w-]+\.github\.io\b|\b[\w-]+/compiler-bugs\b", "",
                      (root / rel).read_text(errors="replace"))
        hits = {m.group(0) for m in names.finditer(text) if not m.group(0).startswith(("cc.", "wingtip"))
                or rel not in LABEL_EXAMPLES}
        if rel not in LABEL_EXAMPLES:
            hits |= {m.group(0) for m in LABEL.finditer(text)} | {m.group(0) for m in DISCLOSURE.finditer(text)}
        if hits:
            found[rel] = sorted(hits)[:5]
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="scrub the generated files in place first")
    a = ap.parse_args(argv)
    if a.write:
        for f in scrub_generated(ROOT):
            print("scrubbed", f)
    bad = leaks(ROOT)
    for f, hits in list(bad.items())[:40]:
        print(f"  {f}: {', '.join(hits)}")
    print(f"private text in {len(bad)} files")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
