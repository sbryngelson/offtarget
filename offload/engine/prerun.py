"""The pre-run legality and race check of a generated program.

``check(program) -> (ok, reasons)``: a fuzz, stress or reproducer program is
compiled and run only when ``ok``. Legality needs two witnesses that are not
the compiler under test, and both must accept: ``rules`` (the rules of
``offload.engine.rules``, the checks in ``EXTRA`` and the race rule) and
``frontend`` (``amdflang`` or ``amdclang`` with ``-fsyntax-only``). A
program is refused when no front end is available (``witness unavailable``),
when the witnesses disagree (``witnesses disagree``) or when the rules
cannot read it (``unreadable``). A refusal by the front end alone carries
``FRONTEND_ONLY`` and is listed in the reports (``refusal_kind``).
The race rule (``races``) reports a scalar written in a loop shared by
threads, teams or gangs that no clause privatizes or reduces. ``EXTRA``
holds restrictions ``offload.engine.rules`` does not check, one rule id each."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

RACE_CITE = ("OpenMP 5.2 §1.4.1 p.27 (a data race: the result is "
             "unspecified), §5.1.1, §5.8.1")
ACC_RACE_CITE = "OpenACC 3.4 §2.9.15 (independent loop iterations)"


# --- the program ------------------------------------------------------------------

# AFAR's amdclang has no openacc.h: the C OpenACC witness reads the
# declarations the programs use (fix, item 10; the program compiled
# and run is unchanged)
# Guarded (a converted program includes openacc.h twice: its own
# include and its self-check's) and the whole OpenACC 3.4 C API (§3.2),
# so a program calling acc_copyin is not refused for an implicit
# declaration of the stub's making
_ACC_PROTOS = """
typedef enum { acc_device_none = 0, acc_device_default = 1,
  acc_device_host = 2, acc_device_not_host = 3 } acc_device_t;
typedef enum { acc_property_memory = 1, acc_property_free_memory = 2,
  acc_property_shared_memory_support = 3, acc_property_name = 4,
  acc_property_vendor = 5, acc_property_driver = 6 } acc_device_property_t;
enum { acc_async_noval = -1, acc_async_sync = -2, acc_async_default = -3 };
int acc_get_num_devices(acc_device_t);
void acc_set_device_type(acc_device_t);
acc_device_t acc_get_device_type(void);
void acc_set_device_num(int, acc_device_t);
int acc_get_device_num(acc_device_t);
size_t acc_get_property(int, acc_device_t, acc_device_property_t);
const char *acc_get_property_string(int, acc_device_t, acc_device_property_t);
void acc_init(acc_device_t); void acc_init_device(int, acc_device_t);
void acc_shutdown(acc_device_t); void acc_shutdown_device(int, acc_device_t);
int acc_async_test(int); int acc_async_test_device(int, int);
int acc_async_test_all(void); int acc_async_test_all_device(int);
void acc_wait(int); void acc_wait_device(int, int);
void acc_wait_async(int, int); void acc_wait_device_async(int, int, int);
void acc_wait_all(void); void acc_wait_all_device(int);
void acc_wait_all_async(int); void acc_wait_all_device_async(int, int);
void acc_async_wait(int); void acc_async_wait_all(void);
int acc_get_default_async(void); void acc_set_default_async(int);
int acc_on_device(acc_device_t);
void *acc_malloc(size_t); void acc_free(void *);
void *acc_copyin(void *, size_t); void acc_copyin_async(void *, size_t, int);
void *acc_create(void *, size_t); void acc_create_async(void *, size_t, int);
void *acc_present_or_copyin(void *, size_t); void *acc_pcopyin(void *, size_t);
void *acc_present_or_create(void *, size_t); void *acc_pcreate(void *, size_t);
void acc_copyout(void *, size_t); void acc_copyout_async(void *, size_t, int);
void acc_copyout_finalize(void *, size_t);
void acc_copyout_finalize_async(void *, size_t, int);
void acc_delete(void *, size_t); void acc_delete_async(void *, size_t, int);
void acc_delete_finalize(void *, size_t);
void acc_delete_finalize_async(void *, size_t, int);
void acc_update_device(void *, size_t);
void acc_update_device_async(void *, size_t, int);
void acc_update_self(void *, size_t); void acc_update_self_async(void *, size_t, int);
void acc_map_data(void *, void *, size_t); void acc_unmap_data(void *);
void *acc_deviceptr(void *); void *acc_hostptr(void *);
int acc_is_present(void *, size_t);
void acc_memcpy_to_device(void *, void *, size_t);
void acc_memcpy_to_device_async(void *, void *, size_t, int);
void acc_memcpy_from_device(void *, void *, size_t);
void acc_memcpy_from_device_async(void *, void *, size_t, int);
void acc_memcpy_device(void *, void *, size_t);
void acc_memcpy_device_async(void *, void *, size_t, int);
void acc_memcpy_d2d(void *, void *, size_t, int, int);
void acc_memcpy_d2d_async(void *, void *, size_t, int, int, int);
void acc_attach(void **); void acc_attach_async(void **, int);
void acc_detach(void **); void acc_detach_async(void **, int);
void acc_detach_finalize(void **); void acc_detach_finalize_async(void **, int);
"""
ACC_H_STUB = ("#ifndef HV_OPENACC_STUB\n#define HV_OPENACC_STUB\n"
              "#include <stddef.h>\n" + _ACC_PROTOS.strip() + "\n#endif")


def _acc_c_stub(files, lang, model):
    if lang != "c" or model != "acc":
        return files
    return [(n, re.sub(r"^\s*#\s*include\s*<openacc\.h>",
                       lambda m: ACC_H_STUB, t, flags=re.M))
            for n, t in files]


def _files_of(program) -> tuple[list, str, str, int]:
    files, lang, model, version = _files_of_raw(program)
    return _acc_c_stub(files, lang, model), lang, model, version


def _files_of_raw(program) -> tuple[list, str, str, int]:
    """(files [(name, text)], lang, model, version) of a stress program
    (``files``), a fuzz program (``source``), a confirmer ProgramRef
    (``text``, file marks) or a (text, lang) pair."""
    if isinstance(program, tuple):
        # (text, lang[, model[, version]])
        text, lang = program[0], program[1]
        model = program[2] if len(program) > 2 and program[2] else \
            _model_of(text)
        files = _split(text) or [("prog.c" if lang == "c" else "prog.f90",
                                  text)]
        v = program[3] if len(program) > 3 and program[3] else 52
        return files, lang, model, 34 if model == "acc" else v
    if hasattr(program, "files") and program.files:
        lang = getattr(program, "lang", "f90")
        model = getattr(program, "model", "omp")
        return list(program.files), lang, model, \
            34 if model == "acc" else 52
    text = getattr(program, "text", None) or getattr(program, "source", "")
    lang = getattr(program, "lang", "f90")
    lang = "c" if lang == "c" else "f90"
    model = getattr(program, "model", None) or _model_of(text)
    files = _split(text) or [("prog.c" if lang == "c" else "prog.f90",
                              text)]
    v = getattr(program, "version", 0) or 52
    return files, lang, model, 34 if model == "acc" else v


def _split(text: str):
    from offload.engine.confirm.programs import split_files
    return split_files(text)


def _model_of(text: str) -> str:
    acc = re.search(r"^\s*(?:!\$acc|#\s*pragma\s+acc)\b", text, re.M | re.I)
    omp = re.search(r"^\s*(?:!\$omp|#\s*pragma\s+omp)\b", text, re.M | re.I)
    return "acc" if acc and not omp else "omp"


def _sources(files, lang) -> list[str]:
    """The texts the rules read: Fortran files joined in compile order;
    each C file with its local headers inlined."""
    if lang == "c":
        heads = {n: t for n, t in files if n.endswith(".h")}
        out = []
        for n, t in files:
            if n.endswith(".c"):
                for h, ht in heads.items():
                    t = t.replace(f'#include "{h}"', ht)
                out.append(t)
        return out
    return ["\n".join(t for n, t in files if not n.endswith(".h"))]


# --- witness 1: offload.engine.rules, EXTRA and the race rule ---------------------------

def rules_witness(program) -> tuple[bool | None, list[str]]:
    """(accepted, reasons): None when the rules cannot read the program
    (a grammar or scanner limit: no verdict)."""
    from offload.engine.grammar import GrammarError
    from offload.engine.rules import ProgramError, parse_program, violations
    files, lang, model, version = _files_of(program)
    reasons: list[str] = []
    for text in _sources(files, lang):
        try:
            tree = parse_program(text, version, "c" if lang == "c" else
                                 None)
        except (GrammarError, ProgramError) as e:
            return None, [f"rules: cannot read it: {type(e).__name__}: "
                          f"{str(e).splitlines()[0][:200]}"]
        except Exception as e:      # a scanner limit is no verdict either
            return None, [f"rules: cannot read it: {type(e).__name__}: "
                          f"{str(e)[:200]}"]
        found = violations(tree, version)
        reasons += [f"rules: violates {r}" for r in found]
        reasons += [f"race: {r}" for r in races(tree, text, lang)]
        reasons += [f"restriction: {r}" for r in extra(text, lang, tree)]
    return not reasons, reasons


# --- the race rule --------------------------------------------------------------------

_OMP_THREADED = {"parallel", "do", "for", "loop", "distribute", "taskloop"}
_PROTECT = ("atomic", "critical", "single", "masked", "master", "ordered")
_DSA = ("private", "firstprivate", "lastprivate", "reduction", "linear",
        "in_reduction", "task_reduction", "copyprivate", "induction")
_F_ASSIGN = re.compile(r"^\s*(?:\d+\s+)?([a-z_]\w*)\s*=(?!=)(.*)$", re.I)
_F_DO = re.compile(r"^\s*(?:\w+\s*:\s*)?do\s+(?:concurrent\s*\(\s*)?"
                   r"([a-z_]\w*)\s*=", re.I)
_C_ASSIGN = re.compile(r"(?<![\w.\]>])([A-Za-z_]\w*)\s*([-+*/%&|^]|<<|>>)?="
                       r"(?!=)")
_C_INCR = re.compile(r"(?:(?<![\w.\]>])([A-Za-z_]\w*)\s*(?:\+\+|--))|"
                     r"(?:(?:\+\+|--)\s*([A-Za-z_]\w*))")
_C_FOR = re.compile(r"\bfor\s*\(\s*(?:[A-Za-z_][\w\s\*]*\s)?([A-Za-z_]\w*)"
                    r"\s*=")
_C_DECL = re.compile(r"\b(?:int|long|double|float|char|short|bool|_Bool|"
                     r"unsigned|signed|size_t|int64_t|int32_t|uint64_t|"
                     r"uint32_t|const|struct\s+\w+)\b[\w\s\*]*?\b"
                     r"([A-Za-z_]\w*)\s*(?:=|;|\[|,)")


def _children(tree) -> dict:
    kids: dict[int, list] = {}
    for p, c in tree.nesting:
        kids.setdefault(p, []).append(c)
    return kids


def _parents(tree) -> dict:
    return {c: p for p, c in tree.nesting}


def _descendants(kids, i) -> list:
    out, todo = [], list(kids.get(i, ()))
    while todo:
        k = todo.pop()
        out.append(k)
        todo += kids.get(k, ())
    return out


class _AllBut(set):
    """Every name but the ones a shared clause lists (a default(private) or
    default(firstprivate) clause privatizes the rest)."""

    def __init__(self, shared):
        super().__init__()
        self.shared = set(shared)

    def __contains__(self, name) -> bool:
        return name not in self.shared

    def __ior__(self, other):
        return self


def _dsa_names(d) -> set:
    out = set()
    for c in d.clauses:
        if c.name == "default" and any(a.strip().lower() in (
                "private", "firstprivate") for a in c.args):
            shared = set()
            for c2 in d.clauses:
                if c2.name == "shared":
                    shared |= {a.strip().lower() for a in c2.args}
            return _AllBut(shared)
    for c in d.clauses:
        if c.name in _DSA:
            for a in c.args:
                m = re.match(r"\s*(?:[\w+*\-.]+\s*:\s*)*([A-Za-z_]\w*)",
                             a.strip())
                if m:
                    out.add(m.group(1).lower())
    return out


def _threaded(tree, i, model: str) -> bool:
    d = tree.directives[i]
    leaves = d.name.split()
    if model == "acc":
        if "loop" not in leaves or any(c.name == "seq" for c in d.clauses):
            return False
        if leaves[0] in ("kernels", "serial"):
            return False        # kernels: the compiler decides
        # a loop inside a kernels or serial construct: not a race
        par = _parents(tree)
        k = i
        while k in par:
            k = par[k]
            name = tree.directives[k].name.split()[0]
            if name in ("kernels", "serial"):
                return False
            if name == "parallel":
                return True
        return leaves[0] == "parallel"
    return bool(_OMP_THREADED & set(leaves))


def _scalar(tree, name: str) -> bool:
    """Not declared anywhere as an array, pointer, allocatable or derived
    type (an undeclared name is taken as a scalar)."""
    for (s, n), attr in tree.decls.items():
        if n == name and attr in ("pointer", "allocatable"):
            return False
    if any(n == name for (_, n) in tree.arrays):
        return False
    if any(n == name for (_, n) in tree.vartypes):
        return False
    return True


def races(tree, text: str, lang: str) -> list[str]:
    """The race rule (module docstring) on one parsed source."""
    lines = text.splitlines()
    model = "acc" if tree.directives and tree.directives[0].atoms and \
        next(iter(tree.directives[0].atoms)).startswith("acc.") else None
    if model is None:
        model = "acc" if re.search(r"^\s*(?:!\$acc|#\s*pragma\s+acc)\b",
                                   text, re.M | re.I) else "omp"
    kids = _children(tree)
    par = _parents(tree)
    out = []
    for i, d in enumerate(tree.directives):
        a = tree.assoc[i]
        if a.kind != "loop" or not a.end_line or not _threaded(tree, i,
                                                               model):
            continue
        priv = _dsa_names(d)
        nested = _descendants(kids, i)
        for k in nested:
            more = _dsa_names(tree.directives[k])
            priv = more if isinstance(more, _AllBut) else priv | more
        leaves = d.name.split()
        if model == "omp" and not (set(leaves) & {"parallel", "do", "for",
                                                  "loop", "taskloop"}):
            # a distribute loop: one thread per team runs it; the
            # enclosing teams construct may privatize
            k = i
            while k in par:
                k = par[k]
                if "teams" in tree.directives[k].name.split():
                    priv |= _dsa_names(tree.directives[k])
                    break
        if model == "acc":
            k = i
            while k in par:
                k = par[k]
                priv |= _dsa_names(tree.directives[k])
                if tree.directives[k].name.split()[0] == "parallel":
                    break
        protected = []
        for k in nested:
            if tree.directives[k].name.split()[0] in _PROTECT:
                b = tree.assoc[k]
                # an atomic without an end directive protects the next
                # statement
                protected.append((b.line, (b.end_line or b.line + 1) +
                                  (1 if lang == "c" else 0)))
        first = a.line
        # Fortran: up to the END DO; C: the loop's last line included
        body = range(first + 1, a.end_line + (1 if lang == "c" else 0))
        found = _writes(lines, body, lang, protected)
        loopvars = {v.lower() for v in a.loop_vars}
        for name, (ln, update) in sorted(found.items()):
            low = name.lower()
            if low in priv or low in loopvars or not _scalar(tree, low):
                continue
            if model == "acc" and not update:
                continue        # OpenACC privatizes scalars by analysis
            kind = "updated (x = x op ...)" if update else "written"
            cite = ACC_RACE_CITE if model == "acc" else RACE_CITE
            out.append(f"line {ln}: {name} is {kind} in every iteration of "
                       f"'{d.name}' (line {first}) and no clause makes it "
                       f"private or a reduction: {cite}")
        if model == "omp":
            out += array_races(tree, text, lang, lines, body, d, a, priv,
                               protected)
    return out


# --- array and aliasing races ----------------------------------

_F_ARR_W = re.compile(r"^\s*([a-z_]\w*)\s*\(([^=]*)\)\s*=(?!=)(.*)$", re.I)
_C_ARR_W = re.compile(r"(?<![\w.>])([A-Za-z_]\w*)\s*\[([^\]]*)\]\s*"
                      r"([-+*/%&|^]?)=(?!=)")
_C_LOCAL_ARRAY = re.compile(
    # no static or extern: a variable with static storage duration declared
    # inside the construct is shared (5.2 §5.1.1 p.98 l.1)
    r"^(?:(?:const|volatile|register|unsigned|signed|long|short)\s+)*"
    r"(?:int|long|double|float|char|short|bool|_Bool|size_t|"
    r"u?int(?:8|16|32|64)_t|struct\s+\w+|[A-Za-z_]\w*_t)\s*\**\s*"
    r"([A-Za-z_]\w*)\s*\[")
_OFFSET = re.compile(r"^([A-Za-z_]\w*)\s*(?:([+-])\s*(\d+))?$")


def _statements(lines, body, lang, protected) -> list[tuple[int, str, bool]]:
    """(line, statement, guarded) of the loop body, outside protected
    regions; Fortran continuations joined, C split at ';'."""
    out, stmt, start, in_if = [], "", 0, 0
    for ln in body:
        if ln - 1 >= len(lines):
            break
        if any(a < ln <= b for a, b in protected):
            continue
        raw = lines[ln - 1]
        if lang == "c":
            code = re.sub(r"//.*$", "", raw)
            if code.strip().startswith("#"):
                continue
            guarded = re.search(r"\bif\b", code) is not None
            for part in re.split(r"[;{}]", code):
                if part.strip():
                    out.append((ln, part.strip(), guarded))
            continue
        if raw.lstrip().lower().startswith(("!$omp", "!$acc")):
            continue
        code = raw.split("!")[0]
        if not code.strip():
            continue
        if not stmt:
            start = ln
        stmt = (stmt + " " + code.rstrip().rstrip("&")) if stmt else \
            code.rstrip().rstrip("&")
        if code.rstrip().endswith("&"):
            continue
        st, stmt = stmt.strip(), ""
        low = st.lower()
        if re.match(r"^(\w+\s*:\s*)?if\s*\(.*\)\s*then\b", low):
            in_if += 1
            continue
        if re.match(r"^end\s*if\b", low):
            in_if = max(0, in_if - 1)
            continue
        guarded = in_if > 0
        mi = re.match(r"^if\s*\((.*)\)\s*(?!then\b)(\w.*)$", st, re.I)
        if mi and "=" in mi.group(2):
            st, guarded = mi.group(2), True
        out.append((start, st, guarded))
    return out


def _ids(text: str) -> set:
    return {x.lower() for x in re.findall(r"[A-Za-z_]\w*", text or "")}


def _array_name(tree, name: str) -> bool:
    low = name.lower()
    if any(n == low for (_, n) in tree.arrays):
        return True
    return any(n == low and attr in ("allocatable", "pointer")
               for (_, n), attr in tree.decls.items())


def _components(sub: str) -> list | None:
    """[(var, offset)] of a subscript of plain `v`, `v+c`, `v-c` forms."""
    parts = _split_top(sub)
    out = []
    for p in parts:
        m = _OFFSET.match(p.strip())
        if not m:
            return None
        off = int(m.group(3) or 0) * (-1 if m.group(2) == "-" else 1)
        out.append((m.group(1).lower(), off))
    return out


_C_COUNTER = r"[\w\[\].>-]+"
_C_LOCAL_DECL = r"^\s*(?:const\s+|static\s+|volatile\s+)*(?:unsigned\s+|signed\s+)?" \
                r"(?:long\s+long|int|long|short|char|size_t|u?int\d+_t)\s+\**%s\b"


def _step(*groups) -> int:
    """The constant step of a counter update, 0 when there is none (a step of 0 hands every
    iteration the same value)."""
    for g in groups:
        if g:
            return int(g)
    return 0


def _c_atomic_blocks(lines, rows):
    """[(kind, counter, variable, step, rows)] of the C `atomic capture` blocks (kind
    "capture") and plain `atomic` / `atomic update` statements (kind "update") of the region
    that change a counter by a constant."""
    out = []
    x = _C_COUNTER
    for k, ln in enumerate(rows):
        if ln - 1 >= len(lines):
            break
        raw = lines[ln - 1].strip()
        cap = re.match(r"#\s*pragma\s+omp\s+atomic\b.*\bcapture\b", raw)
        upd = re.match(r"#\s*pragma\s+omp\s+atomic(?:\s+update)?\s*$", raw)
        if not (cap or upd):
            continue
        for n in range(1, 6):
            used = rows[k + 1:k + 1 + n]
            if len(used) < n:
                break
            blk = " ".join(lines[r - 1].strip() for r in used if r - 1 < len(lines))
            if cap:
                pats = ((rf"\{{\s*(\w+)\s*=\s*({x})\s*;\s*\2\s*(?:\+=\s*(\d+)|=\s*\2\s*\+\s*(\d+))\s*;\s*\}}",
                         lambda m: (m.group(1), m.group(2), _step(m.group(3), m.group(4)))),
                        (rf"\{{\s*({x})\s*(?:\+=\s*(\d+)|=\s*\1\s*\+\s*(\d+))\s*;\s*(\w+)\s*=\s*\1\s*;\s*\}}",
                         lambda m: (m.group(4), m.group(1), _step(m.group(2), m.group(3)))),
                        (rf"(\w+)\s*=\s*({x})\+\+\s*;", lambda m: (m.group(1), m.group(2), 1)),
                        (rf"(\w+)\s*=\s*\+\+({x})\s*;", lambda m: (m.group(1), m.group(2), 1)))
                for pat, get in pats:
                    m = re.fullmatch(pat, blk)
                    if m:
                        v, cx, st = get(m)
                        out.append(("capture", cx.replace(" ", "").lower(), v.lower(), st, [ln, *used]))
                        break
                else:
                    continue
                break
            for pat, get in ((rf"({x})\s*\+=\s*(\d+)\s*;", lambda m: (m.group(1), _step(m.group(2)))),
                             (rf"({x})\s*=\s*\1\s*\+\s*(\d+)\s*;", lambda m: (m.group(1), _step(m.group(2)))),
                             (rf"({x})\+\+\s*;", lambda m: (m.group(1), 1)),
                             (rf"\+\+({x})\s*;", lambda m: (m.group(1), 1))):
                m = re.fullmatch(pat, blk)
                if m:
                    cx, st = get(m)
                    out.append(("update", cx.replace(" ", "").lower(), None, st, [ln, *used]))
                    break
            else:
                continue
            break
    return out


def _f_atomic_blocks(lines, rows):
    """The same for Fortran: `!$omp atomic capture` ... `!$omp end atomic` and a plain
    `!$omp atomic` / `atomic update` statement."""
    out = []
    for k, ln in enumerate(rows):
        if ln - 1 >= len(lines):
            break
        raw = lines[ln - 1].strip()
        cap = re.match(r"!\$omp\s+atomic\s+capture\b", raw, re.I)
        upd = re.match(r"!\$omp\s+atomic(?:\s+update)?\s*$", raw, re.I)
        if not (cap or upd):
            continue
        blk, used = [], [ln]
        for r in rows[k + 1:k + 4]:
            t = lines[r - 1].strip()
            if re.match(r"!\$omp\s+end\s+atomic", t, re.I):
                used.append(r)
                break
            if t and not t.startswith("!"):
                blk.append(t.split("!")[0].strip())
                used.append(r)
            if upd and blk:
                break
        parts = [tuple(x.strip().lower() for x in b.split("=", 1)) for b in blk if "=" in b]

        def step(lhs, rhs):
            m = re.fullmatch(rf"{re.escape(lhs)}\s*\+\s*(\d+)|(\d+)\s*\+\s*{re.escape(lhs)}", rhs)
            return _step(*m.groups()) if m else None
        if upd and len(parts) == 1:
            st = step(*parts[0])
            if st is not None:
                out.append(("update", parts[0][0].replace(" ", ""), None, st, used))
        elif cap and len(parts) == 2:
            (l1, r1), (l2, r2) = parts
            if step(l1, r1) is not None and r2 == l1 and re.fullmatch(r"\w+", l2):
                out.append(("capture", l1.replace(" ", ""), l2, step(l1, r1), used))   # x = x + c; v = x
            elif step(l2, r2) is not None and r1 == l2 and re.fullmatch(r"\w+", l1):
                out.append(("capture", l2.replace(" ", ""), l1, step(l2, r2), used))   # v = x; x = x + c
    return out


def _claimed_slots(lines, body, lang, priv=()) -> set:
    """Names that hold a value an atomic capture of a counter handed out: the
    variable `v` of `atomic capture` blocks `x = x + c; v = x` or `v = x;
    x = x + c` (C: `{ v = x; x += c; }`, `v = x++;`). The atomic regions on
    `x` exclude each other (OpenMP 5.2 15.8.4 p.311: 'atomic regions enforce
    exclusive access ... among all threads in the binding thread set without
    regard to the teams'), so no two executions capture the same value of a
    counter that only moves up: an element indexed by `v` is written by one
    iteration. That holds only when

    * the step `c` is a constant above 0 (with 0 every capture returns the
      same value);
    * the counter is shared: not in a private, firstprivate, lastprivate,
      linear or reduction clause (`priv`), and not declared in the region
      (each thread would count on its own copy);
    * every other access to the counter in the region is an atomic update or
      capture with a positive constant step (a plain or atomic write, or a
      read, could move it back or make the captured values repeat)."""
    rows = list(body)
    blocks = (_c_atomic_blocks if lang == "c" else _f_atomic_blocks)(lines, rows)
    out = set()
    for x in {b[1] for b in blocks if b[0] == "capture"}:
        base = re.match(r"[A-Za-z_]\w*", x)
        if not base:
            continue
        base = base.group(0)
        if base in priv:
            continue
        if lang == "c" and any(re.match(_C_LOCAL_DECL % re.escape(base), lines[r - 1])
                               for r in rows if r - 1 < len(lines)):
            continue
        good = set()
        for kind, cx, v, st, used in blocks:
            if cx == x and st > 0:
                good.update(used)
        word = re.compile(rf"\b{re.escape(base)}\b", 0 if lang == "c" else re.I)
        stray = False
        for r in rows:
            if r - 1 >= len(lines) or r in good:
                continue
            raw = lines[r - 1]
            if lang == "c" and r >= 2 and lines[r - 2].rstrip().endswith("\\"):
                continue                    # the construct's own continued pragma line: its clauses are `priv`
            if lang != "c" and re.match(r"\s*!\$omp\s*&", raw, re.I):
                continue
            code = raw.split("//")[0] if lang == "c" else (raw if raw.lstrip().startswith("!$") else raw.split("!")[0])
            if word.search(code):
                stray = True
                break
        if stray:
            continue
        out |= {b[2] for b in blocks if b[0] == "capture" and b[1] == x and b[3] > 0}
    return out


def array_races(tree, text, lang, lines, body, d, a, priv,
                protected) -> list[str]:
    """Array elements that the iterations of a threaded loop share:
    (1) an element written at a subscript that depends on no loop
    variable of the loop (every iteration writes it); (2) a loop-carried
    dependence: an element written at `a(i+c)` and read at `a(i+c')` in
    another iteration; (3) aliasing: an array written through a pointer
    that names it (Fortran `p => a`, C `p = a` / `p = &a[k]`) and read
    or written under its own name at another subscript. Privatized and
    reduction arrays, protected regions and one-iteration writes under an
    IF are skipped."""
    stmts = _statements(lines, body, lang, protected)
    # the loop variables the construct associates (collapse, ordered);
    # the parser lists every variable of the nest
    n = 1
    for c in d.clauses:
        if c.name in ("collapse", "ordered") and c.args:
            try:
                n = max(n, int(str(c.args[0]).strip()))
            except ValueError:
                pass
    loopvars = {v.lower() for v in list(a.loop_vars)[:n]}
    # names that carry the loop's iteration: loop variables and scalars
    # computed from them in the body (out(lin) with lin = (i-1)*n + j)
    dep = set(loopvars) | _claimed_slots(lines, body, lang, priv)
    changed = True
    while changed:
        changed = False
        for _, st, _ in stmts:
            # an inner loop whose bounds carry the iteration carries it too
            # (do i = lo, hi with lo from the parallel loop's c); one with
            # constant bounds does not: every iteration writes its range
            m = re.match(r"^\s*(?:do\s+|for\s*\(\s*(?:[A-Za-z_][\w ]*\s)?)"
                         r"([A-Za-z_]\w*)\s*=(?!=)(.*)$", st, re.I) or \
                re.match(r"^\s*([A-Za-z_]\w*)\s*=(?!=)(.*)$", st)
            if m and m.group(1).lower() not in dep and \
                    _ids(m.group(2)) & dep:
                dep.add(m.group(1).lower())
                changed = True
    writes, reads = [], []
    for ln, st, guarded in stmts:
        if lang == "c":
            for m in _C_ARR_W.finditer(st):
                writes.append((ln, m.group(1), m.group(2), guarded,
                               bool(m.group(3))))
            rhs = st.split("=", 1)[-1] if "=" in st else st
            for m in re.finditer(r"([A-Za-z_]\w*)\s*\[([^\]]*)\]", rhs):
                reads.append((ln, m.group(1), m.group(2)))
        else:
            m = _F_ARR_W.match(st)
            if m and _array_name(tree, m.group(1)):
                writes.append((ln, m.group(1), m.group(2), guarded,
                               re.search(rf"\b{m.group(1)}\s*\(",
                                         m.group(3), re.I) is not None))
                rhs = m.group(3)
            else:
                rhs = st.split("=", 1)[-1] if "=" in st else st
            for r in re.finditer(r"([A-Za-z_]\w*)\s*\(([^()]*)\)", rhs):
                if _array_name(tree, r.group(1)):
                    reads.append((ln, r.group(1), r.group(2)))
    alias = _aliases(text, lang)
    cite = RACE_CITE
    out, seen = [], set()
    # An array declared in the loop body is private to each
    # iteration (5.2 §5.1.1: a variable declared in a scope inside the
    # construct); its initializer writes no shared element
    local = set()
    if lang == "c":
        for _, st, _ in stmts:
            m = _C_LOCAL_ARRAY.match(st)
            if m:
                local.add(m.group(1).lower())
    for ln, name, sub, guarded, update in writes:
        low = name.lower()
        if low in priv or low in local:
            continue
        if not (_ids(sub) & dep):
            if guarded and not update:
                continue
            key = ("same", low)
            if key not in seen:
                seen.add(key)
                out.append(f"line {ln}: {name}({sub.strip()}) is written in "
                           f"every iteration of '{d.name}' (line {a.line}): "
                           f"the subscript depends on no loop variable: "
                           f"{cite}")
            continue
        wc = _components(sub)
        for rl, rname, rsub in reads:
            rlow = rname.lower()
            other = rlow != low and (alias.get(low) == rlow or
                                     alias.get(rlow) == low)
            if rlow != low and not other:
                continue
            if rlow in priv or " ".join(rsub.split()) == \
                    " ".join(sub.split()):
                continue
            rc = _components(rsub)
            if wc is None or rc is None or len(wc) != len(rc):
                continue
            if all(w[0] == r[0] for w, r in zip(wc, rc)) and any(
                    w[0] in loopvars and w[1] != r[1]
                    for w, r in zip(wc, rc)):
                key = ("carried", low, rlow)
                if key in seen:
                    continue
                seen.add(key)
                how = (f"through the alias {name} of {rname}" if other else
                       "a loop-carried dependence")
                out.append(f"line {ln}: {name}({sub.strip()}) is written and "
                           f"{rname}({rsub.strip()}) read in other "
                           f"iterations of '{d.name}' (line {a.line}): "
                           f"{how}: {cite}")
    return out


def _aliases(text: str, lang: str) -> dict:
    """pointer name -> the array it is pointed at (lower case)."""
    out = {}
    if lang == "c":
        for m in re.finditer(r"\*\s*([A-Za-z_]\w*)\s*=\s*&?\s*([A-Za-z_]\w*)"
                             r"\s*(?:\[[^\]]*\])?\s*;", text):
            out[m.group(1).lower()] = m.group(2).lower()
        for m in re.finditer(r"(?<![\w*])([A-Za-z_]\w*)\s*=\s*&\s*"
                             r"([A-Za-z_]\w*)\s*\[", text):
            out[m.group(1).lower()] = m.group(2).lower()
    else:
        for m in re.finditer(r"\b([A-Za-z_]\w*)\s*=>\s*([A-Za-z_]\w*)",
                             text):
            out[m.group(1).lower()] = m.group(2).lower()
    return out


def _writes(lines: list[str], body, lang: str, protected) -> dict:
    """name -> (first line, is an update) of the scalars assigned in the
    body lines, outside protected ranges, Fortran BLOCKs and inner DO
    variables / C declarations of the body. A plain write under an IF
    (``if (i == 1) x = ...``: possibly one iteration) is not counted; an
    update under an IF is (several iterations may take it)."""
    found: dict[str, tuple] = {}
    local, loopv = set(), set()
    in_block = 0
    in_if = 0
    cstack: list[bool] = []       # C: is each open brace an if/else block
    stmt = ""
    for ln in body:
        if ln - 1 >= len(lines):
            break
        raw = lines[ln - 1]
        if any(a < ln <= b for a, b in protected):
            continue
        if lang == "c":
            code = re.sub(r"//.*$", "", raw)
            if code.strip().startswith("#"):
                continue
            for m in _C_FOR.finditer(code):
                loopv.add(m.group(1))
            for m in _C_DECL.finditer(code):
                local.add(m.group(1))
            guarded = any(cstack) or re.search(r"\b(?:if|else)\b",
                                                code) is not None
            for m in _C_ASSIGN.finditer(code):
                name, op = m.group(1), m.group(2)
                if name in ("if", "for", "while", "return"):
                    continue
                rhs = code[m.end():]
                upd = bool(op) or re.search(rf"\b{re.escape(name)}\b",
                                            rhs) is not None
                if upd or not guarded:
                    _add(found, name, ln, upd)
            for m in _C_INCR.finditer(code):
                _add(found, m.group(1) or m.group(2), ln, True)
            for ch_i, ch in enumerate(code):
                if ch == "{":
                    cstack.append(re.search(r"\b(?:if|else)\b",
                                            code[:ch_i]) is not None
                                  or bool(cstack and cstack[-1]))
                elif ch == "}" and cstack:
                    cstack.pop()
            continue
        code = raw.split("!")[0] if not raw.lstrip().lower().startswith(
            ("!$omp", "!$acc")) else ""
        if not code.strip():
            continue
        stmt = (stmt + " " + code.rstrip().rstrip("&")) if stmt else \
            code.rstrip().rstrip("&")
        if code.rstrip().endswith("&"):
            continue
        s, stmt = stmt.strip(), ""
        low = s.lower()
        if re.match(r"^(\w+\s*:\s*)?block\b", low):
            in_block += 1
            continue
        if re.match(r"^end\s*block\b", low):
            in_block -= 1
            continue
        m = _F_DO.match(s)
        if m:
            loopv.add(m.group(1).lower())
            continue
        if in_block:
            continue
        if re.match(r"^(\w+\s*:\s*)?if\s*\(.*\)\s*then\b", low) or \
                re.match(r"^(\w+\s*:\s*)?select\s*(case|type)\b", low):
            in_if += 1
            continue
        if re.match(r"^end\s*(if|select)\b", low):
            in_if = max(0, in_if - 1)
            continue
        guarded = in_if > 0
        # a one-line IF: its action statement
        mi = re.match(r"^if\s*\((.*)\)\s*(?!then\b)(\w.*)$", s, re.I)
        if mi and "=" in mi.group(2) and not re.match(
                r"^then\b", mi.group(2), re.I):
            s = mi.group(2)
            guarded = True
        m = _F_ASSIGN.match(s)
        if m:
            name = m.group(1)
            upd = re.search(rf"\b{re.escape(name)}\b", m.group(2),
                            re.I) is not None
            if upd or not guarded:
                _add(found, name, ln, upd)
    for n in list(found):
        if n in local or n in loopv or n.lower() in loopv:
            del found[n]
    return found


def _add(found, name, ln, upd):
    if name in found:
        old = found[name]
        found[name] = (old[0], old[1] or upd)
    else:
        found[name] = (ln, upd)


# --- the restriction checks offload.engine.rules lacks -------------------------------------

EXTRA_CITES = {
    "uses-allocators-traits-constant":
        "OpenMP 5.2 §6.8 p.181 l.16-17 (\"With this syntax, traits must be "
        "a constant array with constant values\"), p.182 l.18-19",
    "alloc-in-target-predefined":
        "OpenMP 5.2 §18.13.6 p.429 l.21-26 (\"Unless dynamic_allocators "
        "appears on a requires directive in the same compilation unit, "
        "omp_alloc and omp_aligned_alloc invocations that appear in target "
        "regions must not pass omp_null_allocator as the allocator "
        "argument, which must be a constant expression that evaluates to "
        "one of the predefined memory allocator values. The alignment "
        "argument to omp_aligned_alloc must be a power of two and the size "
        "argument must be a multiple of alignment.\")",
    "declare-target-module-variable":
        "OpenMP 5.2 §13.8 p.286 l.31-32 (\"A variable referenced in a "
        "target region but not the target construct that is not declared "
        "in the target region must appear in a declare target directive.\")",
    "acc-loop-reduction-data-clause":
        "OpenACC 3.4 §2.6.2 p.42 l.1403-1409 (\"If a scalar variable "
        "appears in a reduction clause on a loop construct that has a "
        "parent parallel or serial construct, and if the reduction's access "
        "to the original variable is exposed to the parent compute "
        "construct, the variable must appear either in an explicit data "
        "clause visible at the compute construct or in a firstprivate, "
        "private, or reduction clause on the compute construct.\")",
}

_PREDEFINED_ALLOC = re.compile(r"^omp_(?:default|large_cap|const|high_bw|"
                               r"low_lat|cgroup|pteam|thread)_mem_alloc$")


def _directives(text: str, lang: str, model: str) -> list[tuple]:
    """(first line, last line, lower-cased directive text) of every
    directive of `model` (continuations joined)."""
    out = []
    lines = text.splitlines()
    k = 0
    pre = (rf"^\s*#\s*pragma\s+{model}\b" if lang == "c" else
           rf"^\s*!\${model}\b")
    while k < len(lines):
        if re.match(pre, lines[k], re.I):
            start, body = k, lines[k]
            if lang == "c":
                while body.rstrip().endswith("\\") and k + 1 < len(lines):
                    k += 1
                    body = body.rstrip()[:-1] + " " + lines[k]
                body = re.sub(rf"^\s*#\s*pragma\s+{model}\s*", "", body,
                              flags=re.I)
            else:
                body = re.sub(rf"^\s*!\${model}&?\s*", "", body, flags=re.I)
                while body.rstrip().endswith("&") and k + 1 < len(lines):
                    k += 1
                    nxt = re.sub(rf"^\s*!\${model}&?\s*", "", lines[k],
                                 flags=re.I)
                    body = body.rstrip()[:-1] + " " + nxt.lstrip("&")
                body = body.split("!")[0]
            out.append((start + 1, k + 1, " ".join(body.lower().split())))
        k += 1
    return out


def _clause_args(d: str, name: str) -> list[str]:
    out = []
    for m in re.finditer(rf"\b{name}\s*\(", d):
        depth, j = 1, m.end()
        while j < len(d) and depth:
            depth += {"(": 1, ")": -1}.get(d[j], 0)
            j += 1
        out.append(d[m.end():j - 1])
    return out


def _split_top(s: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
            continue
        depth += {"(": 1, ")": -1, "[": 1, "]": -1}.get(ch, 0)
        cur += ch
    out.append(cur)
    return [x.strip() for x in out if x.strip()]


def _regions(text: str, lang: str, dirs: list, opener: str) -> list[tuple]:
    """(first, last) line ranges of the constructs whose directive starts
    with `opener` (Fortran: up to the end directive or, for a loop
    construct, the END DO of its loop; C: the following statement or
    brace block)."""
    lines = text.splitlines()
    out = []
    for first, last, d in dirs:
        if not re.match(rf"^{opener}\b", d):
            continue
        if opener == "target" and re.match(
                r"^target\s*(?:data|enter|exit|update)\b", d):
            continue        # a data construct or standalone: no region
        if lang == "c":
            out.append((first, _c_extent(lines, last)))
        else:
            out.append((first, _f_extent(lines, last, d)))
    return out


def _c_extent(lines, last) -> int:
    k = last          # 0-based index of the line after the pragma
    depth, seen = 0, False
    while k < len(lines):
        code = re.sub(r"//.*$", "", lines[k])
        for ch in code:
            if ch == "{":
                depth += 1
                seen = True
            elif ch == "}":
                depth -= 1
        if seen and depth <= 0:
            return k + 1
        if not seen and code.strip().endswith(";") and depth == 0 and \
                not code.strip().startswith(("for", "while", "if")):
            return k + 1
        k += 1
    return len(lines)


# the words of a construct's name (a clause ends it: ``target map(...)`` is
# a target construct; the extent had run to the end of the file)
_CONSTRUCT_WORDS = {
    "target", "teams", "distribute", "parallel", "do", "for", "simd", "loop",
    "data", "task", "taskloop", "sections", "section", "single", "masked",
    "master", "critical", "ordered", "atomic", "workshare", "scope",
    "taskgroup", "kernels", "serial", "host_data", "workdistribute",
    "enter", "exit", "update"}


def _construct_name(d: str) -> list[str]:
    """The leading words of a directive that name its construct."""
    out = []
    for w in re.split(r"[\s,(]+", d.strip()):
        if w.lower() not in _CONSTRUCT_WORDS:
            break
        out.append(w.lower())
    return out


def _f_extent(lines, last, d) -> int:
    name = _construct_name(d) or d.split("(")[0].split()[:1]
    head = " ".join(w for w in name[:4])
    k = last
    if re.search(r"\b(?:do|loop|distribute|simd|taskloop)\b", head) and \
            not re.search(r"\b(?:data|update|enter|exit)\b", head):
        depth = 0
        while k < len(lines):
            s = lines[k].split("!")[0].strip().lower()
            if re.match(r"^(\w+\s*:\s*)?do\b", s):
                depth += 1
            elif re.match(r"^end\s*do\b", s) or re.match(r"^\d+\s+continue",
                                                         s):
                depth -= 1
                if depth <= 0:
                    return k + 1
            k += 1
        return len(lines)
    words = head.split()
    pat = re.compile(r"^\s*!\$(?:omp|acc)\s+end\s*" + r"\s*".join(
        re.escape(w) for w in words[:2]) + r"\b", re.I)
    while k < len(lines):
        if pat.match(lines[k]):
            return k + 1
        k += 1
    return len(lines)


def extra(text: str, lang: str, tree=None) -> list[str]:
    """The EXTRA restriction checks on one source: '<id>: <what> (<cite>)'
    for each violation."""
    out = []
    model = _model_of(text)
    if model == "omp":
        dirs = _directives(text, lang, "omp")
        out += _traits_constant(text, lang, dirs)
        out += _alloc_in_target(text, lang, dirs)
        if lang != "c":
            out += _module_variables(text, dirs)
    else:
        out += _acc_reduction(text, lang)
    return out


def _cite(rid: str) -> str:
    return f"{rid}: " + "{} (" + EXTRA_CITES[rid] + ")"


def _traits_constant(text, lang, dirs) -> list[str]:
    out = []
    for first, _, d in dirs:
        for arg in _clause_args(d, "uses_allocators"):
            if ":" in arg.split("(")[0]:
                continue          # the 5.2 modifier form: offload.engine.rules
            for item in _split_top(arg):
                m = re.fullmatch(r"([a-z_]\w*)\s*\(\s*([a-z_]\w*)\s*\)", item)
                if not m:
                    continue
                t = m.group(2)
                if lang == "c":
                    const = re.search(rf"\bconst\b[^;]*\b{t}\s*\[", text,
                                      re.I)
                else:
                    const = re.search(rf"\bparameter\b[^\n]*::[^\n]*\b{t}\b",
                                      text, re.I)
                if not const:
                    out.append(_cite("uses-allocators-traits-constant")
                               .format(f"line {first}: traits array {t} of "
                                       f"uses_allocators({item}) is not a "
                                       "constant array"))
    return out


def _alloc_in_target(text, lang, dirs) -> list[str]:
    if any(re.match(r"^requires\b.*\bdynamic_allocators\b", d)
           for _, _, d in dirs):
        return []
    lines = text.splitlines()
    regions = _regions(text, lang, dirs, "target")
    out = []
    call = re.compile(r"\bomp_(aligned_alloc|alloc)\s*\(", re.I)
    for a, b in regions:
        body = "\n".join(lines[a:b])
        for m in call.finditer(body):
            depth, j = 1, m.end()
            while j < len(body) and depth:
                depth += {"(": 1, ")": -1}.get(body[j], 0)
                j += 1
            args = _split_top(body[m.end():j - 1].replace("\n", " ")
                              .replace("&", " "))
            ln = a + body[:m.start()].count("\n") + 1
            if not args:
                continue
            alloc = args[-1].strip()
            why = []
            if not _PREDEFINED_ALLOC.match(alloc.lower()):
                why.append(f"allocator {alloc} is not a predefined "
                           "allocator")
            if m.group(1).lower() == "aligned_alloc" and len(args) >= 3:
                al, size = args[0].strip(), args[1].strip()
                if al.isdigit() and (int(al) & (int(al) - 1)):
                    why.append(f"alignment {al} is not a power of two")
                sz = re.fullmatch(r"(\d+)", size)
                if al.isdigit() and int(al) and (
                        (sz and int(sz.group(1)) % int(al)) or
                        (not sz and re.fullmatch(r"sizeof\s*\(\s*(int|float|"
                                                 r"double|long|char)\s*\)",
                                                 size) and int(al) > 8)):
                    why.append(f"size {size} is not a multiple of the "
                               f"alignment {al}")
            if why:
                out.append(_cite("alloc-in-target-predefined").format(
                    f"line {ln}: omp_{m.group(1)} in a target region without"
                    " requires dynamic_allocators: " + "; ".join(why)))
    return out


def _module_variables(text, dirs) -> list[str]:
    """Fortran: module variables referenced in a module procedure that is
    called in a target region (or declared target) without being in a
    declare target directive."""
    if any(re.match(r"^requires\b.*\bunified_shared_memory\b", d)
           for _, _, d in dirs):
        return []
    lines = text.splitlines()
    low = [ln.split("!")[0].lower() if not re.match(
        r"^\s*!\$omp", ln, re.I) else "" for ln in lines]
    # declare target lists (every form) and the procedures declared target
    declared, dt_procs = set(), set()
    for first, _, d in dirs:
        if not d.startswith("declare target"):
            continue
        rest = d[len("declare target"):]
        names = re.findall(r"[a-z_]\w*", re.sub(r"\b(?:to|enter|link|"
                                                 r"device_type|indirect|"
                                                 r"any|host|nohost)\b", " ",
                                                 rest))
        declared |= set(names)
        if not names:
            dt_procs.add(first)       # in a procedure's specification part
    out = []
    mods = list(re.finditer(r"^\s*module\s+(?!procedure\b)([a-z_]\w*)\s*$",
                            "\n".join(low), re.M))
    for mm in mods:
        start = "\n".join(low)[:mm.start()].count("\n")
        end, contains = len(low), None
        for k in range(start + 1, len(low)):
            if re.match(r"^\s*end\s*module\b", low[k]):
                end = k
                break
            if contains is None and re.match(r"^\s*contains\s*$", low[k]):
                contains = k
        if contains is None:
            continue
        mvars = set()
        stmt = ""
        skip = 0          # inside a derived type definition or interface
        for k in range(start + 1, contains):
            s = low[k].strip()
            if not s:
                continue
            if re.match(r"^(?:abstract\s+)?interface\b", s) or re.match(
                    r"^type\s*(?:,[^:]*)?(?:::)?\s*[a-z_]\w*\s*$", s) or \
                    re.match(r"^type\s*,", s) and "::" in s and "(" not in \
                    s.split("::")[0].replace("extends(", "").replace(
                        "bind(", ""):
                skip += 1
                continue
            if re.match(r"^end\s*(?:type|interface)\b", s):
                skip = max(0, skip - 1)
                continue
            if skip:
                continue
            stmt = (stmt + " " + s.rstrip("&")) if stmt else s.rstrip("&")
            if s.endswith("&"):
                continue
            s, stmt = stmt, ""
            m = re.match(r"^(integer|real|double\s*precision|logical|"
                         r"complex|character|type\s*\(|class\s*\()", s)
            if not m or "parameter" in s.split("::")[0]:
                continue
            ents = s.split("::", 1)[1] if "::" in s else s[m.end():]
            ents = re.sub(r"\([^()]*(?:\([^()]*\)[^()]*)*\)", "", ents)
            ents = re.sub(r"=[^,]*", "", ents)
            mvars |= {e.strip() for e in ents.split(",")
                      if re.fullmatch(r"[a-z_]\w*", e.strip())}
        mvars -= declared
        if not mvars:
            continue
        # module procedures
        procs = []
        k = contains + 1
        while k < end:
            m = re.match(r"^\s*(?:(?:pure|elemental|recursive|impure|"
                         r"module)\s+)*(?:[a-z0-9_*()]+\s+)*?(subroutine|"
                         r"function)\s+([a-z_]\w*)\s*(\(([^)]*)\))?",
                         low[k])
            if m:
                kind, name = m.group(1), m.group(2)
                args = {a.strip() for a in (m.group(4) or "").split(",")}
                j = k + 1
                while j < end and not re.match(
                        rf"^\s*end\s*{kind}\b", low[j]) and not (
                        re.match(r"^\s*end\s*$", low[j])):
                    j += 1
                procs.append((name, k, j, args))
                k = j
            k += 1
        target_lines = [ab for ab in _regions(text, "f90", dirs, "target")]
        for name, a, b, args in procs:
            called = any(re.search(rf"\b(?:call\s+)?{name}\s*\(",
                                   "\n".join(low[x:y])) for x, y in
                         target_lines)
            marked = any(a < ln - 1 < b for ln in dt_procs)
            if not (called or marked):
                continue
            body = "\n".join(low[a + 1:b])
            local = set()
            for s in body.splitlines():
                if "::" in s and re.match(r"^\s*(integer|real|double|"
                                          r"logical|complex|character|"
                                          r"type|class)", s):
                    ents = re.sub(r"\([^()]*(?:\([^()]*\)[^()]*)*\)", "",
                                  s.split("::", 1)[1])
                    local |= {e.strip().split("=")[0].strip()
                              for e in ents.split(",")}
            # names, not components (s%c)
            ident = r"(?<![%\w])([a-z_]\w*)\b"
            used = set(re.findall(ident, body)) | (
                set(re.findall(ident, low[a])) - {name} - args)
            bad = sorted((used & mvars) - local - args)
            if bad:
                out.append(_cite("declare-target-module-variable").format(
                    f"line {a + 1}: {name} ({'called in a target region' if called else 'declare target'}) "
                    f"references the module variables {', '.join(bad)}, "
                    "which no declare target directive names"))
    return out


_ACC_DATA = ("copy", "copyin", "copyout", "create", "present", "no_create",
             "deviceptr", "attach", "pcopy", "pcopyin", "pcopyout",
             "pcreate", "present_or_copy", "present_or_copyin",
             "present_or_copyout", "present_or_create")


def _names_in(d: str, clauses) -> set:
    out = set()
    for c in clauses:
        for arg in _clause_args(d, c):
            arg = re.sub(r"^\s*(?:readonly|zero)\s*:", "", arg)
            arg = re.sub(r"^[^:()]*:", "", arg) if c in (
                "reduction",) else arg
            for item in _split_top(arg):
                m = re.match(r"([a-z_]\w*)", item.strip())
                if m:
                    out.add(m.group(1))
    return out


def _acc_reduction(text, lang) -> list[str]:
    dirs = _directives(text, lang, "acc")
    lines = text.splitlines()
    computes = []           # (first, last, directive)
    for first, last, d in dirs:
        if re.match(r"^(parallel|serial)\b(?!\s+loop)", d):
            ext = _c_extent(lines, last) if lang == "c" else \
                _f_extent(lines, last, d)
            computes.append((first, ext, d))
    datas = []
    for first, last, d in dirs:
        if re.match(r"^(data|declare|enter data)\b", d):
            ext = (_c_extent(lines, last) if lang == "c" else
                   _f_extent(lines, last, d)) if d.startswith("data") \
                else len(lines)
            datas.append((first, ext, d))
    out = []
    for first, _, d in dirs:
        if not re.match(r"^loop\b", d) or "reduction" not in d:
            continue
        parent = [c for c in computes if c[0] < first <= c[1]]
        if not parent:
            continue
        cf, cl, cd = max(parent, key=lambda c: c[0])
        visible = _names_in(cd, _ACC_DATA + ("firstprivate", "private",
                                             "reduction"))
        for a, b, dd in datas:
            if a <= cf <= b:
                visible |= _names_in(dd, _ACC_DATA)
        for v in sorted(_names_in(d, ("reduction",)) - visible):
            if _is_array(text, v, lang):
                continue
            out.append(_cite("acc-loop-reduction-data-clause").format(
                f"line {first}: {v} is in a loop reduction inside the "
                f"compute construct of line {cf} with no data clause for it"
                " there"))
    return out


def _is_array(text, v, lang) -> bool:
    if lang == "c":
        return re.search(rf"\b{v}\s*\[", text) is not None
    for s in text.lower().splitlines():
        if "::" in s and re.search(rf"\b{v}\b", s.split("::", 1)[1]):
            if "dimension" in s.split("::")[0] or re.search(
                    rf"\b{v}\s*\(", s.split("::", 1)[1]):
                return True
    return False


# --- witness 2: the front end -----------------------------------------------------------

def openacc_stub(texts) -> str:
    """A declarations-only Fortran ``openacc`` module for the front end
    (AFAR flang has no openacc.mod: "OpenACC is NOT supported for
    AMDGPU"), with the names of the OpenACC API the program uses: device
    kinds as named constants, acc_on_device / acc_is_present as logical
    functions, acc_get_* as integer functions, the other routines as
    external procedures. Base-language declarations only; the directives
    are what the front end checks."""
    names = set()
    for t in texts:
        names |= {n.lower() for n in re.findall(r"\b(acc_\w+)", t, re.I)}
    lines = ["module openacc", "  implicit none",
             "  integer, parameter :: acc_device_kind = 4",
             "  integer, parameter :: acc_handle_kind = 4"]
    k = 0
    for n in sorted(names):
        if n in ("acc_device_kind", "acc_handle_kind"):
            continue
        if n in ("acc_on_device", "acc_is_present", "acc_async_test",
                 "acc_async_test_all", "acc_async_test_device",
                 "acc_async_test_all_device"):
            lines.append(f"  logical, external :: {n}")
        elif n.startswith(("acc_device_", "acc_async_", "acc_property_")):
            lines.append(f"  integer(acc_device_kind), parameter :: {n} "
                         f"= {k}")
            k += 1
        elif n in ("acc_on_device", "acc_is_present", "acc_async_test",
                   "acc_async_test_all"):
            lines.append(f"  logical, external :: {n}")
        elif n.startswith(("acc_get_", "acc_deviceptr", "acc_hostptr")):
            lines.append(f"  integer, external :: {n}")
        else:
            lines.append(f"  external :: {n}")
    return "\n".join(lines + ["end module openacc", ""])

def frontend_witness(program, timeout_s: int = 600
                     ) -> tuple[bool | None, list[str]]:
    """(accepted, reasons) of the flang or clang front end; None when it
    cannot run here (no AFAR install, or a checker failure)."""
    from offload.engine import harness
    from offload.engine.toolchains import AFAR_BIN
    files, lang, model, version = _files_of(program)
    tool = f"{AFAR_BIN}/amdclang" if lang == "c" else f"{AFAR_BIN}/amdflang"
    if not Path(tool).exists():
        return None, [f"frontend: {Path(tool).name} not installed here"]
    flag = "-fopenacc" if model == "acc" else \
        f"-fopenmp -fopenmp-version={version if version != 34 else 52}"
    std = "-std=c11 " if lang == "c" else ""
    with tempfile.TemporaryDirectory(prefix="prerun_") as d:
        for name, text in files:
            (Path(d) / name).write_text(text)
        order = [n for n, _ in files]
        if model == "acc" and lang != "c" and not any(
                re.search(r"^\s*module\s+openacc\b", t, re.I | re.M)
                for _, t in files):
            (Path(d) / "openacc_stub.f90").write_text(
                openacc_stub([t for _, t in files]))
            order.insert(0, "openacc_stub.f90")
        for name in order:
            if not name.endswith((".c", ".f90", ".F90")):
                continue
            ex = harness._execute(f"ulimit -c 0\n{tool} {std}{flag} "
                                  f"-fsyntax-only {name}\n", Path(d),
                                  timeout_s, merge=True)
            if ex.timed_out:
                return None, [f"frontend: {name}: timed out"]
            if ex.rc != 0:
                errs = [ln for ln in ex.stdout.splitlines()
                        if re.search(r":\d+:\d+: error:", ln)] or \
                    [ln for ln in ex.stdout.splitlines()
                     if re.search(r"\berror:", ln)]
                return False, [f"frontend: {name}: " + (
                    errs[0] if errs else ex.stdout.strip()[:300]).strip()]
    return True, []


# --- the check ---------------------------------------------------------------------------

def check(program, frontend: bool = True,
          timeout_s: int = 600) -> tuple[bool, list[str]]:
    """(ok, reasons): ok only when both witnesses accept and the race rule
    finds nothing (see the module docstring). `frontend` False skips the
    second witness (then ok is always False: one witness is not
    enough), for callers that only want the rules' reasons."""
    r_ok, r_why = rules_witness(program)
    if frontend:
        f_ok, f_why = frontend_witness(program, timeout_s)
    else:
        f_ok, f_why = None, ["frontend: not run"]
    reasons = list(r_why) + [w for w in f_why if f_ok is False]
    if r_ok is None or f_ok is None:
        reasons += [w for w in (r_why if r_ok is None else []) +
                    (f_why if f_ok is None else []) if w not in reasons]
        reasons.append("witness unavailable: legality needs two witnesses")
        return False, reasons
    if r_ok != f_ok:
        reasons.append("witnesses disagree (rules "
                       f"{'accept' if r_ok else 'reject'}, front end "
                       f"{'accepts' if f_ok else 'rejects'}): legality "
                       "review")
        if r_ok and not f_ok:
            reasons.append(FRONTEND_ONLY)
    return bool(r_ok and f_ok), reasons


FRONTEND_ONLY = ("front end alone refuses: a candidate AFAR front-end "
                 "defect (the rules accept)")


def refusal_kind(reasons) -> str:
    """The kind of a pre-run refusal from its reasons: ``frontend_only``
    (a candidate AFAR front-end defect), ``unreadable`` (the rules cannot
    read the program), ``witness_unavailable``, ``rules`` (a restriction
    rule), ``race``, ``restriction`` (EXTRA), ``frontend`` (both refuse),
    ``other``."""
    text = reasons if isinstance(reasons, str) else "; ".join(reasons)
    if FRONTEND_ONLY in text:
        return "frontend_only"
    if "rules: cannot read it" in text:
        return "unreadable"
    if "witness unavailable" in text:
        return "witness_unavailable"
    for k in ("rules: violates", "race:", "restriction:"):
        if k in text:
            return {"rules: violates": "rules", "race:": "race",
                    "restriction:": "restriction"}[k]
    if "frontend" in text or "front end" in text:
        return "frontend"
    return "other"
