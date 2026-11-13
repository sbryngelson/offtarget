"""The optional `site:` block of a finding file: hand-written fields the site
shows when present.

The block is a run of comment lines (``!`` in Fortran, ``//`` in C) anywhere
in the file, from a ``site:`` line to an ``end site`` line, one ``key: value``
per line; a line starting ``+ `` continues the value above it, so no line
passes 132 characters (Fortran's limit covers comment lines too; parse refuses a
longer one in a Fortran file). The seed tool puts it at the end of the file, so the program's line
numbers and the confirmer's header keys (``! toolchain:``, ``! failure:``, the
first ``HSA_XNACK=``) are untouched. Unknown keys are an error, so typos
surface in the build.
"""
from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

KEYS = ("title", "summary", "workaround", "found_in", "control", "report",
        "same_as", "disposition", "hide", "devices")
DISPOSITIONS = ("not-a-compiler-issue", "out-of-scope", "mixed")
WIDTH = 132
_LINE = re.compile(r"^\s*(?:!|//)\s?(.*)$")


class SiteHeaderError(ValueError):
    pass


@dataclass(frozen=True)
class SiteHeader:
    title: str | None = None
    summary: str | None = None
    workaround: str | None = None
    found_in: str | None = None
    controls: tuple[tuple[str, str], ...] = ()
    report: str | None = None
    same_as: str | None = None
    disposition: tuple[str, str] | None = None
    hide: bool = False
    # `devices: all [TC...]`: the site matrix leaves every device of the node visible to the
    # program on these toolchains ("*": every toolchain) instead of pinning one GPU per run
    devices: tuple[str, ...] = ()


def _block(path: Path) -> list[tuple[int, str]]:
    """The block's (line number, comment text) pairs, without its markers."""
    out, inside, found = [], False, 0
    fortran = Path(path).suffix.lower() in (".f90", ".f", ".f03", ".f08")
    for n, raw in enumerate(Path(path).read_text(errors="replace").splitlines(), 1):
        if inside and fortran and len(raw) > WIDTH:
            raise SiteHeaderError(f"{path}: line {n} is longer than {WIDTH} characters")
        m = _LINE.match(raw)
        text = m.group(1).strip() if m else None
        if not inside:
            if text == "site:":
                found += 1
                if found > 1:
                    raise SiteHeaderError(f"{path}: more than one site: block (line {n})")
                inside = True
            continue
        if text is None:
            raise SiteHeaderError(f"{path}: site: block not closed by 'end site' before line {n}")
        if text == "end site":
            inside = False
            continue
        if text.startswith("+ ") and out:
            out[-1] = (out[-1][0], out[-1][1] + " " + text[2:].strip())
            continue
        out.append((n, text))
    if inside:
        raise SiteHeaderError(f"{path}: site: block has no 'end site'")
    return out


def _findings_dir(path: Path) -> Path:
    """What a control path is relative to: the findings directory (findings) the file
    is in, as the site build reads it; the file's own directory when it is in none."""
    p = Path(path).resolve()
    return next((d for d in p.parents if d.name == "findings"), p.parent)


def parse(path: Path) -> SiteHeader:
    vals: dict = {}
    controls = []
    for n, text in _block(path):
        key, sep, value = text.partition(":")
        key, value = key.strip(), value.strip()
        if not sep or key not in KEYS:
            raise SiteHeaderError(f"{path}: unknown key {key!r} in site: block, line {n}")
        if key == "control":
            src, _, desc = value.partition(" ")
            if not src or not desc.strip():
                raise SiteHeaderError(f"{path}: control needs a path and a description, line {n}")
            if not (_findings_dir(path) / src).is_file():
                raise SiteHeaderError(f"{path}: control {src!r} not found (relative to "
                                      f"{_findings_dir(path).name}/), line {n}")
            controls.append((src, desc.strip()))
        elif key == "disposition":
            kind, _, reason = value.partition(" ")
            if kind not in DISPOSITIONS or not reason.strip():
                raise SiteHeaderError(f"{path}: disposition must be one of {DISPOSITIONS} "
                                      f"followed by a reason, line {n}")
            vals[key] = (kind, reason.strip())
        elif key == "hide":
            if value not in ("true", "false"):
                raise SiteHeaderError(f"{path}: hide must be true or false, line {n}")
            vals[key] = value == "true"
        elif key == "devices":
            what, *tcs = value.split()
            from offload.engine.toolchains import registry
            bad = [t for t in tcs if t not in registry().toolchains]
            if what != "all" or bad:
                raise SiteHeaderError(f"{path}: devices must be 'all' followed by catalog toolchains"
                                      f"{' (unknown: ' + ', '.join(bad) + ')' if bad else ''}, line {n}")
            vals[key] = tuple(tcs) or ("*",)
        else:
            if key in vals:
                raise SiteHeaderError(f"{path}: {key} repeated, line {n}")
            vals[key] = value
    return SiteHeader(controls=tuple(controls), **vals)


_VERSIONS = re.compile(r",\s*(?:CCE |AFAR |NVHPC )?\d+(?:\.\d+)+"
                       r"(?:\s+(?:to|and)\s+(?:CCE |AFAR |NVHPC )?\d+(?:\.\d+)+)?.*$")


def _disposition(status: str, why: str) -> tuple[str, str] | None:
    """data/vendor/checks/dispositions.py's (status, why) as a site disposition;
    None when the finding is an issue the site shows (fixed is computed)."""
    w = why.lower()
    if status.startswith("held"):
        return ("mixed", why)
    if status != "not a report" or "covers both vendors" in w or "packet" in w:
        return None
    if "out of scope" in w or "outside the device-offload scope" in w:
        return ("out-of-scope", why)
    return ("not-a-compiler-issue", why)


def seed(finding: str, manual: dict, reports: list, cases: list) -> SiteHeader:
    """The block the seed tool writes for `finding` (path under findings),
    from the vendor checks' dispositions, report grouping and cases."""
    disp = None
    for (path, _vendor), (status, why) in manual.items():
        if path == finding:
            disp = disp or _disposition(status, why)
    title = same_as = None
    for r in reports:
        if finding in r["findings"]:
            stem = lambda p: p.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            primary = next((p for p in r["findings"] if stem(p) == r["primary"]), r["findings"][0])
            title = title or _VERSIONS.sub("", r["title"]).strip()
            if primary != finding and not same_as:
                same_as = primary.rsplit(".", 1)[0]
    controls = []
    for c in cases:
        if c["finding"] == finding and c.get("control"):
            extra = c.get("control_opt") or c.get("control_flags")
            desc = c["control_what"] + (f" ({extra})" if extra else "")
            ctl = ("../vendor/checks/" + c["control"], desc)
            if ctl not in controls:
                controls.append(ctl)
    return SiteHeader(title=title, controls=tuple(controls), same_as=same_as, disposition=disp)


def merge(old: SiteHeader, new: SiteHeader) -> SiteHeader:
    """`old` with the fields it lacks taken from `new`; never overwrites."""
    return SiteHeader(**{f: (getattr(old, f) if getattr(old, f) not in (None, (), False)
                             else getattr(new, f))
                         for f in SiteHeader.__dataclass_fields__})


def strip(text: str) -> str:
    """`text` without its site: block (and the blank lines before it), so a
    fingerprint of the program is the same with or without the block."""
    return "\n".join(_without_block(text.splitlines())) + "\n"


def _without_block(lines: list[str]) -> list[str]:
    out, inside = [], False
    for raw in lines:
        m = _LINE.match(raw)
        text = m.group(1).strip() if m else None
        if not inside and text == "site:":
            inside = True
            continue
        if inside:
            if text == "end site":
                inside = False
            continue
        out.append(raw)
    while out and not out[-1].strip():
        out.pop()
    return out


def write(path: Path, h: SiteHeader, lang: str) -> None:
    """Put `h` in `path` as its site: block, replacing any block there, at the end."""
    out = _without_block(Path(path).read_text().splitlines())
    block = render(h, lang) if h != SiteHeader() else []
    Path(path).write_text("\n".join(out + block) + "\n")


def render(h: SiteHeader, lang: str) -> list[str]:
    c = "//" if lang == "c" else "!"
    lines = ["site:"]
    for key in ("title", "summary", "workaround", "found_in"):
        if getattr(h, key):
            lines.append(f"{key}: {getattr(h, key)}")
    lines += [f"control: {p} {d}" for p, d in h.controls]
    for key in ("report", "same_as"):
        if getattr(h, key):
            lines.append(f"{key}: {getattr(h, key)}")
    if h.disposition:
        lines.append(f"disposition: {h.disposition[0]} {h.disposition[1]}")
    if h.hide:
        lines.append("hide: true")
    if h.devices:
        lines.append("devices: all" + "".join(f" {t}" for t in h.devices if t != "*"))
    lines.append("end site")
    out = []
    for x in lines:
        first, *rest = textwrap.wrap(x, WIDTH - len(c) - 1, break_long_words=False,
                                     break_on_hyphens=False, subsequent_indent="+ ") or [x]
        out += [f"{c} {y}" for y in [first, *rest]]
    return out
