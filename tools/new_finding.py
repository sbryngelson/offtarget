#!/usr/bin/env python3
"""Draft a finding file from recorded rows (data/findings/AUTHORING.md).

    python3 -I tools/new_finding.py PROGRAM --campaign NAME --rows FILE... \\
        [--control FILE...] [--id PROGRAM_ID...] [--programs ID...] [--name STEM] [--dir DIR] \\
        [--write [--readme-section HEADING] | --proposal]

PROGRAM is the reduction; FILE... are the rows holding its runs and its controls' (matched by
program text, or by --id). The factual lines come from those rows; the title, the rule, the
legality statement and the site text stay TODO(human) (tools/repo/check_findings.py fails on them).
Without --write the draft and its entries are printed. --write puts the finding, its index.yaml
entry and (with --readme-section) its LOG.md row in place. --proposal (an outside contribution)
writes the finding, its controls and its rows to data/findings/proposed/ instead."""
from __future__ import annotations

import argparse
import glob
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import finding_header as H  # noqa: E402
from offload.engine import finding_rows as R  # noqa: E402
from offload.engine.site import header as SH  # noqa: E402
from offload.engine.site import matrix as M  # noqa: E402
from offload.engine.site import scrub as S  # noqa: E402

TODO_TITLE = f"{H.MARK} one-sentence title"
TODO_RULE = f"{H.MARK} the specification requirement, cited with version, section, page and lines"
TODO_LEGAL = f"{H.MARK} the legality statement and its witnesses"
TODO_SITE_TITLE = f"{H.MARK} the issue's name in a few words"
TODO_SITE_SUMMARY = f"{H.MARK} one sentence for the site"
RUNTIME = ("wrong_answer", "crash", "run_error", "timeout", "fell_back_to_host")
KIND = {"ice": "incorrect (compiler failure)", "rejected": "not supported",
        "wrong_answer": "incorrect", "crash": "incorrect (run-time error)",
        "run_error": "incorrect (run-time error)"}
MODE_ORDER = ("unified", "copy", "managed")
_DIAG = re.compile(r"error|-[SF]-|fatal|internal|undefined|abort|PLEASE submit", re.I)


class NoRows(Exception):
    """The rows hold no failing run of the program."""


@dataclass
class Draft:
    rel: str
    text: str
    index_entry: str
    readme_row: str
    notes: list = field(default_factory=list)
    controls: list = field(default_factory=list)      # (source path, name) of the claimed controls


def label(tc: str) -> str:
    from offload.engine.site.data import _version_label
    fam, ver, _ = M.VERSIONS[tc]
    return _version_label(fam, ver)


def _tc_phrase(tcs) -> str:
    return ", ".join(f"{t} ({label(t)})" for t in tcs)


def body_of(text: str) -> str:
    """The program without its leading comment block (a reduction's own header) and any
    site: block."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and H._LEAD.match(lines[i]) and not lines[i].lstrip().startswith("!$"):
        i += 1
    return SH.strip("\n".join(lines[i:]).lstrip("\n"))


def _values(obs_text: str) -> tuple[list, str]:
    """(value lines, check word) of a run's output: `tot= 16` lines and check=pass|fail."""
    body = obs_text.split("\n", 1)[1] if "\n" in obs_text else ""
    vals = [x.strip() for x in body.splitlines() if "=" in x and not x.startswith("RESULT")]
    chk = re.search(r"check=(pass|fail)", body)
    return vals, chk.group(1) if chk else ""


# a compiler's own crash banner, most telling first
_PREFER = R.ICE_BANNERS


def _observed(o: R.Obs) -> str:
    text = S.scrub(o.obs)
    stage = text.split(" ", 1)[0].split("\n", 1)[0]
    body = text.split("\n", 1)[1] if "\n" in text else ""
    lines = [x.strip() for x in body.splitlines() if x.strip()]
    if stage == "COMPILE_FAIL":
        pick = next((x for rx in _PREFER for x in lines if rx.search(x)), None) or \
            next((x for x in lines if _DIAG.search(x)), lines[0] if lines else "")
        return f"`{pick[:150]}`"
    sig = re.search(r"signal=(\w+)", text.split("\n", 1)[0])
    vals, chk = _values(text)
    if stage == "RUN_OK" and vals:
        return "`" + "`, `".join(vals[:3]) + "`" + (f" with `check={chk}`" if chk else "")
    first = (lines[0] if lines else stage)[:150]
    return f"`{first}`" + (f" (killed by signal {sig.group(1)})" if sig else "")


def _expected(passing: list) -> str:
    sets = {tuple(_values(o.obs)[0]) for o in passing}
    if len(sets) != 1:
        return f"{H.MARK} the compilers that pass print different values: " + \
            "; ".join(sorted(" ".join(s) for s in sets))
    vals = next(iter(sets))
    chk = next((c for c in (_values(o.obs)[1] for o in passing) if c), "")
    if not vals:
        res = next((x.strip() for o in passing for x in o.obs.splitlines() if x.startswith("RESULT")), "")
        return "compiles and runs to completion" + (f", printing `{S.scrub(res)[:120]}`" if res else "")
    return "compiles and prints " + "`" + "`, `".join(vals) + "`" + (f" with `check={chk}`" if chk else "")


def _opt(cmds) -> str:
    c = Counter(m.group(0) for x in cmds for m in [re.search(r"-O[0-3s]\b", x)] if m)
    return c.most_common(1)[0][0] if c else ""


def _flags(cmd: str) -> str:
    """A recorded command or flag string without the source file, `-o repro` and library paths;
    the compiler's path becomes its name."""
    toks, out, skip = S.scrub(cmd).split(), [], False
    for i, t in enumerate(toks):
        if skip:
            skip = False
        elif t == "-o":
            skip = True
        elif re.search(r"\.(?:c|f90|F90|f)$", t) or t.startswith("-L"):
            continue
        else:
            out.append(Path(t).name if i == 0 and "/" in t else t)
    return " ".join(out)


def _build(failing, lang: str) -> str:
    """The compiler and flags of the failing rows (the compiler's name from the toolchain's recipe
    when the row records flags only)."""
    from offload.engine.toolchains import TOOLCHAINS
    by = defaultdict(list)
    for tc in M.TOOLCHAINS:
        os_ = [o for o in failing if o.tc == tc and o.cmd]
        if os_ and tc in TOOLCHAINS:
            t = TOOLCHAINS[tc]
            cmd = Counter(_flags(o.cmd) for o in os_).most_common(1)[0][0]
            if not cmd.split()[0:1] or cmd.startswith("-"):
                cmd = Path((t.cc if lang == "c" else t.fc).split()[0]).name + " " + cmd
            by[cmd].append(tc)
    if len(by) == 1:
        return next(iter(by))
    return "; ".join(f"{cmd} ({', '.join(tcs)})" for cmd, tcs in by.items()) or \
        f"{H.MARK} the build line (the rows record none)"


def _primary(failing, case, primary, ctl_fail=frozenset()) -> list:
    """The toolchains the finding is about: those named (--primary, or the check case's
    `affected`), else the first family that fails; of them, those failing with the signature most
    of them share."""
    order = [t for t in M.TOOLCHAINS if any(o.tc == t for o in failing)]
    aff = (case or {}).get("affected", [])
    from offload.engine.toolchains import REGRESSION_TOOLCHAINS
    heads = [a.split("@")[0] for a in aff]
    want = list(primary) or heads + [r for r, h in REGRESSION_TOOLCHAINS.items() if h in heads]
    pri = [t for t in order if t in want] or [t for t in order if M.VERSIONS[t][0] == M.VERSIONS[order[0]][0]]
    from offload.engine import finding_claims as C
    sigs = Counter(C._sig(o) for o in failing if o.tc in pri)
    top = sigs.most_common(1)[0][0]
    # every toolchain, of any family, that fails with the top signature is primary: a finding never
    # says a compiler fails "another way" when its signature is the top one; except a toolchain
    # outside the named ones that fails a control with the same signature (its failure is not shown to be this one)
    base = {t for t in pri if any(o.tc == t and C._sig(o) == top for o in failing)}
    return [t for t in order if t in base or (not any((t, top) == c_ for c_ in ctl_fail) and any(o.tc == t and C._sig(o) == top for o in failing))]


def _node_ok(os_) -> tuple[bool, bool | None]:
    """(all four environments fail identically, (c) differs from (a) or None when unknown)."""
    by = {e: [o for o in os_ if o.env == e] for e in "abcd"}
    full = all(by[e] for e in "abcd") and len({o.sig for o in os_}) == 1
    a = {_nk(o.node) for o in by["a"] if o.node}
    c = {_nk(o.node) for o in by["c"] if o.node}
    return full, (bool(c - a) if a and c else None)


def generate(program, campaign: str, rows, controls=(), name: str | None = None, root: Path = ROOT,
             dir: str | None = None, programs=(), ids=(), case: dict | None = None, gate=(),
             primary=(), same: dict | None = None) -> Draft:
    """`same`: toolchain -> why its failing rows, which carry another signature, are this finding's
    failure (a judgement: another platform's runtime reporting the same defect differently); they
    are listed with the failing toolchains and a `counted as this failure` bullet states the reason."""
    program, root = Path(program), Path(root)
    ext = program.suffix
    lang = "c" if ext == ".c" else "f90"
    name = name or program.stem
    dir = dir or campaign
    rel = f"{dir}/{name}{ext}"
    body = body_of(program.read_text())
    fp = R.fingerprint(body, lang)
    files = []
    for r in list(rows) + list(gate):
        files += [Path(x) for x in sorted(glob.glob(str(r)))] or [Path(r)]
    files = list(dict.fromkeys(files))
    obs = []
    for f in files:
        obs += R._file_obs(f, root)
    ids = set(ids) | {program.stem}
    repro = [o for o in obs if o.variant == "repro" and (o.fp == fp or o.pid in ids)]
    if case is not None:
        # the site rows come first, as the claim checker reads them (R.evidence_for)
        repro = R.site_obs(case, M._rows()) + repro
    failing_all = [o for o in repro if o.failed]
    if not failing_all:
        raise NoRows(f"{program}: no failing row of the program in {len(files)} row file(s)")
    notes: list = []
    lang_ctl_fail = set()
    for c in controls:
        c = Path(c)
        cfp = R.fingerprint(c.read_text(), lang)
        from offload.engine import finding_claims as C1
        lang_ctl_fail |= {(o.tc, C1._sig(o)) for o in obs if (o.fp == cfp or o.pid == c.stem) and o.failed}
    pri = _primary(failing_all, case, primary, lang_ctl_fail)
    counted = [t for t in M.TOOLCHAINS if t in (same or {}) and t not in pri and any(o.tc == t for o in failing_all)]
    pri = [t for t in M.TOOLCHAINS if t in pri or t in counted]
    from offload.engine import finding_claims as C
    sig_of = C._sig                                                         # the claim checker's own
    failing = [o for o in failing_all if o.tc in pri]
    tcs = [t for t in M.TOOLCHAINS if t in pri]
    modes = [m for m in MODE_ORDER if any(o.mode == m for o in failing)]
    opt = _opt(o.cmd for o in failing)
    fail_line = _tc_phrase(tcs) + "; modes: " + ", ".join(modes) + (f"; {opt}" if opt else "")
    cls = Counter(o.cls for o in failing).most_common(1)[0][0]
    cells = defaultdict(list)
    for o in failing:
        cells[(o.tc, o.target)].append(o)
    # the signature most cells show in their first row (the claim checker counts the same way)
    top_sig = Counter(sig_of(os_[0]) for os_ in cells.values()).most_common(1)[0][0]
    top_n = sum(1 for os_ in cells.values() if sig_of(os_[0]) == top_sig)
    rep = next(os_[0] for os_ in cells.values() if sig_of(os_[0]) == top_sig)
    observed = _observed(rep) + f"; identical signature on {top_n} of {len(cells)} failing cells"
    if top_n < len(cells):
        observed += " (" + "; ".join(
            f"{tc} on {tg}: {_observed(os_[0])}" for (tc, tg), os_ in sorted(cells.items())
            if sig_of(os_[0]) != top_sig) + " differ)"
    passing = [o for o in repro if o.passed]
    expected = _expected(passing) if passing else \
        f"{H.MARK} no row of the program passes; state the expected output and its source"

    site_label = f"site rows, check case {case['id']}" if case else ""

    def where(os_):
        paths = sorted({o.path for o in os_ if o.path})
        rel_ = [str(Path(p).relative_to(root)) if root in Path(p).parents else p for p in paths]
        return ", ".join(([("rows " + ", ".join(rel_))] if rel_ else []) +
                         ([site_label] if any(o.src == "site-rows" for o in os_) else []))

    # the gate: the reduction's own runs in a-d, and the campaign programs'
    gate_bits = []
    if any(o.env for o in failing):
        from offload.engine import finding_claims as C0
        nodes = [_node_ok(os_) for os_ in cells.values()]
        c_text = "(c) on another node or GPU than (a)" if nodes and all(d is True for _, d in nodes) \
            else "(c) node not recorded for every cell"
        # the count the claim checker recomputes (same function, same rows)
        ok, total = C0._gate_cells([o for o in repro if o.tc in tcs]) or (0, len(cells))
        red_bit = (f"{ok} of {total} cells reproduce in all four environments (a-d; {c_text}; "
                   f"{where([o for os_ in cells.values() for o in os_])})")
        if case is None:             # with a check case the site rows carry the gate; counts of both sources differ by mode
            gate_bits.append(red_bit)
    prog_ids = [p for p in programs if p]
    if prog_ids:
        from offload.engine import finding_claims as C
        gc = C.gate_cells(obs, set(prog_ids), tuple(tcs), C._modes("modes: " + ", ".join(modes)))
        if gc:
            conf = sum(1 for v in gc.values() if v[0])
            # the gate reruns and the stored runs the confirmation is judged against
            gobs = [o for o in obs if o.pid in prog_ids and o.tc in tcs and o.src == "campaign-rows"
                    and (o.env or o.variant == "repro")]
            gate_bits.append(f"campaign gate of the programs below: {len(gc)} cells, {conf} confirmed in the "
                             f"four environments (a-d; (c) on another node or GPU; {where(gobs)})")
        else:
            notes.append("no gate rows (environments a-d) for the programs " + ", ".join(prog_ids))
    if not gate_bits:
        notes.append("the rows hold no gate environments (a-d) for this program: run the gate "
                     "(tools/campaigns/gate.py) and give its rows")
    # the campaign gate's count first: the claim checker reads the first "N cells" of the line
    gate_line = "; ".join(sorted(gate_bits, key=lambda b: 0 if b.startswith("campaign gate") else 1))

    # other families: those with a passing row; those failing another way
    ok_tcs = [t for t in M.TOOLCHAINS if t not in pri and any(o.tc == t for o in passing)]
    other_bits = []
    odd = [t for t in M.TOOLCHAINS if t not in pri and any(o.tc == t for o in failing_all)]
    both = set(ok_tcs) & set(odd)

    def in_modes(ts, os_):
        # a toolchain that passes in one memory mode and fails in another says which
        ms = sorted({o.mode for o in os_ if o.tc in both and o.mode})
        return f" in {', '.join(ms)} mode" if ms and any(t in both for t in ts) else ""
    if ok_tcs:
        good = [o for o in passing if o.tc in ok_tcs]
        other_bits.append(_tc_phrase(ok_tcs) + " run the file correctly" + in_modes(ok_tcs, good) + " ("
                          + where(good) + ")")
    same_but_ctl = [t for t in odd if (t, top_sig) in lang_ctl_fail and any(C._sig(o) == top_sig for o in failing_all if o.tc == t)]
    odd = [t for t in odd if t not in same_but_ctl]
    if same_but_ctl:
        other_bits.append(_tc_phrase(same_but_ctl) + " fail the controls too, so a failure with this signature is "
                          "not claimed to be this one")
    if odd:
        o0 = next(o for o in failing_all if o.tc == odd[0])
        bad = [o for o in failing_all if o.tc in odd]
        other_bits.append(_tc_phrase(odd) + " fail it another way" + in_modes(odd, bad) + ", e.g. "
                          + _observed(o0))
    other = "; ".join(other_bits)

    # controls: claimed only where a row passes
    claimed, ctl_lines, goods = [], [], {}
    for c in controls:
        c = Path(c)
        cfp = R.fingerprint(c.read_text(), lang)
        cobs = [o for o in obs if o.fp == cfp or o.pid == c.stem]
        good = [t for t in tcs if any(o.tc == t and o.passed for o in cobs)]
        for t in (t for t in tcs if t not in good):
            bad = any(o.tc == t and o.failed for o in cobs)
            notes.append(f"control {c.name}: " + ("its recorded row fails" if bad else "no recorded row")
                         + f" on {t} ({label(t)}): not claimed")
        if good:
            claimed.append((c, c.name))
            goods[c.name] = good
            ctl_lines.append(f"controls/{c.name} (one change from this file; correct on {_tc_phrase(good)}; "
                             f"{where([o for o in cobs if o.passed])})")
    control = "; ".join(ctl_lines)

    lead = "//" if lang == "c" else "!"
    width = 132
    out = [f"{lead} # Finding ({campaign}): {TODO_TITLE}", lead]
    out += H.bullet("toolchains and modes that fail", fail_line, lead, width)
    out += H.bullet("build", _build(failing, lang), lead, width)
    out += H.bullet("failure", cls + (" (check=fail)" if cls == "wrong_answer" else ""), lead, width)
    out += H.bullet("observed", observed, lead, width)
    if counted:
        out += H.bullet("counted as this failure", "; ".join(f"{_tc_phrase([t])}: {same[t]}" for t in counted), lead, width)
    out += H.bullet("expected", expected, lead, width)
    out += H.bullet("rule", TODO_RULE, lead, width)
    if control:
        out += H.bullet("same-compiler control", control, lead, width)
    if other:
        out += H.bullet("other families", other, lead, width)
    if gate_line:
        out += H.bullet("gate and confirmer", gate_line, lead, width)
    if prog_ids:
        out += H.bullet(f"programs ({len(prog_ids)})", ", ".join(prog_ids), lead, width)
    out += H.bullet("legality", TODO_LEGAL, lead, width)
    text = "\n".join(out) + "\n" + body.rstrip("\n") + "\n"
    sh = SH.SiteHeader(title=TODO_SITE_TITLE, summary=TODO_SITE_SUMMARY, controls=tuple(
        (f"{dir}/controls/{n}", "one change from the finding; correct on " + ", ".join(goods[n]))
        for _, n in claimed))
    text += "\n" + "\n".join(SH.render(sh, lang)) + "\n"

    from offload.engine.toolchains import TOOLCHAINS
    arches = list(dict.fromkeys(TOOLCHAINS[t].arch for t in tcs if t in TOOLCHAINS)) or ["gfx942"]
    msg = re.sub(r"`", "", _observed(rep).split("`")[1] if _observed(rep).startswith("`") else "")[:100]
    msg = re.sub(r"\b\d+:\d+\b|\bline \d+\b", "", msg).strip()
    try:
        re.compile(msg)
    except re.error:
        msg = re.escape(msg)
    entry = {"file": rel, "toolchains": tcs, "lang": lang, "outcome": cls}
    if msg and cls in ("ice", "rejected", "crash", "run_error"):
        entry["message"] = msg
    entry.update(modes=modes, arch=arches)
    if prog_ids:
        entry["programs"] = prog_ids
    index_entry = "\n".join("    " + ln if i else "  - " + ln for i, ln in enumerate(
        yaml.safe_dump(entry, sort_keys=False, default_flow_style=None, width=1000,
                       allow_unicode=True).splitlines()))
    readme_row = f"| `{rel}` | {KIND.get(cls, 'incorrect')} | {H.MARK} one sentence ({', '.join(tcs)}) |"
    return Draft(rel, text, index_entry, readme_row, notes, claimed)


def _nk(node: str) -> str:
    from offload.engine.gate import node_key
    return node_key(node)


def write(d: Draft, root: Path = ROOT, readme_section: str | None = None, proposal: bool = False,
          rows: list | None = None) -> list[str]:
    """Put the finding, its claimed controls and the entries in place; the paths written. A
    proposal (an outside contribution) goes to data/findings/proposed/ with copies of its row files
    (NAME.rows.jsonl) and no index or log entry: nothing publishes it until a maintainer runs the
    gate, the site rows and the legality review and moves it in."""
    root = Path(root)
    fd = root / "data" / "findings"
    if proposal:
        dest = fd / "proposed" / Path(d.rel).name
        if dest.exists():
            raise SystemExit(f"new_finding: {dest} exists; refusing to overwrite a proposal")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(d.text)
        done = [str(dest)]
        if rows:
            r = dest.with_suffix(".rows.jsonl")
            r.write_text("".join(Path(x).read_text() for x in rows))
            done.append(str(r))
        for src, n in d.controls:
            (dest.parent / "controls").mkdir(exist_ok=True)
            (dest.parent / "controls" / n).write_text(Path(src).read_text())
            done.append(str(dest.parent / "controls" / n))
        return done
    dest = fd / d.rel
    if dest.exists():
        raise SystemExit(f"new_finding: {d.rel} exists; refusing to overwrite a finding")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(d.text)
    done = [str(dest)]
    for src, n in d.controls:
        cd = dest.parent / "controls"
        cd.mkdir(exist_ok=True)
        (cd / n).write_text(Path(src).read_text())
        done.append(str(cd / n))
    idx = fd / "index.yaml"
    if idx.is_file():
        t = idx.read_text()
        idx.write_text(t + ("" if t.endswith("\n") else "\n") + d.index_entry + "\n")
        done.append(str(idx))
    if readme_section and (fd / "LOG.md").is_file():
        lines = (fd / "LOG.md").read_text().splitlines()
        h = next((i for i, x in enumerate(lines) if x.startswith("## ") and readme_section in x), None)
        if h is None:
            raise SystemExit(f"new_finding: no LOG.md section matching {readme_section!r}")
        end = h + 1
        while end < len(lines) and not lines[end].startswith("## "):
            end += 1
        last = max((i for i in range(h, end) if lines[i].startswith("| `")), default=None)
        if last is None:
            raise SystemExit(f"new_finding: the LOG.md section {readme_section!r} has no table")
        lines.insert(last + 1, d.readme_row)
        (fd / "LOG.md").write_text("\n".join(lines) + "\n")
        done.append(str(fd / "LOG.md"))
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("program")
    ap.add_argument("--campaign", required=True)
    ap.add_argument("--rows", nargs="*", default=[], help="result row files (optional with --case)")
    ap.add_argument("--control", nargs="*", default=[])
    ap.add_argument("--id", nargs="*", default=[], help="row program ids of the reduction")
    ap.add_argument("--programs", nargs="*", default=[], help="campaign program ids it stands for")
    ap.add_argument("--gate", nargs="*", default=[], help="gate rerun files of the campaign programs")
    ap.add_argument("--primary", nargs="*", default=[], help="the toolchains the finding is about")
    ap.add_argument("--name")
    ap.add_argument("--dir")
    ap.add_argument("--case", help="a data/vendor/site check case id whose committed rows to add")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--proposal", action="store_true",
                    help="write to data/findings/proposed/ with the rows, no index entry (outside contributors)")
    ap.add_argument("--readme-section")
    a = ap.parse_args(argv)
    case = None
    if a.case:
        case = next((c for c in M._cases() if c["id"] == a.case), None)
        if case is None:
            print(f"new_finding: no check case {a.case!r}", file=sys.stderr)
            return 2
    try:
        d = generate(a.program, a.campaign, a.rows, a.control, a.name, ROOT, a.dir, a.programs,
                     a.id, case, a.gate, a.primary)
    except NoRows as e:
        print(f"new_finding: {e}", file=sys.stderr)
        return 1
    if a.proposal:
        for p in write(d, ROOT, proposal=True, rows=a.rows):
            print("wrote", p)
    elif a.write:
        for p in write(d, ROOT, a.readme_section):
            print("wrote", p)
        if not a.readme_section:
            print("LOG.md row (add it under its section, or pass --readme-section):\n" + d.readme_row)
    else:
        print(d.text)
        print("--- data/findings/index.yaml\n" + d.index_entry)
        print("--- data/findings/LOG.md\n" + d.readme_row)
    for n in d.notes:
        if a.proposal and n.startswith("the rows hold no gate environments"):
            n = "no gate rows: a maintainer runs the gate when the proposal is taken in"
        print("note:", n)
    print(f"{len(H.todos(d.text))} TODO(human) in the draft: tools/repo/check_findings.py fails until they are resolved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
