"""How much public code has every ingredient a finding's own evidence proves necessary.

A minimized program (``Minimized by compliance.fuzz_min``) is 1-minimal: each of its offload
regions, with its features (offload.engine.usage) and the language words of its statements, is
needed. A hand-written finding with passing one-change controls needs what each control removed:
region features on that region's directives, features of standalone directives in the file, and
language words. A language word is a code word the program does not declare (``names``): a
keyword, an intrinsic, a library or API routine. A control that removes only names proves
nothing; a finding left with no proven ingredient has no signature.

A corpus file (``record``) is exposed when it holds every requirement. ``count`` gives distinct
repositories and files, copies once. It counts code with the ingredients, not code that fails."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from offload.engine import finding_claims as FC, finding_header as H, usage as U

MINIMIZED = "Minimized by compliance.fuzz_min"
_C_EXT = (".c", ".h", ".cc", ".cpp", ".cxx", ".hpp")


@dataclass(frozen=True)
class Part:
    features: frozenset                         # on one region
    words: frozenset = frozenset()              # minimal: in that region; controls: in the file
    file_features: frozenset = frozenset()      # on any directive of the file


@dataclass
class Signature:
    kind: str                                   # "minimal" or "controls"
    parts: list = field(default_factory=list)   # minimal: each matched by one region
    requirements: list = field(default_factory=list)   # controls: all hold


@dataclass
class Record:
    repo: str
    path: str
    regions: list                      # [(features, words)]
    words: frozenset
    features: frozenset = frozenset()  # of every directive


def _is_c(name: str) -> bool:
    return name.lower().endswith(_C_EXT)


def _scan(text: str, name: str):
    try:
        return U.scan(text, name)
    except Exception:                  # a file the scanner cannot read has no regions
        return None


def _code(text: str, name: str) -> str:
    """The code without comments or directives."""
    if _is_c(name):
        return "\n".join(ln for ln in U._c_strip(text).splitlines() if not ln.lstrip().startswith("#"))
    return "\n".join(U._strip_f_comment(ln) for ln in text.splitlines()
                     if not ln.lstrip().startswith(("!", "#")))


_F_DECL = re.compile(r"^(?:integer|real|logical|complex|character|double\s*precision|"
                     r"type\s*\(|class\s*\(|procedure)", re.I)
_F_UNIT = re.compile(r"^(?:[\w\s()=*,]*?\s)?(?:program|module|submodule\s*\([^)]*\)|subroutine|"
                     r"function|block\s+data|interface)\s+(\w+)", re.I)
_F_TYPE = re.compile(r"^type\s*(?:,[^:]*)?(?:::)?\s*([A-Za-z_]\w*)\s*$", re.I)
_C_TYPE = (r"(?:int|long|short|float|double|char|void|unsigned|signed|bool|_Bool|size_t|"
           r"\w+_t|struct\s+\w+|union\s+\w+|enum\s+\w+|const|static|extern|register|volatile)")
_C_DECL = re.compile(rf"\b{_C_TYPE}\b[\s*]*((?:[\s*]*[A-Za-z_]\w*\s*(?:\[[^\]]*\])*"
                     rf"\s*(?:=[^,;(){{}}]*)?,)*[\s*]*[A-Za-z_]\w*)\s*[;=\[(),]")


def names(text: str, name: str) -> set:
    """What the program declares: variables, procedures, types, members, associate and
    construct names, macros."""
    out = set()
    if _is_c(name):
        code = U._c_strip(text)
        out |= set(re.findall(r"#\s*define\s+(\w+)", code))
        code = "\n".join(ln for ln in code.splitlines() if not ln.lstrip().startswith("#"))
        out |= set(re.findall(r"\}\s*([A-Za-z_]\w*)\s*[;,\[=]", code))
        out |= set(re.findall(r"\b(?:struct|union|enum)\s+(\w+)", code))
        out |= set(re.findall(r"typedef\b[^;]*?\b(\w+)\s*;", code))
        out |= set(re.findall(r"(?:\.|->)\s*([A-Za-z_]\w*)", code))
        for m in _C_DECL.finditer(code):
            out |= set(re.findall(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)*(?:=[^,]*)?(?:,|$)",
                                  m.group(1)))
        return {w.lower() for w in out} - set(_C_TYPE_WORDS)
    for _, _, stmt, model in U.fortran_statements(text):
        if model is not None:
            continue
        s = stmt.strip()
        if _F_DECL.match(s):
            out |= set(U._decl_entities(s)[1])
        for rx in (_F_UNIT, _F_TYPE):
            m = rx.match(s)
            if m:
                out.add(m.group(1).lower())
        m = re.match(r"^([A-Za-z_]\w*)\s*:(?!:)", s)
        if m:
            out.add(m.group(1).lower())
        if re.match(r"^associate\b", s, re.I):
            out |= {w.lower() for w in re.findall(r"([A-Za-z_]\w*)\s*=>", s)}
        out |= {w.lower() for w in re.findall(r"%\s*([A-Za-z_]\w*)", s)}
    return out


_C_TYPE_WORDS = ("int", "long", "short", "float", "double", "char", "void", "unsigned", "signed",
                 "bool", "_bool", "size_t", "struct", "union", "enum", "const", "static",
                 "extern", "register", "volatile")


def _language(text: str, name: str, words) -> frozenset:
    return frozenset(words) - names(text, name)


def _directive_features(fs) -> frozenset:
    """The features of every directive, with each clause modifier's leading word."""
    out = set()
    for d in (fs.directives if fs else []):
        out |= U._features_of(d)
        for c, mod, _, _ in d.clauses:
            for m in U.split_top(mod or ""):
                w = re.match(r"\s*([A-Za-z_]\w*)", m)
                if w:
                    out.add(f"mod:{c}:{w.group(1).lower()}")
    return frozenset(out)


def _parts_of(text: str, name: str) -> list:
    fs = _scan(text, name)
    return [r.features for r in fs.regions if r.features] if fs else []


def _controls(path: Path, root: Path, text: str) -> list[Path]:
    out = []
    for p, _ in FC._controls(H.parse(text), text, root, path.parent):
        q = next((d / p for d in (path.parent, root) if (d / p).is_file()), None)
        if q is not None:
            out.append(q)
    return out


def job_slug(rel: str) -> str:
    """The directory name of a finding's generated controls."""
    return rel.rsplit(".", 1)[0].replace("/", "__")


def _generated(rel: str, extra: Path | None) -> list[Path]:
    d = extra / job_slug(rel) / "controls" if extra else None
    return sorted(p for p in d.iterdir() if p.suffix in (".f90", ".c")) if d and d.is_dir() else []


def signature(path: Path, root: Path, extra: Path | None = None) -> Signature | None:
    """The signature of the finding at `path`; `extra` holds controls generated for it
    (tools/campaigns/exposure.py controls), each passing on the compiler the finding fails on."""
    text = path.read_text(errors="replace")
    fs = _scan(text, path.name)
    regions = [r for r in (fs.regions if fs else []) if r.features]
    if not regions:
        return None
    if MINIMIZED in text:
        return Signature("minimal", parts=[
            Part(frozenset(r.features), _language(text, path.name, r.words)) for r in regions])
    words = _language(text, path.name, U.code_words(_code(text, path.name)))
    rfeat = frozenset().union(*[r.features for r in regions])
    dfeat = _directive_features(fs)
    reqs = []
    rel = str(path.relative_to(root)) if root in path.parents else path.name
    for c in _controls(path, root, text) + _generated(rel, extra):
        ct = c.read_text(errors="replace")
        cfs = _scan(ct, c.name)
        cregions = [r for r in (cfs.regions if cfs else []) if r.features]
        if len(cregions) == len(regions):
            # the same regions: what each one lost (a clause removed from one of two regions
            # that both have it)
            lost = [(r, frozenset(r.features) - frozenset(q.features)) for r, q in zip(regions, cregions)]
            on, fkey = next(((r, k) for r, k in lost if k), (regions[0], frozenset()))
        else:
            fkey = rfeat - frozenset().union(*[r.features for r in cregions])
            on = next((r for r in regions if r.features & fkey), regions[0])
        dkey = dfeat - _directive_features(cfs) - fkey
        wkey = words - U.code_words(_code(ct, c.name))
        if not (fkey or dkey or wkey):
            continue
        dirs = frozenset(x for x in on.features if x.startswith("dir:"))
        reqs.append(Part(dirs | (frozenset(on.features) & fkey), wkey, dkey))
    return Signature("controls", requirements=reqs) if reqs else None


def signatures(root: Path, extra: Path | None = None) -> dict:
    """Every committed finding (not controls, not proposed) to its signature or None."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.suffix in (".f90", ".c") and not {"controls", "proposed"} & set(p.relative_to(root).parts):
            out[str(p.relative_to(root))] = signature(p, root, extra)
    return out


def ingredients(sig: Signature) -> int:
    """How many proven ingredients beyond the directive names a signature has."""
    ps = sig.parts if sig.kind == "minimal" else sig.requirements
    return sum(sum(1 for x in p.features if not x.startswith("dir:")) + len(p.words)
               + len(p.file_features) for p in ps)


def measurable(sig: Signature | None) -> bool:
    """A count says something: a minimized program, or a proven ingredient beyond the names of
    directives (a control that only unwraps a construct shows which construct, not the trigger)."""
    return sig is not None and (sig.kind == "minimal" or ingredients(sig) >= 1)


def wants_controls(sig: Signature | None) -> bool:
    """Generated controls could tighten it: no signature, or one proven ingredient or none."""
    return sig is None or (sig.kind == "controls" and ingredients(sig) <= 1)


_MODE = {"mi300a-u": 1, "mi300a-c": 0}


_MODE_NAME = {"copy": 0, "unified": 1}


def named_compilers(entry: dict | None, text: str) -> tuple[set, set | None] | None:
    """The toolchains and memory modes a finding says fail: its index entry, else its header's
    failing-toolchains bullet or a minimized program's ``toolchain:`` line. None when it names none."""
    if entry and entry.get("toolchains"):
        modes = {_MODE_NAME[m] for m in entry.get("modes") or [] if m in _MODE_NAME}
        return set(entry["toolchains"]), modes or None
    h = H.parse(text)
    line = h.get("fail") or ""
    m = re.search(r"^\W*toolchain:\s*(.*)$", text, re.M)
    if not line and m:
        line = m.group(1)
    tcs = {t for x in H.mentions(line) for t in x.tcs}
    if not tcs and m:
        tcs = {m.group(1).split()[0]}
    if not tcs:
        return None
    modes = {_MODE_NAME[w] for w in re.findall(r"\b(copy|unified)\b", line)}
    if re.search(r"HSA_XNACK=([01])", line):
        modes.add(int(re.search(r"HSA_XNACK=([01])", line).group(1)))
    return tcs, modes or None


def control_job(rel: str, obs, local, named=None) -> dict | None:
    """Where to make a finding's controls: the local toolchain and memory mode it is recorded
    failing on most often, among the ones it names (`named`: toolchains, modes), with a host run
    of a correct toolchain of another family as the output reference."""
    from collections import Counter
    from offload.engine.finding_header import family_of
    tcs, modes = named if named else (None, None)
    fails = Counter((o.tc, _MODE[o.target]) for o in obs
                    if o.failed and o.tc in local and o.target in _MODE
                    and (tcs is None or o.tc in tcs) and (modes is None or _MODE[o.target] in modes))
    if not fails:
        return None
    (tc, mode), _ = fails.most_common(1)[0]
    good = Counter(o.tc for o in obs if o.passed and o.tc in local and family_of(o.tc) != family_of(tc))
    bad = {o.tc for o in obs if o.failed}
    ref = (good.most_common(1)[0][0] if good else
           next((t for t in sorted(local) if family_of(t) != family_of(tc) and t not in bad), None))
    return {"finding": rel, "slug": job_slug(rel), "targets": [f"{tc}/{mode}"],
            "reference": f"host:{ref}" if ref else None}


def record(text: str, path: str, repo: str) -> Record:
    fs = _scan(text, path)
    regions = [(frozenset(r.features), frozenset(r.words)) for r in fs.regions] if fs else []
    return Record(repo, path, regions, frozenset(U.code_words(_code(text, path))),
                  _directive_features(fs))


def exposed(sig: Signature, rec: Record) -> bool:
    if sig.kind == "minimal":
        return all(any(p.features <= f and p.words <= w for f, w in rec.regions)
                   for p in sig.parts)
    return all(any(q.features <= f for f, _ in rec.regions) and q.words <= rec.words
               and q.file_features <= rec.features for q in sig.requirements)


def count(sigs: dict, records) -> dict:
    """Finding to the distinct repositories and files exposed (copies once)."""
    seen, recs = set(), []
    for r in records:
        key = (tuple(sorted(map(str, r.regions))), r.words)
        if key not in seen:
            seen.add(key)
            recs.append(r)
    out = {}
    for name, s in sigs.items():
        if s is not None:
            hit = [r for r in recs if exposed(s, r)]
            out[name] = {"repos": len({r.repo for r in hit}), "files": len(hit)}
    return out
