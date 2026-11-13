#!/usr/bin/env python3
"""Build the public offload-issue site.

    python3 -I tools/site/site_build.py OUT [--repo-url URL] [--source-branch BRANCH]

Writes OUT/data/ (offload.engine.site.data.build), then the pages: index.html (the observed
issues, interactive; issues.html forwards to it), issues/<id>.html, compilers/<tc>.html and compilers/index.html,
canuse.html (interactive), method.html, and static/. The issue, compiler and method
pages are plain HTML; only the issue list and can-I-use need JavaScript. `--repo-url`
adds links to the finding sources (off until the repository is public), into
`--source-branch` (default master; the workflow passes the repository's default branch).
"""
import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine.confirm.machines import load as _machines  # noqa: E402
from offload.engine.site.data import _order, fixed_order, page_name  # noqa: E402
from offload.engine.site.matrix import TARGETS, VERSIONS  # noqa: E402
from offload.engine.toolchains import registry as _registry  # noqa: E402

SITE = ROOT / "site"
# target -> its long name (catalog/machines.yaml modes.<mode>.target_name)
TG_NAME = {m.mode_table[mode]["target"]: m.mode_table[mode]["target_name"]
           for m in _machines().values() for mode in m.modes if m.mode_table[mode].get("target")}
# target -> its ISA code name (the machine's arch)
TG_ISA = {m.mode_table[mode]["target"]: m.arch
          for m in _machines().values() for mode in m.modes if m.mode_table[mode].get("target")}


def gpu_mode(t):
    """(GPU, memory mode) of a target, from its long name "MI300A (gfx942), copy (XNACK 0)"."""
    name = TG_NAME[t]
    gpu = name.split(" (", 1)[0].split(",", 1)[0]
    return gpu, (name.split("), ", 1)[1] if "), " in name else "")


def target_head(t):
    gpu, mode = gpu_mode(t)
    return (f'{e(gpu)} <span class="small mono">{e(TG_ISA[t])}</span>'
            + (f'<div class="small">{e(mode)}</div>' if mode else ""))
STATE_WORD = {"fails-like": "behaves incorrectly", "fails-differently": "fails another way",
              "correct": "correct", "unknown": "unknown", "na": "n/a"}
KIND_TAG = {"incorrect": "Appears to behave incorrectly", "unsupported": "Appears not to support"}
# the families' long names, in catalog order (catalog/toolchains.yaml)
FAM = {f.id: f.long_name for f in _registry().families.values()}
e = html.escape
# the statuses a compiler page lists: every issue that fails there, fixed later or not
LIST_ST = "open,changed,mixed,fixed"


BRAND = "OffTarget"


# the repository the site links to (--repo-url); none until there is a public one
REPO_URL = ""


def footer(repo_url: str = "") -> str:
    """Every page's footer: the author, the AI-assistance note and, with a repository, its link."""
    from offload.engine.site.scrub import AUTHOR
    name, url = AUTHOR
    repo = f' <a class="src" href="{e(repo_url)}">Source code</a>' if repo_url else ""
    return f'<p>By <a href="{e(url)}">{e(name)}</a>, with assistance from AI tools.{repo}</p>'


def page(title, body, root, current, scripts="", description=""):
    tpl = (SITE / "templates" / "base.html").read_text()
    cur = {f"cur_{k}": (' aria-current="page"' if k == current else "")
           for k in ("issues", "compilers", "canuse", "method")}
    full = title if title == BRAND else f"{title} · {BRAND}"
    return tpl.format(title=e(full), body=body, root=root, scripts=scripts,
                      description=e(description or title), footer=footer(REPO_URL), **cur)


def state_word(c, kind):
    if c["state"] == "fails-like" and kind == "unsupported":
        return "not supported"
    return STATE_WORD[c["state"]]


def variants_table(cells, kind):
    # the site data's order: family, release, then catalog position (two installs of one
    # release, GCC on the MI250X and the A100, sort the same way under every hash seed)
    tcs = sorted({c["tc"] for c in cells}, key=_order)
    head = "".join(f'<th scope="col">{target_head(t)}</th>' for t in TARGETS.values())
    names = {tc: next(c["version"] for c in cells if c["tc"] == tc) for tc in tcs}
    # one release installed per GPU vendor (GCC 16.2.0's AMD and NVIDIA builds): one row when the
    # installs ran on different GPUs, each cell from the install that ran there; where two ran on
    # one GPU, a row each, named by its GPUs
    ran = {tc: [c["target"] for c in cells if c["tc"] == tc and c["state"] != "na"] for tc in tcs}
    groups: dict = {}
    for tc in tcs:
        groups.setdefault(names[tc], []).append(tc)
    rows_of = []
    for name, group in groups.items():
        targets = [t for tc in group for t in ran[tc]]
        if len(group) > 1 and len(targets) == len(set(targets)):
            rows_of.append((name, group))
        else:
            for tc in group:
                on = ", ".join(dict.fromkeys(gpu_mode(t)[0] for t in ran[tc]
                                             if next(c for c in cells if c["tc"] == tc and c["target"] == t)["state"] != "unknown"))
                rows_of.append((name + (f" ({on})" if len(group) > 1 and on else ""), [tc]))
    rows = []
    for name, group in rows_of:
        cs = {c["target"]: c for c in cells if c["tc"] in group and (c["state"] != "na" or len(group) == 1)}
        tds = []
        for t in TARGETS.values():
            c = cs.get(t)
            if not c:
                tds.append('<td><span class="v s-na">n/a</span></td>')
                continue
            why = f' title="{e(c["reason"])}"' if c["reason"] else ""
            extra = f'<div class="small">{e(c["reason"])}</div>' if c["state"] == "unknown" and c["reason"] else ""
            tds.append(f'<td><span class="v s-{c["state"]}"{why}>{e(state_word(c, kind))}</span>{extra}</td>')
        rows.append(f'<tr><th scope="row">{e(name)}</th>{"".join(tds)}</tr>')
    return (f'<div class="box"><table><thead><tr><th scope="col">Compiler</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def messages(ms, kind):
    """Each distinct failure under the grid, with where it happens."""
    if not ms:
        return ""
    rows = "".join(
        f'<tr><td><span class="v s-{m["state"]}">{e(state_word({"state": m["state"]}, kind))}</span></td>'
        f'<td>{"<br>".join(e(w) for w in m["where"])}</td>'
        f'<td><details><summary>show</summary><pre class="light">{e(m["message"] or m["outcome"])}</pre></details></td></tr>'
        for m in ms)
    return ('<h3>Messages</h3><div class="box"><table><thead><tr><th scope="col">Result</th>'
            f'<th scope="col">Compiler and GPU</th><th scope="col">Message</th></tr></thead><tbody>{rows}</tbody></table></div>')


def spec_section(p):
    """What the specification requires: version, section, page and lines, and the passage
    (a member of an issue shows its defect's requirement and says so)."""
    items = []
    for c in p["citations"]:
        where = re.search(r"p\.[\d\u2013\-]+(?:\s+l\.[\d\u2013\-]+)?", c.get("text", ""))
        label = f'{c["version"]} \u00a7{c["section"]}' if c.get("version") and c.get("section") else c.get("text", "")
        items.append(f'<div class="card"><p><strong>{e(label)}</strong>'
                     + (f' <span class="small">{e(where.group(0))}</span>' if where else "") + '</p>'
                     + (f'<blockquote>{e(c["quote"])}</blockquote>' if c.get("quote") else "") + '</div>')
    src = p.get("citations_from")
    note = (f'<p class="small">The same requirement as the issue <a href="{e(page_name(src))}.html">{e(src)}</a>.</p>'
            if src else "")
    return ('<section><h2>What the specification requires</h2>'
            '<p class="small">The specification text this program relies on and the compiler is expected to support.</p>'
            + note + '<div class="grid2">' + "".join(items) + '</div></section>')


def issue_page(p):
    tag = "Mixed evidence" if p["status"] == "mixed" else KIND_TAG[p["kind"]]
    status = {"open": "Open", "changed": f"Changed in {p['status_version']}",
              "fixed": f"Fixed in {p['status_version']}", "mixed": "Mixed evidence",
              "not-reproduced": "Not reproduced in current runs", "not-run": "Not yet run"}.get(p["status"], p["status"])
    parts = [f'<p class="small"><a href="../index.html">Observed issues</a> › {e(p["id"])}</p>',
             '<div class="row-wrap">'
             f'<span class="tag {"k-mixed" if p["status"] == "mixed" else "k-" + p["kind"]}">{e(tag)}</span>'
             f'<span class="small">{e(p["failure"][:1].upper() + p["failure"][1:])} · '
             f'{"C" if p["lang"] == "c" else "Fortran"} · '
             f'{"OpenACC" if p["model"] == "acc" else "OpenMP"} · {e(status)}'
             f'{" · regression" if p["regression"] else ""}</span></div>',
             f'<h1>{e(p["title"])}</h1>']
    if p.get("legality"):
        why = p.get("legality_why") or ""
        parts.append(f'<p class="legality lg-{e(p["legality"])}"><b>Legality:</b> {e(p["legality_words"])}.'
                     f'{" " + e(why) if why else ""} <a href="../method.html#legality">How this is checked</a></p>')
    if p["defect"] != p["id"]:
        parts.append(f'<p>Same issue as <a href="{e(p["defect_page"])}.html">{e(p["defect"])}</a>; this program is '
                     'another reproducer of it.</p>')
    if p.get("summary"):
        parts.append(f'<p>{e(p["summary"])}</p>')
    if p.get("mixed_reason"):
        parts.append(f'<section><h2>Mixed evidence</h2><p>{e(p["mixed_reason"])}</p></section>')
    if p["cells"]:
        parts.append('<section><h2>Affected variants</h2>' + variants_table(p["cells"], p["kind"]) +
                     '<p class="small">"behaves incorrectly" / "not supported": this issue, confirmed in up to four '
                     'environments (another build directory, another node, a repeat). "fails another way": a '
                     'different failure, not counted as this issue. "unknown": not run there, or the runs '
                     'disagree.</p>' + messages(p["messages"], p["kind"]) + '</section>')
    if p["commands"] or p["source"]:
        cmds = "".join(f'<h3>{e(c["label"])}{" (runs correctly)" if c["role"] == "correct" else ""}</h3>'
                       f'<pre>{e(c["text"])}</pre>' for c in p["commands"])
        src = (f'<details><summary>Program ({len(p["source"].splitlines())} lines)</summary>'
               f'<pre class="light">{e(p["source"])}</pre></details>') if p["source"] else ""
        link = f'<p><a href="{e(p["source_url"])}">Source in the repository</a></p>' if p.get("source_url") else ""
        r = p.get("report_urls") or {}
        if r:
            link += ('<p class="small report">Something to add? '
                     f'<a href="{e(r["dispute"])}">Dispute its legality</a> · '
                     f'<a href="{e(r["fixed"])}">Report it fixed in a newer release</a> · '
                     f'<a href="{e(r["wrong"])}">Report a mistake on this page</a></p>')
        parts.append(f'<section><h2>Reproduce</h2>{cmds}{src}{link}</section>')
    if p.get("expected") or p.get("observed"):
        parts.append('<section><h2>Expected and observed</h2><div class="grid2">'
                     + (f'<div class="card"><h3>Expected</h3><pre class="light">{e(p["expected"])}</pre></div>'
                        if p.get("expected") else "")
                     + (f'<div class="card"><h3>Observed where it behaves incorrectly</h3>'
                        f'<pre class="light">{e(p["observed"])}</pre></div>' if p.get("observed") else "")
                     + '</div></section>')
    if p["citations"]:
        parts.append(spec_section(p))
    ev = []
    if p["controls"]:
        ev.append('<div class="card"><h3>Same compiler, one change</h3><ul>' + "".join(
            f'<li>{e(c["what"])}: ' + ("; ".join(f'{e(r["label"])}: {e(STATE_WORD[r["state"]])}' for r in c["results"])
                                       or "not run yet")
            + (f'<details><summary>Control program</summary><pre class="light">{e(c["source"])}</pre></details>'
               if c.get("source") else "") + '</li>'
            for c in p["controls"]) + '</ul></div>')
    if p["witnesses"]:
        ev.append(f'<div class="card"><h3>Other compilers run it correctly</h3><p>{e(", ".join(p["witnesses"]))}</p></div>')
    if ev:
        parts.append('<section><h2>Evidence</h2><div class="grid2">' + "".join(ev) + '</div></section>')
    if p.get("workaround"):
        parts.append(f'<section><h2>Workaround</h2><p>{e(p["workaround"])}</p></section>')
    if p.get("found_in"):
        parts.append(f'<section><h2>Found in</h2><p>{e(p["found_in"])}</p></section>')
    if p["defect"] == p["id"] and len(p["members"]) > 1:
        parts.append('<section><h2>Reproducers of this issue</h2><ul>' + "".join(
            f'<li><a href="{e(m["page"])}.html">{e(m["id"])}</a></li>' for m in p["members"]) + '</ul></section>')
    return "\n".join(parts)


# the groups of a compiler page, most serious first: (title, test on an issue)
GROUPS = (("Wrong answers", lambda i: i.get("symptom") == "wrong_answer"),
          ("Crashes, hangs and errors at run time", lambda i: i.get("stage") == "run"),
          ("Compiler crashes and hangs", lambda i: i.get("symptom") in ("ice", "timeout")),
          ("Legal code refused at compile or link time", lambda i: i["kind"] == "unsupported"),
          ("Other observed issues", lambda i: True))
ST_WORD = {"open": "Open", "changed": "Changed in", "fixed": "Fixed in", "mixed": "Mixed evidence",
           "not-reproduced": "Not reproduced in current runs", "not-run": "Not yet run"}


def compiler_page(c, issues, root):
    by = {i["id"]: i for i in issues}
    fam = c["family"]

    def status(i):
        v = i["fams"].get(fam) or {}
        word = ST_WORD.get(v.get("status"), v.get("status") or "")
        return f"{word} {v['status_version']}" if v.get("status_version") else word

    def item(i):
        reg = i["fams"].get(fam, {}).get("regression")
        return (f'<li><a href="{root}issues/{i["page"]}.html">{e(i["title"])}</a> '
                f'<span class="small">{e(status(i))}{" · regression" if reg else ""}</span></li>')

    def lst(ids):
        rows = [by[i] for i in ids if i in by]
        return '<ul>' + "".join(item(i) for i in rows) + '</ul>' if rows else '<p class="sub">None.</p>'
    defects = [by[i] for i in c["fails"] if i in by and by[i]["defect"] == i]
    order = {i["id"]: n for n, i in enumerate(fixed_order(defects, fam, set(c["regressions"])))}
    groups = []
    placed: set = set()
    for title, test in GROUPS:
        mine = sorted((i for i in defects if i["id"] not in placed and test(i)), key=lambda i: order.get(i["id"], len(order)))
        placed |= {i["id"] for i in mine}
        if mine:
            groups.append(f'<section><h2>{e(title)} <span class="small">({len(mine)})</span></h2>'
                          f'<ul>{"".join(item(i) for i in mine)}</ul></section>')
    return (f'<h1>{e(c["label"])}</h1><p class="sub">{len(defects)} observed issues; '
            f'{len(c["regressions"])} regressions from the previous version, marked below. Most serious first: wrong '
            'results, then issues whose legality is settled, then regressions, then how widely an issue fails.</p>'
            f'<p><a href="{root}index.html?fam={fam}&amp;vers={quote(pill(c["tc"]))}&amp;st={LIST_ST}">'
            'See them in the issue list</a></p>'
            + "".join(groups) +
            f'<section><h2>Fixed or changed in this version</h2>{lst(c["fixed_or_changed"])}</section>')


def pill(tc: str) -> str:
    """The issue list's version button of a toolchain (its `vers` value): "21.0.3", "16.2 AMD"."""
    return _registry().toolchains[tc].site_pill


# the parts of a release's bar: when its issues fail, in the order the bar shows them
STAGES = (("run", "at run time"), ("compile", "at compile time"), ("link", "at link time"))
FRONT_ENDS = {f.id: (f.site_name.split(" (", 1)[1].rstrip(")") if " (" in (f.site_name or "") else "")
              for f in _registry().families.values()}


def _gpus(targets) -> str:
    """"MI300A (unified memory, copy), MI250X": the GPUs of `targets`, with their memory modes
    where a GPU ran in more than one."""
    by: dict = {}
    for t in targets:
        gpu, mode = gpu_mode(t)
        by.setdefault(gpu, []).append(mode.split(" (", 1)[0])
    return ", ".join(g + (f" ({', '.join(m)})" if len(m) > 1 else "") for g, m in by.items())


def compilers_index(cs: list[dict], issues: list[dict], ran: dict, root: str = "../") -> str:
    """The compilers page: per family, its releases left to right. A release shows how many issues
    fail on it and a bar of them by when they fail (each part opens those issues in the list);
    between two releases of a family, its regressions and fixes. Bars share a scale within a
    family only (the counts follow how hard each compiler was searched)."""
    by = {i["id"]: i for i in issues}
    order = {tc: n for n, tc in enumerate(VERSIONS)}
    fams = list(dict.fromkeys(c["family"] for c in sorted(cs, key=lambda c: order.get(c["tc"], 99))))
    legend = "".join(f'<span class="key"><span class="sw seg-{s}"></span>fails {e(w)}</span>' for s, w in STAGES)
    out = [f'<h1>Compilers</h1><p class="sub wide">{len(cs)} compiler releases from {len(fams)} families, each run on '
           'the GPUs listed with it. A release shows the issues that fail on it, split by when they fail; a part '
           'of a bar opens those issues in the list. Bars share a scale within each family only: the counts follow '
           'how hard each compiler was searched, not how good it is.</p>'
           f'<p class="small legend">{legend}</p>']
    for fam in fams:
        rels = sorted((c for c in cs if c["family"] == fam), key=lambda c: order.get(c["tc"], 99))
        counts = []
        for c in rels:
            defects = [by[i] for i in c["fails"] if i in by and by[i]["defect"] == i]
            counts.append({s: sum(1 for i in defects if i.get("stage") == s) for s, _w in STAGES} | {"all": len(defects)})
        top = max([n["all"] for n in counts] + [1])
        targets = list(dict.fromkeys(t for c in rels for t in ran.get(c["tc"], [])))
        cols = []
        for k, (c, n) in enumerate(zip(rels, counts)):
            prev = rels[k - 1] if k else None
            delta = ""
            if prev and prev["version"] != c["version"]:
                reg, fix = len(c["regressions"]), len(c["fixed_or_changed"])
                delta = (f'<p class="delta">since {e(prev["version"])}: {reg} regressions, {fix} fixed or changed</p>'
                         if reg or fix else f'<p class="delta">No change from {e(prev["version"])}</p>')
            link = lambda s: (f'{root}index.html?fam={fam}&amp;vers={quote(pill(c["tc"]))}'  # noqa: E731
                              f'&amp;stages={s}&amp;st={LIST_ST}')
            segs = "".join(f'<a class="seg seg-{s}" style="flex-grow:{n[s]}" href="{link(s)}" '
                           f'title="{n[s]} fail {e(w)}" aria-label="{n[s]} issues of {e(c["label"])} that fail {e(w)}"></a>'
                           for s, w in STAGES if n[s])
            parts = "".join(f'<span class="key" title="{n[s]} fail {e(w)}"><span class="sw seg-{s}"></span>{n[s]}'
                            f'<span class="vh"> {e(w)}</span></span>' for s, w in STAGES if n[s])
            cols.append(f'<li class="release"><a class="rel" href="{c["tc"]}.html">'
                        f'{e(c["label"].split(" ", 1)[1])}</a>'
                        f'<p class="count"><span class="n">{n["all"]}</span> issues</p>'
                        f'<div class="bar" style="width:{100 * n["all"] / top:.1f}%">{segs}</div>'
                        f'<p class="small parts">{parts or "none"}</p>{delta}</li>')
        out.append(f'<section class="family"><div class="fam-head"><h2>{e(FAM[fam])}</h2>'
                   f'<span class="small">{e(FRONT_ENDS.get(fam, ""))}</span>'
                   f'<a class="all" href="{root}index.html?fam={fam}">All {e(FAM[fam])} issues</a></div>'
                   f'<p class="small">Ran on {e(_gpus(targets))}.</p><ol class="releases">{"".join(cols)}</ol></section>')
    return "".join(out)


METHOD = """<h1>Method</h1>
<p>Every observation on this site comes from small, legal programs compiled and run on the compilers and GPUs
below. Each program checks its own result and prints it.</p>
<section><h2>How a result is decided</h2>
<p>Each program is compiled and run with time limits, and its outcome is classified from all of the compiler's
messages as rejected, internal compiler error, link failure, crash, hang, wrong answer or correct. Its legality is
checked against the OpenMP or OpenACC specification text by two independent checkers, neither of them the compiler
under test.</p>
<p>A failure counts only when it reproduces in another build directory, on another node and in a repeat run;
results that disagree are shown as unknown. Where a program has a control, the control differs by one change and
runs correctly on the same compiler. When another compiler family runs the same program correctly, that is listed
as evidence too.</p></section>
<section><h2>States and statuses</h2>
<p>Each cell of an issue's table says what happened to the program on that compiler, GPU and memory mode:</p>
<dl class="terms">
<dt>behaves incorrectly / not supported</dt><dd>this issue reproduces there.</dd>
<dt>fails another way</dt><dd>a different failure there; not counted as this issue.</dd>
<dt>correct</dt><dd>the program's own check passes there.</dd>
<dt>unknown</dt><dd>not run there, or the runs disagree.</dd>
</dl>
<p>Each issue also says when it fails and how:</p>
<dl class="terms">
<dt>At compile time</dt><dd>the compiler refuses the legal program, crashes (an internal compiler error) or does not finish.</dd>
<dt>At link time</dt><dd>the link step refuses it (an undefined symbol, a missing library) or the offload or LTO tool crashes.</dd>
<dt>At run time</dt><dd>the program crashes or aborts, stops with a run-time error, hangs, or finishes with a wrong answer.</dd>
</dl>
<h2 id="legality">Legality review</h2>
<p>Each issue's program is also read by independent readers that see the program, the specification text and the
observed result, but not the argument written for the issue. The readers are language models (Claude Sonnet), each
run on its own with no access to the catalog. Every batch of programs a reader gets holds one decoy whose answer is
known, an illegal program or a result the specification does not require; a reader that misses its decoy does not
count, and neither does one that quotes a passage the specification does not contain, quotes a program line the
program does not contain, or says the program lacks something that is there. Two readers read each program.
When they disagree or one is uncertain, two more readers adjudicate: they see both readings and check each against the
specification, in batches that hold a decoy dispute whose right side is known. Every reading that counts, for an
issue or against it, is then fact-checked: a verifier lists the premises the reading rests on and checks each
against the specification and the program, in batches that hold a reading with a known false premise and a sound
one. A reading two verifiers refute, each with quotes that check out, no longer counts. An argument against an issue's
legality, filed from the link on its page, goes to adjudicators the same way. An issue's legality is one of:</p>
<dl class="terms">
<dt>independently confirmed</dt><dd>two readers, or two adjudicators of a dispute, find the program legal and the
result required.</dd>
<dt>supported by outside evidence</dt><dd>the readers find the specification unclear, and an official example, a vendor's
own bug tracker or a fix in a later release settles it.</dd>
<dt>contested</dt><dd>an adjudicator (or, before adjudication, a reader) finds the program not legal or the result
not required, and nothing outside settles it. The reason is shown on the issue.</dd>
<dt>not independently confirmed</dt><dd>no review yet, readers uncertain, or the program changed since its review.</dd>
</dl>
<p>An issue's status on a compiler release X is one of:</p>
<dl class="terms">
<dt>Fixed in X</dt><dd>correct on X wherever the previous version failed (each GPU and memory mode).</dd>
<dt>Changed in X</dt><dd>a different failure there from X on.</dd>
<dt>Not yet run</dt><dd>no result yet on the compiler the program was written for.</dd>
<dt>Not reproduced in current runs</dt><dd>it ran there and did not fail this way.</dd>
<dt>Mixed evidence</dt><dd>the program's legality is disputed or not settled; the reason is shown.</dd>
</dl></section>
<section><h2>Behaviour no tested compiler implements</h2><p>Three constructs read plainly in the OpenMP 5.2
text and fail on every compiler tested (AFAR, CCE, NVHPC, GCC) and on the host: a firstprivate item
initialized by its type's type-bound defined assignment (section 5.4.4), a lastprivate item updated by it
(section 5.4.5), and the finalization of a privatized item of a finalizable type at the end of the region
(section 5.3). Because no implementation honours them and the failure is not specific to offload, they are not
listed as compiler issues here.</p></section>
<section><h2>HeCBench programs</h2><p>Some programs come from HeCBench, a public collection of GPU benchmarks (ORNL/HeCBench,
one fixed version). Its OpenMP offload versions are built the way the collection's own makefiles say, with each
compiler's own offload flags, and checked against a serial host build of the same code or against the program's own
check. Half of the benchmarks, chosen in advance by a fixed rule on their names, were used here; the results for the
other half are held back and not shown. Benchmarks under copyleft or non-commercial licences are left out. As for every
other program, a failure counts only when it reproduces in another build directory, on another node and in a repeat
run, and another compiler family runs the same program correctly. The failures found this way are reduced to small
programs written for this site; no benchmark code is copied. Runs that hit the 30-second time limit are not counted
as issues, because they cannot tell a hang from a slow kernel.</p></section>
<section><h2>Compilers and GPUs</h2>{machines}</section>
<section><h2>Sources and credits</h2><p>Programs come from a generated catalog of OpenMP and OpenACC
constructs, randomized and stress programs, real application codes, and public bug reports and test suites,
including the OpenMP Validation and Verification suite, the LLVM project's offload tests (Apache 2.0 with LLVM
exception) and AMD's AOMP tests, each credited in its program's header.</p>
<h3>Quoted specification text</h3>
<p>The passages under "What the specification requires" are quoted, each with its version, section and page,
from these documents, whose notices follow.</p>
<ul>
<li>OpenMP Application Programming Interface, Version 4.5 November 2015: Copyright © 1997-2015 OpenMP Architecture Review Board.</li>
<li>OpenMP Application Programming Interface, Version 5.0 November 2018: Copyright © 1997-2018 OpenMP Architecture Review Board.</li>
<li>OpenMP Application Programming Interface, Version 5.1 November 2020: Copyright © 1997-2020 OpenMP Architecture Review Board.</li>
<li>OpenMP Application Programming Interface, Version 5.2 November 2021: Copyright © 1997-2021 OpenMP Architecture Review Board.</li>
<li>OpenMP Application Programming Interface, Version 6.0 November 2024: Copyright © 1997-2024 OpenMP Architecture Review Board.</li>
</ul>
<p>Permission to copy without fee all or part of this material is granted, provided the OpenMP Architecture Review Board copyright notice and the title of this document appear. Notice is given that copying is by permission of the OpenMP Architecture Review Board.</p>
<ul>
<li>The OpenACC® Application Programming Interface, Version 3.4, June 2025, OpenACC-Standard.org: © 2011-2025 OpenACC-Standard.org. All rights reserved. Complying with all applicable copyright laws is the responsibility of the user. Without limiting the rights under copyright, no part of this document may be reproduced, stored in, or introduced into a retrieval system, or transmitted in any form or by any means (electronic, mechanical, photocopying, recording, or otherwise), or for any purpose, without the express written permission of the authors.</li>
</ul></section>"""


def machines_table(ran_tc):
    """Each compiler release and the GPUs (with their ISA) and memory modes it has results on."""
    def where(tc):
        by: dict = {}
        for t in ran_tc.get(tc, []):
            gpu, mode = gpu_mode(t)
            by.setdefault((gpu, TG_ISA[t]), []).append(mode.split(" (")[0])
        return "; ".join(f"{g} ({isa}" + (f", {' and '.join(m for m in ms if m)}" if any(ms) else "") + ")"
                         for (g, isa), ms in by.items()) or "not run"
    rows = "".join(f'<tr><th scope="row">{e(FAM[f])}</th><td>{e(v)}</td><td>'
                   + e(where(tc)) + "</td></tr>" for tc, (f, v, _) in VERSIONS.items())
    return ('<div class="box"><table><thead><tr><th scope="col">Compiler</th><th scope="col">Version</th>'
            f'<th scope="col">GPUs and memory modes</th></tr></thead><tbody>{rows}</tbody></table></div>')


DIRECTIVE = re.compile(r"^\s*(?:!\$(?:omp|acc)|#pragma\s+(?:omp|acc))", re.I)


def render(out: Path) -> None:
    out = Path(out)
    d = out / "data"
    shutil.copytree(SITE / "static", out / "static", dirs_exist_ok=True)
    data = json.loads((d / "issues.json").read_text())
    issues = data["issues"]
    (out / "index.html").write_text(page(
        "Offload compiler issues", '<div class="cols"><details id="filters-box" class="filters-box" open>'
        '<summary class="btn">Filters</summary><aside id="filters" class="filters" aria-label="Filters"></aside></details>'
        '<div class="main"><h1 id="heading">Observed issues</h1><p id="summary" class="sub">Loading…</p>'
        '<p class="small legend">Version boxes: <span class="v s-fails-like">behaves incorrectly</span> '
        '<span class="v s-correct">correct</span> <span class="v s-fails-differently">fails another way</span> '
        '<span class="v s-unknown">not run or undecided</span></p>'
        '<div id="also" class="row-wrap"></div><div id="sorts" class="row-wrap"></div><div id="list" class="list"></div>'
        '<p class="small">Each row is one issue; findings with the same cause are grouped as its reproducers.</p></div></div>', "", "issues",
        '<script src="static/toolchains.js"></script><script src="static/query.js"></script>'
        '<script src="static/issues.js"></script>',
        "OpenMP and OpenACC device-offload programs that compilers get wrong, with reproducers and evidence."))
    # the issue list was issues.html: old and shared links forward to it with their filters
    (out / "issues.html").write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Observed issues</title>'
        '<meta name="robots" content="noindex"><link rel="canonical" href="index.html">'
        "<script>location.replace('index.html' + location.search + location.hash);</script></head>"
        '<body><p>The issue list is at <a href="index.html">index.html</a>.</p></body></html>\n')
    (out / "issues").mkdir(exist_ok=True)
    for i in issues:
        p = json.loads((d / "issues" / f"{i['page']}.json").read_text())
        (out / "issues" / f"{i['page']}.html").write_text(
            page(p["title"], issue_page(p), "../", "issues"))
    (out / "compilers").mkdir(exist_ok=True)
    idx = []
    for f in sorted((d / "compilers").glob("*.json")):
        c = json.loads(f.read_text())
        (out / "compilers" / f"{c['tc']}.html").write_text(page(c["label"], compiler_page(c, issues, "../"),
                                                                "../", "compilers"))
        idx.append(c)
    (out / "compilers" / "index.html").write_text(page(
        "Compilers", compilers_index(idx, issues, data.get("ran_tc") or {}), "../", "compilers",
        description="The compiler releases measured, their issues by when they fail, and what changed between releases."))
    (out / "canuse.html").write_text(page(
        "Feature support", '<h1>Feature support</h1><p class="sub">What each compiler does with a construct or clause, '
        'per GPU and memory mode. Pick one from the list, or type to narrow it.</p>'
        '<p><label for="cu-q" class="lbl">Construct</label><br><input id="cu-q" list="cu-atoms" '
        'style="font:inherit;padding:8px 12px;border:1px solid var(--ok-line);border-radius:8px;width:100%;max-width:420px">'
        '<datalist id="cu-atoms"></datalist></p><div id="cu-out"></div><div id="cu-browse" class="browse"></div>', "", "canuse",
        '<script src="static/toolchains.js"></script><script src="static/canuse.js"></script>'))
    (out / "method.html").write_text(page("Method", METHOD.replace("{machines}", machines_table(data.get("ran_tc", {}))), "", "method"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--repo-url", default="")
    ap.add_argument("--source-branch", default="master",
                    help="the branch the source links point into (the repository's default branch)")
    a = ap.parse_args(argv)
    from offload.engine.site import data as D
    global REPO_URL
    REPO_URL = a.repo_url.rstrip("/")
    rep = D.build(Path(a.out), a.repo_url, a.source_branch)
    render(Path(a.out))
    print(json.dumps(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
