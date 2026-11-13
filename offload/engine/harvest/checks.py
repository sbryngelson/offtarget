"""The FileCheck lines of a harvested test and the matcher that turns them into
a self-check.

A harvested LLVM test states its expected output as FileCheck directives
(``// CHECK: ...``). The converted program matches them against its own
output (offload.engine.harvest.convert); ``match`` here is the reference
implementation the tests exercise. ``parse_checks`` reads CHECK, -NEXT,
-SAME, -NOT, -DAG and -EMPTY; -LABEL counts as CHECK and -COUNT-n as n CHECK
lines. ``compile_pattern`` gives mode ``tokens`` (token by token, numbers
by value: integers exactly, others within a relative 1e-5) or, for C only,
``regex`` (``{{re}}`` and ``[[NAME:re]]`` as a POSIX extended expression).
Fortran (``match_stream``) matches over one token stream with commas
dropped, since list-directed output is processor dependent. ``Unsupported``
marks tests that are filtered: numeric variables, ``[[@LINE]]``, a variable
used in its own definition, a regex in Fortran.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

KINDS = ("CHECK", "NEXT", "SAME", "NOT", "DAG", "EMPTY")


class Unsupported(ValueError):
    """A FileCheck feature the self-check does not implement."""


@dataclass(frozen=True)
class Check:
    kind: str
    pattern: str
    line: int


def _directive_re(prefixes) -> re.Pattern:
    alt = "|".join(re.escape(p) for p in prefixes)
    return re.compile(r"(?:^|[^A-Za-z0-9_-])(" + alt + r")"
                      r"(-NEXT|-SAME|-NOT|-DAG|-EMPTY|-LABEL|-COUNT-\d+)?:"
                      r"(.*)$")


def parse_checks(text: str, prefixes=("CHECK",)) -> list[Check]:
    """The directives of `prefixes` in file order."""
    rx = _directive_re(prefixes)
    out: list[Check] = []
    for k, line in enumerate(text.splitlines(), start=1):
        m = rx.search(line)
        if not m:
            continue
        suffix = m.group(2) or ""
        pat = m.group(3).strip()
        if pat.endswith("*/"):
            pat = pat[:-2].rstrip()
        if suffix.startswith("-COUNT-"):
            out += [Check("CHECK", pat, k)] * int(suffix[7:])
        elif suffix in ("", "-LABEL"):
            out.append(Check("CHECK", pat, k))
        else:
            out.append(Check(suffix[1:], pat, k))
    return out


def prefixes_in(text: str) -> set[str]:
    """Every FileCheck-looking prefix of a text (``FOO:``, ``FOO-NEXT:``
    on a comment line)."""
    found = set()
    for m in re.finditer(r"(?://|!)\s*([A-Z][A-Z0-9_]*)(?:-NEXT|-SAME|-NOT|"
                         r"-DAG|-EMPTY|-LABEL|-COUNT-\d+)?:", text):
        found.add(m.group(1))
    return found


# --- tokens -------------------------------------------------------------------------

_TOKEN = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eEdD][+-]?\d+)?|"
                    r"[A-Za-z_][A-Za-z0-9_]*|\S")


@dataclass(frozen=True)
class Tok:
    text: str
    start: int
    end: int

    @property
    def kind(self) -> str:
        c = self.text[0]
        if c.isdigit() or (c == "." and len(self.text) > 1):
            return "num"
        if c.isalpha() or c == "_":
            return "word"
        return "punct"


def tokenize(text: str, start: int = 0) -> list[Tok]:
    return [Tok(m.group(0), m.start(), m.end())
            for m in _TOKEN.finditer(text, start)]


def _num(s: str) -> float:
    return float(s.replace("d", "e").replace("D", "e"))


def _intlike(s: str) -> bool:
    return not re.search(r"[.eEdD]", s)


def token_equal(p: str, o: str) -> bool:
    """Two tokens are equal: numbers by value (integers by their digits
    without leading zeros, others within a relative 1e-5), anything else
    by text."""
    pt, ot = Tok(p, 0, 0).kind, Tok(o, 0, 0).kind
    if pt == "num" and ot == "num":
        if _intlike(p) and _intlike(o):
            return (p.lstrip("0") or "0") == (o.lstrip("0") or "0")
        a, b = _num(p), _num(o)
        return a == b or abs(a - b) <= 1e-5 * max(abs(a), abs(b))
    return p == o


def _tok_ok(pt: str, ot: Tok, where: str) -> bool:
    """`where`: "only" (the pattern's one token), "first", "last", "mid"."""
    if Tok(pt, 0, 0).kind == "word" and ot.kind == "word":
        if where == "only":
            return pt in ot.text
        if where == "first":
            return ot.text.endswith(pt)
        if where == "last":
            return ot.text.startswith(pt)
    return token_equal(pt, ot.text)


def _find_tokens(seg: list[str], toks: list[Tok], col: int):
    """(start, end) of the first occurrence of the token sequence `seg` in
    `toks` at or after column `col`."""
    k = len(seg)
    for i in range(len(toks) - k + 1):
        if toks[i].start < col:
            continue
        ok = True
        for j in range(k):
            where = "only" if k == 1 else "first" if j == 0 else \
                "last" if j == k - 1 else "mid"
            if not _tok_ok(seg[j], toks[i + j], where):
                ok = False
                break
        if ok:
            return toks[i].start, toks[i + k - 1].end
    return None


# --- patterns -----------------------------------------------------------------------

@dataclass
class Pattern:
    mode: str                       # "tokens" | "regex"
    text: str
    segments: list = field(default_factory=list)    # tokens mode
    regex: str = ""                                 # regex mode (ERE)
    defs: list = field(default_factory=list)        # [(name, group)]
    uses: list = field(default_factory=list)


_ERE_SPECIAL = set("\\.[]{}()*+?^$|")
_WILD = ("{{.*}}", "{{.+}}")


def ere_escape(text: str) -> str:
    return "".join("\\" + c if c in _ERE_SPECIAL else c for c in text)


def _fold(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text)


def _pieces(pattern: str) -> list[tuple[str, str]]:
    """[(kind, text)]: ("lit", text), ("re", regex), ("def", name, re) as
    ("def", "NAME\\0re"), ("use", name)."""
    out = []
    i = 0
    while i < len(pattern):
        a = pattern.find("{{", i)
        b = pattern.find("[[", i)
        cands = [x for x in (a, b) if x >= 0]
        if not cands:
            out.append(("lit", pattern[i:]))
            break
        j = min(cands)
        if j > i:
            out.append(("lit", pattern[i:j]))
        if j == a:
            e = pattern.find("}}", j + 2)
            if e < 0:
                raise Unsupported("unbalanced {{ in a CHECK pattern")
            # a regex may end with }} ({{[0-9]}}}}): take the last }} run
            while pattern.startswith("}", e + 2):
                e += 1
            out.append(("re", pattern[j + 2:e]))
            i = e + 2
        else:
            e = pattern.find("]]", j + 2)
            if e < 0:
                raise Unsupported("unbalanced [[ in a CHECK pattern")
            # a nested [[:xdigit:]] class inside the definition
            while pattern.startswith("]", e + 2):
                e += 1
            body = pattern[j + 2:e]
            if body.startswith("#") or body.startswith("@") or \
                    body.lstrip().startswith(("#", "@")):
                raise Unsupported(f"FileCheck numeric or line variable "
                                  f"[[{body}]]")
            m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)(?::(.*))?", body,
                             re.S)
            if not m:
                raise Unsupported(f"FileCheck variable [[{body}]]")
            if m.group(2) is None:
                out.append(("use", m.group(1)))
            elif m.group(2) == "":
                raise Unsupported(f"FileCheck empty definition [[{body}]]")
            else:
                out.append(("def", m.group(1) + "\0" + m.group(2)))
            i = e + 2
    return out


def _groups(ere: str) -> int:
    """The number of capturing groups opened in an ERE prefix."""
    n, i, br = 0, 0, False
    while i < len(ere):
        c = ere[i]
        if c == "\\":
            i += 2
            continue
        if br:
            if c == "]":
                br = False
        elif c == "[":
            br = True
            if ere[i + 1:i + 2] == "]":
                i += 1
            elif ere[i + 1:i + 3] == "^]":
                i += 2
        elif c == "(":
            n += 1
        i += 1
    return n


def compile_pattern(pattern: str, lang: str = "c") -> Pattern:
    """The pattern's mode and its compiled form (see the module docstring)."""
    pieces = _pieces(pattern)
    if all(k == "lit" or (k == "re" and "{{" + t + "}}" in _WILD)
           for k, t in pieces):
        segs, cur = [], ""
        for k, t in pieces:
            if k == "lit":
                cur += t
            else:
                segs.append(cur)
                cur = ""
        segs.append(cur)
        segs = [" ".join(s.split()) for s in segs]
        return Pattern("tokens", pattern, segments=[s for s in segs if s])
    if lang != "c":
        raise Unsupported("a regular expression in a Fortran CHECK pattern")
    ere, defs, uses, defined = "", [], [], set()
    for k, t in pieces:
        if k == "lit":
            ere += ere_escape(_fold(t))
        elif k == "re":
            if t == "$":
                ere += "$"
            elif t == "^":
                ere += "^"
            else:
                ere += "(" + t + ")"
        elif k == "def":
            name, rx = t.split("\0", 1)
            defs.append((name, _groups(ere) + 1))
            defined.add(name)
            ere += "(" + rx + ")"
        else:
            if t in defined:
                raise Unsupported(f"variable {t} used in its defining "
                                  "pattern")
            uses.append(t)
            ere += "\x01" + t + "\x01"
    return Pattern("regex", pattern, regex=ere, defs=defs, uses=uses)


# --- the reference matcher ------------------------------------------------------------

_POSIX_CLASSES = {"[:xdigit:]": "0-9A-Fa-f", "[:digit:]": "0-9",
                  "[:alpha:]": "A-Za-z", "[:alnum:]": "0-9A-Za-z",
                  "[:space:]": r" \t\n\r\f\v", "[:upper:]": "A-Z",
                  "[:lower:]": "a-z", "[:punct:]": r"!-/:-@\[-`{-~"}


def _python_re(ere: str) -> str:
    for k, v in _POSIX_CLASSES.items():
        ere = ere.replace(k, v)
    return ere


def _find(p: Pattern, line: str, col: int, vars_: dict):
    """(start, end, captures) of the first match of `p` in `line` at or
    after `col`, else None."""
    if p.mode == "tokens":
        toks = tokenize(line)
        if not p.segments:
            return col, col, {}
        start = None
        c = col
        for seg in p.segments:
            hit = _find_tokens([t.text for t in tokenize(seg)], toks, c)
            if hit is None:
                return None
            if start is None:
                start = hit[0]
            c = hit[1]
        return start, c, {}
    ere = p.regex
    for u in p.uses:
        if u not in vars_:
            return None
        ere = ere.replace("\x01" + u + "\x01", ere_escape(vars_[u]))
    rx = re.compile(_python_re(ere))
    # at a column after the start ^ does not match (REG_NOTBOL)
    m = rx.search(line, min(col, len(line)))
    if m is None:
        return None
    caps = {name: m.group(g) for name, g in p.defs}
    return m.start(), m.end(), caps


def _lines(output: str) -> list[str]:
    lines = output.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    # runs of blanks folded to one in every line (FileCheck's default; the
    # columns of every mode are positions in the folded line)
    return [_fold(ln.rstrip("\r")) for ln in lines]


def _stream(text: str, repeats: bool = False) -> list[Tok]:
    """Fortran: the tokens of a text without its commas (list-directed
    output separates values by blanks or commas and may begin a new record
    anywhere, F2018 13.10.4: neither is part of the expected values). With
    `repeats` (the output), a repeated value ``r*c`` (an unsigned integer,
    ``*`` and a value, with no blank between: F2018 13.10.4 allows it for
    r consecutive equal values; CCE prints ``16*42.``) is r tokens c."""
    toks = [t for t in tokenize(text) if t.text != ","]
    if not repeats:
        return toks
    out, k = [], 0
    while k < len(toks):
        t = toks[k]
        if k + 2 < len(toks) and toks[k + 1].text == "*" and \
                t.text.isdigit() and t.end == toks[k + 1].start and \
                toks[k + 1].end == toks[k + 2].start and \
                toks[k + 2].text != "*":
            out += [toks[k + 2]] * int(t.text)
            k += 3
            continue
        out.append(t)
        k += 1
    return out


def _find_stream(p: Pattern, toks: list[Tok], start: int):
    """(first token, end token) of the first occurrence of a token
    pattern in a token stream at or after token `start`."""
    if not p.segments:
        return start, start
    first, c = None, start
    for seg in p.segments:
        st = [t.text for t in _stream(seg)]
        k = len(st)
        hit = None
        for i in range(c, len(toks) - k + 1):
            if all(_tok_ok(st[j], toks[i + j], "only" if k == 1 else
                           "first" if j == 0 else "last" if j == k - 1
                           else "mid") for j in range(k)):
                hit = (i, i + k)
                break
        if hit is None:
            return None
        if first is None:
            first = hit[0]
        c = hit[1]
    return first, c


def match_stream(checks: list[Check], output: str) -> tuple[bool, str]:
    """The Fortran rules: the directives in order over the output's token
    stream (no commas, no record boundaries): NEXT and SAME read as CHECK,
    EMPTY holds, NOT between two matches, DAG in any order."""
    toks = _stream(output, repeats=True)
    pats = [compile_pattern(c.pattern, "f90") if c.kind != "EMPTY" else
            None for c in checks]
    cur = 0
    nots: list[int] = []

    def bad_not(limit: int) -> int | None:
        for k in nots:
            h = _find_stream(pats[k], toks, cur)
            if h and h[1] <= limit:
                return k
        return None

    i = 0
    while i < len(checks):
        c = checks[i]
        if c.kind == "EMPTY":
            i += 1
            continue
        if c.kind == "NOT":
            nots.append(i)
            i += 1
            continue
        if c.kind == "DAG":
            j, hits = i, []
            while j < len(checks) and checks[j].kind == "DAG":
                h = _find_stream(pats[j], toks, cur)
                if h is None:
                    return False, f"CHECK-DAG not found: {checks[j].pattern}"
                hits.append(h)
                j += 1
            b = bad_not(min(h[0] for h in hits))
            if b is not None:
                return False, f"CHECK-NOT found: {checks[b].pattern}"
            nots, cur, i = [], max(h[1] for h in hits), j
            continue
        h = _find_stream(pats[i], toks, cur)
        if h is None:
            return False, f"not found: {c.pattern}"
        b = bad_not(h[0])
        if b is not None:
            return False, f"CHECK-NOT found: {checks[b].pattern}"
        nots, cur = [], h[1]
        i += 1
    b = bad_not(len(toks))
    if b is not None:
        return False, f"CHECK-NOT found: {checks[b].pattern}"
    return True, ""


def match(checks: list[Check], output: str, lang: str = "c"
          ) -> tuple[bool, str]:
    """(ok, why) of the directives against an output, with the rules the
    in-program matchers follow (module docstring); Fortran: match_stream."""
    if lang != "c":
        return match_stream(checks, output)
    lines = _lines(output)
    pats = [compile_pattern(c.pattern, lang) if c.kind != "EMPTY" else None
            for c in checks]
    vars_: dict[str, str] = {}
    line, col, started = 0, 0, False
    nots: list[int] = []

    def search(p, l0, c0, only_line=None):
        rng = [only_line] if only_line is not None else \
            range(l0, len(lines))
        for ln in rng:
            if ln < 0 or ln >= len(lines):
                continue
            hit = _find(p, lines[ln], c0 if ln == l0 else 0, vars_)
            if hit:
                return ln, hit
        return None

    def check_nots(to_line, to_col) -> int | None:
        for k in nots:
            for ln in range(line, min(to_line, len(lines) - 1) + 1):
                c0 = col if ln == line else 0
                hit = _find(pats[k], lines[ln], c0, vars_)
                if hit and (ln < to_line or hit[1] <= to_col):
                    return k
        return None

    i = 0
    while i < len(checks):
        c = checks[i]
        if c.kind == "NOT":
            nots.append(i)
            i += 1
            continue
        if c.kind == "DAG":
            j = i
            ends, starts = [], []
            while j < len(checks) and checks[j].kind == "DAG":
                f = search(pats[j], line, col)
                if f is None:
                    return False, f"CHECK-DAG not found: {checks[j].pattern}"
                ln, (s, e, caps) = f
                vars_.update(caps)
                starts.append((ln, s))
                ends.append((ln, e))
                j += 1
            bad = check_nots(*min(starts))
            if bad is not None:
                return False, f"CHECK-NOT found: {checks[bad].pattern}"
            nots = []
            line, col = max(ends)
            started = True
            i = j
            continue
        if c.kind == "EMPTY":
            nxt = line + 1 if started else 0
            if nxt >= len(lines) or lines[nxt] != "":
                return False, "CHECK-EMPTY: the next line is not empty"
            f = (nxt, (0, 0, {}))
        elif c.kind == "NEXT" and started:
            f = search(pats[i], line + 1, 0, only_line=line + 1)
        elif c.kind == "SAME" and started:
            f = search(pats[i], line, col, only_line=line)
        else:
            f = search(pats[i], line, col)
        if f is None:
            return False, f"CHECK{'' if c.kind == 'CHECK' else '-' + c.kind}" \
                f" not found: {c.pattern}"
        ln, (s, e, caps) = f
        bad = check_nots(ln, s)
        if bad is not None:
            return False, f"CHECK-NOT found: {checks[bad].pattern}"
        nots = []
        vars_.update(caps)
        line, col, started = ln, e, True
        i += 1
    bad = check_nots(len(lines), 1 << 30)
    if bad is not None:
        return False, f"CHECK-NOT found: {checks[bad].pattern}"
    return True, ""
