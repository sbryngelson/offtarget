"""The words of a generated finding, from what the tools recorded: the key constructs are what the
reduction's one-change controls changed (its report.md), and the title, file name, rule and site text
follow from them, the failure and the specification (offload.engine.fuzz_cites). Nothing is
written by hand; a finding whose controls changed nothing keeps the reduced program's own key
constructs (offload.engine.confirm.findings key constructs)."""
from __future__ import annotations

import re

# what each failure is, as a title says it
VERB = {"crash": "aborts at run time", "run_error": "stops with a run-time error", "timeout": "hangs",
        "wrong_answer": "gives a wrong result", "fell_back_to_host": "runs a target region on the host",
        "ice": "crashes while compiling", "rejected": "refuses"}
SLUG = {"crash": "abort", "run_error": "run-error", "timeout": "hang", "wrong_answer": "wrong",
        "fell_back_to_host": "host-fallback", "ice": "ice", "rejected": "rejected"}
LANG = {"f90": "Fortran", "c": "C"}
MODEL = {"omp": "OpenMP", "acc": "OpenACC"}
# the opening of the rule: what the specification requires of every conforming program
REQUIRES = {"wrong": "a conforming program's result is the one its constructs define",
            "abort": "a conforming program runs to completion",
            "compile": "a conforming program compiles and links"}

_EDIT = re.compile(r"^- `controls/[^`]+`: (.+?) at line \d+;", re.M)


def control_constructs(report: str) -> list[str]:
    """The construct keys the reduction's controls changed, in order: "unwrap teams" -> dir:teams,
    "delete clause thread_limit(1)" -> clause:thread_limit, "shorten target parallel to target"
    -> dir:parallel, "drop r1a from map(...)" -> clause:map."""
    sec = report.split("## Controls", 1)[-1].split("\n## ", 1)[0]
    out = []
    for edit in _EDIT.findall(sec):
        if edit.startswith("unwrap "):
            key = "dir:" + edit[len("unwrap "):].strip()
        elif edit.startswith("delete clause "):
            key = "clause:" + re.split(r"[(\s]", edit[len("delete clause "):].strip())[0]
        elif edit.startswith("shorten "):
            m = re.match(r"shorten (.+?) to (.+)$", edit)
            gone = [w for w in m.group(1).split() if w not in m.group(2).split()] if m else []
            key = "dir:" + " ".join(gone) if gone else None
        elif edit.startswith("drop "):
            m = re.search(r"from (\w+)\(", edit)
            key = "clause:" + m.group(1) if m else None
        else:
            key = None
        if key and key not in out:
            out.append(key)
    return out


def _phrase(key: str) -> str:
    kind, _, name = key.partition(":")
    art = "an" if name[:1] in "aeio" else "a"
    return f"{art} {name} clause" if kind == "clause" else f"{art} {name} construct"


def model_of(text: str) -> str:
    """acc when the program has an OpenACC directive (!$acc, #pragma acc), else omp."""
    return "acc" if re.search(r"^\s*(?:!\$acc|#\s*pragma\s+acc)\b", text, re.M | re.I) else "omp"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def title(label: str, outcome: str, lang: str, model: str, keys: list[str], link: bool = False) -> str:
    verb = "fails to link" if outcome == "rejected" and link else VERB.get(outcome, "fails")
    what = f"a {LANG.get(lang, lang)} {MODEL.get(model, model)} program"
    head = f"{label} refuses {what}" if outcome == "rejected" and not link else f"{label} {verb} on {what}"
    return head + (f" with {_join([_phrase(k) for k in keys])}" if keys else "")


def name(family: str, outcome: str, keys: list[str]) -> str:
    words = [re.sub(r"[^a-z0-9]+", "-", k.partition(":")[2].lower()).strip("-") for k in keys[:3]]
    return "-".join([family, *words, SLUG.get(outcome, outcome)])


def rule(keys: list[str], model: str, outcome: str) -> str:
    """What the specification requires, and the cited Semantics of each key construct."""
    from offload.engine import fuzz_cites as FC
    kind = "compile" if outcome in ("rejected", "ice") else ("wrong" if outcome in ("wrong_answer", "fell_back_to_host")
                                                             else "abort")
    cites = [FC.text(c) for k in keys for c in FC.cites(k, model)]
    return REQUIRES[kind] + (": " + "; ".join(cites) if cites else "")


def site_summary(label: str, outcome: str, keys: list[str], lang: str, model: str, link: bool = False) -> str:
    return title(label, outcome, lang, model, keys, link) + "."


SOURCE = {"elision": "the sequential elision", "metamorphic": "the metamorphic runs", "model": "the program's own value",
          "derivation": "a derivation"}
NUMBER = {1: "one", 2: "two", 3: "three", 4: "four"}


def expected_text(res: dict) -> str:
    """The expected line from the confirmer's result (its expected value and sources)."""
    e = res.get("expected") or {}
    src = [SOURCE.get(s, s) for s in e.get("sources") or []]
    value = e.get("value") or ""
    own = " the program checks its own result;" if value.startswith("check=") else ""
    return (f"{value}:{own} {e.get('status', 'provisional')} by {NUMBER.get(len(src), len(src))} independent "
            f"sources ({', '.join(src)})").replace(":  ", ": ")


def legality_text(res: dict) -> str:
    """The legality line: what the rules engine and the confirmer's witnesses recorded (the verdict
    itself is computed: tools/review/review.py mechanical)."""
    runs = sorted({w.split("/")[0] for w in res.get("witnesses") or [] if "/" in w})
    return ("the rules engine accepts it (offload.engine.prerun.rules_witness); "
            + (f"{', '.join(runs)} run it correctly in the confirmer's runs (tools/confirm.py case); " if runs else "")
            + "the legality verdict is computed (tools/review/review.py mechanical)")


def site_title(family_label: str, outcome: str, keys: list[str]) -> str:
    names = [k.partition(":")[2] for k in keys[:3]]
    return f"{family_label}: {SLUG.get(outcome, outcome).replace('-', ' ')}" + (f" with {_join(names)}" if names else "")


def fill(path, *, title: str, expected: str | None, rule: str, legality: str, site_title: str,
         site_summary: str) -> None:
    """Write the generated words into a new_finding draft: its title line and the expected, rule and
    legality fields (each with its continuation lines), and the site title and summary; a field left
    TODO(human) and one filled before are replaced alike; a field given as None keeps what the rows
    gave it (new_finding writes the expected line from a passing row). Every line is wrapped to 132
    columns."""
    import textwrap
    from pathlib import Path
    from offload.engine import finding_header as H
    path = Path(path)
    lead = "//" if path.suffix == ".c" else "!"
    fields = {"expected": expected, "rule": rule, "legality": legality}
    lines = path.read_text().splitlines()
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        body = ln[len(lead):].lstrip() if ln.startswith(lead) else None
        key = next((k for k in fields if body is not None and body.startswith(f"- {k}:")
                    and (fields[k] is not None or "TODO(human)" in body)), None)
        if body is not None and body.startswith("# Finding"):
            head = body.split(":", 1)[0] + ": "
            wrapped = textwrap.wrap(head + title, 132 - len(lead) - 1, subsequent_indent="  ",
                                    break_long_words=False, break_on_hyphens=False)
            out += [f"{lead} {x}" for x in wrapped]
            i += 1
            while i < len(lines) and lines[i].startswith(f"{lead}   "):      # the old title's wrap
                i += 1
            continue
        if key and fields[key] is None:
            raise ValueError(f"{path}: {key} is TODO(human) and no text was given for it")
        if key:
            out += H.bullet(key, fields[key], lead)
            i += 1
            while i < len(lines) and lines[i].startswith(f"{lead}   "):
                i += 1
            continue
        if body is not None and body.startswith("title:") and (i + 1 < len(lines) and "summary:" in lines[i + 1]
                                                               or "TODO(human)" in body):
            out.append(f"{lead} title: {site_title}")
        elif body is not None and body.startswith("summary:"):
            # a site field continues on "+ " lines (offload.engine.site.header)
            wrapped = textwrap.wrap(f"summary: {site_summary}", 132 - len(lead) - 1, break_long_words=False,
                                    break_on_hyphens=False)
            out += [f"{lead} {wrapped[0]}"] + [f"{lead} + {x}" for x in
                                               textwrap.wrap(" ".join(wrapped[1:]), 132 - len(lead) - 3,
                                                             break_long_words=False, break_on_hyphens=False)]
            while i + 1 < len(lines) and lines[i + 1].startswith(f"{lead} + "):
                i += 1
        else:
            out.append(ln)
        i += 1
    path.write_text("\n".join(out) + "\n")
