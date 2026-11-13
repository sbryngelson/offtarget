"""Directive-line parser for the slice, driven by the catalog.

``parse_directive(text, lang, version)`` takes one directive (possibly
several physical lines), strips the sentinel, and returns a ``Directive`` or
raises ``GrammarError`` with a code from ``GrammarError.CODES``. It
normalizes to one logical line (Fortran free form only; C ``#pragma omp``),
reads the longest directive name the skeleton knows, then the clauses as
``name[(arguments)]``. It checks language, version, allowed, once-only,
exclusive and required clauses against the skeleton as corrected by
``spec_overrides.yaml``, and matches each clause's arguments against its
``clauses.yaml`` syntax. A clause with no grammar entry is split generically.
Clause forms with ``langs`` apply in their language only. The version selects
the model (``catalog.model_of``): 34 is OpenACC 3.4, with its own catalog,
sentinel ``!$acc`` and atom prefix ``acc.``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from offload.engine.catalog import (DIRECTIVE_NAME_CLASS, ClauseForm, Grammar,
                                Skeleton, base_name, default_grammar,
                                default_skeleton, directive_atom, feature,
                                model_of, rule_valid, spec_name,
                                spelling_valid)


class GrammarError(Exception):
    CODES = frozenset({"unknown_directive", "unknown_clause",
                       "clause_not_allowed", "clause_repeated",
                       "missing_required", "bad_argument", "wrong_language",
                       "version", "fixed_form"})

    def __init__(self, code: str, message: str):
        if code not in self.CODES:
            raise ValueError(f"unknown GrammarError code {code!r}")
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass
class Clause:
    name: str
    args: list[str] = field(default_factory=list)
    modifiers: list[str] = field(default_factory=list)


@dataclass
class Directive:
    name: str  # skeleton key, e.g. "target data" or "ordered (Block)"
    clauses: list[Clause]
    atoms: frozenset[str]
    end: bool = False  # a paired end directive ("!$omp end target data")
    args: list[str] = field(default_factory=list)  # "declare target (a, b)"


# Directives whose name may be followed by a parenthesised argument list.
_ARG_ASSOCIATIONS = {"Explicit", "Declaration"}
_ARG_DIRECTIVES = {"critical", "flush", "depobj", "declare mapper",
                   "declare reduction", "declare_induction"}
# OpenACC directives with a parenthesised argument (3.4 §2.10, §2.16.3)
_ACC_ARG_DIRECTIVES = {"cache", "wait"}
# Associations whose directives have a paired end directive in Fortran.
_END_ASSOCIATIONS = {"Block", "LoopNest", "FromLeaves", "LoopSeq"}


def _lang(lang: str) -> str:
    low = lang.lower()
    if low in ("fortran", "f", "f90"):
        return "Fortran"
    if low in ("c", "c++", "cpp"):
        return "C"
    raise ValueError(f"unknown language {lang!r}")


# --- step 1: one logical line -------------------------------------------------

def _outside_strings(text: str, fn) -> str:
    """Apply fn to the parts of text outside '...' and "..." literals."""
    out = []
    for i, part in enumerate(re.split(r"""('(?:[^']|'')*'?|"(?:[^"]|"")*"?)""",
                                      text)):
        out.append(part if i % 2 else fn(part))
    return "".join(out)


def _strip_bang_comment(text: str) -> str:
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "!":
            return text[:i]
    return text


_SENTINEL = re.compile(r"^(\s*)(!)\$omp", re.I)
_FIXED_FORM = re.compile(r"^[c*]\$omp", re.I)
_SENTINELS = {"omp": _SENTINEL,
              "acc": re.compile(r"^(\s*)(!)\$acc", re.I)}
_FIXED_FORMS = {"omp": _FIXED_FORM,
                "acc": re.compile(r"^[c*]\$acc", re.I)}


def sentinel(model: str = "omp") -> re.Pattern:
    """The free-form sentinel of a model (``!$omp`` / ``!$acc``)."""
    return _SENTINELS[model]


def _is_comment(raw: str) -> bool:
    """A blank line or a plain Fortran comment (not a !$ line)."""
    s = raw.lstrip()
    return not s or (s.startswith("!") and not s.startswith("!$"))


def _fortran_line(text: str, model: str = "omp") -> str:
    """The logical directive line (free form only)."""
    for raw in text.splitlines():
        if _FIXED_FORMS[model].match(raw):
            raise GrammarError("fixed_form", "fixed-form sentinel "
                               f"{raw.strip()!r}: only free-form Fortran "
                               f"(!${model}) is supported")
    parts: list[str] = []
    pending = False
    lines = [l for l in text.splitlines() if not _is_comment(l)]
    for n, raw in enumerate(lines):
        m = _SENTINELS[model].match(raw)
        if not m:
            name = "OpenMP" if model == "omp" else "OpenACC"
            raise GrammarError("unknown_directive",
                               f"no {name} sentinel in {raw.strip()!r}")
        rest = raw[m.end():]
        if model == "omp" and rest[:1].lower() == "x":
            raise GrammarError("unknown_directive",
                               f"ompx sentinel not supported: {raw.strip()!r}")
        rest = _strip_bang_comment(rest)
        if n and pending:
            stripped = rest.lstrip()
            rest = stripped[1:] if stripped.startswith("&") else stripped
        elif n:
            raise GrammarError("unknown_directive",
                               f"line {n + 1} does not continue the directive")
        rest = rest.rstrip()
        pending = rest.endswith("&")
        parts.append(rest[:-1] if pending else rest)
    if not parts:
        raise GrammarError("unknown_directive", "empty directive text")
    return _outside_strings("".join(parts), str.lower).strip()


_PRAGMA = re.compile(r"^\s*#\s*pragma\s+omp\b")
# The OpenACC C sentinel (OpenACC 3.4 §2.1: #pragma acc)
_PRAGMAS = {"omp": _PRAGMA, "acc": re.compile(r"^\s*#\s*pragma\s+acc\b")}


def _c_line(text: str, model: str = "omp") -> str:
    text = re.sub(r"\\\n", " ", text.strip())
    if "\n" in text:
        raise GrammarError("unknown_directive", "more than one pragma line")
    m = _PRAGMAS[model].match(text)
    if not m:
        raise GrammarError("unknown_directive",
                           f"no #pragma {model} in {text!r}")
    text = _outside_strings(text[m.end():],
                            lambda s: re.sub(r"/\*.*?\*/", " ", s))
    return _outside_strings(text, lambda s: s.split("//")[0]).strip()


# --- step 2: tokens and the directive structure -------------------------------

_TOKEN = re.compile(r"""\s*(?:([A-Za-z_][A-Za-z0-9_$]*)|('(?:[^']|'')*'"""
                    r"""|"(?:[^"]|"")*")|([(),:;])|(\S))""")


@dataclass
class _Tok:
    kind: str  # name, string, punct, other
    text: str
    start: int
    end: int


def _tokenize(line: str) -> list[_Tok]:
    toks = []
    pos = 0
    while pos < len(line):
        m = _TOKEN.match(line, pos)
        if not m or m.end() == pos:
            break
        kind = ("name" if m.group(1) else "string" if m.group(2)
                else "punct" if m.group(3) else "other")
        text = m.group(m.lastindex)
        toks.append(_Tok(kind, text, m.start(m.lastindex), m.end()))
        pos = m.end()
    return toks


def _close_paren(toks: list[_Tok], i: int, what: str) -> int:
    """Index of the ')' matching the '(' at toks[i]."""
    depth = 0
    for j in range(i, len(toks)):
        if toks[j].text == "(":
            depth += 1
        elif toks[j].text == ")":
            depth -= 1
            if depth == 0:
                return j
    raise GrammarError("bad_argument", f"unbalanced parentheses in {what}")


def _split(text: str, seps: str) -> list[str]:
    """Split at top-level separators: [piece, sep, piece, ..., piece]."""
    out: list[str] = []
    depth = 0
    quote = None
    cur = []
    for ch in text:
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif depth == 0 and ch in seps:
            out += [" ".join("".join(cur).split()), ch]
            cur = []
            continue
        cur.append(ch)
    out.append(" ".join("".join(cur).split()))
    return out


# --- step 4: clause argument matching -----------------------------------------

_IDENT = re.compile(r"^(?:[a-z_][a-z0-9_$]*|\.[a-z]+\.)$", re.I)
# C: an identifier, no Fortran .op. operator
_C_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$", re.I)
_LIST_ITEM = re.compile(r"^[A-Za-z_/]")


class _Matcher:
    """Backtracking match of one clause-argument specification."""

    def __init__(self, form: ClauseForm, directive_names: frozenset,
                 lang: str = "Fortran"):
        self.form = form
        self.names = directive_names
        self.ident = _C_IDENT if lang == "C" else _IDENT

    def run(self, alt: tuple, flat: list[str]):
        for pos, caps in self.match(alt, flat, 0, ()):
            if pos == len(flat):
                return caps
        return None

    def match(self, nodes, flat, pos, caps):
        if not nodes:
            yield pos, caps
            return
        node, rest = nodes[0], nodes[1:]
        k = node.kind
        if k == "opt":
            yield from self.match(node.body + rest, flat, pos, caps)
            yield from self.match(rest, flat, pos, caps)
        elif k == "lit":
            if pos < len(flat) and pos % 2 and flat[pos] == node.values[0]:
                yield from self.match(rest, flat, pos + 1, caps)
        elif pos >= len(flat) or pos % 2 or not flat[pos]:
            return
        elif k == "expr":
            yield from self.match(rest, flat, pos + 1,
                                  caps + (("arg", flat[pos], node.label),))
        elif k == "enum":
            if flat[pos] in node.values:
                new = (("arg", flat[pos], feature(flat[pos])),)
                if node.label:
                    new += (("arg", None, node.label),)
                yield from self.match(rest, flat, pos + 1, caps + new)
        elif k in ("list", "expr_list"):
            end = pos
            while (end + 2 < len(flat) and flat[end + 1] == ","
                   and flat[end + 2]):
                end += 2
            for stop in range(end, pos - 1, -2):
                items = flat[pos:stop + 1:2]
                if k == "list" and not all(_LIST_ITEM.match(i) for i in items):
                    continue
                new = tuple(("arg", i, None) for i in items)
                if node.label:
                    new += (("arg", None, node.label),)
                yield from self.match(rest, flat, stop + 1, caps + new)
        elif k == "mods":
            end = pos
            while (end + 2 < len(flat) and flat[end + 1] == ","
                   and flat[end + 2]):
                end += 2
            for stop in range(end, pos - 1, -2):
                mods = self.modifiers(flat[pos:stop + 1:2], node.values)
                if mods is not None:
                    new = tuple(x for c, t, a in mods
                                for x in self.expand(c, t, a))
                    yield from self.match(rest, flat, stop + 1, caps + new)

    def expand(self, cls, text, feat) -> tuple:
        """The captures of one modifier: a 5.0 list-wrapping modifier
        (``val(x, y)``) gives the modifier keyword and the list items as
        arguments; a 5.0 call form (``alloc(traits)``) gives the whole text
        as the modifier and the identifier as the argument."""
        mc = self.form.modifiers.get(cls)
        if mc is not None and (mc.wraps_list or mc.call):
            head, inner = text.split("(", 1)
            if mc.wraps_list:
                items = _split(inner[:-1], ",")[::2]
                return (("mod", mc.complex, feat),) + tuple(
                    ("arg", i, None) for i in items)
            return (("mod", text, feat), ("arg", head.strip(), None))
        return (("mod", text, feat),)

    def classify(self, piece: str, classes) -> tuple | None:
        mods = self.form.modifiers
        for cls in classes:
            if cls == DIRECTIVE_NAME_CLASS:
                if piece in self.names:
                    return cls, "directive_name"
                continue
            mc = mods[cls]
            if piece in mc.keywords:
                return cls, feature(piece)
            if mc.complex and re.match(rf"^{re.escape(mc.complex)}\s*\(.*\)$",
                                       piece):
                return cls, feature(mc.complex)
            if mc.call and re.match(r"^[a-z_]\w*\s*\(.*\)$", piece, re.I):
                return cls, feature(mc.complex)
        for cls in classes:
            if cls != DIRECTIVE_NAME_CLASS and mods[cls].identifier \
                    and self.ident.match(piece):
                return cls, None
        for cls in classes:
            if cls != DIRECTIVE_NAME_CLASS and mods[cls].expr:
                return cls, feature(cls)
        return None

    def modifiers(self, pieces, classes) -> list | None:
        """[(class, text, atom feature)] if the pieces form a legal modifier
        list, else None."""
        found = []
        for piece in pieces:
            hit = self.classify(piece, classes)
            if hit is None and self.form.modifier_commas_optional:
                words = _split(piece, " ")[::2]
                hits = [self.classify(w, classes) for w in words]
                mods = self.form.modifiers
                if len(words) > 1 and all(h and h[0] in mods
                                          and not mods[h[0]].expr
                                          for h in hits):
                    found += [(h[0], w, h[1]) for h, w in zip(hits, words)]
                    continue
            if hit is None:
                return None
            found.append((hit[0], piece, hit[1]))
        names = [c for c, _, _ in found]
        for cls in set(names):
            mc = self.form.modifiers.get(cls)
            keyword_class = mc is not None and mc.keywords and not mc.one_of \
                and not mc.identifier
            if keyword_class:
                texts = [t for c, t, _ in found if c == cls]
                if len(texts) != len(set(texts)):
                    return None
            elif names.count(cls) > 1:
                return None
            if mc is not None and mc.ultimate and names[-1] != cls:
                return None
            if mc is not None and mc.exclusive and len(names) > 1:
                return None
        for cls in classes:
            mc = self.form.modifiers.get(cls)
            if mc is not None and mc.required and cls not in names:
                return None
        return found


# --- the parser -----------------------------------------------------------------

@dataclass
class _Raw:
    name: str
    text: str | None  # argument text between the parentheses, None if absent


class _Parser:
    def __init__(self, sk: Skeleton, grammar: Grammar, lang: str,
                 version: int):
        self.sk, self.grammar = sk, grammar
        self.lang, self.version = lang, version
        self.model = model_of(version)
        index: dict[str, list[str]] = {}
        for key, spec in sk.directives.items():
            for s in spec.spellings:
                index.setdefault(s.text, [])
                if key not in index[s.text]:
                    index[s.text].append(key)
        for e in grammar.spellings:
            index.setdefault(e.spelling, [])
            if e.directive not in index[e.spelling]:
                index[e.spelling].append(e.directive)
        self.index = index
        self.max_words = max(len(s.split()) for s in index)
        # Fortran: blanks between keywords of a directive name are optional
        # (OpenMP 5.2 §3.1.2), so names are also looked up without blanks.
        self.compact = {}
        for s in index:
            other = self.compact.setdefault(s.replace(" ", ""), s)
            if other != s:
                raise ValueError(f"spellings {other!r} and {s!r} collide "
                                 "without blanks")
        # the directive-name modifier class: in Fortran a directive-name
        # modifier is a directive-name, so its blanks are optional too
        self.names = frozenset(index) | (frozenset(self.compact)
                                         if lang == "Fortran" else frozenset())
        self.clause_spellings = {
            s["text"]: base_name(k) for k, c in sk.clauses.items()
            for s in c["spellings"]}
        self._allowed: dict = {}

    def allowed(self, key):
        """The directive's clause rules after the spec overrides."""
        if key not in self._allowed:
            self._allowed[key] = self.grammar.allowed(self.sk, key)
        return self._allowed[key]

    def parse(self, text: str) -> Directive:
        if self.lang == "Fortran":
            line = _fortran_line(text, self.model)
            toks = _tokenize(line)
            spelling, end, toks = self.fortran_name(toks)
        else:
            line = _c_line(text, self.model)
            toks = _tokenize(line)
            spelling, end, toks = self.c_name(toks)
        if spelling is None:
            words = [t.text for t in toks[:3] if t.kind == "name"]
            raise GrammarError("unknown_directive",
                               f"no directive named {' '.join(words)!r}"
                               if words else f"no directive in {line!r}")
        i = 0
        dargs = None
        if i < len(toks) and toks[i].text == "(":
            j = _close_paren(toks, i, spelling)
            dargs = line[toks[i].end:toks[j].start]
            i = j + 1
        raws = []
        while i < len(toks):
            t = toks[i]
            if t.text == ",":
                i += 1
                continue
            if t.kind != "name":
                raise GrammarError("unknown_clause",
                                   f"expected a clause at {line[t.start:]!r}")
            if i + 1 < len(toks) and toks[i + 1].text == "(":
                j = _close_paren(toks, i + 1, t.text)
                raws.append(_Raw(t.text, line[toks[i + 1].end:toks[j].start]))
                i = j + 1
            else:
                raws.append(_Raw(t.text, None))
                i += 1
        return self.resolve(spelling, end, dargs, raws)

    @staticmethod
    def _leading_names(toks):
        run = []
        for t in toks:
            if t.kind != "name":
                break
            run.append(t)
        return run

    def c_name(self, toks):
        """(spelling, end, remaining tokens); C names need their blanks."""
        words = [t.text for t in self._leading_names(toks)]
        for k in range(min(len(words), self.max_words), 0, -1):
            s = " ".join(words[:k])
            if s in self.index:
                return s, False, toks[k:]
        return None, False, toks

    def fortran_name(self, toks):
        """(spelling, end, remaining tokens). The longest spelling matching
        the leading names with blanks removed wins, and it must end at a
        blank (free form: a name never runs into the first clause). A
        leading "end" may be run together with the name ("enddo")."""
        run = self._leading_names(toks)
        text = "".join(t.text for t in run)
        bounds, cum = set(), 0
        for t in run:
            cum += len(t.text)
            bounds.add(cum)

        def find(start):
            """Longest name from `start` and the number of tokens it spans."""
            for k in range(len(text), start, -1):
                if k in bounds and text[start:k] in self.compact:
                    return k, toks[sum(1 for b in bounds if b <= k):]
            return None, None

        start, end = 0, False
        k, rest = find(0)
        if k is None and text.startswith("end"):
            start, end = 3, True
            k, rest = find(3)
        if k is None:
            return None, False, toks
        return self.compact[text[start:k]], end, rest

    def resolve(self, spelling, end, dargs, raws) -> Directive:
        keys = self.index[spelling]
        keys = [k for k in keys if not self.sk.directive(k).languages
                or self.lang in self.sk.directive(k).languages]
        if not keys:
            raise GrammarError("wrong_language",
                               f"{spelling!r} is not a {self.lang} directive")
        keys = [k for k in keys if spelling_valid(self.sk, self.grammar, k,
                                                  spelling, self.version)]
        if not keys:
            raise GrammarError("version", f"{spelling!r} is not valid in "
                               f"{spec_name(self.version)}")
        if end:
            keys = [k for k in keys if self.lang == "Fortran"
                    and self.sk.directive(k).association in _END_ASSOCIATIONS]
            # A delimited begin directive's paired end directive
            # drops the "begin" (5.2 §7.4.4: begin metadirective ... end
            # metadirective)
            if not keys and self.lang == "Fortran" and \
                    f"begin {spelling}" in self.sk.directives and \
                    self.sk.directive(f"begin {spelling}").association \
                    in _END_ASSOCIATIONS:
                keys = [f"begin {spelling}"]
            if not keys:
                raise GrammarError("unknown_directive",
                                   f"{spelling!r} has no end directive")
        first = None
        for key in keys:
            try:
                return self.build(key, end, dargs, raws)
            except GrammarError as err:
                first = first or err
        raise first

    def build(self, key, end, dargs, raws) -> Directive:
        spec = self.sk.directive(key)
        m = self.model
        atoms = {directive_atom(key, m)}
        args = []
        if dargs is not None:
            if spec.association not in _ARG_ASSOCIATIONS \
                    and base_name(key) not in (
                        _ARG_DIRECTIVES if m == "omp"
                        else _ACC_ARG_DIRECTIVES):
                raise GrammarError("bad_argument",
                                   f"{key!r} takes no directive argument")
            args = [p for p in _split(dargs, ",")[::2]]
            if not all(args):
                raise GrammarError("bad_argument",
                                   f"empty item in {key}({dargs})")
        allowed = self.allowed(key)
        by_spelling = {}
        for c in allowed:
            for s in self.sk.clauses[c]["spellings"]:
                by_spelling[s["text"]] = c
        clauses, present, counts = [], [], {}
        for raw in raws:
            ckey = by_spelling.get(raw.name)
            if ckey is None:
                if raw.name in self.clause_spellings:
                    raise GrammarError("clause_not_allowed",
                                       f"{raw.name} is not allowed on {key}")
                raise GrammarError("unknown_clause",
                                   f"no clause named {raw.name!r}")
            rule = allowed[ckey]
            if not rule_valid(rule, self.version):
                raise GrammarError("version", f"{raw.name} on {key} is not "
                                   f"valid in {spec_name(self.version)}")
            entry = self.grammar.clauses.get(ckey)
            if end and not (entry and entry.end_clause):
                raise GrammarError("clause_not_allowed",
                                   f"{raw.name} is not allowed on end {key}")
            counts[ckey] = counts.get(ckey, 0) + 1
            if rule.once and counts[ckey] > 1:
                raise GrammarError("clause_repeated",
                                   f"{raw.name} may appear once on {key}")
            present.append(ckey)
            clause, feats = self.clause(key, raw, entry)
            clauses.append(clause)
            # OpenMP atoms keep the spelling; an OpenACC alias spelling
            # (pcopy, present_or_copy, dtype) names its clause
            cname = raw.name if m == "omp" else base_name(ckey)
            atoms.add(f"{m}.clause.{cname}")
            atoms.update(f"{m}.clause.{cname}.{f}" for f in feats)
        groups = {}
        for ckey in present:
            g = allowed[ckey].exclusive_group
            if g is not None:
                groups.setdefault(g, set()).add(ckey)
        for g, members in groups.items():
            if len(members) > 1:
                raise GrammarError("clause_not_allowed",
                                   f"{', '.join(sorted(members))} are "
                                   f"mutually exclusive on {key}")
        if spec.required and not end and not spec.required & set(present):
            raise GrammarError("missing_required",
                               f"{key} needs one of "
                               f"{', '.join(sorted(spec.required))}")
        return Directive(key, clauses, frozenset(atoms), end, args)

    def clause(self, key, raw: _Raw, entry) -> tuple[Clause, set[str]]:
        form = entry.form_for(key, self.version,
                              "c" if self.lang == "C" else "f90") \
            if entry else None
        if form is None:
            return self.generic(raw), set()
        where = f"{raw.name}({raw.text}) on {key}" if raw.text is not None \
            else f"{raw.name} on {key}"
        specs = [None] if raw.text is None else (
            _split(raw.text, ";")[::2] if form.multiple_specs else [raw.text])
        matcher = _Matcher(form, self.names, self.lang)
        clause, feats = Clause(raw.name), set()
        for spec_text in specs:
            caps = None
            for alt in form.syntax:
                if alt and alt[0].kind == "none":
                    if spec_text is None:
                        caps = ()
                        break
                    continue
                if spec_text is None:
                    continue
                caps = matcher.run(alt, _split(spec_text, ",:;"))
                if caps is not None:
                    break
            if caps is None:
                raise GrammarError(
                    "bad_argument", f"{where} does not match "
                    f"{form.syntax_text!r} ({form.citation})")
            for role, text, feat in caps:
                if text is not None:
                    (clause.args if role == "arg"
                     else clause.modifiers).append(text)
                if feat:
                    feats.add(feat)
        return clause, feats

    @staticmethod
    def generic(raw: _Raw) -> Clause:
        if raw.text is None:
            return Clause(raw.name)
        flat = _split(raw.text, ",:")
        if ":" in flat[1::2]:
            cut = flat.index(":")
            return Clause(raw.name, flat[cut + 1::2], flat[:cut:2])
        return Clause(raw.name, flat[::2])


# Parsers by (id(skeleton), id(grammar), lang, version). Each value keeps its
# skeleton and grammar alive, so an id cannot be reused by a reloaded catalog
# while its entry exists; the identity check guards against it anyway.
_PARSERS: dict[tuple, tuple] = {}


def _parser(sk: Skeleton, grammar: Grammar, lang: str,
            version: int) -> _Parser:
    key = (id(sk), id(grammar), lang, version)
    hit = _PARSERS.get(key)
    if hit is None or hit[0] is not sk or hit[1] is not grammar:
        if len(_PARSERS) >= 64:
            _PARSERS.clear()
        hit = _PARSERS[key] = (sk, grammar, _Parser(sk, grammar, lang,
                                                    version))
    return hit[2]


def parse_directive(text: str, lang: str, version: int,
                    skeleton: Skeleton | None = None,
                    grammar: Grammar | None = None) -> Directive:
    """Parse one directive (sentinel included) at an OpenMP version (52, 60)
    or the OpenACC version (34)."""
    m = model_of(version)
    return _parser(skeleton or default_skeleton(m),
                   grammar or default_grammar(m),
                   _lang(lang), version).parse(text)
