"""The header of a finding file: the comment block above the program that says what fails,
where, and what backs it (data/findings/AUTHORING.md).

``parse`` reads the leading comment lines (``//`` in C, ``!`` in Fortran) as `` - key: value``
bullets (a line indented under a bullet continues it; the fuzz findings' `` toolchain: ...``
lines have no dash) and ``mentions`` reads which toolchains a sentence names. The claim checker
(offload.engine.finding_claims) and the scaffold (tools/new_finding.py) share this grammar, so a
header the scaffold writes is a header the checker reads.

An unfinished item of a draft is the marker ``TODO(human)``: a finding that holds one is not
committable (tools/repo/check_findings.py).
"""
from __future__ import annotations

import re
from pathlib import Path
import textwrap
from dataclasses import dataclass, field

MARK = "TODO(human)"
_LEAD = re.compile(r"^\s*(?://|!)\s?(.*)$")
_BULLET = re.compile(r"^- ?([A-Za-z][\w ()/&,'-]{1,60}?):\s*(.*)$")
_FUZZ = re.compile(r"^(toolchain|failure|also fails on|expected|observed|message):\s*(.*)$")
_TITLE = re.compile(r"^# Finding(?: \(([^)]*)\))?:\s*(.*)$")

# bullet key (lower case) -> field name
KEYS = {"toolchains and modes that fail": "fail", "toolchains": "fail", "toolchain": "fail",
        "build": "build", "failure": "failure", "observed": "observed", "expected": "expected",
        "rule": "rule", "same-compiler control": "control", "same-compiler controls": "control",
        "control (same compiler)": "control", "control": "control",
        "other families": "other", "other family": "other", "another family": "other",
        "gate and confirmer": "gate", "gate": "gate", "legality": "legality",
        "programs": "programs", "also fails on": "also"}


@dataclass
class Header:
    title: str | None = None
    campaign: str | None = None
    fields: dict = field(default_factory=dict)
    lines: list = field(default_factory=list)      # the comment lines without markers

    def get(self, name: str) -> str:
        return self.fields.get(name, "")


def comment_lines(text: str) -> list[str]:
    """The leading run of comment lines of a file, markers removed (a blank line or the first
    code line ends it; the site: block is not part of it)."""
    out = []
    for raw in text.splitlines():
        m = _LEAD.match(raw)
        if m is None:
            if out and not raw.strip():
                break
            if out:
                break
            continue
        if m.group(1).strip() == "site:":
            break
        out.append(m.group(1).rstrip())
    return out


def parse(text: str) -> Header:
    h = Header(lines=comment_lines(text))
    cur = None
    for ln in h.lines:
        t = _TITLE.match(ln)
        if t:
            h.campaign, h.title = t.group(1), t.group(2)
            cur = None
            continue
        b = _BULLET.match(ln) if ln.startswith("-") else _FUZZ.match(ln)
        if b:
            name = KEYS.get(b.group(1).strip().lower().replace("fortran ", ""),
                            b.group(1).strip().lower())
            if name.startswith("programs"):
                name = "programs"
            if name in h.fields:
                h.fields[name] += " " + b.group(2).strip()
            else:
                h.fields[name] = b.group(2).strip()
            cur = name
        elif ln.startswith("-"):
            cur = None      # a bullet whose key is not a field name: its lines are not the last field's
        elif cur and ln[:1] in (" ", "\t") and ln.strip():
            h.fields[cur] += " " + ln.strip()
        elif not ln.strip():
            cur = None
    return h


def todos(text: str) -> list[tuple[int, str]]:
    """(line number, line) of every TODO(human) marker in `text`."""
    return [(n, ln.strip()) for n, ln in enumerate(text.splitlines(), 1) if MARK in ln]


# --- toolchain mentions ----------------------------------------------------------------

# The toolchains a header may name come from catalog/toolchains.yaml: a family's
# toolchains (no arch twin: a header names a release, the machine is context),
# the version tokens that name a release (the major, "CCE 21", is the first
# release with it; a full version its own) and the family names.
from offload.engine.toolchains import registry as _registry  # noqa: E402
_R = _registry()
FAMILIES = {f: tuple(t for t in _R.site_toolchains() if _R.toolchains[t].family_id == f)
            for f in _R.families}
_VERS: dict = {}
for _fam, _tcs in FAMILIES.items():
    if len({_R.toolchains[t].version for t in _tcs}) > 1:
        _VERS[_fam] = {}
        for _t in _tcs:
            _v = _R.toolchains[_t].version
            _VERS[_fam].setdefault(_v.split(".")[0], _t)
            _VERS[_fam].setdefault(_v, _t)
# a toolchain id that is also a compiler command's name (gcc) names the command in a header,
# not the toolchain ("gcc -fopenmp is never evidence")
_COMMANDS = {Path(c).name for t in _R.toolchains.values() for c in (t.fc, t.cc, t.cxx) if c}
# a header that names a twin (gcc_g90, cce21_g90) names the toolchain it is the twin of
_TWIN_OF = {w: b for w, b in _R.twins().items() if b in _R.site_toolchains()}
_KEY = re.compile(r"\b(" + "|".join(sorted((t for ts in FAMILIES.values() for t in ts if t not in _COMMANDS),
                                            key=lambda t: (-len(t), t)) + sorted(_TWIN_OF, key=lambda t: (-len(t), t)))
                  + r")\b")
_FAM_NAMES = [_R.families[f].name for f in FAMILIES]
_FAM = re.compile(r"\b(" + "|".join(map(re.escape, _FAM_NAMES)) + r")\b"
                  r"(?:\s+((?:v?\d+(?:\.\d+){0,2})(?:\s*(?:/|,\s*|\s+and\s+|\s+or\s+|\s+to\s+)\s*"
                  r"(?:" + "|".join(re.escape(_R.families[f].name) + r"\s+" for f in _VERS)
                  + r")?\d+(?:\.\d+){0,2})*))?")
# a family with one release installed on several machines (GCC 16.2 on the AMD GPUs and the
# A100): the words near its name that pick the install, the catalog's `mention_words` or,
# without them, the arch, the machine, the GPU's short name (machines.yaml target_short) and
# the twin suffix, of the install and of its twins (GCC's MI250X install, gcc_g90, picks gcc);
# the first install whose words match wins, else the whole family
def _install_words(name: str) -> list[str]:
    from offload.engine.confirm.machines import load as _machines
    tc = _R.toolchains[name]
    if tc.mention_words:
        return list(tc.mention_words)
    m = _machines()[tc.machine]
    words = [tc.arch, tc.machine, tc.arch.replace("_", "")]
    words += [m.mode_table[x]["target_short"].split()[0] for x in m.modes
              if m.mode_table[x].get("target_short")]
    sfx = _R.arches[tc.arch].get("twin_suffix", "")
    return words + ([sfx.lstrip("_")] if sfx else [])


_WHERE = {}
for _fam, _tcs in FAMILIES.items():
    if len(_tcs) > 1 and len({_R.toolchains[t].version for t in _tcs}) == 1:
        for _t in _tcs:
            _words = [w for n in (_t, *_R.twins_of(_t)) for w in _install_words(n)]
            _WHERE.setdefault(_fam, []).append(
                (_t, re.compile("|".join(map(re.escape, dict.fromkeys(_words))))))


def family_of(tc: str) -> str:
    return next((f for f, t in FAMILIES.items() if tc in t), tc)


@dataclass(frozen=True)
class Mention:
    family: str
    tcs: tuple          # the toolchains named (all of a family when no version is given)
    explicit: bool      # versions given: every one is meant; else any one of the family
    pos: int


def _version_tc(fam: str, tok: str) -> str | None:
    """The release a version token names: the full version, else the first release of
    its major ("21.0.5" is the CCE 21 line)."""
    table = _VERS.get(fam, {})
    tok = tok.lstrip("v")
    if tok in table:
        return table[tok]
    return table.get(tok.split(".")[0])


def mentions(text: str) -> list[Mention]:
    out = []
    for m in _KEY.finditer(text):
        tc = _TWIN_OF.get(m.group(1), m.group(1))
        out.append(Mention(family_of(tc), (tc,), True, m.start()))
    for m in _FAM.finditer(text):
        fam = next(f for f in FAMILIES if _R.families[f].name == m.group(1))
        vers = m.group(2)
        if fam in _WHERE:
            ctx = text[max(0, m.start() - 60): m.end() + 60]
            tcs = next(((t,) for t, where in _WHERE[fam] if where.search(ctx)), FAMILIES[fam])
            out.append(Mention(fam, tcs, False, m.start()))
            continue
        if vers and fam in _VERS:
            toks = re.findall(r"\d+(?:\.\d+){0,2}", vers)
            tcs = tuple(dict.fromkeys(t for t in (_version_tc(fam, k) for k in toks) if t))
            if tcs:
                out.append(Mention(fam, tcs, True, m.start()))
                continue
        out.append(Mention(fam, FAMILIES[fam], fam == "afar", m.start()))
    out.sort(key=lambda x: x.pos)
    return out


_SPLIT = re.compile(r";|(?<=[a-z\)`])\.\s+(?=[A-Z(])|\bbut\b|\bwhile\b|\bwhereas\b")
POS = re.compile(r"\b(correct(?:ly)?|pass(?:es)?|compiles? and (?:runs?|prints?|gives?)|"
                 r"runs? (?:it|this|the|all|them|both)|gives? [\d`]|prints?|accepts?)\b", re.I)
NEG = re.compile(r"\b(fail\w*|reject\w*|ICE|wrong|fault\w*|abort\w*|crash\w*|not (?:support|implement)\w*|"
                 r"unsupported|error\w*|hang\w*|differ\w*|another way|garbage|stops?|no family|"
                 r"cannot|unknown)\b", re.I)
HEDGE = re.compile(r"not (?:studied|claimed|run)\b|has not been run|were not run|unverified|"
                   r"not measured|did not run", re.I)


def clauses(text: str) -> list[str]:
    return [c.strip() for c in _SPLIT.split(text) if c.strip()]


def positive(clause: str) -> bool:
    return bool(POS.search(clause)) and not NEG.search(clause) and not HEDGE.search(clause)


# --- writing ---------------------------------------------------------------------------

def bullet(key: str, value: str, lead: str, width: int = 132) -> list[str]:
    """`- key: value` wrapped to `width` columns after the comment lead (`//` or `!`)."""
    first = f"- {key}: {value}".strip()
    room = width - len(lead) - 1
    lines = textwrap.wrap(first, room, subsequent_indent="  ", break_long_words=False,
                          break_on_hyphens=False) or [first]
    return [f"{lead} {x}" for x in lines]
