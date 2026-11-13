"""Finding drafts and their promotion.

A draft is a directory results/confirm/drafts/<case id>/ with
``finding.md`` (header: compilers and versions, arch, memory modes,
expected vs actual, the evidence table, the rule id, the ruling citations
or "citation needed"), ``program.<f90|c>`` (the minimized program when
there is one, else the case's program) and ``result.json``. Drafts never
go to findings by themselves: ``promote`` copies the program there
with the header as comments and appends an entry to
data/findings/index.yaml (an explicit step)."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DRAFTS = ROOT / "results" / "confirm" / "drafts"
FINDINGS = ROOT / "data" / "findings"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")[:120]


def _compiler(ev: list[dict], tc: str) -> str:
    from offload.engine.toolchains import TOOLCHAINS, compiler_version
    try:
        return compiler_version(TOOLCHAINS[tc]) or tc
    except Exception:
        return tc


# gfortran and gcc are never a legality witness (standing rule). The gate's base-language syntax check (gfortran -std=f2008
# or gcc -std=c11, without OpenMP) stays in result.json's checks, but a
# draft's legality line never names it as a checker.
_BASE_CHECKER = re.compile(r"\b(gfortran|gcc)\b")


def _checker_list(basis: str) -> tuple[list[str], str] | None:
    """The checkers of a "legal by the checkers (...)" basis and the text
    after its closing parenthesis, the list split at top-level commas (a
    checker name may contain parentheses); None for another basis."""
    head = "legal by the checkers ("
    if not basis.startswith(head):
        return None
    depth, cur, items = 0, "", []
    for i, ch in enumerate(basis[len(head):]):
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                items.append(cur)
                return ([x.strip() for x in items if x.strip()],
                        basis[len(head) + i + 1:])
            depth -= 1
        elif ch == "," and depth == 0:
            items.append(cur)
            cur = ""
            continue
        cur += ch
    return None


def legality_text(leg: dict) -> str:
    """The draft's legality line: the gate's status and basis without the
    base-language checkers. A "legal by the checkers (...)" basis keeps
    its other checkers; a basis that rests on gfortran or gcc is replaced
    by a pointer to the spec reading."""
    status = leg.get("status", "unknown")
    basis = leg.get("basis", "")
    parsed = _checker_list(basis)
    if parsed is not None:
        kept = [x for x in parsed[0] if not _BASE_CHECKER.search(x)]
        tail = parsed[1]
        if _BASE_CHECKER.search(tail):
            tail = ""
        basis = ("checked by " + ", ".join(kept) + tail
                 + "; the legality rests on the spec reading in the "
                 "finding")
    elif _BASE_CHECKER.search(basis):
        basis = ("the base-language syntax check rejects it (see "
                 "result.json); the legality needs a spec reading")
    return f"{status} ({basis})"


def render(result: dict, compiler_text: str | None = None) -> str:
    c = result["case"]
    p = c["program"]
    exp = result.get("expected") or {}
    rows = []
    for e in result.get("evidence", []):
        if not e.get("runs") and e.get("status") != "value":
            continue
        outs = ", ".join(sorted({r["outcome"] for r in e.get("runs", [])}))
        rows.append(f"| {e['collector']} | {e.get('toolchain', '')} | "
                    f"{e.get('arch', '')} | {e.get('mode', '')} | "
                    f"{e.get('variant', '')} | {outs} | "
                    f"{(e.get('value') or '')[:60]} | "
                    f"{e.get('provenance', {}).get('origin', '')} |")
    cites = result.get("citations") or ["citation needed"]
    lines = [
        f"# Draft finding: {p['ident']} on {c['toolchain']}",
        "",
        f"- compiler: {compiler_text or c['toolchain']}",
        f"- toolchain: {c['toolchain']}; arch: {c['arch']}; machine: "
        f"{c['machine']}; memory mode: {c['mode']}; opt: {c['opt']}",
        f"- program: {p['kind']} {p['ident']} ({p['lang']}, "
        f"version {p['version']}, sha256 {p['sha256'][:16]})",
        f"- expected: {exp.get('value')} ({exp.get('status')}; "
        f"{' + '.join(exp.get('sources', []))})",
        f"- actual: {c['outcome']} {c.get('value') or ''} "
        f"({c.get('reason', '')[:200]})",
        f"- verdict: {result['verdict']} by rule {result['rule']}: "
        f"{result['rationale']}",
        f"- reason: {result['reason']}",
        "- citations: " + "; ".join(cites),
        f"- legality: {legality_text(result['legality'])}",
        f"- witnesses: {', '.join(result.get('witnesses') or []) or 'none'}",
        "- withdrawn: " + (", ".join(f"{w['toolchain']} ({w['finding']})"
                                     for w in result.get("withdrawn", []))
                           or "none"),
        "",
        "## Evidence",
        "",
        "| collector | toolchain | arch | mode | variant | outcomes | value |"
        " origin |",
        "|---|---|---|---|---|---|---|---|",
        *rows,
        "",
        "## Actions",
        "",
        *[f"- {a}" for a in result.get("actions", [])],
    ]
    return "\n".join(lines) + "\n"


def write_draft(result: dict, base: Path | None = None) -> Path:
    c = result["case"]
    d = Path(base or DRAFTS) / _slug(c["case_id"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "finding.md").write_text(render(result))
    ext = "c" if c["program"]["lang"] == "c" else "f90"
    src = result.get("minimized") or result.get("source") or ""
    if not src:
        from offload.engine.confirm.ingest import Row  # noqa: F401
        src = result.get("program_text", "")
    (d / f"program.{ext}").write_text(src)
    (d / "result.json").write_text(json.dumps(result, indent=1,
                                              default=str))
    return d


def promote(draft: Path, name: str, findings: Path = FINDINGS,
            index: Path | None = None) -> Path:
    """Copy a draft's program to data/findings/<name> with the draft's
    header as comments and add an index entry."""
    draft = Path(draft)
    result = json.loads((draft / "result.json").read_text())
    c = result["case"]
    lang = c["program"]["lang"]
    ext = "c" if lang == "c" else "f90"
    if not name.endswith(f".{ext}"):
        name = f"{name}.{ext}"
    target = Path(findings) / name
    if target.exists():
        raise FileExistsError(target)
    lead = "//" if lang == "c" else "!"
    head = []
    for ln in (draft / "finding.md").read_text().split("## Evidence")[0] \
            .splitlines():
        ln = f"{lead} {ln}" if ln else lead
        if lang == "c":
            head.append(ln)
        else:
            from offload.engine.hdrwrap import wrap_line
            head.extend(wrap_line(ln))
    body = (draft / f"program.{ext}").read_text()
    if lang != "c":
        from offload.engine.hdrwrap import wrap_comments
        body = wrap_comments(body)
    target.write_text("\n".join(head) + "\n" + body)
    index = Path(index or Path(findings) / "index.yaml")
    exp = (result.get("expected") or {}).get("value") or ""
    entry = (f"  - file: {name}\n    toolchains: [{c['toolchain']}]\n"
             f"    lang: {lang}\n    outcome: {c['outcome']}\n"
             f"    modes: [{c['mode']}]\n    arch: [{c['arch']}]\n")
    if c["outcome"] in ("ice", "rejected", "crash"):
        msg = c.get("reason", "").split(":", 1)[-1].strip()[:80]
        entry += f"    message: {json.dumps(re.escape(msg))}\n"
    if exp:
        entry += f"    expected: {json.dumps(exp)}\n"
    with index.open("a") as f:
        f.write(entry)
    return target
