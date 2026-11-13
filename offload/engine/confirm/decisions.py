"""Agent decisions and spot checks over a batch of confirmer results.

The confirmer decides each failing cell by its rules. An agent decides only
the cells left ``needs_human`` and re-reads a seeded random 10% of each
verdict class. Both are data in catalog/triage_28.yaml:

* ``decisions``: match needs_human results by rule id, toolchain, outcome and
  regexes over reason and signature, and give a verdict with its basis. A
  decision never changes a verdict the rules gave.
* ``spot_checks``: one entry per signature group of the sampled cases
  (``spot_sample``, ``spot_groups``): agree true/false and a note.
* ``case_spot_checks``: one entry per sampled case (``case_sample``, at most
  CAP per class, agent-decided cells as class "agent-decided");
  ``case_agreement`` counts them."""
from __future__ import annotations

import random
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA = ROOT / "catalog" / "triage_28.yaml"


def _msg_key(text: str) -> str:
    t = re.sub(r"File = [^|]*\|", "", text or "")
    t = re.sub(r"ftn: ERROR \S+", "ftn: ERROR", t)
    t = re.sub(r'loc\("[^"]*":\d+:\d+\)', "loc", t)
    t = re.sub(r"<tmpdir>\S*|/\S+", "<path>", t)
    t = re.sub(r'"[A-Za-z0-9_$%]+"', '"X"', t)
    t = re.sub(r"checksum=-?\d+|expected=-?\d+", "", t)
    t = re.sub(r"0x[0-9a-fA-F]+|\d+", "N", t)
    return " ".join(t.split("; repeats")[0].split())[:120]


def signature(r: dict) -> str:
    """toolchain | outcome | rule | cause: the later form R11c names, the
    finding a bug is an instance of, else the message key."""
    c = r["case"]
    m = re.search(r"later form (\S+) \(", r.get("reason") or "")
    if m:
        cause = f"form {m.group(1)}"
    elif r.get("findings"):
        cause = "finding " + Path(r["findings"][0]["file"]).name
    else:
        cause = _msg_key(c.get("reason", ""))
    return f"{c['toolchain']}|{c['outcome']}|{r['rule']}|{cause}"


@dataclass(frozen=True)
class Decision:
    id: str
    verdict: str
    basis: str
    rule: str = "*"
    toolchains: tuple = ()
    outcomes: tuple = ()
    reason: str = ""
    sig: str = ""
    cases: tuple = ()
    own_sample_class: bool = False   # sampled as a class of its own

    def matches(self, r: dict) -> bool:
        from fnmatch import fnmatchcase
        c = r["case"]
        if r["verdict"] != "needs_human":
            return False
        if self.cases and c["case_id"] not in self.cases:
            return False
        if not fnmatchcase(r["rule"], self.rule):
            return False
        if self.toolchains and c["toolchain"] not in self.toolchains:
            return False
        if self.outcomes and c["outcome"] not in self.outcomes:
            return False
        if self.reason and not re.search(self.reason, c.get("reason", "")):
            return False
        if self.sig and not re.search(self.sig, signature(r)):
            return False
        return True


def load(path: Path = DATA) -> dict:
    if not Path(path).is_file():
        return {"decisions": [], "spot_checks": [], "case_spot_checks": []}
    d = yaml.safe_load(Path(path).read_text()) or {}
    if d.get("version") != 1:
        raise ValueError("triage_28: unknown version")
    decs = []
    for x in d.get("decisions") or ():
        m = x.get("match") or {}
        decs.append(Decision(x["id"], x["verdict"], x["basis"],
                             m.get("rule", "*"),
                             tuple(m.get("toolchains") or ()),
                             tuple(m.get("outcomes") or ()),
                             m.get("reason", ""), m.get("signature", ""),
                             tuple(m.get("cases") or ()),
                             bool(x.get("own_sample_class", False))))
    return {"decisions": decs, "spot_checks": list(d.get("spot_checks")
                                                    or ()),
            "case_spot_checks": list(d.get("case_spot_checks") or ())}


def apply(results: list[dict], decisions) -> list[dict]:
    """Each result with `final` (verdict) and `decided_by` ("rules" or
    the decision id): the first matching decision decides a needs_human
    result."""
    out = []
    for r in results:
        r = dict(r)
        r["final"], r["decided_by"] = r["verdict"], "rules"
        if r["verdict"] == "needs_human":
            for d in decisions:
                if d.matches(r):
                    r["final"], r["decided_by"] = d.verdict, d.id
                    break
        out.append(r)
    return out


def spot_sample(results: list[dict], frac: float = 0.1, seed: int = 28
                ) -> dict[str, list[str]]:
    """A seeded random `frac` (at least one) of each rule-decided verdict
    class, by case id."""
    by = defaultdict(set)
    for r in results:
        if r["verdict"] != "needs_human":
            by[r["verdict"]].add(r["case"]["case_id"])
    rnd = random.Random(seed)
    out = {}
    for v in sorted(by):
        ids = sorted(by[v])
        out[v] = sorted(rnd.sample(ids, max(1, round(len(ids) * frac))))
    return out


def spot_groups(results: list[dict], sample: dict) -> dict[str, list[str]]:
    """The sampled case ids by signature (verdict | signature)."""
    want = {c for v in sample.values() for c in v}
    out = defaultdict(list)
    for r in results:
        if r["case"]["case_id"] in want:
            out[f"{r['verdict']}|{signature(r)}"].append(
                r["case"]["case_id"])
    return {k: sorted(v) for k, v in sorted(out.items())}


CAP = 60
CASE_SEED = 2801          # A fresh draw


def own_classes(decisions) -> tuple:
    """The ids of the decisions sampled as a class of their own
    (``own_sample_class: true`` in the decisions file: a decision that
    would otherwise fill the agent-decided sample, e.g. one that came
    later with thousands of cells)."""
    return tuple(d.id for d in decisions if d.own_sample_class)


def case_sample(final: list[dict], frac: float = 0.1, cap: int = CAP,
                seed: int = CASE_SEED, own_class=()
                ) -> dict[str, list[str]]:
    """The case-level spot sample of results with `final`/`decided_by`
    (apply): a seeded `frac` of each final verdict class decided by the
    rules (needs_human included), at least one and at most `cap` cases,
    and the same of the agent-decided cells as class "agent-decided" (a
    decision in `own_class` as "agent-decided <id>")."""
    by = defaultdict(set)
    for r in final:
        d = r.get("decided_by", "rules")
        k = r["final"] if d == "rules" else \
            f"agent-decided {d}" if d in own_class else "agent-decided"
        by[k].add(r["case"]["case_id"])
    rnd = random.Random(seed)
    out = {}
    for v in sorted(by):
        ids = sorted(by[v])
        n = min(cap, max(1, round(len(ids) * frac)))
        out[v] = sorted(rnd.sample(ids, n))
    return out


def sample_of(checks: list[dict]) -> dict[str, list[str]]:
    """The recorded case-level sample (each check names the class its
    case had when the sample was drawn)."""
    out = defaultdict(list)
    for c in checks:
        out[c["class"]].append(c["case"])
    return {k: sorted(v) for k, v in sorted(out.items())}


def case_agreement(sample: dict, checks: list[dict]) -> dict:
    """Per sampled class: cases sampled, read (a check entry) and agreed."""
    by = {c["case"]: c for c in checks}
    return {v: {"sampled": len(ids),
                "read": sum(1 for c in ids if c in by),
                "agree": sum(1 for c in ids if c in by and by[c]["agree"])}
            for v, ids in sample.items()}
