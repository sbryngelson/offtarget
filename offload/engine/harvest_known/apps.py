"""The workaround history of open offload applications.

Commits, pull requests and issues that add or remove a workaround naming a
compiler (CCE, Cray, nvfortran, NVHPC, amdflang, AOMP, XNACK, "compiler
bug"). The callers read ``git log`` of a clone in the untrusted download
area and the GitHub API's issue/PR JSON (read-only); these functions only
parse text."""
from __future__ import annotations

import re

from offload.engine.harvest_known import textscan

_HIT = re.compile(
    r"\bCCE\b|\bcray\b|\bcrayftn\b|\bftn-\d+|\bnvfortran\b|\bnvc\b|\bnvhpc\b|"
    r"\bNV\s?HPC\b|\bpgi\b|\bpgfortran\b|\bamdflang\b|\bamd[- ]flang\b|"
    r"\bLLVMFlang\b|\bflang-new\b|\bAFAR\b|\bAOMP\b|XNACK|"
    r"compiler\s+(bug|issue|error|crash|problem)|internal compiler error|"
    r"\bICE\b|miscompil|\bfort2\b|work[- ]?around", re.I)
_PR = re.compile(r"(?:\(|\bpull request\s+|\bsee\s+|\band\s+|^|\s)#(\d+)\b",
                 re.I)
_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)


def workaround_hit(text: str) -> bool:
    return bool(_HIT.search(text))


def pr_numbers(text: str) -> list[int]:
    return [int(x) for x in _PR.findall(text)]


def parse_log(log: str) -> list[dict]:
    """``git log --format=%x1e%H %ad%n%B --date=short`` into records (the
    ASCII record separator starts each commit; bodies may hold anything)."""
    out: list[dict] = []
    for chunk in log.split("\x1e")[1:]:
        head, _, rest = chunk.partition("\n")
        commit, date = head.split()[:2]
        lines = rest.strip("\n").split("\n")
        subject = lines[0] if lines else ""
        body = "\n".join(lines[1:]).strip()
        out.append({"commit": commit, "date": date, "subject": subject,
                    "body": body})
    return out


def issue_record(issue: dict, repo: str) -> dict:
    body = issue.get("body") or ""
    text = (issue.get("title") or "") + "\n" + body
    codes = _FENCE.findall(body)
    mods: set[str] = set()
    for c in codes:
        mods |= textscan.models(c)
    mods |= textscan.models(body)
    if "omp-target" in mods:
        mods.discard("omp-host")
    return {"repo": repo, "number": issue["number"],
            "kind": "pr" if issue.get("pull_request") else "issue",
            "url": issue.get("html_url"), "title": issue.get("title"),
            "created": (issue.get("created_at") or "")[:10],
            "state": issue.get("state"), "n_code": len(codes),
            "models": sorted(mods),
            "compilers": sorted(textscan.compilers(text)),
            "hit": workaround_hit(text)}
