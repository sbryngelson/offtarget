"""The OpenMP Examples (github.com/OpenMP/Examples, cloned to
corpus/omp_examples) as harvest programs.

An example is a candidate when its tags say ``@@operation: run`` and
``@@expect: success`` and it uses a device construct or device routine
(``selected``). Its expected result is what the example documents (an
``//OUTPUT:`` comment, a "prints" or "Outputs:" note, its own PASSED or
Failed lines), written as CHECK lines per example in
catalog/harvest2_examples.yaml, or its exit status when it checks itself.
An entry with ``skip`` records why it is not converted. offload.engine.harvest.convert
renames main and appends the self-check (``filecheck`` or ``exit_status``).

The examples carry the OpenMP ARB notice (omp_copyright.txt), a BSD-style
license that requires keeping the copyright notice and disclaimer."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from offload.engine.harvest import checks as K
from offload.engine.harvest import convert as HC
from offload.engine.harvest import filters as HF

LICENSE = ("OpenMP ARB Examples notice (BSD-style: redistribution with or "
           "without modification permitted, the copyright notice and "
           "disclaimer retained): Copyright (c) 1997-2025 OpenMP "
           "Architecture Review Board")
URL = "https://github.com/OpenMP/Examples/blob/{commit}/{path}"

_TAG = re.compile(r"@@(\w+):\s*(.*?)\s*$")


def tags(text: str) -> dict:
    out = {}
    for line in text.splitlines()[:12]:
        m = _TAG.search(line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def selected(text: str) -> bool:
    t = tags(text)
    if t.get("operation") != "run" or t.get("expect") != "success":
        return False
    lang = "c" if t.get("type", "").startswith("C") else "f90"
    code = HF._strip_comments(text, lang)
    return HF._offload(code, lang, "omp")


def program_id(path: str) -> str:
    name = Path(path).name
    stem, ext = name.rsplit(".", 1)
    return ("h2-ompex-" + re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower()
            + "-" + ext.lower())


def convert(path: str, text: str, entry: dict, commit: str,
            incs: list | None = None) -> dict:
    """The harvest program of a selected example and its catalog entry."""
    lang = "c" if path.endswith(".c") else "f90"
    t = tags(text)
    checks = entry.get("checks") or []
    cs = K.parse_checks("\n".join("// " + c for c in checks), ("CHECK",)) \
        if checks else []
    v = {"flags": [], "prefixes": ["CHECK"] if cs else []}
    if lang == "c":
        src, edits = HC.convert_c(text, cs, v)
    else:
        src, edits = HC.convert_f(text, cs, v)
    flags = []
    m = re.search(r"omp_(\d)\.(\d)", t.get("version", ""))
    if m:
        flags.append(f"-fopenmp-version={m.group(1)}{m.group(2)}")
    version, gerr = HC.spec_version(text, lang, flags, "omp")
    oracle = "filecheck" if cs else "exit_status"
    modes = entry.get("modes") or ["copy", "unified"]
    url = URL.format(commit=commit[:12], path=path)
    head = [
        "Harvested example (tools/campaigns/harvest2.py examples; do not edit)",
        f"source: {url}",
        f"license: {LICENSE}",
        f"original sha256: {hashlib.sha256(text.encode()).hexdigest()}",
    ]
    if incs:
        head.append("inlined: " + ", ".join(i for i in incs if i))
    head += [
        f"tags: version {t.get('version', '?')}; operation run; expect success",
        f"modes: {', '.join(modes)}",
        f"spec version: OpenMP {version // 10}.{version % 10} (the grammar "
        "reads every directive at it; at least the example's @@version)",
        "expected: exit status 0" + (
            f" and the output matches {len(cs)} CHECK lines from the "
            "example's documented output (catalog/harvest2_examples.yaml)"
            if cs else " (the example's own check: a nonzero exit or STOP "
            "on a wrong result)"),
        "self-check: RESULT ran_on_host=<0|1> check=<pass|fail>",
        "edits: " + "; ".join(edits + ["self-check appended"]),
    ]
    if lang == "c":
        head = ["/*"] + [" * " + ln.replace("*/", "* /") for ln in head] + \
            [" */"]
        pre = HC.CR.PRELUDE
        src = pre + "\n".join(head) + "\n" + src[len(pre):]
    else:
        src = "\n".join("! " + ln for ln in head) + "\n" + src
    return {"id": program_id(path), "record": f"ompex/{path}", "lang": lang,
            "model": "omp", "version": version, "source": src,
            "oracle": oracle, "checks": len(cs),
            "prefixes": ["CHECK"] if cs else [], "modes": modes,
            "edits": edits, "grammar_errors": gerr, "url": url,
            "license": LICENSE, "project": "OpenMP/Examples",
            "suite": path.split("/")[0], "commit": commit, "gpl": False,
            "original_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "source_kind": "examples"}
