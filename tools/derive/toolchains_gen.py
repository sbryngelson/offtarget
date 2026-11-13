#!/usr/bin/env python3
"""Generate what cannot read catalog/toolchains.yaml at run time.

    python3 -I tools/derive/toolchains_gen.py            # write the generated files
    python3 -I tools/derive/toolchains_gen.py --check    # exit 1 when a committed file is stale

Each generated file carries a "generated from catalog/toolchains.yaml" header:
* site/static/toolchains.js: constants for the site scripts (family order, version
  pills and their toolchains, GPU/mode columns per family, family and target
  names, can-I-use rows).
* tools/jobs/toolchains.sh: the table the job scripts source (``tc_check NAME
  LANE`` refuses a toolchain not in the lane; lists per lane, machine and family;
  ``tc_machine``, ``tc_family``, ``tc_modes``).
* docs/tooling/toolchains.md: the table of toolchains for people.
tools/regenerate.py --check and tests/cluster/test_reports.py fail when
a committed copy differs from the catalog."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
if __name__ == "__main__":      # what is committed comes from the committed catalogs, never from one user's settings
    os.environ["OFFLOAD_LOCAL"] = ""

from offload.engine import toolchains as T  # noqa: E402
from offload.engine.confirm.machines import load as machines  # noqa: E402
from offload.engine.site.columns import canuse_columns, target_isas, target_names, version_label  # noqa: E402

HEADER = "generated from catalog/toolchains.yaml by tools/derive/toolchains_gen.py; do not edit"
OUTPUTS = {
    "site/static/toolchains.js": "site_js",
    "tools/jobs/toolchains.sh": "shell_table",
    "docs/tooling/toolchains.md": "docs_table",
}


_version_label = version_label


def _js(value) -> str:
    """A JavaScript literal (single-quoted strings, unquoted plain keys)."""
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_js(v) for v in value) + "]"
    if isinstance(value, dict):
        items = []
        for k, v in value.items():
            key = k if k.replace("_", "").isalnum() and not k[0].isdigit() and "-" not in k \
                else _js(k)
            items.append(f"{key}: {_js(v)}")
        return "{ " + ", ".join(items) + " }"
    return json.dumps(value)


def site_js(reg: T.Registry) -> str:
    fams = reg.family_order()
    tcs = reg.toolchains
    targets = list(reg.targets().values())
    by_fam = {f: [t for t in reg.site_toolchains() if tcs[t].family_id == f] for f in fams}
    versions = {f: [tcs[t].site_pill for t in by_fam[f]] for f in fams}
    pills = [p for ps in versions.values() for p in ps]
    if len(set(pills)) != len(pills):
        raise ValueError(f"toolchains: the site's version pills are not unique: {pills}")
    tc_of = {tcs[t].site_pill: t for f in fams for t in by_fam[f]}
    fam_targets = {f: [x for x in targets if any(x in tcs[t].targets() for t in by_fam[f])]
                   for f in fams}
    fam_name = {f: reg.families[f].site_name for f in fams}
    tg_name, tg_short = target_names()
    cols = canuse_columns(reg)
    cu_tc, cu_tg, cu_kind, cu_run = cols["rows"], cols["targets"], cols["kinds"], cols["runs"]
    lines = [
        f"// {HEADER}",
        "// The toolchains the site knows: the family buttons (the first is the default), the",
        "// version pills of each family and their toolchain ids, the GPU/mode columns per family,",
        "// the family and target names, the ISA of each target, the feature-support rows and the",
        "// targets each row ran on.",
        f"const FAMILIES = {_js(list(fams))};",
        f"const VERSIONS = {_js(versions)};",
        f"const TC = {_js(tc_of)};",
        f"const TARGETS = {_js(fam_targets)};",
        f"const FAM_NAME = {_js(fam_name)};",
        f"const TG_NAME = {_js(tg_name)};",
        f"const TG_SHORT = {_js(tg_short)};",
        f"const TG_ISA = {_js(target_isas())};",
        f"const CU_TC = {_js(cu_tc)};",
        f"const CU_TG = {_js(cu_tg)};",
        f"const CU_KIND = {_js(cu_kind)};",
        f"const CU_RUN = {_js(cu_run)};",
        "if (typeof module !== 'undefined') module.exports = { FAMILIES, VERSIONS, TC, TARGETS,"
        " FAM_NAME, TG_NAME, TG_SHORT, TG_ISA, CU_TC, CU_TG, CU_KIND, CU_RUN };",
    ]
    return "\n".join(lines) + "\n"


def shell_table(reg: T.Registry) -> str:
    tcs = reg.toolchains
    out = [f"# {HEADER}",
           "# The toolchain table the job scripts source (`. tools/jobs/toolchains.sh`): the",
           "# toolchains per lane (the runner group a script belongs to), per machine",
           "# (measured; a regression release is not one) and per family, and",
           "# `tc_check NAME LANE`, which refuses a toolchain the lane does not run.",
           f"TC_ALL=\"{' '.join(tcs)}\""]
    for lane in reg.lanes():
        out.append(f"TC_LANE_{lane}=\"{' '.join(reg.of_lane(lane))}\"")
    for m in machines().values():
        out.append(f"TC_MACHINE_{m.name}=\"{' '.join(reg.of_machine(m.name))}\"")
    for fam in reg.families:
        out.append(f"TC_FAMILY_{fam}=\"{' '.join(reg.of_family(fam))}\"")
    out.append(f"TC_REGRESSION=\"{' '.join(reg.regression())}\"")

    def case(name: str, pairs, doc: str) -> None:
        out.append(f"{name}() {{  # {doc}")
        out.append('  case "$1" in')
        for value, names in pairs:
            out.append(f"    {'|'.join(names)}) echo \"{value}\" ;;")
        out.append("    *) return 1 ;;")
        out.append("  esac")
        out.append("}")

    def group(key):
        groups: dict = {}
        for n, t in tcs.items():
            groups.setdefault(key(t), []).append(n)
        return list(groups.items())
    case("tc_machine", group(lambda t: t.machine), "the machine of a toolchain")
    case("tc_family", group(lambda t: t.family_id), "the compiler family of a toolchain")
    case("tc_modes", group(lambda t: " ".join(str(x) for x in t.xnack_modes)),
         "the stored row keys of its memory modes")
    case("tc_lane", group(lambda t: t.lane), "the lane (runner group) of a toolchain")
    lanes = " ".join(reg.lanes())
    out += ["tc_list() {  # tc_list LANE [MACHINE]: the lane's toolchains (on MACHINE), comma-separated",
            '  local v out="" t; eval "v=\\${TC_LANE_$1-}"',
            f'  [ -n "$v" ] || {{ echo "unknown lane $1 (lanes: {lanes})" >&2; return 1; }}',
            '  for t in $v; do [ -z "${2:-}" ] || [ "$(tc_machine "$t")" = "$2" ] || continue; out="${out:+$out,}$t"; done',
            '  echo "$out"',
            "}",
            "tc_check() {  # tc_check NAME LANE: 0 when NAME is a toolchain of LANE, else a message and 1",
            '  local lane; lane=$(tc_lane "$1") || { echo "unknown toolchain $1 (catalog/toolchains.yaml); known: $TC_ALL" >&2; return 1; }',
            '  if [ "$lane" != "$2" ]; then',
            '    local v; eval "v=\\${TC_LANE_$2-}"',
            f'    [ -n "$v" ] || {{ echo "unknown lane $2 (lanes: {lanes})" >&2; return 1; }}',
            '    echo "toolchain $1 is not run by the $2 scripts (its lane: $lane); this lane runs: $v" >&2; return 1',
            "  fi",
            "}"]
    return "\n".join(out) + "\n"


def docs_table(reg: T.Registry) -> str:
    tcs = reg.toolchains
    ms = machines()
    out = [f"<!-- {HEADER} -->",
           "# Toolchains",
           "",
           "Every compiler release the project measures, from `catalog/toolchains.yaml`",
           "(`offload/engine/toolchains.py` reads it; `python3 -I tools/derive/toolchains_gen.py` writes this",
           "table, `site/static/toolchains.js` and `tools/jobs/toolchains.sh`). To add a release:",
           "docs/tooling/contributing.md, \"Add a compiler or a compiler release\".",
           "",
           "| id | family | version | machine | GPU | memory modes | lane | table column | site label | role |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for n, t in tcs.items():
        m = ms[t.machine]
        modes = ", ".join(f"{m.mode_of_row_key(x)} ({x})" for x in t.xnack_modes)
        role = (f"regression release, compared with `{t.regression_of}`" if t.regression_of
                else f"{reg.twin_tag(n)} twin of `{t.twin_of}`" if t.twin_of
                else "headline")
        if not t.report_column:
            role += "; no support-table column"
        if t.merged_key:
            role += f"; merged key `{t.merged_key}`"
        label = reg.label(n) if (t.report_column or t.twin_of or not t.regression_of) else "(none)"
        site = "" if t.twin_of else _version_label(reg, t.family_id, t.site_version)
        out.append(f"| `{n}` | {t.family_id} | {t.version} | {t.machine} | {t.arch} | {modes} | "
                   f"{t.lane} | {label} | {site} | {role} |")
    out += ["", "## Families", "",
            "| family | name | vendor packet | recipe kind | message table | gate compile budget (s) | legality witness |",
            "|---|---|---|---|---|---|---|"]
    from offload.engine.confirm.machines import frontend_checkers
    front_ends = {c.get("family") for c in frontend_checkers().values()}
    for f in reg.families.values():
        witness = ("never (under test only)" if f.under_test_only
                   else "witnesses other families' cases" if f.witness == "other_families"
                   else "its front end checks other families' cases" if f.id in front_ends
                   else "")
        out.append(f"| {f.id} | {f.long_name} | {f.vendor or '-'} | {f.kind} | {f.message_table} | "
                   f"{f.compile_s:g} | {witness} |")
    out += ["", "## Lanes", "",
            "| lane | toolchains | run by |",
            "|---|---|---|"]
    for lane in reg.lanes():
        out.append(f"| {lane} | {', '.join(f'`{t}`' for t in reg.of_lane(lane))} | "
                   f"{reg.lane_doc(lane)} |")
    return "\n".join(out) + "\n"


def generate(reg: T.Registry | None = None) -> dict[str, str]:
    """path (relative to the repository) -> contents of every generated file."""
    reg = reg or T.registry()
    return {path: globals()[fn](reg) for path, fn in OUTPUTS.items()}


def stale(root: Path = ROOT, reg: T.Registry | None = None) -> list[str]:
    """The generated files whose committed copy differs (or is missing)."""
    out = []
    for path, text in generate(reg).items():
        p = root / path
        if not p.is_file() or p.read_text() != text:
            out.append(path)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="report stale files, write nothing")
    ap.add_argument("--check-registry", action="store_true",
                    help="print offload.engine.toolchains.check_registry() (the catalog against "
                         "machines.yaml, canaries.yaml and the report columns); exit 1 on a problem")
    a = ap.parse_args(argv)
    if a.check_registry:
        problems = T.check_registry()
        for p in problems:
            print(p)
        print("[]" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    if a.check:
        bad = stale()
        for p in bad:
            print(f"stale: {p} (run python3 -I tools/derive/toolchains_gen.py)")
        return 1 if bad else 0
    for path, text in generate().items():
        p = ROOT / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
