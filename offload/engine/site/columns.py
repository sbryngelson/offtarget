"""The rows, columns and names of the feature-support table, derived from the toolchain registry."""
from collections import Counter

from offload.engine import toolchains as T
from offload.engine.confirm.machines import load as machines


def version_label(reg: T.Registry, fam: str, version: str) -> str:
    name = reg.families[fam].name
    return version if version.startswith(name) else f"{name} {version}"


def target_names() -> tuple[dict, dict]:
    """(long names, short names) of the GPU and memory-mode targets, by target id."""
    tg_name, tg_short = {}, {}
    for m in machines().values():
        for mode in m.modes:
            spec = m.mode_table[mode]
            if spec.get("target"):
                tg_name[spec["target"]] = spec["target_name"]
                tg_short[spec["target"]] = spec["target_short"]
    return tg_name, tg_short


def target_isas() -> dict:
    """The ISA code name (gfx942, gfx90a, sm_80, ...) of each GPU and memory-mode target, by target id."""
    return {spec["target"]: m.arch for m in machines().values() for mode in m.modes
            if (spec := m.mode_table[mode]).get("target")}


def canuse_columns(reg: T.Registry | None = None) -> dict:
    """{"rows": [[toolchain id, label]], "targets": {gpu kind: [[target id, short name]]},
    "kinds": {toolchain: gpu kind}, "runs": {toolchain: [the target ids it and its twins ran on]}}."""
    reg = reg or T.registry()
    tcs = reg.toolchains
    _, tg_short = target_names()
    merged_fams = {tcs[t].family_id for t in reg.merged()}
    rows = [[t, version_label(reg, tcs[t].family_id, tcs[t].site_version)]
            for t in reg.site_toolchains() if tcs[t].family_id in merged_fams]
    # one release installed for several GPUs (GCC 16.2.0 for AMD and the A100): each row
    # named with its install's GPU (the last word of its site pill)
    seen = Counter(label for _, label in rows)
    rows = [[t, f"{label} ({tcs[t].site_pill.split()[-1]})" if seen[label] > 1 and tcs[t].site_pill
             else label] for t, label in rows]
    kinds = reg.target_kinds()
    targets: dict[str, list] = {}
    from offload.engine.confirm.machines import load as machines
    measured = {m.name for m in machines().values() if m.toolchains}      # a GPU with no merged matrix rows has no column
    for (machine, _), x in reg.targets().items():
        if machine in measured:
            targets.setdefault(kinds[x], []).append([x, tg_short[x]])
    return {"rows": rows, "targets": targets, "kinds": {t: reg.arches[tcs[t].arch]["gpu"] for t, _ in rows},
            "runs": {t: list(reg.run_targets(t)) for t, _ in rows}}
