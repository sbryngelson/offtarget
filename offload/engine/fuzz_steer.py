"""Steering the fuzzer with the usage profile, the failing real kernels and
campaign feedback, per compiler family.

The generator is unchanged. For each seed a steered campaign draws ``K``
fuzz-4s50 programs (seeds ``base + seed*K + j``) and keeps one with
probability proportional to its weight, so its seed replays it.

``Steer.weight`` multiplies three factors over the feature sets of the
program's offload regions (offload.engine.usage.region_features):

* profile: tempered log density ratio of real to generated feature
  frequencies, exponentiated and clipped to [1/20, 20];
* boost: x(1 + beta) per boost pair present, at most x4;
* feedback (``Feedback``): x2 near (Jaccard >= 0.5) a program with a new
  failure signature, x0.3 near one whose signature was seen ``SATURATED`` times."""
from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from offload.engine import usage as U

GEN = "fuzz-4s50"
K = 12
SATURATED = 5
SEED_BASE = 3_000_000           # steered campaigns' candidate seeds


def program_features(source: str) -> list[set]:
    return U.region_features(source)


def jaccard(a: set, b: set) -> float:
    return len(a & b) / max(1, len(a | b))


def family(tc: str) -> str:
    return "afar" if tc.startswith("afar") else "nvhpc" if \
        tc.startswith("nvhpc") else "cce"


@dataclass
class Feedback:
    """Per family: the feature sets of programs with a new failure
    signature and with saturated signatures, and signature counts."""
    counts: dict = field(default_factory=dict)       # family -> sig -> n
    new: dict = field(default_factory=dict)          # family -> [features]
    saturated: dict = field(default_factory=dict)    # family -> [features]

    def update(self, fam: str, sig: str, feats: set) -> None:
        c = self.counts.setdefault(fam, {})
        c[sig] = c.get(sig, 0) + 1
        if c[sig] == 1:
            self.new.setdefault(fam, []).append(sorted(feats))
        if c[sig] == SATURATED:
            self.saturated.setdefault(fam, []).append(sorted(feats))

    def multiplier(self, fam: str, feats: set) -> float:
        m = 1.0
        if any(jaccard(feats, set(f)) >= 0.5 for f in self.new.get(fam,
                                                                    [])[-50:]):
            m *= 2.0
        if any(jaccard(feats, set(f)) >= 0.5 for f in
               self.saturated.get(fam, [])):
            m *= 0.3
        return m

    def to_json(self) -> dict:
        return {"counts": self.counts, "new": self.new,
                "saturated": self.saturated}

    @staticmethod
    def from_json(d: dict) -> "Feedback":
        return Feedback(d.get("counts", {}), d.get("new", {}),
                        d.get("saturated", {}))


class Steer:
    def __init__(self, profile: dict, alpha: float = 0.5, beta: float = 0.5,
                 feedback: Feedback | None = None):
        self.alpha, self.beta = alpha, beta
        real = profile["real_frequencies"]["features"]
        gen = profile["generator_frequencies"]["features"]
        nr = max(1, profile["real_frequencies"]["regions"])
        ng = max(1, profile["generator_frequencies"]["regions"])
        self.terms = {}
        for f in set(gen):
            # smoothed frequencies (add one half)
            pr = (real.get(f, 0.0) * nr + 0.5) / (nr + 1)
            pg = (gen[f] * ng + 0.5) / (ng + 1)
            self.terms[f] = (math.log(pr / pg),
                             math.log((1 - pr) / (1 - pg)))
        self.pairs = [tuple(r["pair"]) for r in profile.get("boost_pairs",
                                                            [])]
        self.feedback = feedback or Feedback()

    def region_logw(self, s: set) -> float:
        return sum(a if f in s else b for f, (a, b) in self.terms.items())

    def weight(self, regions: list[set], fam: str | None = None) -> float:
        if not regions:
            return 1 / 20
        lw = sum(self.region_logw(s) for s in regions) / len(regions)
        w = min(20.0, max(1 / 20, math.exp(self.alpha * lw)))
        allf = set().union(*regions)
        hits = sum(1 for a, b in self.pairs if a in allf and b in allf)
        w *= min(4.0, (1 + self.beta) ** hits)
        if fam:
            w *= self.feedback.multiplier(fam, allf)
        elif self.feedback.counts:
            # a campaign that runs every program on every family: the mean
            # of the families' multipliers
            fams = sorted(self.feedback.counts)
            w *= sum(self.feedback.multiplier(f, allf) for f in fams) / \
                len(fams)
        return w

    def choose(self, seed: int, fam: str | None = None, k: int = K
               ) -> dict:
        """The kept candidate of campaign seed `seed`."""
        from offload.engine.fuzz import generate
        cands = []
        for j in range(k):
            s = SEED_BASE + seed * k + j
            p = generate(s, GEN)
            regs = program_features(p.source)
            cands.append((s, self.weight(regs, fam), regs))
        rng = random.Random(f"steer:{seed}:{fam}")
        tot = sum(w for _, w, _ in cands)
        x = rng.random() * tot
        for s, w, regs in cands:
            x -= w
            if x <= 0:
                break
        return {"seed": s, "weight": round(w, 4),
                "mean_weight": round(tot / k, 4),
                "features": sorted(set().union(*regs)) if regs else []}


def signature(cls: str, reason: str, tc: str) -> str:
    """A failure's signature for the feedback (and the campaign
    comparison): the family, the class and the message key (an ICE's or a
    rejection's message without positions, names and numbers; a run
    failure's kind)."""
    from offload.engine.confirm.decisions import _msg_key
    if cls in ("wrong_code", "host_fallback"):
        key = cls
    elif cls in ("run_error", "timeout", "run_timeout"):
        key = re.sub(r"\d+", "N", reason.split(";")[0])[:60]
    else:
        key = _msg_key(reason)
    return f"{family(tc)}|{cls}|{key}"


def feedback_from_campaign(programs_jsonl: Path, fb: Feedback | None = None
                           ) -> Feedback:
    """Feedback of a fuzz_exec campaign: every non-agree, non-reject
    class of a judged program updates its family's counts."""
    from offload.engine.fuzz import generate
    fb = fb or Feedback()
    for line in Path(programs_jsonl).read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("check") != "ok" or "results" not in d:
            continue
        feats = None
        for tc, r in d["results"].items():
            if r["cls"] in ("agree", "compile_reject", "harness_error"):
                continue
            if feats is None:
                p = generate(d["seed"], d["gen_version"],
                             tuple(d.get("base") or ()))
                feats = set().union(*program_features(p.source)) or set()
            fb.update(family(tc), signature(r["cls"], r["reason"], tc),
                      feats)
    return fb
