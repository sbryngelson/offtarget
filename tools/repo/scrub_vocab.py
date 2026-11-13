#!/usr/bin/env python3
"""Take the internal work-item vocabulary ("Task 38b", "fix round 2", "review I5", "the owner") out of text.

    python3 -I tools/repo/scrub_vocab.py report          # counts of what is left, per directory
    python3 -I tools/repo/scrub_vocab.py apply [PATH..]  # rewrite comments, docstrings and prose in place

`scrub` works on one comment, docstring or paragraph. Labels at the start of a comment or docstring go, with the colon,
and the sentence keeps its meaning; a trailing "(Task 31, rulings.md)" keeps only what is not a label; a mention
in the middle of a sentence is dropped. Strings that code compares are never touched: the file adapters
(`scrub_source`) pick out comments and docstrings only.
"""
import ast
import io
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

sys.path.insert(0, str(ROOT))
from offload.engine.textclean import FORBIDDEN, ITEM, ITEMS, LAB, REV, RND, residue, scrub  # noqa: F401


def _py_spans(src: str, strings: bool = False) -> list[tuple[int, int, int, int]]:
    """(start line, start col, end line, end col) of every comment and docstring, 1-based lines;
    with `strings`, of every plain string literal that holds the vocabulary too."""
    spans = []
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        if t.type == tokenize.COMMENT:
            spans.append((*t.start, *t.end))
        elif strings and t.type == tokenize.STRING and re.match(r"[rRuU]?[\"']", t.string) and residue(t.string):
            spans.append((*t.start, *t.end))
        elif strings and t.type == getattr(tokenize, "FSTRING_MIDDLE", -1) and residue(t.string):
            spans.append((*t.start, *t.end))
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) \
                    and isinstance(first.value.value, str):
                spans.append((first.lineno, first.col_offset, first.end_lineno, first.end_col_offset))
    return spans


def _splice(src: str, spans: list[tuple[int, int, int, int]], fn) -> str:
    lines = src.split("\n")
    for sl, sc, el, ec in sorted(set(spans), reverse=True):
        head, tail = lines[sl - 1][:sc], lines[el - 1][ec:]
        body = "\n".join([lines[sl - 1][sc:]] + lines[sl:el - 1] + ([lines[el - 1][:ec]] if el > sl else []))
        if el == sl:
            body = lines[sl - 1][sc:ec]
        new = fn(body)
        lines[sl - 1:el] = (head + new + tail).split("\n") if new or head.strip() or tail.strip() else []
    return "\n".join(lines)


# files whose strings are written into committed seals: they keep the original words
STRING_EXEMPT = ("offload/engine/harvest2/split.py", "tools/campaigns/fresh_bench.py", "tools/campaigns/harvest_known.py",
                 "tools/campaigns/harvest.py")


def scrub_source(path: str, text: str, strings: bool = False) -> str:
    """`text` of the file `path` with the vocabulary out of its comments, docstrings or prose;
    with `strings`, out of Python string literals and YAML values too."""
    suffix = Path(path).suffix
    if suffix == ".py":
        try:
            return _splice(text, _py_spans(text, strings and path not in STRING_EXEMPT), scrub)
        except (SyntaxError, tokenize.TokenError):
            return text
    if suffix == ".json" and strings:
        return _json_strings(text)
    if suffix in (".yaml", ".yml") and strings:
        out = []
        for l in text.split("\n"):
            if residue(l):
                new = scrub(l)
                if not new and l.lstrip().startswith("#"):
                    continue
                l = new or l
            out.append(l)
        return "\n".join(out)
    if suffix == ".sh" and strings:
        text = "\n".join(scrub(l) if (re.search(r'\bWHY=|--why ', l) and residue(l) and not l.lstrip().startswith("#")) else l
                         for l in text.split("\n"))
    if suffix == ".sh" and strings:
        text = "\n".join(_trailing_comment(l) for l in text.split("\n"))
    if suffix in (".sh", ".yaml", ".yml", ".txt"):
        return _comment_lines(text, "#")
    if suffix in (".f90", ".F90", ".f"):
        return _comment_lines(text, "!")
    if suffix in (".c", ".h", ".cpp"):
        text = re.sub(r"/\*.*?\*/", lambda m: scrub(m.group(0)), text, flags=re.S)
        return _comment_lines(text, "//")
    if suffix == ".md":
        return scrub(text)
    return text


def _json_strings(text: str) -> str:
    """Scrub the text of each JSON string that holds the vocabulary; refuse (return unchanged) if the document would differ otherwise."""
    import json

    def one(m: re.Match) -> str:
        body = m.group(0)
        if not residue(body):
            return body
        inner = body[1:-1]
        return '"' + scrub(inner).replace("\n", "\\n") + '"'
    new = re.sub(r'"(?:[^"\\]|\\.)*"', one, text)
    try:
        a, b = json.loads(text), json.loads(new)
    except ValueError:
        return text

    def deep(x):
        if isinstance(x, str):
            return scrub(x)
        if isinstance(x, list):
            return [deep(v) for v in x]
        if isinstance(x, dict):
            return {deep(k): deep(v) for k, v in x.items()}
        return x
    return new if deep(a) == b else text


def code_unchanged(old: str, new: str) -> bool:
    """True when two Python sources differ only in comments and docstrings."""
    def bare(src: str) -> str:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) \
                        and isinstance(first.value.value, str):
                    node.body = node.body[1:] or [ast.Pass()]
        return ast.dump(tree)
    return bare(old) == bare(new)


def only_strings_changed(old: str, new: str) -> bool:
    """True when two Python sources have the same code (same tree, same number of strings) and differ
    only in the text of their string literals."""
    def skeleton(src: str):
        tree = ast.parse(src)
        strs = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                strs.append(node.value)
                node.value = ""
        return ast.dump(tree), strs
    (a, sa), (b, sb) = skeleton(old), skeleton(new)
    return a == b and len(sa) == len(sb)


EXEMPT = ("data/bench/*", "data/index/*", "offload/engine/site/scrub.py", "offload/engine/textclean.py", "tests/test_repository.py", "tests/site/test_site_scrub*.py", "catalog/lint_model*.json", "tools/moves*.tsv",
          "tools/repo/path_allowlist.txt", "docs/superpowers/*", "tools/repo/scrub_vocab.py", "tests/test_scrub_vocab.py",
          "tools/*_probe/*/*", "tools/*_probe/*.f90", "tools/*_probe/*.c", "tools/*_probe/*.log", "tools/*_probe/*.jsonl", "tests/data/*", "tests/golden/*", "results/*", "tools/repo/trace_reads.py")
SUFFIXES = (".py", ".sh", ".yaml", ".yml", ".md", ".f90", ".F90", ".f", ".c", ".h", ".cpp", ".txt", ".json")


def in_scope(root: Path) -> list[str]:
    import fnmatch
    import subprocess
    files = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout.splitlines()
    return [f for f in files if f.endswith(SUFFIXES) and not any(fnmatch.fnmatchcase(f, e) for e in EXEMPT)]


def apply(root: Path, paths: list[str] | None = None, write: bool = True, strings: bool = False) -> dict:
    """Scrub each in-scope file; return {"changed": n, "residue": {path: [tokens]}, "unsafe": [paths]}."""
    out = {"changed": 0, "residue": {}, "unsafe": []}
    for f in paths or in_scope(root):
        old = (root / f).read_text(errors="strict")
        new = scrub_source(f, old, strings)
        if f.endswith(".py") and new != old and not (only_strings_changed(old, new) if strings else code_unchanged(old, new)):
            out["unsafe"].append(f)
            continue
        if new != old:
            out["changed"] += 1
            if write:
                (root / f).write_text(new)
        left = residue(new)
        if left:
            out["residue"][f] = left
    return out


def main(argv=None) -> int:
    args = list(argv or sys.argv[1:])
    cmd = args.pop(0) if args else "report"
    strings = "--strings" in args
    args = [a for a in args if a != "--strings"]
    res = apply(ROOT, args or None, write=cmd == "apply", strings=strings)
    per = {}
    for f, toks in res["residue"].items():
        d = "/".join(f.split("/")[:2]) if f.startswith(("docs/", "tests/")) else f.split("/")[0]
        per[d] = per.get(d, 0) + len(toks)
    print(f"{cmd}: {res['changed']} files changed; residue {sum(per.values())} in {len(res['residue'])} files; "
          f"{len(res['unsafe'])} refused (code would change)")
    for d, n in sorted(per.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {n:6d}  {d}")
    for f in res["unsafe"][:5]:
        print("  refused:", f)
    return 0


def _trailing_comment(line: str) -> str:
    """A shell line with the vocabulary scrubbed out of its trailing ` # comment` (outside quotes)."""
    if line.lstrip().startswith("#") or not residue(line):
        return line
    for m in re.finditer(r"\s#\s", line):
        head = line[:m.start()]
        if head.count('"') % 2 == 0 and head.count("'") % 2 == 0:
            return head + scrub(line[m.start():]) if scrub(line[m.start():].lstrip()) else head
    return line


def _comment_lines(text: str, marker: str) -> str:
    out = []
    for line in text.split("\n"):
        if line.lstrip().startswith(marker) and not line.startswith("#!"):
            new = scrub(line)
            if new == "" and line.strip():
                continue
            out.append(new)
        else:
            out.append(line)
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
