"""The NVIDIA HPC compilers forum (Discourse) as a bug source.

The fetcher (fetch_category, fetch_topic) does read-only anonymous GETs
of Discourse's JSON endpoints into the untrusted download area; nothing
is posted and no account is used. topic_record turns a topic's JSON into
an inventory row: its code blocks' offload models and languages, the TPR
numbers and "fixed in" versions its posts name, and whether a staff post
confirms a defect. stage() places a row in the funnel."""
from __future__ import annotations

import html as _html
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from offload.engine.harvest_known import textscan

BASE = "https://forums.developer.nvidia.com"
# HPC Compilers: "nvc, nvc++ and nvfortran" (313), "Legacy PGI Compilers" (304)
CATEGORIES = {313: "nvc-nvc-and-nvfortran", 304: "legacy-pgi"}
UA = "compliance-harvest/1 (read-only research crawl)"
DELAY_S = 1.2

_CODE = re.compile(r"<pre[^>]*>\s*<code[^>]*>(.*?)</code>\s*</pre>", re.S)
_TAG = re.compile(r"<[^>]+>")
# a staff post that confirms a defect in the compiler
_CONFIRM = re.compile(
    r"\b(TPR|problem report|filed (a|an) (issue|report|bug)|report(ed)? "
    r"(it|this|the issue|the problem)? ?to (our )?(engineering|compiler team)|"
    r"compiler (bug|issue|error|problem)|our (bug|issue|error)|"
    r"(able to|can|could) reproduce|is a bug|appears to be a bug|"
    r"looks like a bug|this is a bug|regression|fixed in|has been fixed|"
    r"been resolved|will be fixed)\b", re.I)


def code_blocks(cooked: str) -> list[str]:
    return [_html.unescape(_TAG.sub("", b)) for b in _CODE.findall(cooked)]


def plain_text(cooked: str) -> str:
    return _html.unescape(_TAG.sub(" ", cooked))


def topic_record(topic: dict) -> dict:
    posts = topic.get("post_stream", {}).get("posts", [])
    codes: list[str] = []
    text: list[str] = []
    staff_text: list[str] = []
    for p in posts:
        cooked = p.get("cooked") or ""
        codes += code_blocks(cooked)
        t = plain_text(cooked)
        text.append(t)
        if p.get("staff"):
            staff_text.append(t)
    all_text = "\n".join([topic.get("title", ""), *text])
    mods: set[str] = set()
    langs: set[str] = set()
    for c in codes:
        m = textscan.models(c)
        mods |= m
        lang = textscan.language(c)
        if m and lang not in ("shell", "other"):
            langs.add(lang)
    if "omp-target" in mods:
        mods.discard("omp-host")
    tp = sorted(textscan.tprs(all_text))
    fx = sorted(textscan.fixed_in(all_text))
    staff_ok = any(_CONFIRM.search(t) for t in staff_text)
    evidence = ("tpr" if tp else "fixed" if fx else
                "staff" if staff_ok else None)
    return {"id": topic["id"], "url": f"{BASE}/t/{topic['id']}",
            "title": topic.get("title", ""), "slug": topic.get("slug", ""),
            "category": topic.get("category_id"),
            "created": (topic.get("created_at") or "")[:10],
            "posts": topic.get("posts_count", len(posts)),
            "n_code": len(codes), "models": sorted(mods),
            "languages": sorted(langs), "tprs": tp, "fixed_in": fx,
            "staff_confirmed": staff_ok, "evidence": evidence,
            "compilers": sorted(textscan.compilers(all_text))}


def stage(r: dict) -> str:
    """The funnel stage a topic stops at ('candidate' when it passes)."""
    if not r["n_code"]:
        return "no_code"
    if not ({"acc", "omp-target"} & set(r["models"])):
        return "not_offload"
    if not ({"c", "fortran"} & set(r["languages"])):
        return "cxx_only"
    if not r["evidence"]:
        return "no_bug_evidence"
    return "candidate"


def listing_ids(d: dict) -> list[int]:
    return [t["id"] for t in d.get("topic_list", {}).get("topics", [])]


def listing_has_more(d: dict) -> bool:
    return bool(d.get("topic_list", {}).get("more_topics_url"))


# --- network (read-only GETs; the callers write into the untrusted area) -------

def _get(url: str, tries: int = 5) -> bytes:
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                   "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(min(120, 10 * 2 ** i))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(min(120, 10 * 2 ** i))
    raise RuntimeError(f"giving up on {url}")


def fetch_category(cat: int, out: Path, max_pages: int = 2000) -> list[int]:
    """Every topic id of a category, one listing page per file."""
    out.mkdir(parents=True, exist_ok=True)
    ids: list[int] = []
    for page in range(max_pages):
        f = out / f"c{cat}-p{page:04d}.json"
        if not f.is_file():
            f.write_bytes(_get(f"{BASE}/c/{cat}.json?page={page}"))
            time.sleep(DELAY_S)
        d = json.loads(f.read_text())
        got = listing_ids(d)
        ids += got
        if not got or not listing_has_more(d):
            break
    return ids


def fetch_topic(tid: int, out: Path) -> Path:
    """A topic's JSON, with every post (Discourse sends the first 20)."""
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"t{tid}.json"
    if f.is_file():
        return f
    d = json.loads(_get(f"{BASE}/t/{tid}.json"))
    time.sleep(DELAY_S)
    ps = d.get("post_stream", {})
    have = {p["id"] for p in ps.get("posts", [])}
    rest = [i for i in ps.get("stream", []) if i not in have]
    for k in range(0, len(rest), 20):
        q = "&".join(f"post_ids[]={i}" for i in rest[k:k + 20])
        more = json.loads(_get(f"{BASE}/t/{tid}/posts.json?{q}"))
        ps["posts"] += more.get("post_stream", {}).get("posts", [])
        time.sleep(DELAY_S)
    f.write_text(json.dumps(d))
    return f


_T_MODEL = re.compile(r"openacc|\bacc\b|\$acc|openmp|\bomp\b|\btarget\b|"
                      r"offload|\bgpu\b|kernels?\b|device|managed|unified|"
                      r"declare|routine|reduction|collapse|present|"
                      r"\bmap\b|-mp\b|-acc\b|-ta=|tesla", re.I)
_T_BUG = re.compile(r"\bbug\b|wrong|incorrect|crash|segfault|segmentation|"
                    r"internal compiler|\bICE\b|\berror\b|fail|hang|"
                    r"regression|illegal|invalid|not work|issue|problem|"
                    r"different results?|NaN|signal 11|fort[12]\b", re.I)


def title_priority(title: str) -> int:
    """Fetch order: offload words count 2, defect words 1 (0: neither)."""
    return 2 * bool(_T_MODEL.search(title)) + bool(_T_BUG.search(title))


def listing_titles(d: dict) -> dict[int, str]:
    return {t["id"]: t.get("title", "") for t in
            d.get("topic_list", {}).get("topics", [])}
