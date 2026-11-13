"""Translate a generated free-form Fortran program into C11.

The C programs of the slice are the Fortran programs of ``offload.engine.gen``
ported statement by statement, with the same data, oracle and output line
(``RESULT ran_on_host=<0|1> check=<pass|fail>``). ``translate`` reads the
rendered Fortran source (header, optional module ``gen_mod``, ``program
gen_prog``) and writes C: derived types as structs, module variables and
procedures at file scope, and ``int main(void)``.
Arrays keep their Fortran extents and 1-based values (``a(i)`` is
``a[i - 1]``). Allocatable arrays become fixed-size arrays, pointer arrays
``int *``. Directives map ``!$omp`` to
``#pragma omp``, ``do`` to ``for``, and Fortran reduction identifiers to C
operators; end directives go away and their ``nowait`` moves up.
``TranslateError`` is raised for anything outside this subset (``character``
variables, assumed-shape dummies, ``workdistribute``)."""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field

from offload.engine.grammar import GrammarError, parse_directive


def _top_ops(t: str) -> set[str]:
    """The binary operators of a rendered C expression outside
    parentheses and brackets (they are rendered with blanks around)."""
    ops, depth = set(), 0
    for k, ch in enumerate(t):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif depth == 0 and ch == " ":
            m = re.match(r" (\S+) ", t[k:])
            if m and re.fullmatch(r"[-+*/%<>=!&|^?:]+", m.group(1)):
                ops.add(m.group(1))
    return ops


def _paren(t: str, right: bool = False) -> str:
    """Operand `t` of % in parentheses where C precedence needs them
    (mod(7*s + j, m) is (7*s + j) % m, not 7*s + j % m): the left
    operand when it has an operator of lower precedence than %, the right
    one when it has any operator."""
    ops = _top_ops(t)
    if right:
        return f"({t})" if ops else t
    return f"({t})" if ops - {"*", "/", "%"} else t


class TranslateError(Exception):
    """The Fortran program uses something the translator does not port."""


# --- the Fortran source ---------------------------------------------------------

def _strip_comment(text: str) -> str:
    q = None
    for i, ch in enumerate(text):
        if q:
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
        elif ch == "!":
            return text[:i]
    return text


def logical_lines(source: str) -> list[tuple[str, str]]:
    """(kind, text) per logical line: "head" (a leading ``! `` header
    line), "omp" (a directive, continuations joined, sentinel kept) or
    "stmt"."""
    out = []
    lines = source.splitlines()
    k = 0
    header = True
    while k < len(lines):
        raw = lines[k]
        s = raw.strip()
        k += 1
        if header and s.startswith("! "):
            out.append(("head", s[2:]))
            continue
        header = False
        if not s:
            continue
        if s.lower().startswith(("!$omp", "!$acc")):
            # OpenACC programs (!$acc) too
            sent = s[:5].lower()
            text = s
            while _strip_comment(text[5:]).rstrip().endswith("&"):
                body = _strip_comment(text[5:]).rstrip()[:-1].rstrip()
                nxt = lines[k].strip()
                k += 1
                if not nxt.lower().startswith(sent):
                    raise TranslateError(f"bad continuation {nxt!r}")
                nxt = nxt[5:].lstrip()
                if nxt.startswith("&"):
                    nxt = nxt[1:].lstrip()
                text = sent + " " + body.lstrip() + " " + nxt
            out.append(("omp", text))
            continue
        if s.startswith("!"):
            continue
        text = _strip_comment(s).rstrip()
        while text.endswith("&"):
            nxt = lines[k].strip()
            k += 1
            if nxt.startswith("&"):
                nxt = nxt[1:]
            text = text[:-1].rstrip() + " " + nxt.strip()
        out.append(("stmt", text))
    return out


# --- expressions ----------------------------------------------------------------

@dataclass
class E:
    kind: str          # num, real, logical, str, name, call, member, arrayc,
                       # binop, unop, section, kwarg, paren
    value: str = ""
    args: list = field(default_factory=list)


_ETOK = re.compile(r"""\s*(?:
    (?P<real>\d+\.\d*(?:[dDeE][+-]?\d+)?|\d+[dDeE][+-]?\d+)
  | (?P<num>\d+(?:_\w+)?)
  | (?P<dotop>\.(?:and|or|not|eqv|neqv|eq|ne|lt|le|gt|ge|true|false)\.)
  | (?P<str>'(?:[^']|'')*'|"(?:[^"]|"")*")
  | (?P<name>[A-Za-z_]\w*)
  | (?P<op>==|/=|<=|>=|=>|\*\*|//|\(/|/\)|[-+*/<>=(),:%\[\]])
)""", re.X | re.I)


def _etoks(text: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    text = text.rstrip()
    while pos < len(text):
        m = _ETOK.match(text, pos)
        if not m or m.end() == pos:
            raise TranslateError(f"cannot read expression {text!r} at "
                                 f"{text[pos:]!r}")
        out.append((m.lastgroup, m.group(m.lastgroup)))
        pos = m.end()
    return out


_BIN = {".or.": 1, ".and.": 2, ".eqv.": 0, ".neqv.": 0,
        "==": 4, "/=": 4, "<": 4, "<=": 4, ">": 4, ">=": 4,
        ".eq.": 4, ".ne.": 4, ".lt.": 4, ".le.": 4, ".gt.": 4, ".ge.": 4,
        "+": 6, "-": 6, "*": 7, "/": 7, "**": 9}
_REL = {".eq.": "==", ".ne.": "/=", ".lt.": "<", ".le.": "<=", ".gt.": ">",
        ".ge.": ">="}


class _EParser:
    def __init__(self, text: str):
        self.toks = _etoks(text)
        self.i = 0
        self.text = text

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self, value=None):
        t = self.peek()
        if value is not None and (t[1] or "").lower() != value:
            raise TranslateError(f"expected {value!r} in {self.text!r}")
        self.i += 1
        return t

    def parse(self):
        e = self.expr(0)
        if self.i != len(self.toks):
            raise TranslateError(f"trailing tokens in {self.text!r}")
        return e

    def expr(self, prec):
        kind, v = self.peek()
        low = (v or "").lower()
        if low == ".not.":
            self.take()
            left = E("unop", ".not.", [self.expr(3)])
        elif low in ("-", "+"):
            self.take()
            left = E("unop", low, [self.expr(6)])
        else:
            left = self.primary()
        while True:
            kind, v = self.peek()
            low = (v or "").lower()
            p = _BIN.get(low)
            if p is None or p < prec:
                return left
            self.take()
            low = _REL.get(low, low)
            right = self.expr(p + 1 if low != "**" else p)
            left = E("binop", low, [left, right])

    def primary(self):
        kind, v = self.take()
        if kind is None:
            raise TranslateError(f"expression ends early: {self.text!r}")
        low = v.lower()
        if kind == "real":
            return E("real", v)
        if kind == "num":
            return E("num", v.split("_")[0])
        if kind == "dotop" and low in (".true.", ".false."):
            return E("logical", low)
        if kind == "str":
            return E("str", v)
        if v == "(":
            e = self.expr(0)
            self.take(")")
            return E("paren", "", [e])
        if v == "[" or v == "(/":
            items = []
            close = "]" if v == "[" else "/)"
            while self.peek()[1] != close:
                items.append(self.expr(0))
                if self.peek()[1] == ",":
                    self.take()
            self.take(close)
            return E("arrayc", "", items)
        if kind == "name":
            node = E("name", v)
            while True:
                if self.peek()[1] == "(":
                    self.take()
                    args = []
                    while self.peek()[1] != ")":
                        args.append(self.arg())
                        if self.peek()[1] == ",":
                            self.take()
                    self.take(")")
                    node = E("call", "", [node] + args)
                elif self.peek()[1] == "%":
                    self.take()
                    _, comp = self.take()
                    node = E("member", comp, [node])
                else:
                    return node
        raise TranslateError(f"unexpected {v!r} in {self.text!r}")

    def arg(self):
        """An argument: an expression, a section l:u[:s], or name=value."""
        kind, v = self.peek()
        if kind == "name" and self.i + 1 < len(self.toks) and \
                self.toks[self.i + 1][1] == "=":
            self.take()
            self.take()
            return E("kwarg", v.lower(), [self.expr(0)])
        parts: list = []
        cur = None if self.peek()[1] == ":" else self.expr(0)
        if self.peek()[1] != ":":
            return cur
        parts.append(cur)
        while self.peek()[1] == ":":
            self.take()
            parts.append(None if self.peek()[1] in (":", ",", ")")
                         else self.expr(0))
        return E("section", "", parts)


def parse_expr(text: str) -> E:
    return _EParser(text).parse()


# --- symbols --------------------------------------------------------------------

@dataclass
class Var:
    name: str
    ftype: str            # integer, logical, double, c_ptr, depend, alloc,
                          # alloctrait, struct:<t>, character
    dims: list = field(default_factory=list)  # Fortran extents (texts)
    attrs: set = field(default_factory=set)
    init: str | None = None
    intent: str | None = None
    deferred: bool = False  # (:) shape


_TYPE = re.compile(r"^(integer|logical|double\s*precision|real|character"
                   r"|type|class)\b\s*(\([^)]*\))?\s*(.*)$", re.I)


def _split_top(text: str, sep: str = ",") -> list[str]:
    out, cur, depth, q = [], "", 0, None
    for ch in text:
        if q:
            q = None if ch == q else q
        elif ch in "'\"":
            q = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == sep and depth == 0:
            out.append(cur.strip())
            cur = ""
            continue
        cur += ch
    out.append(cur.strip())
    return [x for x in out if x]


def parse_declaration(stmt: str) -> list[Var] | None:
    m = _TYPE.match(stmt.strip())
    if not m or "::" not in stmt or re.match(r"^type\s*::", stmt.strip(),
                                             re.I):
        return None
    base, kind_sel, _ = m.groups()
    spec, ents = stmt.split("::", 1)
    attrs_text = _split_top(spec)[1:]
    b = base.lower().replace(" ", "")
    ks = (kind_sel or "").strip("() ").lower()
    if b == "integer":
        ftype = {"": "integer", "omp_depend_kind": "depend",
                 "omp_allocator_handle_kind": "alloc"}.get(ks)
        if ftype is None:
            raise TranslateError(f"integer kind {ks!r}")
    elif b == "logical":
        ftype = "logical"
    elif b in ("doubleprecision",):
        ftype = "double"
    elif b == "character":
        raise TranslateError("character variables are Fortran-only here")
    elif b == "type":
        t = ks
        ftype = {"c_ptr": "c_ptr", "omp_alloctrait": "alloctrait"}.get(
            t, f"struct:{t}")
    else:
        raise TranslateError(f"type {b!r} is not ported")
    attrs, dims, intent = set(), [], None
    for a in attrs_text:
        al = a.lower()
        if al.startswith("intent"):
            intent = re.search(r"\((\w+)\)", al).group(1)
        elif al.startswith("dimension"):
            dims = _split_top(re.search(r"\((.*)\)", a).group(1))
        else:
            attrs.add(al)
    out = []
    for ent in _split_top(ents):
        mm = re.match(r"^([A-Za-z_]\w*)\s*(\((.*?)\))?\s*(?:=\s*(.*))?$",
                      ent.strip(), re.S)
        if not mm:
            raise TranslateError(f"entity {ent!r}")
        d = _split_top(mm.group(3)) if mm.group(2) else list(dims)
        deferred = bool(d) and all(x == ":" for x in d)
        out.append(Var(mm.group(1), ftype, [] if deferred else d,
                       set(attrs), mm.group(4), intent, deferred))
    return out


# --- C expression emission ------------------------------------------------------

_INTRINSIC_BIN = {"iand": "&", "ior": "|", "ieor": "^"}
_OMP_FUNCS = re.compile(r"^(omp|acc)_\w+$")  # The OpenACC API
_REDOP = {".and.": "&&", ".or.": "||", "iand": "&", "ior": "|", "ieor": "^"}


def _simplify_minus_one(text: str) -> str:
    """text - 1, folding an integer literal or a trailing + k."""
    t = text.strip()
    if re.fullmatch(r"-?\d+", t):
        return str(int(t) - 1)
    m = re.fullmatch(r"(.*\S)\s*\+\s*(\d+)", t)
    if m and _balanced(m.group(1)):
        k = int(m.group(2)) - 1
        return m.group(1) if k == 0 else f"{m.group(1)} + {k}"
    m = re.fullmatch(r"(.*\S)\s*-\s*(\d+)", t)
    if m and _balanced(m.group(1)):
        return f"{m.group(1)} - {int(m.group(2)) + 1}"
    return f"{t} - 1"


def _balanced(t: str) -> bool:
    d = 0
    for ch in t:
        d += ch in "(["
        d -= ch in ")]"
        if d < 0:
            return False
    return d == 0


class Ctx:
    """The symbols visible to a statement: name -> Var (innermost wins),
    and the derived types' components."""

    def __init__(self, scopes: list[dict], functions: dict, tr):
        self.scopes = scopes
        self.functions = functions
        self.tr = tr

    def var(self, name: str) -> Var | None:
        low = name.lower()
        for s in reversed(self.scopes):
            if low in s:
                return s[low]
        return None

    def of(self, e: "E") -> Var | None:
        """The Var of a name or component designator (no subscripts)."""
        if e.kind == "name":
            return self.var(e.value)
        if e.kind == "member":
            base = self.of(e.args[0])
            if base is None or not base.ftype.startswith("struct:"):
                return None
            comps = self.tr.types.get(base.ftype[7:], {})
            return comps.get(e.value.lower())
        return None


class Emitter:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    # shapes ------------------------------------------------------------------
    def shape(self, e: E) -> list[str]:
        """Extents (C texts) of an array-valued expression, [] if scalar."""
        k = e.kind
        if k == "name":
            v = self.ctx.var(e.value)
            return list(self.extents(v)) if v and (v.dims or v.deferred) \
                else []
        if k == "paren":
            return self.shape(e.args[0])
        if k == "unop":
            return self.shape(e.args[0])
        if k == "binop":
            return self.shape(e.args[0]) or self.shape(e.args[1])
        if k == "member":
            v = self.ctx.of(e)
            return [self.c(parse_expr(d)) for d in v.dims] if v and v.dims \
                else []
        if k == "call":
            head = e.args[0]
            if head.kind in ("name", "member"):
                v = self.ctx.of(head)
                if v is not None and (v.dims or v.deferred):
                    out = []
                    for a in e.args[1:]:
                        if a.kind == "section":
                            lo, hi = a.args[0], a.args[1] if len(a.args) > 1 \
                                else None
                            lo_t = self.c(lo) if lo else "1"
                            hi_t = self.c(hi) if hi else "?"
                            out.append(_extent(lo_t, hi_t))
                    return out
                fn = head.value.lower()
                if fn == "sum" and any(a.kind == "kwarg" for a in e.args[1:]):
                    full = self.shape(e.args[1])
                    dim = int(next(a for a in e.args[1:]
                                   if a.kind == "kwarg").args[0].value)
                    return [x for j, x in enumerate(full) if j != dim - 1]
                if fn in ("merge", "max", "min", "mod", "abs"):
                    for a in e.args[1:]:
                        s = self.shape(a)
                        if s:
                            return s
            return []
        return []

    def extents(self, v: Var) -> list[str]:
        if v.deferred:
            ext = self.ctx.tr.allocated.get(v.name.lower())
            if ext is None:
                raise TranslateError(f"extent of {v.name} unknown")
            return ext
        return [self.c(parse_expr(d)) for d in v.dims]

    # scalar emission ----------------------------------------------------------
    def c(self, e: E, idx: list[str] | None = None) -> str:
        """C text of `e`; for an array-valued expression, its element at
        the 0-based index texts `idx`."""
        k = e.kind
        if k == "num":
            return e.value
        if k == "real":
            return re.sub(r"[dD]", "e", e.value).replace("e0", "") \
                if not re.search(r"[dD][+-]?[1-9]", e.value) else \
                re.sub(r"[dD]", "e", e.value)
        if k == "logical":
            return "true" if e.value == ".true." else "false"
        if k == "str":
            body = e.value[1:-1].replace("''", "'")
            return '"' + body.replace('"', '\\"') + '"'
        if k == "paren":
            return f"({self.c(e.args[0], idx)})"
        if k == "name":
            v = self.ctx.var(e.value)
            name = e.value
            if v is not None and (v.dims or v.deferred) and idx is not None:
                return name + "".join(f"[{i}]" for i in idx)
            if v is not None and v.intent in ("inout", "out") and \
                    not v.dims and not v.deferred:
                return f"(*{name})"
            return name
        if k == "member":
            v = self.ctx.of(e)
            text = f"{self.c(e.args[0])}.{e.value}"
            if v is not None and v.dims and idx is not None:
                return text + "".join(f"[{i}]" for i in idx)
            return text
        if k == "unop":
            op = {".not.": "!", "-": "-", "+": "+"}[e.value]
            inner = e.args[0]
            t = self.c(inner, idx)
            if inner.kind == "binop":
                t = f"({t})"
            return f"{op}{t}"
        if k == "binop":
            return self.binop(e, idx)
        if k == "call":
            return self.call(e, idx)
        if k == "arrayc":
            return "{" + ", ".join(self.c(a) for a in e.args) + "}"
        raise TranslateError(f"cannot emit {e.kind}")

    _PREC = {"||": 1, "&&": 2, "==": 4, "!=": 4, "<": 5, "<=": 5, ">": 5,
             ">=": 5, "+": 6, "-": 6, "*": 7, "/": 7}

    def binop(self, e: E, idx) -> str:
        op = e.value
        if op == "**":
            raise TranslateError("** is not ported")
        cop = {".and.": "&&", ".or.": "||", ".eqv.": "==", ".neqv.": "!=",
               "/=": "!="}.get(op, op)
        p = self._PREC[cop]
        parts = []
        for side, a in enumerate(e.args):
            t = self.c(a, idx)
            if a.kind == "binop":
                ap = self._PREC.get({".and.": "&&", ".or.": "||",
                                     ".eqv.": "==", ".neqv.": "!=",
                                     "/=": "!="}.get(a.value, a.value), 9)
                if ap < p or (ap == p and side == 1 and cop in "-/") or (
                        cop in ("&&", "||", "==", "!=") and ap != p
                        and ap <= 5):
                    t = f"({t})"
            parts.append(t)
        return f"{parts[0]} {cop} {parts[1]}"

    def call(self, e: E, idx) -> str:
        head, args = e.args[0], e.args[1:]
        if head.kind == "member":
            v = self.ctx.of(head)
            if v is not None and v.dims:
                return self.element(e, idx)
        if head.kind != "name":
            raise TranslateError("call of a non-name")
        name = head.value
        low = name.lower()
        v = self.ctx.var(name)
        if v is not None and (v.dims or v.deferred):
            return self.element(e, idx)
        if low == "merge":
            a, b, c = args
            return f"({self.c(c, idx)} ? {self.c(a, idx)} : {self.c(b, idx)})"
        if low == "mod":
            # An operand with an operator keeps its own parentheses
            # (mod(7*s + j, m) is (7*s + j) % m, not 7*s + j % m)
            x = _paren(self.c(args[0], idx))
            y = _paren(self.c(args[1], idx), right=True)
            return f"({x} % {y})"
        if low in ("max", "min"):
            x, y = (self.c(a, idx) for a in args)
            op = ">" if low == "max" else "<"
            return f"({x} {op} {y} ? {x} : {y})"
        if low in _INTRINSIC_BIN:
            x, y = (self.c(a, idx) for a in args)
            return f"({x} {_INTRINSIC_BIN[low]} {y})"
        if low == "abs":
            x = self.c(args[0], idx)
            return f"({x} < 0 ? -({x}) : {x})"
        if low == "c_loc":
            a = args[0]
            if a.kind == "name":
                av = self.ctx.var(a.value)
                if av is not None and (av.dims or av.deferred):
                    return a.value
                return f"&{a.value}"
            return f"&{self.c(a)}"
        if low == "c_associated":
            return f"({self.c(args[0])} == {self.c(args[1])})"
        if low == "omp_alloctrait":
            return "{" + ", ".join(self.c(a) for a in args) + "}"
        if low in ("all", "any", "count", "sum"):
            return self.ctx.tr.lift(e, self)
        if low == "acc_is_present" and len(args) == 1 and \
                args[0].kind == "name":
            # The Fortran form takes the variable (3.4 §3.2.30);
            # the C form its address and size in bytes
            a = args[0].value
            av = self.ctx.var(a)
            if av is not None and "pointer" in av.attrs and \
                    (av.dims or av.deferred):
                ext = self.ctx.tr.allocated.get(a.lower())
                if ext is None:
                    raise TranslateError(f"extent of pointer {a}")
                return f"acc_is_present({a}, ({ext[0]}) * sizeof(*{a}))"
            if av is not None and (av.dims or av.deferred):
                return f"acc_is_present({a}, sizeof({a}))"
            return f"acc_is_present(&{a}, sizeof({a}))"
        if _OMP_FUNCS.match(low) or low in self.ctx.functions:
            fn = self.ctx.functions.get(low)
            out = []
            for k, a in enumerate(args):
                t = self.c(a, idx)
                if fn is not None and k < len(fn) and fn[k] in ("inout",
                                                                "out"):
                    t = "&" + t if not t.startswith("(*") else t[2:-1]
                out.append(t)
            return f"{name}({', '.join(out)})"
        raise TranslateError(f"unknown function {name!r}")

    def element(self, e: E, idx) -> str:
        """An array reference a(...) (element, or element `idx` of a
        section)."""
        head, args = e.args[0], e.args[1:]
        v = self.ctx.of(head)
        subs = []
        k = 0
        for a in args:
            if a.kind == "section":
                lo = self.c(a.args[0]) if a.args[0] is not None else "1"
                if idx is None:
                    raise TranslateError("section in a scalar context")
                base = _simplify_minus_one(lo)
                subs.append(idx[k] if base == "0" else f"{base} + {idx[k]}")
                k += 1
            else:
                subs.append(_simplify_minus_one(self.c(a, None if not
                                                       self.shape(a)
                                                       else idx)))
        name = self.c(head) if head.kind == "member" else head.value
        if v is not None and v.intent in ("inout", "out") and not v.dims:
            name = f"(*{name})"
        return name + "".join(f"[{s}]" for s in subs)

    # clause items ---------------------------------------------------------------
    def item(self, text: str, mapping: bool = False) -> str:
        """A list item of a clause: x, x(i), x(l:u), s%c."""
        e = parse_expr(text)
        if e.kind == "name":
            v = self.ctx.var(e.value)
            if mapping and v is not None and "pointer" in v.attrs and \
                    (v.dims or v.deferred):
                ext = self.ctx.tr.allocated.get(v.name.lower())
                if ext is None:
                    raise TranslateError(f"extent of pointer {v.name}")
                return f"{v.name}[0:{ext[0]}]"
            if mapping and v is not None and v.intent in ("inout", "out") \
                    and not v.dims and not v.deferred:
                # A scalar dummy passed by reference is a pointer
                # in C: map its pointee (the Fortran dummy's storage)
                return f"{e.value}[0:1]"
            return e.value
        if e.kind == "member":
            return self.c(e)
        if e.kind == "call" and e.args[0].kind in ("name", "member"):
            v = self.ctx.of(e.args[0])
            if v is None or not (v.dims or v.deferred):
                raise TranslateError(f"list item {text!r}")
            subs = []
            for a in e.args[1:]:
                if a.kind == "section":
                    lo = self.c(a.args[0]) if a.args[0] is not None else "1"
                    hi = self.c(a.args[1]) if len(a.args) > 1 and \
                        a.args[1] is not None else None
                    if hi is None:
                        hi = self.extents(v)[len(subs)]
                    start = _simplify_minus_one(lo)
                    length = _extent(lo, hi)
                    st = f":{self.c(a.args[2])}" if len(a.args) > 2 and \
                        a.args[2] is not None else ""
                    subs.append(f"{start}:{length}{st}")
                else:
                    subs.append(_simplify_minus_one(self.c(a)))
            return self.c(e.args[0]) + "".join(f"[{s}]" for s in subs)
        raise TranslateError(f"list item {text!r}")


def _extent(lo: str, hi: str) -> str:
    """hi - lo + 1, folded where both are literals or lo is 1."""
    if re.fullmatch(r"-?\d+", lo) and re.fullmatch(r"-?\d+", hi):
        return str(int(hi) - int(lo) + 1)
    if lo.strip() == "1":
        return hi
    if lo.strip() == hi.strip():
        return "1"  # A one-element section a(i:i)
    m = re.fullmatch(r"(.+?)\s*-\s*(\d+)", hi)
    if re.fullmatch(r"\d+", lo) and m:
        return f"{m.group(1)} - {int(m.group(2)) + int(lo) - 1}"
    return f"{hi} - ({lo}) + 1" if not re.fullmatch(r"\w+", lo) \
        else f"{hi} - {lo} + 1"


# --- program structure ------------------------------------------------------------

@dataclass
class Node:
    kind: str                 # stmt, do, while, if, dir, ifone
    text: str = ""
    body: list = field(default_factory=list)
    orelse: list = field(default_factory=list)
    end_clauses: str = ""     # clauses of a paired end directive
    directive: object = None  # grammar.Directive of a dir node
    line: str = ""            # the directive's full text


@dataclass
class Unit:
    kind: str                 # module, program, function, subroutine
    name: str
    params: list = field(default_factory=list)
    spec: list = field(default_factory=list)   # (kind, text)
    body: list = field(default_factory=list)   # (kind, text)
    procs: list = field(default_factory=list)  # module procedures
    result_type: str = ""


_PROC_HEAD = re.compile(r"^(?:(integer|logical)\s+)?(function|subroutine)\s+"
                        r"([a-z_]\w*)\s*\(([^)]*)\)\s*$", re.I)
_END_UNIT = re.compile(r"^end\s*(module|program|function|subroutine)\b", re.I)
_SPEC_STMT = re.compile(r"^(use\b|implicit\b|integer\b|logical\b|double\s*"
                        r"precision\b|type\b|character\b|real\b)", re.I)


def _is_spec(kind: str, text: str, in_type: bool) -> bool:
    """A line of a specification part: USE, IMPLICIT, a type declaration,
    a derived-type definition line, or a declarative directive."""
    low = text.lower().strip()
    if in_type:
        return True
    if kind == "omp":
        try:
            d = parse_directive(text, "fortran", _VERSION[0])
        except GrammarError as err:
            raise TranslateError(f"directive {text!r}: {err}") from err
        return d.name in ("declare target", "requires", "threadprivate",
                          "declare mapper", "declare reduction",
                          "declare simd", "error", "declare", "routine")
    return bool(re.match(r"^(use\b|implicit\b|type\s*::|type\s*\(|"
                         r"(integer|logical|double\s*precision|real|"
                         r"character)\b)", low))


def _units(lines) -> list[Unit]:
    units: list[Unit] = []
    stack: list[Unit] = []
    in_exec: dict[int, bool] = {}
    in_type: dict[int, bool] = {}
    for kind, text in lines:
        if kind == "head":
            continue
        low = text.lower().strip()
        if kind == "stmt":
            m = re.match(r"^(module|program)\s+(\w+)$", low)
            if m and not stack:
                u = Unit(m.group(1), m.group(2))
                units.append(u)
                stack.append(u)
                continue
            m = _PROC_HEAD.match(text.strip())
            if m and not stack:
                # An external procedure (the OpenACC programs'
                # routine and bind recipes), a function at file scope
                u = Unit(m.group(2).lower(), m.group(3).lower(),
                         [p.strip().lower() for p in m.group(4).split(",")
                          if p.strip()],
                         result_type=(m.group(1) or "").lower())
                units.append(u)
                stack.append(u)
                continue
            if m and stack:
                u = Unit(m.group(2).lower(), m.group(3).lower(),
                         [p.strip().lower() for p in m.group(4).split(",")
                          if p.strip()],
                         result_type=(m.group(1) or "").lower())
                stack[-1].procs.append(u)
                stack.append(u)
                continue
            if low == "contains":
                in_exec[id(stack[-1])] = True
                continue
            if _END_UNIT.match(low):
                stack.pop()
                continue
        if not stack:
            raise TranslateError(f"statement outside a unit: {text!r}")
        u = stack[-1]
        if not in_exec.get(id(u)) and _is_spec(kind, text,
                                                in_type.get(id(u), False)):
            if kind == "stmt" and re.match(r"^type\s*::", low):
                in_type[id(u)] = True
            elif kind == "stmt" and re.match(r"^end\s*type\b", low):
                in_type[id(u)] = False
            u.spec.append((kind, text))
            continue
        in_exec[id(u)] = True
        u.body.append((kind, text))
    return units


_VERSION = [52]
# The model of the program being translated (omp, or acc for an
# OpenACC 3.4 program: !$acc -> #pragma acc)
_MODEL = ["omp"]


def _tree(lines, version) -> list[Node]:
    """Nodes of an executable part."""
    from offload.engine.rules import association
    root: list[Node] = []
    stack: list[tuple[Node, list]] = []  # (node, the list it fills)

    def cur() -> list:
        return stack[-1][1] if stack else root

    pending_loop: list[Node] = []  # loop/statement directives awaiting body
    k = 0
    lines = list(lines)
    while k < len(lines):
        kind, text = lines[k]
        k += 1
        low = text.lower().strip()
        if kind == "omp":
            try:
                d = parse_directive(text, "fortran", version)
            except GrammarError as err:
                raise TranslateError(f"directive {text!r}: {err}") from err
            if d.end:
                # the end of the innermost open block directive, or of the
                # loop/statement directive that just closed
                last = cur()[-1] if cur() else None
                if stack and stack[-1][0].kind == "dir" and \
                        stack[-1][0].directive.name == d.name:
                    node = stack.pop()[0]
                    node.end_clauses = _clause_text(text)
                    continue
                if last is not None and last.kind == "dir" and \
                        last.directive.name == d.name:
                    last.end_clauses = _clause_text(text)
                    continue
                raise TranslateError(f"unpaired end directive {text!r}")
            node = Node("dir", directive=d, line=text)
            how = association(d.name, _MODEL[0])
            if _MODEL[0] == "acc" and d.name == "atomic" and any(
                    kk == "omp" and re.match(r"^!\$acc\s+end\s*atomic\b",
                                             tt.strip(), re.I)
                    for kk, tt in lines[k:k + 3]):
                # An OpenACC atomic capture of two statements
                # closed by end atomic: in C, a structured block
                # (3.4 §2.12, p.81)
                how = "block"
                node.text = "block"
            cur().append(node)
            if how == "block":
                stack.append((node, node.body))
            elif how in ("loop", "statement"):
                pending_loop.append(node)
                stack.append((node, node.body))
                node.text = "pending"
            continue
        # statements
        if re.match(r"^do\s+while\s*\(", low):
            node = Node("while", text=re.match(r"^do\s+while\s*\((.*)\)$",
                                               text.strip(), re.I).group(1))
            cur().append(node)
            stack.append((node, node.body))
            continue
        m = re.match(r"^do\s+([a-z_]\w*)\s*=\s*(.*)$", low)
        if m:
            node = Node("do", text=text.strip()[2:].strip())
            cur().append(node)
            stack.append((node, node.body))
            continue
        if re.match(r"^end\s*do$", low):
            while stack and stack[-1][0].kind not in ("do", "while"):
                raise TranslateError(f"end do inside {stack[-1][0].kind}")
            stack.pop()
            _close_pending(stack)
            continue
        m = re.match(r"^if\s*\((.*)\)\s*then$", text.strip(), re.I)
        if m and _balanced(m.group(1)):
            node = Node("if", text=m.group(1))
            cur().append(node)
            stack.append((node, node.body))
            continue
        if re.match(r"^else\s*if\b", low):
            raise TranslateError("else if is not ported")
        if low == "else":
            node = stack[-1][0]
            stack[-1] = (node, node.orelse)
            continue
        if re.match(r"^end\s*if$", low):
            stack.pop()
            _close_pending(stack)
            continue
        cond_rest = _if_parts(text.strip())
        if cond_rest is not None:
            cur().append(Node("ifone", text=cond_rest[0],
                              body=[Node("stmt", text=cond_rest[1])]))
            _close_pending(stack)
            continue
        cur().append(Node("stmt", text=text.strip()))
        _close_pending(stack)
    if stack:
        raise TranslateError(f"unclosed {stack[-1][0].kind}")
    return root


def _if_parts(text: str):
    """(condition, statement) of a one-line logical IF, else None."""
    m = re.match(r"^if\s*\(", text, re.I)
    if not m:
        return None
    depth = 0
    for j in range(m.end() - 1, len(text)):
        depth += text[j] == "("
        depth -= text[j] == ")"
        if depth == 0:
            rest = text[j + 1:].strip()
            if not rest or rest.lower() == "then":
                return None
            return text[m.end():j], rest
    return None


def _close_pending(stack):
    """Close loop/statement directives whose one associated construct is
    complete."""
    while stack and stack[-1][0].kind == "dir" and \
            stack[-1][0].text == "pending" and stack[-1][0].body:
        node = stack.pop()[0]
        node.text = ""


def _clause_text(line: str) -> str:
    """The clauses of a directive line (after the directive name)."""
    d_text = line.strip()[5:].strip()
    return _split_name(d_text)[1]


def _split_name(text: str) -> tuple[str, str]:
    """(directive name as written, with its parenthesised argument if any;
    clause text) of a directive without its sentinel: the longest prefix
    of words that the grammar reads as the directive (or end directive)
    name."""
    cuts = sorted({m.start() for m in re.finditer(r"[ (]", text)}
                  | {len(text)}, reverse=True)
    for cut in cuts:
        head = text[:cut].strip()
        if not head or "(" in head:
            continue
        try:
            d = parse_directive(f"!${_MODEL[0]} " + head, "fortran",
                                _VERSION[0])
            if d.clauses:
                continue
        except GrammarError as err:
            if err.code != "missing_required":
                continue
        rest = text[cut:].strip()
        if rest.startswith("("):  # a directive argument: keep with the name
            depth = 0
            for j, ch in enumerate(rest):
                depth += ch == "("
                depth -= ch == ")"
                if depth == 0:
                    break
            head += rest[:j + 1]
            rest = rest[j + 1:].strip()
        return head, rest
    raise TranslateError(f"no directive name in {text!r}")


# --- the translator -------------------------------------------------------------

_CTYPE = {"integer": "int", "logical": "bool", "double": "double",
          "c_ptr": "void *", "depend": "omp_depend_t",
          "alloc": "omp_allocator_handle_t",
          "alloctrait": "omp_alloctrait_t"}
_KEYWORDS = {
    "to", "from", "tofrom", "alloc", "release", "delete", "present",
    "always", "close", "self", "storage", "ref_ptee", "ref_ptr",
    "ref_ptr_ptee", "static", "dynamic", "guided", "auto", "runtime",
    "monotonic", "nonmonotonic", "simd", "inscan", "task", "default",
    "conditional", "concurrent", "reproducible", "unconstrained", "in", "out",
    "inout", "inoutset", "mutexinoutset", "depobj", "ancestor", "device_num",
    "any", "host", "nohost", "primary", "master", "spread", "seq_cst",
    "acq_rel", "acquire", "relaxed", "none", "shared", "private",
    "firstprivate", "scalar", "aggregate", "pointer", "all", "parallel",
    "teams", "thread", "val", "strict", "saved", "automap", "fatal",
    "warning", "max", "min", "+", "-", "*", "compilation", "execution",
    "omp_all_memory"}
_COMPLEX = re.compile(r"^(mapper|traits|memspace|allocator|align|step|"
                      r"original)\s*\((.*)\)$", re.I | re.S)
_REDUCTION_CLAUSES = {"reduction", "in_reduction", "task_reduction"}
# clauses whose pieces are never directive names (only list items)
_LIST_ONLY = {"shared", "private", "firstprivate", "lastprivate"}


def _directive_names() -> frozenset:
    from offload.engine.catalog import default_grammar, default_skeleton
    if not _DNAMES:
        sk, g = default_skeleton(), default_grammar()
        _DNAMES.update(s.text for d in sk.directives.values()
                       for s in d.spellings)
        _DNAMES.update(e.spelling for e in g.spellings)
    return frozenset(_DNAMES)


_DNAMES: set = set()
_MAP_CLAUSES = {"map", "to", "from"}
# The OpenACC data clauses (a pointer list item is mapped as the
# array section of its pointee, as in a map clause)
_ACC_DATA_CLAUSES = {"copy", "copyin", "copyout", "create", "present",
                     "no_create", "delete", "attach", "detach", "deviceptr",
                     "device_resident", "link", "self", "host", "device",
                     "use_device", "pcopy", "pcopyin", "pcopyout",
                     "pcreate"}


class Translator:
    def __init__(self, source: str, version: int):
        from offload.engine.catalog import model_of
        _VERSION[0] = version
        _MODEL[0] = model_of(version)
        self.model = _MODEL[0]
        self.version = version
        self.lines = logical_lines(source)
        self.allocated: dict[str, list[str]] = {}
        self.ntmp = 0
        self.pre: list[str] = []
        self.needs_stdlib = False
        self.functions: dict[str, list] = {}  # name -> intents of dummies
        self.file_scope: list[str] = []
        self.clause_names: set[str] = set()
        self._raw_alloc: dict[str, list[str]] = {}
        self.types: dict[str, dict] = {}

    # ---- helpers ----
    def fresh(self, stem: str) -> str:
        self.ntmp += 1
        return f"{stem}{self.ntmp}_"

    def lift(self, e: E, em: "Emitter") -> str:
        """A reduction intrinsic (all/any/count/sum) as a temporary computed
        by loops in self.pre; returns its name."""
        fn = e.args[0].value.lower()
        args = e.args[1:]
        if any(a.kind == "kwarg" for a in args):
            raise TranslateError(f"{fn} with dim= outside all()")
        arg = args[0]
        shp = em.shape(arg)
        if not shp:
            raise TranslateError(f"{fn} of a scalar")
        t = self.fresh("t")
        init, upd = {
            "all": ("bool", "true", "{t} = {t} && ({x});"),
            "any": ("bool", "false", "{t} = {t} || ({x});"),
            "count": ("int", "0", "if ({x}) {t}++;"),
            "sum": ("int", "0", "{t} += {x};"),
        }[fn][0:2], {"all": "{t} = {t} && ({x});",
                     "any": "{t} = {t} || ({x});",
                     "count": "if ({x}) {t}++;",
                     "sum": "{t} += {x};"}[fn]
        idx = [self.fresh("k") for _ in shp]
        body = self.elements(arg, em, idx)
        self.pre.append(f"{init[0]} {t} = {init[1]};")
        self.pre += _loops(shp, idx, [upd.format(t=t, x=body)])
        return t

    def elements(self, e: E, em: "Emitter", idx: list[str]) -> str:
        """Element text of an array-valued expression at `idx`, with sum(...,
        dim=) parts precomputed into temporaries."""
        e = self._presum(e, em)
        return em.c(e, idx)

    def _presum(self, e: E, em: "Emitter") -> E:
        if e.kind == "call" and e.args[0].kind == "name" and \
                e.args[0].value.lower() == "sum" and any(
                    a.kind == "kwarg" for a in e.args[1:]):
            arr = e.args[1]
            dim = int(next(a for a in e.args[1:]
                           if a.kind == "kwarg").args[0].value)
            full = em.shape(arr)
            keep = [x for j, x in enumerate(full) if j != dim - 1]
            t = self.fresh("t")
            idx = [self.fresh("k") for _ in full]
            out_idx = [x for j, x in enumerate(idx) if j != dim - 1]
            decl = f"int {t}" + "".join(f"[{x}]" for x in keep) + ";"
            self.pre.append(decl)
            self.pre += _loops(keep, out_idx,
                               [f"{t}{''.join(f'[{x}]' for x in out_idx)}"
                                " = 0;"])
            self.pre += _loops(full, idx, [
                f"{t}{''.join(f'[{x}]' for x in out_idx)} += "
                f"{em.c(arr, idx)};"])
            em.ctx.scopes[-1][t] = Var(t, "integer", keep)
            return E("name", t)
        if e.args:
            e = E(e.kind, e.value, [self._presum(a, em) if isinstance(a, E)
                                     else a for a in e.args])
        return e

    # ---- symbols ----
    def declare(self, scope: dict, spec: list) -> list[tuple]:
        """Fill `scope` from a specification part; returns the derived types
        [(name, [Var])] it defines."""
        types, cur = [], None
        for kind, text in spec:
            if kind != "stmt":
                continue
            low = text.lower().strip()
            m = re.match(r"^type\s*::\s*(\w+)$", low)
            if m:
                cur = (m.group(1), [])
                types.append(cur)
                continue
            if re.match(r"^end\s*type\b", low):
                cur = None
                continue
            if low.startswith(("use", "implicit")):
                continue
            vs = parse_declaration(text)
            if vs is None:
                raise TranslateError(f"declaration {text!r}")
            for v in vs:
                if cur is not None:
                    cur[1].append(v)
                else:
                    scope[v.name.lower()] = v
        return types

    def c_decl(self, v: Var, em: Emitter, static: bool = False) -> str:
        if "external" in v.attrs:
            return ""  # An external function, defined before main
        if v.ftype.startswith("struct:"):
            base = f"struct {v.ftype[7:]}"
        else:
            base = _CTYPE[v.ftype]
        star = ""
        if "pointer" in v.attrs and (v.dims or v.deferred):
            star = "*"
            dims = []
        elif v.deferred:
            dims = self.allocated.get(v.name.lower())
            if dims is None:
                raise TranslateError(f"{v.name} is never allocated")
        else:
            dims = [em.c(parse_expr(d)) for d in v.dims]
        if base.endswith("*"):
            text = f"{base}{v.name}"
        else:
            text = f"{base} {star}{v.name}"
        text += "".join(f"[{d}]" for d in dims)
        if v.init is not None:
            init = parse_expr(v.init)
            text += " = " + em.c(init)
        if "parameter" in v.attrs and v.ftype != "integer":
            text = "const " + text
        return ("static " if static else "") + text + ";"

    # ---- statements ----
    def stmt(self, text: str, em: Emitter) -> list[str]:
        """C lines of one Fortran statement (with lifted temporaries)."""
        self.pre = []
        low = text.lower().strip()
        out: list[str]
        if low.startswith("print"):
            if "result ran_on_host=" not in low:
                raise TranslateError(f"print {text!r}")
            out = ['printf("RESULT ran_on_host=%d check=%s\\n", host_flag, '
                   'ok ? "pass" : "fail");']
        elif low.startswith(("allocate(", "allocate (")):
            out = []
            for it in _split_top(re.match(r"^allocate\s*\((.*)\)$", text.strip(),
                                         re.I).group(1)):
                name = it.split("(")[0].strip().lower()
                v = em.ctx.var(name)
                if v is not None and "pointer" in v.attrs:
                    self.needs_stdlib = True
                    ext = self.allocated[name]
                    size = " * ".join(ext)
                    out.append(f"{name} = malloc({size} * sizeof *{name});")
        elif low.startswith(("deallocate(", "deallocate (")):
            out = []
            for it in _split_top(re.match(r"^deallocate\s*\((.*)\)$",
                                         text.strip(), re.I).group(1)):
                v = em.ctx.var(it.strip())
                if v is not None and "pointer" in v.attrs:
                    out.append(f"free({it.strip()});")
        elif low.startswith("call "):
            out = self.call_stmt(text.strip()[5:].strip(), em)
        elif low in ("exit", "cycle"):
            out = ["break;" if low == "exit" else "continue;"]
        elif "=>" in text:
            lhs, rhs = (x.strip() for x in text.split("=>", 1))
            out = [f"{lhs} = {em.c(parse_expr(rhs))};"]
        else:
            m = re.match(r"^(.*?[^=<>/])=(?!=)(.*)$", text.strip())
            if not m:
                raise TranslateError(f"statement {text!r}")
            out = self.assign(m.group(1).strip(), m.group(2).strip(), em)
        return self.pre + out

    def assign(self, lhs_t: str, rhs_t: str, em: Emitter) -> list[str]:
        lhs, rhs = parse_expr(lhs_t), parse_expr(rhs_t)
        if em.ctx.tr.result is not None and lhs.kind == "name" and \
                lhs.value.lower() == em.ctx.tr.result:
            return [f"r_ = {em.c(rhs)};"]
        shp = em.shape(lhs)
        if not shp:
            if em.shape(rhs):
                raise TranslateError(f"array value to scalar: {lhs_t}")
            return [f"{em.c(lhs)} = {em.c(rhs)};"]
        idx = [self.fresh("k") for _ in shp]
        rhs_el = self.elements(rhs, em, idx) if em.shape(rhs) else em.c(rhs)
        lhs_el = em.c(lhs, idx)
        return _loops(shp, idx, [f"{lhs_el} = {rhs_el};"])

    def call_stmt(self, text: str, em: Emitter) -> list[str]:
        e = parse_expr(text)
        if e.kind == "name":
            return [f"{e.value}();"]
        name = e.args[0].value.lower()
        args = e.args[1:]
        if name == "c_f_pointer":
            src, dst = em.c(args[0]), args[1].value
            if len(args) > 2:
                self.allocated[dst.lower()] = [em.c(x) for x in args[2].args]
            return [f"{dst} = {src};"]
        return [em.call(e, None) + ";"]

    # ---- directives ----
    @staticmethod
    def c_param(v: "Var", name: str) -> str:
        """A dummy argument: int (intent in or none) or int * (inout, out);
        A type(c_ptr) dummy (the 5.0 is_device_ptr programs) is a
        void * passed by value."""
        if v.dims and v.ftype == "integer":
            return "int *" + name  # An explicit-shape dummy array
        if v.ftype == "c_ptr" and not v.dims:
            if v.intent not in (None, "in"):
                raise TranslateError(f"c_ptr dummy {name} with intent "
                                     f"{v.intent}")
            return "void *" + name
        return ("int " if v.intent in (None, "in") else "int *") + name

    def directive(self, node: Node, em: Emitter) -> str:
        text = node.line.strip()[5:].strip()
        name, clauses = _split_name(text)
        cname = self.c_name(name)
        m = re.match(r"^cache\s*\((.*)\)$", cname, re.I | re.S)
        if self.model == "acc" and m:
            # The cache directive's vars (elements, subarrays)
            inner = m.group(1)
            mod = re.match(r"^\s*(readonly)\s*:\s*", inner, re.I)
            items = _split_top(inner[mod.end():] if mod else inner)
            cname = "cache(" + (f"{mod.group(1)}: " if mod else "") + \
                ", ".join(em.item(x) for x in items) + ")"
        extra = (clauses + " " + node.end_clauses).strip()
        return (f"#pragma {self.model} " + cname + (" " + self.c_clauses(
            extra, em)
                                          if extra else "")).rstrip()

    def c_name(self, name: str) -> str:
        """A directive name (with its argument) in C: do -> for; the
        argument's list items translated."""
        m = re.match(r"^([^(]*)(\((.*)\))?$", name.strip(), re.S)
        words = m.group(1).split()
        if "workdistribute" in [w.lower() for w in words]:
            raise TranslateError("workdistribute is Fortran-only")
        words = ["for" if w.lower() == "do" else w for w in words]
        out = " ".join(words)
        if m.group(2):
            arg = m.group(3)
            if out.lower().replace("_", " ") == "declare mapper":
                # [mapper-identifier :] type :: var -> [id :] struct type var
                mm = re.match(r"^(?:\s*(\w+)\s*:(?!:))?\s*(\w+)\s*::\s*"
                              r"(\w+)\s*$", arg)
                if not mm:
                    raise TranslateError(f"declare mapper({arg})")
                ident = f"{mm.group(1)}: " if mm.group(1) else ""
                arg = f"{ident}struct {mm.group(2)} {mm.group(3)}"
            elif out.lower().replace("_", " ") in ("declare target",
                                                   "threadprivate"):
                arg = ", ".join(_split_top(arg))
            out += "(" + arg + ")"
        return out

    def c_clauses(self, text: str, em: Emitter) -> str:
        from offload.engine.grammar import _close_paren, _tokenize
        toks = _tokenize(text)
        out = []
        i = 0
        while i < len(toks):
            t = toks[i]
            if t.text == ",":
                i += 1
                continue
            if i + 1 < len(toks) and toks[i + 1].text == "(":
                j = _close_paren(toks, i + 1, t.text)
                arg = text[toks[i + 1].end:toks[j].start]
                out.append(f"{t.text}({self.c_arg(t.text.lower(), arg, em)})")
                i = j + 1
            else:
                out.append(t.text)
                i += 1
        return " ".join(out)

    def c_arg(self, clause: str, text: str, em: Emitter) -> str:
        from offload.engine.grammar import _split
        pieces = _split(text, ",:;")
        out = []
        for k, p in enumerate(pieces):
            if k % 2:
                out.append(p + " " if p in ",;" else ": ")
                continue
            out.append(self.c_piece(clause, p, em))
        return "".join(out).replace(" : ", ": ").strip()

    def c_piece(self, clause: str, p: str, em: Emitter) -> str:
        low = p.lower().strip()
        if not low:
            return ""
        if clause in _REDUCTION_CLAUSES and low in _REDOP:
            return _REDOP[low]
        if clause in _REDUCTION_CLAUSES and low in (".eqv.", ".neqv."):
            raise TranslateError(f"reduction identifier {low} is "
                                 "Fortran-only")
        if low == "do":
            return "for"
        if low in _KEYWORDS:
            return low
        if low in _directive_names() and clause not in _LIST_ONLY:
            return " ".join("for" if w == "do" else w for w in low.split())
        m = re.match(r"^iterator\s*\((.*)\)$", p.strip(), re.I | re.S)
        if m:
            return "iterator(" + ", ".join(self.c_iter(s, em) for s in
                                           _split_top(m.group(1))) + ")"
        m = _COMPLEX.match(p.strip())
        if m:
            inner = m.group(2)
            if m.group(1).lower() == "mapper":
                return f"{m.group(1)}({inner.strip()})"
            return f"{m.group(1)}({em.c(parse_expr(inner))})"
        e = parse_expr(p)
        if clause == "uses_allocators" and e.kind == "call" and \
                len(e.args) == 2 and all(a.kind == "name" for a in e.args):
            # The 5.0 form allocator(traits-array) (5.0 §2.12.5)
            return f"{e.args[0].value}({e.args[1].value})"
        if e.kind in ("name", "member") or (
                e.kind == "call" and e.args[0].kind in ("name", "member")
                and em.ctx.of(e.args[0]) is not None):
            return em.item(p, mapping=clause in _MAP_CLAUSES or (
                _MODEL[0] == "acc" and clause in _ACC_DATA_CLAUSES))
        return em.c(e)

    def c_iter(self, spec: str, em: Emitter) -> str:
        m = re.match(r"^(?:(.*?)::)?\s*([a-z_]\w*)\s*=\s*(.*)$", spec.strip(),
                     re.I | re.S)
        if not m:
            raise TranslateError(f"iterator {spec!r}")
        typ = m.group(1)
        if typ and typ.strip().lower() != "integer":
            raise TranslateError(f"iterator type {typ!r}")
        name = m.group(2)
        parts = _split_top(m.group(3), ":")
        em.ctx.scopes.append({name.lower(): Var(name, "integer")})
        try:
            lb, ub = em.c(parse_expr(parts[0])), em.c(parse_expr(parts[1]))
            step = em.c(parse_expr(parts[2])) if len(parts) > 2 else None
        finally:
            em.ctx.scopes.pop()
        neg = step is not None and step.startswith("-")
        end = _simplify_minus_one(ub) if neg else _plus_one(ub)
        return f"{name} = {lb}:{end}" + (f":{step}" if step else "")

    # ---- emission of an executable part ----
    def emit(self, nodes: list[Node], em: Emitter, ind: int) -> list[str]:
        out = []
        pad = "  " * ind
        for node in nodes:
            k = node.kind
            if k == "stmt":
                out += [pad + x for x in self.stmt(node.text, em)]
            elif k == "ifone":
                self.pre = []
                cond = em.c(parse_expr(node.text))
                pre = self.pre
                body = self.stmt(node.body[0].text, em)
                out += [pad + x for x in pre]
                if len(body) == 1:
                    out.append(f"{pad}if ({cond}) {body[0]}")
                else:
                    out.append(f"{pad}if ({cond}) {{")
                    out += [pad + "  " + x for x in body]
                    out.append(pad + "}")
            elif k == "if":
                self.pre = []
                cond = em.c(parse_expr(node.text))
                out += [pad + x for x in self.pre]
                out.append(f"{pad}if ({cond}) {{")
                out += self.emit(node.body, em, ind + 1)
                if node.orelse:
                    out.append(f"{pad}}} else {{")
                    out += self.emit(node.orelse, em, ind + 1)
                out.append(pad + "}")
            elif k == "while":
                self.pre = []
                cond = em.c(parse_expr(node.text))
                if self.pre:
                    raise TranslateError("reduction in a while condition")
                inner = self.emit(node.body, em, ind + 1)
                out.append(f"{pad}while ({cond}) {{" + ("" if inner
                                                         else " }"))
                if inner:
                    out += inner + [pad + "}"]
            elif k == "do":
                out += self.do_loop(node, em, ind)
            elif k == "dir":
                out += self.dir_node(node, em, ind)
            else:
                raise TranslateError(f"node {k}")
        return out

    def do_loop(self, node: Node, em: Emitter, ind: int) -> list[str]:
        pad = "  " * ind
        m = re.match(r"^([a-z_]\w*)\s*=\s*(.*)$", node.text, re.I)
        var = m.group(1)
        parts = _split_top(m.group(2))
        if len(parts) not in (2, 3):
            raise TranslateError(f"do {node.text!r}")
        lb, ub = em.c(parse_expr(parts[0])), em.c(parse_expr(parts[1]))
        decl = "" if var.lower() in self.outer_loop_vars else "int "
        if len(parts) == 3:
            st = em.c(parse_expr(parts[2]))
            if st.startswith("-"):
                head = (f"for ({decl}{var} = {lb}; {var} >= {ub}; "
                        f"{var} -= {st[1:].strip()})")
            else:
                head = f"for ({decl}{var} = {lb}; {var} <= {ub}; {var} += {st})"
        else:
            head = f"for ({decl}{var} = {lb}; {var} <= {ub}; {var}++)"
        inner = self.emit(node.body, em, ind + 1)
        return [f"{pad}{head} {{"] + inner + [pad + "}"]

    def dir_node(self, node: Node, em: Emitter, ind: int) -> list[str]:
        from offload.engine.rules import association
        pad = "  " * ind
        line = self.directive(node, em)
        how = "block" if node.text == "block" else association(
            node.directive.name, self.model)
        out = _wrap_c(pad + line)
        if how == "block":
            inner = self.emit(node.body, em, ind + 1)
            return out + [pad + "{"] + inner + [pad + "}"]
        if how in ("loop", "statement"):
            if not node.body:
                raise TranslateError(f"{node.directive.name} without its "
                                     "loop")
            return out + self.emit(node.body, em, ind)
        return out

    # ---- the whole program ----
    def run(self) -> str:
        head = [t for k, t in self.lines if k == "head"]
        units = _units(self.lines)
        module = next((u for u in units if u.kind == "module"), None)
        prog = next((u for u in units if u.kind == "program"), None)
        externals = [u for u in units if u.kind in ("function",
                                                       "subroutine")]
        if prog is None:
            raise TranslateError("no main program")
        self.result = None
        mod_scope: dict = {}
        prog_scope: dict = {}
        types = []
        if module is not None:
            types += self.declare(mod_scope, module.spec)
        types += self.declare(prog_scope, prog.spec)
        self.types = {t: {v.name.lower(): v for v in members}
                      for t, members in types}
        # extents of allocatable/pointer arrays from ALLOCATE statements
        # (and of a pointer associated with a whole array: p => a)
        for u in ([module] if module else []) + [prog] + (
                module.procs if module else []):
            for kind, text in u.body:
                pm = re.match(r"^(\w+)\s*=>\s*(\w+)$", text.strip())
                if kind == "stmt" and pm:
                    tgt = (prog_scope.get(pm.group(2).lower())
                           or mod_scope.get(pm.group(2).lower()))
                    if tgt is not None and (tgt.dims or tgt.deferred):
                        self.allocated[pm.group(1).lower()] = \
                            tgt.dims or self._raw_alloc.get(
                                pm.group(2).lower(), [])
                m = re.match(r"^allocate\s*\((.*)\)$", text.strip(), re.I)
                if kind == "stmt" and m:
                    for it in _split_top(m.group(1)):
                        mm = re.match(r"^(\w+)\s*\((.*)\)$", it.strip())
                        self.allocated[mm.group(1).lower()] = _split_top(
                            mm.group(2))
                        self._raw_alloc[mm.group(1).lower()] = _split_top(
                            mm.group(2))
        # C texts of the extents
        ctx0 = Ctx([mod_scope, prog_scope], self.functions, self)
        em0 = Emitter(ctx0)
        self.allocated = {k: [em0.c(parse_expr(x)) for x in v]
                          for k, v in self.allocated.items()}
        # names the program's directives give static storage
        static_names = set()
        for kind, text in prog.spec:
            if kind == "omp":
                d = parse_directive(text, "fortran", self.version)
                if d.name in ("declare target", "threadprivate"):
                    static_names |= {a.lower() for a in d.args}
                    for c in d.clauses:
                        if c.name in ("enter", "to", "link", "local"):
                            static_names |= {a.lower() for a in c.args}
        # names that clauses mention (loop variables named there stay
        # declared outside their loops)
        for u in [prog] + (module.procs if module else []):
            for kind, text in u.body + u.spec:
                if kind == "omp":
                    clauses = _clause_text(text)
                    self.clause_names |= {
                        w.lower() for w in re.findall(r"[A-Za-z_]\w*",
                                                      clauses)}
        lines: list[str] = []
        includes = ["#include <stdio.h>", "#include <stdbool.h>",
                    "#include <omp.h>" if self.model == "omp" else
                    "#include <openacc.h>"]
        # the main program's named constants, at file scope (module data
        # may use them in C, where a Fortran module has its own)
        params = [v for v in prog_scope.values()
                  if "parameter" in v.attrs and v.ftype == "integer"
                  and not v.dims]
        if params:
            lines.append("enum { " + ", ".join(
                f"{v.name} = {em0.c(parse_expr(v.init))}" for v in params)
                + " };")
        # derived types
        for tname, members in types:
            lines.append(f"struct {tname} {{")
            for v in members:
                lines.append("  " + self.c_decl(v, em0))
            lines.append("};")
        # module data and its directives
        if module is not None:
            for kind, text in module.spec:
                if kind == "omp":
                    lines.append(self.directive(Node(
                        "dir", line=text, directive=parse_directive(
                            text, "fortran", self.version)), em0))
                elif parse_declaration(text) is not None:
                    for v in parse_declaration(text):
                        lines.append(self.c_decl(v, em0))
        # program variables with static storage, program declarative
        # directives
        prog_dirs = [t for k, t in prog.spec if k == "omp"]
        for v in prog_scope.values():
            if v.name.lower() in static_names:
                lines.append(self.c_decl(v, em0))
        main_dirs = []
        main_decl_dirs = []  # Acc declare, after the declarations
        named_routines = []  # Acc routine(name), before main
        for text in prog_dirs:
            d = parse_directive(text, "fortran", self.version)
            if self.model == "acc" and d.name == "declare":
                main_decl_dirs.append(self.directive(Node(
                    "dir", line=text, directive=d), em0))
            elif self.model == "acc" and d.name == "routine" and d.args:
                named_routines.append(self.directive(Node(
                    "dir", line=text, directive=d), em0))
            elif d.name in ("declare target", "threadprivate", "requires",
                            "declare mapper"):
                lines.append(self.directive(Node(
                    "dir", line=text, directive=d), em0))
            elif d.name == "error":
                # a compile-time error directive of the main program's
                # specification part: the first line of main
                main_dirs.append(self.directive(Node(
                    "dir", line=text, directive=d), em0))
            else:
                raise TranslateError(f"{d.name} in the main program's "
                                     "specification part")
        # external procedures, then module procedures
        for proc in externals:
            lines += self.procedure(proc, {})
        if module is not None:
            for proc in module.procs:
                lines += self.procedure(proc, mod_scope)
        lines += named_routines
        # main
        loop_vars = set()
        for kind, text in prog.body:
            m = re.match(r"^do\s+([a-z_]\w*)\s*=", text.strip(), re.I)
            if kind == "stmt" and m:
                loop_vars.add(m.group(1).lower())
        self.outer_loop_vars = {v for v in loop_vars
                                if v in self.clause_names}
        ctx = Ctx([mod_scope, prog_scope], self.functions, self)
        em = Emitter(ctx)
        main = ["int main(void) {"] + ["  " + x for x in main_dirs]
        for v in prog_scope.values():
            if v in params or v.name.lower() in static_names:
                continue
            if v.name.lower() in loop_vars - self.outer_loop_vars and \
                    not v.dims:
                continue
            if v.ftype == "alloctrait" and "parameter" in v.attrs:
                main.append("  " + self.c_decl(v, em).replace(
                    "omp_alloctrait_t", "const omp_alloctrait_t", 1))
                continue
            if self.c_decl(v, em):
                main.append("  " + self.c_decl(v, em))
        main += ["  " + x for x in main_decl_dirs]
        body = self.emit(_tree(prog.body, self.version), em, 1)
        main += body + ["  return 0;", "}"]
        if self.needs_stdlib:
            includes.insert(1, "#include <stdlib.h>")
        out = [f"// {h}" for h in head] + includes + [""] + lines + (
            [""] if lines else []) + main
        return "\n".join(out) + "\n"

    def procedure(self, proc: Unit, mod_scope: dict) -> list[str]:
        scope: dict = {}
        self.declare(scope, proc.spec)
        intents = []
        for p in proc.params:
            v = scope.get(p)
            if v is None:
                raise TranslateError(f"dummy {p} undeclared")
            if v.intent is None and any(
                    k == "stmt" and re.search(
                        rf"(?:^|\))\s*{re.escape(p)}\s*=(?!=)", t, re.I)
                    for k, t in proc.body):
                # A dummy without intent is passed by reference,
                # so one the procedure assigns is inout (the 5.0
                # is_device_ptr program's hf)
                v = scope[p] = dataclasses.replace(v, intent="inout")
            if v.deferred or (v.dims and (len(v.dims) != 1 or ":" in
                                          v.dims[0])):
                raise TranslateError("array dummy arguments are not ported")
            # A rank-1 explicit-shape dummy array is a pointer
            # parameter (the array's address; deviceptr programs)
            intents.append("array" if v.dims else v.intent or "in")
        self.functions[proc.name] = intents
        ctx = Ctx([mod_scope, scope], self.functions, self)
        em = Emitter(ctx)
        self.result = proc.name if proc.kind == "function" else None
        params = ", ".join(self.c_param(scope[p], p) for p in proc.params) \
            or "void"
        rtype = {"integer": "int", "logical": "bool", "": "void"}[
            proc.result_type]
        dirs = [t for k, t in proc.spec if k == "omp"]
        before, after = [], []
        for text in dirs:
            d = parse_directive(text, "fortran", self.version)
            if self.model == "acc" and d.name == "routine":
                # Without a name the C routine directive goes
                # immediately before the definition (3.4 §2.15.1, p.91);
                # with one, anywhere a prototype is allowed: after it
                line = self.directive(Node("dir", line=text, directive=d),
                                      em)
                (after if d.args else before).append(line)
                continue
            if d.name != "declare target":
                raise TranslateError(f"{d.name} in a procedure")
            listed = d.args or any(c.name in ("enter", "to", "link", "local")
                                   for c in d.clauses)
            if listed:
                after.append(self.directive(Node("dir", line=text,
                                                 directive=d), em))
            else:
                # clause-less (or device_type/indirect only): the delimited
                # form around the definition (5.2 §7.8.2, 6.0 §9.9.2)
                name, clauses = _split_name(text.strip()[5:].strip())
                begin = "#pragma omp begin declare target"
                if self.version < 51:
                    # 5.0 has no begin declare target; its
                    # delimited form is declare target ... end declare
                    # target, without clauses (5.0 §2.12.7, p.181)
                    if clauses:
                        raise TranslateError("a clause on the 5.0 delimited "
                                             "declare target")
                    begin = "#pragma omp declare target"
                if clauses:
                    begin += " " + self.c_clauses(clauses, em)
                before.append(begin)
                after.insert(0, "#pragma omp end declare target")
        loop_vars = {m.group(1).lower() for k, t in proc.body
                     if k == "stmt" and (m := re.match(
                         r"^do\s+([a-z_]\w*)\s*=", t.strip(), re.I))}
        saved = self.outer_loop_vars if hasattr(self, "outer_loop_vars") \
            else set()
        self.outer_loop_vars = {v for v in loop_vars
                                if v in self.clause_names}
        out = before + [f"{rtype} {proc.name}({params}) {{"]
        for v in scope.values():
            if v.name.lower() in proc.params or v.name.lower() == proc.name:
                continue
            if v.name.lower() in loop_vars - self.outer_loop_vars and \
                    not v.dims:
                continue
            out.append("  " + self.c_decl(v, em))
        if self.result:
            out.append(f"  {rtype} r_;")
        out += self.emit(_tree(proc.body, self.version), em, 1)
        if self.result:
            out.append("  return r_;")
        out.append("}")
        self.result = None
        self.outer_loop_vars = saved
        return out + after


def _plus_one(text: str) -> str:
    t = text.strip()
    if re.fullmatch(r"-?\d+", t):
        return str(int(t) + 1)
    m = re.fullmatch(r"(.*\S)\s*-\s*(\d+)", t)
    if m and _balanced(m.group(1)):
        k = int(m.group(2)) - 1
        return m.group(1) if k == 0 else f"{m.group(1)} - {k}"
    return f"{t} + 1"


def _loops(shape: list[str], idx: list[str], body: list[str]) -> list[str]:
    out, pad = [], ""
    for ext, k in zip(shape, idx):
        out.append(f"{pad}for (int {k} = 0; {k} < {ext}; {k}++)")
        pad += "  "
    out += [pad + b for b in body]
    return out


C_MAX_LINE = 96


def _wrap_c(line: str) -> list[str]:
    """A long #pragma line split at clause boundaries with backslash
    continuations."""
    if len(line) <= C_MAX_LINE:
        return [line]
    ind = line[:len(line) - len(line.lstrip())]
    parts, depth, cur = [], 0, ""
    for ch in line.strip():
        depth += ch == "("
        depth -= ch == ")"
        if ch == " " and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        cur += ch
    parts.append(cur)
    out, cur = [], ""
    for p in parts:
        if cur and len(ind) + len(cur) + len(p) + 3 > C_MAX_LINE:
            out.append(cur)
            cur = "    " + p
        else:
            cur = f"{cur} {p}" if cur else p
    out.append(cur)
    return [ind + x + (" \\" if k < len(out) - 1 else "")
            for k, x in enumerate(out)]


def translate(source: str, version: int) -> str:
    """The C11 program of a generated Fortran program (see the module
    docstring); raises TranslateError for what is not ported."""
    return Translator(source, version).run()
