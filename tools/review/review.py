#!/usr/bin/env python3
"""Independent legality reviews of the findings (offload.engine.legality_review, README.md here).

    python3 -I tools/review/review.py select [--set wrong-current]   # the finding ids of a set
    python3 -I tools/review/review.py prepare --out DIR [--per 4] [--readings 2] [IDS...]
    python3 -I tools/review/review.py disputes --out DIR [--argument FILE ID]   # adjudication batches
    python3 -I tools/review/review.py verify --out DIR [--per 8]     # claim verification batches
    python3 -I tools/review/review.py ingest DIR                     # check the answers, write the records
    python3 -I tools/review/review.py rule ID --spec openmp-5.2.txt --section 3.2.6 --quote TEXT --why TEXT
                                                                     # a maintainer's ruling (see README.md)

`prepare` writes DIR/batch-NN/ with one anonymized case file per finding, one decoy, key.json and
prompt.txt; `disputes` does the same for the findings whose readers disagree or are uncertain, adding
both readings and a decoy dispute. A reader works one batch and writes out.jsonl. `ingest` checks
each batch's decoy and quotes and writes data/findings/reviews/<id>.json. Nothing here runs a model."""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import legality_review as L  # noqa: E402

HERE = Path(__file__).resolve().parent
DECOYS = HERE / "decoys"
SPEC_DIR = L.SPEC_TEXT


def _pages() -> dict:
    from offload.engine.site import data as D
    return D.records(D.gather())["pages"]


def current_releases() -> dict:
    """family -> its newest measured release (a regression release is no headline)."""
    from offload.engine.toolchains import registry
    reg = registry()
    out = {}
    for name, (fam, _label, order) in reg.versions().items():
        if reg.toolchains[name].regression_of:
            continue
        if fam not in out or order > out[fam][1]:
            out[fam] = (name, order)
    return {f: n for f, (n, _o) in out.items()}


def select(which: str, pages: dict) -> list[str]:
    """wrong-current: the defects with a wrong answer still open on a family's newest release;
    current: any defect open there; unreviewed: every defect without a review record; all: every
    defect."""
    cur = current_releases()
    out = []
    for fid, p in sorted(pages.items()):
        if p["defect"] != fid or which == "wrong-current" and p.get("symptom") != "wrong_answer":
            continue
        if which == "all":
            out.append(fid)
            continue
        if which == "unreviewed":
            if L.load(fid) is None:
                out.append(fid)
            continue
        if any(v["status"] == "open" and cur.get(f) in v["versions"] for f, v in p["fams"].items()):
            out.append(fid)
    return out


def _anon(text: str) -> str:
    """Compiler messages without file names or the harness's prefixes."""
    text = re.sub(r"[\w./<>-]*?[\w-]+\.(f90|F90|c|cpp)\b", lambda m: "prog." + m.group(1).lower(), text)
    return text.replace("<tmpdir>", "").replace("diagnostic: ", "")


def case_text(n: int, c: dict) -> str:
    ext = "c" if c["lang"] == "C" else "f90"
    fails = ", ".join(f"compiler {chr(65 + j)}" for j in range(max(1, min(c["nfail"], 4))))
    oks = ", ".join(f"compiler {chr(69 + j)}" for j in range(min(c["nok"], 4))) or "none recorded"
    return (f"# Case {n}\n\nModel and language: {c['model']}, {c['lang']}. Specification version: "
            f"{c['version']}.\n\nCompilers that do not produce the expected result: {fails}.\n"
            f"Failure kind: {c['failure']}.\nCompilers that run it as expected: {oks}.\n"
            + (f"Memory: {c['memory']}\n" if c.get("memory") else "")
            + f"Expected result: {c['expected']}\nObserved (first failing compiler): {c['observed']}\n\n"
            f"```{ext}\n{c['code'].rstrip()}\n```\n")


def finding_case(fid: str, page: dict) -> dict:
    f = L.finding_file(fid)
    versions = sorted(set(re.findall(r"(?:OpenMP|OpenACC) \d\.\d", " ".join(page.get("specs") or []))))
    model = "OpenACC" if page["model"] == "acc" else "OpenMP"
    return {"id": fid, "code": L.program_text(f), "sha": L.program_sha(f),
            "lang": "C" if page["lang"] == "c" else "Fortran", "model": model,
            "version": ", ".join(versions) or ("OpenACC 3.4" if model == "OpenACC" else "OpenMP 5.2"),
            "failure": page.get("failure") or page.get("symptom") or "",
            "nfail": sum(1 for v in page["fams"].values() if v["status"] == "open" and v["versions"]),
            "nok": len(page.get("witnesses") or []),
            "expected": page.get("expected") or "see the program",
            "observed": _anon((page.get("observed") or "").strip())[:400],
            "memory": L.memory_line(page.get("targets_failing") or [])}


def prepare(out: Path, ids: list[str], per: int, readings: int, seed: int) -> int:
    pages = _pages()
    cases = [finding_case(i, pages[i]) for i in ids]
    decoys = json.loads((DECOYS / "decoys.json").read_text())
    rng = random.Random(seed)
    batches = []
    for r in range(readings):
        order = cases[:]
        rng.shuffle(order)
        batches += [order[i:i + per] for i in range(0, len(order), per)]
    out.mkdir(parents=True, exist_ok=True)
    instr = (HERE / "instructions.md").read_text()
    for b, group in enumerate(batches, 1):
        d = out / f"batch-{b:02d}"
        d.mkdir(exist_ok=True)
        dec = dict(decoys[(b - 1) % len(decoys)])
        dec["code"] = (DECOYS / dec["file"]).read_text()
        items = [("finding", c) for c in group] + [("decoy", dec)]
        rng.shuffle(items)
        key = []
        for n, (kind, c) in enumerate(items, 1):
            (d / f"case-{n:02d}.md").write_text(case_text(n, c))
            key.append({"case": n, "kind": kind, "id": c.get("id") or c["file"], "sha": c.get("sha"),
                        "answer": c.get("answer")})
        (d / "key.json").write_text(json.dumps({"round": "read", "instructions": L.INSTRUCTIONS, "cases": key},
                                               indent=1) + "\n")
        paths = "\n".join(str(d / f"case-{n:02d}.md") for n in range(1, len(items) + 1))
        (d / "prompt.txt").write_text(instr.format(cases=paths, spec_dir=SPEC_DIR, out=d / "out.jsonl"))
    print(f"{len(ids)} findings, {readings} readings, {len(batches)} batches -> {out}")
    return 0


def _readings_text(a: str, b: str) -> str:
    return f"\n## Reading A\n\n{a}\n\n## Reading B\n\n{b}\n"


def _reading(r: dict) -> str:
    return f"legal: {r['legal']}, result_required: {r['result_required']}. {r['reasoning']}"


def dispute_readings(rec: dict, outside: str | None) -> tuple[str, str]:
    """The two readings an adjudicator weighs: two counted readings, or, for a dispute from outside
    (an issue), the first counted reading and the outside argument."""
    rs = [_reading(r) for r in rec["readers"] if L.counted(r)]
    return (rs[0], outside.strip()) if outside else (rs[0], rs[1])


def disputed() -> list[str]:
    """Findings whose counted readers disagree or are uncertain and that have no adjudicators under
    the current instructions yet."""
    out = []
    for p in sorted(L.REVIEWS.glob("*.json")):
        rec = json.loads(p.read_text())
        current = [a for a in rec.get("adjudicators", []) if a.get("instructions", "v1") == L.INSTRUCTIONS]
        if rec.get("advisory", rec["verdict"]) in ("contested", "unconfirmed") and not current \
                and sum(L.counted(r) for r in rec["readers"]) >= 2:
            out.append(p.stem.replace("--", "/"))
    return out


def prepare_disputes(out: Path, ids: list[str], per: int, seed: int, outside: str | None = None) -> int:
    pages = _pages()
    rng = random.Random(seed)
    cases = []
    for fid in ids:
        c = finding_case(fid, pages[fid])
        pair = list(dispute_readings(L.load(fid), outside))
        rng.shuffle(pair)
        c["readings"] = _readings_text(*pair)
        cases.append(c)
    decoys = json.loads((DECOYS / "decoys.json").read_text())
    batches = []
    for _r in range(2):
        order = cases[:]
        rng.shuffle(order)
        batches += [order[i:i + per] for i in range(0, len(order), per)]
    out.mkdir(parents=True, exist_ok=True)
    instr = (HERE / "adjudicate.md").read_text()
    for b, group in enumerate(batches, 1):
        d = out / f"batch-{b:02d}"
        d.mkdir(exist_ok=True)
        dec = dict(decoys[(b - 1) % len(decoys)])
        dec["code"] = (DECOYS / dec["file"]).read_text()
        pair = [dec["right_reading"], dec["wrong_reading"]]
        rng.shuffle(pair)
        dec["readings"] = _readings_text(*pair)
        items = [("finding", c) for c in group] + [("decoy", dec)]
        rng.shuffle(items)
        key = []
        for n, (kind, c) in enumerate(items, 1):
            (d / f"case-{n:02d}.md").write_text(case_text(n, c) + c["readings"])
            key.append({"case": n, "kind": kind, "id": c.get("id") or c["file"], "sha": c.get("sha"),
                        "answer": c.get("answer")})
        (d / "key.json").write_text(json.dumps({"round": "adjudicate", "instructions": L.INSTRUCTIONS, "cases": key},
                                               indent=1) + "\n")
        paths = "\n".join(str(d / f"case-{n:02d}.md") for n in range(1, len(items) + 1))
        (d / "prompt.txt").write_text(instr.format(cases=paths, spec_dir=SPEC_DIR, out=d / "out.jsonl"))
    print(f"{len(ids)} disputed findings, {len(batches)} adjudication batches -> {out}")
    return 0


def _counted_refutations(r: dict) -> tuple[int, int]:
    vs = [v for v in r.get("verifications", []) if L.verification_counted(v)]
    return sum(1 for v in vs if v.get("refuted")), len(vs)


def verify_targets() -> list[dict]:
    """The readings to verify: every reading and adjudication that counts under the current
    instructions and has no counted verification yet, and those one counted verifier refuted
    (they get a second verifier)."""
    out = []
    for p in sorted(L.REVIEWS.glob("*.json")):
        rec = json.loads(p.read_text())
        fid = p.stem.replace("--", "/")
        for role in ("readers", "adjudicators"):
            for r in rec.get(role, []):
                if not L.counted(r):
                    continue
                n, m = _counted_refutations(r)
                if m == 0 or (n == 1 and m == 1):
                    out.append({"id": fid, "role": role, "run": r["run"], "reading": r})
    return sorted(out, key=lambda t: (t["id"], t["role"], t["run"]))


def _reading_text(r: dict) -> str:
    quotes = "".join(f"\n- {p.get('spec', p.get('file', ''))} {p.get('section', '')}: \"{p.get('quote', '')}\""
                     for p in (r.get("passages") or []))
    return (f"\n## The reading\n\nlegal: {r['legal']}, result_required: {r['result_required']}.\n\n"
            f"{r.get('reasoning', '')}\n" + (f"\nPassages it quotes:{quotes}\n" if quotes else ""))


def prepare_verify(out: Path, per: int, seed: int) -> int:
    """Batches of `per` readings to verify, each with two decoy readings of a decoy program: one
    with a false premise (to refute) and one sound (to uphold)."""
    pages = _pages()
    rng = random.Random(seed)
    targets = verify_targets()
    rng.shuffle(targets)
    decoys = json.loads((DECOYS / "decoys.json").read_text())
    out.mkdir(parents=True, exist_ok=True)
    instr = (HERE / "verify.md").read_text()
    batches = [targets[i:i + per] for i in range(0, len(targets), per)]
    for b, group in enumerate(batches, 1):
        d = out / f"batch-{b:02d}"
        d.mkdir(exist_ok=True)
        dec = dict(decoys[(b - 1) % len(decoys)])
        dec["code"] = (DECOYS / dec["file"]).read_text()
        items = [("reading", t, case_text(0, finding_case(t["id"], pages[t["id"]])) + _reading_text(t["reading"]))
                 for t in group]
        for kind, text in (("decoy-false", dec["wrong_reading"]), ("decoy-true", dec["right_reading"])):
            items.append((kind, {"id": dec["file"]}, case_text(0, dec) + f"\n## The reading\n\n{text}\n"))
        rng.shuffle(items)
        key = []
        for n, (kind, t, text) in enumerate(items, 1):
            (d / f"case-{n:02d}.md").write_text(text.replace("# Case 0", f"# Case {n}", 1))
            key.append({"case": n, "kind": kind, "id": t["id"], "role": t.get("role"), "run": t.get("run"),
                        "sha": L.program_sha(L.finding_file(t["id"])) if kind == "reading" else None})
        (d / "key.json").write_text(json.dumps({"round": "verify", "cases": key}, indent=1) + "\n")
        paths = "\n".join(str(d / f"case-{n:02d}.md") for n in range(1, len(items) + 1))
        (d / "prompt.txt").write_text(instr.format(cases=paths, spec_dir=SPEC_DIR, out=d / "out.jsonl"))
    print(f"{len(targets)} readings, {len(batches)} verification batches -> {out}")
    return 0


def _ingest_verify(run: Path, d: Path, key: dict, ans: dict, records: dict) -> None:
    """A verification batch: its decoys, then each verified reading gets the verification."""
    want = {"decoy-false": True, "decoy-true": False}
    ok = all(n in ans and bool(ans[n].get("refuted")) == want[k["kind"]] for n, k in key.items() if k["kind"] in want)
    print(f"{d.name}: decoys {'caught' if ok else 'missed'}, {len(ans)} answers")
    rid = f"{run.name}/{d.name}"
    for n, k in key.items():
        if k["kind"] != "reading" or n not in ans:
            continue
        a = ans[n]
        claims = a.get("claims") or []
        refuted = bool(a.get("refuted")) and any(str(c.get("verdict", "")).lower() == "false" for c in claims)
        passages = [p for c in claims for p in (c.get("passages") or [])]
        lines = [x for c in claims for x in (c.get("program_lines") or [])]
        rec = records.setdefault(k["id"], L.load(k["id"]))
        if rec is None or rec.get("program_sha") != k["sha"]:
            print(f"{k['id']}: no record or the program changed; verification skipped")
            continue
        r = next((x for x in rec.get(k["role"], []) if x.get("run") == k["run"]), None)
        if r is None:
            continue
        r["verifications"] = [v for v in r.get("verifications", []) if v.get("run") != rid] + [{
            "run": rid, "model": "claude-sonnet", "batch_decoys": "caught" if ok else "missed", "refuted": refuted,
            "false_claims": [c.get("claim", "") for c in claims if str(c.get("verdict", "")).lower() == "false"],
            "quotes": L.check_quotes(passages),
            "program": L.check_program({"program_lines": lines}, L.program_text(L.finding_file(k["id"])))}]


def _case_no(v) -> int:
    return int(re.sub(r"\D", "", str(v)) or 0)


def caught(answer: str, r: dict) -> bool:
    if answer == "illegal":
        return r.get("legal") == "no"
    return r.get("result_required") == "no" or r.get("legal") == "no"


def _clip(text: str, n: int = 450) -> str:
    """The text up to its last full sentence within n characters (else the last whole word)."""
    text = " ".join(text.split())
    # the adjudicators' "Reading A/B" are labels of their batch only; a reader of the site has none
    # (a short "Both readings hold." judges the readings only; a longer sentence about them carries a point)
    text = " ".join(x for x in re.split(r"(?<=[.;])\s+", text)
                    if not re.search(r"\bReadings? [AB]\b", x)
                    and not (len(x) < 60 and re.search(r"\b(both|either|neither) readings?\b", x, re.I)))
    if len(text) <= n:
        return text
    cut = text[:n]
    end = cut.rfind(". ")
    return cut[:end + 1] if end > n // 3 else cut[:cut.rfind(" ")] + " ..."


def _ruling_text(rec: dict) -> str:
    """What the site says of a ruling: whose it is, the passages it cites and its reason."""
    r = rec["ruling"]
    cites = "; ".join(f'{L._SPEC_FILE.get(p["spec"].removesuffix(".txt"), p["spec"])} \u00a7{p["section"]}: '
                      f'"{p["quote"]}"' for p in r["passages"])
    return f"A maintainer's ruling, citing {cites}. {r['reasoning']}"


def advisory_why(rec: dict) -> str:
    """The AI readings' explanation (advisory; never published)."""
    v = rec.get("advisory") or rec.get("verdict")
    if v == "ruled":
        rs = [r for r in rec.get("adjudicators", []) + rec["readers"] if L.counted(r)]
        dissent = next((r for r in rs if r["legal"] == "no" or r["result_required"] == "no"), None)
        return _ruling_text(rec) + (" The independent readings had found otherwise: "
                                    + _clip(dissent.get("reasoning", ""), 300) if dissent and dissent.get("reasoning") else "")
    rs = [r for r in rec["readers"] if L.counted(r)]
    adj = [r for r in rec.get("adjudicators", []) if L.counted(r)]
    no = lambda r: r["legal"] == "no" or r["result_required"] == "no"  # noqa: E731
    if v == "confirmed" and adj:
        doubt = next((r for r in rs if r["legal"] != "yes" or r["result_required"] != "yes"), None)
        return ("One independent reading " + ("disputed it" if doubt and no(doubt) else "was uncertain")
                + f"; {len(adj)} adjudicating readings that weighed both find the program legal and the "
                "result required: " + _clip(adj[0]["reasoning"]))
    if v == "confirmed":
        return f"{len(rs)} independent readings find the program legal and the result required."
    dissent = next((r for r in adj + rs if no(r)), None)
    if v == "contested" and dissent:
        return ("An independent " + ("adjudicating reading" if dissent in adj else "reading") + " finds "
                + ("the program not legal" if dissent["legal"] == "no" else "the result not required")
                + ": " + _clip(dissent["reasoning"]))
    if v == "supported":
        strong = [p for p in rec.get("prior_art", []) if p.get("strength") == "strong"]
        return ("Independent readings find the specification unclear here; "
                + (f"{strong[0]['where']} shows the same program working." if strong
                   else "outside evidence settles it."))
    unsure = next((r for r in adj + rs if r["legal"] != "yes" or r["result_required"] != "yes"), None)
    if unsure:
        return "Independent readings are uncertain: " + _clip(unsure["reasoning"])
    return "No counted independent reading yet."


def ingest(run: Path) -> int:
    records: dict[str, dict] = {}
    answers = {d["file"]: d["answer"] for d in json.loads((DECOYS / "decoys.json").read_text())}
    for d in sorted(run.glob("batch-*")):
        outf = d / "out.jsonl"
        if not outf.is_file():
            print(f"{d.name}: no answers yet")
            continue
        raw = json.loads((d / "key.json").read_text())
        if isinstance(raw, dict) and raw.get("round") == "verify":
            ans = {}
            for ln in outf.read_text().splitlines():
                if ln.strip():
                    a = json.loads(ln)
                    ans[_case_no(a.get("case"))] = a
            _ingest_verify(run, d, {k["case"]: k for k in raw["cases"]}, ans, records)
            continue
        role = "adjudicators" if isinstance(raw, dict) and raw.get("round") == "adjudicate" else "readers"
        version = raw.get("instructions", "v1") if isinstance(raw, dict) else "v1"   # batches before v2: a bare list
        key = {k["case"]: k for k in (raw["cases"] if isinstance(raw, dict) else raw)}
        ans = {}
        for ln in outf.read_text().splitlines():
            if ln.strip():
                a = json.loads(ln)
                ans[_case_no(a.get("case"))] = a
        dec = next(k for k in key.values() if k["kind"] == "decoy")
        answer = answers.get(dec["id"], dec["answer"])     # the answer key as it is now
        ok = dec["case"] in ans and caught(answer, ans[dec["case"]])
        print(f"{d.name}: decoy {'caught' if ok else 'missed'}, {len(ans)} answers")
        for n, k in key.items():
            if k["kind"] != "finding" or n not in ans:
                continue
            a = ans[n]
            rec = records.setdefault(k["id"], L.load(k["id"]) or {
                "finding": str(L.finding_file(k["id"]).relative_to(L.FINDINGS)), "readers": [],
                "prior_art": [], "external": []})
            if rec.get("program_sha") not in (None, k["sha"]):
                if role == "adjudicators":
                    print(f"{k['id']}: the program changed since its readings; adjudication skipped")
                    continue
                rec["readers"] = []            # the program changed: earlier readings no longer apply
                rec.pop("adjudicators", None)
                rec.pop("ruling", None)        # and neither does a ruling on the old program
            rec["program_sha"] = k["sha"]
            rec["instructions"] = L.INSTRUCTIONS
            rid = f"{run.name}/{d.name}"
            rec[role] = [r for r in rec.get(role, []) if r.get("run") != rid]
            rec[role].append({"run": rid, "model": "claude-sonnet", "instructions": version,
                                   "batch_decoy": "caught" if ok else "missed",
                                   "legal": a.get("legal"), "result_required": a.get("result_required"),
                                   "quotes": L.check_quotes(a.get("passages")),
                                   "program": L.check_program(a, L.program_text(L.finding_file(k["id"]))),
                                   "reasoning": a.get("reasoning", "")})
    L.REVIEWS.mkdir(parents=True, exist_ok=True)
    for fid, rec in records.items():
        settle(fid, rec)
        L.record_path(fid).write_text(json.dumps(rec, indent=1) + "\n")
    from collections import Counter
    print(dict(Counter(r["verdict"] for r in records.values())), f"{len(records)} records")
    return 0


_SOURCE_WORDS = {"other-family": "another compiler family's run", "self-check": "the program's own check",
                 "generator-model": "the generator's model"}


def why_of(rec: dict) -> str:
    """What the site says of the verdict: only its mechanical basis or the maintainer's ruling."""
    v = rec["verdict"]
    m = rec.get("mechanical") or {}
    if v == "ruled":
        return _ruling_text(rec)
    if v == "refuted":
        if m.get("rules") == "reject":
            return "The rules engine rejects the program: " + _clip("; ".join(m.get("rules_why") or []), 300)
        return "The result the program checks is not required: " + _clip("; ".join(m.get("hazards") or []), 300)
    if v == "supported":
        return "Outside evidence supports it: " + _clip("; ".join(str(e.get("source", e)) for e in rec["external"]), 300)
    if v == "checked":
        w = ", ".join(m.get("witnesses") or []) or "another family's front end"
        exp = "" if m.get("outcome") in L.ACCEPTANCE else f"; the expected result comes from {_SOURCE_WORDS[m['expected']]}"
        return f"The rules engine accepts the program and {w} of another compiler family build{'s' if ',' not in w else ''} and run it as expected{exp}."
    if not m:
        return "Not yet checked."
    gaps = []
    if m.get("rules") != "accept":
        gaps.append("the rules engine cannot read it" if m.get("rules") == "unreadable" else "the rules engine does not accept it")
    if m.get("witness") == "reject":
        names = {"afar-frontend": "AMD's", "nvhpc": "NVHPC's"}
        who = sorted({names["nvhpc" if k.startswith("nvhpc") else k] for k, v in (m.get("front_ends") or {}).items()
                      if v == "reject" and (k.startswith("nvhpc") or k in names)}) or ["a"]
        gaps.append(f"{' and '.join(who)} front end{'s' if len(who) > 1 else ''}, of another family, reject{'' if len(who) > 1 else 's'} it")
    elif m.get("witness") != "accept":
        gaps.append("no compiler of another family (GCC does not count) has accepted it")
    if m.get("outcome") not in L.ACCEPTANCE and m.get("expected") not in L.EXPECTED_SOURCES:
        gaps.append("no independent source gives the expected result")
    return "Not yet settled: " + "; ".join(gaps) + ". A maintainer's ruling decides it."


def settle(fid: str, rec: dict) -> dict:
    """Recompute a record's verdicts: the legality verdict (mechanical), the advisory one (AI readings)."""
    rec["advisory"] = L.advisory(rec)
    rec["advisory_why"] = advisory_why(rec) if rec.get("readers") else ""
    rec["verdict"] = L.verdict(rec)
    rec["why"] = why_of(rec)
    return rec


def _findings() -> dict:
    """{finding id: (index entry, program path)} of every finding of the index."""
    from offload.engine.confirm.findings import load_index
    out = {}
    for f in load_index():
        fid = str(Path(f.file).relative_to("data/findings").with_suffix(""))
        out[fid] = (f, L.finding_file(fid))
    return out


def _lang_model(path: Path) -> tuple[str, str]:
    text = path.read_text(errors="replace")
    model = "acc" if re.search(r"^\s*(?:!\$acc|#\s*pragma\s+acc)\b", text, re.M | re.I) else "omp"
    return ("c" if path.suffix in (".c", ".cpp") else "f90"), model


def stale_records() -> list[str]:
    """The findings whose record is missing or was computed from other inputs than the current ones
    (legality_mechanical.inputs_hash)."""
    from offload.engine import legality_mechanical as LM
    from offload.engine.site import matrix as M
    rows, cases, wit, code = M._rows(), M._cases(), LM.load_rows(), LM.code_hash()
    out = []
    for fid, (f, path) in sorted(_findings().items()):
        if path is None:
            continue
        rec = L.load(fid) or {}
        want = LM.inputs_hash(L.program_sha(path), f.outcome, M.cells(fid, rows, cases), wit, fid, code)
        if (rec.get("mechanical") or {}).get("inputs") != want:
            out.append(fid)
    return out


def mechanical(ids: list[str], frontend: bool = False, nvhpc: bool = False) -> int:
    """Each finding's mechanical evidence (offload.engine.legality_mechanical) from its program, the
    committed rows and the stored front-end rows, and its verdicts; every finding of the index when
    ids is empty. --frontend (a compute node) first runs AMD's front end on the findings that need
    it and stores the rows (catalog/finding_witness.yaml); --nvhpc does the same with NVHPC's front ends
    (catalog/machines.yaml independent_checkers, over ssh)."""
    from collections import Counter
    from offload.engine import legality_mechanical as LM
    from offload.engine.site import matrix as M
    rows, cases = M._rows(), M._cases()
    index = _findings()
    ids = ids or sorted(index)
    wit = LM.load_rows()
    cells = {fid: M.cells(fid, rows, cases) for fid in ids if fid in index}
    if frontend or nvhpc:
        want, witnessed = {}, set()
        for fid, cs in cells.items():
            path = index[fid][1]
            if path is None:
                continue
            failing = {LM._family(c.tc) for c in cs if c.state == "fails-like"}
            if any(c.state == "correct" and LM._family(c.tc) not in failing | LM.NOT_A_WITNESS for c in cs):
                witnessed.add(fid)
            want[fid] = (L.program_sha(path), failing)
        for fam, on in (("afar", frontend), ("nvhpc", nvhpc)):
            if not on:
                continue
            need = LM.needs_frontend(want, wit, witnessed, family=fam)
            print(f"{fam} front end: {len(need)} findings")
            for fid in need:
                path = index[fid][1]
                lang, model = _lang_model(path)
                text = path.read_text(errors="replace")
                got = LM.frontend_row(fid, want[fid][0], text, lang, model) if fam == "afar" \
                    else LM.nvhpc_rows(fid, want[fid][0], text, lang, model)
                if got is None:
                    print(f"{fid}: the {fam} front end cannot run or be reached here")
                    if fam == "nvhpc":
                        break           # an unreachable machine stays unreachable for the rest
                    continue
                got = got if isinstance(got, list) else [got]
                wit = [x for x in wit if not (x["finding"] == fid and x.get("family", "afar") == fam)] + got
                print(f"{fid}: {', '.join(r['checker'] + ' ' + r['result'] for r in got) or 'no checker'}")
        LM.write_rows(wit)
    code = LM.code_hash()
    out = Counter()
    for fid in ids:
        if fid not in index or index[fid][1] is None:
            print(f"{fid}: not a finding of the index"); continue
        f, path = index[fid]
        text = path.read_text(errors="replace")
        lang, model = _lang_model(path)
        sha = L.program_sha(path)
        rec = L.load(fid) or {"readers": [], "program_sha": sha}
        m = LM.evidence(text, lang, model, f.outcome, cells[fid], wit, fid, sha)
        m["program_sha"] = sha
        m["inputs"] = LM.inputs_hash(sha, f.outcome, cells[fid], wit, fid, code)
        rec["mechanical"] = m
        settle(fid, rec)
        L.REVIEWS.mkdir(parents=True, exist_ok=True)
        L.record_path(fid).write_text(json.dumps(rec, indent=1) + "\n")
        out[rec["verdict"]] += 1
    print(dict(out), f"{sum(out.values())} findings")
    return 0


def queue() -> list[tuple[str, str, str]]:
    """(finding, gap, advisory) of every open finding: what a maintainer's ruling would settle."""
    out = []
    for p in sorted(L.REVIEWS.glob("*.json")):
        rec = json.loads(p.read_text())
        if rec.get("verdict") == "open":
            out.append((p.stem.replace("--", "/"), rec.get("why", "").removeprefix("Not yet settled: "),
                        rec.get("advisory", "")))
    return out


def rule(fid: str, spec: str, section: str, quotes: list[str], why: str, date: str) -> int:
    """Record a maintainer's ruling on a finding: refused unless every quote is in the
    specification under the section named (legality_review.check_quotes)."""
    rec = L.load(fid)
    f = L.finding_file(fid)
    if rec is None or f is None:
        print(f"{fid}: no review record or no finding")
        return 1
    passages = [{"spec": spec, "section": section, "quote": q} for q in quotes]
    checked = L.check_quotes(passages)
    if checked["not_found"] or checked["wrong_section"] or not checked["ok"]:
        print(f"{fid}: refused, the quotes do not all check out under {spec} \u00a7{section}: {checked}")
        return 1
    if rec.get("program_sha") != L.program_sha(f):
        print(f"{fid}: refused, the program changed since its review; review it again first")
        return 1
    rec["ruling"] = {"by": "maintainer", "date": date, "passages": passages, "quotes": checked, "reasoning": why}
    settle(fid, rec)
    L.record_path(fid).write_text(json.dumps(rec, indent=1) + "\n")
    print(f"{fid}: {rec['verdict']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--set", default="wrong-current", choices=("wrong-current", "current", "unreviewed", "all"))
    p = sub.add_parser("prepare")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--per", type=int, default=4)
    p.add_argument("--readings", type=int, default=2)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--set", default="wrong-current", choices=("wrong-current", "current", "unreviewed", "all"))
    p.add_argument("ids", nargs="*")
    q = sub.add_parser("disputes")
    q.add_argument("--out", type=Path, required=True)
    q.add_argument("--per", type=int, default=4)
    q.add_argument("--seed", type=int, default=1)
    q.add_argument("--argument", type=Path, help="an outside dispute (the issue's argument) of the one finding named")
    q.add_argument("ids", nargs="*")
    v = sub.add_parser("verify")
    v.add_argument("--out", type=Path, required=True)
    v.add_argument("--per", type=int, default=8)
    v.add_argument("--seed", type=int, default=1)
    i = sub.add_parser("ingest")
    i.add_argument("run", type=Path)
    r = sub.add_parser("rule", help="a maintainer's ruling that cites the specification")
    r.add_argument("id")
    r.add_argument("--spec", required=True, help="the specification text, e.g. openmp-5.2.txt")
    r.add_argument("--section", required=True)
    r.add_argument("--quote", action="append", required=True, help="a verbatim passage (repeatable)")
    r.add_argument("--why", required=True, help="the reasoning, one or two sentences")
    r.add_argument("--date", default=__import__("datetime").date.today().isoformat())
    mc = sub.add_parser("mechanical", help="the mechanical legality evidence and verdicts (no AI reading)")
    mc.add_argument("--frontend", action="store_true", help="also run AMD's front end (a compute node)")
    mc.add_argument("--nvhpc", action="store_true", help="also run NVHPC's front ends (over ssh)")
    mc.add_argument("ids", nargs="*")
    sub.add_parser("queue", help="the open findings a maintainer's ruling would settle, by gap")
    a = ap.parse_args(argv)
    if a.cmd == "queue":
        from itertools import groupby
        rows = sorted(queue(), key=lambda r: r[1])
        for gap, grp in groupby(rows, key=lambda r: r[1]):
            grp = list(grp)
            print(f"{len(grp)}: {gap}")
            for fid, _, adv in grp:
                print(f"    {fid}" + (f"  (AI readings: {adv})" if adv else ""))
        return 0
    if a.cmd == "mechanical":
        return mechanical(a.ids, a.frontend, a.nvhpc)
    if a.cmd == "rule":
        return rule(a.id, a.spec, a.section, a.quote, a.why, a.date)
    if a.cmd == "select":
        print("\n".join(select(a.set, _pages())))
        return 0
    if a.cmd == "prepare":
        ids = a.ids or select(a.set, _pages())
        return prepare(a.out, ids, a.per, a.readings, a.seed)
    if a.cmd == "verify":
        return prepare_verify(a.out, a.per, a.seed)
    if a.cmd == "disputes":
        if a.argument and len(a.ids) != 1:
            ap.error("--argument takes exactly one finding id")
        return prepare_disputes(a.out, a.ids or disputed(), a.per, a.seed,
                                a.argument.read_text() if a.argument else None)
    return ingest(a.run)


if __name__ == "__main__":
    sys.exit(main())
