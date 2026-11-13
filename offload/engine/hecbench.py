"""HeCBench (ORNL) device-offload benchmarks as real-code test material.

The pure part of the ``hecbench`` campaign. For each ``src/<name>-omp``
benchmark it derives a build recipe and run command from ``Makefile.aomp``,
classifies it as buildable or not, splits benchmarks into a dev half and a
sealed holdout half, and judges a run's output. Compiling and running is
``offload.engine.hecbench_run``; the campaign is ``offload.engine.campaigns.hecbench``;
the command line is tools/campaigns/hecbench.py.

``make -n -B -f Makefile.aomp run`` with the compiler variables replaced by
markers prints the commands, which ``parse_dry_run`` reads. Only -D, -U, -I,
-isystem, -include and -std= are kept for compiling and -l and -L for linking;
the toolchain's flags (catalog/toolchains.yaml) replace the rest. A repeat-like
run argument (repeat, iter, reps, loops) becomes ``REPEAT`` (2). A benchmark is
in the dev half iff the SHA-256 of its directory name, as a number, is even."""
from __future__ import annotations

import hashlib
import json
import re
import shlex
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
BENCH = ROOT / "data" / "bench" / "hecbench"
HOLDOUT = ROOT / "data" / "bench" / "hecbench-holdout"
CLONE = ROOT / "corpus" / "apps" / "HeCBench-ornl"
SPLIT = BENCH / "split.yaml"
RECIPES = BENCH / "recipes.yaml"
HOLDOUT_RECIPES = HOLDOUT / "recipes.yaml"
RESULTS = ROOT / "results" / "hecbench"

REPEAT = 2                 # the fixed small repeat count
RUN_TIMEOUT_S = 30         # a run's time limit
REF_TIMEOUT_S = 90         # the serial host reference's run limit (no oracle beyond it)
COMPILE_TIMEOUT_S = 900

# the markers the compiler variables take in the dry run
CC_MARK, CXX_MARK, FC_MARK = "HECB_CC", "HECB_CXX", "HECB_FC"
MARKS = (CC_MARK, CXX_MARK, FC_MARK)
MAKE_VARS = (f"CC={CC_MARK}", f"CXX={CXX_MARK}", f"FC={FC_MARK}", "OPTIMIZE=yes",
             "DEBUG=no", "VERIFY=no", "DEVICE=gpu")

C_EXT = (".c",)
CXX_EXT = (".cpp", ".cc", ".cxx", ".C")
F_EXT = (".f", ".f90", ".F90", ".F", ".f95")
CUDA_EXT = (".cu", ".cuh")
SOURCE_EXT = C_EXT + CXX_EXT + F_EXT + CUDA_EXT
HEADER_EXT = (".h", ".hpp", ".hh", ".cuh", ".inc")

STATUSES = ("ok", "needs-external-library", "needs-data-file", "cuda-only-dependency",
            "other-language", "no-recipe")


# --- the split --------------------------------------------------------------------------


def name_hash(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def half_of(name: str) -> str:
    """``dev`` iff the SHA-256 of the directory name is even, else ``holdout``."""
    return "dev" if int(name_hash(name), 16) % 2 == 0 else "holdout"


def case_id(name: str) -> str:
    """The id of a benchmark in rows and tables: ``hecbench-<directory>``."""
    return f"hecbench-{name}"


# --- licences ---------------------------------------------------------------------------


def parse_gpl_listed(readme: str) -> list[str]:
    """The benchmark names the README's License section lists as having GPL-style
    licenses ("The benchmarks a, b, c have GPL-style licenses.")."""
    m = re.search(r"The benchmarks?\s+([^.\n]*?)\s+(?:have|has)\s+GPL-style\s+licen[sc]es?",
                  readme)
    if not m:
        return []
    return sorted(x.strip() for x in re.split(r",|\band\b", m.group(1)) if x.strip())


# licence classes whose benchmarks are tracked as an id only and left out of every table that
# carries source text
WITHHELD = ("gpl-style", "restricted")
_GRANT = re.compile(r"for any purpose,?\s+commercial or non-?commercial", re.I)
_RESTRICTED = re.compile(
    r"non-?\s?commercial\s+use\s+licen[cs]e|not\s+for\s+commercial\s+use|"
    r"research\s+(?:purposes?\s+|use\s+)?only|"
    r"academic\s+use\s+only|non-?commercial\s+(?:use|purposes?)\s+only|"
    r"redistribution\s+is\s+(?:not\s+permitted|prohibited)", re.I)
LICENCE_FILES = ("LICENSE", "LICENCE", "COPYING", "LICENSE.md", "LICENSE.txt", "LICENCE.txt", "COPYING.txt")


def read_licence_file(bench_dir: Path) -> str | None:
    """The text of the first licence file of a benchmark directory, else None."""
    for n in LICENCE_FILES:
        p = Path(bench_dir) / n
        if p.is_file():
            return p.read_text(errors="replace")
    return None


def licence_file_class(text: str) -> str:
    """``copyleft`` for a GNU (GPL, LGPL, AGPL) or Mozilla licence file, ``restricted`` for a
    licence that forbids commercial use or redistribution (non-commercial, research or academic
    use only), else ``permissive`` (MIT, BSD, Apache, ISC, a vendor's own permissive text; a
    grant "for any purpose, commercial or non-commercial" is permissive)."""
    head = text[:3000]
    if re.search(r"GNU\s+(?:LESSER\s+|AFFERO\s+|LIBRARY\s+)?GENERAL\s+PUBLIC|Mozilla Public", head, re.I):
        return "copyleft"
    if re.search(r"GPL|General Public License", head):
        return "copyleft"
    if _RESTRICTED.search(_GRANT.sub("", text)):
        return "restricted"
    return "permissive"


def licence_class(name: str, gpl_listed, license_text: str | None) -> str:
    """The licence class of the benchmark directory ``<base>-omp``:

    * ``gpl-style``: named in the README's list, or its own licence file is a
      GNU or Mozilla one (the sources never enter a tracked file);
    * ``restricted``: an own licence file that forbids commercial use or redistribution
      (treated like ``gpl-style``: an id only in tracked files);
    * ``own-permissive``: an own licence file of a permissive licence;
    * ``bsd3``: no own licence file, the repository's BSD-3-Clause licence.
    """
    base = name[:-4] if name.endswith("-omp") else name
    if base in set(gpl_listed):
        return "gpl-style"
    if license_text is not None:
        return {"copyleft": "gpl-style", "restricted": "restricted"}.get(
            licence_file_class(license_text), "own-permissive")
    return "bsd3"


# --- the dry run ------------------------------------------------------------------------


def _join_continuations(text: str) -> list[str]:
    out, cur = [], ""
    for ln in text.splitlines():
        if ln.rstrip().endswith("\\"):
            cur += ln.rstrip()[:-1] + " "
            continue
        out.append(cur + ln)
        cur = ""
    if cur:
        out.append(cur)
    return out


def _split_command(line: str) -> list[str]:
    """Shell words of a command, up to the first shell operator."""
    try:
        toks = shlex.split(line, comments=False)
    except ValueError:
        toks = line.split()
    out = []
    for t in toks:
        if t in ("&&", "||", ";", "|", ">", ">>", "<", "2>", "2>&1", "&"):
            break
        out.append(t)
    return out


# a flag that takes its value as the next word
_SEPARATE = {"-D", "-U", "-I", "-isystem", "-include", "-o", "-L", "-l", "-x"}


def parse_dry_run(text: str) -> dict:
    """Read the commands ``make -n`` printed.

    Returns ``{"compiles": [{src, lang, defines, undefs, includes, std, include_files}],
    "link": {"libs", "libdirs", "output"} | None, "run": {"program", "args"} | None,
    "dropped": [flags], "compilers": [first words of commands that are no marker],
    "sources": [every source named]}``. A compile is a command whose first word is a
    marker and that names a source file; one without ``-c`` is a compile and a link."""
    compiles, link, run = [], None, None
    dropped: set = set()
    foreign: list = []
    outputs: list = []
    for ln in _join_continuations(text):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        toks = _split_command(s)
        if not toks:
            continue
        first = toks[0]
        if first in MARKS:
            comp = {"src": [], "defines": [], "undefs": [], "includes": [], "std": "",
                    "include_files": []}
            libs, libdirs, out = [], [], ""
            only_c = "-c" in toks
            i = 1
            while i < len(toks):
                t = toks[i]
                nxt = toks[i + 1] if i + 1 < len(toks) else ""
                if t in _SEPARATE and t != "-x":
                    val, i = nxt, i + 2
                    flag = t
                elif re.match(r"-(D|U|I|L|l)\S", t) or t.startswith("-isystem") and len(t) > 8:
                    flag, val, i = t[:2], t[2:], i + 1
                    if t.startswith("-isystem"):
                        flag, val = "-isystem", t[8:]
                else:
                    flag, val = t, ""
                    i += 1
                    if t.startswith("-std="):
                        comp["std"] = t[5:]
                        continue
                    if t == "-c":
                        continue
                    if not t.startswith("-"):
                        if Path(t).suffix in SOURCE_EXT:
                            comp["src"].append(t)
                        elif t.endswith(".o"):
                            pass
                        elif t in ("x",):
                            pass
                        continue
                    # a dropped flag; "-Xopenmp-target=..." and "-o" arguments consumed above
                    dropped.add(re.sub(r"=.*", "=...", t))
                    continue
                if flag == "-D":
                    comp["defines"].append(val)
                elif flag == "-U":
                    comp["undefs"].append(val)
                elif flag in ("-I", "-isystem"):
                    comp["includes"].append(val)
                elif flag == "-include":
                    comp["include_files"].append(val)
                elif flag == "-L":
                    libdirs.append(val)
                elif flag == "-l":
                    libs.append(val)
                elif flag == "-o":
                    out = val
                elif flag == "-x":
                    dropped.add("-x")
            if comp["src"]:
                for src in comp["src"]:
                    compiles.append({**{k: list(v) if isinstance(v, list) else v
                                        for k, v in comp.items() if k != "src"},
                                     "src": src})
            if out and not (only_c and comp["src"]):
                link = {"libs": libs, "libdirs": libdirs, "output": out}
                outputs.append(out)
            elif libs or libdirs:
                link = {"libs": libs, "libdirs": libdirs, "output": out or "a.out"}
            elif not only_c and comp["src"] and link is None:
                link = {"libs": [], "libdirs": [], "output": out or "a.out"}
            continue
        if first in ("rm", "echo", "cd", "mkdir", "cp", "mv", "cat", "test", "[", "true", ":"):
            continue
        m = re.match(r"(?:\./|\S*/)?([\w.+-]+)$", first)
        if first.startswith("./") or (outputs and Path(first).name == Path(outputs[-1]).name):
            run = {"program": Path(first).name, "args": toks[1:]}
            continue
        foreign.append(first)
    return {"compiles": compiles, "link": link, "run": run, "dropped": sorted(dropped),
            "compilers": sorted(set(foreign)),
            "sources": sorted({c["src"] for c in compiles})}


_REPEAT_RX = re.compile(
    r"\b\w*(?:repeat|iter|reps?|loops?|ntimes|nrun)\w*\s*=\s*(?:\([^)]*\)\s*)?"
    r"(?:std::)?(?:atoi|atol|atoll|stoi|stol|strtol|strtoul|stoul)\s*\(\s*(?:argv|args|av|v)\s*\[\s*(\d+)\s*\]",
    re.I)


def repeat_arg_index(source_texts) -> int | None:
    """The 1-based argument a repeat-like variable is read from, in the first
    source that reads one (``repeat = atoi(argv[2])``), else None."""
    for text in source_texts:
        m = _REPEAT_RX.search(text)
        if m:
            return int(m.group(1))
    return None


def apply_repeat(args: list[str], index: int | None, repeat: int = REPEAT) -> list[str]:
    if index is None or not (1 <= index <= len(args)):
        return list(args)
    out = list(args)
    out[index - 1] = str(repeat)
    return out


# --- what a benchmark needs -------------------------------------------------------------

SYSTEM_LIBS = {"m", "pthread", "dl", "rt", "stdc++", "c", "gomp", "omp"}
CUDA_INCLUDE = re.compile(
    r'#\s*include\s*[<"](?:cuda[\w./]*|cu(?:blas|fft|rand|sparse|solver|dnn|tensor)[\w./]*|thrust/[\w/.]+|'
    r'cub/[\w/.]+|nvtx[\w./]*|nccl[\w./]*|hip/[\w/.]+|hip[\w./]*|rocblas\S*|rocm\S*|nvml\S*|device_launch\S*)[>"]')
EXTERNAL_INCLUDE = re.compile(
    r'#\s*include\s*[<"](mpi\.h|opencv2?/[\w/.]+|boost/[\w/.]+|fftw3?\.h|mkl\w*\.h|cblas\.h|lapacke?\.h|'
    r'hdf5\.h|png\.h|jpeglib\.h|zlib\.h|gsl/[\w.]+|omp_ext\.h|Eigen/[\w/.]+|petsc\w*\.h|'
    r'curl/[\w.]+|sycl/[\w/.]+|CL/[\w.]+|tbb/[\w/.]+|libpng\S*|netcdf\.h|gmp\.h|mpfr\.h|'
    r'sqlite3\.h|openssl/[\w.]+|unistd\.h)[>"]')
EXTERNAL_INCLUDE_NOT = ("unistd.h",)          # POSIX: never external


def _file_like(arg: str) -> bool:
    if re.fullmatch(r"-?\d+(\.\d+)?([eE][-+]?\d+)?", arg) or arg.startswith("-"):
        return False
    return "/" in arg or bool(re.search(r"\.[A-Za-z][A-Za-z0-9]{0,3}$", arg))


def args_data_files(args: list[str], bench_dir: Path) -> tuple[list[str], list[str]]:
    """(the arguments that name a file, those of them missing) relative to the
    benchmark directory."""
    named = [a for a in args if _file_like(a)]
    # a file the program writes (out*, result*) is no input
    missing = [a for a in named if not (Path(bench_dir) / a).exists() and
               not re.match(r"(?i)(out|result)", Path(a).name) and not a.lower().endswith(".out")]
    return named, missing


def classify(recipe_parts: dict, texts: dict, bench_dir: Path, makefile_text: str) -> tuple[str, str]:
    """(status, reason) of a benchmark from its parsed dry run, the texts of
    its sources and local headers (name -> text), its directory and its Makefile."""
    comps = recipe_parts["compiles"]
    if not comps:
        return "no-recipe", "make -n printed no compile command"
    srcs = recipe_parts["sources"]
    if any(Path(s).suffix in CUDA_EXT for s in srcs):
        return "cuda-only-dependency", "a CUDA source file is in the build"
    if any(Path(s).suffix in F_EXT for s in srcs):
        return "other-language", "a Fortran source is in the build"
    foreign = [c for c in recipe_parts["compilers"]
               if re.search(r"nvcc|hipcc|mpi(cc|cxx|c\+\+|f90|run)|icpx|dpcpp|sycl|ifx", c)]
    if foreign:
        c = foreign[0]
        if re.search(r"nvcc|hipcc", c):
            return "cuda-only-dependency", f"the build calls {c}"
        return "needs-external-library", f"the build calls {c}"
    for name, text in texts.items():
        m = CUDA_INCLUDE.search(text)
        if m:
            return "cuda-only-dependency", f"{name} includes {m.group(0).split()[-1]}"
    link = recipe_parts["link"] or {}
    for lib in link.get("libs", []):
        if lib not in SYSTEM_LIBS:
            if re.match(r"cu|hip|nvrtc|nccl|rocm|roc|cudart|nvToolsExt", lib):
                return "cuda-only-dependency", f"links -l{lib}"
            return "needs-external-library", f"links -l{lib}"
    for name, text in texts.items():
        for m in EXTERNAL_INCLUDE.finditer(text):
            if m.group(1) not in EXTERNAL_INCLUDE_NOT:
                return "needs-external-library", f"{name} includes {m.group(1)}"
    run = recipe_parts.get("run")
    if run:
        named, missing = args_data_files(run["args"], bench_dir)
        if missing:
            return "needs-data-file", "the run arguments name " + ", ".join(missing[:3]) + \
                " (not in the repository)"
    fopens = _literal_data_files(texts, bench_dir)
    if fopens:
        return "needs-data-file", "the program opens " + ", ".join(fopens[:3]) + \
            " (not in the repository)"
    return "ok", ""


_FOPEN_RX = re.compile(r'(?:fopen|ifstream\s+\w+\s*\(|\.open)\s*\(?\s*"([^"%\\]+\.[A-Za-z0-9]{1,5})"\s*,?\s*(?:"r[b]?")?')


def _literal_data_files(texts: dict, bench_dir: Path) -> list[str]:
    """String-literal input files a program opens for reading that are not in the
    benchmark directory (a file the program writes is opened with "w"/"wb")."""
    out = []
    for name, text in texts.items():
        for m in re.finditer(r'fopen\s*\(\s*"([^"%\\]+)"\s*,\s*"(r|rb|rt)"\s*\)', text):
            f = m.group(1)
            if "/" in f or f.startswith("."):
                p = (Path(bench_dir) / f)
            else:
                p = Path(bench_dir) / f
            if not p.exists():
                out.append(f)
    return sorted(set(out))


# --- the recipe -------------------------------------------------------------------------

RECIPE_KEYS = ("dir", "id", "half", "licence", "status", "reason", "lang", "compiles", "libs",
               "libdirs", "std", "run_args", "repeat_arg", "program", "dropped")


def read_texts(bench_dir: Path, rel_sources: list[str]) -> dict:
    """The texts of the recipe's sources and the headers next to them."""
    out = {}
    bd = Path(bench_dir)
    names = list(rel_sources)
    names += sorted(p.name for p in bd.iterdir() if p.suffix in HEADER_EXT)
    for n in names:
        p = bd / n
        if p.is_file() and n not in out:
            out[n] = p.read_text(errors="replace")
    return out


def language_of(sources: list[str]) -> str:
    """``cpp`` when any source is C++, ``c`` when all are C."""
    if any(Path(s).suffix in CXX_EXT for s in sources):
        return "cpp"
    return "c"


def recipe_from(name: str, bench_dir: Path, dry_run: str, gpl_listed, license_text: str | None,
                makefile_text: str = "") -> dict:
    """The recipe of one benchmark from the dry run's text (see the module
    docstring for the procedure)."""
    parts = parse_dry_run(dry_run)
    texts = read_texts(bench_dir, parts["sources"])
    status, reason = classify(parts, texts, bench_dir, makefile_text)
    lic = licence_class(name, gpl_listed, license_text)
    run = parts["run"]
    main_srcs = parts["sources"]
    idx = repeat_arg_index(texts[s] for s in main_srcs if s in texts)
    args = apply_repeat(run["args"], idx) if run else []
    if run:
        # an argument that names a file of the repository is made relative to the
        # benchmark directory by the runner; keep it as the Makefile gives it
        pass
    std = next((c["std"] for c in parts["compiles"] if c["std"]), "")
    recipe = {
        "dir": name, "id": case_id(name), "half": half_of(name), "licence": lic,
        "status": status, "reason": reason,
        "lang": language_of(main_srcs) if main_srcs else "",
        "compiles": [{k: c[k] for k in ("src", "defines", "undefs", "includes", "std",
                                         "include_files") if c.get(k)} for c in parts["compiles"]],
        "libs": (parts["link"] or {}).get("libs", []),
        "libdirs": (parts["link"] or {}).get("libdirs", []),
        "std": std,
        "run_args": args, "repeat_arg": idx,
        "program": (parts["link"] or {}).get("output") or (run or {}).get("program", ""),
        "dropped": parts["dropped"],
    }
    return recipe


def recipe_for_tracking(recipe: dict) -> dict:
    """What a tracked file may hold: the whole recipe, except for a gpl-style
    benchmark, which is an id, its licence class, its half and its status."""
    if recipe["licence"] in WITHHELD:
        return {k: recipe[k] for k in ("dir", "id", "half", "licence", "status", "reason")}
    return recipe


def recipe_json(recipe: dict) -> str:
    return json.dumps(recipe, sort_keys=True)


# --- the oracle -------------------------------------------------------------------------

_TIMING = re.compile(r"time|elapsed|second|\bms\b|\bus\b|\bns\b|GB/s|GFlop|GFLOP|throughput|"
                     r"bandwidth|speed|perform|FPS|Mop|average|kernel execution|latency|"
                     r"\bsec\b|runtime|duration|rate|MB/s|Mpix|cycles|per second|/s\b", re.I)
_KEY = re.compile(r"checksum|check sum|\bsum\b|result|error|resid|norm|mismatch|diff|energy|"
                  r"total|max|min|value|output|answer|solution|verif|pass|fail|accuracy|"
                  r"correct|equal|match", re.I)
_NUM = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
FAIL_RX = re.compile(r"\bFAIL(?:ED|URE)?\b|mismatch(?:es)?\b(?!\s*[:=]\s*0\b)|verification\s+failed|"
                     r"\bincorrect\b|\bwrong\b|\bnot\s+match", re.I)
PASS_RX = re.compile(r"\bPASS(?:ED)?\b|verification\s+(?:passed|successful)|\bsuccess(?:ful(?:ly)?)?\b|"
                     r"\bcorrect\b|\bOK\b", re.I)


def significant_lines(text: str) -> list[str]:
    """Lines that carry a checked value: they name a result-like word and are not
    timings, in order."""
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if s and _KEY.search(s) and not _TIMING.search(s):
            out.append(s)
    return out


def numbers_of(line: str) -> list[float]:
    out = []
    for m in _NUM.finditer(line):
        try:
            out.append(float(m.group(0)))
        except ValueError:
            pass
    return out


def lines_agree(ref: list[str], got: list[str], rel: float = 1e-3, absolute: float = 1e-6) -> str | None:
    """None when every significant line of ``got`` equals the reference's line
    (words equal, numbers within ``rel``/``absolute``), else the first difference."""
    if len(ref) != len(got):
        return f"{len(got)} checked lines, the reference has {len(ref)}"
    for a, b in zip(ref, got):
        wa, wb = _NUM.sub("#", a), _NUM.sub("#", b)
        if wa != wb:
            return f"line differs: {b[:80]!r} against {a[:80]!r}"
        for x, y in zip(numbers_of(a), numbers_of(b)):
            if abs(x - y) > max(absolute, rel * max(abs(x), abs(y))):
                return f"value differs: {b[:80]!r} against {a[:80]!r}"
    return None


def oracle_kind(ref_out: str | None) -> str:
    """How a candidate's output is judged, from the serial host reference's output:
    ``self-check`` (the reference passes its own check: the candidate must too),
    ``lines`` (checked lines compared with the reference's), or ``none``."""
    if ref_out is None or FAIL_RX.search(ref_out):
        return "none"           # no reference, or the reference fails its own check: no oracle
    if PASS_RX.search(ref_out) and not FAIL_RX.search(ref_out) and re.search(r"\bPASS(ED)?\b|verification", ref_out, re.I):
        return "self-check"
    if significant_lines(ref_out):
        return "lines"
    return "none"


def judge_output(out: str, ref_out: str | None) -> tuple[bool, str]:
    """(ok, reason) of a run that exited 0: the benchmark's own verification
    text, then the checked lines against the serial host reference."""
    if FAIL_RX.search(out):
        line = next(ln for ln in out.splitlines() if FAIL_RX.search(ln))
        return False, f"check_fail: the benchmark printed {line.strip()[:120]!r}"
    kind = oracle_kind(ref_out)
    if kind == "self-check":
        if not re.search(r"\bPASS(ED)?\b|verification\s+(passed|successful)", out, re.I):
            return False, "check_fail: no PASS line printed (the reference prints one)"
        return True, "self-check: PASS"
    if kind == "lines":
        why = lines_agree(significant_lines(ref_out), significant_lines(out))
        if why:
            return False, f"check_fail: {why}"
        return True, "lines agree with the serial host reference"
    return True, "no oracle (exit 0, no failure text)"


# --- the files --------------------------------------------------------------------------


def load_split(path: Path = SPLIT) -> dict:
    return yaml.safe_load(Path(path).read_text())


def load_recipes(path: Path) -> dict:
    """id (directory name) -> recipe, from a recipes.yaml."""
    d = yaml.safe_load(Path(path).read_text())
    return {r["dir"]: r for r in d["benchmarks"]}


def clone_commit(clone: Path = CLONE) -> str:
    """The commit a clone is at (read from .git, no git command)."""
    git = Path(clone) / ".git"
    head = (git / "HEAD").read_text().strip()
    if head.startswith("ref: "):
        ref = git / head[5:]
        if ref.is_file():
            return ref.read_text().strip()
        for ln in (git / "packed-refs").read_text().splitlines():
            if ln.endswith(head[5:]):
                return ln.split()[0]
    return head
