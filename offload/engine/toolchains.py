"""The toolchain registry: every compiler release the project measures, read
from catalog/toolchains.yaml. The matrix, gate, confirmer, support tables,
site and job scripts all ask this module for the list.

A toolchain has a family (releases and arch twins of one compiler share bugs),
a version, a machine and arch (catalog/machines.yaml), its memory modes, a
recipe (prelude, compilers, flags, environment) and its display names.

A twin is a toolchain's install on another GPU, named with the arch's
``twin_suffix`` (afar_g90) or after its machine (afar_mi300x).

NVHPC's memory mode is a compile flag (catalog/machines.yaml
``modes.<mode>.flags``), so ``for_mode`` returns a toolchain compiled for one
mode. AMD modes are run-time settings (HSA_XNACK), so it returns an AMD
toolchain unchanged. GCC 16.2 is ``under_test_only``."""
from __future__ import annotations

import dataclasses
import os
import re
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from offload.engine import localcfg
from offload.engine.root import ROOT  # noqa: E402
CATALOG = ROOT / "catalog" / "toolchains.yaml"
# the environment variable that points the registry at another catalog
# (tests: a copy with a fake toolchain added)
CATALOG_ENV = "COMPLIANT_TOOLCHAINS"


def _afar_bin(lustre: str, vast: str, isdir=os.path.isdir) -> str:
    """An install root with a fallback copy: the default install, or on a
    host without it that has the copy (Tioga: /p/vast1) the copy, so its
    front end (the legality checks, e.g. the fuzz minimizer's) runs there
    too."""
    return lustre if isdir(lustre) or not isdir(vast) else vast


@dataclass(frozen=True)
class Family:
    """A compiler family of catalog/toolchains.yaml."""
    id: str
    name: str                  # the short label ("CCE")
    long_name: str             # the site's method table ("Cray CCE")
    site_name: str             # the issue list's family button
    vendor: str | None         # the vendor packet (data/vendor/<vendor>)
    kind: str                  # the recipe kind (Toolchain.kind)
    message_table: str         # offload.engine.harness PATTERNS key
    compile_s: float           # the gate's seconds per compile
    flags: dict = field(default_factory=dict)        # model -> lang -> template
    unsupported: dict = field(default_factory=dict)  # "acc" | "acc/c" -> why
    prelude: str = ""
    fc: str = ""
    cc: str = ""
    cxx: str = ""              # the C++ driver (the hecbench campaign), "" when none
    version_flags: dict = field(default_factory=dict)  # OpenMP version -> flag
    c_version_flag: bool = False
    offload_targets: dict = field(default_factory=dict)  # GCC: arch prefix -> target
    latomic: dict = field(default_factory=dict)          # GCC: target -> extra flag
    under_test_only: str = ""  # the reason it is never a legality witness
    witness: str = ""          # "other_families": its compilers witness other cases
    site_gpus: str = ""        # the method table's "GPUs and memory modes" text
    site_public: dict = field(default_factory=dict)  # path template -> public form
    site_runtime_env: bool = False  # the site's commands export LD_LIBRARY_PATH

    def supports_model(self, model: str) -> bool:
        """Whether any language of the family compiles `model`."""
        return model not in self.unsupported

    def why_unsupported(self, model: str, lang: str) -> str | None:
        return self.unsupported.get(model) or self.unsupported.get(f"{model}/{lang}")


@dataclass(frozen=True)
class Toolchain:
    name: str
    prelude: str  # plain statement list (no pipes) run before compiling
    fc: str       # Fortran compiler command
    extra: str = ""  # extra flags of a non-baseline run (version, includes)
    model: str = "omp"  # "acc": compile OpenACC (CCE only)
    cc: str = ""  # C compiler command
    lang: str = "f90"  # "c": compile C (OpenMP only); "cpp": C++ (takes C's flags)
    arch: str = "gfx942"  # The offload target
    machine: str = "tuolumne"  # Where it runs
    # Extra run-time environment (Tioga: AFAR's library path)
    env: tuple[tuple[str, str], ...] = ()
    xnack_modes: tuple[int, ...] = (0, 1)  # Tioga runs X=0 only
    # The compiler vendor of the recipe ("afar", "cce", "nvhpc");
    # "" = by name (AFAR or, otherwise, CCE: the early toolchains)
    vendor: str = ""
    # The memory mode (row key) this toolchain is compiled for,
    # on a machine whose modes are compile flags (for_mode); None elsewhere
    mode: int | None = None
    # --- catalog attributes (catalog/toolchains.yaml; "" for an ad-hoc
    # test toolchain) ---
    family_id: str = ""
    version: str = ""
    label: str = ""            # the support tables' column name
    site_version: str = ""     # the version label the site shows
    site_pill: str = ""        # the issue list's version pill
    site_targets: tuple[str, ...] = ()  # the site columns it has cells in ("" = all of its GPU kind)
    site_plan_runs: bool = False
    site_root_var: str = ""
    site_gpus: str = ""
    merged_key: str | None = None  # its key in the merged result tables (dashboard, can-I-use)
    report_column: bool = True
    regression_of: str | None = None
    twin_of: str | None = None
    lane: str = ""
    canaries: str = ""         # its entry in catalog/canaries.yaml
    mention_words: tuple[str, ...] = ()  # words near the family name that pick this install
    install_root: str = ""     # the resolved install root ({root})
    install_roots: tuple[str, ...] = ()  # every root the recipe may name (default, fallback)
    install_env: str = ""      # the environment variable that overrides the root
    cxx: str = ""              # C++ compiler command (the hecbench campaign)

    @property
    def base(self) -> str:
        """The gfx942 toolchain name."""
        return base_name(self.name)

    @property
    def kind(self) -> str:
        """The recipe's vendor."""
        return self.vendor or ("afar" if self.base == "afar" else "cce")

    @property
    def family(self) -> Family:
        """The family of the recipe: the catalog's for a registered
        toolchain, else the family of its ``kind`` (ad-hoc test toolchains
        named like the AMD ones)."""
        reg = registry()
        if self.family_id in reg.families:
            return reg.families[self.family_id]
        return reg.family_of_kind(self.kind)

    def _machine(self):
        """The toolchain's machine in catalog/machines.yaml, None for a
        machine it does not list (ad-hoc test toolchains)."""
        from offload.engine.confirm.machines import load
        return load().get(self.machine)

    def compile_time_modes(self) -> bool:
        """Whether the memory mode is a compile flag (NVHPC)."""
        m = self._machine()
        return m is not None and m.compile_time_modes

    def for_mode(self, xnack: int) -> "Toolchain":
        """The toolchain compiled for mode `xnack` (a row key): itself when
        the machine selects modes at run time (AMD); with ``mode`` set (its
        compile flag added by ``flags``) when modes are compile flags."""
        if not self.compile_time_modes():
            return self
        if xnack not in self.xnack_modes:
            raise ValueError(f"{self.name} has no mode stored as {xnack} "
                             f"(its modes: {self.xnack_modes})")
        return self if self.mode == xnack else \
            dataclasses.replace(self, mode=xnack)

    def mode_flag(self) -> str:
        """The compile flag of the selected mode ("" for AMD). A toolchain
        whose modes are compile flags must have one selected."""
        if not self.compile_time_modes():
            return ""
        if self.mode is None:
            raise ValueError(f"{self.name}: its memory mode is a compile "
                             "flag: select one with for_mode(row key)")
        m = self._machine()
        return m.flags(m.mode_of_row_key(self.mode), self.kind)

    def _template_fields(self) -> dict:
        """The values a family's flag template may name."""
        fam = self.family
        fields = {"arch": self.arch, "cc": "", "target": "", "latomic": ""}
        if fam.kind == "nvhpc":
            cc = re.fullmatch(r"sm_(\d+)", self.arch)
            if cc is None:
                raise ValueError(f"{self.name}: arch {self.arch} is not sm_NN")
            fields["cc"] = cc.group(1)
        if fam.offload_targets:
            target = next((t for p, t in fam.offload_targets.items()
                           if self.arch.startswith(p)), None)
            if target is None:
                raise ValueError(f"{self.name}: no {fam.name} offload target "
                                 f"for {self.arch}")
            fields["target"] = target
            fields["latomic"] = fam.latomic.get(target, "")
        return fields

    def flags(self) -> str:
        """The fixed compile flags (without the optimisation level): the
        family's template for the model and language
        (catalog/toolchains.yaml ``flags``), the memory mode's compile flag
        where the mode is one, then `extra`. A (model, language)
        the family does not compile is refused with the catalog's reason."""
        fam = self.family
        lang = "c" if self.lang == "cpp" else self.lang     # C++ takes C's flags
        why = fam.why_unsupported(self.model, lang)
        if why:
            raise ValueError(why)
        tpl = (fam.flags.get(self.model) or {}).get(lang)
        if tpl is None:
            raise ValueError(f"{self.name}: {fam.name} has no flags for "
                             f"{self.model} {self.lang}")
        base = tpl.format(**self._template_fields())
        parts = [base, self.mode_flag(), self.extra]
        return " ".join(p for p in parts if p)

    def compiler(self) -> str:
        """The compiler command of the toolchain's language."""
        if self.lang == "cpp":
            if not self.cxx:
                raise ValueError(f"toolchain {self.name} has no C++ compiler")
            return self.cxx
        if self.lang == "c":
            if not self.cc:
                raise ValueError(f"toolchain {self.name} has no C compiler")
            return self.cc
        return self.fc

    def compile_cmd(self, src: str, out: str, opt: str = "-O2") -> str:
        cmd = f"{self.compiler()} {self.flags()} {opt} {src} -o {out}"
        return f"{self.prelude}\n{cmd}" if self.prelude else cmd

    def run_env(self, xnack: int) -> dict[str, str]:
        """The run-time environment of mode `xnack` (a row key): the
        machine's mode ``env`` (AMD: HSA_XNACK=<key>) and the toolchain's
        own. On a machine whose modes are compile flags the
        environment selects nothing, and a build for another mode is
        refused."""
        if xnack not in self.xnack_modes:
            raise ValueError(f"{self.name} runs at HSA_XNACK="
                             f"{self.xnack_modes} only, not {xnack}")
        m = self._machine()
        if m is None or not m.compile_time_modes:
            return {"HSA_XNACK": str(xnack), **dict(self.env)}
        if self.mode is not None and self.mode != xnack:
            raise ValueError(f"{self.name} was compiled for mode "
                             f"{self.mode}, not {xnack}")
        return {**m.env(m.mode_of_row_key(xnack)), **dict(self.env)}

    def targets(self) -> tuple[str, ...]:
        """The site's GPU/mode columns it has cells in: the catalog's
        ``site_targets``, else every target of its GPU vendor kind."""
        if self.site_targets:
            return self.site_targets
        reg = registry()
        gpu = reg.arches[self.arch]["gpu"]
        return tuple(t for t, g in reg.target_kinds().items() if g == gpu)

    def public(self, text: str) -> str:
        """`text` with the install paths in their public form (the site's
        command lines: ``$AFAR/bin/``, a bare ``nvfortran``, ``$GCC_16_2``;
        catalog/toolchains.yaml ``site_public``)."""
        for root in self.install_roots:
            fields = _root_fields(root)
            fields["var"] = self.site_root_var
            pairs = [(tpl.format(**fields), pub.format(**fields))
                     for tpl, pub in self.family.site_public.items()]
            for path, pub in sorted(pairs, key=lambda kv: -len(kv[0])):
                text = text.replace(path, pub)
        return text


def _root_fields(root: str) -> dict:
    """The placeholders an install root fills in a recipe template."""
    p = Path(root)
    return {"root": root, "root_dir": str(p.parent),
            "root_grandparent": str(p.parent.parent)}


class Registry:
    """The checked contents of catalog/toolchains.yaml."""

    def __init__(self, data: dict, environ=None):
        if data.get("version") != 1:
            raise ValueError("toolchains: unknown version")
        self.environ = os.environ if environ is None else environ
        self.arches: dict[str, dict] = dict(data.get("arches") or {})
        self.site: dict = dict(data.get("site") or {})
        self.lane_docs: dict[str, str] = dict(data.get("lanes") or {})
        # machine -> the directory a campaign's private copy of the tree
        # goes under (tools/jobs/campaign_remote.sh)
        self.campaign_lanes: dict[str, str] = dict(data.get("campaign_lanes") or {})
        # machine -> {max_minutes, hosts}: the interactive-queue rules a
        # foreground job of a campaign obeys (tools/campaign.py submit)
        self.pdebug: dict[str, dict] = {k: dict(v) for k, v in
                                        (data.get("pdebug") or {}).items()}
        self.families: dict[str, Family] = {}
        for fid, d in (data.get("families") or {}).items():
            self.families[fid] = self._family(fid, d)
        self.toolchains: dict[str, Toolchain] = {}
        for name, d in (data.get("toolchains") or {}).items():
            self.toolchains[name] = self._toolchain(name, d)
        self._check()

    # --- construction -------------------------------------------------

    def _family(self, fid: str, d: dict) -> Family:
        for key in ("name", "long_name", "kind", "message_table", "compile_s"):
            if key not in d:
                raise ValueError(f"toolchains: family {fid}: no {key}")
        if not d.get("flags"):
            raise ValueError(f"toolchains: family {fid}: no flags")
        return Family(
            fid, d["name"], d["long_name"], d.get("site_name") or d["long_name"],
            d.get("vendor"), d["kind"], d["message_table"], float(d["compile_s"]),
            {m: dict(v) for m, v in d["flags"].items()},
            dict(d.get("unsupported") or {}), d.get("prelude") or "",
            d.get("fc") or "", d.get("cc") or "", d.get("cxx") or "",
            {int(k): v for k, v in (d.get("version_flags") or {}).items()},
            bool(d.get("c_version_flag")), dict(d.get("offload_targets") or {}),
            dict(d.get("latomic") or {}), d.get("under_test_only") or "",
            d.get("witness") or "", d.get("site_gpus") or "",
            dict(d.get("site_public") or {}), bool(d.get("site_runtime_env")))

    def _toolchain(self, name: str, d: dict) -> Toolchain:
        for key in ("family", "version", "machine", "arch", "modes"):
            if key not in d:
                raise ValueError(f"toolchains: {name}: no {key}")
        fam = self.families.get(d["family"])
        if fam is None:
            raise ValueError(f"toolchains: {name}: unknown family {d['family']}")
        if d["arch"] not in self.arches:
            raise ValueError(f"toolchains: {name}: unknown arch {d['arch']}")
        inst = d.get("install") or {}
        roots = []
        root = ""
        if inst:
            default = str(inst["default"])
            roots.append(default)
            root = default
            if inst.get("fallback"):
                roots.append(str(inst["fallback"]))
                root = _afar_bin(default, str(inst["fallback"]))
            if inst.get("env"):
                root = self.environ.get(inst["env"], root)
        fields = _root_fields(root) if root else {}
        mods = {k: str(v) for k, v in (d.get("modules") or {}).items()}
        fields.update(mods)
        fields["arch"] = d["arch"]

        def fill(s: str) -> str:
            try:
                return s.format(**fields) if s else s
            except KeyError as e:
                raise ValueError(f"toolchains: {name}: the recipe names {{{e.args[0]}}}: "
                                 "give it in `modules` (or `install`)") from None
        prelude = d.get("prelude") if "prelude" in d else fam.prelude
        fc = d.get("fc") or fam.fc
        cc = d.get("cc") or fam.cc
        cxx = d.get("cxx") or fam.cxx
        env = tuple((k, fill(str(v))) for k, v in (d.get("env") or {}).items())
        modes = tuple(d["modes"])
        row_keys = self._row_keys(name, d["machine"], modes)
        return Toolchain(
            name, fill(prelude or ""), fill(fc), cc=fill(cc), cxx=fill(cxx), arch=d["arch"],
            machine=d["machine"], env=env, xnack_modes=row_keys,
            vendor=fam.kind, family_id=fam.id, version=str(d["version"]),
            label=d.get("label") or "", site_version=str(d.get("site_version") or d["version"]),
            site_pill=str(d.get("site_pill") or d.get("site_version") or d["version"]),
            site_targets=tuple(d.get("site_targets") or ()),
            site_plan_runs=bool(d.get("site_plan_runs")),
            site_root_var=d.get("site_root_var") or "",
            site_gpus=d.get("site_gpus") or fam.site_gpus,
            merged_key=d.get("merged_key"), report_column=d.get("report_column", True),
            regression_of=d.get("regression_of"), twin_of=d.get("twin_of"),
            lane=d.get("lane") or "", canaries=d.get("canaries") or name,
            mention_words=tuple(d.get("mention_words") or ()),
            install_root=root, install_roots=tuple(roots),
            install_env=inst.get("env") or "")

    def _row_keys(self, name: str, machine: str, modes: tuple) -> tuple[int, ...]:
        """The stored row keys of the machine's modes, ascending."""
        from offload.engine.confirm.machines import load
        m = load().get(machine)
        if m is None:  # reported by check_registry
            return ()
        for mode in modes:
            if not m.has(mode):
                raise ValueError(f"toolchains: {name}: {machine} has no "
                                 f"{mode} mode")
        return tuple(sorted(m.row_key(x) for x in modes))

    def _check(self) -> None:
        for name, tc in self.toolchains.items():
            if tc.twin_of is not None and tc.twin_of not in self.toolchains:
                raise ValueError(f"toolchains: {name}: twin_of {tc.twin_of} "
                                 "is not a toolchain")
            if tc.regression_of is not None and \
                    tc.regression_of not in self.toolchains:
                raise ValueError(f"toolchains: {name}: regression_of "
                                 f"{tc.regression_of} is not a toolchain")
            if tc.twin_of is not None and name not in self._twin_names(tc):
                raise ValueError(f"toolchains: {name}: a twin of {tc.twin_of} on "
                                 f"{tc.machine} is named "
                                 f"{' or '.join(self._twin_names(tc))}")
            if tc.twin_of is None and tc.regression_of is None and not tc.label:
                raise ValueError(f"toolchains: {name}: no label")
            if tc.lane and tc.lane not in self.lane_docs:
                raise ValueError(f"toolchains: {name}: lane {tc.lane} is not described "
                                 f"under `lanes:` (known: {', '.join(self.lane_docs)})")

    def _twin_names(self, tc: Toolchain) -> tuple[str, ...]:
        """The names a twin may have: its base and the arch's suffix (gfx90a), or its base
        and its machine (an arch without a suffix, or another machine of the arch)."""
        suffix = self.arches[tc.arch].get("twin_suffix")
        return tuple(f"{tc.twin_of}{s}" for s in (suffix, f"_{tc.machine}") if s)

    # --- the lists --------------------------------------------------------

    def family_of(self, name: str) -> Family | None:
        tc = self.toolchains.get(name)
        return self.families.get(tc.family_id) if tc is not None else None

    def family_of_kind(self, kind: str) -> Family:
        for fam in self.families.values():
            if fam.kind == kind:
                return fam
        raise KeyError(f"no compiler family of kind {kind}")

    def message_table(self, name: str) -> str:
        """The message-table key of a toolchain (``family()``): its
        family's; for a name the catalog does not know, the family whose
        id prefixes the name (test toolchains named like the real ones),
        else the name itself."""
        base = base_name(name)
        fam = self.family_of(base)
        if fam is None:
            fam = next((f for f in self.families.values()
                        if base.startswith(f.id)), None)
        return fam.message_table if fam is not None else base

    def label(self, name: str) -> str:
        """The support-table column name: the catalog's label, a twin's
        ``<base label> <arch>``."""
        tc = self.toolchains[name]
        if tc.label:
            return tc.label
        if tc.twin_of:
            if self.twin_tag(name) == tc.arch:
                return f"{self.label(tc.twin_of)} {tc.arch}"
            from offload.engine.confirm.machines import load
            return f"{self.label(tc.twin_of)} {load()[tc.machine].device.split()[-1]}"
        return name

    def headline(self) -> tuple[str, ...]:
        """The toolchains that are neither a twin nor a regression release,
        in catalog order (the site's toolchains)."""
        return tuple(n for n, t in self.toolchains.items()
                     if t.twin_of is None and t.regression_of is None)

    def site_toolchains(self) -> tuple[str, ...]:
        """The toolchains the site has cells for: every one that is not an
        arch twin (the site keys cells by machine)."""
        return tuple(n for n, t in self.toolchains.items() if t.twin_of is None)

    def of_arch(self, arch: str) -> tuple[str, ...]:
        """The toolchains of `arch` that are neither twins on another machine of the arch
        nor regression releases."""
        return tuple(n for n, t in self.toolchains.items() if t.arch == arch
                     and t.regression_of is None
                     and not (t.twin_of and self.toolchains[t.twin_of].arch == arch))

    def of_gpu(self, gpu: str) -> tuple[str, ...]:
        """The report columns of the machines with GPUs of `gpu` (amd,
        nvidia), twins and regression releases left out."""
        return tuple(n for n, t in self.toolchains.items()
                     if self.arches[t.arch]["gpu"] == gpu and t.report_column
                     and t.twin_of is None and t.regression_of is None)

    def of_family(self, fid: str) -> tuple[str, ...]:
        return tuple(n for n, t in self.toolchains.items() if t.family_id == fid)

    def of_machine(self, machine: str) -> tuple[str, ...]:
        """The measured toolchains of a machine (a regression release is
        not one): catalog/machines.yaml's former ``toolchains`` lists."""
        return tuple(n for n, t in self.toolchains.items()
                     if t.machine == machine and t.regression_of is None)

    def of_lane(self, lane: str) -> tuple[str, ...]:
        return tuple(n for n, t in self.toolchains.items() if t.lane == lane)

    def lanes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(t.lane for t in self.toolchains.values() if t.lane))

    def lane_doc(self, lane: str) -> str:
        """Which scripts run a lane (catalog ``lanes``); a lane the catalog
        does not describe is refused by the check below."""
        return self.lane_docs.get(lane, "")

    def regression(self) -> dict[str, str]:
        return {n: t.regression_of for n, t in self.toolchains.items()
                if t.regression_of is not None}

    def twins(self) -> dict[str, str]:
        return {n: t.twin_of for n, t in self.toolchains.items() if t.twin_of}

    def twins_of(self, name: str) -> tuple[str, ...]:
        """The twins of `name`, in catalog order."""
        return tuple(n for n, t in self.toolchains.items() if t.twin_of == name)

    def base_of(self, name: str) -> str:
        """The toolchain a twin is the twin of (a name the catalog does not
        know: ``base_name``'s suffix rule)."""
        t = self.toolchains.get(name)
        if t is None:
            return base_name(name)
        return t.twin_of or name

    def twin_key(self, name: str) -> str:
        """What a twin's name adds to its base's ("_g90", "_mi300x"; "" for a
        toolchain that is no twin)."""
        t = self.toolchains[name]
        return name[len(t.twin_of):] if t.twin_of else ""

    def twin_tag(self, name: str) -> str:
        """How the support tables name a twin's GPU: the arch for a twin named
        with the arch's suffix (gfx90a), else its machine (mi300x)."""
        t = self.toolchains[name]
        suffix = self.arches[t.arch].get("twin_suffix")
        return t.arch if suffix and self.twin_key(name) == suffix else t.machine

    def machine_twins(self) -> frozenset:
        """The twins named after their machine (afar_mi300x, gcc_mi350x): support-table cells
        only, outside the evidence machines (MI300A, MI250X, the A100)."""
        return frozenset(n for n, t in self.toolchains.items()
                         if t.twin_of and self.twin_tag(n) == t.machine)

    def table_only(self) -> frozenset:
        """The toolchains whose rows are support-table cells only, never
        evidence (the confirmer, the expected values): the machine twins
        and the toolchains of a family under test only (GCC)."""
        return self.machine_twins() | frozenset(
            n for n, t in self.toolchains.items() if t.family_id in self.under_test_only())

    def twin(self, name: str, arch: str) -> str | None:
        """The twin of `name` on `arch`, if the catalog has one."""
        return next((n for n, t in self.toolchains.items()
                     if t.twin_of == name and t.arch == arch), None)

    def merged(self) -> tuple[str, ...]:
        """The headline toolchains with a key in the merged result tables."""
        return tuple(n for n in self.headline() if self.toolchains[n].merged_key)

    def in_merged(self, name: str) -> bool:
        """Whether a toolchain's rows are in the merged result files: it,
        or the toolchain it is the twin of, has a ``merged_key``."""
        t = self.toolchains[name]
        base = self.toolchains[t.twin_of] if t.twin_of else t
        return bool(base.merged_key)

    def under_test_only(self) -> dict[str, str]:
        return {f.id: f.under_test_only for f in self.families.values()
                if f.under_test_only}

    def versions(self) -> dict[str, tuple[str, str, int]]:
        """toolchain -> (family, site version label, release order within
        the family) for the site's toolchains (offload.engine.site.matrix
        VERSIONS): the order is the version's rank among the family's
        distinct versions in catalog order."""
        out = {}
        seen: dict[str, list] = {}
        for n in self.site_toolchains():
            t = self.toolchains[n]
            vs = seen.setdefault(t.family_id, [])
            if t.version not in vs:
                vs.append(t.version)
            out[n] = (t.family_id, t.site_version, vs.index(t.version))
        return out

    def targets(self) -> dict[tuple[str, str], str]:
        """(machine, mode row key as text) -> the site's target id
        (catalog/machines.yaml ``modes.<mode>.target``), machines and
        modes in file order."""
        from offload.engine.confirm.machines import load
        out = {}
        for m in load().values():
            for mode in m.modes:
                t = m.mode_table[mode].get("target")
                if t:
                    out[(m.name, str(m.row_key(mode)))] = t
        return out

    def run_targets(self, name: str) -> tuple[str, ...]:
        """The site targets a toolchain and its twins were measured on (their
        machines' modes; the catalog's ``site_targets`` where it has them): the
        feature-support cells it can have, any other being n/a."""
        if self.toolchains[name].site_targets:
            return self.toolchains[name].site_targets
        ran = {(t.machine, str(x)) for t in (self.toolchains[n] for n in (name, *self.twins_of(name)))
               for x in t.xnack_modes}
        return tuple(t for k, t in self.targets().items() if k in ran)

    def target_kinds(self) -> dict[str, str]:
        """target id -> GPU vendor kind of its machine."""
        from offload.engine.confirm.machines import load
        out = {}
        for m in load().values():
            for mode in m.modes:
                t = m.mode_table[mode].get("target")
                if t:
                    out[t] = self.arches[m.arch]["gpu"]
        return out

    def family_order(self) -> tuple[str, ...]:
        """The site's family order (the first is the default family)."""
        return tuple(self.site.get("family_order") or self.families)

    def install_roots(self) -> tuple[str, ...]:
        """Every install root a recipe may name, unique, in catalog order."""
        return tuple(dict.fromkeys(r for t in self.toolchains.values()
                                   for r in t.install_roots))

    def arch_machines(self) -> dict[str, str]:
        from offload.engine.confirm.machines import load
        out: dict[str, str] = {}
        for m in load().values():
            out.setdefault(m.arch, m.name)       # the first machine of an arch, when several share its ISA
        return out


def load(path: Path | str | None = None, environ=None) -> Registry:
    """The registry of `path` (default: the catalog, or the file
    ``COMPLIANT_TOOLCHAINS`` names)."""
    p = Path(path or os.environ.get(CATALOG_ENV) or CATALOG)
    data = yaml.safe_load(p.read_text()) or {}
    if p == CATALOG:
        data = localcfg.overlay("toolchains.yaml", data)
    return Registry(data, environ)


@lru_cache(maxsize=None)
def _registry(path: str) -> Registry:
    return load(path)


def registry() -> Registry:
    """The registry in use (cached per catalog path)."""
    return _registry(str(os.environ.get(CATALOG_ENV) or CATALOG))


def reset() -> None:
    """Forget the cached registry (tests that point COMPLIANT_TOOLCHAINS at
    another catalog, then reload the consumer modules)."""
    _registry.cache_clear()
    import sys
    fi = sys.modules.get("offload.engine.confirm.findings")
    if fi is not None:
        fi.front_end.cache_clear()


_R = registry()
TOOLCHAINS: dict[str, Toolchain] = dict(_R.toolchains)
# the device of each arch (``device_of``), the machine of each arch and the
# toolchain-name suffix of an arch's twin toolchains ("" for gfx942)
DEVICES = {a: d["device"] for a, d in _R.arches.items()}
MACHINES = _R.arch_machines()
ARCH_SUFFIX = {a: d["twin_suffix"] for a, d in _R.arches.items()
               if "twin_suffix" in d}
DEVICE = DEVICES[next(iter(ARCH_SUFFIX))]  # the target device of Tuolumne runs
# the gfx942 headline toolchains of the families that witness for each other
# (a family under test only, GCC, is left out: the fuzz, stress and widened
# campaigns' targets) and their gfx90a twins
GFX942_TOOLCHAINS = tuple(t for t in _R.of_arch("gfx942")
                          if _R.toolchains[t].family_id not in _R.under_test_only())
GFX90A_TOOLCHAINS = tuple(_R.twin(t, "gfx90a") for t in GFX942_TOOLCHAINS
                          if _R.twin(t, "gfx90a"))
# Toolchains measured only by regression mode (tools/confirm.py
# regress), each with the headline toolchain it is compared with. They are
# never headline columns and their rows go to results/confirm/regress/
REGRESSION_TOOLCHAINS = _R.regression()
GCC_TOOLCHAINS = _R.of_family("gcc")
# the toolchains of other machines than the AMD ones (support-table
# columns of their own; offload.engine.report): the NVIDIA machine's
NVIDIA_TOOLCHAINS = _R.of_gpu("nvidia")
# the install roots other modules name directly: AFAR's front end is the
# legality pre-check's (offload.engine.prerun), its /p/vast1 copy serves Tioga
AFAR_BIN = f"{TOOLCHAINS['afar'].install_root}/bin"
AFAR_VAST = TOOLCHAINS["afar_g90"].install_root
AFAR_BIN_G90 = f"{AFAR_VAST}/bin"
NVHPC_BIN = TOOLCHAINS["nvhpc"].install_root
NVHPC269_BIN = TOOLCHAINS["nvhpc269"].install_root
GCC_G90_ROOT = TOOLCHAINS["gcc_g90"].install_root
GCC_SM80_ROOT = TOOLCHAINS["gcc_sm80"].install_root
GCC_VERSION = TOOLCHAINS["gcc_sm80"].version
# C: the OpenMP C flags of the AMD recipe kinds on gfx942
# (offload.engine.run_matrix; tests)
C_FLAGS = {k: _R.family_of_kind(k).flags["omp"]["c"].format(arch="gfx942")
           for k in ("afar", "cce")}


def install_roots() -> tuple[str, ...]:
    """Every compiler install root of the catalog (paths to scrub from
    recorded messages)."""
    return registry().install_roots()


@lru_cache(maxsize=None)
def base_name(name: str) -> str:
    """The toolchain a twin is the twin of (``cce21_g90``, ``afar_mi300x`` -> ``cce21``,
    ``afar``); a name the catalog does not know loses an arch's twin suffix."""
    tc = TOOLCHAINS.get(name)
    if tc is not None:
        return tc.twin_of or name
    for suffix in ARCH_SUFFIX.values():
        if suffix and name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def arch_of(name: str) -> str:
    """The arch of a registered toolchain (``TOOLCHAINS``). A name the registry does not know raises KeyError (it used to
    default to gfx942, so an unregistered toolchain's rows were recorded
    as MI300A rows)."""
    tc = TOOLCHAINS.get(name)
    if tc is not None:
        return tc.arch
    raise KeyError(f"unknown toolchain {name}: register it in "
                   "catalog/toolchains.yaml (docs/tooling/contributing.md, "
                   "\"Add a compiler\")")


def device_of(tc: Toolchain) -> str:
    """The target device of a toolchain's runs."""
    return DEVICES[tc.arch]


def parse_rocminfo(text: str) -> tuple[str, str]:
    """(gfx name, marketing name) of the first GPU agent in rocminfo's
    output; ("", "") if none."""
    m = re.search(r"^\s*Name:\s+(gfx[0-9a-f]+)\s*$", text, re.M)
    if m is None:
        return "", ""
    # the agent's marketing name follows its name, before the next agent
    rest = text[m.end():]
    nxt = re.search(r"^\s*Name:", rest, re.M)
    mk = re.search(r"^\s*Marketing Name:\s+(\S.*?)\s*$",
                   rest[:nxt.start()] if nxt else rest, re.M)
    return m.group(1), mk.group(1) if mk else ""


def gpu_count(text: str) -> int:
    """The number of GPU agents in rocminfo's output (the devices a run
    sees; ROCR_VISIBLE_DEVICES filters them)."""
    return len(re.findall(r"^\s*Name:\s+gfx[0-9a-f]+\s*$", text, re.M))


def detect_gpu_count() -> int | None:
    """GPU agents visible to this process per rocminfo (else the
    NVIDIA GPUs per nvidia-smi, narrowed by CUDA_VISIBLE_DEVICES), None
    without either."""
    for exe in ["/opt/rocm/bin/rocminfo"] + sorted(
            str(p) for p in Path("/opt").glob("rocm-*/bin/rocminfo"))[::-1]:
        if Path(exe).is_file():
            try:
                res = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=60)
            except (subprocess.SubprocessError, OSError):
                continue
            return gpu_count(res.stdout)
    gpus = _nvidia_gpus()
    if gpus is None:
        return None
    return len(visible_nvidia(gpus, os.environ.get("CUDA_VISIBLE_DEVICES")))


NVIDIA_SMI = "nvidia-smi"
_NV_QUERY = ["--query-gpu=index,uuid,compute_cap,name",
             "--format=csv,noheader"]


def parse_nvidia_smi(text: str) -> list[tuple[str, str, str, str]]:
    """(index, uuid, sm arch, name) per GPU of ``nvidia-smi
    --query-gpu=index,uuid,compute_cap,name --format=csv,noheader``
: compute capability 8.0 is ``sm_80``."""
    out = []
    for line in text.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 4 or not re.fullmatch(r"\d+\.\d+", parts[2]):
            continue
        out.append((parts[0], parts[1], "sm_" + parts[2].replace(".", ""),
                    ", ".join(parts[3:])))
    return out


def visible_nvidia(gpus: list, cuda_visible: str | None) -> list:
    """The GPUs a CUDA process sees: CUDA_VISIBLE_DEVICES (indices or
    UUIDs, in its order; nvidia-smi itself ignores it) narrows the list."""
    if cuda_visible is None:
        return list(gpus)
    out = []
    for tok in (t.strip() for t in cuda_visible.split(",")):
        if not tok:
            break
        hit = [g for g in gpus if tok == g[0] or g[1].startswith(tok)]
        if not hit:  # CUDA stops at the first invalid entry
            break
        out.append(hit[0])
    return out


def _nvidia_gpus() -> list | None:
    try:
        res = subprocess.run([NVIDIA_SMI, *_NV_QUERY], capture_output=True,
                             text=True, timeout=60)
    except (subprocess.SubprocessError, OSError):
        return None
    if res.returncode != 0:
        return None
    return parse_nvidia_smi(res.stdout)


def detect_gpu() -> tuple[str, str]:
    """(gfx name, marketing name) of this node's first GPU per rocminfo
    (recorded in every result row); without rocminfo,
    (sm arch, name) of the first visible NVIDIA GPU per nvidia-smi; ("",
    "") without a GPU or either tool. Cached."""
    if _GPU:
        return _GPU[0]
    found = ("", "")
    cands = ["/opt/rocm/bin/rocminfo"] + sorted(
        str(p) for p in Path("/opt").glob("rocm-*/bin/rocminfo"))[::-1]
    for exe in cands:
        if not Path(exe).is_file():
            continue
        try:
            res = subprocess.run([exe], capture_output=True, text=True,
                                 timeout=60)
        except (subprocess.SubprocessError, OSError):
            continue
        found = parse_rocminfo(res.stdout)
        if found[0]:
            break
    if not found[0]:  # An NVIDIA node (nvidia-smi)
        vis = visible_nvidia(_nvidia_gpus() or [],
                             os.environ.get("CUDA_VISIBLE_DEVICES"))
        if vis:
            found = (vis[0][2], vis[0][3])
    _GPU.append(found)
    return found


_GPU: list[tuple[str, str]] = []

_TRIPLE = re.compile(rb"amdgcn-amd-amdhsa--gfx[0-9a-f]+(?::[a-z]+[+-])*")


def code_object_targets(data: bytes) -> list[str]:
    """The AMDGPU code-object target ids (``amdgcn-amd-amdhsa--gfx90a``,
    with ``:xnack-``/``:xnack+`` when the code object is not "xnack any")
    named in an executable's bytes, sorted and unique (run
    metadata; AFAR's packaged images are read with llvm-objdump
    --offloading instead)."""
    return sorted({m.decode() for m in _TRIPLE.findall(data)})


# GCC's offload image for AMD is an AMDGPU ELF code object embedded in the
# host executable; its e_flags name the GPU (EF_AMDGPU_MACH, the low byte;
# gcc/config/gcn/gcn-devices.def) and the xnack setting (code object v4+:
# 0x100 any, 0x200 off, 0x300 on)
_GCN_MACH = {0x30: "gfx908", 0x3f: "gfx90a", 0x4c: "gfx942", 0x4f: "gfx950"}
_EM_AMDGPU = 224


def gcn_targets(data: bytes) -> list[str]:
    """The target ids (``amdgcn-amd-amdhsa--gfx90a``, ``:xnack-``/
    ``:xnack+`` when not "any") of the AMDGPU ELF code objects embedded in
    an executable's bytes (GCC's offload images), sorted and unique."""
    import struct
    out = set()
    i = data.find(b"\x7fELF")
    while i >= 0:
        if len(data) >= i + 52 and data[i + 4] == 2 and data[i + 5] == 1:
            machine, = struct.unpack_from("<H", data, i + 18)
            flags, = struct.unpack_from("<I", data, i + 48)
            if machine == _EM_AMDGPU:
                mach = _GCN_MACH.get(flags & 0xff, f"mach{flags & 0xff:#x}")
                xn = {0x200: ":xnack-", 0x300: ":xnack+"}.get(
                    flags & 0x300, "")
                out.add(f"amdgcn-amd-amdhsa--{mach}{xn}")
        i = data.find(b"\x7fELF", i + 1)
    return sorted(out)


def parse_nvhpc_cuda(dryrun: str) -> str:
    """The CUDA version an NVHPC compile uses, from its -dryrun output
    (the bundled toolkit path ``.../cuda/<X.Y>/...``); "" if none."""
    found = re.findall(r"/cuda/(\d+\.\d+)\b", dryrun)
    return found[0] if found else ""


def nvhpc_cuda(tc, workdir) -> str:
    """The default CUDA of an NVHPC toolchain (recorded
    in the toolchain metadata), from -dryrun of the smoke program."""
    res = subprocess.run(["bash", "-c", tc.compile_cmd(
        str(_DEV_F90), str(Path(workdir) / "dryrun.out")).replace(
        " -o ", " -dryrun -o ", 1)], capture_output=True, text=True,
        timeout=300, cwd=workdir)
    return parse_nvhpc_cuda(res.stdout + res.stderr)


_SM = re.compile(rb"\bsm_[0-9]{2,3}[af]?\b")


def nvidia_targets(data: bytes) -> list[str]:
    """The sm_NN arches named in an NVHPC executable's embedded
    device images, sorted and unique."""
    return sorted({m.decode() for m in _SM.findall(data)})


def loaded_rocm_version(tc: Toolchain) -> str | None:
    """ROCm version the toolchain's prelude loads, or None if it loads none."""
    if not any(t == "rocm" or t.startswith("rocm/")
               for t in tc.prelude.split()):
        return None
    res = subprocess.run(
        ["bash", "-c", f'{{ {tc.prelude}\n}} >/dev/null 2>&1 && echo "$ROCM_PATH"'],
        capture_output=True, text=True, check=True)
    m = re.search(r"rocm-(\d+\.\d+(?:\.\d+)?)", res.stdout)
    return m.group(1) if m else None


def compiler_version(tc: Toolchain) -> str:
    """The compiler's version banner (its first line, plus CCE's target line
    when there is one), run through the toolchain's prelude; "" if the
    compiler cannot be run. C toolchains report the C compiler's
    banner ("AMD clang version ...", "Cray clang version ...")."""
    key = tc.name if tc.lang != "c" else f"{tc.name}:c"
    cached = _VERSIONS.get(key)
    if cached is not None:
        return cached
    try:
        res = subprocess.run(
            ["bash", "-c", f"{{ {tc.prelude or 'true'}\n}} >/dev/null 2>&1; "
                           f"{tc.compiler()} --version 2>&1"],
            capture_output=True, text=True, timeout=120)
        lines = [ln.strip() for ln in res.stdout.splitlines()
                 if ln.strip().startswith(("AMD flang", "Cray Fortran",
                                           "AMD clang", "Cray clang",
                                           "nvfortran ", "nvc ",
                                           "GNU Fortran (GCC)",
                                           "gcc (GCC)"))]
        out = " | ".join(lines)
    except (subprocess.SubprocessError, OSError):
        out = ""
    _VERSIONS[key] = out
    return out


_VERSIONS: dict[str, str] = {}


def parse_module_list(text: str) -> list[str]:
    """The module names of ``module -t list`` output."""
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.rstrip().endswith(":")
            and " " not in ln.strip()]


_DEV_F90 = ROOT / "tests" / "data" / "dev.f90"


def toolchain_meta(tc: Toolchain, workdir: Path) -> dict:
    """Run metadata of a toolchain: its machine, arch and device,
    the modules its prelude leaves loaded (``module -t list``) and the
    code-object target ids of a compiled smoke program (tests/data/dev.f90;
    AFAR's offload images through its llvm-objdump --offloading, CCE's
    triples from the executable's bytes). The compilers' default code
    objects are "xnack any": no ``:xnack`` feature in the id."""
    import dataclasses
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    out: dict = {"name": tc.name, "machine": tc.machine, "arch": tc.arch,
                 "device": device_of(tc), "modules": [], "code_object": []}
    if "module " in tc.prelude:
        res = subprocess.run(
            ["bash", "-c", f"{{ {tc.prelude}\n}} >/dev/null 2>&1; "
                           "module -t list 2>&1"],
            capture_output=True, text=True, timeout=120)
        out["modules"] = parse_module_list(res.stdout)
    f = dataclasses.replace(tc, lang="f90", model="omp")
    if f.compile_time_modes():  # Built for its headline mode
        m = f._machine()
        f = f.for_mode(m.row_key(m.headline_mode))
    exe = workdir / f"{tc.name}.meta.out"
    res = subprocess.run(["bash", "-c", f.compile_cmd(str(_DEV_F90),
                                                      str(exe))],
                         capture_output=True, text=True, timeout=600,
                         cwd=workdir)
    if res.returncode != 0 or not exe.is_file():
        out["code_object_error"] = (res.stdout + res.stderr)[-400:]
        return out
    found = code_object_targets(exe.read_bytes())
    if tc.kind == "gcc" and tc.arch.startswith("gfx"):  # embedded ELF
        found = gcn_targets(exe.read_bytes())
    if tc.kind == "nvhpc" or tc.arch.startswith("sm_"):  # The
        found = nvidia_targets(exe.read_bytes())  # embedded images' arch
    objdump = Path(tc.fc).parent.parent / "lib" / "llvm" / "bin" / \
        "llvm-objdump"
    if tc.base == "afar" and objdump.is_file():
        r = subprocess.run([str(objdump), "--offloading", str(exe)],
                           capture_output=True, text=True, timeout=120)
        arches = re.findall(r"^arch\s+(\S+)", r.stdout, re.M)
        triples = re.findall(r"^triple\s+(\S+)", r.stdout, re.M)
        found += [f"{t} {a}" for t, a in zip(triples, arches)]
    out["code_object"] = found
    if tc.kind == "nvhpc":  # The CUDA the compiler picks
        out["cuda"] = nvhpc_cuda(f, workdir)
        # The runtime the runs load (LD_LIBRARY_PATH)
        out["runtime_libs"] = dict(tc.env).get("LD_LIBRARY_PATH", "")
    if tc.kind == "gcc":  # the release's runtime (and ROCm's HSA)
        out["runtime_libs"] = dict(tc.env).get("LD_LIBRARY_PATH", "")
    return out



def family(name: str) -> str:
    """The message-table key of a toolchain (catalog/toolchains.yaml
    ``families.<f>.message_table``): every CCE release shares the tables
    captured from CCE 19."""
    return registry().message_table(name)


def check_registry(reg: Registry | None = None) -> list[str]:
    """The toolchain registry against the machines
    (catalog/machines.yaml), the support-table columns (offload.engine.report)
    and the canaries (catalog/canaries.yaml). Returns the problems (empty
    when consistent); a new toolchain fails here until every place that
    must know it does."""
    from offload.engine.confirm.machines import load
    from offload.engine import canary
    reg = reg or registry()
    machines = load()
    twins = {w for t in reg.of_arch("gfx942") for w in reg.twins_of(t)}
    columns = set(reg.of_arch("gfx942")) | twins | set(reg.of_gpu("nvidia")) | \
        {n for n, t in reg.toolchains.items() if not t.report_column}
    canaries = set((canary.load().get("toolchains") or {}))
    out = []
    for name, tc in reg.toolchains.items():
        m = machines.get(tc.machine)
        if m is None:
            out.append(f"{name}: machine {tc.machine} is not in "
                       "catalog/machines.yaml")
        elif m.arch != tc.arch:
            out.append(f"{name}: arch {tc.arch}, machine {m.name} is "
                       f"{m.arch}")
        if tc.canaries not in canaries:
            out.append(f"{name}: no canaries in catalog/canaries.yaml "
                       f"(entry {tc.canaries}: the five kinds, measured)")
        if not tc.lane:
            out.append(f"{name}: no lane (which run scripts run it)")
        if name in reg.regression():
            continue
        if m is not None and name not in m.toolchains:
            out.append(f"{name}: not in machines.yaml {m.name} toolchains")
        if name not in columns:
            out.append(f"{name}: not a support-table column "
                       "(offload.engine.report.ALL_TOOLCHAINS)")
    for m in machines.values():
        for name in m.toolchains:
            if name not in reg.toolchains:
                out.append(f"machines.yaml {m.name}: toolchain {name} is "
                           "not registered")
    return out
