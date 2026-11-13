#!/usr/bin/env python3
"""Greedy line-deletion reduction of a compile failure (an ICE
or a rejection whose message contains MSG) on one toolchain, after the confirmer's own
reduction: a candidate deletes one line, or a directive with its end
directive, or a block from a line to its matching end; when no deletion
of lines is kept, a candidate deletes one clause of a directive, one item
of a clause list or one entity of a declaration (clause-list
level); it is kept when
the program still passes offload.engine.fuzz.check_rules and gfortran
-std=f2008 -fsyntax-only (no OpenMP) and the toolchain's compile still
fails with MSG (MSG "compile_timeout": the compile is still running after
MIN_LIMIT seconds, default 90). On a compute node:
    python3 -I data/evidence/dataenv_probe/min_ice.py IN OUT TOOLCHAIN MSG"""
import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))
from offload.engine import fuzz, fuzz_exec  # noqa: E402
from offload.engine.toolchains import TOOLCHAINS  # noqa: E402

KEEP = re.compile(r"^\s*(program|end program|module|end module|contains|"
                  r"submodule|end submodule|implicit none|!@file)", re.I)
END = re.compile(r"^\s*(end\b|!\$omp\s+end\b)", re.I)


def blocks(lines):
    """(start, end) spans to delete: single lines, and a line opening a
    block (do, if then, subroutine, function, type, interface, a
    directive with an end directive) with its matching end."""
    spans = [(k, k) for k, ln in enumerate(lines) if ln.strip()
             and not KEEP.match(ln)]
    opens = re.compile(r"^\s*(do\b|if\b.*\bthen\s*$|subroutine\b|"
                       r"(integer |logical |real\S* )?function\b|type\s*::|"
                       r"interface\b|!\$omp\s+(?!end\b)(\w+(\s+\w+)*))", re.I)
    for k, ln in enumerate(lines):
        m = opens.match(ln)
        if not m:
            continue
        depth = 0
        for j in range(k + 1, len(lines)):
            s = lines[j].strip().lower()
            if opens.match(lines[j]) and not s.startswith("!$omp&"):
                depth += 1
            if END.match(lines[j]):
                if depth == 0:
                    spans.append((k, j))
                    break
                depth -= 1
    spans.sort(key=lambda s: -(s[1] - s[0]))
    return spans


def _top_split(s):
    """Top-level comma-separated parts of `s` (parentheses balanced)."""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur]


def _groups(line):
    """(name start, open paren, close paren) of the top-level `name(...)`
    groups of a directive line."""
    out, depth = [], 0
    for m in re.finditer(r"[()]", line):
        if m.group() == "(":
            if depth == 0:
                n = re.search(r"\w+\s*$", line[:m.start()])
                o = (n.start() if n else m.start(), m.start())
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                out.append(o + (m.start(),))
    return out


DECL = re.compile(r"^(\s*(?:integer|real|complex|logical|character|type\s*\()"
                  r"[^!]*?::\s*)(.*)$", re.I)


def item_edits(lines):
    """Candidate texts deleting one clause, clause-list item or declared
    entity on one line."""
    out = []
    for k, ln in enumerate(lines):
        new = []
        if re.match(r"\s*!\$omp", ln, re.I):
            for a, o, c in _groups(ln):
                if not re.match(r"\s*!\$omp\s*&?\s*$", ln[:a], re.I):
                    new.append(ln[:a].rstrip(", ") + " " + ln[c + 1:].lstrip(", "))
                body = ln[o + 1:c]
                colon = body.rfind(":") if body.count("(") == 0 else -1
                pre, lst = (body[:colon + 1], body[colon + 1:]) if colon >= 0 \
                    else ("", body)
                parts = _top_split(lst)
                for i in range(len(parts)) if len(parts) > 1 else ():
                    rest = ",".join(parts[:i] + parts[i + 1:]).strip()
                    new.append(ln[:o + 1] + pre + (" " if pre else "") + rest
                               + ln[c:])
                mods = _top_split(pre[:-1]) if pre else []
                for i in range(len(mods)) if len(mods) > 1 else ():
                    rest = ",".join(mods[:i] + mods[i + 1:]).strip()
                    new.append(ln[:o + 1] + rest + ":" + lst + ln[c:])
        else:
            m = DECL.match(ln)
            if m and "=" not in m.group(2):
                parts = _top_split(m.group(2))
                for i in range(len(parts)) if len(parts) > 1 else ():
                    new.append(m.group(1) + ",".join(
                        parts[:i] + parts[i + 1:]).strip())
        out += ["\n".join(lines[:k] + [x] + lines[k + 1:]) + "\n"
                for x in new if x != ln]
    return out


def main() -> int:
    src, out, tc, msg = Path(sys.argv[1]).read_text(), sys.argv[2], \
        TOOLCHAINS[sys.argv[3]], sys.argv[4]

    def oracle(text):
        try:
            if fuzz.check_rules(text) or fuzz.check_gfortran(text):
                return False
        except Exception:        # a checker that cannot read a candidate
            return False
        with tempfile.TemporaryDirectory(prefix="mi_") as d:
            d = Path(d)
            (d / "p.f90").write_text(text)
            if msg == "compile_timeout":
                cls, _, _, _ = fuzz_exec.compile_program(
                    tc, d / "p.f90", d / "p.out", d,
                    timeout_s=int(os.environ.get("MIN_LIMIT", "90")))
                return cls == "timeout"
            cls, reason, _, _ = fuzz_exec.compile_program(
                tc, d / "p.f90", d / "p.out", d, timeout_s=300)
        return cls in ("ice", "compile_reject") and msg in reason
    lines = src.splitlines()
    assert oracle("\n".join(lines) + "\n"), "does not reproduce"
    with ThreadPoolExecutor(16) as ex:
        changed = True
        while changed:
            changed = False
            spans = blocks(lines)
            for b in range(0, len(spans), 16):
                batch = spans[b:b + 16]
                cands = ["\n".join(lines[:a] + lines[e + 1:]) + "\n"
                         for a, e in batch]
                res = list(ex.map(oracle, cands))
                if any(res):
                    k = res.index(True)
                    a, e = batch[k]
                    lines = lines[:a] + lines[e + 1:]
                    print(f"deleted {a}-{e}: {len(lines)} lines", flush=True)
                    Path(out).write_text("\n".join(lines) + "\n")
                    changed = True
                    break
            if changed:
                continue
            cands = item_edits(lines)
            for b in range(0, len(cands), 16):
                res = list(ex.map(oracle, cands[b:b + 16]))
                if any(res):
                    lines = cands[b + res.index(True)].splitlines()
                    print(f"item edit: {len(lines)} lines", flush=True)
                    Path(out).write_text("\n".join(lines) + "\n")
                    changed = True
                    break
    Path(out).write_text("\n".join(lines) + "\n")
    print(f"{len(src.splitlines())} -> {len(lines)} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
