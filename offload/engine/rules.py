"""Restriction rules (layer 3 of the catalog) and the program tree they read.

``parse_program(source, version)`` scans free-form Fortran for its OpenMP
directives (``!$acc`` for version 34) and returns a ``ProgramTree``:
``directives``, ``nesting`` (parent, child pairs), ``assoc`` (the code each
directive applies to), ``ends`` (paired end directives) and the declaration
tables ``decls``, ``vartypes``, ``types`` and ``uses``. It raises
``ProgramError`` on unmatched or unclosed constructs.
``catalog/omp/rules.yaml`` and ``catalog/acc/rules.yaml`` hold the rules.
Each ``spec`` entry becomes one ``Rule`` with id ``OMP<ver>-<id>`` or
``ACC34-<stem>``. A static rule names a predicate registered with
``@predicate``; a runtime rule has none and gives a ``why``.
A predicate takes ``(tree, version)`` and returns the indices of the
offending directives. ``violations(tree, version)`` returns the sorted ids
of violated rules; ``findings`` returns ``(id, directive index)`` pairs."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

import yaml

from offload.engine.catalog import (DIRECTIVE_NAME_CLASS, catalog_dir,
                                default_grammar, default_skeleton, model_of,
                                rule_valid)
from offload.engine.grammar import (_FIXED_FORMS, _SENTINELS, Directive,
                                _is_comment, _strip_bang_comment,
                                parse_directive)

from offload.engine.root import ROOT  # noqa: E402

RULES_PATH = ROOT / "catalog" / "omp" / "rules.yaml"


class ProgramError(ValueError):
    """Directive structure that parse_program cannot pair or does not
    support."""


@dataclass
class Assoc:
    kind: str = "standalone"  # block, loop, statement, standalone
    line: int = 0
    end_line: int | None = None
    loop_depth: int = 0
    loop_vars: tuple = ()
    stmts: int = 0
    unit: int = 0
    depth_known: bool = True
    scope: tuple = ()  # enclosing scoping units, outermost first
    # Per loop of the DO chain (loop_vars order): the bounds
    # (lb, ub, incr) as lower-cased text (incr "" when absent; DO
    # CONCURRENT: its first index-spec), and the number of base-language
    # statements directly in that loop's body outside the next loop of the
    # chain (intervening code; 0 for every loop but the innermost means
    # perfectly nested)
    loop_bounds: tuple = ()
    intervening: tuple = ()


@dataclass
class ProgramTree:
    directives: list[Directive]
    nesting: list[tuple[int, int]]
    assoc: list[Assoc] = field(default_factory=list)
    ends: dict[int, Directive] = field(default_factory=dict)
    decls: dict = field(default_factory=dict)  # (scope, name) -> attribute
    vartypes: dict = field(default_factory=dict)  # (scope, name) -> type
    types: dict = field(default_factory=dict)  # (scope, type) -> components
    uses: dict = field(default_factory=dict)  # scope -> [None | {names}]
    # base-language statements (line, lower-cased text, scoping units) and
    # named constants (scope, name): for the default(none) rule
    statements: list = field(default_factory=list)
    params: set = field(default_factory=set)
    # (scope, name) -> intrinsic type keyword of its declaration
    # ("integer", "real", "doubleprecision", "complex", "logical",
    # "character", "type", "class"); names declared with an array spec;
    # names with the SAVE attribute (attribute, SAVE statement, or an
    # initializer); scoping unit -> (kind, name) for program units and
    # subprograms (kind: program, module, submodule, blockdata,
    # subroutine, function); scoping unit -> module names of its USE
    # statements
    vtypes: dict = field(default_factory=dict)
    arrays: set = field(default_factory=set)
    saved: set = field(default_factory=set)
    units: dict = field(default_factory=dict)
    use_modules: dict = field(default_factory=dict)
    # The source language ("f90" or "c", offload.engine.c_program) and
    # the C scanner's extra facts
    lang: str = "f90"
    extra: dict = field(default_factory=dict)

    def _find(self, scope: tuple, name: str, table: dict):
        """(scope chain up to the declaring unit, entry) of `name` in
        `table` from the innermost scoping unit of `scope` outward (host
        association), or None when no declaration is visible: not
        declared, or a USE statement in a scoping unit on the way (the
        declaring one included) may supply the name."""
        for k in range(len(scope) - 1, -1, -1):
            sid = scope[k]
            if any(u is None or name in u for u in self.uses.get(sid, ())):
                return None
            if (sid, name) in table:
                return scope[:k + 1], table[(sid, name)]
        return None

    def _lookup(self, scope: tuple, name: str, table: dict):
        hit = self._find(scope, name, table)
        return None if hit is None else hit[1]

    def attribute(self, i: int, name: str) -> str | None:
        """Declared attribute of `name` seen from directive i: "pointer",
        "allocatable" or "plain"; None when no declaration is visible."""
        return self._lookup(self.assoc[i].scope, name, self.decls)

    def designator_attribute(self, i: int, item: str) -> str | None:
        """Attribute of a list item `v` or `v%c%d` (C: `v.c`, `v->c`;
        subscripts ignored) seen from directive i: for a component, every
        derived type on the path must be defined in the visible source (a
        use-associated type gives None)."""
        item = re.sub(r"\[[^\[\]]*\]", "", item)
        parts = [re.sub(r"\(.*", "", p).strip() for p in
                 re.split(r"%|->|\.", re.sub(r"\([^()]*\)", "", item))]
        scope = self.assoc[i].scope
        hit = self._find(scope, parts[0], self.decls)
        if hit is None:
            return None
        # A type name is resolved where the entity naming it was declared:
        # the variable's declaring unit, then the defining unit of each
        # type on the path (a host's s keeps the host's type t).
        scope, attr = hit
        tname = self.vartypes.get((scope[-1], parts[0]))
        for comp in parts[1:]:
            found = self._find(scope, tname, self.types) if tname else None
            if found is None or comp not in found[1]:
                return None
            scope, comps = found
            attr, tname = comps[comp]
        return attr

    def __post_init__(self):
        self.assoc += [Assoc() for _ in self.directives[len(self.assoc):]]

    def parent(self, i: int) -> int | None:
        for p, c in self.nesting:
            if c == i:
                return p
        return None

    def children(self, i: int) -> list[int]:
        return [c for p, c in self.nesting if p == i]

    def descendants(self, i: int) -> list[int]:
        out = []
        for c in self.children(i):
            out += [c] + self.descendants(c)
        return out


# --- directive facts from the skeleton ---------------------------------------

# Directives associated with one statement whose end directive is optional
# (5.2 §3.1 / 6.0 §5.1 and §6.3); when the next directive is their end
# directive they span the statements up to it.
_ONE_STATEMENT = {"atomic", "allocators", "dispatch"}


def leaves(key: str, model: str = "omp") -> list[str]:
    """Leaf constructs of a directive, outermost first (itself if a leaf)."""
    return list(default_skeleton(model).directive(key).leaves) or [key]


def association(key: str, model: str = "omp") -> str:
    """block, loop, statement, loopseq or standalone."""
    if key in _ONE_STATEMENT:
        return "statement"
    sk = default_skeleton(model)
    assoc = sk.directive(key).association
    if assoc == "FromLeaves":
        assoc = sk.directive(leaves(key, model)[-1]).association
    return {"Block": "block", "LoopNest": "loop",
            "LoopSeq": "loopseq"}.get(assoc, "standalone")


_association = association


# --- the scanner -------------------------------------------------------------

_DO = re.compile(r"^(?:[a-z_]\w*\s*:\s*)?do(?![\w=])\s*(.*)$")
_END_DO = re.compile(r"^end\s*do(?:\s+[a-z_]\w*)?$")
_UNIT_END = re.compile(r"^(?:end(?:\s*(?:program|subroutine|function|module|"
                       r"submodule|procedure|block\s*data)\b.*)?|contains)$")
_BLOCK = re.compile(r"^(?:[a-z_]\w*\s*:\s*)?block$")
_END_BLOCK = re.compile(r"^end\s*block(?:\s+[a-z_]\w*)?$")
_LABEL = re.compile(r"^\d+\s+")
# Program unit and subprogram headers and ends, for the compilation unit of a
# directive (Fortran: a program unit; 5.2 §1.2.2, p.3). A separate module
# procedure (module procedure ... end procedure) is ignored as a pair.
_UNIT_HEAD = re.compile(
    r"^(?:program\s+\w+|module\s+(?!procedure\b)\w+|submodule\s*\(.*|"
    r"block\s*data\b.*|(?:[\w(),=*:]+\s+)*?(?:subroutine|function)\s+"
    r"[a-z_]\w*\s*(?:\(.*|result\b.*|bind\b.*)?)$")
_UNIT_TAIL = re.compile(r"^end(?:\s*(?:program|subroutine|function|module|"
                        r"submodule|block\s*data)\b.*)?$")


@dataclass
class _Do:
    var: str | None
    line: int
    owner: int | None = None  # loop directive this DO is associated with
    loops: list = field(default_factory=list)
    directive: bool = False
    transform: bool = False  # a loop-associated directive in the body
    bounds: tuple = ("", "", "")  # lb, ub, incr (lower-cased text)
    stmts: int = 0  # base-language statements directly in the body


@dataclass
class _Blk:
    line: int
    owner: int | None = None  # block directive whose structured block it is
    loops: list = field(default_factory=list)  # DO and BLOCK constructs
    directive: bool = False
    transform: bool = False
    stmts: int = 0


@dataclass
class _Dir:
    index: int
    kind: str  # block, loop, statement
    pending: bool = False  # waiting for its DO loop / first statement


def _split_statements(text: str) -> list[str]:
    """Split a statement line at ';' outside character literals."""
    parts, cur, quote = [], [], None
    for ch in text:
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == ";":
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    parts.append("".join(cur))
    return [p for p in parts if p.strip()]


def _logical_lines(source: str, model: str = "omp"):
    """(first line number, kind, text): kind is "omp" (raw directive text
    of the model's sentinel, continuation lines included) or "stmt"
    (lower-cased statement)."""
    _SENTINEL, _FIXED_FORM = _SENTINELS[model], _FIXED_FORMS[model]
    lines = source.splitlines()
    n = 0
    while n < len(lines):
        raw = lines[n]
        start = n + 1
        if _SENTINEL.match(raw) or _FIXED_FORM.match(raw):
            group = [raw]  # parse_directive rejects a fixed-form sentinel
            while _strip_bang_comment(
                    _SENTINEL.sub("", group[-1], count=1)).rstrip() \
                    .endswith("&"):
                n += 1
                while n < len(lines) and _is_comment(lines[n]):
                    n += 1
                if n >= len(lines):
                    raise ProgramError(f"line {start}: directive continued "
                                       "past the end of the source")
                group.append(lines[n])
            n += 1
            yield start, "omp", "\n".join(group)
            continue
        stripped = raw.lstrip()
        if _is_comment(raw) or stripped.startswith("#") or (
                stripped.startswith("!$")
                and not re.match(r"!\$[\s&]", stripped)):
            n += 1
            continue
        if stripped.startswith("!$"):
            stripped = stripped[2:]
        text = _strip_bang_comment(stripped).rstrip()
        while text.endswith("&"):
            n += 1
            while n < len(lines) and _is_comment(lines[n]):
                n += 1
            if n >= len(lines):
                break
            nxt = _strip_bang_comment(lines[n].lstrip()).rstrip()
            text = text[:-1] + (nxt[1:] if nxt.startswith("&") else nxt)
        n += 1
        for part in _split_statements(text):
            yield start, "stmt", " ".join(part.lower().split())


def _is_do(stmt: str) -> bool:
    """A DO statement (not an assignment to a variable named do)."""
    m = _DO.match(stmt)
    return bool(m) and not m.group(1).startswith("=")


def _do_var(rest: str, line: int) -> str | None:
    """Iteration variable of a DO statement, None if not canonical."""
    if re.match(r"^\d", rest):
        raise ProgramError(f"line {line}: label DO loops are not supported")
    m = re.match(r"^concurrent\s*\(\s*(?:[^:()]*::)?\s*([a-z_]\w*)\s*=", rest)
    if m:
        return m.group(1)
    m = re.match(r"^,?\s*([a-z_]\w*)\s*=", rest)
    if m and not rest.startswith("while"):
        return m.group(1)
    return None


def _depth(do: _Do) -> tuple:
    """(loop variables, known) of the DO chain starting at `do`: a loop
    body holding exactly one DO loop, possibly inside BLOCK constructs
    (5.2 §4.4.1, p.86), and no directive continues the chain. `known` is
    False when a loop-associated (loop-transforming) directive in a body
    stops it: its generated loops may continue the nest."""
    dos, known = _chain(do)
    return tuple(d.var for d in dos), known


def _chain(do: _Do) -> tuple:
    """(the _Do frames of the chain starting at `do`, known)."""
    if do.var is None:
        return [], True
    inner, known = _body_chain(do)
    return [do] + inner, known


def _body_chain(frame) -> tuple:
    if frame.transform:
        return [], False
    # BLOCK constructs without a loop are intervening code
    loops = [c for c in frame.loops if isinstance(c, _Do) or _has_loop(c)]
    if len(loops) != 1 or frame.directive:
        return [], True
    inner = loops[0]
    return _body_chain(inner) if isinstance(inner, _Blk) else _chain(inner)


def _has_loop(blk: _Blk) -> bool:
    return any(isinstance(c, _Do) or _has_loop(c) for c in blk.loops)


def _intervening(dos: list) -> tuple:
    """Statements directly in each chain loop's body outside the next
    chain loop: its own statements and those of the BLOCK constructs
    around the next loop or beside it (BLOCK constructs are transparent,
    5.2 §4.4.1)."""
    out = []
    for k, do in enumerate(dos):
        nxt = dos[k + 1] if k + 1 < len(dos) else None
        out.append(do.stmts + _between(do, nxt))
    return tuple(out)


def _contains(frame, target) -> bool:
    return any(c is target or (isinstance(c, _Blk) and _contains(c, target))
               for c in frame.loops)


def _between(frame, target) -> int:
    """Statements in the BLOCK constructs of `frame` (recursively) that are
    not inside `target` (None: all of them)."""
    n = 0
    for c in frame.loops:
        if c is target or not isinstance(c, _Blk):
            continue
        n += c.stmts + _between(c, target)
    return n


def _split_top(text: str, sep: str) -> list[str]:
    """Split at `sep` outside parentheses."""
    parts, cur, depth = [], [], 0
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    parts.append("".join(cur).strip())
    return parts


def _do_bounds(rest: str) -> tuple:
    """(lb, ub, incr) of a DO statement from the text after DO (DO
    CONCURRENT: its first index-spec); empty strings when unknown."""
    m = re.match(r"^concurrent\s*\((.*)$", rest)
    if m:
        header, depth = [], 1
        for ch in m.group(1):
            depth += (ch == "(") - (ch == ")")
            if depth == 0:
                break
            header.append(ch)
        spec = "".join(header)
        spec = spec.split("::", 1)[1] if "::" in spec else spec
        first = _split_top(spec, ",")[0]
        mm = re.match(r"^\s*[a-z_]\w*\s*=\s*(.*)$", first)
        parts = _split_top(mm.group(1), ":") if mm else []
    else:
        m = re.match(r"^,?\s*[a-z_]\w*\s*=\s*(.*)$", rest)
        parts = _split_top(m.group(1), ",") if m else []
    return tuple((parts + ["", "", ""])[:3])


_TYPE_SPEC = re.compile(
    r"^(?:integer|real|double\s*precision|double\s*complex|complex|logical|"
    r"character|type\s*\(|class\s*\()")
_ATTR_STMT = re.compile(r"^(pointer|allocatable|dimension|target)\b\s*"
                        r"(?:::)?\s*(.*)$")
_TYPE_DEF = re.compile(r"^type\b(?!\s*\()(?!\s*is\b)\s*(?:,[^:]*)?(?:::)?"
                       r"\s*[a-z_]\w*(?:\s*\(.*\))?$")
_END_TYPE = re.compile(r"^end\s*type\b")
_RANK = {"pointer": 3, "allocatable": 2, "plain": 1}
_USE = re.compile(r"^use\b(?:\s*,\s*(?:non_)?intrinsic)?(?:\s*::)?\s*"
                  r"[a-z_]\w*\s*(?:,\s*(.*))?$")
# type(t) / class(t); class(*) and type(*) name no type, so a component of
# such an entity never resolves (never fires).
_DECL_TYPE = re.compile(r"^(?:type|class)\s*\(\s*([a-z_]\w*)\s*\)")


def _use_names(stmt: str):
    """For a USE statement: None if it may supply any name (no ONLY), else
    the set of local names of its ONLY list (renames: the local name). Not
    a USE statement: False."""
    m = _USE.match(stmt)
    if not m:
        return False
    rest = (m.group(1) or "").strip()
    only = re.match(r"^only\s*:(.*)$", rest)
    if not only:
        return None
    names = set()
    for part in _split_statements_commas(only.group(1)):
        local = part.split("=>")[0].strip()
        if re.fullmatch(r"[a-z_]\w*", local):
            names.add(local)
    return names


def _entities(text: str) -> list[str]:
    """Names of an entity list (`a(:), b = 1, c`)."""
    names = []
    for part in _split_statements_commas(text):
        m = re.match(r"\s*([a-z_]\w*)", part)
        if m:
            names.append(m.group(1))
    return names


def _split_statements_commas(text: str) -> list[str]:
    parts, cur, depth = [], [], 0
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    parts.append("".join(cur))
    return parts


def _declaration(stmt: str) -> tuple[str, list[str]] | None:
    """(attribute, names) of a type declaration or attribute statement
    (pointer, allocatable, dimension, target), else None. The attribute is
    pointer, allocatable or plain."""
    m = _ATTR_STMT.match(stmt)
    if m and not re.match(r"^\w+\s*=", stmt):
        attr = m.group(1) if m.group(1) in ("pointer", "allocatable") \
            else "plain"
        return attr, _entities(m.group(2))
    if not _TYPE_SPEC.match(stmt) or re.search(r"\bfunction\b", stmt):
        return None
    if "::" in stmt:
        spec, ents = stmt.split("::", 1)
    else:  # old style: type-spec [(kind)] [*len] entities
        m = re.match(r"^((?:double\s*precision|double\s*complex|[a-z]+)"
                     r"\s*(?:\([^()]*(?:\([^()]*\)[^()]*)*\))?"
                     r"\s*(?:\*\s*\d+)?)\s+(.*)$", stmt)
        if not m:
            return None
        spec, ents = m.group(1), m.group(2)
    attrs = [a.strip().split("(")[0].strip()
             for a in _split_statements_commas(spec)[1:]]
    attr = "pointer" if "pointer" in attrs else (
        "allocatable" if "allocatable" in attrs else "plain")
    return attr, _entities(ents)


_SAVE_STMT = re.compile(r"^save\b\s*(?:::)?\s*(.*)$")
_USE_MOD = re.compile(r"^use\b(?:\s*,\s*(?:non_)?intrinsic)?(?:\s*::)?\s*"
                      r"([a-z_]\w*)")
# "module integer function f(x)" (a separate module procedure's interface
# body or definition) is a function, not a module
_UNIT_KIND = re.compile(r"^(?:(program)|(module)(?=\s+\w+$)|(submodule)|"
                        r"(block\s*data)"
                        r"|.*?\b(subroutine|function))\s*(?:\([^)]*\)\s*)?"
                        r"([a-z_]\w*)?")


def _decl_facts(stmt: str) -> tuple:
    """Facts of a specification statement: (intrinsic type keyword
    or None, names with an array spec, names with SAVE, save_all) where
    save_all marks a bare SAVE statement."""
    m = _SAVE_STMT.match(stmt)
    if m and not re.match(r"^save\s*=", stmt):
        rest = m.group(1).strip()
        return None, set(), set(_entities(re.sub(r"/\w+/", "", rest))), \
            not rest
    m = _ATTR_STMT.match(stmt)
    if m and not re.match(r"^\w+\s*=", stmt):
        ents = m.group(2)
        arrays = {n for n in _entities(ents)
                  if re.search(rf"\b{n}\s*\(", ents)}
        return None, arrays, set(), False
    if not _TYPE_SPEC.match(stmt) or re.search(r"\bfunction\b", stmt):
        return None, set(), set(), False
    if "::" in stmt:
        spec, ents = stmt.split("::", 1)
    else:
        m = re.match(r"^((?:double\s*precision|double\s*complex|[a-z]+)"
                     r"\s*(?:\([^()]*(?:\([^()]*\)[^()]*)*\))?"
                     r"\s*(?:\*\s*\d+)?)\s+(.*)$", stmt)
        if not m:
            return None, set(), set(), False
        spec, ents = m.group(1), m.group(2)
    vtype = re.sub(r"\s+", "", re.match(r"^(double\s*precision|double\s*"
                                          r"complex|[a-z]+)", spec).group(1))
    attrs = [a.strip().split("(")[0].strip()
             for a in _split_statements_commas(spec)[1:]]
    names, arrays, saved = _entities(ents), set(), set()
    for part in _split_statements_commas(ents):
        mm = re.match(r"\s*([a-z_]\w*)\s*(\()?", part)
        if not mm:
            continue
        if mm.group(2) or "dimension" in attrs:
            arrays.add(mm.group(1))
        if ("save" in attrs or re.search(r"(?<![=<>/])=(?!=)", part)) \
                and "parameter" not in attrs:
            saved.add(mm.group(1))
    return vtype, arrays, saved, False


def parse_program(source: str, version: int,
                  lang: str | None = None) -> ProgramTree:
    """Directive tree of a free-form Fortran source (see the module doc),
    or of a C source (``offload.engine.c_program``; `lang` "c", or
    None and the source has a ``#pragma omp`` line)."""
    from offload.engine.c_program import is_c_source, parse_c_program
    if lang == "c" or (lang is None and is_c_source(source)):
        return parse_c_program(source, version)
    tree = _parse_fortran(source, version)
    # Integer object-like macros of a preprocessed source (the
    # omp_vv Fortran tests), for the iterator range rule
    tree.extra["macros"] = {
        k: int(v) for k, v in re.findall(
            r"^\s*#\s*define\s+([A-Za-z_]\w*)\s+\(?\s*(-?\d+)\s*\)?\s*$",
            source, re.M)}
    return tree


def _parse_fortran(source: str, version: int) -> ProgramTree:
    tree = ProgramTree([], [], [], {})
    stack: list = []
    just_closed: int | None = None
    model = model_of(version)

    def association(key):
        return _association(key, model)

    def innermost_dir():
        for f in reversed(stack):
            if isinstance(f, _Dir):
                return f
        return None

    def close_loop_without_do(f: _Dir):
        stack.pop()
        tree.assoc[f.index].end_line = tree.assoc[f.index].line

    def describe(f):
        if isinstance(f, _Dir):
            a = tree.assoc[f.index]
            return (f"!${model} {tree.directives[f.index].name} "
                    f"(line {a.line})")
        return f"{'DO' if isinstance(f, _Do) else 'BLOCK'} (line {f.line})"

    def end_follows(k: int, name: str) -> bool:
        """Whether the next directive after item k is `end <name>`."""
        for _, kind, text in items[k + 1:]:
            if kind == "omp":
                d = parse_directive(text, "fortran", version)
                return d.end and d.name == name
        return False

    unit, depth = 0, 0  # program units started; header nesting depth
    scopes: list[int] = [0]  # scoping units; 0 is the file outside units
    nscopes = 0
    in_type = None  # name of the derived type being defined
    items = list(_logical_lines(source, model))
    for k, (line, kind, text) in enumerate(items):
        top = stack[-1] if stack else None
        if isinstance(top, _Dir) and top.pending:
            if top.kind == "loop":
                if kind == "stmt" and _is_do(_LABEL.sub("", text)):
                    pass  # the DO is handled below
                elif kind == "omp":
                    d = parse_directive(text, "fortran", version)
                    if not d.end and association(d.name) == "loop":
                        raise ProgramError(
                            f"line {line}: loop-transforming or loop "
                            f"directive {d.name!r} between a loop directive "
                            "and its DO loop is not supported")
                    close_loop_without_do(top)
                else:
                    close_loop_without_do(top)
            else:  # block directive: a BLOCK construct is handled below
                top.pending = kind == "stmt" and bool(_BLOCK.match(text))
        if kind == "omp":
            d = parse_directive(text, "fortran", version)
            if d.end:
                if just_closed is not None \
                        and tree.directives[just_closed].name == d.name:
                    tree.ends[just_closed] = d
                    tree.assoc[just_closed].end_line = line
                    just_closed = None
                    continue
                top = stack[-1] if stack else None
                if not (isinstance(top, _Dir) and top.kind == "block"
                        and tree.directives[top.index].name == d.name):
                    opened = describe(top) if top else "no open construct"
                    raise ProgramError(f"line {line}: !${model} end "
                                       f"{d.name} does not match {opened}")
                stack.pop()
                tree.ends[top.index] = d
                tree.assoc[top.index].end_line = line
                just_closed = None
                continue
            just_closed = None
            idx = len(tree.directives)
            parent = innermost_dir()
            tree.directives.append(d)
            if parent is not None:
                tree.nesting.append((parent.index, idx))
            how = association(d.name)
            if stack and isinstance(stack[-1], (_Do, _Blk)):
                stack[-1].directive = True
                stack[-1].transform |= how == "loop"
            if how == "loopseq":
                raise ProgramError(f"line {line}: loop-sequence directive "
                                   f"{d.name!r} is not supported")
            tree.assoc.append(Assoc(kind=how, line=line, unit=unit,
                                    scope=tuple(scopes)))
            if how == "statement" and end_follows(k, d.name):
                stack.append(_Dir(idx, "block"))  # several statements
            elif how in ("block", "loop", "statement"):
                stack.append(_Dir(idx, how, pending=how != "statement"))
            continue
        # a base-language statement
        stmt = _LABEL.sub("", text)
        tree.statements.append((line, stmt, tuple(scopes)))
        vtype, arrays, saved, save_all = _decl_facts(stmt)
        if not in_type:
            if vtype:
                for name in (_declaration(stmt) or (None, []))[1]:
                    tree.vtypes[(scopes[-1], name)] = vtype
            tree.arrays |= {(scopes[-1], x) for x in arrays}
            tree.saved |= {(scopes[-1], x) for x in saved}
            if save_all:
                tree.saved.add((scopes[-1], "*"))
        if just_closed is not None:
            just_closed = None
        owner = innermost_dir()
        if owner is not None:
            tree.assoc[owner.index].stmts += 1
        if _UNIT_HEAD.match(stmt) and not stmt.startswith("end"):
            depth += 1
            if depth == 1:
                unit += 1
            nscopes += 1
            scopes.append(nscopes)
            km = _UNIT_KIND.match(stmt)
            kind = next((g for g in km.groups()[:5] if g), "") if km else ""
            tree.units[nscopes] = (re.sub(r"\s+", "", kind),
                                   km.group(6) if km else None)
        elif _UNIT_TAIL.match(stmt) and depth:
            depth -= 1
            scopes.pop()
        elif _TYPE_DEF.match(stmt):
            in_type = re.match(r".*?([a-z_]\w*)(?:\s*\(.*\))?$",
                               stmt).group(1)
            tree.types.setdefault((scopes[-1], in_type), {})
        elif _END_TYPE.match(stmt):
            in_type = None
        elif _use_names(stmt) is not False:
            tree.uses.setdefault(scopes[-1], []).append(_use_names(stmt))
            tree.use_modules.setdefault(scopes[-1], []).append(
                _USE_MOD.match(stmt).group(1))
        else:
            decl = _declaration(stmt)
            if decl and _TYPE_SPEC.match(stmt) and "::" in stmt and re.search(
                    r",\s*parameter\b", stmt.split("::", 1)[0]):
                tree.params |= {(scopes[-1], x) for x in decl[1]}
            if decl:
                attr, names = decl
                m = _DECL_TYPE.match(stmt)
                tname = m.group(1) if m else None
                for name in names:
                    if in_type:
                        tree.types[(scopes[-1], in_type)][name] = (attr,
                                                                   tname)
                        continue
                    key = (scopes[-1], name)
                    old = tree.decls.get(key)
                    if old is None or _RANK[attr] > _RANK[old]:
                        tree.decls[key] = attr
                    if tname:
                        tree.vartypes[key] = tname
        if _UNIT_END.match(stmt):
            if stack:
                raise ProgramError(f"line {line}: {stmt!r} while "
                                   f"{describe(stack[-1])} is still open")
            continue
        if _BLOCK.match(stmt):
            blk = _Blk(line)
            top = stack[-1] if stack else None
            if isinstance(top, (_Do, _Blk)):
                top.loops.append(blk)
            elif isinstance(top, _Dir) and top.kind == "block" and top.pending:
                top.pending = False
                blk.owner = top.index
                tree.assoc[top.index].stmts -= 1  # the block itself
            stack.append(blk)
            continue
        if _END_BLOCK.match(stmt):
            top = stack[-1] if stack else None
            if not isinstance(top, _Blk):
                raise ProgramError(f"line {line}: END BLOCK does not match "
                                   f"{describe(top) if top else 'any BLOCK'}")
            stack.pop()
            if top.owner is not None:
                stack.pop()  # the block directive whose block this is
                tree.assoc[top.owner].stmts -= 1
                tree.assoc[top.owner].end_line = line
                just_closed = top.owner
            continue
        if _is_do(stmt):
            rest = _DO.match(stmt).group(1)
            do = _Do(_do_var(rest, line), line, bounds=_do_bounds(rest))
            top = stack[-1] if stack else None
            if isinstance(top, (_Do, _Blk)):
                top.loops.append(do)
            elif isinstance(top, _Dir) and top.kind == "loop" and top.pending:
                top.pending = False
                do.owner = top.index
            stack.append(do)
            continue
        if _END_DO.match(stmt):
            top = stack[-1] if stack else None
            if not isinstance(top, _Do):
                raise ProgramError(f"line {line}: END DO does not match "
                                   f"{describe(top) if top else 'any DO'}")
            stack.pop()
            if top.owner is not None:
                stack.pop()  # the loop directive owning this DO
                dos, known = _chain(top)
                vars_ = tuple(d.var for d in dos)
                a = tree.assoc[top.owner]
                a.loop_depth, a.loop_vars = len(vars_), vars_
                a.depth_known = known
                a.loop_bounds = tuple(d.bounds for d in dos)
                a.intervening = _intervening(dos)
                a.end_line = line
                just_closed = top.owner
            continue
        top = stack[-1] if stack else None
        if isinstance(top, (_Do, _Blk)) and not _declaration(stmt) \
                and _use_names(stmt) is False \
                and not re.match(r"^implicit\b", stmt):
            top.stmts += 1  # executable statement in a DO or BLOCK body
        if isinstance(top, _Dir) and top.kind == "statement":
            stack.pop()
            tree.assoc[top.index].end_line = line
            just_closed = top.index
    if stack:
        raise ProgramError(f"{describe(stack[-1])} is never closed")
    return tree


# --- rules -------------------------------------------------------------------

class RuleError(ValueError):
    """A malformed rules file."""


@dataclass(frozen=True)
class Rule:
    id: str          # OMP<ver>-<construct-or-topic>-<kind>-<nnn>
    text: str        # the spec sentence, verbatim
    citation: str    # "OpenMP <ver> §<sec>, p.<n>"
    check: str       # static | runtime
    status: str      # provisional | reviewed
    predicate: str | None
    version: int = 0
    also: tuple = ()
    why: str = ""
    example: str = ""
    notes: str = ""
    lang: str = "both"  # "both", "f90" or "c"

    def applies(self, lang: str) -> bool:
        """Whether the rule holds for a program in `lang`."""
        return self.lang in ("both", lang)


PREDICATES: dict[str, Callable] = {}


def predicate(fn):
    """Register a rule predicate under its function name (a name may be
    registered once: the OpenMP and OpenACC predicates share the
    registry)."""
    if fn.__name__ in PREDICATES and PREDICATES[fn.__name__] is not fn:
        raise RuleError(f"predicate {fn.__name__!r} registered twice")
    PREDICATES[fn.__name__] = fn
    return fn


_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-[a-z]+-\d{3}$")
_CITATION = re.compile(r"^OpenMP (\d)\.(\d) §[\d.]+, p\.\d+$")
_CITATIONS = {"omp": _CITATION,
              "acc": re.compile(r"^OpenACC (\d)\.(\d) §[\d.]+, p\.\d+$")}
RULE_PREFIX = {"omp": "OMP", "acc": "ACC"}


def rules_from_list(entries: list, model: str = "omp") -> list[Rule]:
    """Expand rules.yaml entries into one Rule per version (see module doc;
    OpenACC rules: ``ACC<ver>-<stem>``)."""
    _CITATION = _CITATIONS[model]
    out, seen = [], set()
    for e in entries:
        stem = e.get("id", "")
        if not _ID.match(stem):
            raise RuleError(f"bad rule id {stem!r}")
        check, pred = e.get("check"), e.get("predicate")
        if check not in ("static", "runtime"):
            raise RuleError(f"{stem}: check must be static or runtime")
        if e.get("status") not in ("provisional", "reviewed"):
            raise RuleError(f"{stem}: status must be provisional or reviewed")
        if check == "static" and pred not in PREDICATES:
            raise RuleError(f"{stem}: static rule needs a registered "
                            f"predicate, got {pred!r}")
        if check == "runtime" and (pred is not None or not e.get("why")):
            raise RuleError(f"{stem}: a runtime rule has predicate: null "
                            "and says why in `why`")
        spec = e.get("spec") or {}
        if not spec:
            raise RuleError(f"{stem}: no spec entry")
        lang = e.get("lang", "both")
        if lang not in ("both", "f90", "c"):
            raise RuleError(f"{stem}: lang must be both, f90 or c")
        for ver, s in spec.items():
            rid = f"{RULE_PREFIX[model]}{ver}-{stem}"
            if model_of(int(ver)) != model:
                raise RuleError(f"{rid}: version {ver} is not {model}")
            m = _CITATION.match(s.get("citation", ""))
            if not m or int(m.group(1) + m.group(2)) != ver:
                raise RuleError(f"{rid}: bad citation {s.get('citation')!r}")
            if rid in seen:
                raise RuleError(f"duplicate rule id {rid}")
            seen.add(rid)
            out.append(Rule(rid, " ".join(s["text"].split()), s["citation"],
                            check, e["status"], pred, int(ver),
                            tuple(s.get("also", ())), e.get("why", ""),
                            e.get("example", ""), e.get("notes", ""), lang))
    return out


def load_rules(path: Path = RULES_PATH, model: str = "omp") -> list[Rule]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return rules_from_list(data["rules"], model)


@lru_cache(maxsize=1)
def default_rules() -> tuple:
    """The OpenMP rules (catalog/omp/rules.yaml)."""
    return tuple(load_rules())


@lru_cache(maxsize=1)
def acc_rules() -> tuple:
    """The OpenACC rules (catalog/acc/rules.yaml); their predicates are
    registered by offload.engine.acc_rules."""
    import offload.engine.acc_rules  # noqa: F401 - registers the predicates
    return tuple(load_rules(catalog_dir("acc") / "rules.yaml", "acc"))


def rules_for(version: int) -> tuple:
    """The rules of the model of `version`."""
    return acc_rules() if model_of(version) == "acc" else default_rules()


def findings(tree: ProgramTree, version: int,
             rules=None) -> list[tuple[str, int]]:
    """(rule id, directive index) for every violation of a static rule
    that holds in the tree's language (Rule.lang)."""
    out = set()
    lang = getattr(tree, "lang", "f90")
    for r in rules if rules is not None else rules_for(version):
        if r.version == version and r.check == "static" and r.applies(lang):
            out.update((r.id, i) for i in PREDICATES[r.predicate](tree,
                                                                  version))
    return sorted(out)


def violations(tree: ProgramTree, version: int, rules=None) -> list[str]:
    """Sorted ids of the static rules the program violates, each once."""
    return sorted({rid for rid, _ in findings(tree, version, rules)})


# --- helpers for predicates --------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _compact(name: str) -> str:
    return name.replace(" ", "").replace("_", "")


@lru_cache(maxsize=1)
def _names() -> dict:
    """Directive spelling without blanks or underscores -> skeleton key."""
    out = {}
    for key, spec in default_skeleton().directives.items():
        for s in spec.spellings:
            out.setdefault(_compact(s.text), key)
    for e in default_grammar().spellings:
        out.setdefault(_compact(e.spelling), e.directive)
    return out


def _clauses(tree: ProgramTree, i: int, *names: str, end: bool = False):
    """Clauses of directive i (and of its end directive if `end`)."""
    ds = [tree.directives[i]]
    if end and i in tree.ends:
        ds.append(tree.ends[i])
    return [c for d in ds for c in d.clauses if not names or c.name in names]


def _items(clauses) -> list[str]:
    return [_norm(a) for c in clauses for a in c.args]


def _base(item: str) -> str:
    m = re.match(r"(/\w+/|[a-z_]\w*)", item)
    return m.group(1) if m else item


# List items in C: a[...] for an element or section, s.c / p->c
# for a structure element
_C_PART = re.compile(r"\[|->|\.(?=[a-z_])")


def _is_part(item: str) -> bool:
    """A list item that is part of another variable: an array element or
    section, or a structure element (Fortran x(...), s%c; C x[...], s.c,
    p->c)."""
    return "(" in item or "%" in item or bool(_C_PART.search(item))


def _is_component(item: str) -> bool:
    """A structure element (Fortran s%c, C s.c or p->c)."""
    return "%" in item or "->" in item or bool(
        re.search(r"\.(?=[a-z_])", item))


def _section_base(item: str) -> str | None:
    """The base expression text of an array section item (Fortran
    b(l:u), C b[l:n]), None if the item is not a section."""
    m = re.match(r"^(.*?)\((?=[^()]*:)", item) or re.match(
        r"^(.*?)\[(?=[^\[\]]*:)", item)
    return m.group(1) if m else None


def _int(expr: str) -> int | None:
    """The value of an integer literal (optionally signed, kind, parens)."""
    m = re.fullmatch(r"\(*([+-]?\d+)(?:_\w+)?\)*", _norm(expr))
    return int(m.group(1)) if m else None


def _leaves(tree: ProgramTree, i: int) -> list[str]:
    return leaves(tree.directives[i].name)


def _ancestors(tree: ProgramTree, i: int) -> list[int]:
    out = []
    p = tree.parent(i)
    while p is not None:
        out.append(p)
        p = tree.parent(p)
    return out


def _enclosing_leaf(tree: ProgramTree, i: int, leaf: str) -> str | None:
    """The construct that immediately encloses the `leaf` constituent of
    directive i: the previous leaf of a compound directive, else the
    innermost leaf of the lexically enclosing construct, else None."""
    ls = _leaves(tree, i)
    k = ls.index(leaf)
    if k:
        return ls[k - 1]
    p = tree.parent(i)
    return None if p is None else _leaves(tree, p)[-1]


def _dnm(clause, key: str, version: int) -> list[str]:
    """The directive-name modifiers of a clause, as written."""
    entry = default_grammar().clauses.get(clause.name)
    form = entry.form_for(key, version) if entry else None
    if form is None:
        return []

    def has_dnm(nodes):
        return any((n.kind == "mods" and DIRECTIVE_NAME_CLASS in n.values)
                   or (n.kind == "opt" and has_dnm(n.body)) for n in nodes)

    if not any(has_dnm(alt) for alt in form.syntax):
        return []
    keywords = {k for mc in form.modifiers.values() for k in mc.keywords}
    return [m for m in clause.modifiers
            if _compact(m) in _names() and m not in keywords]


# 6.0 target_data is a composite of three constituent directives (6.0 §15.7,
# p.458) that the skeleton does not list as leaves.
_TARGET_DATA_60 = ["target enter data", "task", "target exit data"]


def _rule_leaves(key: str, version: int) -> list[str]:
    """Leaves of a directive for the rules (6.0 target data: its three
    constituent directives)."""
    if key == "target data" and version >= 60:
        return list(_TARGET_DATA_60)
    return leaves(key)


def _constituents(key: str, version: int) -> set[str]:
    """The directive and its constituent directives: each leaf and each
    directive named by consecutive leaves (6.0 glossary, p.35)."""
    ls = _rule_leaves(key, version)
    out = {key}
    for a in range(len(ls)):
        for b in range(a + 1, len(ls) + 1):
            hit = _names().get(_compact(" ".join(ls[a:b])))
            if hit:
                out.add(hit)
    return out


def _has_ancestor_device(tree: ProgramTree, i: int) -> bool:
    return any("ancestor" in c.modifiers for c in _clauses(tree, i, "device"))


_DEVICE_CONSTRUCTS = {"target", "target data", "target enter data",
                      "target exit data", "target update"}
_LOOP_TRANSFORMS = {"fuse", "interchange", "reverse", "split", "stripe",
                    "tile", "unroll"}
_WORKSHARING = {"do", "for", "sections", "single", "workshare", "scope"}
_DSA = ("private", "firstprivate", "lastprivate", "shared", "linear",
        "reduction", "in_reduction", "is_device_ptr", "use_device_ptr",
        "has_device_addr", "use_device_addr")


def _each(tree: ProgramTree, test) -> list[int]:
    return [i for i in range(len(tree.directives)) if test(i)]


def _map_construct(tree: ProgramTree, i: int) -> bool:
    """Map clauses "on a construct": not those of declare mapper."""
    return tree.directives[i].name != "declare mapper"


# --- Helpers -----------------------------------------------------------

# Directives that are not constructs (declarative, informational/utility,
# subsidiary and separating directives): the nesting rules about
# constructs and regions do not count them (assume is an informational
# directive: lenient, it is outside the slice).
_NOT_CONSTRUCT = {
    "declare target", "declare simd", "declare variant", "declare mapper",
    "declare reduction", "declare_induction", "requires", "threadprivate",
    "groupprivate", "allocate", "assumes", "begin assumes",
    "begin declare target", "begin declare variant", "end assumes",
    "end declare target", "end declare variant", "error", "nothing",
    "metadirective", "unknown", "scan", "section", "assume"}


def _is_construct(tree: ProgramTree, i: int) -> bool:
    return tree.directives[i].name not in _NOT_CONSTRUCT


def _extent(tree: ProgramTree, i: int) -> tuple:
    a = tree.assoc[i]
    return a.line, (a.end_line if a.end_line is not None else a.line)


def _body(tree: ProgramTree, i: int, strict: bool = False) -> list:
    """(line, statement) of the base-language statements in the lexical
    extent of directive i (a loop construct: its DO nest; strict: not
    inside a nested construct's extent)."""
    a = tree.assoc[i]
    if a.kind == "standalone":
        return []
    lo, hi = _extent(tree, i)
    nested = [_extent(tree, c) for c in tree.descendants(i)
              if tree.assoc[c].kind != "standalone"] if strict else []
    return [(ln, st) for ln, st, _ in tree.statements
            if lo < ln <= hi and not any(a_ <= ln <= b_ for a_, b_ in nested)]


_STRING = re.compile(r"'[^']*'|\"[^\"]*\"")
_API_CALL = re.compile(r"\b(omp_\w+)\s*\(|\bcall\s+(omp_\w+)")


def _api_calls(stmt: str) -> list[str]:
    """Names of OpenMP runtime routines referenced (called) in a
    statement: omp_name(or CALL omp_name."""
    return [a or b for a, b in _API_CALL.findall(_STRING.sub("", stmt))]


def _outer_leaves(tree: ProgramTree, i: int):
    """(directive index, leaf) of the constructs enclosing directive i,
    innermost first (the leaves of each enclosing compound from its
    innermost leaf outward)."""
    for p in _ancestors(tree, i):
        for leaf in reversed(_leaves(tree, p)):
            yield p, leaf


def _assoc_count(tree: ProgramTree, i: int) -> int | None:
    """Number of loops associated with loop directive i: collapse(n) (1
    without), or ordered(n) when larger (5.2 §4.4.4: the loops associated
    with the construct); None when collapse is not an integer literal."""
    n = _collapse(tree, i)
    if n is None:
        return None
    o = _items(_clauses(tree, i, "ordered"))
    if o and _int(o[0]) is not None:
        n = max(n, _int(o[0]))
    return n


def _order_concurrent(tree: ProgramTree, i: int) -> bool:
    """A construct on which order(concurrent) is specified, or with a loop
    leaf and no order clause (5.2 §11.7, 6.0 §13.8: as if order(concurrent)
    is present)."""
    orders = _clauses(tree, i, "order")
    if orders:
        return "concurrent" in _items(orders)
    return "loop" in _leaves(tree, i)


# --- predicates: nesting and placement ---------------------------------------

@predicate
def teams_strictly_nested_in_target(tree, version):
    """A teams constituent whose immediately enclosing construct (in this
    source) is not a target construct."""
    return _each(tree, lambda i: "teams" in _leaves(tree, i) and
                 _enclosing_leaf(tree, i, "teams") not in (None, "target"))


@predicate
def target_contains_only_teams(tree, version):
    """A target construct with a nested teams construct that also contains a
    statement or another directive outside the teams construct."""
    def bad(i):
        if tree.directives[i].name != "target":
            return False
        kids = tree.children(i)
        return any(_leaves(tree, k)[0] == "teams" for k in kids) and (
            tree.assoc[i].stmts > 0 or len(kids) > 1)
    return _each(tree, bad)


@predicate
def teams_nested_regions(tree, version):
    """A directive nested directly in a teams construct (or a compound
    construct ending in teams) whose outermost leaf is not distribute,
    parallel or loop (6.0: or a loop-transforming construct, or
    workdistribute, which 6.0 §13.5 requires to be closely nested in teams
    although its properties omit teams-nestable)."""
    ok = {"distribute", "parallel", "loop"}
    if version >= 60:
        ok |= _LOOP_TRANSFORMS | {"workdistribute"}
    teams = [i for i in range(len(tree.directives))
             if _leaves(tree, i)[-1] == "teams"]
    out = {c for i in teams for c in tree.children(i)
           if _leaves(tree, c)[0] not in ok}
    # Routine regions strictly nested in teams: only
    # omp_get_num_teams and omp_get_team_num (5.2 §10.2; 6.0: the
    # teams-nestable routines, §22.1, §22.3) may be called in the teams
    # body outside nested constructs
    routines = {"omp_get_num_teams", "omp_get_team_num"}
    out |= {i for i in teams for _, st in _body(tree, i, strict=True)
            if set(_api_calls(st)) - routines}
    return sorted(out)


def _in_main_program(tree: ProgramTree, i: int) -> bool:
    """Directive i is in a main program's scoping unit (no caller can put
    it into another region)."""
    return tree.units.get(tree.assoc[i].scope[-1], ("", None))[0] \
        == "program"


def _outside(tree, i, leaf, want) -> bool:
    """The constituent `leaf` of directive i is not immediately enclosed by
    `want`: another enclosing construct, or none in a main program (Task
    16: an orphaned construct of a main program is in the implicit parallel
    region)."""
    enc = _enclosing_leaf(tree, i, leaf)
    return enc != want and (enc is not None or _in_main_program(tree, i))


@predicate
def distribute_strictly_nested_in_teams(tree, version):
    """A distribute constituent whose immediately enclosing construct (in
    this source) is not a teams construct, or that has none in a main
    program."""
    return _each(tree, lambda i: "distribute" in _leaves(tree, i) and
                 _outside(tree, i, "distribute", "teams"))


@predicate
def loop_orphan_has_bind(tree, version):
    """A loop directive not nested in any construct, without a bind
    clause (5.0: only when it appears in a procedure, 5.0 §2.9.5 p.131)."""
    def in_procedure(i):
        return any(tree.units.get(s, ("", None))[0] in ("subroutine",
                                                        "function")
                   for s in tree.assoc[i].scope)
    return _each(tree, lambda i: tree.directives[i].name == "loop"
                 and tree.parent(i) is None
                 and not _clauses(tree, i, "bind")
                 and (version > 50 or in_procedure(i)))


@predicate
def loop_bind_teams_in_teams(tree, version):
    """A loop constituent with bind(teams) whose immediately enclosing
    construct (in this source) is not a teams construct, or that has none
    in a main program."""
    return _each(tree, lambda i: "loop" in _leaves(tree, i)
                 and "teams" in _items(_clauses(tree, i, "bind"))
                 and _outside(tree, i, "loop", "teams"))


@predicate
def device_construct_in_target(tree, version):
    """A device-affecting construct (target, target data, target enter/exit
    data, target update) lexically inside a construct with a target leaf,
    unless it is a target construct with device(ancestor: ...)."""
    def bad(i):
        if _leaves(tree, i)[0] not in _DEVICE_CONSTRUCTS:
            return False
        if _leaves(tree, i)[0] == "target" and _has_ancestor_device(tree, i):
            return False
        return any("target" in _leaves(tree, a) for a in _ancestors(tree, i))
    return _each(tree, bad)


@predicate
def order_concurrent_nesting(tree, version):
    """A directive nested in a construct with order(concurrent) whose
    outermost leaf is not loop, parallel or simd (5.2: any nested directive;
    6.0: directly nested ones, and also atomic and loop-transforming
    constructs)."""
    if version >= 60:
        ok, nested = ({"loop", "parallel", "simd", "atomic"}
                      | _LOOP_TRANSFORMS), tree.children
    else:
        ok, nested = {"loop", "parallel", "simd"}, tree.descendants
    # A loop construct without an order clause behaves as if
    # order(concurrent) is present (5.2 §11.7, p.257; 6.0 §13.8, p.423)
    return sorted({c for i in range(len(tree.directives))
                   if _order_concurrent(tree, i)
                   for c in nested(i) if _is_construct(tree, c)
                   and _leaves(tree, c)[0] not in ok})


@predicate
def declare_target_in_specification_part(tree, version):
    """A declare target directive lexically inside an OpenMP construct (so
    in an execution part, not a specification part)."""
    return _each(tree, lambda i: tree.directives[i].name == "declare target"
                 and tree.parent(i) is not None)


@predicate
def requires_in_specification_part(tree, version):
    """A requires directive lexically inside an OpenMP construct."""
    return _each(tree, lambda i: tree.directives[i].name == "requires"
                 and tree.parent(i) is not None)


@predicate
def requires_before_device_constructs(tree, version):
    """A requires directive with reverse_offload, unified_address or
    unified_shared_memory after a device construct of the same program unit
    (the Fortran compilation unit)."""
    req = {"reverse_offload", "unified_address", "unified_shared_memory"}

    def bad(i):
        return tree.directives[i].name == "requires" \
            and bool(_clauses(tree, i, *req)) and any(
                _leaves(tree, j)[0] in _DEVICE_CONSTRUCTS
                and tree.assoc[j].unit == tree.assoc[i].unit
                for j in range(i))
    return _each(tree, bad)


@predicate
def requires_same_memory_order(tree, version):
    """A requires directive whose atomic_default_mem_order argument differs
    from that of an earlier requires directive of the same program unit
    (5.0: any second one, 5.0 §2.4 p.63)."""
    seen, out = {}, []
    for i in range(len(tree.directives)):
        unit = tree.assoc[i].unit
        for o in _items(_clauses(tree, i, "atomic_default_mem_order")):
            if unit in seen and (version == 50 or seen[unit] != o):
                out.append(i)
            seen.setdefault(unit, o)
    return out


# --- predicates: loop association --------------------------------------------

def _collapse(tree, i) -> int | None:
    args = _items(_clauses(tree, i, "collapse"))
    return _int(args[0]) if args else 1


@predicate
def loop_nest_follows(tree, version):
    """A loop-nest-associated directive not followed by a DO loop of the
    form DO var = ... (or DO CONCURRENT)."""
    return _each(tree, lambda i: tree.assoc[i].kind == "loop"
                 and tree.assoc[i].loop_depth == 0)


@predicate
def collapse_within_depth(tree, version):
    """collapse(n) with an integer literal n greater than the depth of the
    DO nest that follows."""
    def bad(i):
        a = tree.assoc[i]
        n = _collapse(tree, i) if _clauses(tree, i, "collapse") else None
        return a.kind == "loop" and a.loop_depth > 0 and a.depth_known \
            and n is not None and n > a.loop_depth
    return _each(tree, bad)


@predicate
def loop_lastprivate_iteration_variable(tree, version):
    """A lastprivate list item on a directive with a loop leaf that is not
    the iteration variable of one of the collapsed loops."""
    def bad(i):
        a = tree.assoc[i]
        if "loop" not in _leaves(tree, i) or a.loop_depth == 0 \
                or not a.depth_known:
            return False
        n = _collapse(tree, i)
        loop_vars = a.loop_vars[:n] if n is not None else a.loop_vars
        return any(x not in loop_vars
                   for x in _items(_clauses(tree, i, "lastprivate")))
    return _each(tree, bad)


# --- predicates: data mapping ------------------------------------------------

_MAP_TYPES = {52: {"alloc", "delete", "from", "release", "to", "tofrom"},
              60: {"alloc", "from", "release", "storage", "to", "tofrom"}}


def _map_types(tree, i, version) -> list[str | None]:
    types = _MAP_TYPES[52 if version < 60 else 60]
    out = []
    for c in _clauses(tree, i, "map"):
        t = [m for m in c.modifiers if m in types]
        out.append(t[0] if t else None)
    return out


def _map_type_not_in(allowed):
    def check(tree, i, version):
        return any(t not in allowed for t in _map_types(tree, i, version))
    return check


@predicate
def target_map_types(tree, version):
    """A map clause on a directive with a target leaf whose map-type is not
    to, from, tofrom or alloc (5.2)."""
    bad = _map_type_not_in({None, "to", "from", "tofrom", "alloc"})
    return _each(tree, lambda i: "target" in _leaves(tree, i)
                 and bad(tree, i, version))


@predicate
def target_data_map_types(tree, version):
    """A map clause on target data whose map-type is not to, from, tofrom
    or alloc (5.2)."""
    bad = _map_type_not_in({None, "to", "from", "tofrom", "alloc"})
    return _each(tree, lambda i: tree.directives[i].name == "target data"
                 and bad(tree, i, version))


@predicate
def enter_data_map_entering(tree, version):
    """A map clause on target enter data that is not map-entering: 5.2
    map-type other than to, tofrom, alloc; 6.0 other than to, tofrom,
    storage or alloc (alloc stands for storage on map-entering constructs).
    A clause without a map-type defaults to tofrom (6.0: storage with the
    delete modifier), both map-entering."""
    allowed = {None, "to", "tofrom", "alloc"} | (
        {"storage"} if version >= 60 else set())
    if version == 50:  # 5.0 §2.12.3 p.166: a map-type, to or alloc
        allowed = {"to", "alloc"}
    bad = _map_type_not_in(allowed)
    return _each(tree, lambda i: tree.directives[i].name == "target enter data"
                 and bad(tree, i, version))


@predicate
def exit_data_map_exiting(tree, version):
    """A map clause on target exit data that is not map-exiting: 5.2
    map-type other than from, tofrom, release, delete; 6.0 other than from,
    tofrom, storage or release (release stands for storage on map-exiting
    constructs; delete is a modifier there)."""
    allowed = {None, "from", "tofrom", "release"} | (
        {"storage"} if version >= 60 else {"delete"})
    if version == 50:  # 5.0 §2.12.4 p.169: a map-type, from/release/delete
        allowed = {"from", "release", "delete"}
    bad = _map_type_not_in(allowed)
    return _each(tree, lambda i: tree.directives[i].name == "target exit data"
                 and bad(tree, i, version))


def _mapper(clause) -> str:
    for m in clause.modifiers:
        mm = re.fullmatch(r"mapper\s*\((.*)\)", m)
        if mm:
            return _norm(mm.group(1))
    return "default"


@predicate
def map_same_item_same_mapper(tree, version):
    """The same list item (same text) in map clauses of one directive with
    different mapper modifiers (no modifier means mapper(default))."""
    def bad(i):
        mappers = {}
        for c in _clauses(tree, i, "map"):
            for x in _items([c]):
                mappers.setdefault(x, set()).add(_mapper(c))
        return any(len(v) > 1 for v in mappers.values())
    return _each(tree, lambda i: _map_construct(tree, i) and bad(i))


@predicate
def map_whole_and_part(tree, version):
    """Map clauses of one directive that name a variable and also an array
    section or element of it (x and x(...)): different list items that
    share storage, neither the containing structure of the other. Only when
    x has a visible non-POINTER declaration in the source
    (ProgramTree.designator_attribute; for s%c the declared type of s must
    be defined in the source with c non-POINTER): a pointer x maps the
    pointer and x(...) its target, and an undeclared or possibly
    use-associated x (or type) is not checked."""
    def not_pointer(i, x):
        return tree.designator_attribute(i, x) in ("allocatable", "plain")

    def bad(i):
        xs = set(_items(_clauses(tree, i, "map")))
        return any((y.startswith(x + "(") or y.startswith(x + "["))
                   and not_pointer(i, x) for x in xs for y in xs)
    return _each(tree, lambda i: _map_construct(tree, i) and bad(i))


@predicate
def map_self_consistent(tree, version):
    """A map list item with the self modifier and another map list item of
    the same base variable without it, on one directive."""
    def bad(i):
        cs = _clauses(tree, i, "map")
        selfish = {_base(x) for c in cs if "self" in c.modifiers
                   for x in _items([c])}
        return any(_base(x) in selfish for c in cs
                   if "self" not in c.modifiers for x in _items([c]))
    return _each(tree, lambda i: _map_construct(tree, i) and bad(i))


@predicate
def target_dsa_not_mapped(tree, version):
    """On a target construct, a list item of private, firstprivate,
    is_device_ptr or has_device_addr with the same base variable as a map
    list item."""
    def bad(i):
        if tree.directives[i].name != "target":
            return False
        dsa = {_base(x) for x in _items(_clauses(
            tree, i, "private", "firstprivate", "is_device_ptr",
            "has_device_addr"))}
        return bool(dsa & {_base(x) for x in _items(_clauses(tree, i,
                                                               "map"))})
    return _each(tree, bad)


def _categories(tree, i) -> list[str]:
    """The variable-category of each defaultmap clause of directive i; a
    clause without one counts as all ("If no variable-category is specified
    in the clause then the effect is as if all was specified", 5.2 §5.8.7
    p.161 l.17-18; in 5.0 such a clause applies to every category)."""
    return [(_norm(c.modifiers[0]) if c.modifiers else "all")
            for c in _clauses(tree, i, "defaultmap")]


@predicate
def defaultmap_category_once(tree, version):
    """Two defaultmap clauses on one directive whose variable-categories
    overlap: the same category twice, or all (a clause without a category)
    beside any other defaultmap clause."""
    def bad(i):
        cats = _categories(tree, i)
        # from 5.2 defaultmap-map-002 refuses all beside another clause
        return len(cats) != len(set(cats)) or (
            version < 52 and "all" in cats and len(cats) > 1)
    return _each(tree, bad)


@predicate
def defaultmap_all_alone(tree, version):
    """A defaultmap clause with the all variable-category and another
    defaultmap clause on the same directive."""
    return _each(tree, lambda i: "all" in _categories(tree, i)
                 and len(_clauses(tree, i, "defaultmap")) > 1)


# --- predicates: clauses -----------------------------------------------------

@predicate
def dnm_names_constituent(tree, version):
    """A directive-name modifier that names neither the directive nor one
    of its constituent directives."""
    def bad(i):
        key = tree.directives[i].name
        ok = _constituents(key, version)
        return any(_names()[_compact(m)] not in ok
                   for c in _clauses(tree, i) for m in _dnm(c, key, version))
    return _each(tree, bad)


@predicate
def if_once_per_constituent(tree, version):
    """Two if clauses that apply to a common leaf construct: an if clause
    without a directive-name modifier applies to every leaf, one with a
    modifier naming a constituent to that constituent's leaves."""
    def bad(i):
        key = tree.directives[i].name
        sets = []
        for c in _clauses(tree, i, "if"):
            dnm = _dnm(c, key, version)
            if not dnm:
                sets.append(set(_rule_leaves(key, version)))
                continue
            named = _names()[_compact(dnm[0])]
            if named in _constituents(key, version):
                sets.append(set(_rule_leaves(named, version)))
        return any(a & b for k, a in enumerate(sets) for b in sets[k + 1:])
    return _each(tree, bad)


def _not_positive(values) -> bool:
    return any(v is not None and v <= 0 for v in map(_int, values))


@predicate
def thread_limit_positive(tree, version):
    """thread_limit with an integer literal argument less than one."""
    return _each(tree, lambda i: _not_positive(
        [c.args[-1] for c in _clauses(tree, i, "thread_limit")]))


def _num_teams_bounds(tree, i, version):
    """(lower, upper) texts of each num_teams clause (lower None if absent)."""
    key = tree.directives[i].name
    out = []
    for c in _clauses(tree, i, "num_teams"):
        dnm = set(_dnm(c, key, version))
        lower = [m for m in c.modifiers if m not in dnm]
        out.append((lower[0] if lower else None, c.args[-1]))
    return out


@predicate
def num_teams_positive(tree, version):
    """num_teams with an integer literal lower-bound or upper-bound less
    than one."""
    return _each(tree, lambda i: any(
        _not_positive([lo, up] if lo is not None else [up])
        for lo, up in _num_teams_bounds(tree, i, version)))


@predicate
def num_teams_bounds_ordered(tree, version):
    """num_teams with integer literal bounds where lower-bound exceeds
    upper-bound."""
    def bad(i):
        for lo, up in _num_teams_bounds(tree, i, version):
            lo, up = (_int(lo) if lo is not None else None), _int(up)
            if lo is not None and up is not None and lo > up:
                return True
        return False
    return _each(tree, bad)


@predicate
def dist_schedule_chunk_positive(tree, version):
    """dist_schedule with an integer literal chunk_size less than one."""
    return _each(tree, lambda i: _not_positive(
        [c.args[1] for c in _clauses(tree, i, "dist_schedule")
         if len(c.args) > 1]))


def _reductions(tree, i, modifier):
    return [c for c in _clauses(tree, i, "reduction") if modifier in
            c.modifiers]


@predicate
def reduction_task_placement(tree, version):
    """reduction(task, ...) on a directive without a parallel or
    worksharing leaf, or with a simd or loop leaf."""
    def bad(i):
        ls = set(_leaves(tree, i))
        return bool(_reductions(tree, i, "task")) and (
            not ls & ({"parallel"} | _WORKSHARING) or ls & {"simd", "loop"})
    return _each(tree, bad)


@predicate
def reduction_inscan_placement(tree, version):
    """reduction(inscan, ...) on a directive without a do or simd leaf, or
    with a distribute leaf (6.0: or taskloop; 5.0: on any directive but do,
    do simd, simd, parallel do and parallel do simd, 5.0 §2.19.5.4
    p.302)."""
    banned = {"distribute"} | ({"taskloop"} if version >= 60 else set())
    ok50 = {"do", "do simd", "simd", "parallel do", "parallel do simd",
            "for", "for simd", "parallel for", "parallel for simd"}

    def bad(i):
        ls = set(_leaves(tree, i))
        if version == 50:
            return bool(_reductions(tree, i, "inscan")) and \
                tree.directives[i].name not in ok50
        return bool(_reductions(tree, i, "inscan")) and (
            not ls & {"do", "for", "simd"} or ls & banned)
    return _each(tree, bad)


@predicate
def reduction_inscan_not_mixed(tree, version):
    """A reduction clause with inscan and one without it on one
    directive."""
    return _each(tree, lambda i: bool(_reductions(tree, i, "inscan")) and any(
        "inscan" not in c.modifiers for c in _clauses(tree, i, "reduction")))


@predicate
def reduction_inscan_no_ordered_schedule(tree, version):
    """reduction(inscan, ...) on a directive with an ordered or schedule
    clause."""
    return _each(tree, lambda i: bool(_reductions(tree, i, "inscan"))
                 and bool(_clauses(tree, i, "ordered", "schedule")))


@predicate
def reduction_task_no_nowait(tree, version):
    """reduction(task, ...) on a directive with nowait (on the directive or
    its end directive)."""
    return _each(tree, lambda i: bool(_reductions(tree, i, "task"))
                 and bool(_clauses(tree, i, "nowait", end=True)))


@predicate
def distribute_firstprivate_lastprivate(tree, version):
    """A list item in both firstprivate and lastprivate on a directive with
    a distribute leaf."""
    return _each(tree, lambda i: "distribute" in _leaves(tree, i) and bool(
        set(_items(_clauses(tree, i, "firstprivate")))
        & set(_items(_clauses(tree, i, "lastprivate")))))


@predicate
def distribute_no_conditional_lastprivate(tree, version):
    """lastprivate(conditional: ...) on a directive with a distribute
    leaf."""
    return _each(tree, lambda i: "distribute" in _leaves(tree, i) and any(
        "conditional" in c.modifiers
        for c in _clauses(tree, i, "lastprivate")))


@lru_cache(maxsize=None)
def _allowed(leaf: str) -> dict:
    return default_grammar().allowed(default_skeleton(), leaf)


def _permits(leaf: str, clause: str, version: int) -> bool:
    rule = _allowed(leaf).get(clause)
    return rule is not None and rule_valid(rule, version)


def _dsa_split(tree, i, version) -> list[dict]:
    """Explicit data-sharing clauses of directive i split onto its leaf
    constructs per 5.2 §17.2 / 6.0 §19.2: for each leaf, list item -> the
    clause names applied to it there.

    private and linear: the innermost leaf permitting the clause;
    firstprivate: the listed leaves (distribute; teams without distribute; a
    worksharing leaf that accepts it; taskloop; parallel without taskloop or
    an accepting worksharing leaf; target unless the item is in lastprivate
    or is the base of a map list item), or the only permitting leaf;
    reduction: every permitting leaf except parallel combined with
    sections, do, loop or taskloop and teams combined with loop; every
    other clause (shared, lastprivate, in_reduction, is_device_ptr, ...):
    every permitting leaf; a clause no leaf permits but the directive does
    (6.0 target_data's use_device_*) stays on the directive. Not modeled
    (so never a violation by
    themselves): the implicit shared clauses the split adds on parallel and
    teams, the implicit map clauses on target, and the firstprivate /
    lastprivate effect of linear on the outer leaves."""
    key = tree.directives[i].name
    ls = _rule_leaves(key, version)
    out = [dict() for _ in ls] + [dict()]  # last: the directive itself
    lastp = set(_items(_clauses(tree, i, "lastprivate")))
    mapped = {_base(x) for x in _items(_clauses(tree, i, "map"))}
    for c in _clauses(tree, i, *_DSA):
        ks = [k for k, leaf in enumerate(ls) if _permits(leaf, c.name,
                                                            version)]
        if not ks:  # no leaf takes it (6.0 target_data: use_device_*)
            if _permits(key, c.name, version):
                for x in set(_items([c])):
                    out[-1].setdefault(x, []).append(c.name)
            continue
        for x in set(_items([c])):
            if c.name in ("private", "linear"):
                targets = [ks[-1]]
            elif c.name == "firstprivate" and len(ks) > 1:
                ws = any(ls[k] in _WORKSHARING for k in ks)
                targets = [k for k in ks if (
                    ls[k] == "distribute"
                    or (ls[k] == "teams" and "distribute" not in ls)
                    or ls[k] in _WORKSHARING or ls[k] == "taskloop"
                    or (ls[k] == "parallel" and not ws
                        and "taskloop" not in ls)
                    or (ls[k] == "target" and x not in lastp
                        and _base(x) not in mapped))]
            elif c.name == "reduction":
                targets = [k for k in ks if not (
                    (ls[k] == "parallel" and set(ls) & {
                        "sections", "do", "for", "loop", "taskloop"})
                    or (ls[k] == "teams" and "loop" in ls))]
            else:
                targets = ks
            for k in targets:
                out[k].setdefault(x, []).append(c.name)
    return out


@predicate
def dsa_list_item_once(tree, version):
    """After splitting the explicit data-sharing clauses of a directive onto
    its leaf constructs (see _dsa_split: private, firstprivate, lastprivate,
    shared, linear, reduction, in_reduction, is_device_ptr, use_device_ptr,
    has_device_addr, use_device_addr), a list item (same text) in two
    clauses on one leaf, other than exactly one firstprivate and one
    lastprivate. Implicit clauses created by the split are not counted."""
    def bad(i):
        return any(len(v) > 1 and sorted(v) != ["firstprivate", "lastprivate"]
                   for leaf in _dsa_split(tree, i, version)
                   for v in leaf.values())
    return _each(tree, bad)


@predicate
def list_item_not_part_of_variable(tree, version):
    """An array element, array section or structure component (a list item
    with "(" or "%") in a variable list: declare target's extended list and
    its to/enter/link/local clauses, and private, firstprivate,
    lastprivate, shared."""
    def bad(i):
        d = tree.directives[i]
        xs = _items(_clauses(tree, i, "private", "firstprivate",
                             "lastprivate", "shared"))
        if d.name == "declare target":
            xs += [_norm(a) for a in d.args]
            xs += _items(_clauses(tree, i, "to", "enter", "link", "local"))
        return any(_is_part(x) for x in xs)
    return _each(tree, bad)


@predicate
def use_device_no_structure_element(tree, version):
    """A structure component (a list item with "%") in use_device_ptr or
    use_device_addr (5.2)."""
    return _each(tree, lambda i: any(_is_component(x) for x in _items(
        _clauses(tree, i, "use_device_ptr", "use_device_addr"))))


@predicate
def use_device_addr_section_base(tree, version):
    """An array section in use_device_addr whose array base is not a name
    (6.0), e.g. s%a(1:n)."""
    return _each(tree, lambda i: any(
        _section_base(x) is not None
        and not re.fullmatch(r"[a-z_]\w*", _section_base(x))
        for x in _items(_clauses(tree, i, "use_device_addr"))))


@predicate
def device_ancestor_only_on_target(tree, version):
    """device(ancestor: ...) on a directive without a target leaf."""
    return _each(tree, lambda i: _has_ancestor_device(tree, i)
                 and "target" not in _leaves(tree, i))


@predicate
def device_ancestor_is_one(tree, version):
    """device(ancestor: n) with an integer literal n other than 1."""
    return _each(tree, lambda i: any(
        "ancestor" in c.modifiers and _int(c.args[-1]) not in (None, 1)
        for c in _clauses(tree, i, "device")))


@predicate
def device_ancestor_needs_reverse_offload(tree, version):
    """device(ancestor: ...) in a source without a requires directive that
    has the reverse_offload clause (anywhere in the source: a requires in a
    module that the program unit references also counts)."""
    if any(d.name == "requires" and _clauses(tree, i, "reverse_offload")
           for i, d in enumerate(tree.directives)):
        return []
    return _each(tree, lambda i: _has_ancestor_device(tree, i))


@predicate
def target_ancestor_limits(tree, version):
    """A construct with a target leaf and device(ancestor: ...) that has a
    clause other than device, firstprivate, private, defaultmap, map (6.0:
    nowait), a leaf other than target, or a nested directive."""
    ok = {"device", "firstprivate", "private", "defaultmap", "map"} | (
        {"nowait"} if version >= 60 else set())

    def bad(i):
        if "target" not in _leaves(tree, i) or not _has_ancestor_device(
                tree, i):
            return False
        return (any(c.name not in ok for c in _clauses(tree, i, end=True))
                or len(_leaves(tree, i)) > 1 or bool(tree.children(i))
                # Calls to runtime routines in the region
                or any(_api_calls(st) for _, st in _body(tree, i)))
    return _each(tree, bad)


# --- predicates: declare target ----------------------------------------------

@predicate
def declare_target_extended_list_alone(tree, version):
    """declare target with both an extended-list argument and clauses."""
    return _each(tree, lambda i: tree.directives[i].name == "declare target"
                 and bool(tree.directives[i].args)
                 and bool(tree.directives[i].clauses))


@predicate
def declare_target_enter_or_link(tree, version):
    """declare target with clauses but no enter, to (its 5.2 synonym) or
    link clause."""
    return _each(tree, lambda i: tree.directives[i].name == "declare target"
                 and bool(tree.directives[i].clauses)
                 and not _clauses(tree, i, "enter", "to", "link"))


@predicate
def declare_target_nohost_link(tree, version):
    """declare target with device_type(nohost) and a link clause."""
    return _each(tree, lambda i: tree.directives[i].name == "declare target"
                 and "nohost" in _items(_clauses(tree, i, "device_type"))
                 and bool(_clauses(tree, i, "link")))


# --- default(none) ---------------------------------------------------------

# Clauses that give a list item an explicitly determined data-sharing
# attribute (5.2 §5.4, 6.0 §7.5).
_EXPLICIT_DSA = ("private", "firstprivate", "lastprivate", "shared", "linear",
                 "induction",
                 "reduction", "in_reduction", "is_device_ptr",
                 "has_device_addr", "use_device_ptr", "use_device_addr")
_DO_VAR = re.compile(r"^(?:[a-z_]\w*\s*:\s*)?do\s+(?:\d+\s*,?\s*)?"
                     r"([a-z_]\w*)\s*=")


@predicate
def default_none_listed(tree, version):
    """A construct with default(none) whose structured block or loop nest
    references, in a base-language statement, a variable declared in the
    source (seen from the directive, ProgramTree.attribute: not a named
    constant, not supplied by a USE) that is listed in no data-sharing
    attribute clause of the directive and has no predetermined attribute
    the scanner can see: DO variables of loops in the construct are
    predetermined private, threadprivate variables are predetermined (5.2
    §5.1.1, 6.0 §7.1.1). References in nested
    directives' clauses are not counted (lenient), nor names a USE may
    supply."""
    if getattr(tree, "lang", "f90") == "c":
        return _c_default_none(tree, version)
    out = []
    # threadprivate variables are predetermined (5.2 §5.1.1, 6.0 §7.1.1)
    tprivate = {_base(_norm(x)) for d in tree.directives
                if d.name == "threadprivate" for x in d.args}
    for i, d in enumerate(tree.directives):
        cl = [c for c in d.clauses if c.name == "default"]
        if not cl or not any(_norm(a).startswith("none")
                             for c in cl for a in c.args):
            continue
        a = tree.assoc[i]
        if a.kind not in ("block", "loop") or a.end_line is None:
            continue
        listed = {_base(x) for x in _items(_clauses(tree, i,
                                                    *_EXPLICIT_DSA))}
        body = [(ln, st) for ln, st, _ in tree.statements
                if a.line < ln < a.end_line
                or (a.kind == "loop" and ln == a.end_line)]
        dovars = {m.group(1) for _, st in body
                  if (m := _DO_VAR.match(st))}
        if version == 50 and "teams" in leaves(d.name) and not \
                {"parallel", "task", "taskloop"} & set(leaves(d.name)):
            # 5.0 §2.19.1.1 p.271: a sequential loop's variable is private
            # only in a parallel or task generating construct (5.2 adds
            # teams), so in a teams region only the DO variables of loops
            # in a nested parallel or task construct, or of loops a loop
            # directive is associated with, are predetermined
            dovars = set(a.loop_vars or ()) if a.kind == "loop" else set()
            for j in tree.descendants(i):
                b = tree.assoc[j]
                if b.kind == "loop":
                    dovars |= set(b.loop_vars or ())
                if {"parallel", "task", "taskloop"} & set(_leaves(tree, j)) \
                        and b.end_line is not None:
                    dovars |= {m.group(1) for ln, st, _ in tree.statements
                               if b.line < ln < b.end_line
                               and (m := _DO_VAR.match(st))}
        for _, st in body:
            names = set(re.findall(r"(?<![%\w])([a-z_]\w*)",
                                   _STRING.sub("", st)))
            hit = [x for x in names - listed - dovars - tprivate
                   if tree.attribute(i, x) is not None
                   and not any((sid, x) in tree.params
                               for sid in a.scope)]
            if hit:
                out.append(i)
                break
    return out


def _c_names(st: str) -> set:
    """Identifiers of a C statement (not member names after . or ->)."""
    st = _STRING.sub("", st)
    return set(re.findall(r"(?<![\w.>])([a-z_]\w*)", st)) - {
        "for", "if", "while", "do", "int", "bool", "double", "return",
        "struct", "const", "static", "sizeof", "true", "false", "else",
        "switch", "case", "break", "continue", "void", "char", "long",
        "short", "unsigned", "signed", "float"}


def _c_outside(tree, i, scopes, name) -> bool:
    """Whether `name`, referenced in a statement with scope chain
    `scopes` inside construct i, is declared (visibly) outside the
    construct: its declaring scope, seen from the statement, is on the
    directive's own scope chain. A name declared inside the construct
    (a block or for-loop scope of its own) is private (5.2 §5.1.1: variables
    with automatic storage duration declared in a scope inside the
    construct)."""
    hit = tree._find(scopes, name, tree.decls)
    if hit is None:
        return False
    return hit[0][-1] in tree.assoc[i].scope


def _c_construct_refs(tree, i) -> set:
    """(name) of the variables declared outside construct i that its
    statements reference (C); the iteration variables of the
    loops the construct is associated with are not counted (predetermined
    private, 5.2 §5.1.1)."""
    a = tree.assoc[i]
    if a.kind not in ("block", "loop") or a.end_line is None:
        return set()
    loopv = set(a.loop_vars or ())
    out = set()
    for ln, st, scopes in tree.statements:
        if not (a.line < ln <= a.end_line):
            continue
        for x in _c_names(st):
            if x in loopv or not _c_outside(tree, i, scopes, x):
                continue
            if any((s, x) in tree.params for s in scopes):
                continue
            key = tree._find(scopes, x, tree.decls)
            # a function name is not a variable
            if key is not None and tree.units and any(
                    n == x for _, n in tree.units.values()) and \
                    key[0][-1] == 0:
                continue
            out.add(x)
    return out


def _c_default_none(tree, version):
    """default(none) in C: a variable declared outside the
    construct that its statements reference, not listed in a data-sharing
    attribute clause, not a loop iteration variable of the construct, not
    threadprivate, not a named (enumeration) constant."""
    out = []
    tprivate = {_base(_norm(x)) for d in tree.directives
                if d.name == "threadprivate" for x in d.args}
    for i, d in enumerate(tree.directives):
        cl = [c for c in d.clauses if c.name == "default"]
        if not cl or not any(_norm(a).startswith("none")
                             for c in cl for a in c.args):
            continue
        listed = {_base(x) for x in _items(_clauses(tree, i,
                                                    *_EXPLICIT_DSA))}
        if _c_construct_refs(tree, i) - listed - tprivate:
            out.append(i)
    return out


# =============================================================================
# The remaining static restrictions
# =============================================================================

def _decl_scope(tree: ProgramTree, i: int, name: str):
    """The scoping unit that declares `name` as seen from directive i, or
    None (not declared, or a USE may supply it)."""
    hit = tree._find(tree.assoc[i].scope, name, tree.decls)
    return None if hit is None else hit[0][-1]


def _vtype(tree: ProgramTree, i: int, name: str) -> str | None:
    s = _decl_scope(tree, i, name)
    return None if s is None else tree.vtypes.get((s, name))


def _is_array(tree: ProgramTree, i: int, name: str) -> bool | None:
    s = _decl_scope(tree, i, name)
    return None if s is None else (s, name) in tree.arrays


def _outer_leaf_slots(tree: ProgramTree, i: int):
    """(directive index, leaf position, leaf) of the enclosing constructs,
    innermost first."""
    for p in _ancestors(tree, i):
        ls = _leaves(tree, p)
        for k in range(len(ls) - 1, -1, -1):
            yield p, k, ls[k]


def _on_leaf(tree, i, k, version, names) -> set:
    """List items of directive i that the clause split puts on its leaf k
    in one of the clauses `names`."""
    split = _dsa_split(tree, i, version)
    return {x for x, cs in split[k].items() if set(cs) & set(names)} \
        if k < len(split) - 1 else set()


_PRIVATIZING = ("private", "firstprivate", "lastprivate", "linear")
_WS_LEAVES = {"do", "for", "sections", "single", "workshare", "scope"}


def _ws_leaf(tree, i, leaf) -> bool:
    """A worksharing leaf (5.2 §11: do, for, sections, single, workshare,
    scope; loop only with bind(parallel), when its binding region is the
    parallel region)."""
    return leaf in _WS_LEAVES or (
        leaf == "loop" and "parallel" in _items(_clauses(tree, i, "bind")))


# --- nesting of regions --------------------------------------------------------

@predicate
def worksharing_closely_nested(tree, version):
    """A construct whose outermost leaf is a worksharing construct and whose
    closest enclosing construct, up to the nearest parallel, teams or target
    leaf, is a worksharing, task, taskloop, critical, ordered, atomic or
    masked construct (taskgroup and other constructs are passed through)."""
    bad_outer = {"task", "taskloop", "critical", "ordered (Block)", "atomic",
                 "masked", "master"} | ({"loop"} if version == 50 else set())

    def bad(i):
        if not _ws_leaf(tree, i, _leaves(tree, i)[0]):
            return False
        for p, leaf in _outer_leaves(tree, i):
            if leaf in ("parallel", "teams", "target"):
                return False
            if leaf in bad_outer or _ws_leaf(tree, p, leaf):
                return True
        return False
    return _each(tree, bad)


def _simdizable(tree, c, version) -> bool:
    name = tree.directives[c].name
    if not _is_construct(tree, c) or name in ("simd", "atomic"):
        return True
    if version >= 60 and name in _LOOP_TRANSFORMS:
        return True
    if name == "loop":  # SIMDizable iff its binding region is not defined
        return not set(_items(_clauses(tree, c, "bind"))) & {"teams",
                                                              "parallel"}
    if name == "ordered (Block)":
        return bool(_clauses(tree, c, "simd"))
    return False


@predicate
def simd_simdizable_only(tree, version):
    """A construct lexically inside a construct with a simd leaf that is not
    SIMDizable: simd, atomic, loop without bind(teams/parallel), ordered
    with the simd clause (6.0: and loop-transforming constructs)."""
    return sorted({c for i in range(len(tree.directives))
                   if "simd" in _leaves(tree, i)
                   for c in tree.descendants(i)
                   if not _simdizable(tree, c, version)})


@predicate
def order_concurrent_no_api_calls(tree, version):
    """A construct with order(concurrent) (a loop leaf without an order
    clause counts) whose lexical extent calls an OpenMP runtime routine
    (5.2: none may be called; 6.0: only order-concurrent-nestable routines,
    and no routine has that property)."""
    return _each(tree, lambda i: _order_concurrent(tree, i) and any(
        _api_calls(st) for _, st in _body(tree, i)))


def _ordered_parent(tree, i):
    for p in _ancestors(tree, i):
        if tree.directives[p].name != "taskgroup":
            return p
    return None


def _block_ordered(tree, i, simd: bool) -> bool:
    return tree.directives[i].name == "ordered (Block)" and (
        bool(_clauses(tree, i, "simd")) == simd)


@predicate
def ordered_threads_in_worksharing_loop(tree, version):
    """A block-associated ordered construct without the simd clause whose
    closest enclosing construct (taskgroup passed through) has no do leaf.
    An orphaned ordered construct is not flagged."""
    def bad(i):
        p = _ordered_parent(tree, i) if _block_ordered(tree, i, False) \
            else None
        return p is not None and not set(_leaves(tree, p)) & {"do", "for"}
    return _each(tree, bad)


@predicate
def ordered_simd_in_simd(tree, version):
    """A block-associated ordered construct with the simd clause whose
    closest enclosing construct has no simd leaf (orphans not flagged)."""
    def bad(i):
        p = tree.parent(i) if _block_ordered(tree, i, True) else None
        return p is not None and "simd" not in _leaves(tree, p)
    return _each(tree, bad)


@predicate
def ordered_binding_has_ordered_clause(tree, version):
    """A block-associated ordered construct without the simd clause closely
    nested in a construct with a do leaf that has no ordered clause, or an
    ordered(n) whose literal n is not 1 (5.2) / not the collapse value
    (6.0)."""
    def bad(i):
        p = _ordered_parent(tree, i) if _block_ordered(tree, i, False) \
            else None
        if p is None or not set(_leaves(tree, p)) & {"do", "for"}:
            return False
        cl = _clauses(tree, p, "ordered")
        if not cl:
            return True
        n = _int(cl[0].args[0]) if cl[0].args else None
        want = 1 if version < 60 else _collapse(tree, p)
        return n is not None and want is not None and n != want
    return _each(tree, bad)


@predicate
def workdistribute_in_teams(tree, version):
    """A workdistribute constituent whose immediately enclosing construct is
    not a teams construct (orphaned: flagged, the restriction names the
    construct)."""
    return _each(tree, lambda i: "workdistribute" in _leaves(tree, i)
                 and _enclosing_leaf(tree, i, "workdistribute") != "teams")


@predicate
def workdistribute_no_nested_region(tree, version):
    """A construct lexically inside a workdistribute construct."""
    return sorted({c for i in range(len(tree.directives))
                   if "workdistribute" in _leaves(tree, i)
                   for c in tree.descendants(i) if _is_construct(tree, c)})


_ASSIGNMENT = re.compile(r"^[a-z_]\w*\s*(?:\([^=]*\))?(?:\s*%\s*[a-z_]\w*\s*"
                         r"(?:\([^=]*\))?)*\s*=(?!=)")


@predicate
def workdistribute_statements(tree, version):
    """A base-language statement in a workdistribute construct that is not
    an assignment or a CALL (BLOCK / END BLOCK delimiters aside); whether a
    called procedure is pure and elemental is not checked."""
    def bad(i):
        return "workdistribute" in _leaves(tree, i) and any(
            not (_ASSIGNMENT.match(st) or re.match(r"^call\b", st)
                 or _BLOCK.match(st) or _END_BLOCK.match(st))
            for _, st in _body(tree, i))
    return _each(tree, bad)


# --- compound constructs and clause values --------------------------------------

def _assoc_vars(tree, i) -> tuple | None:
    """Iteration variables of the loops associated with loop directive i,
    or None when unknown."""
    a = tree.assoc[i]
    n = _assoc_count(tree, i)
    if a.kind != "loop" or not a.loop_depth or n is None:
        return None
    if n > a.loop_depth and a.depth_known:
        return None  # collapse-loop-001 reports it
    return a.loop_vars[:n] if n <= a.loop_depth else None


@predicate
def distribute_linear_loop_vars(tree, version):
    """A compound with a distribute leaf and a linear list item that is not
    the iteration variable of an associated loop."""
    def bad(i):
        ls = _leaves(tree, i)
        vs = _assoc_vars(tree, i)
        return "distribute" in ls and len(ls) > 1 and vs is not None and any(
            _base(x) not in vs for x in _items(_clauses(tree, i, "linear")))
    return _each(tree, bad)


@predicate
def schedule_runtime_auto_no_chunk(tree, version):
    """schedule(runtime, chunk) or schedule(auto, chunk)."""
    return _each(tree, lambda i: any(
        c.args and _norm(c.args[0]) in ("runtime", "auto") and len(c.args) > 1
        for c in _clauses(tree, i, "schedule")))


@predicate
def schedule_nonmonotonic_no_ordered(tree, version):
    """schedule with the nonmonotonic modifier and an ordered clause on the
    same directive."""
    return _each(tree, lambda i: any(
        "nonmonotonic" in c.modifiers for c in _clauses(tree, i, "schedule"))
        and bool(_clauses(tree, i, "ordered")))


def _lit(tree, i, name) -> int | None:
    cs = _clauses(tree, i, name)
    return _int(cs[0].args[0]) if cs and cs[0].args else None


@predicate
def simdlen_le_safelen(tree, version):
    """simdlen and safelen with integer literals, simdlen > safelen."""
    def bad(i):
        a, b = _lit(tree, i, "simdlen"), _lit(tree, i, "safelen")
        return a is not None and b is not None and a > b
    return _each(tree, bad)


@predicate
def simd_order_concurrent_no_safelen(tree, version):
    """A directive with a simd leaf, order(concurrent) and safelen."""
    return _each(tree, lambda i: "simd" in _leaves(tree, i)
                 and "concurrent" in _items(_clauses(tree, i, "order"))
                 and bool(_clauses(tree, i, "safelen")))


@predicate
def positive_arguments(tree, version):
    """An integer literal less than one as an argument with the positive
    property: num_threads, safelen, simdlen, the schedule chunk_size, the
    ordered parameter, the aligned alignment (thread_limit, num_teams and
    dist_schedule have their own rules)."""
    def values(i):
        out = []
        for c in _clauses(tree, i, "num_threads", "safelen", "simdlen",
                          "ordered"):
            out += c.args if c.name == "num_threads" else c.args[:1]
        for c in _clauses(tree, i, "schedule"):
            out += c.args[1:2]
        for c in _clauses(tree, i, "aligned"):
            out += [m for m in c.modifiers if _compact(m) not in _names()]
        return out
    return _each(tree, lambda i: _not_positive(values(i)))


@predicate
def constant_arguments(tree, version):
    """safelen, simdlen or ordered(n) whose argument is a variable declared
    in the source (not a named constant)."""
    def bad(i):
        for c in _clauses(tree, i, "safelen", "simdlen", "ordered"):
            x = _norm(c.args[0]) if c.args else ""
            if re.fullmatch(r"[a-z_]\w*", x) \
                    and tree.attribute(i, x) is not None \
                    and not any((s, x) in tree.params
                                for s in tree.assoc[i].scope):
                return True
        return False
    return _each(tree, bad)


# clause sets (5.2 §3.2, 6.0 §5.2) the skeleton does not enforce
_REQUIRED_SETS = {
    52: {"target update": {"to", "from"}, "scan": {"inclusive", "exclusive"},
         "depobj": {"depend", "destroy", "update"}},
    60: {"target update": {"to", "from"},
         "scan": {"inclusive", "exclusive", "init_complete"},
         "depobj": {"destroy", "init", "update", "depend"}},
}
_EXCLUSIVE_SETS = {
    52: {"scan": [{"inclusive", "exclusive"}],
         "depobj": [{"depend", "destroy", "update"}],
         "task": [{"detach", "mergeable"}],
         "taskloop": [{"nogroup", "reduction"}, {"grainsize", "num_tasks"}]},
    60: {"scan": [{"inclusive", "exclusive", "init_complete"}],
         "single": [{"copyprivate", "nowait"}],
         "task": [{"detach", "mergeable"}],
         "taskloop": [{"nogroup", "reduction"}, {"grainsize", "num_tasks"}]},
}


@predicate
def clause_set_required(tree, version):
    """target update without to/from, scan without inclusive/exclusive,
    depobj without depend/destroy/update (6.0: init/destroy/update)."""
    sets = _REQUIRED_SETS[52 if version < 60 else 60]
    return _each(tree, lambda i: tree.directives[i].name in sets and not (
        {c.name for c in _clauses(tree, i, end=True)}
        & sets[tree.directives[i].name]))


@predicate
def clause_set_exclusive(tree, version):
    """Two clauses with different names from one exclusive clause set on a
    directive (scan, depobj (5.2), single (6.0), task, taskloop)."""
    sets = _EXCLUSIVE_SETS[52 if version < 60 else 60]
    return _each(tree, lambda i: any(
        len({c.name for c in _clauses(tree, i, end=True)} & s) > 1
        for s in sets.get(tree.directives[i].name, ())))


@predicate
def single_copyprivate_nowait(tree, version):
    """single with copyprivate and nowait (on the directive or its end
    directive)."""
    return _each(tree, lambda i: tree.directives[i].name == "single"
                 and bool(_clauses(tree, i, "copyprivate", end=True))
                 and bool(_clauses(tree, i, "nowait", end=True)))


_UNIQUE_LISTS = set(_DSA) | {"to", "from", "enter", "link", "local",
                             "aligned", "nontemporal", "copyin",
                             "copyprivate", "allocate", "inclusive",
                             "exclusive"}


@predicate
def list_item_directive_wide_unique(tree, version):
    """A list item twice in one clause, in two clauses of the same name
    (not data-sharing clauses, which datasharing-dsa-001 checks after the
    split; not map or depend, where the spec allows repeats), in both to
    and from, or in two of enter, link and local, of one directive."""
    def bad(i):
        cs = [c for c in _clauses(tree, i, end=True)
              if c.name in _UNIQUE_LISTS]
        if tree.directives[i].name == "declare target" \
                and len(set(map(_norm, tree.directives[i].args))) \
                < len(tree.directives[i].args):
            return True
        by = {}
        for c in cs:
            xs = _items([c])
            if len(xs) != len(set(xs)):
                return True
            by.setdefault(c.name, []).extend(set(xs))
        if any(len(xs) != len(set(xs)) for n, xs in by.items()
               if n not in _DSA):
            return True
        pairs = [("to", "from"), ("enter", "link"), ("enter", "local"),
                 ("link", "local"), ("to", "link"), ("to", "local")]
        return any(set(by.get(a, ())) & set(by.get(b, ())) for a, b in pairs)
    return _each(tree, bad)


@predicate
def linear_inscan_loop_vars(tree, version):
    """reduction(inscan, ...) and a linear list item that is not the
    iteration variable of an associated loop, on one directive."""
    def bad(i):
        vs = _assoc_vars(tree, i)
        return bool(_reductions(tree, i, "inscan")) and vs is not None and any(
            _base(x) not in vs for x in _items(_clauses(tree, i, "linear")))
    return _each(tree, bad)


def _linear_ref_uval(c) -> bool:
    return any(re.match(r"^(?:ref|uval)\s*\(", _norm(a)) for a in c.args) \
        or bool({"ref", "uval"} & set(map(_norm, c.modifiers)))


@predicate
def linear_ref_uval_declare_simd(tree, version):
    """A linear clause with the ref or uval modifier on a directive other
    than declare simd (5.0: any modifier, val included, 5.0 §2.9.2 p.107,
    §2.9.3.1 p.113)."""
    def has_mod(c):
        if version == 50:
            return bool({"ref", "uval", "val"} & set(map(_norm, c.modifiers)))
        return _linear_ref_uval(c)
    return _each(tree, lambda i: tree.directives[i].name != "declare simd"
                 and any(has_mod(c) for c in _clauses(tree, i, "linear")))


def _linear_names(c) -> list[str]:
    return [_base(re.sub(r"^(?:ref|uval|val)\((.*)\)$", r"\1", _norm(a)))
            for a in c.args]


@predicate
def linear_not_pointer(tree, version):
    """A linear list item declared with the POINTER attribute."""
    return _each(tree, lambda i: any(
        tree.attribute(i, x) == "pointer"
        for c in _clauses(tree, i, "linear") for x in _linear_names(c)))


@predicate
def linear_integer(tree, version):
    """A linear list item (without ref) declared with an intrinsic type
    other than integer, or a derived type."""
    return _each(tree, lambda i: any(
        _vtype(tree, i, x) not in (None, "integer")
        for c in _clauses(tree, i, "linear") if not _linear_ref_uval(c)
        for x in _linear_names(c)))


@predicate
def loop_var_predetermined_dsa(tree, version):
    """After the clause split, the iteration variable of an associated loop
    in a data-sharing clause on a loop leaf (do, simd, distribute, loop,
    taskloop) other than private or lastprivate (or linear on a simd leaf
    with one associated loop)."""
    loop_leaves = {"do", "for", "simd", "distribute", "loop", "taskloop"}

    def bad(i):
        vs = _assoc_vars(tree, i)
        if not vs:
            return False
        ls = _rule_leaves(tree.directives[i].name, version)
        split = _dsa_split(tree, i, version)
        for k, leaf in enumerate(ls):
            if leaf not in loop_leaves:
                continue
            for x, names in split[k].items():
                if x not in vs:
                    continue
                for nm in names:
                    if nm in ("private", "lastprivate") or (
                            nm == "linear" and leaf == "simd"
                            and len(vs) == 1):
                        continue
                    return True
        return False
    return _each(tree, bad)


# --- data-sharing across nested constructs ---------------------------------------

def _binding(tree, i, kinds, stop) -> tuple | None:
    """(directive, leaf position, leaf) of the closest enclosing leaf in
    `kinds`, if no leaf in `stop` comes first."""
    for p, k, leaf in _outer_leaf_slots(tree, i):
        if leaf in kinds:
            return p, k, leaf
        if leaf in stop:
            return None
    return None


_GENERATING = {"parallel", "teams", "target", "task", "taskloop"}


def _items_on(tree, i, version, leaf, names) -> set:
    ls = _rule_leaves(tree.directives[i].name, version)
    return {_base(x) for k, lf in enumerate(ls) if lf == leaf
            for x in _on_leaf(tree, i, k, version, names)}


def _private_in(tree, p, k, version, names=_PRIVATIZING) -> set:
    return {_base(x) for x in _on_leaf(tree, p, k, version, names)}


def _nested_dsa_rule(inner_leaves, inner_clauses, outer, outer_clauses,
                     doc):
    """A predicate: an item in `inner_clauses` on an inner leaf in
    `inner_leaves` (worksharing leaves for "ws") that is in `outer_clauses`
    on the closest enclosing `outer` leaf (no other generating leaf
    between)."""
    def fn(tree, version):
        def bad(i):
            ls = _rule_leaves(tree.directives[i].name, version)
            if ls[0] not in inner_leaves and not (
                    "ws" in inner_leaves and _ws_leaf(tree, i, ls[0])):
                return False
            items = _items_on(tree, i, version, ls[0], inner_clauses)
            if not items:
                return False
            hit = _binding(tree, i, {outer}, _GENERATING - {outer})
            if hit is None:
                return False
            p, k, _ = hit
            return bool(items & _private_in(tree, p, k, version,
                                            outer_clauses))
        return _each(tree, bad)
    fn.__doc__ = doc
    return fn


def _register(name, fn):
    fn.__name__ = name
    return predicate(fn)


_register("firstprivate_private_in_parallel", _nested_dsa_rule(
    {"ws"}, ("firstprivate",), "parallel", _PRIVATIZING,
    """firstprivate on a worksharing construct of an item that is private
    (private, firstprivate, lastprivate, linear) on the closest enclosing
    parallel leaf."""))
_register("firstprivate_private_in_teams", _nested_dsa_rule(
    {"distribute"}, ("firstprivate",), "teams", _PRIVATIZING,
    """firstprivate on a distribute construct of an item that is private on
    the closest enclosing teams leaf."""))
_register("firstprivate_reduction_in_parallel_ws", _nested_dsa_rule(
    {"ws", "task", "taskloop"}, ("firstprivate",), "parallel",
    ("reduction",),
    """firstprivate on a worksharing, task or taskloop construct of an item
    in a reduction clause of the closest enclosing parallel leaf (5.2)."""))
_register("firstprivate_reduction_in_parallel_task", _nested_dsa_rule(
    {"task", "taskloop"}, ("firstprivate",), "parallel", ("reduction",),
    """firstprivate on a task or taskloop construct of an item in a
    reduction clause of the closest enclosing parallel leaf (6.0)."""))
_register("firstprivate_reduction_in_teams", _nested_dsa_rule(
    {"distribute"}, ("firstprivate",), "teams", ("reduction",),
    """firstprivate on a distribute construct of an item in a reduction
    clause of the closest enclosing teams leaf (5.2)."""))
_register("reduction_shared_in_parallel", _nested_dsa_rule(
    {"ws"}, ("reduction",), "parallel", _PRIVATIZING + ("reduction",),
    """reduction on a worksharing construct of an item that is private
    (private, firstprivate, lastprivate, linear, reduction) on the closest
    enclosing parallel leaf."""))
_register("reduction_shared_in_teams", _nested_dsa_rule(
    {"distribute", "loop"}, ("reduction",), "teams",
    _PRIVATIZING + ("reduction",),
    """reduction on a distribute or loop construct of an item that is
    private on the closest enclosing teams leaf (6.0)."""))


@predicate
def lastprivate_private_in_binding(tree, version):
    """lastprivate on a work-distribution leaf (worksharing leaves,
    distribute, loop) of an item that is private on the closest enclosing
    parallel (distribute: teams) leaf."""
    def bad(i):
        ls = _rule_leaves(tree.directives[i].name, version)
        first = ls[0]
        if first == "distribute":
            outer = "teams"
        elif _ws_leaf(tree, i, first) or first == "loop":
            outer = "parallel"
        else:
            return False
        items = _items_on(tree, i, version, first, ("lastprivate",))
        hit = _binding(tree, i, {outer}, _GENERATING - {outer}) \
            if items else None
        return hit is not None and bool(
            items & _private_in(tree, hit[0], hit[1], version))
    return _each(tree, bad)


@predicate
def lastprivate_conditional_scalar(tree, version):
    """lastprivate(conditional: x) with x declared as an array."""
    return _each(tree, lambda i: any(
        _is_array(tree, i, _base(x))
        for c in _clauses(tree, i, "lastprivate")
        if "conditional" in c.modifiers for x in _items([c])))


def _tp_keys(tree) -> set:
    """(declaring scope, name) of threadprivate variables."""
    out = set()
    for j, d in enumerate(tree.directives):
        if d.name == "threadprivate":
            for x in d.args:
                x = _norm(x)
                if not x.startswith("/"):
                    s = _decl_scope(tree, j, x)
                    out.add((s if s is not None else
                             tree.assoc[j].scope[-1], x))
    return out


def _key(tree, i, x) -> tuple:
    s = _decl_scope(tree, i, x)
    return (s if s is not None else tree.assoc[i].scope[-1], x)


@predicate
def copyin_threadprivate(tree, version):
    """A copyin list item (not a common block) declared in the source,
    visible from the directive, that no threadprivate directive names."""
    def bad(i):
        tp = _tp_keys(tree)
        return any(not x.startswith("/") and tree.attribute(i, x) is not None
                   and _key(tree, i, x) not in tp
                   for x in map(_base, _items(_clauses(tree, i, "copyin"))))
    return _each(tree, bad)


@predicate
def threadprivate_only_copyin(tree, version):
    """A threadprivate variable as the base of a list item of a clause
    other than copyin and copyprivate."""
    def bad(i):
        tp = _tp_keys(tree)
        return tree.directives[i].name != "threadprivate" and any(
            _key(tree, i, _base(x)) in tp
            for c in _clauses(tree, i, end=True)
            if c.name not in ("copyin", "copyprivate")
            and c.name in _UNIQUE_LISTS | {"map", "depend"}
            for x in _items([c]))
    return _each(tree, bad)


@predicate
def threadprivate_in_specification_part(tree, version):
    """A threadprivate directive lexically inside a construct (an execution
    part)."""
    return _each(tree, lambda i: tree.directives[i].name == "threadprivate"
                 and tree.parent(i) is not None)


def _foreign_scope(tree, i, x) -> bool:
    """x is declared visibly from directive i, in another scoping unit."""
    s = _decl_scope(tree, i, _norm(x))
    return s is not None and s != tree.assoc[i].scope[-1]


@predicate
def threadprivate_declaring_scope(tree, version):
    """A threadprivate variable declared (visibly) in another scoping unit
    than the directive's."""
    return _each(tree, lambda i: tree.directives[i].name == "threadprivate"
                 and any(_foreign_scope(tree, i, x) for x in
                         tree.directives[i].args
                         if not _norm(x).startswith("/")))


def _not_saved(tree, i, x) -> bool:
    """x is declared in a subprogram (not a program, module or submodule)
    without SAVE (attribute, statement, bare SAVE, or initializer); a
    procedure of the source (a function's name is also its result
    variable's) is not a variable."""
    s = _decl_scope(tree, i, x)
    if s is None or s == 0 or any(n == x for _, n in tree.units.values()):
        return False
    if getattr(tree, "lang", "f90") == "c":
        # C: static storage duration = file scope or static
        return (s, x) not in tree.saved
    kind = tree.units.get(s, ("", None))[0]
    if kind in ("program", "module", "submodule", "blockdata", ""):
        return False
    return (s, x) not in tree.saved and (s, "*") not in tree.saved


@predicate
def threadprivate_saved(tree, version):
    """A threadprivate variable declared in a subprogram without the SAVE
    attribute."""
    return _each(tree, lambda i: tree.directives[i].name == "threadprivate"
                 and any(_not_saved(tree, i, _norm(x))
                         for x in tree.directives[i].args
                         if not _norm(x).startswith("/")))


def _dt_items(tree, i, *names) -> list[str]:
    d = tree.directives[i]
    xs = _items(_clauses(tree, i, *names))
    if "enter" in names:
        xs += [_norm(a) for a in d.args]
    return [x for x in xs if not x.startswith("/")]


@predicate
def declare_target_enter_saved(tree, version):
    """A declare target variable (5.2: any list item; 6.0: in enter or
    the extended list) declared in a subprogram without SAVE."""
    names = ("enter", "to", "link", "local") if version < 60 else (
        "enter", "to")
    return _each(tree, lambda i: tree.directives[i].name == "declare target"
                 and any(_not_saved(tree, i, x)
                         for x in _dt_items(tree, i, *names)))


@predicate
def declare_target_link_saved(tree, version):
    """A link list item declared in a subprogram without SAVE (6.0)."""
    return _each(tree, lambda i: tree.directives[i].name == "declare target"
                 and any(_not_saved(tree, i, x)
                         for x in _dt_items(tree, i, "link")))


@predicate
def declare_target_declaring_scope(tree, version):
    """A declare target variable declared (visibly) in another scoping
    unit than the directive's."""
    return _each(tree, lambda i: tree.directives[i].name == "declare target"
                 and any(_foreign_scope(tree, i, x) for x in _dt_items(
                     tree, i, "enter", "to", "link", "local")))


@predicate
def declare_target_procedure_placement(tree, version):
    """A declare target without an extended list and without enter, to,
    link or local clauses (5.2: no clauses or only device_type/indirect;
    6.0: a declaration-associated directive; 5.0: no clauses at all, 5.0
    §2.12.7 p.184) in a program, module or submodule scoping unit."""
    def bad(i):
        d = tree.directives[i]
        if d.name != "declare target" or d.args or _clauses(
                tree, i, "enter", "to", "link", "local"):
            return False
        if version == 50 and d.clauses:
            return False
        kind = tree.units.get(tree.assoc[i].scope[-1], ("", None))[0]
        return kind in ("program", "module", "submodule", "blockdata")
    return _each(tree, bad)


def _cross_directive(tree, first: tuple, second: tuple) -> list[int]:
    """declare target directives naming an item in a clause of `second`
    that another declare target directive names in `first` (the extended
    list counts as enter)."""
    seen = {}
    for i, d in enumerate(tree.directives):
        if d.name != "declare target":
            continue
        for kind, names in (("a", first), ("b", second)):
            for x in _dt_items(tree, i, *names) if "enter" in names else [
                    x for x in _items(_clauses(tree, i, *names))]:
                seen.setdefault(_key(tree, i, _base(x)), []).append((kind, i))
    out = set()
    for hits in seen.values():
        a = {i for k, i in hits if k == "a"}
        b = {i for k, i in hits if k == "b"}
        if any(x != y for x in a for y in b):
            out.add(max(a | b))
    return sorted(out)


@predicate
def declare_target_enter_link(tree, version):
    """The same item in enter (or to, or the extended list) on one declare
    target directive and in link (6.0: or local) on another."""
    second = ("link",) if version < 60 else ("link", "local")
    return _cross_directive(tree, ("enter", "to"), second)


@predicate
def declare_target_link_local(tree, version):
    """The same item in link on one declare target directive and local on
    another (6.0)."""
    return _cross_directive(tree, ("link",), ("local",))


@predicate
def indirect_device_type_any(tree, version):
    """indirect (or indirect(.true.)) with device_type other than any."""
    def bad(i):
        ind = _clauses(tree, i, "indirect")
        on = ind and (not ind[0].args or _norm(ind[0].args[0]) == ".true.")
        return bool(on) and any(x != "any" for x in _items(
            _clauses(tree, i, "device_type")))
    return _each(tree, bad)


@predicate
def map_device_local(tree, version):
    """A map list item that a declare target local clause of the source
    names (a device-local variable, 6.0)."""
    def bad(i):
        local = {_key(tree, j, _base(x)) for j, d in enumerate(tree.directives)
                 if d.name == "declare target"
                 for x in _items(_clauses(tree, j, "local"))}
        return _map_construct(tree, i) and any(
            _key(tree, i, _base(x)) in local
            for x in _items(_clauses(tree, i, "map")))
    return _each(tree, bad)


@predicate
def target_map_structure_elements(tree, version):
    """On a construct with a target leaf that maps s%c (and not s), a
    statement in the construct referencing another component s%d that no
    map clause names."""
    def bad(i):
        if "target" not in _leaves(tree, i):
            return False
        # C structure elements s.c / p->c read as s%c
        maps = {re.sub(r"\([^()]*\)|\[[^\[\]]*\]", "",
                       x.replace("->", "%").replace(".", "%"))
                for x in _items(_clauses(tree, i, "map"))}
        out = False
        for x in maps:
            if "%" not in x:
                continue
            s = x.split("%")[0]
            if s in maps:
                continue
            for _, st in _body(tree, i):
                st = re.sub(r"->|\.(?=[a-z_])", "%", st)
                for comp in re.findall(rf"(?<![%\w]){s}\s*(?:\([^()]*\)|"
                                       r"\[[^\[\]]*\])?\s*"
                                       r"%\s*([a-z_]\w*)", st):
                    el = f"{s}%{comp}"
                    # mapped: the element itself or a part of it (s%c%d)
                    if not any(m == el or m.startswith(el + "%")
                               for m in maps):
                        out = True
        return out
    return _each(tree, bad)


@predicate
def defaultmap_none_listed(tree, version):
    """A construct with defaultmap(none) (or defaultmap(none: all)) whose
    lexical extent references a variable declared in the source that is
    not a named constant, not a DO variable of a loop in the construct,
    not threadprivate, not in a declare target enter/to/link clause and
    not listed in a data-environment attribute clause of the directive."""
    attr_clauses = _EXPLICIT_DSA + ("map",)
    dt = None
    out = []
    for i, d in enumerate(tree.directives):
        cl = [c for c in _clauses(tree, i, "defaultmap")
              if _items([c])[:1] == ["none"]
              and (not c.modifiers or _norm(c.modifiers[0]) == "all")]
        if not cl:
            continue
        if dt is None:
            dt = {_key(tree, j, _base(x)) for j, e in enumerate(
                tree.directives) if e.name == "declare target"
                for x in _dt_items(tree, j, "enter", "to", "link")}
            dt |= _tp_keys(tree)
        listed = {_base(x) for x in _items(_clauses(tree, i, *attr_clauses))}
        if getattr(tree, "lang", "f90") == "c":
            if any(_key(tree, i, x) not in dt
                   for x in _c_construct_refs(tree, i) - listed):
                out.append(i)
            continue
        body = _body(tree, i)
        dovars = {m.group(1) for _, st in body if (m := _DO_VAR.match(st))}
        for _, st in body:
            names = set(re.findall(r"(?<![%\w])([a-z_]\w*)",
                                   _STRING.sub("", st)))
            if any(tree.attribute(i, x) is not None
                   and not any((s, x) in tree.params
                               for s in tree.assoc[i].scope)
                   and _key(tree, i, x) not in dt
                   for x in names - listed - dovars):
                out.append(i)
                break
    return out


_ALLOC_PRIVATE = ("private", "firstprivate", "lastprivate", "linear",
                  "reduction", "in_reduction", "induction")


@predicate
def allocate_needs_private_clause(tree, version):
    """An allocate list item (not on allocators) that no private,
    firstprivate, lastprivate, linear, reduction, in_reduction or induction
    clause of the directive names."""
    def bad(i):
        if tree.directives[i].name == "allocators":
            return False
        priv = {_base(x) for x in _items(_clauses(tree, i, *_ALLOC_PRIVATE))}
        return any(_base(x) not in priv
                   for x in _items(_clauses(tree, i, "allocate")))
    return _each(tree, bad)


def _has_requires(tree, i, clause) -> bool:
    unit = tree.assoc[i].unit
    return any(d.name == "requires" and tree.assoc[j].unit == unit
               and _clauses(tree, j, clause)
               for j, d in enumerate(tree.directives))


@predicate
def allocate_target_allocator(tree, version):
    """An allocate clause without an allocator modifier on a construct with
    a target leaf or inside one, without requires dynamic_allocators in
    the program unit."""
    def bad(i):
        cs = [c for c in _clauses(tree, i, "allocate")
              if not [m for m in c.modifiers
                      if not re.match(r"^align\s*\(", _norm(m))]]
        in_target = "target" in _leaves(tree, i) or any(
            "target" in _leaves(tree, a) for a in _ancestors(tree, i))
        return bool(cs) and in_target and not _has_requires(
            tree, i, "dynamic_allocators")
    return _each(tree, bad)


_PREDEFINED_ALLOCATORS = {
    "omp_default_mem_alloc", "omp_large_cap_mem_alloc", "omp_const_mem_alloc",
    "omp_high_bw_mem_alloc", "omp_low_lat_mem_alloc", "omp_cgroup_mem_alloc",
    "omp_pteam_mem_alloc", "omp_thread_mem_alloc", "omp_null_allocator"}
_PREDEFINED_MEMSPACES = {
    "omp_default_mem_space", "omp_large_cap_mem_space",
    "omp_const_mem_space", "omp_high_bw_mem_space", "omp_low_lat_mem_space",
    "omp_null_mem_space"}


@predicate
def uses_allocators_not_in_other_clauses(tree, version):
    """A uses_allocators allocator that is also in a data-sharing or map
    clause of the directive."""
    def bad(i):
        al = {_base(x) for x in _items(_clauses(tree, i, "uses_allocators"))}
        return bool(al & {_base(x) for x in _items(
            _clauses(tree, i, *(_DSA + ("map",))))})
    return _each(tree, bad)


def _modifiers(c) -> list[str]:
    """The modifiers of a clause other than directive-name modifiers."""
    return [m for m in c.modifiers if _compact(_norm(m)) not in _names()]


@predicate
def uses_allocators_predefined_no_modifiers(tree, version):
    """uses_allocators of a predefined allocator with modifiers (a
    directive-name modifier aside)."""
    return _each(tree, lambda i: any(
        _modifiers(c) and set(_items([c])) & _PREDEFINED_ALLOCATORS
        for c in _clauses(tree, i, "uses_allocators")))


@predicate
def uses_allocators_predefined_memspace(tree, version):
    """A memspace(...) modifier whose argument is not a predefined memory
    space name."""
    def bad(i):
        for c in _clauses(tree, i, "uses_allocators"):
            for m in c.modifiers:
                mm = re.fullmatch(r"memspace\s*\((.*)\)", _norm(m))
                if mm and mm.group(1) not in _PREDEFINED_MEMSPACES:
                    return True
        return False
    return _each(tree, bad)


@predicate
def uses_allocators_traits_constant(tree, version):
    """A traits(t) modifier (5.0: an allocator(t) item) whose t is declared
    in the source as a variable that is not a named constant."""
    def bad(i):
        for c in _clauses(tree, i, "uses_allocators"):
            for m in c.modifiers:
                mm = re.fullmatch(r"traits\s*\(([a-z_]\w*)\)", _norm(m)) \
                    or (version == 50 and re.fullmatch(
                        r"[a-z_]\w*\(([a-z_]\w*)\)", _norm(m)))
                if mm and tree.attribute(i, mm.group(1)) is not None and \
                        not any((s, mm.group(1)) in tree.params
                                for s in tree.assoc[i].scope) and \
                        not _c_const(tree, i, mm.group(1)):
                    return True
        return False
    return _each(tree, bad)


def _c_const(tree, i, name) -> bool:
    """A C variable declared const (a constant array of the
    uses_allocators traits)."""
    s = _decl_scope(tree, i, name)
    return s is not None and "const" in tree.extra.get("ctypes", {}).get(
        (s, name), "").split()


_MEMORY_ORDER = ("seq_cst", "acq_rel", "release", "acquire", "relaxed")


@predicate
def requires_mem_order_before_atomic(tree, version):
    """requires atomic_default_mem_order after an atomic construct without
    a memory-order clause in the same program unit."""
    def bad(i):
        if tree.directives[i].name != "requires" or not _clauses(
                tree, i, "atomic_default_mem_order"):
            return False
        return any(tree.directives[j].name == "atomic"
                   and tree.assoc[j].unit == tree.assoc[i].unit
                   and not _clauses(tree, j, *_MEMORY_ORDER)
                   for j in range(i))
    return _each(tree, bad)


_DEVICE_GLOBAL = {52: ("reverse_offload", "unified_address",
                       "unified_shared_memory"),
                  60: ("reverse_offload", "unified_address",
                       "unified_shared_memory", "self_maps")}


@predicate
def requires_same_in_all_units(tree, version):
    """Program units of the source that contain declare target directives
    or device constructs whose device requirements differ (5.2: some
    specify reverse_offload, unified_address or unified_shared_memory,
    some none; 6.0: different sets, self_maps included). A unit inherits
    the requirements of the modules of the source it uses."""
    if getattr(tree, "lang", "f90") == "c":
        return []  # C: one source is one translation unit (5.2 §1.2.2)
    req_names = _DEVICE_GLOBAL[52 if version < 60 else 60]
    units, names, reqs, uses = {}, {}, {}, {}
    for ln, st, scopes in tree.statements:
        if len(scopes) > 1:
            units.setdefault(scopes[1], None)
    top_of = {}
    for _, _, scopes in tree.statements:
        for s in scopes[1:]:
            top_of[s] = scopes[1] if len(scopes) > 1 else None
    for s, (kind, name) in tree.units.items():
        if top_of.get(s) == s and kind == "module":
            names[name] = s
    for s, mods in tree.use_modules.items():
        if top_of.get(s):
            uses.setdefault(top_of[s], set()).update(mods)
    device = {}
    for i, d in enumerate(tree.directives):
        sc = tree.assoc[i].scope
        top = sc[1] if len(sc) > 1 else None
        if top is None:
            continue
        if d.name == "requires":
            reqs.setdefault(top, set()).update(
                c.name for c in d.clauses if c.name in req_names)
        if d.name == "declare target" or (
                _leaves(tree, i)[0] in _DEVICE_CONSTRUCTS):
            device.setdefault(top, i)

    def effective(top):
        out = set(reqs.get(top, ()))
        for m in uses.get(top, ()):
            if m in names:
                out |= reqs.get(names[m], set())
        return out
    sets = {top: effective(top) for top in device}
    if version < 60:
        kinds = {bool(v) for v in sets.values()}
        if len(kinds) > 1:
            return sorted(device[t] for t, v in sets.items() if not v)
        return []
    if len({frozenset(v) for v in sets.values()}) > 1:
        common = max(sets.values(), key=len)
        return sorted(device[t] for t, v in sets.items() if v != common)
    return []


def _dep_type(c) -> str | None:
    kinds = {"in", "out", "inout", "mutexinoutset", "inoutset", "depobj",
             "source", "sink"}
    return next((m for m in map(_norm, c.modifiers) if m in kinds), None)


@predicate
def depend_all_memory_out_inout(tree, version):
    """omp_all_memory in a depend clause whose type is not out or inout."""
    return _each(tree, lambda i: any(
        "omp_all_memory" in _items([c]) and _dep_type(c) not in ("out",
                                                                 "inout")
        for c in _clauses(tree, i, "depend")))


@predicate
def depend_depobj_no_section(tree, version):
    """An array section in a depend clause with the depobj type."""
    return _each(tree, lambda i: any(
        _dep_type(c) == "depobj" and any(
            re.search(r"\(.*:.*\)|\[.*:.*\]", x) for x in _items([c]))
        for c in _clauses(tree, i, "depend")))


@predicate
def depend_no_common_block(tree, version):
    """A common block name (/name/) in a depend clause."""
    return _each(tree, lambda i: any(
        x.startswith("/") for x in _items(_clauses(tree, i, "depend"))))


def _zero_length(item: str) -> bool:
    """An array section with integer literal bounds lb > ub in some
    dimension (or a literal length of zero is not Fortran syntax; C, Task
    20: a literal length of 0)."""
    for dims in _c_sections(item):
        if any(len(t) >= 2 and _int(t[1] or "x") == 0 for t in dims):
            return True
    m = re.search(r"\((.*)\)$", item)
    if not m:
        return False
    for dim in _split_top(m.group(1), ","):
        parts = _split_top(dim, ":")
        if len(parts) >= 2:
            lo, hi = _int(parts[0] or "x"), _int(parts[1] or "x")
            if lo is not None and hi is not None and lo > hi:
                return True
    return False


@predicate
def depend_no_zero_length(tree, version):
    """A depend list item that is an array section with literal bounds
    lb > ub (zero length)."""
    return _each(tree, lambda i: any(
        _zero_length(x) for x in _items(_clauses(tree, i, "depend"))))


@predicate
def taskwait_no_mutexinoutset(tree, version):
    """taskwait with depend(mutexinoutset: ...)."""
    return _each(tree, lambda i: tree.directives[i].name == "taskwait" and any(
        _dep_type(c) == "mutexinoutset" for c in _clauses(tree, i, "depend")))


@predicate
def taskwait_nowait_needs_depend(tree, version):
    """taskwait with nowait and no depend clause."""
    return _each(tree, lambda i: tree.directives[i].name == "taskwait"
                 and bool(_clauses(tree, i, "nowait"))
                 and not _clauses(tree, i, "depend"))


@predicate
def taskwait_replayable_needs_depend(tree, version):
    """taskwait with replayable and no depend clause (6.0)."""
    return _each(tree, lambda i: tree.directives[i].name == "taskwait"
                 and bool(_clauses(tree, i, "replayable"))
                 and not _clauses(tree, i, "depend"))


@predicate
def depobj_one_locator(tree, version):
    """A depend clause on depobj with more than one list item."""
    return _each(tree, lambda i: tree.directives[i].name == "depobj" and any(
        len(_items([c])) > 1 for c in _clauses(tree, i, "depend")))


@predicate
def depobj_update_not_depobj(tree, version):
    """update(depobj) on a depobj directive."""
    return _each(tree, lambda i: "depobj" in _items(
        _clauses(tree, i, "update")))


def _scans(tree, i) -> list[int]:
    return [c for c in tree.children(i) if tree.directives[c].name == "scan"
            and _clauses(tree, c, "inclusive", "exclusive")]


@predicate
def scan_at_most_one(tree, version):
    """A construct with more than one scan directive (with inclusive or
    exclusive) as its separating directives."""
    return sorted(s for i in range(len(tree.directives))
                  for s in _scans(tree, i)[1:])


@predicate
def scan_not_orphaned(tree, version):
    """A scan directive not directly in the loop nest of a construct with a
    do or simd leaf."""
    def bad(i):
        if tree.directives[i].name != "scan":
            return False
        p = tree.parent(i)
        return p is None or not set(_leaves(tree, p)) & {"do", "for", "simd"}
    return _each(tree, bad)


@predicate
def scan_items_in_inscan_reduction(tree, version):
    """A scan inclusive/exclusive list item that is not in a
    reduction(inscan, ...) clause of the enclosing construct."""
    def bad(i):
        if tree.directives[i].name != "scan" or tree.parent(i) is None:
            return False
        red = set(_items(_reductions(tree, tree.parent(i), "inscan")))
        return any(x not in red for x in _items(
            _clauses(tree, i, "inclusive", "exclusive")))
    return _each(tree, bad)


@predicate
def inscan_items_on_scan(tree, version):
    """A reduction(inscan, ...) list item that no inclusive or exclusive
    clause of a scan directive in the construct names."""
    def bad(i):
        red = set(_items(_reductions(tree, i, "inscan")))
        if not red:
            return False
        on = set().union(*[set(_items(_clauses(tree, s, "inclusive",
                                               "exclusive")))
                           for s in _scans(tree, i)])
        return bool(red - on)
    return _each(tree, bad)


@predicate
def scan_perfectly_nested(tree, version):
    """A construct with a scan directive whose associated loops are not
    perfectly nested (intervening statements)."""
    def bad(i):
        a, n = tree.assoc[i], _assoc_count(tree, i)
        return bool(_scans(tree, i)) and n is not None and n > 1 and any(
            a.intervening[:n - 1])
    return _each(tree, bad)


@predicate
def declare_simd_in_subprogram(tree, version):
    """declare simd outside the specification part of a subroutine or
    function (in a program, module or submodule scoping unit, or inside a
    construct)."""
    def bad(i):
        if tree.directives[i].name != "declare simd":
            return False
        kind = tree.units.get(tree.assoc[i].scope[-1], ("", None))[0]
        return tree.parent(i) is not None or kind in (
            "program", "module", "submodule", "blockdata")
    return _each(tree, bad)


def _mapper_spec(d) -> tuple:
    """(mapper identifier, type, variable) of a declare mapper argument
    (Fortran ``[id:] type :: var``; C ``[id:] type var``, the
    type with its blanks removed)."""
    raw = d.args[0] if d.args else ""
    if "::" not in raw and raw:
        m = re.match(r"^\s*(?:(\w+)\s*:(?!:))?\s*(.*\S)\s+(\w+)\s*$", raw)
        if m:
            return (m.group(1) or "default").lower(), _norm(m.group(2)), \
                m.group(3).lower()
    arg = _norm(raw)
    head, _, var = arg.partition("::")
    ident, _, typ = head.rpartition(":")
    return ident or "default", typ, var


@predicate
def declare_mapper_no_release_delete(tree, version):
    """release or delete map-type on a declare mapper map clause (5.2)."""
    return _each(tree, lambda i: tree.directives[i].name == "declare mapper"
                 and any(set(c.modifiers) & {"release", "delete"}
                         for c in _clauses(tree, i, "map")))


@predicate
def declare_mapper_modifier_default(tree, version):
    """A mapper(m) modifier with m other than default on a declare mapper
    map clause."""
    return _each(tree, lambda i: tree.directives[i].name == "declare mapper"
                 and any(_mapper(c) != "default"
                         for c in _clauses(tree, i, "map")))


@predicate
def declare_mapper_unique(tree, version):
    """Two declare mapper directives in one scoping unit with the same
    mapper identifier and type."""
    seen, out = set(), []
    for i, d in enumerate(tree.directives):
        if d.name == "declare mapper":
            ident, typ, _ = _mapper_spec(d)
            key = (tree.assoc[i].scope[-1], ident, typ)
            if key in seen:
                out.append(i)
            seen.add(key)
    return out


@predicate
def declare_mapper_type_not_intrinsic(tree, version):
    """A declare mapper for an intrinsic type; for an abstract type the
    source defines (5.0 §2.19.7.3 p.328, 5.2, 6.0); (6.0) for a
    parameterized derived type the source defines."""
    def bad(i):
        if tree.directives[i].name != "declare mapper":
            return False
        typ = _mapper_spec(tree.directives[i])[1]
        if re.match(r"^(?:integer|real|doubleprecision|complex|logical|"
                    r"character)\b", typ):
            return True
        if tree.lang != "f90":
            return False
        m = re.fullmatch(r"(?:type|class)\(([a-z_]\w*)\)|([a-z_]\w*)", typ)
        t = _oop(tree)["types"].get(m and (m.group(1) or m.group(2)))
        return bool(t and (t["abstract"] or (version >= 60 and t["pdt"])))
    return _each(tree, bad)


@predicate
def declare_mapper_maps_var(tree, version):
    """A declare mapper none of whose map clauses maps the variable or an
    element of it."""
    def bad(i):
        if tree.directives[i].name != "declare mapper":
            return False
        var = _mapper_spec(tree.directives[i])[2]
        return bool(var) and not any(_base(x) == var for x in _items(
            _clauses(tree, i, "map")))
    return _each(tree, bad)


# --- loop nest shape --------------------------------------------------------------

_BRANCH = re.compile(r"^(?:if\s*\(.*\)\s*)?(exit|cycle)\b\s*([a-z_]\w*)?$")
_DO_NAME = re.compile(r"^(?:([a-z_]\w*)\s*:\s*)?do\b")


def _branches(tree, i) -> list[tuple]:
    """(exit|cycle, depth of the DO it applies to, line) in the DO nest of
    loop directive i; depth 1 is the outermost loop of the nest."""
    out, stack = [], []
    for ln, st in _body(tree, i):
        if _is_do(st):
            m = _DO_NAME.match(st)
            stack.append(m.group(1) if m else None)
            continue
        if _END_DO.match(st):
            if stack:
                stack.pop()
            continue
        m = _BRANCH.match(st)
        if m and stack:
            name = m.group(2)
            if name:
                depth = next((k + 1 for k in range(len(stack) - 1, -1, -1)
                              if stack[k] == name), None)
            else:
                depth = len(stack)
            if depth:
                out.append((m.group(1), depth, ln))
    return out


def _n_assoc(tree, i) -> int:
    a = tree.assoc[i]
    n = _assoc_count(tree, i) or 1
    return min(n, a.loop_depth) if a.loop_depth else n


@predicate
def exit_from_associated_loop(tree, version):
    """An EXIT statement that terminates one of the associated loops."""
    return _each(tree, lambda i: tree.assoc[i].kind == "loop" and any(
        k == "exit" and d <= _n_assoc(tree, i)
        for k, d, _ in _branches(tree, i)))


@predicate
def cycle_in_intervening_code(tree, version):
    """A CYCLE statement that applies to an associated loop other than the
    innermost one (it is in intervening code or branches out of the inner
    loop body)."""
    return _each(tree, lambda i: tree.assoc[i].kind == "loop" and any(
        k == "cycle" and d < _n_assoc(tree, i)
        for k, d, _ in _branches(tree, i)))


@predicate
def loop_var_not_modified(tree, version):
    """An assignment to the iteration variable of an associated loop, or a
    nested DO loop with that variable, in the loop nest."""
    def bad(i):
        vs = _assoc_vars(tree, i)
        if not vs:
            return False
        if getattr(tree, "lang", "f90") == "c":
            return _c_loop_var_modified(tree, i, vs)
        dos = [m.group(1) for _, st in _body(tree, i)
               if (m := _DO_VAR.match(st))]
        if any(dos.count(v) > 1 for v in vs):
            return True
        return any(re.match(rf"^{v}\s*=(?!=)", st)
                   for _, st in _body(tree, i) for v in vs)
    return _each(tree, bad)


def _c_loop_var_modified(tree, i, vs) -> bool:
    """C: an assignment, increment or decrement of an associated
    loop's iteration variable in the nest, or a nested for loop on it,
    other than the associated loops' own headers."""
    own = set(tree.extra["loops"].get(i, {}).get("lines", ()))
    for ln, st in _body(tree, i):
        if st.startswith("for (") and ln in own:
            continue
        for v in vs:
            if re.search(rf"(?<![\w.>*]){v}\s*(?:=(?!=)|\+\+|--|"
                         r"[-+*/%&|^]=|<<=|>>=)|(?:\+\+|--)\s*"
                         rf"{v}\b", st):
                return True
    return False


@predicate
def loop_var_not_threadprivate(tree, version):
    """The iteration variable of an associated loop is threadprivate."""
    def bad(i):
        vs = _assoc_vars(tree, i)
        tp = _tp_keys(tree)
        return bool(vs) and any(_key(tree, i, v) in tp for v in vs)
    return _each(tree, bad)


@predicate
def loop_var_integer(tree, version):
    """An associated loop whose iteration variable is declared with a type
    other than integer."""
    def bad(i):
        vs = _assoc_vars(tree, i)
        return bool(vs) and any(_vtype(tree, i, v) not in (None, "integer")
                                for v in vs)
    return _each(tree, bad)


def _refs(expr: str, names) -> set:
    return {x for x in re.findall(r"(?<![%\w])([a-z_]\w*)", expr)
            if x in names}


def _nonrect(tree, i) -> list[tuple]:
    """(lb refs, ub refs) of each associated loop after the first whose
    bounds reference an outer associated loop variable."""
    vs = _assoc_vars(tree, i)
    if not vs:
        return []
    out = []
    for k in range(1, len(vs)):
        lb, ub, _ = tree.assoc[i].loop_bounds[k]
        lr, ur = _refs(lb, vs[:k]), _refs(ub, vs[:k])
        if lr or ur:
            out.append((lr, ur))
    return out


@predicate
def nonrect_same_outer_var(tree, version):
    """A non-rectangular loop whose lb and ub reference different outer
    loop variables (or more than one)."""
    return _each(tree, lambda i: any(
        len(lr | ur) > 1 for lr, ur in _nonrect(tree, i)))


def _nonrect_with(*clauses):
    def fn(tree, version):
        return _each(tree, lambda i: bool(_clauses(tree, i, *clauses))
                     and bool(_nonrect(tree, i)))
    fn.__doc__ = (f"A {' or '.join(clauses)} clause on a construct whose "
                  "associated loops include a non-rectangular loop (a bound "
                  "referencing an outer associated loop variable).")
    return fn


_register("schedule_rectangular", _nonrect_with("schedule"))
_register("dist_schedule_rectangular", _nonrect_with("dist_schedule"))
_register("ordered_rectangular", _nonrect_with("ordered"))
_register("linear_rectangular", _nonrect_with("linear"))
_register("induction_rectangular", _nonrect_with("induction"))


@predicate
def ordered_n_within_depth(tree, version):
    """ordered(n) with an integer literal n greater than the depth of the
    DO nest that follows."""
    def bad(i):
        a, n = tree.assoc[i], _lit(tree, i, "ordered")
        return a.kind == "loop" and a.loop_depth > 0 and a.depth_known \
            and n is not None and n > a.loop_depth
    return _each(tree, bad)


@predicate
def ordered_n_ge_collapse(tree, version):
    """ordered(n) and collapse(m) with integer literals, n < m."""
    def bad(i):
        n = _lit(tree, i, "ordered")
        m = _lit(tree, i, "collapse")
        return n is not None and m is not None and n < m
    return _each(tree, bad)


@predicate
def ordered_n_no_linear(tree, version):
    """ordered(n) and a linear clause on one directive (5.2)."""
    return _each(tree, lambda i: any(c.args for c in _clauses(
        tree, i, "ordered")) and bool(_clauses(tree, i, "linear")))


@predicate
def ordered_n_perfectly_nested(tree, version):
    """ordered(n) with the n associated loops not perfectly nested
    (intervening statements; 5.2; 5.0: any ordered clause, the loops the
    construct is associated with, 5.0 §2.9.2 p.107)."""
    def bad(i):
        a, n = tree.assoc[i], _lit(tree, i, "ordered")
        if version == 50 and n is None and _clauses(tree, i, "ordered"):
            n = _lit(tree, i, "collapse") or 1
        return n is not None and a.kind == "loop" and len(a.intervening) \
            >= n and any(a.intervening[:n - 1])
    return _each(tree, bad)


@predicate
def loop_do_concurrent_clauses(tree, version):
    """A construct with a loop leaf followed by a DO CONCURRENT loop with a
    data-sharing clause or collapse (6.0)."""
    def bad(i):
        if "loop" not in _leaves(tree, i):
            return False
        first = next((st for _, st in _body(tree, i) if _is_do(st)), "")
        return bool(re.match(r"^(?:[a-z_]\w*\s*:\s*)?do\s*concurrent\b",
                             first)) and bool(_clauses(
                                 tree, i, "private", "lastprivate",
                                 "reduction", "collapse"))
    return _each(tree, bad)


@predicate
def reduction_section_base(tree, version):
    """A reduction, in_reduction or induction list item that is an array
    section whose base is not a name, or with literal zero length (5.2:
    or a literal stride other than 1)."""
    def bad_item(x):
        if _c_sections(x):  # C: b[lb:len[:stride]]
            base = _section_base(x)
            if base is None or not re.fullmatch(r"[a-z_]\w*", base):
                return True
            if _zero_length(x):
                return True
            return version < 60 and any(
                len(t) == 3 and _int(t[2] or "1") not in (None, 1)
                for dims in _c_sections(x) for t in dims)
        if not re.search(r"\(.*:.*\)$", x):
            return False
        if not re.fullmatch(r"[a-z_]\w*", x.split("(")[0]):
            return True
        if _zero_length(x):
            return True
        if version < 60:
            inner = re.search(r"\((.*)\)$", x).group(1)
            return any(len(p) == 3 and _int(p[2] or "1") not in (None, 1)
                       for p in (_split_top(d, ":")
                                 for d in _split_top(inner, ",")))
        return False
    return _each(tree, lambda i: any(bad_item(x) for x in _items(
        _clauses(tree, i, "reduction", "in_reduction", "induction"))))


@predicate
def aligned_pointer_or_allocatable(tree, version):
    """An aligned list item declared without POINTER or ALLOCATABLE and not
    of type(c_ptr) (5.2)."""
    def bad(i):
        for x in map(_base, _items(_clauses(tree, i, "aligned"))):
            s = _decl_scope(tree, i, x)
            if s is not None and tree.attribute(i, x) == "plain" \
                    and tree.vartypes.get((s, x)) != "c_ptr":
                return True
        return False
    return _each(tree, bad)


@predicate
def aligned_array(tree, version):
    """An aligned list item declared as a scalar (6.0)."""
    return _each(tree, lambda i: any(
        _is_array(tree, i, _base(x)) is False
        for x in _items(_clauses(tree, i, "aligned"))))


@predicate
def in_reduction_matching_item(tree, version):
    """An in_reduction list item whose closest enclosing construct with the
    item in task_reduction or reduction(task, ...) uses another reduction
    identifier, or (in a main program, where no caller can supply one)
    that no enclosing construct has."""
    def ident(c):
        return next((_norm(m) for m in _modifiers(c)
                     if _norm(m) not in ("task", "inscan", "default")), None)

    def bad(i):
        for c in _clauses(tree, i, "in_reduction"):
            for x in _items([c]):
                found = None
                for p in _ancestors(tree, i):
                    for oc in _clauses(tree, p, "task_reduction",
                                       "reduction"):
                        if (oc.name == "task_reduction"
                                or "task" in oc.modifiers) \
                                and x in _items([oc]):
                            found = oc
                    if found:
                        break
                if found is not None and ident(found) != ident(c):
                    return True
                kind = tree.units.get(tree.assoc[i].scope[-1],
                                      ("", None))[0]
                if found is None and kind == "program":
                    return True
        return False
    return _each(tree, bad)


# --- Second pass ------------------------------------------------------------

_LIST_CLAUSES = set(_UNIQUE_LISTS) | {"map", "depend", "use_device_ptr",
                                      "use_device_addr", "is_device_ptr",
                                      "has_device_addr", "in_reduction",
                                      "task_reduction", "induction"}


def _c_sections(x: str) -> list[list[list[str]]]:
    """C array sections: per [..] subscript with a ':', its
    [lb, length[, stride]] texts, as one dimension list."""
    dims = [_split_top(m.group(1), ":")
            for m in re.finditer(r"\[([^\[\]]*)\]", x)]
    return [dims] if any(len(d) > 1 for d in dims) else []


def _sections(x: str) -> list[list[str]]:
    """The subscript triplets (lb, ub[, stride]) of the parenthesised parts
    of a list item that contain a ':'."""
    out = []
    for m in re.finditer(r"\(([^()]*(?:\([^()]*\)[^()]*)*)\)", x):
        dims = _split_top(m.group(1), ",")
        if any(":" in d for d in dims):
            out.append([_split_top(d, ":") for d in dims])
    return out


@predicate
def section_stride_positive(tree, version):
    """An array section with an integer literal stride less than one."""
    return _each(tree, lambda i: any(
        len(t) == 3 and _int(t[2] or "1") is not None and _int(t[2]) < 1
        for c in _clauses(tree, i, end=True) if c.name in _LIST_CLAUSES
        for x in _items([c]) for dims in _sections(x) for t in dims))


@predicate
def section_last_part_ref(tree, version):
    """A list item with a section subscript in a part-ref other than the
    last (a(1:n)%c)."""
    return _each(tree, lambda i: any(
        re.search(r"\([^()]*:[^()]*\)\s*%", x)
        for c in _clauses(tree, i, end=True) if c.name in _LIST_CLAUSES
        for x in _items([c])))


@predicate
def map_section_contiguous(tree, version):
    """A map list item that is an array section with an integer literal
    stride other than 1 (not contiguous)."""
    return _each(tree, lambda i: _map_construct(tree, i) and any(
        len(t) == 3 and _int(t[2] or "1") not in (None, 1)
        for x in _items(_clauses(tree, i, "map"))
        for dims in _sections(x) + _c_sections(x) for t in dims))


def _iterator_values(spec: str, c_lang: bool, consts: dict | None = None
                     ) -> tuple[str, int | None]:
    """(identifier, number of values) of one iterator-specifier
    ``[type] id = begin:end[:step]`` (None when a bound is not an integer
    literal). C/C++ ranges exclude the end, Fortran ranges include it
    (5.2 §3.2.6 p.67)."""
    m = re.match(r"\s*(?:[\w\s:*]*?(?:::)?\s+)?([a-z_]\w*)\s*=\s*(.+)$",
                 spec.strip(), re.I)
    if not m:
        return "", None
    parts = _split_top(m.group(2), ":")
    nums = [_int(x) if _int(x) is not None else
            (consts or {}).get(x.strip()) for x in parts]
    if len(parts) not in (2, 3) or any(n is None for n in nums):
        return m.group(1).lower(), None
    b, e = nums[0], nums[1]
    s = nums[2] if len(nums) == 3 else 1
    if s == 0:
        return m.group(1).lower(), None
    if c_lang:
        n = max(0, -(-(e - b) // s)) if s > 0 else max(0, -(-(b - e) // -s))
    else:
        n = max(0, (e - b) // s + 1) if s > 0 else max(0, (b - e) // -s + 1)
    return m.group(1).lower(), n


@predicate
def map_iterator_shared_containing_array(tree, version):
    """A map clause whose iterator modifier gives two or more values (integer
    literal bounds) to an identifier used only in the subscript applied to a
    named variable: every instance has that variable as containing array
    (or base pointer), 5.2 §5.8.3 p.156."""
    def bad(i):
        for c in _clauses(tree, i, "map"):
            for mod in c.modifiers:
                m = re.match(r"\s*iterator\s*\((.*)\)\s*$", mod, re.I | re.S)
                if not m:
                    continue
                c_lang = getattr(tree, "lang", "") == "c"
                multi = set()
                for spec in _split_top(m.group(1), ","):
                    macros = tree.extra.get("macros") or {}
                    ident, n = _iterator_values(
                        spec, c_lang, {**{k.lower(): v for k, v in
                                          macros.items()}, **macros})
                    if ident and n is not None and n >= 2:
                        multi.add(ident)
                for x in c.args:
                    x = _norm(x)
                    mm = (re.fullmatch(r"([a-z_]\w*)\s*\[([^\[\]]*)\]", x)
                          or re.fullmatch(r"([a-z_]\w*)\s*\(([^()]*)\)", x))
                    if mm and multi & set(re.findall(r"[a-z_]\w*",
                                                     mm.group(2))):
                        return True
        return False
    return _each(tree, bad)


@predicate
def task_reduction_item_needs_in_reduction(tree, version):
    """A task construct whose body references an item of a reduction clause
    of the innermost enclosing worksharing or parallel construct (a leaf
    of it) without naming it in an in_reduction clause."""
    def bad(i):
        if tree.directives[i].name != "task":
            return False
        hit = None
        for p, k, leaf in _outer_leaf_slots(tree, i):
            if leaf == "parallel" or _ws_leaf(tree, p, leaf):
                hit = (p, k)
                break
            if leaf in ("teams", "target"):
                return False
        if hit is None:
            return False
        red = {_base(x) for x in _on_leaf(tree, hit[0], hit[1], version,
                                          ("reduction",))}
        red -= {_base(x) for x in _items(_clauses(tree, i, "in_reduction"))}
        if not red:
            return False
        names = set()
        for _, st in _body(tree, i):
            names |= set(re.findall(r"(?<![%\w])([a-z_]\w*)",
                                    _STRING.sub("", st)))
        names |= {_base(x) for x in _items(_clauses(tree, i))}
        return bool(red & names)
    return _each(tree, bad)


@predicate
def ordered_simd_threads_in_worksharing_simd(tree, version):
    """A block-associated ordered construct with both simd and threads
    whose closest enclosing construct has no simd leaf, or has one but no
    do leaf of its own or of its closest enclosing construct (5.2)."""
    def bad(i):
        d = tree.directives[i]
        if d.name != "ordered (Block)" or not (
                _clauses(tree, i, "simd") and _clauses(tree, i, "threads")):
            return False
        p = tree.parent(i)
        if p is None:
            return False
        ls = set(_leaves(tree, p))
        if "simd" not in ls:
            return True
        if ls & {"do", "for"}:
            return False
        q = tree.parent(p)
        return q is None or not set(_leaves(tree, q)) & {"do", "for"}
    return _each(tree, bad)


_DECLARATIVE = {"declare target", "declare simd", "declare mapper",
                "declare reduction", "declare_induction", "declare variant",
                "requires", "threadprivate", "groupprivate", "allocate"}
_USE_IMPLICIT = re.compile(r"^(?:use\b|import\b|implicit\b)")


@predicate
def declarative_after_use(tree, version):
    """A declarative directive (5.2: requires) before a USE, IMPORT or
    IMPLICIT statement of its own scoping unit."""
    names = _DECLARATIVE if version >= 60 else {"requires"}

    def bad(i):
        if tree.directives[i].name not in names:
            return False
        a = tree.assoc[i]
        return any(ln > a.line and sc == a.scope and _USE_IMPLICIT.match(st)
                   for ln, st, sc in tree.statements)
    return _each(tree, bad)


@predicate
def named_constant_list_item(tree, version):
    """A named constant (PARAMETER, visible from the directive) as a list
    item of a clause other than shared or firstprivate (5.2: of a
    data-sharing attribute clause; 6.0: of any clause)."""
    clauses = set(_DSA) if version < 60 else _LIST_CLAUSES

    def bad(i):
        for c in _clauses(tree, i, end=True):
            if c.name not in clauses or c.name in ("shared", "firstprivate"):
                continue
            for x in map(_base, _items([c])):
                s = _decl_scope(tree, i, x)
                if s is not None and (s, x) in tree.params:
                    return True
        return False
    return _each(tree, bad)


# --- Fortran derived types and type-bound procedures (fortran-oop) ---------------
# The scanner's facts (``types``,
# ``vartypes``, ``vtypes``, ``units``, ``statements``) plus a pass over the
# statements of each derived-type definition: its parent (EXTENDS), whether
# it is abstract or parameterized, and its type-bound procedure part
# (specific bindings, generic bindings, final subroutines). Types are
# matched by name across the source (the programs judged here define each
# type once); a binding whose procedure is not defined in the source is
# never judged.

_TYPE_HEAD = re.compile(r"^type\b(?!\s*\()(?!\s*is\b)\s*(,[^:]*)?(?:::)?\s*"
                        r"([a-z_]\w*)\s*(\(.*\))?$")
_TBP_SPECIFIC = re.compile(r"^procedure\b\s*(?:\(\s*\w*\s*\))?\s*"
                           r"(?:,([^:]*))?(?:::)?\s*(.*)$")
_TBP_GENERIC = re.compile(r"^generic\b\s*(?:,[^:]*)?::\s*(.+?)\s*=>\s*(.*)$")
_TBP_FINAL = re.compile(r"^final\b\s*(?:::)?\s*(.*)$")
_GENERIC_IFACE = re.compile(r"^interface\s+([a-z_]\w*)\s*$")
_PROC_POINTER = re.compile(r"^procedure\s*\([^)]*\)\s*,([^:]*)::\s*(.*)$")
_CHAIN = r"[a-z_]\w*(?:\s*\([^()]*\))?(?:\s*%\s*[a-z_]\w*(?:\s*\([^()]*\))?)*"
_TBP_REF = re.compile(rf"({_CHAIN})\s*%\s*([a-z_]\w*)\s*(?=\(|$)")
_ASSIGN_TO = re.compile(rf"^({_CHAIN})\s*=(?![=>])")
_ANY_CHAIN = re.compile(_CHAIN)
_LOCAL_DECL = re.compile(r"^(type|class)\s*\(\s*([a-z_]\w*)\s*\)(.*)$")


def _oop(tree: ProgramTree) -> dict:
    """{type name: {parent, abstract, pdt, comps, bindings, generics,
    finals}}, procedure names defined in the source, generic interface
    names and procedure pointer names (cached in tree.extra)."""
    if "oop" in tree.extra:
        return tree.extra["oop"]
    types, generic_names, proc_ptrs = {}, set(), set()
    cur, tbp = None, False
    for _, st, _sc in tree.statements:
        m = _TYPE_HEAD.match(st)
        if cur is None and m:
            attrs = m.group(1) or ""
            par = re.search(r"\bextends\s*\(\s*([a-z_]\w*)\s*\)", attrs)
            cur, tbp = m.group(2), False
            types[cur] = {"parent": par.group(1) if par else None,
                          "abstract": bool(re.search(r"\babstract\b",
                                                     attrs)),
                          "pdt": bool(m.group(3)), "comps": {},
                          "bindings": {}, "generics": {}, "finals": []}
            continue
        if cur is not None:
            if _END_TYPE.match(st):
                cur = None
            elif st == "contains":
                tbp = True
            elif tbp and (g := _TBP_GENERIC.match(st)):
                key = _norm(g.group(1))
                types[cur]["generics"].setdefault(key, []).extend(
                    _norm(x) for x in _split_statements_commas(g.group(2)))
            elif tbp and (f := _TBP_FINAL.match(st)):
                types[cur]["finals"] += [_norm(x) for x in
                                         _split_statements_commas(f.group(1))]
            elif tbp and (p := _TBP_SPECIFIC.match(st)):
                deferred = "deferred" in (p.group(1) or "")
                for ent in _split_statements_commas(p.group(2)):
                    b, _, impl = ent.partition("=>")
                    b, impl = _norm(b), _norm(impl) or _norm(b)
                    if b:
                        types[cur]["bindings"][b] = None if deferred \
                            else impl
            continue
        g = _GENERIC_IFACE.match(st)
        if g:
            generic_names.add(g.group(1))
        pp = _PROC_POINTER.match(st)
        if pp and re.search(r"\bpointer\b", pp.group(1)):
            proc_ptrs |= set(_entities(pp.group(2)))
    for (_scope, tname), comps in tree.types.items():
        if tname in types:
            types[tname]["comps"].update(comps)
    procs = {}
    for uid, (kind, name) in tree.units.items():
        if kind in ("subroutine", "function") and name:
            procs.setdefault(name, []).append(uid)
    out = {"types": types, "procs": procs, "generic_names": generic_names,
           "proc_pointers": proc_ptrs}
    tree.extra["oop"] = out
    return out


def _ancestors_of(types: dict, t: str) -> list[str]:
    out = []
    while t in types and t not in out:
        out.append(t)
        t = types[t]["parent"]
    return out


def _descendants_of(types: dict, t: str) -> list[str]:
    return [d for d in types if d != t and t in _ancestors_of(types, d)]


def _scoped(table: dict, scopes: tuple, name: str):
    """The entry of `name` declared in the innermost of `scopes` that
    declares it (a local declaration; no USE shadowing check: a name
    declared in a scoping unit cannot also be use-associated there)."""
    for sid in reversed(scopes):
        if (sid, name) in table:
            return table[(sid, name)]
    return None


def _chain_type(tree, oop, scopes, chain: str):
    """(type name, polymorphic) of a designator `a%b(i)%c`, None when a
    name on the path is not a derived-type entity the source defines."""
    parts = [re.sub(r"\(.*", "", x).strip()
             for x in re.sub(r"\([^()]*\)", "", chain).split("%")]
    t = _scoped(tree.vartypes, scopes, parts[0])
    poly = _scoped(tree.vtypes, scopes, parts[0]) == "class"
    for comp in parts[1:]:
        found = None
        for a in _ancestors_of(oop["types"], t or ""):
            if comp in oop["types"][a]["comps"]:
                found = oop["types"][a]["comps"][comp]
                break
        if found is None:
            return None
        t, poly = found[1], False
    return (t, poly) if t in oop["types"] else None


def _binding_procs(oop, t: str, b: str, poly: bool, seen=None) -> set:
    """Procedures a reference to binding (or generic) `b` of an object of
    declared type `t` may invoke: the inherited or own binding, and, for a
    polymorphic object, every override in an extension of `t`."""
    seen = set() if seen is None else seen
    if (t, b) in seen:
        return set()
    seen.add((t, b))
    types, out = oop["types"], set()
    for a in _ancestors_of(types, t):
        if b in types[a]["bindings"]:
            if types[a]["bindings"][b]:
                out.add(types[a]["bindings"][b])
            break
        if b in types[a]["generics"]:
            for sp in types[a]["generics"][b]:
                out |= _binding_procs(oop, t, sp, poly, seen)
            break
    if poly:
        for d in _descendants_of(types, t):
            impl = types[d]["bindings"].get(b)
            if impl:
                out.add(impl)
    return out


def _finals(oop, t: str) -> set:
    return {f for a in _ancestors_of(oop["types"], t)
            for f in oop["types"][a]["finals"]}


_OPERATOR = re.compile(r"^operator\((.+)\)$")


def _stmt_accesses(tree, oop, st: str, scopes: tuple) -> set:
    """Type-bound procedures a statement accesses: binding references,
    a defined assignment to a derived-type designator, a defined
    operator on one, and the final subroutines of a local derived-type
    object it declares."""
    out = set()
    for m in _TBP_REF.finditer(st):
        ty = _chain_type(tree, oop, scopes, m.group(1))
        if ty:
            out |= _binding_procs(oop, ty[0], m.group(2), ty[1])
    a = _ASSIGN_TO.match(st)
    if a:
        ty = _chain_type(tree, oop, scopes, a.group(1))
        if ty:
            out |= _binding_procs(oop, ty[0], "assignment(=)", ty[1])
    for m in _ANY_CHAIN.finditer(st):
        ty = _chain_type(tree, oop, scopes, m.group(0))
        if not ty:
            continue
        for a_ in _ancestors_of(oop["types"], ty[0]):
            for g in oop["types"][a_]["generics"]:
                op = _OPERATOR.match(g)
                if op and op.group(1) in st.replace(m.group(0), " "):
                    out |= _binding_procs(oop, ty[0], g, ty[1])
    d = _LOCAL_DECL.match(st)
    attrs = _norm(d.group(3).split("::")[0]) if d else ""
    if d and "pointer" not in attrs and not re.search(
            r"intent\(in(?:out)?\)", attrs):
        # a local object or an INTENT(OUT) dummy is finalized (F2018
        # 7.5.6.3); an INTENT(IN)/(INOUT) dummy or a pointer is not
        out |= _finals(oop, d.group(2))
    return out


def _declared_target_procs(tree) -> set:
    """Procedure names that appear in a declare target directive: the
    procedure a declaration-associated directive (no list, no enter/to
    clause) sits in, and the names of its extended list or enter/to
    clauses."""
    out = set()
    for i, d in enumerate(tree.directives):
        if d.name != "declare target":
            continue
        listed = _dt_items(tree, i, "enter", "to")
        if listed:
            out |= {_base(x) for x in listed}
        else:
            kind, name = tree.units.get(tree.assoc[i].scope[-1], ("", None))
            if kind in ("subroutine", "function") and name:
                out.add(name)
    return out


_NOT_REGION = {"target data", "target enter data", "target exit data",
               "target update"}


@predicate
def type_bound_declare_target(tree, version):
    """A type-bound procedure (a specific binding, a generic binding's
    specific, a defined assignment or operator, a final subroutine)
    accessed in a target region whose procedure, defined in the source,
    is in no declare target directive. The region: the statements of
    target constructs and of the procedures that run on the device (in a
    declare target directive, referenced from the region, or reached as
    a type-bound procedure); firstprivate and private items of target
    constructs reach defined assignments and final subroutines."""
    if tree.lang != "f90":
        return []
    oop = _oop(tree)
    if not any(t["bindings"] or t["generics"] or t["finals"]
               for t in oop["types"].values()):
        return []
    declared = _declared_target_procs(tree)
    procs = oop["procs"]
    by_unit = {}
    for ln, st, sc in tree.statements:
        if sc:
            by_unit.setdefault(sc[-1], []).append((ln, st, sc))
    roots = []   # (origin directive, statements)
    for i, d in enumerate(tree.directives):
        if d.name.split()[0] == "target" and d.name not in _NOT_REGION:
            body = [(ln, st, sc) for ln, st, sc in tree.statements
                    if _extent(tree, i)[0] < ln <= _extent(tree, i)[1]]
            roots.append((i, body))
            for c in _clauses(tree, i, "private", "firstprivate"):
                for x in _items([c]):
                    ty = _chain_type(tree, oop, tree.assoc[i].scope, x)
                    if ty:
                        acc = _finals(oop, ty[0])
                        if c.name == "firstprivate":
                            acc |= _binding_procs(oop, ty[0],
                                                  "assignment(=)", ty[1])
                        roots.append((i, [], acc))
        elif d.name == "declare target":
            for name in _declared_target_procs_at(tree, i):
                for uid in procs.get(name, []):
                    roots.append((i, by_unit.get(uid, [])))
    bad, done = set(), set()
    work = [(r[0], r[1], r[2] if len(r) > 2 else set()) for r in roots]
    while work:
        origin, stmts, extra = work.pop()
        reached = set(extra)
        for _ln, st, sc in stmts:
            reached |= _stmt_accesses(tree, oop, st, sc)
            for name in re.findall(r"\b([a-z_]\w*)\s*(?=\(|$)", st):
                if name in procs and not st.startswith(("subroutine",
                                                        "function")):
                    reached.add(("call", name))
        for r in reached:
            called = isinstance(r, tuple)
            name = r[1] if called else r
            if not called and name in procs and name not in declared:
                bad.add(origin)
            if name in procs and name not in done:
                done.add(name)
                for uid in procs[name]:
                    work.append((origin, by_unit.get(uid, []), set()))
    return sorted(bad)


def _declared_target_procs_at(tree, i: int) -> set:
    """The procedure names declare target directive i declares (as
    _declared_target_procs, for one directive)."""
    listed = _dt_items(tree, i, "enter", "to")
    if listed:
        return {_base(x) for x in listed}
    kind, name = tree.units.get(tree.assoc[i].scope[-1], ("", None))
    return {name} if kind in ("subroutine", "function") and name else set()


def _type_name_bad(oop, spec: str) -> bool:
    """A type-name list item that is CLASS(*), TYPE(*) or an abstract
    type defined in the source."""
    spec = _norm(spec)
    if spec in ("class(*)", "type(*)"):
        return True
    m = re.fullmatch(r"(?:type|class)\(([a-z_]\w*)\)|([a-z_]\w*)", spec)
    name = m and (m.group(1) or m.group(2))
    t = oop["types"].get(name) if name else None
    return bool(t and t["abstract"])


def _reduction_types(d) -> list[str]:
    """The type-name list of a declare reduction argument
    ``id : types : combiner``."""
    raw = d.args[0] if d.args else ""
    parts, cur, depth = [], "", 0
    for ch in raw:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == ":" and depth == 0 and len(parts) < 2:
            parts.append(cur)
            cur = ""
            continue
        cur += ch
    parts.append(cur)
    return _split_statements_commas(parts[1]) if len(parts) == 3 else []


@predicate
def type_name_list_item(tree, version):
    """A declare reduction type-name list item (and a declare mapper type)
    that is CLASS(*) or (6.0) TYPE(*), or an abstract type; the abstract
    type of a declare mapper is declaremapper-clause-004's."""
    if tree.lang != "f90":
        return []
    oop = _oop(tree)

    def bad(i):
        d = tree.directives[i]
        if d.name == "declare reduction":
            return any(_type_name_bad(oop, t) for t in _reduction_types(d))
        if d.name == "declare mapper":
            return _norm(_mapper_spec(d)[1]) in ("class(*)", "type(*)")
        return False
    return _each(tree, bad)


@predicate
def declare_target_procedure_name(tree, version):
    """A declare target list item that names a generic interface or a
    procedure pointer of the source."""
    if tree.lang != "f90":
        return []
    oop = _oop(tree)
    names = oop["generic_names"] | oop["proc_pointers"]
    return _each(tree, lambda i: tree.directives[i].name == "declare target"
                 and any(_base(x) in names for x in _dt_items(
                     tree, i, "enter", "to", "link", "local")))


# The C rules (catalog/omp/rules.yaml entries with lang: c)
from offload.engine import c_rules  # noqa: E402,F401
