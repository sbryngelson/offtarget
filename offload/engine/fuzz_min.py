"""Delta-debugging minimizer for fuzz failures.

``minimize(source, failure)`` shrinks a program while ``failure`` (a
``Failure``: toolchain, kind, signature) persists and the program stays legal:
every candidate must pass ``offload.engine.fuzz.check`` before it is compiled.
Only the lines between ``! fuzz: kernels`` and ``! fuzz: checksum`` change,
so no variable is read uninitialised; a final cleanup removes declarations no
kernel line names. Transformations are tried coarse to fine and a batch of
candidates runs in parallel: delete a block, drop a nest level, delete a
statement, a clause or a list item, replace a right-hand side by an operand.
``file_candidates`` also removes unused functions and files of a bundle.
The predicate runs twice (``Oracle``) before a candidate is accepted. A
wrong-code or run-error candidate must also run without signed overflow
(``overflow_trap``) and use a reference from another compiler family
(``trusted_refs``)."""
from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from offload.engine import fuzz_exec as fe
from offload.engine import reduce as RD
from offload.engine.fuzz import check, directive_valid, wrap_directive, wrap_stmt
from offload.engine.fuzz_base import FILE_MARK
from offload.engine.toolchains import TOOLCHAINS, family

# the generator's range bounds (offload.engine.fuzz): kept by step 5
BOUNDS = ("mod", "iand")
# the reference that is no toolchain: sequential elision
# (offload.engine.expected.elision_evidence)
ELISION_REF = "elision"

MARK_BEGIN = "! fuzz: kernels"
MARK_END = "! fuzz: checksum"


# --- logical lines ------------------------------------------------------------------

def join_lines(source: str) -> list[str]:
    """Logical lines: a directive continued with `!$omp&` and a statement
    continued with a leading `&` become one line each."""
    out: list[str] = []
    raw = source.splitlines()
    k = 0
    while k < len(raw):
        line = raw[k].rstrip()
        while line.endswith("&") and k + 1 < len(raw):
            k += 1
            nxt = raw[k].strip()
            if nxt.lower().startswith("!$omp&"):
                nxt = nxt[6:].strip()
            elif nxt.startswith("&"):
                nxt = nxt[1:].strip()
            line = line[:-1].rstrip() + " " + nxt
        out.append(line)
        k += 1
    return out


def split_directive(text: str) -> tuple[str, list[str]]:
    """(directive name, clauses) of `!$omp name clause clause ...` (the
    name is the longest prefix of words that is a skeleton directive)."""
    body = re.sub(r"^\s*!\$omp\s+", "", text, flags=re.I)
    toks, depth, cur = [], 0, ""
    for ch in body:
        if ch == " " and depth == 0:
            if cur:
                toks.append(cur)
            cur = ""
            continue
        depth += {"(": 1, ")": -1}.get(ch, 0)
        cur += ch
    if cur:
        toks.append(cur)
    words = []
    for t in toks:
        if "(" in t:
            break
        words.append(t)
    start = 1 if words[:1] == ["end"] else 0
    n = len(words)
    while n > start + 1 and not directive_valid(" ".join(words[start:n])):
        n -= 1
    return " ".join(toks[:n]), toks[n:]


def render(lines: list[str]) -> str:
    out: list[str] = []
    for line in lines:
        ind = re.match(r"\s*", line).group()
        s = line.strip()
        if len(line) <= 100:
            out.append(line)
        elif s.lower().startswith("!$omp"):
            name, cl = split_directive(s)
            out += wrap_directive(ind, name, cl)
        elif s.startswith("!"):
            out.append(line)
        else:
            out += wrap_stmt(ind, s)
    return "\n".join(out) + "\n"


def region(lines: list[str]) -> tuple[int, int]:
    b = next(k for k, ln in enumerate(lines) if ln.strip() == MARK_BEGIN)
    e = next(k for k, ln in enumerate(lines) if ln.strip() == MARK_END)
    return b + 1, e


def indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def is_dir(line: str) -> bool:
    return line.strip().lower().startswith("!$omp")


LOOP_END = ("do", "simd", "loop", "distribute")
STANDALONE = ("target update", "target enter data", "target exit data",
              "taskwait", "barrier")


def block_end(lines: list[str], k: int, hi: int) -> int | None:
    """Index of the last line of the construct/block starting at line k
    (inclusive), or None if line k does not start one."""
    s = lines[k].strip().lower()
    ind = indent(lines[k])
    if is_dir(lines[k]):
        name, _ = split_directive(s)
        if name.startswith("end") or name in STANDALONE or \
                name == "declare target":
            return k if name in STANDALONE else None
        if name == "atomic" or name.startswith("atomic"):
            return k + 1
        last = name.split()[-1]
        if last in LOOP_END and k + 1 < hi and \
                lines[k + 1].strip().lower().startswith("do "):
            e = block_end(lines, k + 1, hi)
            if e is None:
                return None
            if e + 1 < hi and indent(lines[e + 1]) == ind and \
                    lines[e + 1].strip().lower().startswith(
                        f"!$omp end {name}"):
                e += 1
            return e
        for j in range(k + 1, hi):
            t = lines[j].strip().lower()
            if indent(lines[j]) == ind and t.startswith(f"!$omp end {name}") \
                    and split_directive(t)[0] in (f"end {name}",):
                return j
            if indent(lines[j]) < ind:
                return None
        return None
    if re.match(r"do\b", s) or re.match(r"if\s*\(.*\)\s*then$", s) or \
            s == "block":
        closer = {"d": "end do", "i": "end if", "b": "end block"}[s[0]]
        for j in range(k + 1, hi):
            if indent(lines[j]) == ind and lines[j].strip().lower() == closer:
                return j
            if indent(lines[j]) < ind:
                return None
    return None


def directive_name(line: str) -> str:
    return split_directive(line.strip())[0]


# --- candidates -----------------------------------------------------------------------

@dataclass(frozen=True)
class Cand:
    what: str
    lines: tuple


def _readers(lines, lo, hi, name: str, skip: int) -> bool:
    """Some line of lo..hi other than `skip` names `name`."""
    pat = re.compile(rf"\b{re.escape(name)}\b", re.I)
    return any(pat.search(lines[j]) for j in range(lo, hi) if j != skip)


def _initialised(lines: list[str], name: str) -> bool:
    lo, _ = region(lines)
    pat = re.compile(rf"^\s*{re.escape(name)}\s*=", re.I)
    return any(pat.match(ln) for ln in lines[:lo])


def procedure_regions(lines: list[str]) -> list[tuple[int, int]]:
    """(lo, hi) of the executable part of each internal subroutine kp<k>
    holding a kernel (stage 3): after its declarations, before
    its end."""
    out = []
    for k, ln in enumerate(lines):
        m = re.match(r"^\s*subroutine (kp\d+)\(", ln)
        if not m:
            continue
        end = next((j for j in range(k + 1, len(lines)) if re.match(
            rf"^\s*end subroutine {m.group(1)}\s*$", lines[j])), None)
        if end is None:
            continue
        lo = k + 1
        while lo < end and ("::" in lines[lo] or not lines[lo].strip()):
            lo += 1
        out.append((lo, end))
    return out


def all_regions(lines: list[str]) -> list[tuple[int, int]]:
    return [region(lines)] + procedure_regions(lines)


def candidates(lines: list[str], span=None) -> list[Cand]:
    """Candidates in the kernels region and in every kernel procedure
    (`span`: one of them)."""
    if span is None:
        return [c for sp in all_regions(lines)
                for c in candidates(lines, sp)]
    lo, hi = span
    out: list[Cand] = []
    L = list(lines)
    text = "\n".join("\n".join(L[a:b])
                     for a, b in all_regions(L)).lower()
    has_nowait = "nowait" in text
    # a present modifier (or defaultmap(present)) needs the data region
    # that maps its item: the data constructs stay while one is left (the
    # host references would not see the runtime error termination)
    has_present = re.search(r"\bpresent\b", text) is not None
    data_dirs = ("target data", "target enter data")

    def put(what, new):
        out.append(Cand(what, tuple(new)))
    # 1. blocks, coarsest (outermost) first
    blocks = []
    for k in range(lo, hi):
        e = block_end(L, k, hi)
        if e is not None:
            blocks.append((k, e))
    for k, e in sorted(blocks, key=lambda b: (b[0] - b[1], b[0])):
        s = L[k].strip().lower()
        if is_dir(L[k]) and directive_name(L[k]) in ("taskwait", "barrier") \
                and has_nowait:
            continue
        if is_dir(L[k]) and has_present and \
                directive_name(L[k]) in data_dirs:
            continue
        if s.startswith("do ") and k > lo and is_dir(L[k - 1]) and \
                block_end(L, k - 1, hi) is not None:
            continue  # the loop of a loop construct goes with it
        put(f"delete lines {k + 1}-{e + 1}: {s[:60]}", L[:k] + L[e + 1:])
    # 2. nest levels
    for k, e in blocks:
        if not is_dir(L[k]):
            continue
        name = directive_name(L[k])
        body_has_end = L[e].strip().lower().startswith("!$omp end")
        inner = L[k + 1:e if body_has_end else e + 1]
        inner_text = "\n".join(inner).lower()
        unwrap = False
        if (name == "target data" and not has_present) or (
                name == "taskgroup" and
                                     "task_reduction" not in L[k].lower()):
            unwrap = True
        elif name == "simd" or name.startswith("parallel do") or \
                name == "parallel loop":
            unwrap = True
        elif name == "parallel" and not re.search(
                r"!\$omp\s+(do|loop|single|masked|barrier|critical|"
                r"end do)", inner_text):
            unwrap = True
        if unwrap:
            put(f"unwrap {name} at {k + 1}",
                L[:k] + L[k + 1:e] + L[e + 1:] if body_has_end
                else L[:k] + L[k + 1:])
        leaves = [] if name in STANDALONE else name.split()
        for cut in range(len(leaves) - 1, 0, -1):
            new = " ".join(leaves[:cut])
            if leaves[cut - 1] not in ("target", "distribute", "do") or \
                    not directive_valid(new):
                continue
            nl = list(L)
            _, cl = split_directive(L[k])
            ind = re.match(r"\s*", L[k]).group()
            nl[k] = f"{ind}!$omp {new}" + ("".join(" " + c for c in cl))
            if body_has_end:
                nl[e] = re.sub(rf"!\$omp end {re.escape(name)}",
                               f"!$omp end {new}", L[e], flags=re.I)
            elif leaves[cut - 1] == "target":
                # a block construct needs its end directive
                nl.insert(e + 1, f"{ind}!$omp end {new}")
            put(f"rename {name} -> {new} at {k + 1}", nl)
    # 3. statements
    for k in range(lo, hi):
        s = L[k].strip()
        if not s or s.startswith("!") or block_end(L, k, hi) is not None:
            continue
        low = s.lower()
        if low in ("end do", "end if", "end block", "else") or \
                low.startswith(("do ", "block")):
            continue
        if k > lo and L[k - 1].strip().lower().startswith("!$omp atomic"):
            continue
        m = re.match(r"(?:if\s*\(.*\)\s*)?([a-z]\w*)\s*=", low)
        if m and not _initialised(L, m.group(1)) and \
                _readers(L, lo, hi, m.group(1), k):
            continue
        put(f"delete statement {k + 1}: {s[:60]}", L[:k] + L[k + 1:])
    # 4. clauses
    ptr_comps = _pointer_components(L)
    for k in range(lo, hi):
        if not is_dir(L[k]):
            continue
        name, cl = split_directive(L[k])
        if has_present and name in data_dirs:
            continue
        e = block_end(L, k, hi) or k
        body = L[k + 1:e + 1]
        nowait = any(c == "nowait" for c in cl)
        ind = re.match(r"\s*", L[k]).group()
        assigned = _assigned_scalars(L, body)
        for ci, c in enumerate(cl):
            # a pointer component keeps its explicit map: through the
            # structure's default mapper its association is undefined
            # (5.2 §5.8.3; offload.engine.fuzz_base, stage 3)
            if c.lower().startswith("map(") and any(
                    re.search(rf"%{pc}\b", c, re.I) for pc in ptr_comps):
                continue
            # a structure element keeps its map: 5.2 §13.8 needs every
            # referenced element of a structure with a mapped element
            # mapped too
            if c.lower().startswith("map(") and "%" in c:
                continue
            word = re.match(r"\w+", c).group().lower() if re.match(
                r"\w+", c) else c
            items = _items(c)
            # a scalar the construct assigns keeps its map (and a scalar
            # defaultmap): unmapped it would become firstprivate, and the
            # hosts disagree about firstprivate in host fallback
            if word == "map" and set(items) & assigned:
                if len(items) > 1:
                    for it in items:
                        if it in assigned:
                            continue
                        nc = _drop_item(c, it)
                        nl = list(L)
                        nl[k] = f"{ind}!$omp {name}" + "".join(
                            " " + (nc if x is c else x) for x in cl)
                        put(f"drop {it} from {c} at {k + 1}", nl)
                continue
            if word == "defaultmap" and assigned and re.search(
                    r":\s*(scalar|all)\)", c):
                continue
            if word in ("reduction", "lastprivate", "private",
                        "in_reduction", "task_reduction"):
                if any(_readers(body, 0, len(body), it, -1)
                       for it in items if it not in ("i", "j")):
                    continue
            if word == "depend" and nowait:
                continue
            if word == "map":
                m = re.match(r"map\(([^:()]*):(.*)\)$", c)
                mods = [x.strip() for x in m.group(1).split(",")] if m \
                    else []
                for mod in mods[:-1]:  # the last one is the map type
                    rest_mods = [x for x in mods if x != mod]
                    nc = f"map({', '.join(rest_mods)}:{m.group(2)})"
                    nl = list(L)
                    nl[k] = f"{ind}!$omp {name}" + "".join(
                        " " + (nc if x is c else x) for x in cl)
                    put(f"drop modifier {mod} from {c} at {k + 1}", nl)
            if word == "nowait" and name.startswith("end"):
                pass
            rest = cl[:ci] + cl[ci + 1:]
            nl = list(L)
            nl[k] = f"{ind}!$omp {name}" + "".join(" " + x for x in rest)
            put(f"delete clause {c} at {k + 1}", nl)
            if len(items) > 1 and word in ("map", "shared", "firstprivate",
                                           "private", "depend"):
                for it in items:
                    if word == "private" and it not in ("i", "j") and \
                            _readers(body, 0, len(body), it, -1):
                        continue
                    nc = _drop_item(c, it)
                    nl = list(L)
                    nl[k] = f"{ind}!$omp {name}" + "".join(
                        " " + (nc if x is c else x) for x in cl)
                    put(f"drop {it} from {c} at {k + 1}", nl)
    # 5. expressions
    for k in range(lo, hi):
        s = L[k].strip()
        if s.startswith("!") or s.lower().startswith(("do ", "end", "if (")
                                                      ) and "=" not in s:
            continue
        parts = split_assignment(s)
        if parts is None:
            continue
        lhs, rhs = parts
        if "omp_is_initial_device" in rhs:
            continue
        name = re.match(r"[a-z]\w*", lhs.split(")")[-1].strip() or lhs,
                        re.I)
        target = re.search(r"([a-z]\w*)\s*(\(.*\))?\s*=\s*$", lhs, re.I)
        var = target.group(1) if target else None
        upd = _update_form(var, rhs) if var and not target.group(2) \
            else None
        if var and upd is None and re.search(rf"\b{var}\b", rhs):
            continue  # an update of another shape: leave it
        if upd is not None:
            # an update (v = v op e, v = op(v, e)) stays an update with the
            # same operator, so its order independence is kept
            head, operand, tail = upd
            subs = [head + x + tail for x in _operands(operand)
                    if x != operand]
        else:
            subs = [x for x in _operands(rhs) if x != rhs]
        for sub in subs:
            nl = list(L)
            nl[k] = re.match(r"\s*", L[k]).group() + lhs + sub
            put(f"simplify {k + 1}: {sub[:50]}", nl)
    return out


def split_assignment(s: str) -> tuple[str, str] | None:
    """(everything up to and including "= ", the right-hand side) of an
    assignment statement, optionally guarded by a one-line `if (...)`."""
    k = 0
    if re.match(r"if\s*\(", s, re.I):
        depth, k = 0, s.index("(")
        while k < len(s):
            depth += {"(": 1, ")": -1}.get(s[k], 0)
            k += 1
            if depth == 0:
                break
    m = re.match(r"\s*[a-z]\w*(\s*\([^=]*\))?\s*=\s*", s[k:], re.I)
    if not m or s[k + m.end():].startswith("="):
        return None
    return s[:k + m.end()], s[k + m.end():]


def _update_form(var: str, rhs: str):
    """(head, operand, tail) when `rhs` is `var op operand` or
    `op(var, operand)` (the generator's reduction updates), else None."""
    m = re.match(rf"{re.escape(var)} ([+*]) (.*)$", rhs)
    if m:
        return f"{var} {m.group(1)} ", m.group(2), ""
    m = re.match(rf"(max|min|iand|ior|ieor)\({re.escape(var)}, (.*)\)$",
                 rhs)
    if m and _balanced(m.group(2)):
        return f"{m.group(1)}({var}, ", m.group(2), ")"
    return None


def _pointer_components(lines: list[str]) -> set[str]:
    """Names of the POINTER components of the derived types defined in
    the program."""
    out, in_type = set(), False
    for ln in lines:
        t = ln.strip().lower()
        if re.match(r"type\s*::\s*\w+$", t):
            in_type = True
        elif t.startswith("end type"):
            in_type = False
        elif in_type and "pointer" in t.split("::")[0] and "::" in t:
            out |= set(re.findall(r"([a-z_]\w*)\s*\(",
                                  t.split("::", 1)[1]))
    return out


def _assigned_scalars(lines: list[str], body: list[str]) -> set[str]:
    """Scalar variables (declared without a shape) assigned in `body`."""
    ents = "\n".join(ln.split("::", 1)[1] for ln in lines if "::" in ln)
    arrays = set(re.findall(r"\b([a-z]\w*)\s*\(", ents))
    out = set()
    for ln in body:
        m = re.match(r"\s*(?:if\s*\(.*\)\s*)?([a-z]\w*)\s*=[^=]",
                     ln.strip())
        if m and m.group(1) not in arrays:
            out.add(m.group(1))
    return out


def _items(clause: str) -> list[str]:
    m = re.match(r"\w+\((.*)\)$", clause)
    if not m:
        return []
    inner = m.group(1)
    depth, top = 0, ""
    for ch in inner:
        depth += {"(": 1, ")": -1}.get(ch, 0)
        top += ch if depth == 0 or ch in "()" else ("_" if ch == ":" else ch)
    if ":" in top:
        inner = inner[top.rindex(":") + 1:]
    items, depth, cur = [], 0, ""
    for ch in inner:
        if ch == "," and depth == 0:
            items.append(cur.strip())
            cur = ""
            continue
        depth += {"(": 1, ")": -1}.get(ch, 0)
        cur += ch
    if cur.strip():
        items.append(cur.strip())
    return [re.match(r"\w+", x).group() if re.match(r"\w+", x) else x
            for x in items]


def _drop_item(clause: str, item: str) -> str:
    head, inner = clause.split("(", 1)
    inner = inner[:-1]
    prefix = ""
    depth, top = 0, ""
    for ch in inner:
        depth += {"(": 1, ")": -1}.get(ch, 0)
        top += ch if depth == 0 or ch in "()" else "_"
    if ":" in top:
        cut = top.rindex(":") + 1
        prefix, inner = inner[:cut] + " ", inner[cut:]
    parts, depth, cur = [], 0, ""
    for ch in inner:
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        depth += {"(": 1, ")": -1}.get(ch, 0)
        cur += ch
    parts.append(cur.strip())
    keep = [p for p in parts if not re.match(rf"{re.escape(item)}\b", p)]
    return f"{head}({prefix.strip() + ' ' if prefix else ''}" \
        f"{', '.join(keep)})".replace("( ", "(")


def _operands(expr: str) -> list[str]:
    """Immediate operands of a generated expression: `(a op b)` -> a, b;
    `f(x, y)` -> x, y (merge: its two values); plus "0"."""
    e = expr.strip()
    out = []

    def split_top(s, seps):
        parts, depth, cur, k = [], 0, "", 0
        while k < len(s):
            ch = s[k]
            if depth == 0:
                for sep in seps:
                    if s.startswith(sep, k):
                        parts.append(cur.strip())
                        cur = ""
                        k += len(sep)
                        break
                else:
                    depth += {"(": 1, ")": -1}.get(ch, 0)
                    cur += ch
                    k += 1
                continue
            depth += {"(": 1, ")": -1}.get(ch, 0)
            cur += ch
            k += 1
        parts.append(cur.strip())
        return parts
    m = re.match(r"(\w+)\((.*)\)$", e)
    if m and _balanced(m.group(2)):
        args = split_top(m.group(2), (",",))
        if m.group(1).lower() in BOUNDS and len(args) == 2:
            # keep the bound: the wrapper around a smaller operand, or the
            # bound itself
            out += [f"{m.group(1)}({x}, {args[1]})"
                    for x in _operands(args[0]) if x not in (args[0], "0")]
            out.append(args[1])
            out.append("0")
            return out
        if m.group(1).lower() == "merge":
            args = args[:2]
        out += [a for a in args if a]
    elif e.startswith("(") and e.endswith(")") and _balanced(e[1:-1]):
        parts = split_top(e[1:-1], (" + ", " - ", " * ", " / "))
        if len(parts) >= 2:
            out += parts
    out.append("0")
    return out


def _balanced(s: str) -> bool:
    d = 0
    for ch in s:
        d += {"(": 1, ")": -1}.get(ch, 0)
        if d < 0:
            return False
    return d == 0


# --- procedures and files (outside the kernels) --------------------------

_FUNC_HEAD = re.compile(r"^\s*(?:module\s+)?integer function (\w+)\(")
_USE_ONLY = re.compile(r"^(\s*use \w+, only: )(.*)$")


def _func_blocks(lines: list[str]) -> dict[str, list[tuple[int, int]]]:
    """name -> [(first, last)] of every function definition or interface
    body of `name` (logical lines)."""
    out: dict[str, list] = {}
    for k, ln in enumerate(lines):
        m = _FUNC_HEAD.match(ln)
        if not m:
            continue
        name = m.group(1)
        for j in range(k + 1, len(lines)):
            if re.match(rf"^\s*end function {name}\s*$", lines[j]):
                out.setdefault(name, []).append((k, j))
                break
    return out


def _sections(lines: list[str]) -> list[tuple[int, int]]:
    """(first, last) of each file of a bundle (from its marker)."""
    marks = [k for k, ln in enumerate(lines) if ln.startswith(FILE_MARK)]
    return [(a, (marks[i + 1] - 1) if i + 1 < len(marks) else len(lines) - 1)
            for i, a in enumerate(marks)]


def file_candidates(lines: list[str]) -> list[Cand]:
    """Shrink the program outside the kernels, across the files of a
    bundle: delete a function nothing calls (its definition, interface
    bodies and use-only entries, and an interface block left empty),
    delete a file nothing uses, simplify a function's result expression
    (keeping the generator's mod/iand bounds)."""
    out: list[Cand] = []
    blocks = _func_blocks(lines)
    for name, spans in sorted(blocks.items()):
        inside = {k for a, b in spans for k in range(a, b + 1)}
        pat = re.compile(rf"\b{name}\b", re.I)
        used = any(pat.search(ln) for k, ln in enumerate(lines)
                   if k not in inside and not _USE_ONLY.match(ln)
                   and not ln.lstrip().startswith("!"))
        if used:
            continue
        new = []
        for k, ln in enumerate(lines):
            if k in inside:
                continue
            m = _USE_ONLY.match(ln)
            if m and pat.search(m.group(2)):
                rest = [x.strip() for x in m.group(2).split(",")
                        if x.strip().lower() != name.lower()]
                if not rest:
                    continue
                ln = m.group(1) + ", ".join(rest)
            new.append(ln)
        cleaned = []
        for k, ln in enumerate(new):
            if ln.strip() == "interface" and k + 1 < len(new) and \
                    new[k + 1].strip() == "end interface":
                continue
            if ln.strip() == "end interface" and cleaned and \
                    cleaned[-1].strip() == "interface":
                cleaned.pop()
                continue
            cleaned.append(ln)
        out.append(Cand(f"delete function {name}", tuple(cleaned)))
    for a, b in _sections(lines):
        if lines[a].strip().endswith("fuzz_prog.f90"):
            continue
        body = lines[a + 1:b + 1]
        mods = [re.match(r"^(?:module|submodule \(\w+\)) (\w+)$",
                         x).group(1) for x in body
                if re.match(r"^(?:module|submodule \(\w+\)) (\w+)$", x)]
        rest = lines[:a] + lines[b + 1:]
        if any(re.search(rf"\b(use|submodule \()\s*{m}\b", x)
               for m in mods for x in rest):
            continue
        if any(_FUNC_HEAD.match(x) for x in body):
            continue        # its functions go first (delete function)
        out.append(Cand(f"delete file {lines[a][len(FILE_MARK):]}",
                        tuple(rest)))
    for name, spans in sorted(blocks.items()):
        for a, b in spans:
            for k in range(a + 1, b):
                m = re.match(rf"^(\s*{name} = )(.*)$", lines[k])
                if not m:
                    continue
                for sub in _operands(m.group(2)):
                    if sub == m.group(2):
                        continue
                    nl = list(lines)
                    nl[k] = m.group(1) + sub
                    out.append(Cand(f"simplify {name}: {sub[:40]}",
                                    tuple(nl)))
    return out


# --- cleanup of unused variables --------------------------------------------------------

def cleanup_candidates(lines: list[str]) -> list[Cand]:
    """Remove an array or scalar that no kernel line names: its entity in
    the declarations, every other line outside the kernels that names it
    (allocate, initialisation, checksum), loops left empty, and its entry
    in the final max(...) of host flags."""
    lo, hi = region(lines)
    kern = "\n".join("\n".join(lines[a:b])
                     for a, b in all_regions(lines)).lower()
    decl = {k for k, ln in enumerate(lines[:lo])
            if re.match(r"\s*(integer|real|complex|logical|character|"
                        r"double precision)\b[^:]*::", ln)
            and "parameter" not in ln.split("::")[0]}
    names = set()
    for k in decl:
        ents = re.sub(r"\([^)]*\)", "", lines[k].split("::", 1)[1])
        names |= {x.strip() for x in ents.split(",") if x.strip()}
    out = []
    for name in sorted(names - {"i", "j", "cs"}):
        pat = re.compile(rf"\b{re.escape(name)}\b", re.I)
        if pat.search(kern):
            continue
        new = []
        for k, ln in enumerate(lines):
            if lo <= k < hi or not pat.search(ln):
                new.append(ln)
            elif k in decl:
                head, ents = ln.split("::", 1)
                parts = [p.strip() for p in re.split(r",(?![^()]*\))", ents)]
                keep = [p for p in parts
                        if not re.match(rf"{re.escape(name)}\b", p)]
                if keep:
                    new.append(f"{head}:: {', '.join(keep)}")
            elif ln.strip().startswith("print"):
                t = re.sub(rf"\b{re.escape(name)}, ", "", ln)
                new.append(t.replace("max(0)", "0"))
        changed = True
        while changed:
            changed = False
            nlo, nhi = region(new)
            for k in range(len(new) - 1):
                if nlo <= k < nhi:
                    continue  # a kernel's loops stay (their directives)
                if new[k].strip().startswith("do ") and \
                        new[k + 1].strip() == "end do":
                    del new[k:k + 2]
                    changed = True
                    break
        if new != lines:
            out.append(Cand(f"remove unused {name}", tuple(new)))
    return out


# --- the oracle -----------------------------------------------------------------------

@dataclass(frozen=True)
class Failure:
    toolchain: str
    kind: str          # wrong_code | ice | run_error
    signature: str = ""
    host: int = 0      # ran_on_host of the failing device run


def ice_signature(reason: str, output: str = "") -> str:
    """A compiler-message key for ICE dedupe: the message without version
    hashes, paths, line/column numbers of the program and addresses; for
    AFAR the first frame of the stack dump that names a flang function."""
    text = reason
    m = re.search(r"error: loc\([^)]*\): (.*)", output)
    if "verification of lowering to FIR failed" in reason and m:
        text = "afar FIR verification: " + m.group(1)
    if "PLEASE submit a bug report" in reason or \
            "unable to execute command" in reason:
        frames = re.findall(r"#\d+ 0x[0-9a-f]+ (?:\S+ )?\(?([A-Za-z_][\w:<>~]*"
                            r"(?:\([^)]*\))?)", output)
        useful = [f for f in frames if not re.match(
            r"(llvm::sys|_ZN4llvm3sys|SignalHandler|__restore_rt|"
            r"PrintStackTrace|abort|raise|gsignal)", f)]
        if useful:
            text = "afar stack: " + useful[0][:120]
    text = re.sub(r"version [0-9a-f]+", "version <v>", text)
    text = re.sub(r"<tmpdir>\S*|(?<![\w])/\S+/", "", text)
    # GCC locates an ICE at the program's own file and line ("fuzz_prog.f90:
    # 97:44: internal compiler error: ..."; coverage parity)
    text = re.sub(r"(?<![\w/])[\w.-]+\.(?:f90|c):\d+:\d+:\s*", "", text)
    text = re.sub(r"(File|Line|Column) = [^,]+,?", "", text)
    text = re.sub(r"0x[0-9a-f]+", "0x", text)
    return " ".join(text.split())[:240]


class Oracle:
    """Is the failure still there? Each source is compiled and run at most
    once (cache by hash).

    References: host runs (OMP_TARGET_OFFLOAD=disabled) of the toolchains
    in `refs` (by default AFAR, or CCE 19 for an AFAR failure), and
    ``ELISION_REF``: the sequential elision of the candidate
    (offload.engine.expected.elision_evidence, no OpenMP toolchain). A
    reference never comes from the failing toolchain's family (its own
    host run, or another CCE release for a CCE failure, can share the
    bug). Use ``trusted_refs`` to pick references whose value of the
    ORIGINAL program matched the model. Every reference must give a value
    and all must agree: a reduction that makes two references disagree
    has stepped into a host-side difference (an undefined value, or a
    host-fallback bug of one compiler), not the device failure. A
    candidate whose elided gfortran -ftrapv build traps on a signed
    overflow is rejected (``overflow_trap``). A wrong-code verdict then
    needs the device checksum to differ from the reference, with the
    original ran_on_host, twice in a row."""

    def __init__(self, failure: Failure, refs=None):
        self.failure = failure
        self.tc = TOOLCHAINS[failure.toolchain]
        if isinstance(refs, str):
            refs = [refs]
        if not refs:  # the first gfx942 toolchain of another family
            from offload.engine.toolchains import GFX942_TOOLCHAINS
            fam = TOOLCHAINS[failure.toolchain].family_id
            refs = [next(t for t in GFX942_TOOLCHAINS
                         if TOOLCHAINS[t].family_id != fam)]
        refs = list(refs)
        if failure.kind != "ice":
            same = [r for r in refs if r != ELISION_REF and
                    family(r) == family(failure.toolchain)]
            if same:
                raise ValueError(
                    f"reference {', '.join(same)} is in the compiler family "
                    f"of the failing {failure.toolchain}")
        self.ref_names = refs
        self.elision_ref = ELISION_REF in refs
        self.refs = [TOOLCHAINS[r] for r in refs if r != ELISION_REF]
        self.cache: dict[str, tuple[bool, str]] = {}
        self.calls = 0

    def __call__(self, source: str) -> tuple[bool, str]:
        key = hashlib.sha256(source.encode()).hexdigest()
        if key not in self.cache:
            self.cache[key] = self._judge(source)
        return self.cache[key]

    def _judge(self, source: str) -> tuple[bool, str]:
        self.calls += 1
        chk = check(source)
        if not chk.ok:
            return False, f"illegal: {chk.stage}: {chk.detail[:120]}"
        if self.failure.kind != "ice":
            trap = overflow_trap(source)
            if trap:
                return False, trap
        tmp = Path(tempfile.mkdtemp(prefix="fuzzmin_"))
        try:
            return self._run(source, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _host(self, tc, source: str, tmp: Path, own_exe: Path | None):
        """The host run of `source` by `tc` (None if it does not
        compile); the failing toolchain's binary is reused."""
        if tc.name == self.tc.name and own_exe is not None:
            return fe.execute(tc, own_exe, own_exe.parent, "disabled")
        d = tmp / f"ref-{tc.name}"
        d.mkdir()
        src, exe = d / "m.f90", d / "m.out"
        src.write_text(source)
        cls, _, _, _ = fe.compile_program(tc, src, exe, d)
        if cls is not None:
            return None
        return fe.execute(tc, exe, d, "disabled")

    def _run(self, source: str, tmp: Path) -> tuple[bool, str]:
        f = self.failure
        src, exe = tmp / "m.f90", tmp / "m.out"
        src.write_text(source)
        cls, reason, _, out = fe.compile_program(self.tc, src, exe, tmp)
        if f.kind == "ice":
            ok = cls == "ice" and (not f.signature or
                                   ice_signature(reason, out) == f.signature)
            return ok, reason[:200]
        if cls is not None:
            return False, f"compile: {cls}: {reason[:120]}"
        dev = fe.execute(self.tc, exe, tmp, "mandatory")
        sums = {}
        for rtc in self.refs:
            ref = self._host(rtc, source, tmp, exe)
            if ref is None:
                return False, f"reference compile ({rtc.name}) failed"
            if ref.kind != "ok":
                return False, f"reference run ({rtc.name}): {ref.why}"
            sums[rtc.name] = ref.checksum
        if self.elision_ref:
            from offload.engine import expected as E
            el = E.elision_evidence(source)
            if el.status != "value":
                return False, f"elision reference: {el.status}: " \
                    f"{(el.detail or '')[:120]}"
            sums[ELISION_REF] = int(el.value.split("=", 1)[1])
        if len(set(sums.values())) > 1:
            return False, f"host references disagree: {sums}"
        refsum = next(iter(sums.values()))
        names = "/".join(sums)
        if f.kind == "run_error":
            # "crash" keeps the class, "crash: SIGSEGV" the signal too, and
            # a message after " | " must stay in the run's output
            want, _, msg = f.signature.partition(" | ")
            ok = dev.kind == "fail" and (
                dev.why.split(":")[0] == want.split(":")[0]
                if ":" not in want else
                dev.why.split(";")[0].strip() == want.strip()) and \
                msg.strip() in (dev.stdout or "") + (dev.stderr or "")
            return ok, (f"device: {dev.kind} {dev.why}; host reference "
                        f"({names}) checksum={refsum}")
        if dev.kind != "ok" or dev.host != f.host or dev.checksum == refsum:
            return False, (f"device {dev.kind} {dev.checksum} host={dev.host}"
                           f" ref {refsum}")
        again = fe.execute(self.tc, exe, tmp, "mandatory")
        if again.kind != "ok" or again.checksum != dev.checksum:
            return False, "unstable device result"
        return True, (f"device checksum={dev.checksum} ran_on_host="
                      f"{dev.host}; host reference ({names}) "
                      f"checksum={refsum}")


def overflow_trap(source: str) -> str | None:
    """None if the elided program (no OpenMP, offload.engine.expected's
    sequential omp_lib) built by gfortran -O0 -ftrapv runs to a result;
    else why not (a trap: a signed integer overflow, undefined in
    Fortran). The generator keeps every value in range (its model raises
    on overflow), so an original passes; a reduction step that drops a
    bound may not."""
    from offload.engine import expected as E
    v, note = E.run_elided(source, "gfortran", ("-ftrapv",))
    if v is not None:
        return None
    if re.search(r"rc=(-6|134)\b", note):
        return f"integer overflow (elided gfortran -ftrapv: {note})"
    return f"range guard did not run (elided gfortran -ftrapv: {note})"


def _host_checksum(name: str, source: str) -> int | None:
    tc = TOOLCHAINS[name]
    tmp = Path(tempfile.mkdtemp(prefix="fuzzref_"))
    try:
        src, exe = tmp / "m.f90", tmp / "m.out"
        src.write_text(source)
        if fe.compile_program(tc, src, exe, tmp)[0] is not None:
            return None
        run = fe.execute(tc, exe, tmp, "disabled")
        return run.checksum if run.kind == "ok" else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _elision_value(source: str) -> str | None:
    from offload.engine import expected as E
    el = E.elision_evidence(source)
    return el.value if el.status == "value" else None


def trusted_refs(source: str, expected: int, prefer: str,
                 limit: int = 2, host=None, elision=None) -> list[str]:
    """References for a failure of `prefer`: toolchains outside its
    compiler family whose host run (OMP_TARGET_OFFLOAD=disabled) of
    `source` prints the model's checksum (one per family, at most
    `limit`), then ``ELISION_REF`` when sequential elision applies and
    gives the model's checksum. Empty: no reference independent of the
    failing compiler (the caller does not minimize). `host(name, source)`
    and `elision(source)` replace the runs (tests)."""
    host = host or _host_checksum
    elision = elision or _elision_value
    out, fams = [], set()
    for name in fe.TOOLCHAIN_ORDER:
        f = family(name)
        if f == family(prefer) or f in fams or len(out) >= limit:
            continue
        if host(name, source) == expected:
            out.append(name)
            fams.add(f)
    if elision(source) == f"checksum={expected}":
        out.append(ELISION_REF)
    return out


def refs_for(toolchain: str, refs) -> list[str] | None:
    """`refs` without those in `toolchain`'s family (a reference recorded
    for one failure, reused to judge another toolchain); None if none is
    left."""
    keep = [r for r in (refs or []) if r == ELISION_REF or
            family(r) != family(toolchain)]
    return keep or None


# --- the driver -------------------------------------------------------------------------

@dataclass
class MinResult:
    source: str
    lines_before: int
    lines_after: int
    steps: list = field(default_factory=list)
    verdict: str = ""
    oracle_calls: int = 0


def minimize(source: str, oracle: Oracle, workers: int = 6,
             max_rounds: int = 60, log=lambda *_: None) -> MinResult:
    """Greedy delta debugging over `candidates` then `cleanup_candidates`
    (see the module docstring)."""
    lines = join_lines(source)
    ok, verdict = oracle(render(lines))
    if not ok:
        raise ValueError(f"the failure does not reproduce: {verdict}")
    before = len(source.splitlines())

    def wrap(gen):
        return lambda L: [(c.what, list(c.lines)) for c in gen(L)]
    # the greedy driver is offload.engine.reduce's (shared with the generic
    # reducer); the candidates, the oracle and the rendering stay here
    lines, steps, got = RD.greedy(
        lines, [wrap(candidates), wrap(file_candidates),
                wrap(cleanup_candidates)],
        lambda L: oracle(render(L)), workers, max_rounds * 10,
        lambda what, L: log(f"  {what} -> {len(render(L).splitlines())} "
                            "lines"))
    final = render(lines)
    return MinResult(final, before, len(final.splitlines()), steps,
                     got or verdict, getattr(oracle, "calls", 0))


def finding_header(seed: int, failure: Failure, expected: str,
                   observed: str, gen_version: str) -> str:
    from offload.engine.hdrwrap import wrap_line
    lines = ([
        f"! Minimized by compliance.fuzz_min from fuzz seed {seed} "
        f"({gen_version}).",
        f"! toolchain: {failure.toolchain} (-O2, HSA_XNACK={fe.XNACK}, "
        "OMP_TARGET_OFFLOAD=mandatory)",
        f"! failure: {failure.kind}" + (f" ({failure.signature})"
                                        if failure.signature else ""),
        f"! expected: {expected}",
        f"! observed: {observed}",
        "! Legal OpenMP 5.2: passes offload.engine.rules, gfortran -std=f2008 "
        "and AFAR flang's frontend.",
    ])
    return "\n".join(w for ln in lines for w in wrap_line(ln)) + "\n"


def strip_header(source: str) -> str:
    """The source without the generator's comment header lines (those
    describe the original program, not the minimized one); a bundle's
    first file marker stays."""
    lines = source.splitlines()
    k = 0
    while k < len(lines) and lines[k].startswith("!") and \
            not lines[k].startswith(FILE_MARK):
        k += 1
    return "\n".join(lines[k:]) + "\n"
