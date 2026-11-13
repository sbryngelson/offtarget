"""No user name, host name or private path on the public site.

`scrub` applies the vendor checks' replacements (data/vendor/checks/build.py SCRUB)
and a few more; `leaks` finds anything that still identifies a person, a machine
or a private directory, and the site build fails on any hit."""
from __future__ import annotations

import functools
import re

from offload.engine.site.matrix import B

_MORE = [(re.compile(r"/tmp/[\w.-]*(?:/[\w.$<>-]+)*"), "<dir>"),
         (re.compile(r"(?<![\w<])/(?:nethome|home|users?)/[A-Za-z0-9_.-]+"), "<home>")]
# /tmp/<name>-... and /tmp/<name>_...: a per-user build directory (/tmp/<user>-t44,
# /tmp/<user>_site) names its user
_LEAK = re.compile(r"/p/(?:lustre\d|vast\d)/|/g/g\d+/|/usr/workspace/|/nethome/[a-z]|"
                   r"\btuolumne\d+|\btioga\d+|wingtip-gpu|gatech\.edu|llnl\.gov|/fastscratch/[a-z]|"
                   r"/tmp/[A-Za-z][\w.]*[-_]")


# --- internal task references ----------------------------------------------------------
# The findings' program headers and the committed feature-support notes cite the internal
# work item that produced a line ("Task 47", "since Task 16 ..."). A reader of the public
# site cannot know what that is, so the reference goes, with the connecting words that
# would no longer make sense. One rule per phrasing (tests/site/test_site_inputs.py lists each
# with its result); the findings and the committed inputs keep their history, only the
# text built into the site changes. A reference no rule covers is not guessed at: the site
# build refuses it (offload.engine.site.data) so that a rule is written for it.
_T = r"Task \d+[a-z]?"
TASK_REF = re.compile(rf"\b{_T}\b")
# the start of a comment line, with its marker (`!`, `//`, `/*`, `#`, `-`, `*`)
_BOL = r"^([ \t]*(?:!|//|/\*|\*|#|-)?[ \t]*(?:[#!]|-)?[ \t]*)"


def _cap(text: str) -> str:
    """Start a sentence with a capital, unless its first word is an identifier or a call."""
    return text[:1].upper() + text[1:] if re.match(r"[a-z]+(?![\w(])", text) else text


def _lead(fn):
    return lambda m: m.group(1) + fn(m)


_TASK_RULES = [(re.compile(p, re.M), r) for p, r in [
    # a trailing citation: "(rulings.md, Task 31)", "re-verified in Task 25)"
    (rf", {_T}\)", ")"),
    (rf"re-verified in {_T}\)", "re-verified)"),
    (rf"re-categorised in {_T} \(", "re-categorised ("),
    (rf" \({_T}\)", ""),
    (rf"; {_T} probes\)", ")"),
    # "since Task NN ..." in the feature-support notes and in the findings
    (rf"\bsince(\s+){_T} fix round \d+ ", r"now\1"),
    (rf"\bsince {_T} (the )", r"\1"),
    # the rerun, the catalog widening, the review that cites a file
    (rf"{_T} rerun\b", "rerun"),
    (rf"; {_T} catalog widening", "; catalog widening"),
    (rf"; {_T} review, ", "; "),
    (rf"; {_T},(?=\n)", ";"),
    (rf", {_T} (fix round|re-review)", r", \1"),
    (rf", {_T}: ", ": "),
    (rf"found by: {_T} while reducing", "found by: reducing"),
    (rf"reproducer that {_T} reduced", "reproducer reduced"),
    (rf"\bBefore {_T} the\b", "Previously the"),
    (rf"\bcited in {_T}\b", "cited earlier"),
    # "Task 47 (Task 48's errata):" is one phrase
    (rf"{_T} \({_T}'s(\s+[!/#*-]*)(\s*)errata\):", r"Errata:\1"),
    # "the Task NN pilot", "MFC's Task NN objects", "Task NN's reruns"
    (rf"\b([Tt]he) {_T}(?= [A-Za-z])", r"\1"),
    (rf"\bMFC's {_T} ", "MFC's "),
    (rf"\b{_T}'s\b", "the"),
    # "Task NN cited gfortran ...", at the start of a sentence and inside one
    (_BOL + rf"{_T} cited\b", _lead(lambda m: "An earlier review cited")),
    (rf"{_T} cited\b", "an earlier review cited"),
    # a label in parentheses: "# Finding (Task 49a)", "(Task 42, from ...)", "(Task 33: ...)"
    (rf"Finding \({_T}\)", "Finding"),
    (rf"\({_T}[:,;]? ", "("),
    # a label that starts a comment line
    (_BOL + rf"{_T} finding\b", _lead(lambda m: "Finding")),
    (_BOL + rf"{_T}: (\S+)", _lead(lambda m: _cap(m.group(2)))),
    (_BOL + rf"{_T} \(([^)\n]*)\): ", _lead(lambda m: _cap(m.group(2)) + ": ")),
    (_BOL + rf"{_T} (fix round)", _lead(lambda m: "Fix round")),
    (_BOL + rf"{_T} (audit|probe)\b", _lead(lambda m: _cap(m.group(2)))),
    (_BOL + rf"{_T}\. (\S+)", _lead(lambda m: _cap(m.group(2)))),
    (rf"\. {_T} \(", ". ("),
    (_BOL + rf"{_T} \(", _lead(lambda m: "(")),
    (_BOL + rf"{_T}, ", lambda m: m.group(1)),
]]


def unjargon(text: str) -> str:
    """The text with the internal task references rewritten (rules above); text that cites
    none comes back unchanged, and a reference no rule covers stays (`task_refs`)."""
    for rx, rep in _TASK_RULES:
        text = rx.sub(rep, text)
    return text


# --- internal working vocabulary ---------------------------------------------------------
# The findings' program headers also say who ran what and in which review round ("the
# coordinator's runs", "fix round 2", "errata item 14", "the owner withdrew ..."). The public
# site shows what was observed and why, so each phrasing has its own rule here (listed with its
# result in tests/site/test_site_inputs.py). A rule matches the phrasing of the working
# vocabulary, never the bare word: an OpenMP "owner" of a lock, a block's "new owner", an AMD
# "Agent handle" or "syncscope("agent")" in a compiler message, "review" in a spec quote and a
# file name such as dataenv-pilot.md match no rule, so they stay. Measured values and
# citations are not touched: a rule only drops or rewords the words around them.
# A phrasing no rule covers is not guessed at and does not stop the build either: the words
# are listed by `process_words` (forbidden words with an allow-list of the technical uses) and
# tests/site/test_site_inputs.py fails on any in the built data until a rule is written.
_W = r"(\s+(?:(?:!|//|/?\*|#)[ \t]*)?)"      # a space, or a line break and the comment marker
_DATE = r"(\d{4}-\d\d-\d\d)"
_FR = r"fix rounds? \d+(?: and \d+)?"


_PROCESS_RULES = [
    # a label at the start of a comment line: the label goes, the sentence stays
    (re.compile(_BOL + r"The reproduction gate's review queue: (\S+)", re.M), _lead(lambda m: _cap(m.group(2)))),
    (re.compile(_BOL + r"Fix round \d+ \(review minor \d+\): (\S+)", re.M), _lead(lambda m: _cap(m.group(2)))),
    (re.compile(_BOL + r"Fix round \d+ \((?=(?:reducing )?the reproduction gate)", re.M), _lead(lambda m: "(")),
    (re.compile(_BOL + r"Fix round \d+ \(([^)\n]*)\): ", re.M), _lead(lambda m: _cap(m.group(2)) + ": ")),
    (re.compile(_BOL + r"Fix round \d+: (\S+)", re.M), _lead(lambda m: _cap(m.group(2)))),
    (re.compile(_BOL + r"Errata item \d+: (\S+)", re.M), _lead(lambda m: _cap(m.group(2)))),
    *[(re.compile(p, re.M), r) for p, r in [
        # the coordinator (a reader sees the separate runs, not who made them)
        (r"claims\.yaml; coordinator reading, fix round 1\)", "claims.yaml)"),
        (rf"\(the coordinator found its own{_W}device-malloc initialisation kernel, omp_dm_init_kernel, in the AFAR",
         r"(its own\1device-malloc initialisation kernel, omp_dm_init_kernel, is in the AFAR"),
        (rf"allocator\.cpp; the coordinator's{_W}reading", r"allocator.cpp; a\1reading"),
        (r"is the coordinator's reading\.", "is a reading."),
        (rf"by the coordinator's{_W}reading", r"by that\1reading"),
        (rf"\(the coordinator's{_W}HIP", r"(the\1HIP"),
        (r"\bthe coordinator's (`llvm-nm`|build\b|C launches)", r"the \1"),
        (rf"\bthe{_W}coordinator's raw md5", r"the\1raw md5"),
        (rf"\bthe{_W}coordinator's (?:own )?runs", r"the\1separate runs"),
        (r"\bbuilt by the coordinator against", "built against"),
        (r"\bthe coordinator's rows", "the separate runs' rows"),
        (r"\bthe coordinator also found", "the separate runs also found"),
        (r"\bAlso from the coordinator \(", "Also from the separate runs ("),
        (r"\bdamaged, coordinator \(", "damaged, other runs ("),
        (r"\bA tag test of the coordinator \(", "A tag test in the separate runs ("),
        (r"\bcoordinator \(launches per mask", "other runs  (launches per mask"),
        (r"\(coordinator's isa-", "(the separate runs' isa-"),
        (r"\(the coordinator's check, not repeated here\)", "(checked earlier, not repeated here)"),
        # the owner (a decision or ruling of the project, stated as a rule or a date)
        (rf"\(owner decision {_DATE}; held since final review \d+, N\d\)", r"(held since \1)"),
        (rf"\bthe owner's {_DATE} ruling", r"the \1 ruling"),
        (rf"; the owner withdrew{_W}gfortran/gcc{_W}-fopenmp as offload legality witnesses",
         r";\1gfortran/gcc\2-fopenmp were withdrawn as offload legality witnesses"),
        (rf": owner, {_DATE}\.\)", r": rule of \1.)"),
        # a task reference split by a line break (the task scrub cannot see it)
        (rf"\.md Task{_W}27b fix round 2, written for", r".md;\1written for"),
        # the re-review: a later check
        (r"\bthe re-review (counts|saw)\b", r"a later check \1"),
        (r"\bthe re-review's(\s+)(runs|timeouts)\b", r"the later\1\2"),
        (r"; re-review: (data/reports/)", r"; later check: \1"),
        (r"\(re-review \d+, ", "(a later check, "),
        (r"\(audit and re-review\)", "(audit and a later check)"),
        # the pilot, the reviewer, the review
        (r"; the pilot saw ", "; an earlier run saw "),
        (r"\bthe review's (\d+) runs\b", r"the \1 later runs"),
        (r"\bthe pilot's (\d+ CCE cells)", r"the \1"),
        (r"\(the pilot's rows\)", "(the earlier rows)"),
        (r"found by: the data-environment pilot, rule", "found by: the data-environment rule sample, rule"),
        (r"This 22-line reproducer is the reviewer's\.", "This is the 22-line reproducer."),
        (rf"\(fix round \d+, after the findings{_W}reviewer's runs;", r"(after further\1runs;"),
        # the reproduction gate's review queue
        (r"\breview queue entry\b", "flagged case entry"),
        (r"\breproduction gate's review queue\b", "reproduction gate's flagged cases"),
        # fix round N, in the places it stands
        (r"\(controller ruling (R\d+), fix round \d+\)", r"(ruling \1)"),
        (r"\bBasis \(fix round \d+, N\d\):", "Basis:"),
        (r", fix round \d+ log\)", ", rerun log)"),
        (r"\bsplit in fix round \d+:", "split:"),
        (r"\breproducer replaced in fix round \d+:", "reproducer replaced:"),
        (r", re-review \d+; (CCE [\d/]+), fix round \d+,", r", a rerun; \1, a second rerun,"),
        (r"\. Fix round \d+ reran it with", ". A rerun with"),
        (r"\bFix round \d+: (if \(teams: on\))", r"Reduced further: \1"),
        (r" \(Fix round \d+\.\)", ""),
        (rf"\({_FR}[,;:] ", "("),
        (rf"\({_FR}:{_W}this ", r"(\1this "),
        (r"\(review minor \d+[;,] ", "("),
        (rf" \({_FR}\)", ""),
        (rf", {_FR}\)", ")"),
        # errata item N
        (rf";{_W}errata item \d+\)\. ", r").\1"),
        (r" \(errata item \d+\)", ""),
        (r"\(errata item \d+: ", "("),
        (rf"\.{_W}Errata:{_W}that ", r".\2That "),
    ]],
]


def unprocess(text: str) -> str:
    """The text without the internal working vocabulary (rules above); text that has none
    comes back unchanged, and a phrasing no rule covers stays (`process_words`)."""
    for rx, rep in _PROCESS_RULES:
        text = rx.sub(rep, text)
    return text


def public_text(text: str) -> str:
    """The text as the public site shows it: task references (`unjargon`), then the
    working vocabulary (`unprocess`)."""
    return unprocess(unjargon(text))


# Words of the working vocabulary and the technical uses of the same words that stay. The site
# data test (tests/site/test_site_inputs.py) fails on a match outside the allow-list; the build
# does not, because a spec sentence or a compiler message may legitimately use the word.
_FORBIDDEN = [re.compile(p, f) for p, f in [
    (r"\bcoordinator", re.I), (r"\bowner\b", re.I), (r"\bfix rounds?\b", re.I), (r"(?<![\w./-])errata\b(?![\w-])", re.I),
    (r"\breview queue\b", re.I), (r"\breviewers?\b", re.I), (r"\bre-review\b", re.I),
    (r"\breview minor\b", re.I), (r"\bcontroller\b", re.I), (r"\bsubagents?\b", re.I),
    (r"\bworktrees?\b", re.I), (r"\bClaude\b", 0), (r"\bAI\b", 0), (r"\bagents?\b", re.I),
    (r"(?<![\w./-])pilot\b(?![\w/-])", re.I),     # not dataenv-pilot.md, not pilot_all/
]]
_ALLOWED = [re.compile(p, re.I) for p in [
    r"\b(?:new|old|previous|lock|thread)(?:\s+(?:!|//|\*|#)?\s*)owner\b", r"\bowner (?:of|thread)\b",      # OpenMP, allocators
    r"\bAgent handle\b", r"\bagent 0x", r'syncscope\("agent"\)', r"\bagent[- ](?:scope|release)\b",  # AMD
]]


def process_words(text: str) -> list[str]:
    """The words of the working vocabulary still in the text, outside the technical uses."""
    ok = [m.span() for rx in _ALLOWED for m in rx.finditer(text)]
    hits = [(m.start(), m.group(0)) for rx in _FORBIDDEN for m in rx.finditer(text)
            if not any(a <= m.start() and m.end() <= b for a, b in ok)]
    return [w for _, w in sorted(hits)]


def task_refs(text: str) -> list[str]:
    """The task references still in the text (none on a site page)."""
    return [m.group(0) for m in TASK_REF.finditer(text)]


def scrub(text: str) -> str:
    t = B.scrub(text)
    for rx, rp in _MORE:
        t = rx.sub(rp, t)
    return _names_rx().sub("<user>", t)


def commit_names(log: str) -> set[str]:
    """The user names in `git log --format=%ae` output; a scratch commit's address (copy@localhost,
    t@example.com) names no one."""
    return {re.sub(r"^\d+\+", "", ln.split("@")[0]) for ln in log.splitlines()
            if "@" in ln and not re.fullmatch(r"localhost|example\.(?:com|org|net)", ln.split("@")[1])}


@functools.lru_cache(maxsize=None)
def private_names() -> tuple[str, ...]:
    """The user names nothing published may contain, taken from where they are, never written down: each
    committer's e-mail name (git), this account's login, and OFFLOAD_PRIVATE_NAMES (comma-separated; the
    tests use it). A trailing number is dropped, so jdoe also stands for jdoe1 and sjdoe3."""
    import getpass
    import os
    import subprocess
    from offload.engine.root import ROOT
    try:
        log = subprocess.run(["git", "log", "--format=%ae"], cwd=ROOT, capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        log = ""
    names = commit_names(log)
    try:
        names.add(getpass.getuser())
    except (KeyError, OSError):
        pass
    names |= {n.strip() for n in os.environ.get("OFFLOAD_PRIVATE_NAMES", "").split(",")}
    generic = {"root", "runner", "user", "ubuntu", "github", "trial", "noreply", "admin", "builder", "test", "tests", "testing", "example", "actions"}
    return tuple(sorted({re.sub(r"\d+$", "", n) for n in names if len(n) >= 4 and n.lower() not in generic}))


# the site footer's credit: the author and the author's public profile, linked on purpose (leaks() skips
# exactly this URL; the same handle anywhere else is still a leak)
AUTHOR = ("Spencer H. Bryngelson", "https://github.com/sbryngelson")


@functools.lru_cache(maxsize=None)
def _names_rx() -> re.Pattern:
    names = "|".join(re.escape(n) for n in private_names()) or "(?!)"
    return re.compile(rf"(?<![A-Za-z])s?(?:{names})\d*(?![A-Za-z])")


def leaks(text: str, allow: tuple[str, ...] = ()) -> list[str]:
    """The user, host and private-path names in `text`. `allow` holds exact strings that are public
    on purpose and are not looked at (the configured repository URL, whose owner handle is the
    owner's name); the same name anywhere else is still a leak."""
    for a in (*allow, AUTHOR[1]):
        if a:
            text = text.replace(a, "")
    return [m.group(0) for m in _names_rx().finditer(text)] + [m.group(0) for m in _LEAK.finditer(text)]
