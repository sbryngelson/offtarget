"""The in-program self-checks (offload.engine.harvest.c_runtime,
f_runtime) agree with the reference matcher (offload.engine.harvest.checks.match)
on the same outputs, compiled and run through the harness (a Tuolumne
compute node: AFAR and CCE)."""
import os

import pytest

from offload.engine.harvest import checks as K
from offload.engine.harvest import convert as C

CASES = [
    # (name, output lines, CHECK lines, C only)
    ("basic", ["x = 1"], ["CHECK: x = 1"], False),
    ("numbers", ["   2.000000       4.00  6."], ["CHECK: 2. 4. 6."], False),
    ("number-wrong", [" 2. 4. 7."], ["CHECK: 2. 4. 6."], False),
    ("next-fails", ["a", "zz", "b"], ["CHECK: a", "CHECK-NEXT: b"], False),
    ("next-ok", ["a", "b c"], ["CHECK: a", "CHECK-NEXT: b",
                               "CHECK-SAME: c"], False),
    ("not-between", ["begin", "error 1", "end"],
     ["CHECK: begin", "CHECK-NOT: error", "CHECK: end"], False),
    ("not-at-end", ["x", "bad"], ["CHECK: x", "CHECK-NOT: bad"], False),
    ("dag", ["one", "two", "three"],
     ["CHECK-DAG: two", "CHECK-DAG: one", "CHECK: three"], False),
    ("dag-missing", ["one", "three"],
     ["CHECK-DAG: two", "CHECK-DAG: one", "CHECK: three"], False),
    ("empty", ["a", "", "b"], ["CHECK: a", "CHECK-EMPTY:", "CHECK-NEXT: b"],
     False),
    ("word-edge", ["Test PASSED"], ["CHECK: PASS"], False),
    ("wild", ["x = 17 done"], ["CHECK: x = {{.*}} done"], False),
    ("order", ["b c", "a 1"], ["CHECK: a 1", "CHECK: b"], False),
    ("no-checks", ["anything"], [], False),
    ("regex-var", ["ptr = 0xab12", "again 0xab12"],
     ["CHECK: ptr = [[P:0x[0-9a-f]+]]", "CHECK: again [[P]]"], True),
    ("regex-var-bad", ["ptr = 0xab12", "again 0xab13"],
     ["CHECK: ptr = [[P:0x[0-9a-f]+]]", "CHECK: again [[P]]"], True),
    ("regex-anchor", ["n=42x"], ["CHECK: n={{[0-9]+}}{{$}}"], True),
]


def _c_original(out, checks):
    body = "".join(f'  puts("{ln}");\n' for ln in out)
    return ("#include <stdio.h>\nint main(void) {\n" + body +
            "  return 0;\n}\n" + "".join(f"// {c}\n" for c in checks))


def _f_original(out, checks, stop=False):
    body = "".join(f"  write(*, '(a)') '{ln}'\n" for ln in out)
    return ("program p\n  implicit none\n" + body +
            ("  stop\n" if stop else "") + "end program p\n" +
            "".join(f"! {c}\n" for c in checks))


def _expect(out, checks, lang):
    text = "\n".join("// " + c for c in checks)
    return K.match(K.parse_checks(text), "\n".join(out) + "\n", lang)[0]


def _program(lang, name, src):
    from offload.engine.gen import Program
    return Program(id=f"hvtest-{name}", lang=lang, source=src,
                   atoms=frozenset(), primary_atom="harvest.test",
                   legal=True, violates=None, observable=True)


needs_node = pytest.mark.skipif(
    not os.environ.get("FLUX_JOB_ID") and not os.path.exists("/dev/kfd"),
    reason="needs a Tuolumne compute node (the AFAR and CCE compilers)")


@pytest.mark.gpu
@needs_node
@pytest.mark.parametrize("tc", ["afar", "cce21"])
@pytest.mark.parametrize("lang", ["c", "f90"])
def test_runtime_agrees_with_the_reference(tc, lang):
    from offload.engine import harness
    from offload.engine.toolchains import TOOLCHAINS
    bad = []
    for name, out, checks, c_only in CASES:
        if c_only and lang != "c":
            continue
        orig = (_c_original if lang == "c" else _f_original)(out, checks)
        cs = K.parse_checks(orig)
        v = {"flags": [], "prefixes": ["CHECK"] if checks else [],
             "stderr": False}
        src = (C.convert_c if lang == "c" else C.convert_f)(orig, cs, v)[0]
        r = harness.run_program(_program(lang, name, src), TOOLCHAINS[tc], 1,
                                "-O2", timeout_s=60, repeats=1)
        want = _expect(out, checks, lang)
        got = str(r.outcome) == "correct_on_device"
        if got != want or (not got and "check_fail" not in r.reason):
            bad.append((name, want, str(r.outcome), r.reason[:200]))
    assert not bad, bad


@pytest.mark.gpu
@needs_node
@pytest.mark.parametrize("tc", ["afar", "cce21"])
def test_fortran_stop_and_c_exit_are_checked(tc):
    from offload.engine import harness
    from offload.engine.toolchains import TOOLCHAINS
    v = {"flags": [], "prefixes": ["CHECK"], "stderr": False}
    f = _f_original(["a 1", "b 2"], ["CHECK: a 1", "CHECK-NEXT: b 2"],
                    stop=True)
    src = C.convert_f(f, K.parse_checks(f), v)[0]
    r = harness.run_program(_program("f90", "stop", src), TOOLCHAINS[tc], 1,
                            "-O2", timeout_s=60, repeats=1)
    assert str(r.outcome) == "correct_on_device", r.reason
    c = ("#include <stdio.h>\n#include <stdlib.h>\nint main(void) {\n"
         '  puts("a 1");\n  exit(0);\n}\n// CHECK: a 1\n')
    src = C.convert_c(c, K.parse_checks(c), v)[0]
    r = harness.run_program(_program("c", "exit", src), TOOLCHAINS[tc], 1,
                            "-O2", timeout_s=60, repeats=1)
    assert str(r.outcome) == "correct_on_device", r.reason
    # a failing exit status is a failure even when the output matches
    c1 = c.replace("exit(0)", "exit(3)")
    src = C.convert_c(c1, K.parse_checks(c1), v)[0]
    r = harness.run_program(_program("c", "exit3", src), TOOLCHAINS[tc], 1,
                            "-O2", timeout_s=60, repeats=1)
    assert str(r.outcome) != "correct_on_device"


@pytest.mark.gpu
@needs_node
@pytest.mark.parametrize("tc", ["afar", "cce21"])
def test_fortran_list_directed_output_is_compared_by_value(tc):
    # whatever form the compiler's list-directed output takes (blanks or
    # commas, r*c repeat counts, new records), the values are compared
    from offload.engine import harness
    from offload.engine.toolchains import TOOLCHAINS
    f = ("program p\n  implicit none\n  integer :: a(10)\n  real :: r(16)\n"
         "  a = 0\n  a(2:5) = [2, 3, 4, 5]\n  r = 42.\n"
         "  print *, a\n  print *, r\nend program p\n"
         "! CHECK: 0 2 3 4 5 0 0 0 0 0\n"
         "! CHECK: 42. 42. 42. 42. 42. 42. 42. 42. 42. 42. 42. 42. 42. 42.\n")
    v = {"flags": [], "prefixes": ["CHECK"], "stderr": False}
    src = C.convert_f(f, K.parse_checks(f), v)[0]
    r = harness.run_program(_program("f90", "listdir", src), TOOLCHAINS[tc],
                            1, "-O2", timeout_s=60, repeats=1)
    assert str(r.outcome) == "correct_on_device", (r.reason, r.stdout[-500:])
