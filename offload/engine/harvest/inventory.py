"""The inventory of harvested tests, read as data (never run).
* LLVM (``llvm_record``): every file under ``offload/test`` with a ``RUN:`` line
  (``Inputs/`` are helpers). RUN lines are read with the substitutions of
  ``offload/test/lit.cfg`` (``%libomptarget-compile...``, ``%libomptarget-run[-fail]...``,
  ``-and-run``, ``-run-and-check``, ``env V=x``, ``2>&1``, FileCheck prefixes).
  Each run is one **variant**: the preceding compile's flags, its environment,
  whether it must fail, its prefixes, whether stderr is checked and its triple.
* AOMP (``aomp_record``): every directory of ``test/smoke`` and
  ``test/smoke-fails`` with a Makefile, read for the sources, compiler, flag
  variables, RUNENV, ARGS, RUNCMD and SUPPORTED/UNSUPPORTED. One variant;
  without FileCheck the exit status is the only oracle.

Each record also has the language, model (OpenMP, OpenACC), FileCheck prefixes
with line counts, REQUIRES/UNSUPPORTED/XFAIL, every offload target mentioned
(``arch``) and the licence."""
from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath

LICENSE = {"llvm": "Apache-2.0 WITH LLVM-exception (llvm-project)",
           "aomp": "Apache-2.0 (ROCm/aomp LICENSE)"}

EXT_LANG = {".c": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
            ".f90": "f90", ".F90": "f90", ".f95": "f90", ".F95": "f90",
            ".f03": "f90", ".f08": "f90", ".f": "fixed", ".F": "fixed",
            ".for": "fixed", ".cu": "cuda", ".hip": "hip", ".h": "header",
            ".hpp": "header", ".inc": "header"}

TRIPLES = ("amdgcn-amd-amdhsa", "nvptx64-nvidia-cuda", "x86_64-unknown-"
           "linux-gnu", "x86_64-pc-linux-gnu", "aarch64-unknown-linux-gnu",
           "powerpc64le-ibm-linux-gnu", "powerpc64-ibm-linux-gnu",
           "s390x-ibm-linux-gnu")
_ARCH = re.compile(r"\b(amdgcn[\w-]*|nvptx[\w-]*|gfx\d+[a-z]?|sm_\d+|"
                   r"__AMDGCN__|__NVPTX__|amdgpu|nvidiagpu|cuda)\b")


def lang_of(path: str) -> str:
    return EXT_LANG.get(PurePosixPath(path).suffix, "other")


def model_of(text: str) -> str:
    omp = re.search(r"^\s*(?:#\s*pragma\s+omp\b|!\$omp\b)", text,
                    re.M | re.I)
    acc = re.search(r"^\s*(?:#\s*pragma\s+acc\b|!\$acc\b)", text,
                    re.M | re.I)
    if omp and acc:
        return "both"
    return "omp" if omp else "acc" if acc else "none"


def _keyword_list(text: str, key: str) -> list[str]:
    out = []
    for m in re.finditer(rf"(?:^|[\s/!#*;]){key}:(.*)$", text, re.M):
        out += [x.strip() for x in m.group(1).split(",") if x.strip()]
    return out


def check_counts(text: str) -> dict[str, int]:
    """FileCheck prefix -> number of directive lines."""
    out: dict[str, int] = {}
    for m in re.finditer(r"(?://|!|\*|#)\s*([A-Z][A-Z0-9_]*)(?:-NEXT|-SAME|"
                         r"-NOT|-DAG|-EMPTY|-LABEL|-COUNT-\d+)?:", text):
        p = m.group(1)
        if p in ("RUN", "REQUIRES", "UNSUPPORTED", "XFAIL", "NOTE", "TODO",
                 "FIXME", "XXX", "NB", "WARNING", "ERROR", "BUG", "HACK",
                 "OK"):
            continue
        out[p] = out.get(p, 0) + 1
    return out


def run_lines(text: str) -> list[str]:
    """The RUN lines of a lit test, continuation lines (``\\``) joined."""
    out, cur = [], None
    for m in re.finditer(r"RUN:(.*)$", text, re.M):
        body = m.group(1).rstrip()
        if body.endswith("*/"):
            body = body[:-2].rstrip()
        cont = body.endswith("\\")
        if cont:
            body = body[:-1]
        cur = body if cur is None else cur + " " + body.strip()
        if not cont:
            out.append(" ".join(cur.split()))
            cur = None
    if cur is not None:
        out.append(" ".join(cur.split()))
    return out


# --- LLVM lit -----------------------------------------------------------------------

_COMPILE = re.compile(r"^%libomptarget-compile(opt)?(xx|xxx)?(-fortran)?"
                      r"(-force-usm)?(-and-run|-run-and-check)?-(\S+)$")
_RUN = re.compile(r"^%libomptarget-run(-fail)?-(\S+)$")
_FCHECK = re.compile(r"^%fcheck(?:-plain)?-(\S+)$")


def _split_cmds(line: str) -> list[list[list[str]]]:
    """A RUN line as commands (split at && and ;), each a pipeline (split
    at |) of token lists."""
    try:
        toks = shlex.split(line, posix=True)
    except ValueError:
        toks = line.split()
    cmds, pipe, cur = [], [], []
    for t in toks:
        if t in ("&&", ";", "||"):
            pipe.append(cur)
            cmds.append(pipe)
            pipe, cur = [], []
        elif t == "|":
            pipe.append(cur)
            cur = []
        else:
            cur.append(t)
    pipe.append(cur)
    cmds.append(pipe)
    return cmds


def _prefixes(args: list[str]) -> list[str]:
    out = []
    for i, a in enumerate(args):
        m = re.match(r"-?-check-prefix(?:es)?(?:=(.*))?$", a)
        if m:
            val = m.group(1) if m.group(1) is not None else (
                args[i + 1] if i + 1 < len(args) else "")
            out += [p for p in val.split(",") if p]
    return out or ["CHECK"]


def llvm_variants(lines: list[str], lang: str) -> tuple[list[dict], bool,
                                                         list[str]]:
    """(variants, compile_only, other tools) of a test's RUN lines."""
    flags: list[str] = []
    variants, tools = [], []
    compiled = False
    for line in lines:
        for pipe in _split_cmds(line):
            env: dict[str, str] = {}
            fail = False
            run = None
            stderr = False
            prefixes = None
            for stage in pipe:
                toks = list(stage)
                if "2>&1" in toks:
                    stderr = True
                    toks = [t for t in toks if t != "2>&1"]
                k = 0
                while k < len(toks):
                    t = toks[k]
                    if t in ("env", "%not", "not"):
                        if t != "env":
                            fail = True
                        k += 1
                        continue
                    if t in ("--crash", "-u"):
                        k += 2 if t == "-u" else 1
                        continue
                    m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", t)
                    if m and run is None:
                        env[m.group(1)] = m.group(2)
                        k += 1
                        continue
                    break
                toks = toks[k:]
                if not toks:
                    continue
                head = toks[0]
                mc = _COMPILE.match(head)
                mr = _RUN.match(head)
                mf = _FCHECK.match(head)
                if mc:
                    opt, xx, fort, usm, tail, triple = mc.groups()
                    flags = (["-O3"] if opt else []) + \
                        (["-fopenmp-version=52"] if fort else []) + \
                        (["-fopenmp-force-usm"] if usm else []) + toks[1:]
                    compiled = True
                    if tail:
                        run = {"triple": triple, "fail": fail,
                               "shorthand": tail}
                        if tail == "-run-and-check":
                            prefixes = ["CHECK"]
                elif mr:
                    run = {"triple": mr.group(2), "fail": fail or
                           bool(mr.group(1))}
                elif head == "%t" or head.startswith("%t "):
                    run = {"triple": "generic", "fail": fail}
                elif mf or head in ("FileCheck", "%FileCheck"):
                    prefixes = _prefixes(toks[1:])
                    if mf and run is not None and \
                            run["triple"] != mf.group(1):
                        run["check_triple"] = mf.group(1)
                else:
                    tools.append(head)
            if run is not None:
                variants.append({
                    "flags": list(flags), "env": env,
                    "fail": bool(run["fail"]),
                    "prefixes": prefixes or [], "stderr": stderr,
                    "triple": run.get("check_triple", run["triple"]),
                    "run_triple": run["triple"]})
    uniq, seen = [], set()
    for v in variants:
        key = repr(sorted(v.items()))
        if key not in seen:
            seen.add(key)
            uniq.append(v)
    return uniq, compiled and not uniq, sorted(set(tools))


def llvm_record(rel: str, text: str) -> dict:
    """The inventory record of an LLVM offload lit test (`rel`: its path
    under offload/test)."""
    lang = lang_of(rel)
    lines = run_lines(text)
    variants, compile_only, tools = llvm_variants(lines, lang)
    arch = sorted(set(_ARCH.findall("\n".join(lines) + "\n" + " ".join(
        _keyword_list(text, "REQUIRES") + _keyword_list(text, "UNSUPPORTED")
        + _keyword_list(text, "XFAIL")))) | {
        t for t in TRIPLES if t in "\n".join(lines)})
    return {"id": f"llvm/{rel}", "source": "llvm", "suite": "offload/test",
            "path": f"offload/test/{rel}", "files": [f"offload/test/{rel}"],
            "lang": lang, "model": model_of(text), "run": lines,
            "variants": variants, "compile_only": compile_only,
            "tools": tools, "checks": check_counts(text),
            "requires": _keyword_list(text, "REQUIRES"),
            "unsupported": _keyword_list(text, "UNSUPPORTED"),
            "xfail": _keyword_list(text, "XFAIL"), "arch": arch,
            "license": LICENSE["llvm"], "lines": text.count("\n") + 1}


# --- AOMP smoke ---------------------------------------------------------------------

def parse_makefile(text: str) -> dict[str, str]:
    """Variable assignments of a Makefile (``=``, ``:=``, ``?=``, ``+=``
    appended), continuation lines joined; rules and conditionals are kept
    as text under ``__rules__``."""
    text = re.sub(r"\\\n", " ", text)
    out: dict[str, str] = {}
    rules = []
    for line in text.splitlines():
        s = line.split("#", 1)[0].rstrip() if not line.startswith("\t") \
            else line
        if not s.strip():
            continue
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(\+=|:=|\?=|=)\s*(.*)$",
                     s)
        if m and not line.startswith("\t"):
            name, op, val = m.groups()
            val = val.strip()
            if op == "+=":
                out[name] = (out.get(name, "") + " " + val).strip()
            elif op == "?=":
                out.setdefault(name, val)
            else:
                out[name] = val
        else:
            rules.append(line)
    out["__rules__"] = "\n".join(rules)
    return out


def _expand(val: str, mk: dict, depth: int = 0) -> str:
    if depth > 8:
        return val
    return re.sub(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)",
                  lambda m: _expand(mk.get(m.group(1), ""), mk, depth + 1)
                  if m.group(1) in mk else m.group(0), val)


def _env_of(val: str) -> dict[str, str]:
    out = {}
    try:
        toks = shlex.split(val)
    except ValueError:
        toks = val.split()
    for t in toks:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", t)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def aomp_record(rel: str, makefile: str, files: dict[str, str]) -> dict:
    """The inventory record of an AOMP smoke test directory (`rel`:
    ``smoke/<name>`` or ``smoke-fails/<name>``; `files`: name -> text of
    the directory's files)."""
    mk = parse_makefile(makefile)
    main = _expand(mk.get("TESTSRC_MAIN", ""), mk).split()
    aux = _expand(mk.get("TESTSRC_AUX", ""), mk).split()
    srcs = [s for s in main + aux if s]
    compiler = _expand(mk.get("CC", ""), mk)
    cc_name = " ".join([compiler, mk.get("CLANG", ""), mk.get("FLANG", ""),
                        mk.get("OMP_BIN", "")])
    langs = {lang_of(s) for s in srcs} - {"header"}
    if re.search(r"clang\+\+|\+\+|hipcc", _expand(mk.get("OMP_BIN", ""), mk)
                 + " " + compiler) or "cpp" in langs:
        lang = "cpp"
    elif not langs:
        lang = "none"
    elif len(langs) == 1:
        lang = langs.pop()
    else:
        lang = "mixed"
    flags = []
    for v in ("CFLAGS", "OMP_FLAGS", "EXTRA_CFLAGS", "EXTRA_OMP_FLAGS",
              "LINK_FLAGS", "FLANG_FLAGS"):
        if mk.get(v):
            flags += _expand(mk[v], mk).split()
    runcmd = mk.get("RUNCMD", "")
    rules = mk["__rules__"]
    custom = bool(re.search(r"^(run|check)\s*:", rules, re.M))
    checktext = runcmd + "\n" + (rules if custom else "")
    has_fc = "FILECHECK" in checktext or "FileCheck" in checktext
    prefixes = []
    if has_fc:
        m = re.search(r"FILECHECK\)?\s+([^|\n]*)", checktext)
        prefixes = _prefixes(m.group(1).split() if m else [])
    text = "\n".join(files.get(s, "") for s in srcs)
    env = _env_of(_expand(mk.get("RUNENV", ""), mk))
    variant = {"flags": flags, "env": env, "fail": False,
               "prefixes": prefixes, "stderr": "2>&1" in checktext,
               "triple": "generic", "run_triple": "generic",
               "args": _expand(mk.get("ARGS", ""), mk).split()}
    variants = [variant] if srcs else []
    tools: list[str] = []
    if custom:
        variants, tools = _custom_runs(rules, mk, variant)
    name = PurePosixPath(rel).name
    arch_text = " ".join([mk.get("SUPPORTED", ""), mk.get("UNSUPPORTED", ""),
                          " ".join(flags), text])
    return {"id": f"aomp/{rel}", "source": "aomp",
            "suite": PurePosixPath(rel).parts[0], "path": f"test/{rel}",
            "name": name, "files": [f"{rel}/{s}" for s in srcs],
            "dir_files": sorted(files), "lang": lang,
            "model": model_of(text), "run": [runcmd] if runcmd else [],
            "custom_rules": custom, "variants": variants,
            "compile_only": False, "tools": tools,
            "checks": check_counts(text) if has_fc else {},
            "requires": [], "unsupported": [], "xfail": [],
            "supported": mk.get("SUPPORTED", ""),
            "arch_unsupported": mk.get("UNSUPPORTED", ""),
            "compiler": cc_name.strip(),
            "arch": sorted(set(_ARCH.findall(arch_text))),
            "license": LICENSE["aomp"], "lines": text.count("\n") + 1}


def _rule_body(rules: str, target: str) -> list[str]:
    out, on = [], False
    for ln in rules.splitlines():
        if re.match(rf"^{target}\s*::?", ln):
            on = True
            continue
        if on:
            if ln.startswith("\t"):
                out.append(ln.strip())
            elif ln.strip():
                break
    return out


def _custom_runs(rules: str, mk: dict, base: dict) -> tuple[list, list]:
    """The runs of a Makefile's own ``run:`` / ``check:`` rule: one
    variant per ``./$(TESTNAME)`` line (its environment and arguments, a
    FileCheck after it), and the other commands it runs."""
    body = _rule_body(rules, "run") or _rule_body(rules, "check")
    variants, tools = [], []
    for ln in body:
        ln = ln.lstrip("@-").strip()
        if not ln:
            continue
        cmd = _expand(ln, mk)
        if "$(TESTNAME)" in ln or re.search(r"\./\S+", cmd):
            pre, _, post = cmd.partition("./")
            env = _env_of(pre)
            if not env and pre.strip() and not pre.strip().startswith(
                    ("env", "$(", "timeout")):
                tools.append(pre.split()[0])
            prog, *rest = post.split("|", 1)
            parts = prog.split()
            args = [a for a in parts[1:] if a not in ("2>&1",)
                    and not a.startswith(">")]
            fc = rest[0] if rest else ""
            pfx = _prefixes(fc.split()[1:]) if ("FILECHECK" in ln or
                                                 "FileCheck" in fc) else []
            if rest and not pfx:
                tools.append(fc.split()[0] if fc.split() else "|")
            variants.append({**base, "env": env, "args": args,
                             "prefixes": pfx, "stderr": "2>&1" in ln})
        else:
            word = cmd.split()[0]
            if word not in ("echo", "true", ":", "cd"):
                tools.append(word)
    return variants, sorted(set(tools))
