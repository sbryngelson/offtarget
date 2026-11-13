"""Independent legality reviews of the findings (data/findings/reviews/, tools/review/).

A blind reader judges a finding's program from the specification text alone, without the
finding's own argument: is the program legal, and does the specification require the expected
result (or acceptance)? Each reader works a batch that holds one decoy whose answer is known; a
reader that misses its decoy does not count. Every quoted passage is checked against the
specification text (offload.engine.citations). When the readers disagree or are uncertain, two
adjudicators read the program and both readings side by side, each in a batch with a decoy dispute
whose right side is known. A record holds the readers and adjudicators of one finding, its prior
art and outside evidence, and the verdict, which follows from them by a fixed rule (``verdict``). A record names the hash of the program its readers saw: a changed program makes
it stale, and the finding is then unconfirmed."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from offload.engine.root import ROOT

REVIEWS = ROOT / "data" / "findings" / "reviews"
FINDINGS = ROOT / "data" / "findings"
# the reader instructions' version (tools/review/instructions.md); a verdict counts only readings
# made under it. v2: each answer quotes the program lines it relies on and names what it says the
# program lacks, both checked against the program (check_program).
INSTRUCTIONS = "v2"
VERDICTS = ("confirmed", "supported", "contested", "unconfirmed")
# what each verdict says on the site and in `offload issues`
WORDS = {"confirmed": "independently confirmed",
         "supported": "supported by outside evidence",
         "contested": "contested",
         "unconfirmed": "not independently confirmed"}
_SPEC_FILE = {"openmp-4.5": "OpenMP 4.5", "openmp-5.0": "OpenMP 5.0", "openmp-5.1": "OpenMP 5.1",
              "openmp-5.2": "OpenMP 5.2", "openmp-6.0": "OpenMP 6.0", "openacc-3.4": "OpenACC 3.4"}


def program_text(path: Path) -> str:
    """The program of a finding file without its comment lines (the header, the site: block):
    what a reader sees. Fortran directives (!$omp, !$acc) are code."""
    path = Path(path)
    mark = "//" if path.suffix in (".c", ".h", ".cpp") else "!"
    out = []
    for ln in path.read_text().splitlines():
        s = ln.strip()
        if s.startswith(mark) and not (mark == "!" and s[:2].lower() == "!$"):
            continue
        out.append(ln.rstrip())
    while out and not out[-1]:
        out.pop()
    while out and not out[0]:
        out.pop(0)
    return "\n".join(out) + "\n"


def program_sha(path: Path) -> str:
    return hashlib.sha256(program_text(path).encode()).hexdigest()


def record_path(finding_id: str) -> Path:
    return REVIEWS / (finding_id.replace("/", "--") + ".json")


def load(finding_id: str) -> dict | None:
    p = record_path(finding_id)
    return json.loads(p.read_text()) if p.is_file() else None


def finding_file(finding_id: str) -> Path | None:
    hits = [p for p in FINDINGS.glob(finding_id + ".*") if p.suffix in (".f90", ".F90", ".c", ".cpp")]
    return hits[0] if hits else None


# memory modes whose host and device copies may share storage (catalog/machines.yaml: unified, managed)
SHARED_STORAGE = ("mi300a-u", "a100-m")


def memory_line(targets: list[str]) -> str:
    """What a reader is told of the failing runs' memory: whether any kept host and device apart."""
    if any(t not in SHARED_STORAGE for t in targets):
        return "The failing runs include separate host and device memory (no shared storage)."
    return "Every failing run used unified memory: original and device copies may share storage."


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


def check_program(answer: dict, program: str) -> dict:
    """{ok, not_found, contradicted} for a reader's claims about the program's own text: each of
    `program_lines` must occur in it, and each of `absent` (what the reader says the program
    lacks) must not, as a whole word. Case and spacing are ignored; an absent text under 3
    characters is too short to test and is skipped."""
    prog = _norm(program)
    lines = [ln for ln in (answer.get("program_lines") or []) if _norm(ln)]
    gone = [a for a in (answer.get("absent") or []) if len(_norm(a).replace(" ", "")) >= 3]
    found = sum(1 for ln in lines if _norm(ln) in prog)
    def present(text: str) -> bool:      # as a whole word: device( is not in omp_is_initial_device()
        t = _norm(text)
        return re.search((r"(?<![\w])" if t[:1].isalnum() or t[:1] == "_" else "") + re.escape(t)
                         + (r"(?![\w])" if t[-1:].isalnum() or t[-1:] == "_" else ""), prog) is not None
    return {"ok": found, "not_found": len(lines) - found, "contradicted": sum(1 for a in gone if present(a))}


def verification_counted(v: dict) -> bool:
    """A verifier counts when it refuted its batch's false decoy reading and upheld the sound one
    (batch_decoys "caught"), and every quote it gave checks out: specification passages in the
    specification, program lines in the program."""
    return (v.get("batch_decoys") == "caught" and not (v.get("quotes") or {}).get("not_found")
            and not (v.get("program") or {}).get("not_found"))


def refuted(reader: dict) -> bool:
    """Two counted verifiers each refuted a premise of the reading (claim verification)."""
    return sum(1 for v in reader.get("verifications", []) if v.get("refuted") and verification_counted(v)) >= 2


def counted(reader: dict) -> bool:
    """A reader counts when it read under the current instructions, its batch's decoy was caught,
    none of its quotes is missing from the specification, it quoted at least one program line,
    every program line it quoted is in the program, nothing it says the program lacks is there, and
    no two counted verifiers refuted it (``refuted``)."""
    prog = reader.get("program") or {}
    return (reader.get("instructions", "v1") == INSTRUCTIONS and reader.get("batch_decoy") == "caught"
            and not refuted(reader)
            and not (reader.get("quotes") or {}).get("not_found")
            and prog.get("ok", 0) > 0 and not prog.get("not_found") and not prog.get("contradicted"))


def _yes(r: dict) -> bool:
    return r["legal"] == "yes" and r["result_required"] == "yes"


def _no(r: dict) -> bool:
    return r["legal"] == "no" or r["result_required"] == "no"


def verdict(rec: dict) -> str:
    """The fixed rule. Counted adjudicators decide first: two that find the program legal and the
    result required confirm it, one that finds it not legal or not required contests it. Then the
    readers: confirmed (two counted readers, both legal and required), contested (a counted reader
    says not legal or not required), supported (a contest or an uncertainty settled by outside
    evidence or strong prior art), else unconfirmed (no counted reader yet, or uncertainty with
    nothing to settle it)."""
    rs = [r for r in rec.get("readers", []) if counted(r)]
    adj = [r for r in rec.get("adjudicators", []) if counted(r)]
    settled = bool(rec.get("external")) or any(p.get("strength") == "strong"
                                               for p in rec.get("prior_art", []))
    if any(_no(r) for r in adj):
        return "supported" if settled else "contested"
    if len(adj) >= 2 and all(_yes(r) for r in adj):
        return "confirmed"
    if len(rs) >= 2 and all(_yes(r) for r in rs):
        return "confirmed"
    if any(_no(r) for r in rs):
        return "supported" if settled else "contested"
    if rs and settled:
        return "supported"
    return "unconfirmed"


def status(finding_id: str) -> tuple[str, str]:
    """(verdict, why) of a finding now: its record's verdict, or unconfirmed when there is no
    record or the program changed since its readers saw it."""
    rec = load(finding_id)
    f = finding_file(finding_id)
    if rec is None or f is None:
        return "unconfirmed", "no independent review yet"
    if rec.get("program_sha") != program_sha(f):
        return "unconfirmed", "the program changed since its review"
    return rec.get("verdict", "unconfirmed"), rec.get("why", "")


SPEC_TEXT = ROOT / "results" / "spec_cache"     # the plain text readers search


def _in_text(name: str, quote: str) -> bool:
    """The quote occurs, up to spacing and hyphenation, in the plain-text specification the reader
    was given (offload.engine.citations reads rows parsed from the PDF, whose table columns can come
    out in another order)."""
    from offload.engine import citations as C
    p = SPEC_TEXT / f"{name}.txt"
    pieces = C._pieces(quote)
    if not p.is_file() or not pieces:
        return False
    big = C._squash(p.read_text())
    pos = 0
    for piece in pieces:
        pos = big.find(piece, pos)
        if pos < 0:
            return False
        pos += len(piece)
    return True


def check_quotes(passages: list) -> dict:
    """{ok, wrong_section, not_found} over a reader's quoted passages (offload.engine.citations):
    a quote must occur verbatim in the version it names; wrong_section is a real quote cited under
    another section, or one that occurs in the reader's plain text but not where the section-aware
    check looks."""
    from offload.engine import citations as C
    out = {"ok": 0, "wrong_section": 0, "not_found": 0}
    for p in passages or []:
        if not isinstance(p, dict):
            p = {"quote": str(p)}      # bare text: no specification named, so not found below
        blob = json.dumps(p)
        m = re.search(r"(openmp-\d\.\d|openacc-3\.4)", blob)
        sec = str(p.get("section") or "")
        sec = re.sub(r"^[^\d]*", "", sec).split()[0].rstrip(".,;:") if re.search(r"\d", sec) else ""
        quote = p.get("quote") or p.get("text") or ""
        if not m or not quote:
            out["not_found"] += 1
            continue
        res = C.check(C.Citation(path="", line=0, text="", version=_SPEC_FILE[m.group(1)],
                                 section=sec, quote=quote))
        key = res.status if res.status in out else ("not_found" if res.status == "quote_not_found"
                                                    else "wrong_section")
        if key == "not_found" and _in_text(m.group(1), quote):
            key = "wrong_section"
        out[key] += 1
    return out


def problems(finding_id: str, rec: dict) -> list[str]:
    """What is wrong with a committed record: a verdict the rule does not give, an unknown
    instructions version, a reader without decoy or quote results."""
    out = []
    if rec.get("verdict") != verdict(rec):
        out.append(f"{finding_id}: verdict {rec.get('verdict')}, the rule gives {verdict(rec)}")
    for r in rec.get("readers", []) + rec.get("adjudicators", []):
        if r.get("batch_decoy") not in ("caught", "missed"):
            out.append(f"{finding_id}: a reader without its batch's decoy result")
        if not isinstance(r.get("quotes"), dict):
            out.append(f"{finding_id}: a reader without quote-check results")
    if not rec.get("program_sha"):
        out.append(f"{finding_id}: no program hash")
    return out
