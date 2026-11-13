"""Catalog data classes and loading, the clause grammar, and the slice.

Atom ids name the features the generator and the report track:
``omp.directive.<name>``, ``omp.clause.<name>`` and
``omp.clause.<name>.<feature>`` (an argument form or modifier from
``catalog/omp/clauses.yaml``, e.g. ``omp.clause.map.always``). Semantic atoms
(``catalog/omp/semantic_atoms.yaml``) name behaviour no syntax form carries.
OpenACC uses the prefix ``acc`` and ``catalog/acc/``. The version selects the
catalog: 50, 52, 60 for OpenMP, 34 for OpenACC (``model_of``). ``lang`` is
"f90" or "c".
The slice is the directives in ``SLICE_BASE`` plus every skeleton directive
whose leaf constructs contain one of them, and the clauses the skeleton
allows on them. ``load_grammar`` loads ``catalog/omp/spec_overrides.yaml``
(where the spec overrides the TableGen skeleton) into ``Grammar`` and checks
it; ``Grammar.allowed`` gives a directive's effective clause rules."""
import dataclasses
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from offload.engine.root import ROOT  # noqa: E402

CATALOG_ROOT = ROOT / "catalog"
CATALOG_DIR = CATALOG_ROOT / "omp"
MODELS = ("omp", "acc")
# OpenACC spec versions (the OpenMP ones are 50, 52 and 60); the model of a
# program, atom or rule follows from its version
ACC_VERSIONS = (34,)
MODEL_NAME = {"omp": "OpenMP", "acc": "OpenACC"}


def model_of(version: int) -> str:
    """"acc" for an OpenACC spec version (34), else "omp" (50, 52, 60)."""
    return "acc" if version in ACC_VERSIONS else "omp"


def catalog_dir(model: str = "omp") -> Path:
    if model not in MODELS:
        raise ValueError(f"unknown model {model!r}")
    return CATALOG_ROOT / model


LANGS = ("f90", "c")


def norm_lang(lang: str) -> str:
    """"f90" or "c" for the language spellings the project uses ("f90",
    "fortran", "f"; "c")."""
    low = (lang or "f90").lower()
    if low in ("f90", "fortran", "f"):
        return "f90"
    if low == "c":
        return "c"
    raise ValueError(f"unknown language {lang!r}")


# The skeleton's language names (TableGen) of each catalog language.
SKELETON_LANG = {"f90": "Fortran", "c": "C"}


def spec_name(version: int) -> str:
    """'OpenMP 5.2' / 'OpenACC 3.4'."""
    return f"{MODEL_NAME[model_of(version)]} {version // 10}.{version % 10}"


class AmbiguousSpelling(Exception):
    """More than one directive matches a spelling at a version."""


@dataclass(frozen=True)
class Spelling:
    text: str
    min_ver: int
    max_ver: int | None


@dataclass(frozen=True)
class ClauseRule:
    min_ver: int
    max_ver: int | None
    once: bool
    exclusive_group: str | None


@dataclass(frozen=True)
class DirectiveSpec:
    """`required` means "at least one of" (flang semantics), not "all of"."""
    name: str
    spellings: list[Spelling]
    languages: set[str]  # empty means both C and Fortran
    association: str
    leaves: list[str]
    allowed: dict[str, ClauseRule]
    required: set[str]


@dataclass
class Skeleton:
    directives: dict[str, DirectiveSpec] = field(default_factory=dict)
    clauses: dict[str, dict] = field(default_factory=dict)

    def directive(self, name: str) -> DirectiveSpec:
        return self.directives[name]

    def lookup_all(self, spelling: str, version: int) -> list[DirectiveSpec]:
        """Every directive having `spelling` valid at `version`."""
        return [spec for spec in self.directives.values()
                if any(s.text == spelling and s.min_ver <= version
                       and (s.max_ver is None or version <= s.max_ver)
                       for s in spec.spellings)]

    def lookup(self, spelling: str, version: int) -> DirectiveSpec | None:
        """The single match, None if none; AmbiguousSpelling if several."""
        found = self.lookup_all(spelling, version)
        if len(found) > 1:
            names = ", ".join(sorted(self.key_of(f) for f in found))
            raise AmbiguousSpelling(
                f"{spelling!r} at {version} matches: {names}")
        return found[0] if found else None

    def key_of(self, spec: DirectiveSpec) -> str:
        return next(k for k, v in self.directives.items() if v is spec)


def _spec(name: str, d: dict) -> DirectiveSpec:
    return DirectiveSpec(
        name=name,
        spellings=[Spelling(s["text"], s["min_ver"], s["max_ver"])
                   for s in d["spellings"]],
        languages=set(d["languages"]),
        association=d["association"],
        leaves=list(d["leaves"]),
        allowed={c: ClauseRule(**r) for c, r in d["allowed"].items()},
        required=set(d["required"]),
    )


def skeleton_from_dict(data: dict) -> Skeleton:
    return Skeleton(
        directives={n: _spec(n, d) for n, d in data["directives"].items()},
        clauses=dict(data["clauses"]),
    )


def load_skeleton(path: Path) -> Skeleton:
    return skeleton_from_dict(yaml.safe_load(Path(path).read_text()))


# --- clause grammar (catalog/omp/clauses.yaml) -------------------------------

DIRECTIVE_NAME_CLASS = "directive-name"


@dataclass(frozen=True)
class Node:
    """One element of a clause syntax.

    kind is one of none, list, expr, expr_list, enum, mods, lit, opt. `values`
    holds the enum keywords, the modifier class names or the literal; `body`
    holds the elements of an optional part.
    """
    kind: str
    values: tuple = ()
    label: str | None = None
    body: tuple = ()


@dataclass(frozen=True)
class ModifierClass:
    name: str
    keywords: tuple = ()
    identifier: bool = False
    complex: str | None = None
    expr: bool = False
    one_of: bool = False
    required: bool = False
    ultimate: bool = False
    exclusive: bool = False
    out_of_slice: bool = False  # parsed, but no slice atom
    # OpenMP 5.0 argument forms: a complex modifier whose
    # parentheses hold the clause's list (linear's ``val(x)``: the atom is
    # the modifier, the items are the clause's arguments), and a list item
    # written ``ident(args)`` (uses_allocators' ``alloc(traits)``: the atom
    # is `complex`, the argument is the identifier)
    wraps_list: bool = False
    call: bool = False


@dataclass(frozen=True)
class ClauseForm:
    since: int
    citation: str
    syntax_text: str
    syntax: tuple  # alternatives, each a tuple of Node
    modifiers: dict
    directives: frozenset | None = None
    multiple_specs: bool = False
    modifier_commas_optional: bool = False
    langs: frozenset | None = None  # Only these languages

    def atom_features(self) -> set[str]:
        """Every atom feature name this form can produce."""
        out: set[str] = set()

        def walk(nodes):
            for n in nodes:
                if n.label:
                    out.add(n.label)
                if n.kind == "enum":
                    out.update(feature(v) for v in n.values)
                elif n.kind == "mods":
                    for cls in n.values:
                        out.update(self.class_features(cls))
                elif n.kind == "opt":
                    walk(n.body)

        for alt in self.syntax:
            walk(alt)
        return out

    def class_features(self, cls: str) -> set[str]:
        if cls == DIRECTIVE_NAME_CLASS:
            return {"directive_name"}
        mc = self.modifiers[cls]
        if mc.out_of_slice:
            return set()
        out = {feature(k) for k in mc.keywords}
        if mc.complex:
            out.add(feature(mc.complex))
        if mc.expr:
            out.add(feature(mc.name))
        return out


@dataclass(frozen=True)
class ClauseGrammar:
    name: str
    status: str
    forms: tuple
    end_clause: bool = False

    def form_for(self, directive: str, version: int,
                 lang: str = "f90") -> ClauseForm | None:
        """The form with the largest `since` <= version (else the earliest)
        among the forms that apply on `directive` in `lang` (a form with
        ``langs`` applies only in those languages)."""
        lang = norm_lang(lang)
        forms = [f for f in self.forms
                 if (f.directives is None or directive in f.directives)
                 and (f.langs is None or lang in f.langs)]
        # a form naming the directive wins over a general one (OpenACC:
        # gang, worker, vector on routine; private, reduction on loop)
        named = [f for f in forms if f.directives is not None]
        forms = named or forms
        if not forms:
            return None
        older = [f for f in forms if f.since <= version]
        if older:
            return max(older, key=lambda f: f.since)
        return min(forms, key=lambda f: f.since)


@dataclass(frozen=True)
class DirectiveSince:
    """The spec version that introduced a directive, where TableGen has no
    directive-level introduction version (every spelling from 0)."""
    directive: str
    since: int
    citation: str
    status: str


@dataclass(frozen=True)
class ExtraSpelling:
    """A directive spelling the spec allows beyond the TableGen range."""
    directive: str
    spelling: str
    since: int
    citation: str
    status: str


@dataclass(frozen=True)
class RuleOverride:
    """The spec removes a skeleton clause rule, sets its version bounds
    (`since`/`until` each replace the skeleton's, narrowing or widening), or
    adds a clause the skeleton lacks (valid `since`..`until`, `once` as
    given)."""
    directive: str
    clause: str
    citation: str
    status: str
    remove: bool = False
    add: bool = False
    once: bool = False
    since: int | None = None
    until: int | None = None


@dataclass
class Grammar:
    """Clause grammar plus the spec's overrides of the TableGen skeleton."""
    clauses: dict[str, ClauseGrammar] = field(default_factory=dict)
    spellings: list[ExtraSpelling] = field(default_factory=list)
    rule_overrides: dict[tuple[str, str], RuleOverride] = field(
        default_factory=dict)
    directive_since: dict[str, DirectiveSince] = field(default_factory=dict)
    # (for-twin, clause) overrides mirrored from do compounds
    mirrored: list = field(default_factory=list)
    # Clauses the spec lets repeat on a directive where TableGen
    # says once (defaultmap: once per variable category, which the rules'
    # defaultmap-map predicates check); clause name -> citation
    repeatable: dict = field(default_factory=dict)

    def allowed(self, sk: Skeleton, directive: str) -> dict[str, ClauseRule]:
        """The directive's clause rules after the spec's overrides."""
        out = dict(sk.directive(directive).allowed)
        for clause in self.repeatable:
            if clause in out and out[clause].once:
                r = out[clause]
                out[clause] = ClauseRule(r.min_ver, r.max_ver, False,
                                         r.exclusive_group)
        for (d, clause), o in self.rule_overrides.items():
            if d != directive:
                continue
            if o.remove:
                del out[clause]
            elif o.add:
                out[clause] = ClauseRule(o.since or 0, o.until, o.once, None)
            else:
                # `since`/`until` replace the skeleton's bounds (a bound left
                # out keeps the skeleton's), so an override may narrow or
                # widen the range: a widening with max() would be a silent
                # no-op.
                rule = out[clause]
                lo = rule.min_ver if o.since is None else o.since
                hi = rule.max_ver if o.until is None else o.until
                out[clause] = ClauseRule(lo, hi, rule.once,
                                         rule.exclusive_group)
        return out


_OPS = {"+": "plus", "-": "minus", "*": "times",
        # C reduction identifiers: the same atoms as the Fortran
        # identifiers with the same combiner (5.2 §5.5.5 Table 5.1-5.2)
        "&&": "and", "||": "or", "&": "iand", "|": "ior", "^": "ieor"}


def feature(word: str) -> str:
    """Atom feature name for a keyword, class name or label."""
    if word in _OPS:
        return _OPS[word]
    return word.lower().replace(".", "").replace("-", "_").replace(" ", "_")


_DSL_TOKEN = re.compile(
    r"\s*(?:(enum|modifiers)\[([^\]]*)\]|'([:,])'|(\[)|(\])|(\|)|@(\w+)"
    r"|(none|list|expr_list|expr))")


def parse_syntax(text: str) -> tuple:
    """Parse a clauses.yaml syntax string into alternatives of Nodes."""
    toks = []
    pos = 0
    text = text.strip()
    while pos < len(text):
        m = _DSL_TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise ValueError(f"bad syntax {text!r} at {text[pos:]!r}")
        toks.append(m)
        pos = m.end()
        while pos < len(text) and text[pos].isspace():
            pos += 1

    def seq(i):
        nodes = []
        while i < len(toks):
            m = toks[i]
            if m.group(5) or m.group(6):  # ']' or '|'
                break
            if m.group(4):  # '['
                body, i = seq(i + 1)
                if i >= len(toks) or not toks[i].group(5):
                    raise ValueError(f"unclosed [ in {text!r}")
                nodes.append(Node("opt", body=tuple(body)))
            elif m.group(7):  # @label
                if not nodes:
                    raise ValueError(f"label without element in {text!r}")
                nodes[-1] = Node(nodes[-1].kind, nodes[-1].values,
                                 m.group(7), nodes[-1].body)
            elif m.group(1):
                values = tuple(v.strip() for v in m.group(2).split(",")
                               if v.strip())
                nodes.append(Node("enum" if m.group(1) == "enum" else "mods",
                                  values))
            elif m.group(3):
                nodes.append(Node("lit", (m.group(3),)))
            else:
                nodes.append(Node(m.group(8)))
            i += 1
        return nodes, i

    alts = []
    i = 0
    while True:
        nodes, i = seq(i)
        if any(n.kind == "none" for n in nodes) and len(nodes) != 1:
            raise ValueError(f"'none' must stand alone in {text!r}")
        alts.append(tuple(nodes))
        if i >= len(toks):
            break
        if not toks[i].group(6):
            raise ValueError(f"unexpected {toks[i].group(0)!r} in {text!r}")
        i += 1
    return tuple(alts)


def _mod_classes(nodes) -> set[str]:
    out = set()
    for n in nodes:
        if n.kind == "mods":
            out.update(n.values)
        elif n.kind == "opt":
            out |= _mod_classes(n.body)
    return out


def _form(name: str, d: dict) -> ClauseForm:
    syntax = parse_syntax(d["syntax"])
    mods = {}
    for k, v in (d.get("modifiers") or {}).items():
        v = dict(v)
        keywords = tuple(str(x) for x in v.pop("keywords", ()))
        mods[k] = ModifierClass(name=k, keywords=keywords, **v)
    used = set().union(*(_mod_classes(a) for a in syntax))
    unknown = used - set(mods) - {DIRECTIVE_NAME_CLASS}
    if unknown:
        raise ValueError(f"{name}: undefined modifier classes {unknown}")
    dirs = d.get("directives")
    langs = d.get("langs")
    if langs is not None and not set(langs) <= set(LANGS):
        raise ValueError(f"{name}: unknown langs {langs}")
    return ClauseForm(
        since=int(d["since"]), citation=d["citation"],
        syntax_text=d["syntax"], syntax=syntax, modifiers=mods,
        directives=frozenset(dirs) if dirs else None,
        multiple_specs=bool(d.get("multiple_specs", False)),
        modifier_commas_optional=bool(d.get("modifier_commas_optional",
                                            False)),
        langs=frozenset(langs) if langs is not None else None)


def _check_overrides(grammar: Grammar, sk: Skeleton) -> None:
    """Every override must name an existing directive and clause, so that a
    typo cannot silently do nothing."""
    for e in grammar.spellings:
        if e.directive not in sk.directives:
            raise ValueError(f"spec override: unknown directive "
                             f"{e.directive!r} in directive_spellings")
    for d, o in grammar.directive_since.items():
        if d not in sk.directives:
            raise ValueError(f"spec override: unknown directive {d!r} in "
                             "directive_versions")
        if all(s.min_ver >= o.since for s in sk.directive(d).spellings):
            raise ValueError(f"spec override: {d!r} since {o.since} leaves "
                             "the skeleton's spellings unchanged")
    for (d, c), o in grammar.rule_overrides.items():
        if d not in sk.directives:
            raise ValueError(f"spec override: unknown directive {d!r}")
        if c not in sk.clauses:
            raise ValueError(f"spec override: unknown clause {c!r} on {d!r}")
        allowed = c in sk.directive(d).allowed
        if o.add and allowed:
            raise ValueError(f"spec override adds {c!r} to {d!r}, which the "
                             "skeleton already allows")
        if not o.add and not allowed:
            raise ValueError(f"spec override changes {c!r} on {d!r}, which "
                             "the skeleton does not allow")
        if not o.add and not o.remove:
            rule = sk.directive(d).allowed[c]
            if (o.since is None or o.since == rule.min_ver) and (
                    o.until is None or o.until == rule.max_ver):
                raise ValueError(f"spec override of {c!r} on {d!r} leaves "
                                 "the skeleton's version range unchanged")


def grammar_from_dict(data: dict, overrides: dict | None = None,
                      skeleton: Skeleton | None = None) -> Grammar:
    """`data` is clauses.yaml; `overrides` is spec_overrides.yaml. With a
    skeleton, the overrides are checked against it (ValueError)."""
    overrides = overrides or {}
    clauses = {
        name: ClauseGrammar(
            name=name, status=e["status"],
            forms=tuple(_form(name, f) for f in e["forms"]),
            end_clause=bool(e.get("end_clause", False)))
        for name, e in data["clauses"].items()}
    spellings = [ExtraSpelling(s["directive"], s["spelling"], int(s["since"]),
                               s["citation"], s["status"])
                 for s in overrides.get("directive_spellings") or []]
    since: dict[str, DirectiveSince] = {}
    for e in overrides.get("directive_versions") or []:
        o = DirectiveSince(e["directive"], int(e["since"]), e["citation"],
                           e["status"])
        if o.directive in since:
            raise ValueError(f"spec override: duplicate directive_versions "
                             f"entry for {o.directive!r}")
        since[o.directive] = o
    rules: dict[tuple[str, str], RuleOverride] = {}
    for r in overrides.get("clause_rules") or []:
        o = RuleOverride(r["directive"], r["clause"], r["citation"],
                         r["status"], bool(r.get("remove", False)),
                         bool(r.get("add", False)), bool(r.get("once", False)),
                         r.get("since"), r.get("until"))
        if o.remove + o.add > 1 or not (o.remove or o.add or o.since
                                        is not None or o.until is not None):
            raise ValueError(f"spec override {o} must remove, add or narrow")
        if (o.directive, o.clause) in rules:
            raise ValueError(f"spec override: duplicate entry for "
                             f"{o.clause!r} on {o.directive!r}")
        rules[(o.directive, o.clause)] = o
    grammar = Grammar(clauses, spellings, rules, since)
    for name, e in (overrides.get("repeatable_clauses") or {}).items():
        if not (e or {}).get("citation"):
            raise ValueError(f"spec override repeatable clause {name!r} "
                             "needs a citation")
        grammar.repeatable[name] = e["citation"]
    if skeleton is not None:
        _check_overrides(grammar, skeleton)
        _mirror_for(grammar, skeleton)
    return grammar


def for_twin(key: str) -> str | None:
    """The C ``for`` spelling of a Fortran ``do`` compound key (``parallel
    do simd`` -> ``parallel for simd``), else None."""
    words = key.split(" ")
    if "do" not in words:
        return None
    return " ".join("for" if w == "do" else w for w in words)


def _mirror_for(grammar: Grammar, sk: Skeleton) -> None:
    """Apply each clause-rule override of a ``do`` compound to its
    C ``for`` twin as well. The worksharing-loop construct is one construct
    spelled ``do`` in Fortran and ``for`` in C (5.2 §11.5, 6.0 §13.6), and
    the spec's clause lists (and the cited restrictions) are the same for
    both, so the override's citation holds for the twin. An override is
    mirrored only where it changes the twin's skeleton rule (an addition
    the twin's TableGen record already has, a removal of a clause it does
    not have, or a re-range to its own bounds is skipped); an explicit
    override of the twin wins. ``Grammar.mirrored`` lists the (twin,
    clause) pairs."""
    added = []
    for (d, c), o in list(grammar.rule_overrides.items()):
        twin = for_twin(d)
        if twin is None or twin not in sk.directives or \
                (twin, c) in grammar.rule_overrides:
            continue
        allowed = sk.directive(twin).allowed
        if o.add and c in allowed or (not o.add and c not in allowed):
            continue
        if not o.add and not o.remove:
            rule = allowed[c]
            if (o.since is None or o.since == rule.min_ver) and (
                    o.until is None or o.until == rule.max_ver):
                continue
        grammar.rule_overrides[(twin, c)] = dataclasses.replace(
            o, directive=twin)
        added.append((twin, c))
    grammar.mirrored = sorted(added)


def load_grammar(path: Path, overrides: Path | None = None,
                 skeleton: Skeleton | None = None) -> Grammar:
    """Load clauses.yaml and the spec overrides (by default the
    spec_overrides.yaml beside it), checked against the skeleton (by default
    the skeleton.yaml beside it)."""
    path = Path(path)
    overrides = Path(overrides) if overrides else (
        path.parent / "spec_overrides.yaml")
    over = yaml.safe_load(overrides.read_text()) if overrides.is_file() \
        else None
    if skeleton is None and (path.parent / "skeleton.yaml").is_file():
        skeleton = load_skeleton(path.parent / "skeleton.yaml")
    return grammar_from_dict(yaml.safe_load(path.read_text()), over, skeleton)


def _skeleton_clauses(sk: Skeleton, overrides: Path) -> Skeleton:
    """The skeleton with the clauses ``skeleton_clauses`` of the spec
    overrides adds (a clause TableGen lacks: OpenACC atomic's update)."""
    if not overrides.is_file():
        return sk
    data = yaml.safe_load(overrides.read_text()) or {}
    # Directives TableGen lacks (begin metadirective), each a
    # copy of another directive's clause rules with its own association and
    # spellings; and languages TableGen gets wrong (declare variant has a
    # Fortran form since 5.0)
    for name, e in (data.get("skeleton_directives") or {}).items():
        if name in sk.directives:
            raise ValueError(f"spec override adds directive {name!r}, which "
                             "the skeleton already has")
        if not e.get("citation"):
            raise ValueError(f"spec override directive {name!r} needs a "
                             "citation")
        like = sk.directive(e["clauses_of"])
        sk.directives[name] = DirectiveSpec(
            name=name,
            spellings=[Spelling(t["text"], int(t["min_ver"]), t.get("max_ver"))
                       for t in e["spellings"]],
            languages=set(e.get("languages") or []),
            association=e["association"], leaves=[],
            allowed=dict(like.allowed), required=set(like.required))
    for name, e in (data.get("directive_languages") or {}).items():
        if not e.get("citation"):
            raise ValueError(f"spec override languages of {name!r} need a "
                             "citation")
        spec = sk.directive(name)
        new = set(e.get("languages") or [])
        if new == spec.languages:
            raise ValueError(f"spec override languages of {name!r} change "
                             "nothing")
        sk.directives[name] = dataclasses.replace(spec, languages=new)
    extra = data.get("skeleton_clauses") or {}
    for name, e in extra.items():
        if name in sk.clauses:
            raise ValueError(f"spec override adds clause {name!r}, which "
                             "the skeleton already has")
        if not e.get("citation"):
            raise ValueError(f"spec override clause {name!r} needs a "
                             "citation")
        sk.clauses[name] = {"spellings": [
            {"text": t, "min_ver": 0, "max_ver": None}
            for t in e.get("spellings") or [name]]}
    return sk


@lru_cache(maxsize=None)
def default_skeleton(model: str = "omp") -> Skeleton:
    d = catalog_dir(model)
    return _skeleton_clauses(load_skeleton(d / "skeleton.yaml"),
                             d / "spec_overrides.yaml")


@lru_cache(maxsize=None)
def default_grammar(model: str = "omp") -> Grammar:
    d = catalog_dir(model)
    return load_grammar(d / "clauses.yaml", skeleton=default_skeleton(model))


# --- versions and the slice ----------------------------------------------------

def base_name(key: str) -> str:
    """Skeleton key without a TableGen variant suffix ("ordered (Block)")."""
    return key.split(" (", 1)[0]


def directive_atom(key: str, model: str = "omp") -> str:
    return f"{model}.directive." + base_name(key).replace(" ", "_")


def spelling_valid(sk: Skeleton, grammar: Grammar, key: str, spelling: str,
                   version: int) -> bool:
    intro = grammar.directive_since.get(key)
    if intro is not None and version < intro.since:
        return False
    if any(s.text == spelling and s.min_ver <= version
           and (s.max_ver is None or version <= s.max_ver)
           for s in sk.directive(key).spellings):
        return True
    return any(e.directive == key and e.spelling == spelling
               and e.since <= version for e in grammar.spellings)


def rule_valid(rule: ClauseRule, version: int) -> bool:
    return rule.min_ver <= version and (rule.max_ver is None
                                        or version <= rule.max_ver)


SLICE_BASE = ("target", "target data", "target enter data", "target exit data",
              "target update", "teams", "distribute", "parallel do", "loop",
              "declare target", "requires")


# C: the worksharing-loop construct is spelled ``for``, and the
# delimited form of declare target (5.2 §7.8.2, 6.0 §9.9.2; C/C++ only) is
# a directive of its own (its paired ``end declare target`` is its end)
SLICE_BASE_C = tuple("parallel for" if b == "parallel do" else b
                     for b in SLICE_BASE) + ("begin declare target",)


# OpenACC: every directive but TableGen's placeholder
ACC_NOT_IN_SLICE = ("unknown",)


def _in_lang(d: DirectiveSpec, lang: str) -> bool:
    """The skeleton record exists in the language (no languages: both)."""
    return not d.languages or SKELETON_LANG[lang] in d.languages


def slice_directives(sk: Skeleton, model: str = "omp",
                     lang: str = "f90") -> list[str]:
    """Skeleton keys of the slice's directives in `lang`, sorted."""
    lang = norm_lang(lang)
    if model == "acc":
        # The OpenACC C slice (NVHPC nvc) has the same directives
        # minus any that are Fortran only
        other = {"C"} if lang == "f90" else {"Fortran"}
        return sorted(k for k, d in sk.directives.items()
                      if d.languages != other and k not in ACC_NOT_IN_SLICE)
    base = SLICE_BASE_C if lang == "c" else SLICE_BASE
    seqs = [sk.directive(b).leaves or [b] for b in base]

    def contains(leaves, s):
        return any(leaves[i:i + len(s)] == s
                   for i in range(len(leaves) - len(s) + 1))

    return sorted(k for k, d in sk.directives.items()
                  if _in_lang(d, lang)
                  and (k in base
                       or (d.leaves and any(contains(d.leaves, s)
                                            for s in seqs))))


def slice_clauses(sk: Skeleton, version: int,
                  grammar: Grammar | None = None,
                  lang: str = "f90") -> list[str]:
    """Clauses allowed on some slice directive at `version` (after the spec
    overrides), sorted."""
    model = model_of(version)
    grammar = grammar or default_grammar(model)
    return sorted({c for k in slice_directives(sk, model, lang)
                   for c, rule in grammar.allowed(sk, k).items()
                   if not c.startswith("ompx_") and rule_valid(rule, version)})


@dataclass(frozen=True)
class SemanticAtom:
    """An atom no clause syntax carries (catalog/omp/semantic_atoms.yaml):
    behaviour the spec defines that a program exercises through its data."""
    atom: str
    clause: str
    since: int
    citations: dict
    status: str
    behaviour: str
    langs: frozenset = frozenset(LANGS)  


def semantic_atoms_from_dict(data: dict, model: str = "omp"
                             ) -> dict[str, SemanticAtom]:
    out = {}
    for atom, e in (data.get("atoms") or {}).items():
        parts = atom.split(".")
        if len(parts) != 4 or parts[:2] != [model, "clause"] \
                or parts[2] != e["clause"]:
            raise ValueError(f"semantic atom {atom!r} must be "
                             f"{model}.clause.{e['clause']}.<feature>")
        out[atom] = SemanticAtom(
            atom, e["clause"], int(e["since"]),
            {int(v): c for v, c in e["citations"].items()}, e["status"],
            e["behaviour"], frozenset(e.get("langs") or LANGS))
        if not out[atom].langs <= set(LANGS):
            raise ValueError(f"semantic atom {atom!r}: unknown langs")
    return out


@lru_cache(maxsize=None)
def semantic_atoms(model: str | None = None) -> dict[str, SemanticAtom]:
    """The catalog's semantic atoms (atom id -> entry) of one model, or of
    both (None: the atom ids carry the model)."""
    if model is None:
        return {**semantic_atoms("omp"), **semantic_atoms("acc")}
    path = catalog_dir(model) / "semantic_atoms.yaml"
    if not path.is_file():
        return {}
    return semantic_atoms_from_dict(yaml.safe_load(path.read_text()), model)


@lru_cache(maxsize=None)
def out_of_scope(model: str = "omp") -> dict[str, dict]:
    """catalog/<model>/out_of_scope.yaml: atom id -> {versions,
    langs, reason, spec: {version: {cite, quote}}, status}: the atoms
    outside the device-offload scope (host execution only)."""
    path = catalog_dir(model) / "out_of_scope.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    out = {}
    for atom, e in (data.get("atoms") or {}).items():
        if not atom.startswith(f"{model}.") or not e.get("reason") \
                or not e.get("versions"):
            raise ValueError(f"out_of_scope entry {atom!r} needs the model "
                             "prefix, versions and a reason")
        e = dict(e, versions=[int(v) for v in e["versions"]],
                 langs=list(e.get("langs") or LANGS),
                 spec={int(v): c for v, c in (e.get("spec") or {}).items()})
        out[atom] = e
    return out


def out_of_scope_atoms(version: int, lang: str = "f90") -> dict[str, dict]:
    """The out-of-scope atoms (out_of_scope) at `version` in `lang`."""
    lang = norm_lang(lang)
    return {a: e for a, e in out_of_scope(model_of(version)).items()
            if version in e["versions"] and lang in e["langs"]}


def slice_atoms(version: int, sk: Skeleton | None = None,
                grammar: Grammar | None = None,
                lang: str = "f90", in_scope: bool = True) -> list[str]:
    """Every atom id of the slice at `version` in `lang`, sorted and
    duplicate-free: the directives and clause forms, plus each semantic
    atom of the language whose clause is in the slice at `version` (from
    its `since`). `in_scope` (default): without the atoms outside the
    device-offload scope (out_of_scope_atoms)."""
    m = model_of(version)
    lang = norm_lang(lang)
    sk = sk or default_skeleton(m)
    grammar = grammar or default_grammar(m)
    atoms: set[str] = set()
    for key in slice_directives(sk, m, lang):
        spec = sk.directive(key)
        if not any(spelling_valid(sk, grammar, key, s.text, version)
                   for s in spec.spellings):
            continue
        atoms.add(directive_atom(key, m))
        for c, rule in grammar.allowed(sk, key).items():
            if c.startswith("ompx_") or not rule_valid(rule, version):
                continue
            name = base_name(c)
            atoms.add(f"{m}.clause.{name}")
            entry = grammar.clauses.get(name)
            form = entry.form_for(key, version, lang) if entry else None
            if form:
                atoms.update(f"{m}.clause.{name}.{f}"
                             for f in form.atom_features())
    for atom, e in semantic_atoms(m).items():
        if e.since <= version and f"{m}.clause.{e.clause}" in atoms \
                and lang in e.langs:
            if atom in atoms:
                raise ValueError(f"semantic atom {atom} is also a syntax "
                                 "atom")
            atoms.add(atom)
    if in_scope:
        atoms -= set(out_of_scope_atoms(version, lang))
    return sorted(atoms)


def atom_langs(version: int) -> dict[str, frozenset]:
    """Atom id -> the languages whose slice has it at `version`:
    an atom of both languages maps to {"f90", "c"}."""
    out: dict[str, set] = {}
    for lang in LANGS:
        for a in slice_atoms(version, lang=lang):
            out.setdefault(a, set()).add(lang)
    return {a: frozenset(v) for a, v in out.items()}
