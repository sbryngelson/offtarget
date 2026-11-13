"""The commits that added or fixed a harvested test, and the issues they name.

``parse_log`` reads the output of ``git log --no-renames --name-status
--date=short --format=%x1ecommit%x1f%H%x1f%ad%x1f%B%x1f`` over the test roots
(llvm-project: offload/test and, before the 2024 move, openmp/libomptarget/test;
AOMP: test/smoke and test/smoke-fails). A test is keyed by its path under the
root. ``fix_commits`` lists the commits that touched a test and read as a fix
(``is_fix``). ``issue_refs`` extracts Fixes/Closes/Resolves references, issue
URLs, bugs.llvm.org links, the trailing ``(#N)`` pull request and Phabricator
reviews from a message. ``name_tickets`` reads the ticket number from an AOMP
test directory name (``flang-288446``, ``bugz-50967``, ``issue_001``)."""
from __future__ import annotations

import re


def issue_refs(msg: str, repo: str = "llvm") -> dict[str, list[str]]:
    fixes, issues, pr, reviews = [], [], [], []
    for m in re.finditer(r"\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)"
                         r"\s*:?\s+(?:(?:https?://)?github\.com/([\w.-]+/"
                         r"[\w.-]+)/issues/|#)(\d+)", msg, re.I):
        fixes.append(f"{_repo(m.group(1), repo)}#{m.group(2)}")
    for m in re.finditer(r"github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)", msg):
        issues.append(f"{_repo(m.group(1), repo)}#{m.group(2)}")
    for m in re.finditer(r"(?:bugs\.llvm\.org|llvm\.org/bugs)/show_bug\.cgi"
                         r"\?id=(\d+)|\bPR\s?(\d+)\b", msg):
        issues.append(f"bugzilla#{m.group(1) or m.group(2)}")
    for m in re.finditer(r"\(#(\d+)\)\s*$", msg.splitlines()[0] if msg else
                         "", re.M):
        pr.append(f"{repo}#{m.group(1)}")
    for m in re.finditer(r"reviews\.llvm\.org/(D\d+)", msg):
        reviews.append(m.group(1))
    issues = sorted(set(issues) | set(fixes))
    return {"fixes": sorted(set(fixes)), "issues": issues, "pr": pr,
            "reviews": sorted(set(reviews))}


def _repo(full: str | None, default: str) -> str:
    if not full:
        return default
    full = full.lower()
    return {"llvm/llvm-project": "llvm", "rocm/aomp": "aomp",
            "rocm/llvm-project": "rocm-llvm"}.get(full, full)


_FIX_WORDS = re.compile(r"\b(fix(?:es|ed|ing)?|bug|crash(?:es)?|regression|"
                        r"miscompil\w*|wrong|incorrect|hang)\b", re.I)


def is_fix(msg: str) -> bool:
    if issue_refs(msg)["fixes"]:
        return True
    subject = (msg.splitlines() or [""])[0]
    return bool(_FIX_WORDS.search(subject))


def name_tickets(name: str) -> list[str]:
    out = []
    m = re.match(r"^bugz-(\d+)", name)
    if m:
        return [f"bugzilla#{m.group(1)}"]
    m = re.match(r"^issue[_-]0*(\d+)", name)
    if m:
        return [f"aomp#{m.group(1)}"]
    for m in re.finditer(r"(?:^|[-_])(\d{5,6})(?=$|[-_])", name):
        out.append(f"amd#{m.group(1)}")
    return out


def parse_log(text: str, roots: tuple[str, ...], repo: str = "llvm",
              depth: int | None = None, key_of=None) -> dict[str, dict]:
    """key -> {added: commit record, fix_commits: [commit records], commits:
    n}; the key is the path under its root, or with `depth` its first
    `depth` components (an AOMP test directory), or ``key_of(path under
    root)`` (None: not a test)."""
    commits = []
    for chunk in text.split("\x1ecommit\x1f")[1:]:
        parts = chunk.split("\x1f")
        if len(parts) < 4:
            continue
        sha, date, msg, rest = parts[0], parts[1], parts[2], parts[3]
        files = []
        for ln in rest.splitlines():
            m = re.match(r"^([ADMTRC])\d*\t([^\t]+)(?:\t(.+))?$", ln)
            if m:
                files.append((m.group(1), m.group(3) or m.group(2)))
        refs = issue_refs(msg, repo)
        commits.append({"commit": sha, "date": date,
                        "subject": (msg.strip().splitlines() or [""])[0][:200],
                        "fix": is_fix(msg), **refs, "files": files})
    commits.sort(key=lambda c: c["date"])
    out: dict[str, dict] = {}
    for c in commits:
        rec = {k: v for k, v in c.items() if k != "files"}
        for status, path in c["files"]:
            key = None
            for r in roots:
                if path.startswith(r):
                    key = path[len(r):]
                    break
            if key is None:
                continue
            if key_of is not None:
                key = key_of(key)
                if key is None:
                    continue
            elif depth:
                key = "/".join(key.split("/")[:depth])
            e = out.setdefault(key, {"added": None, "fix_commits": [],
                                     "commits": 0})
            if any(x["commit"] == c["commit"] for x in e["fix_commits"]) or \
                    (e.get("_last") == c["commit"]):
                continue
            e["_last"] = c["commit"]
            e["commits"] += 1
            if status == "A" and e["added"] is None:
                e["added"] = rec
            if c["fix"]:
                e["fix_commits"].append(rec)
    for e in out.values():
        e.pop("_last", None)
    return out
