"""Programs from training material, example collections and applications,
made self-checking by recorded edits (catalog/harvest2_hand.yaml;
``tools/campaigns/harvest2.py hand``).

An entry names a source file at a pinned commit and lists its edits. Each
edit is an exact text replacement (``old`` must occur exactly once) with a
reason (``why``). The edits add a self-check (a host recomputation or the
source's documented values, compared with a stated tolerance; a wrong result
exits nonzero) and only what a standalone legal program needs besides (a
missing #include, a kernel driver, a smaller problem size).
offload.engine.harvest.convert then renames main and appends the self-check
(OpenACC uses the host probe of offload.engine.harvest2.gomp).

The oracle is ``exit_status``, or ``filecheck`` with CHECK lines
(``checks``). An entry with no check and no ``self_checking: true`` is refused."""
from __future__ import annotations

import hashlib
import re

from offload.engine.harvest import checks as K
from offload.engine.harvest import convert as HC
from offload.engine.harvest2 import gomp as G


class EditError(ValueError):
    """An edit that does not apply, or an entry without a self-check."""


def apply_edits(text: str, edits: list[dict]) -> tuple[str, list[str]]:
    notes = []
    for e in edits or []:
        n = text.count(e["old"])
        want = e.get("count", 1)
        if n != want:
            raise EditError(f"edit {e['why']!r}: the old text occurs {n} "
                            f"times, not {want}")
        text = text.replace(e["old"], e["new"])
        notes.append(e["why"])
    return text, notes


def lang_of(path: str) -> str:
    return "c" if path.endswith(".c") else "f90"


def convert(e: dict, text: str, appended: dict | None = None,
            root=None) -> dict:
    """``appended``: path -> text of the entry's ``append`` and ``prepend``
    files (the other translation units of a multi-file example, appended
    in order, or put first: a Fortran module before its use)."""
    lang = lang_of(e["path"])
    inlined: list = []
    if e.get("inline"):
        from pathlib import Path
        skip = tuple(e.get("inline_skip") or ())
        text, inlined = G.inline_includes(text, Path(root) / e["path"],
                                          skip=skip)
        appended = dict(appended or {})
        for q in (e.get("append") or []) + (e.get("prepend") or []):
            appended[q], more = G.inline_includes(appended[q],
                                                  Path(root) / q, skip=skip)
            inlined += more
        if None in inlined:
            raise EditError(f"{e['id']}: a local include is missing")
    for path in e.get("append") or []:
        mark = (f"/* Appended {path} */" if lang == "c" else
                f"! Appended {path}")
        text = text.rstrip("\n") + f"\n{mark}\n" + (appended or {})[path]
    for path in reversed(e.get("prepend") or []):
        mark = (f"/* Prepended {path} */" if lang == "c" else
                f"! Prepended {path}")
        text = f"{mark}\n" + (appended or {})[path].rstrip("\n") + \
            f"\n{mark.replace('prepended', 'end of')}\n" + text
    crlf = "\r\n" in text
    if crlf:
        text = text.replace("\r\n", "\n")
    if e.get("detab"):
        text = text.expandtabs(8)
    body, notes = apply_edits(text, e.get("edits") or [])
    if crlf:
        notes.insert(0, "CRLF line ends as LF")
    if inlined:
        notes.insert(0, "local includes inlined: " +
                     ", ".join(sorted(set(i for i in inlined if i))))
    if e.get("detab"):
        notes.insert(0, "tabs replaced by spaces (a tab is not in the Fortran "
                     "character set)")
    if e.get("append"):
        notes.insert(0, "the example's other files appended: " +
                     ", ".join(e["append"]))
    if e.get("prepend"):
        notes.insert(0, "the example's other files put first (modules "
                     "before their use): " + ", ".join(e["prepend"]))
    checks = e.get("checks") or []
    if not notes and not checks and not e.get("self_checking"):
        raise EditError(f"{e['id']}: no self-check (edits, checks or "
                        "self_checking)")
    model = e.get("model") or G.model_of(body)
    if model not in ("omp", "acc"):
        raise EditError(f"{e['id']}: model {model}")
    cs = K.parse_checks("\n".join("// " + c for c in checks), ("CHECK",)) \
        if checks else []
    defines = e.get("defines") or []
    v = {"flags": defines, "prefixes": ["CHECK"] if cs else []}
    if lang == "c":
        src, cedits = HC.convert_c(body, cs, v)
    else:
        src, cedits = HC.convert_f(body, cs, v)
    if model == "acc":
        src = G.acc_runtime(src, lang)
        cedits.append("the self-check's host probe is OpenACC")
    version, gerr = HC.spec_version(body, lang, [], model)
    oracle = "filecheck" if cs else "exit_status"
    modes = e.get("modes") or ["copy", "unified"]
    orig = hashlib.sha256(text.encode()).hexdigest()
    ver = ("OpenACC 3.4" if model == "acc" else
           f"OpenMP {version // 10}.{version % 10}")
    head = [
        "Harvested program (tools/campaigns/harvest2.py hand; do not edit)",
        f"source: {e['url']}",
        f"license: {e['license']}",
        f"original sha256: {orig}",
        f"modes: {', '.join(modes)}"
        + (f"; defines: {' '.join(defines)}" if defines else ""),
        f"spec version: {ver} (the grammar reads every directive at it)",
        f"expected: exit status 0; {e['why']}" + (
            f"; the output matches {len(cs)} CHECK lines" if cs else ""),
        "self-check: RESULT ran_on_host=<0|1> check=<pass|fail>",
        "edits: " + "; ".join(notes + cedits + ["self-check appended"]),
    ]
    if lang == "c":
        head = ["/*"] + [" * " + ln.replace("*/", "* /") for ln in head] + \
            [" */"]
        pre = HC.CR.PRELUDE
        src = pre + "\n".join(head) + "\n" + src[len(pre):]
    else:
        src = "\n".join("! " + ln for ln in head) + "\n" + src
    return {"id": e["id"], "record": f"{e['repo']}/{e['path']}", "lang": lang,
            "model": model, "version": version, "source": src,
            "oracle": oracle, "checks": len(cs),
            "prefixes": ["CHECK"] if cs else [], "modes": modes,
            "edits": notes + cedits, "grammar_errors": gerr, "url": e["url"],
            "license": e["license"], "project": e["repo"],
            "suite": e.get("suite", e["repo"]), "commit": e["commit"],
            "gpl": bool(re.match(r"(?:L|A)?GPL", e["license"])),
            "copyleft": bool(re.match(r"(?:(?:L|A)?GPL|CC-BY-SA)",
                                      e["license"])),
            "original_sha256": orig,
            "source_kind": e.get("kind", "training")}
