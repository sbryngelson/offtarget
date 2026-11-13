"""The detectors behind tests/cluster/test_standing_rules.py: small functions from
text (or a parsed file) to the offending lines, each tested on a synthetic
violation in tests/cluster/test_standing_rules.py so a rule cannot silently stop
firing. The rules and the ratchet are in tests/standing_rules.py."""
from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.standing_rules import JOB_NAME, Line, pdebug_calls


# --- the flux queue rules ------------------------------------------------------

def pdebug_scan(lines: list[Line]) -> dict[str, str]:
    """rule id -> evidence for one file's logical lines: the first line that
    breaks pdebug-batch, pdebug-job-name or pdebug-chained."""
    found: dict[str, str] = {}

    def note(rule: str, ln: Line) -> None:
        found.setdefault(rule, f"{ln.path}:{ln.no}: {ln.text[:110]}")

    depth = 0
    code_hits = 0
    block_hits: dict[int, int] = {}
    for ln in lines:
        if ln.kind == "code":
            words = ln.text.split()
            if words and words[0] in ("for", "while", "until"):
                depth += 1
            if words and words[0] == "done":
                depth = max(0, depth - 1)
        calls = pdebug_calls(ln.text)
        if not calls:
            continue
        for sub, call in calls:
            if sub in ("batch", "submit", "bulksubmit"):
                note("pdebug-batch", ln)
            elif not JOB_NAME.search(call):
                note("pdebug-job-name", ln)
        if len(calls) > 1:
            note("pdebug-chained", ln)
        if ln.kind == "code":
            code_hits += 1
            if depth or code_hits > 1:
                note("pdebug-chained", ln)
        if ln.kind == "doc" and ln.block:
            block_hits[ln.block] = block_hits.get(ln.block, 0) + 1
            if block_hits[ln.block] > 1:
                note("pdebug-chained", ln)
    return found


MODULE_PIPE = re.compile(
    r"\bmodule\s+(?:load|swap|unload|purge|add|rm|use)\b"
    r"(?:[^;&\n|`]|&(?=\d)|&>)*\|(?!\|)")


def module_pipe(text: str) -> bool:
    return bool(MODULE_PIPE.search(text))


# --- git in the shared tree ---------------------------------------------------------

SHARED_TREE_NAMES = {"$MAIN", "${MAIN}", "$ROOT", "${ROOT}", ".", "$PWD",
                     "${PWD}", "$(pwd)", "$REPO", "${REPO}", "$TREE",
                     "${TREE}", "ROOT", "MAIN", "REPO", "TREE", "Path.cwd()",
                     "str(ROOT)", "str(MAIN)", "os.getcwd()"}
GIT_DESTRUCTIVE = ("stash", "checkout", "restore", "reset", "clean")
GIT_SHELL = re.compile(
    r"(?:^|[\s;&|(])git\s+(?:-C\s+(\S+)\s+)?(%s)\b" % "|".join(GIT_DESTRUCTIVE))


def git_destructive_shell(text: str) -> str | None:
    """The git subcommand when a shell line runs a destructive one in the
    current tree or in a named shared tree; None otherwise (-C <other tree>
    is another repository or the caller's own worktree)."""
    for m in GIT_SHELL.finditer(text):
        target = (m.group(1) or "").strip("\"'")
        if not m.group(1) or target in SHARED_TREE_NAMES:
            return m.group(2)
    return None


def git_destructive_argv(argv: list[str], cwd: str | None) -> str | None:
    if not argv or argv[0] != "git":
        return None
    i, target = 1, None
    while i < len(argv) and argv[i].startswith("-"):
        if argv[i] == "-C" and i + 1 < len(argv):
            target = argv[i + 1]
            i += 2
        else:
            i += 1
    if i < len(argv) and argv[i] in GIT_DESTRUCTIVE:
        if target is None and cwd is None:
            return argv[i]
        if (target or cwd) in SHARED_TREE_NAMES:
            return argv[i]
    return None


# --- filing externally ---------------------------------------------------------------

GH_WRITE = re.compile(
    r"\bgh\s+(?:"
    r"issue\s+(?:create|comment|edit|close|reopen|delete|transfer|lock|pin)"
    r"|pr\s+(?:create|comment|edit|close|merge|review|reopen|ready)"
    r"|release\s+(?:create|upload|edit|delete)"
    r"|gist\s+(?:create|edit|delete)"
    r"|repo\s+(?:create|delete|fork|edit|rename|sync)"
    r"|label\s+(?:create|edit|delete)|workflow\s+run"
    r"|api\b[^|;\n]*?(?:-X\s*(?:POST|PUT|PATCH|DELETE)"
    r"|--method[=\s]\s*(?:POST|PUT|PATCH|DELETE)|\s-[fF]\s|--field|"
    r"--raw-field|--input))", re.I)
CURL_WRITE = re.compile(
    r"\bcurl\b[^|;\n]*?(?:-X\s*(?:POST|PUT|PATCH|DELETE)"
    r"|--request[=\s]\s*(?:POST|PUT|PATCH|DELETE)|\s--data\S*|\s-d\s|\s-F\s"
    r"|--form|--upload-file|\s-T\s|--json)")
MAIL_CMD = re.compile(r"(?:^|[|;&(]\s*)(?:mail|mailx|sendmail|mutt|msmtp)\s")
GIT_PUSH = re.compile(r"(?:^|[\s;&|(])git\s+(?:-C\s+\S+\s+)?push\b")


def external_write_line(text: str) -> str | None:
    for name, rx in (("gh", GH_WRITE), ("curl", CURL_WRITE),
                     ("mail", MAIL_CMD), ("git push", GIT_PUSH)):
        if rx.search(text):
            return name
    return None


def external_write_python(path: Path) -> list[tuple[int, str]]:
    """Calls in a Python file that send something to a remote host: an HTTP
    method other than GET, a request body, a mail client."""
    try:
        tree = ast.parse(Path(path).read_text(errors="replace"))
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names]
            mod = getattr(node, "module", None) or ""
            if any(n.split(".")[0] == "smtplib" for n in names + [mod]):
                out.append((node.lineno, "smtplib"))
        if isinstance(node, ast.Call):
            f = ast.unparse(node.func)
            kw = {k.arg for k in node.keywords}
            if re.search(r"\b(requests|session|httpx)\.(post|put|patch|delete)$",
                         f):
                out.append((node.lineno, f))
            elif f.endswith(("urlopen", "Request")) and kw & {"data", "method"}:
                out.append((node.lineno, f + "(data/method)"))
            elif f.endswith((".request", ".putrequest")) and node.args and \
                    isinstance(node.args[0], ast.Constant) and \
                    str(node.args[0].value).upper() in (
                        "POST", "PUT", "PATCH", "DELETE"):
                out.append((node.lineno, f + f"({node.args[0].value})"))
    return out


# --- bounded waits ---------------------------------------------------------------------

BOUND = re.compile(
    r"date\s+\+%s|\bSECONDS\b|\btimeout\b|\bDEADLINE\b|\bdeadline\b|"
    r"\bleft\b|\bremaining\b|\bEND\b|\w+_END\b|"
    r"\(\(\s*\w+(?:\+\+|--)|\(\([^)]*(?:\+\+|--|\+=)[^)]*\)\)|\bseq\b")
TRUEISH = re.compile(r"^while\s+(?:true|:|\[\s*1\s*\]|\[\[\s*1\s*\]\]|"
                     r"\(\(\s*1\s*\)\))\s*(?:;|$)")


def shell_wait_loops(text: str) -> list[tuple[int, str]]:
    """(line, loop head) of shell loops that wait without a bound: `while
    true`/`while :`/`until ...`, or any while/until loop that sleeps, whose
    head and body carry no deadline (date +%s, SECONDS, a counter, timeout)."""
    lines = text.splitlines()
    out = []
    for i, raw in enumerate(lines):
        s = raw.strip()
        if s.startswith("#") or not re.match(r"(?:while|until)\b", s):
            continue
        depth, body = 0, []
        for j in range(i, len(lines)):
            t = lines[j].strip()
            if t.startswith("#"):
                continue
            if re.match(r"(?:for|while|until)\b", t):
                depth += 1
            if re.match(r"done\b", t):
                depth -= 1
                if depth == 0:
                    break
            body.append(t)
        block = "\n".join(body)
        waits = bool(TRUEISH.match(s)) or s.startswith("until") or \
            re.search(r"\bsleep\b", block)
        if waits and not BOUND.search(block):
            out.append((i + 1, s))
    return out


def python_wait_loops(path: Path) -> list[tuple[int, str]]:
    """`while True` loops that sleep with no clock, deadline or attempt
    counter in the body."""
    try:
        tree = ast.parse(Path(path).read_text(errors="replace"))
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.While):
            src = ast.unparse(node)
            const_true = isinstance(node.test, ast.Constant) and node.test.value
            if "sleep(" in src and const_true and not re.search(
                    r"monotonic|time\.time|deadline|timeout|attempt|tries|"
                    r"range\(", src):
                out.append((node.lineno, "while True with sleep"))
    return out


# --- legality prose of the findings --------------------------------------------------

LEGAL_START = re.compile(
    r"^\s*(?:!|//|\*)\s*(?:-\s*)?(?:legality|Legal[A-Za-z0-9 .]*)\s*:\s*(.*)$")
LEGAL_CONT = re.compile(r"^\s*(?:!|//)\s*(?!- |\s*$)(\S.*)$")   # not a new bullet, not blank


def legality_blocks(text: str) -> list[tuple[int, str]]:
    """(line, text) of every legality statement in a finding's header: the
    `- legality:` line (or a fuzz header's `Legal OpenMP 5.2:` paragraph)
    with the comment lines that continue it (up to a blank comment line, a
    new `- ` bullet or the first line of code)."""
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        m = LEGAL_START.match(lines[i])
        if not m:
            i += 1
            continue
        blk, j = [m.group(1)], i + 1
        while j < len(lines):
            c = LEGAL_CONT.match(lines[j])
            if not c:
                break
            blk.append(c.group(1))
            j += 1
        out.append((i + 1, " ".join(blk)))
        i = j
    return out


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;])\s+", text) if s.strip()]


GCC_TOKEN = re.compile(r"\b(?:GCC|gfortran|gcc)\b(?!\s+cells)")
GCC_DENIED = re.compile(
    r"no (?:compiler under test, )?(?:gfortran|gcc|GCC)|"
    r"(?:GCC|gcc|gfortran)\b[^.;]*\b(?:is|are) (?:a compiler under test|no |"
    r"never)|never a (?:legality )?witness|"
    r"neither GCC|is no legality|not a (?:legality )?witness|no witness|"
    r"without OpenMP|base language|base-language|-std=|under_test_only|"
    r"withdr(?:ew|awn)", re.I)


def gcc_as_witness(text: str) -> list[str]:
    """The sentences of a legality statement that name GCC or gfortran
    when the statement never says GCC is no witness (or that it was
    withdrawn as one)."""
    if GCC_DENIED.search(text):
        return []
    return [s for s in sentences(text) if GCC_TOKEN.search(s)]


FAMILY_TOKEN = {
    "afar": re.compile(r"AFAR|flang|clang"),
    "cce": re.compile(r"\bCCE\b|crayftn|craycc"),
    "nvhpc": re.compile(r"NVHPC|nvfortran|\bnvc\b"),
}
WITNESS_VERB = re.compile(
    r"front[- ]?end|-fsyntax-only|compiles? (?:it|only)|compile-only", re.I)
NOT_A_WITNESS = re.compile(
    r"not counted|not under test|no witness|not a witness|neither|own front "
    r"end|\bits own\b|never|compiler under test|\bis no\b|no compiler|"
    r"other famil|not a legality|shared|reject|rather than|unsupported|"
    r"no verdict|has not|not been run", re.I)


def families_under_test(name: str, head: str) -> set[str]:
    """The compiler families a finding is about, from its file name
    (afar-..., cce19-..., nvhpc-..., clang-...) or a fuzz header's
    `! toolchain:` line."""
    n = Path(name).name
    fams = set()
    for fam in FAMILY_TOKEN:
        if n.startswith(fam) or re.search(r"-%s[0-9_a-z]*\." % fam, n):
            fams.add(fam)
    if n.startswith("afar-cce"):
        fams |= {"afar", "cce"}
    if n.startswith("clang"):
        fams.add("afar")
    m = re.search(r"toolchain: *(\w+)", head)
    if m:
        t = m.group(1)
        fams.add("nvhpc" if t.startswith("nvhpc") else
                 re.sub(r"[0-9_].*", "", t))
    return fams & set(FAMILY_TOKEN)


def own_family_witness(name: str, text: str) -> list[str]:
    """Legality sentences that name a front end of a family the finding is
    about as accepting the program."""
    fams = families_under_test(name, text[:3000])
    bad = []
    for _, blk in legality_blocks(text):
        for s in sentences(blk):
            for fam in fams:
                if FAMILY_TOKEN[fam].search(s) and WITNESS_VERB.search(s) \
                        and not NOT_A_WITNESS.search(s):
                    bad.append(f"{fam}: {s[:110]}")
    return bad


# --- site copy ---------------------------------------------------------------------------

FIRST_PERSON = re.compile(r"(?<![-\w/])(?:we|We|our|Our|ours|us|Us|I|my|My)(?![-\w/])")   # I/O is no pronoun


def first_person(text: str) -> list[str]:
    return [m.group(0) for m in FIRST_PERSON.finditer(text)]


def html_text(html: str) -> str:
    """Visible copy of a page: tags, scripts, styles and program and code
    blocks (compiler output and sources, not copy) removed."""
    t = re.sub(r"<(script|style|pre|code|template)\b.*?</\1>", " ", html,
               flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)


def js_strings(js: str) -> list[str]:
    """The string literals of a script, without its comments."""
    js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    js = re.sub(r"(?m)(^|\s)//.*$", " ", js)
    return [m.group(0)[1:-1] for m in re.finditer(
        r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|`(?:[^`\\]|\\.)*`", js)]


def python_strings(path: Path) -> list[tuple[int, str]]:
    """String constants of a Python file that are not docstrings."""
    tree = ast.parse(Path(path).read_text())
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and node.body and \
                isinstance(node.body[0], ast.Expr) and \
                isinstance(node.body[0].value, ast.Constant) and \
                isinstance(node.body[0].value.value, str):
            docs.add(id(node.body[0].value))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docs]


# --- AI attribution in commit messages --------------------------------------------------

ATTRIBUTION = re.compile(
    r"^\s*(?:co-authored-by:.*(?:claude|anthropic|\bai\b|\bllm\b|gpt|copilot|"
    r"openai|gemini)|generated (?:with|by)\b.*(?:claude|anthropic|\bAI\b|"
    r"\bLLM\b|copilot|chatgpt|gemini)|.*noreply@anthropic\.com.*|"
    r".*\U0001F916.*)$", re.I | re.M)


# --- tracked symlinks -------------------------------------------------------------------------

def tracked_symlinks(root: Path) -> list[tuple[str, str]]:
    """[(path, target)] of every symlink in the tree of HEAD (git mode 120000)."""
    import subprocess
    r = subprocess.run(["git", "-C", str(root), "ls-tree", "-r", "-z", "HEAD"],
                       capture_output=True, text=True, timeout=120)
    out = []
    for ent in r.stdout.split("\0"):
        if not ent.startswith("120000 "):
            continue
        meta, path = ent.split("\t", 1)
        sha = meta.split()[2]
        tgt = subprocess.run(["git", "-C", str(root), "cat-file", "blob", sha],
                             capture_output=True, text=True, timeout=60).stdout
        out.append((path, tgt))
    return out


def symlink_offenders(links: list[tuple[str, str]]) -> dict[str, str]:
    """A symlink at the repository root (a worktree's results/spec/corpus links: merging a
    branch that tracks one replaces the shared directory of the same name, the .gitignore
    having made git treat its files as expendable) or one with an absolute target (it
    names a place on one machine)."""
    found = {}
    for path, tgt in links:
        if "/" not in path:
            found[path] = f"{path} -> {tgt}: a tracked symlink at the repository root"
        elif tgt.startswith("/"):
            found[path] = f"{path} -> {tgt}: a tracked symlink with an absolute target"
    return found
