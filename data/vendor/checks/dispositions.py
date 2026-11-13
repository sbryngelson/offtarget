"""Findings that are not in any vendor report, with the reason
(those that are fixed or not reproduced are computed from the runs)."""

# The site dispositions (not-a-compiler-issue, out-of-scope, mixed) live in each finding's
# site: block (offload.engine.site.header) and are read from there; VENDOR_ONLY keeps what only the
# vendor packets need. LEGACY_MANUAL is the table the site blocks were seeded from
# (by a one-off script, since removed), kept as the seed's record.
import sys as _sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[3]
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

LEGACY_MANUAL = {
    ("cce-acc-self-condition-ignored.f90", "hpe"): (
        "not a report", "out of scope (maintainer ruling 2026-10-21): the construct of interest runs on the host"),
    ("cce19-acc-if-false-link.f90", "hpe"): (
        "not a report", "out of scope (maintainer ruling 2026-10-21): the region with if(.false.) runs on the host"),
    ("catalog/cce-nohost-link.f90", "hpe"): (
        "held", "legality disputed (ruling RUL-LEGAL-NOHOST-REFERENCE)"),
    ("afar-linear-ref-omp50.f90", "amd"): (
        "not a report", "host-only construct (declare simd on a host procedure, no target region): outside "
        "the device-offload scope; the README does not mark it out of scope"),
    ("catalog/afar-c-complex-reduction-link.c", "amd"): (
        "not a report", "the undefined __atomic_load/__atomic_compare_exchange come from the host object "
        "(the program without the target construct fails the same way); with -latomic it builds and "
        "passes on the device in both modes: a missing libatomic link, not a device link failure"),
    ("afar-flang-thread-limit-target-parallel-do.f90", "hpe"): (
        "fixed in CCE 20.0.2", "CCE 19 rejects thread_limit on target parallel do (ftn-1370; its documentation "
        "claimed thread_limit on target for C/C++ only, rule R11c); CCE 20 and 21 accept it and are correct"),
    ("clang-c-declare-target-to-omp52.c", "hpe"): (
        "not a report", "the clang front end's rejection of a deprecated spelling, inherited by craycc; one "
        "upstream llvm-project issue covers both vendors (AMD packet, tier 4)"),
    ("fuzz/b2-85-cce20.f90", "hpe"): (
        "held: legality not settled", "rests on reading map(tofrom: dr%o1) as an explicit attribute of the "
        "structure dr; 5.2 §5.8.1 p.148 treats a reference to a structure element as a reference to the "
        "structure when implicit attributes are determined, so defaultmap(firstprivate: aggregate) may apply "
        "to dr"),
}

VENDOR_ONLY = {k: v for k, v in LEGACY_MANUAL.items() if k[0] in (
    "catalog/afar-c-complex-reduction-link.c",
    "afar-flang-thread-limit-target-parallel-do.f90",
    "clang-c-declare-target-to-omp52.c")}

_VENDOR = {"afar": "amd", "cce19": "hpe", "cce20": "hpe", "cce21": "hpe",
           "nvhpc": "nvidia", "nvhpc269": "nvidia"}


# finding files whose site: block does not parse: reported and skipped here, so one bad
# block cannot break every vendor-check tool at import; the site build parses every
# block itself (offload.engine.site.data.gather) and fails on it
BAD_HEADERS: list = []


def _from_headers(entries=None, root=_ROOT) -> dict:
    from offload.engine.site import header as H
    if entries is None:
        from offload.engine.confirm.findings import load_index
        entries = load_index()
    out = {}
    base = _Path(root) / "data" / "findings"
    for f in entries:
        try:
            h = H.parse(_Path(root) / f.file)
        except H.SiteHeaderError as e:
            BAD_HEADERS.append(f"{f.file}: {e}")
            print(f"dispositions: skipping {f.file}: {e}", file=_sys.stderr)
            continue
        if not h.disposition:
            continue
        kind, why = h.disposition
        status = "held (mixed evidence)" if kind == "mixed" else "not a report"
        rel = str((_Path(root) / f.file).relative_to(base))
        for v in sorted({_VENDOR[t] for t in f.toolchains if t in _VENDOR}):
            out[(rel, v)] = (status, why)
    return out


# (finding path under findings, vendor) -> (status, why)
MANUAL = {**_from_headers(), **VENDOR_ONLY}

# what the newest release does after a fix (shown with the computed "fixed" status)
FIXED_NOTE = {
    ("catalog/cce19-reduction-task-addrspacecast-ice.f90", "hpe"):
        "the internal compiler error is gone; CCE 20 and 21 then fail at the link with undefined "
        "_cray$mt_taskred_modifier_init/_fini, the defect of report cce-reduction-task-link",
    ("catalog/cce20-map-self-rejected.f90", "hpe"):
        "the rejection is gone; CCE 21 at HSA_XNACK=0 stops at run time with \"Requested self map cannot "
        "be satisfied\" (map(self) cannot be honoured without shared memory, which may be conforming); "
        "correct at HSA_XNACK=1",
}
