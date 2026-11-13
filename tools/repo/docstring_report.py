#!/usr/bin/env python3
"""Module docstrings over the length limit.

    python3 -I tools/repo/docstring_report.py            # list the offenders, longest first
    python3 -I tools/repo/docstring_report.py --write    # write tools/repo/docstring_allow.txt
    python3 -I tools/repo/docstring_report.py --same FILE_BEFORE FILE_AFTER
                                                          # exit 0 if only the module docstring differs
"""
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LIMIT = 15
ALLOW = ROOT / "tools" / "repo" / "docstring_allow.txt"


def doc_lines(source: str) -> int:
    doc = ast.get_docstring(ast.parse(source), clean=True)
    return len(doc.splitlines()) if doc else 0


def offenders(root: Path = ROOT) -> list[tuple[str, int]]:
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=root, capture_output=True, text=True,
                           check=True).stdout.split()
    out = []
    for f in files:
        try:
            n = doc_lines((root / f).read_text())
        except (SyntaxError, UnicodeDecodeError, FileNotFoundError):
            continue
        if n > LIMIT:
            out.append((f, n))
    return sorted(out, key=lambda x: (-x[1], x[0]))


def allowed() -> set[str]:
    if not ALLOW.is_file():
        return set()
    return {l.strip() for l in ALLOW.read_text().splitlines() if l.strip() and not l.startswith("#")}


def without_docstring(source: str) -> str:
    tree = ast.parse(source)
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(getattr(tree.body[0], "value", None), ast.Constant) \
            and isinstance(tree.body[0].value.value, str):
        tree.body = tree.body[1:]
    return ast.dump(tree)


def main(argv: list[str]) -> int:
    if argv[:1] == ["--same"]:
        a, b = (Path(p).read_text() for p in argv[1:3])
        return 0 if without_docstring(a) == without_docstring(b) else 1
    off = offenders()
    if argv[:1] == ["--write"]:
        ALLOW.write_text("# module docstrings allowed over %d lines (file formats); shrink this list, never grow it\n" % LIMIT
                         + "".join(f + "\n" for f, _ in off))
        print(len(off), "written to", ALLOW.relative_to(ROOT))
        return 0
    for f, n in off:
        print(f"{n:4d}  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
