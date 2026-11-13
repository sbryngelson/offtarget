"""Machines and memory modes (catalog/machines.yaml).

A memory mode is ``unified``, ``copy`` or ``managed``; a machine
declares the modes it has, how each is selected (``env``: a run-time
environment, the AMD HSA_XNACK; ``flags``: a compile flag, NVHPC's
``-gpu=mem:...``), the value result rows store for it (``row_key``, the
rows' ``xnack`` field), its headline mode, its scheduler and how it is
reached (``access``: ``local`` or ``{ssh, root}``). ``not_applicable``
records a mode the machine cannot run and why (machine data, not a
failure). Rules use modes only; a mode a machine lacks raises
``NotApplicable``, which collectors turn into ``not_applicable``
evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from offload.engine import localcfg
from offload.engine.root import ROOT  # noqa: E402
MACHINES_FILE = ROOT / "catalog" / "machines.yaml"
# ``managed`` (NVHPC -gpu=mem:managed: dynamically allocated data
# in CUDA managed memory, everything else copied) is neither unified nor
# copy; no rule names it, so the mode rules never fire on it
MODES = ("unified", "copy", "managed")


class NotApplicable(Exception):
    """The machine has no such mode (or arch): not a failure, no evidence
    is missing."""


@dataclass(frozen=True)
class Machine:
    name: str
    arch: str
    device: str
    access: object
    scheduler: dict
    headline_mode: str
    mode_table: dict = field(default_factory=dict)
    # the toolchains the data lists (test data); the committed machines
    # take theirs from catalog/toolchains.yaml (``toolchains``)
    listed_toolchains: tuple | None = None
    # Modes the machine cannot run, with the reason (data)
    not_applicable: dict = field(default_factory=dict)
    # the gate's environment (c) is another GPU of this one shared host
    one_host: bool = False
    # whether the site plans its finding-matrix runs here (a toolchain's
    # ``site_plan_runs`` overrides)
    site_plan_runs: bool = True

    @property
    def toolchains(self) -> tuple:
        """The measured toolchains of the machine (a regression-only
        toolchain is not one): catalog/toolchains.yaml, unless the data
        lists them."""
        if self.listed_toolchains is not None:
            return self.listed_toolchains
        from offload.engine.toolchains import registry
        return registry().of_machine(self.name)

    @property
    def modes(self) -> tuple[str, ...]:
        return tuple(m for m in MODES if m in self.mode_table)

    def has(self, mode: str) -> bool:
        return mode in self.mode_table

    def env(self, mode: str) -> dict[str, str]:
        if not self.has(mode):
            raise NotApplicable(f"{self.name} has no {mode} mode")
        return {k: str(v) for k, v in
                (self.mode_table[mode].get("env") or {}).items()}

    def flags(self, mode: str, vendor: str = "") -> str:
        """The compile flag that selects `mode` ("" when the mode is a
        run-time setting, ``env``). A compiler vendor (Toolchain.kind) with
        its own spelling has it in the mode's ``vendor_flags`` (GCC's
        separate memory is its default: no flag)."""
        if not self.has(mode):
            raise NotApplicable(f"{self.name} has no {mode} mode")
        spec = self.mode_table[mode]
        own = spec.get("vendor_flags") or {}
        if vendor and vendor in own:
            return str(own[vendor])
        return str(spec.get("flags") or "")

    @property
    def compile_time_modes(self) -> bool:
        """Whether the modes are compile flags (NVHPC), so each
        mode needs its own build."""
        return any(spec.get("flags") for spec in self.mode_table.values())

    def row_key(self, mode: str) -> int:
        if not self.has(mode):
            raise NotApplicable(f"{self.name} has no {mode} mode")
        return int(self.mode_table[mode]["row_key"])

    def mode_of_row_key(self, key) -> str:
        for m in self.modes:
            if int(self.mode_table[m]["row_key"]) == int(key):
                return m
        raise NotApplicable(f"{self.name} has no mode stored as {key}")

    def other_modes(self, mode: str) -> tuple[str, ...]:
        return tuple(m for m in self.modes if m != mode)


def _check(name: str, d: dict) -> Machine:
    for key in ("arch", "access", "scheduler", "headline_mode", "modes"):
        if key not in d:
            raise ValueError(f"machine {name}: no {key}")
    modes = d["modes"] or {}
    if not modes:
        raise ValueError(f"machine {name}: no memory mode")
    for m, spec in modes.items():
        if m not in MODES:
            raise ValueError(f"machine {name}: unknown mode {m} "
                             f"(known: {', '.join(MODES)})")
        if "row_key" not in spec:
            raise ValueError(f"machine {name}: mode {m} has no row_key")
        if spec.get("env") and spec.get("flags"):
            raise ValueError(f"machine {name}: mode {m} has both env and "
                             "flags")
        vf = spec.get("vendor_flags")
        if vf is not None and (not isinstance(vf, dict) or not spec.get(
                "flags") or not all(isinstance(v, str)
                                    for v in vf.values())):
            raise ValueError(f"machine {name}: mode {m}: vendor_flags is "
                             "a map vendor -> flag of a mode with flags")
    na = d.get("not_applicable") or {}
    for m, why in na.items():
        if m not in MODES or m in modes or not why:
            raise ValueError(f"machine {name}: bad not_applicable mode {m}")
    if d["headline_mode"] not in modes:
        raise ValueError(f"machine {name}: headline mode "
                         f"{d['headline_mode']} is not one of its modes")
    keys = [spec["row_key"] for spec in modes.values()]
    if len(keys) != len(set(keys)):
        raise ValueError(f"machine {name}: two modes share a row_key")
    if (d["scheduler"] or {}).get("kind") not in ("flux", "slurm", "local",
                                                  "direct"):
        raise ValueError(f"machine {name}: unknown scheduler kind")
    listed = tuple(d["toolchains"] or ()) if "toolchains" in d else None
    return Machine(name, d["arch"], d.get("device", ""), d["access"],
                   dict(d["scheduler"]), d["headline_mode"], dict(modes),
                   listed, dict(na), bool(d.get("one_host")),
                   bool(d.get("site_plan_runs", True)))


def load(path: Path = MACHINES_FILE, data: dict | None = None
         ) -> dict[str, Machine]:
    """The machines of `path` (or of `data`), checked."""
    if data is None:
        return dict(_load_file(str(path)))
    if data.get("version") != 1:
        raise ValueError("machines: unknown version")
    _under_test_only(data)
    return {n: _check(n, d) for n, d in (data.get("machines") or {}).items()}


def _read(path: str) -> dict:
    """The file's data; for the catalog itself, with the user's local settings laid over."""
    data = yaml.safe_load(Path(path).read_text()) or {}
    return localcfg.overlay("machines.yaml", data) if Path(path) == MACHINES_FILE else data


@lru_cache(maxsize=None)
def _data(path: str = str(MACHINES_FILE)) -> dict:
    return _read(path)


def family_of(toolchain: str) -> str:
    """The compiler family of a toolchain (catalog/toolchains.yaml
    ``family``; test data may list ``families`` in the machines data); a
    toolchain in no family is its own."""
    for fam, members in (_data().get("families") or {}).items():
        if toolchain in members:
            return fam
    from offload.engine.toolchains import registry
    fam = registry().family_of(toolchain)
    return fam.id if fam is not None else toolchain


def _under_test_only(data: dict) -> frozenset:
    """The checked ``under_test_only`` families of `data` (test data: each
    a known family of its ``families`` with its reason); the committed
    machines have none: the families are catalog/toolchains.yaml's."""
    fams = set(data.get("families") or {})
    out = set()
    for fam, why in (data.get("under_test_only") or {}).items():
        if fam not in fams or not why:
            raise ValueError(f"machines: bad under_test_only entry {fam} "
                             f"(families: {sorted(fams)}; a reason)")
        out.add(fam)
    return frozenset(out)


def under_test_only() -> frozenset:
    """Compiler families that are only ever compilers under test
    (catalog/toolchains.yaml ``families.<f>.under_test_only``: GCC, the
    the standing rule): their cells are never collected as evidence for
    another family's case and they are never a legality witness."""
    from offload.engine.toolchains import registry
    return _under_test_only(_data()) | frozenset(registry().under_test_only())


def compare_with(machine: str) -> tuple[str, ...]:
    """The machines whose toolchains a machine's cases are
    compared with (``compare_with``). The AMD machines are
    compared with wingtip (an NVHPC cell is a family witness for an
    AMD-side defect, in the modes both machines have)."""
    d = ((_data().get("machines") or {}).get(machine) or {})
    return tuple(d.get("compare_with") or ())


def no_present_check() -> frozenset:
    """(family, mode) pairs whose runs do not enforce the present check
    (catalog/machines.yaml ``no_present_check``): no witness for a
    presence or overlap abort."""
    out = set()
    for d in _data().get("no_present_check") or ():
        if d.get("mode") not in MODES or not d.get("family"):
            raise ValueError(f"machines: bad no_present_check entry {d}")
        out.add((d["family"], d["mode"]))
    return frozenset(out)


def frontend_checkers() -> dict:
    """name -> {family, lang} of the legality checkers that are
    compilers."""
    return dict(_data().get("frontend_checkers") or {})


@lru_cache(maxsize=None)
def _load_file(path: str) -> tuple:
    data = _read(path)
    return tuple(load(data=data).items())


def machine_of(toolchain: str) -> Machine:
    """The machine a toolchain runs on (offload.engine.toolchains)."""
    from offload.engine.toolchains import TOOLCHAINS
    return load()[TOOLCHAINS[toolchain].machine]


def machine_of_arch(arch: str) -> Machine | None:
    for m in load().values():
        if m.arch == arch:
            return m
    return None
