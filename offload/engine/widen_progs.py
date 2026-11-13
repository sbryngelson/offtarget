"""The specs of the widened catalog (offload.engine.widen).

Fortran specs (``F_SPECS``) are rendered for OpenMP 5.2 and, where the
feature applies, OpenACC 3.4 through the macros of ``offload.engine.widen.
expand``; C specs (``C_SPECS``) are OpenMP 5.2 C11 programs. Order: base
features (Fortran, then C), directives outside the slice, forms, pairs.

Every program is race free and its result does not depend on the number
of threads, teams or gangs, so sequential elision gives the value OpenMP /
OpenACC execution must give (offload.engine.widen: the expected value's second
source); the few that read a runtime value or depend on the device's
arithmetic say why (``elision``). Arrays are ``a(i) = i`` (input), ``b``
(output), ``ref`` (the host reference); the check is ``all(b == ref)``
unless the spec says otherwise.
"""
from __future__ import annotations

from offload.engine.widen import CSpec, FSpec

# --- spec text cited by the programs --------------------------------------------------

OMP_F08 = ("OpenMP 5.2 §1.7, pp.34-35: Fortran 2008 is a normative base "
           "language (the Fortran 2018 features whose use is unspecified are "
           "listed there; this is not one of them)")
ACC_F08 = ("OpenACC 3.4 §1.8, p.15: Fortran 2008 is a normative base "
           "language (the features whose use is unspecified are listed "
           "there; this is not one of them)")
OMP_IMPLICIT = ("OpenMP 5.2 §13.8, p.284: a procedure referenced in a "
                "target construct is treated as if it appeared in an enter "
                "clause on a declare target directive")
ACC_IMPLICIT = ("OpenACC 3.4 §2.15.1, p.91: a procedure called in a "
                "compute region gets an implicit routine seq directive")
OMP_C11 = ("OpenMP 5.2 §1.7, p.34: C11 is a normative base language")
OMP_OPTIONAL = ("OpenMP 5.2 §3.2.1, p.61: a list item that is an absent "
                "optional dummy is ignored, and the data-sharing and "
                "data-mapping rules of an absent optional referenced in a "
                "construct are ignored")
ACC_OPTIONAL = ("OpenACC 3.4 §2.17.1, p.101: Fortran optional arguments in "
                "data clauses and compute regions")
OMP_STOP = ("OpenMP 5.2 §4.3, p.75: a structured block may contain STOP or "
            "ERROR STOP statements")
OMP_BLOCK_PRIV = ("OpenMP 5.2 §5.1.1, p.96: variables declared within a "
                  "BLOCK construct inside a construct (without SAVE) are "
                  "private")
OMP_COMMON = ("OpenMP 5.2 §3.2.1, p.61 and §7.8.1: a common block name "
              "between slashes is a declare target list item")
ACC_COMMON = ("OpenACC 3.4 §2.13 (declare directive): a var may be the "
              "name of a Fortran common block between slashes")
OMP_DEFAULT_MAPPER = ("OpenMP 5.2 §5.8.3, p.150: the predefined default "
                      "mapper of a derived type maps its allocatable "
                      "components that are not explicit list items")
ACC_DEEP = ("OpenACC 3.4 §2.7.1, p.49 and §2.6.8, p.47: members of "
            "derived type variables may appear in data clauses; the data of "
            "an allocatable or pointer member is copied when the member "
            "appears, and the device pointer is attached")
OMP_STATIC_IN_ROUTINE = ("OpenMP 5.2 §7.8, p.203: a variable with static "
                         "storage duration declared in a device routine is "
                         "treated as if it appeared in an enter clause on "
                         "a declare target directive")
OMP_FPTR = ("OpenMP 5.2 §13.8, p.286: a program may rely on a function "
            "address in a target region for assignments, comparisons to "
            "zero and indirect calls")
OMP_CRITICAL = ("OpenMP 5.2 §15.2, p.316 (critical construct); its binding "
                "thread set is the contention group, so a target parallel "
                "region (one team) is used")
OMP_SECTIONS = "OpenMP 5.2 §11.3, p.226 (sections construct)"
OMP_ATOMIC = "OpenMP 5.2 §15.8.4, p.325 (atomic construct)"
OMP_MAPPER = ("OpenMP 5.2 §5.8.8, p.164 (declare mapper directive): a "
              "map clause on a list item of the mapper's type applies the "
              "mapper")
OMP_DEFAULTMAP_TWO = ("OpenMP 5.2 §5.8.7, p.161: a given variable-category "
                      "may be specified in at most one defaultmap clause on "
                      "a construct (two categories, two clauses: legal)")


def ploop(body: str, clauses: str = "to(a) from(b) tofrom(host_flag)",
          var: str = "i", flag: bool = True) -> str:
    """A @PLOOP kernel over 1..n with the host flag set by iteration 1."""
    inner = "\n".join("    " + ln if ln.strip() else ln
                      for ln in body.strip("\n").splitlines())
    hf = f"\n    if ({var} == 1) @HOSTFLAG" if flag else ""
    return (f"  @PLOOP {clauses}\n  do {var} = 1, n\n{inner}{hf}\n"
            "  end do\n  @END_PLOOP\n")


def region(body: str, clauses: str = "to(a) from(b) tofrom(host_flag)"
           ) -> str:
    inner = "\n".join("    " + ln if ln.strip() else ln
                      for ln in body.strip("\n").splitlines())
    return f"  @REGION {clauses}\n    @HOSTFLAG\n{inner}\n  @END_REGION\n"


def module(body: str, name: str = "wmod") -> str:
    return f"module {name}\n  implicit none\n{body.rstrip()}\nend module {name}\n"


W2 = ("b(i) = 2*a(i) + 1", "b(i) = 2*a(i)")   # the usual mutant edit

# --- base-language features in device code: Fortran --------------------------------

_OPT_WORK = """\
  subroutine work(x, y, hf, c)
    integer, intent(in) :: x(n)
    integer, intent(inout) :: y(n)
    integer, intent(inout) :: hf
    integer, intent(in), optional :: c(n)
    integer :: k
    @PLOOP to(x) tofrom(y, hf)
    do k = 1, n
      if (present(c)) then
        y(k) = x(k) + c(k)
      else
        y(k) = 2*x(k) + 1
      end if
      if (k == 1) @HOSTFLAG[hf]
    end do
    @END_PLOOP
  end subroutine work
"""

_TYPES_ALLOC = module("""\
  type rec_t
    integer, allocatable :: v(:)
  end type rec_t""", "wtypes")

_TYPES_PTR = module("""\
  type prec_t
    integer, pointer :: p(:) => null()
  end type prec_t""", "wtypes")

_TYPES_PT = module("""\
  type pt_t
    integer :: x
    integer :: y
  end type pt_t
  type par_t
    integer :: k
    integer :: m
  end type par_t""", "wtypes")

_TYPES_NEST = module("""\
  type in_t
    integer :: k
  end type in_t
  type out_t
    type(in_t) :: inner
    integer :: w(4)
  end type out_t""", "wtypes")

_ROUTINE_TW = module("""\
contains
  integer function tw(x)
    @ROUTINE
    integer, intent(in) :: x
    tw = 2*x + 1
  end function tw""")

_PRIV_T = "  integer :: t(4)\n"

F_BASE = [
    FSpec("optional-absent", "base.device.optional_absent",
          "an absent OPTIONAL dummy array referenced with PRESENT() in a "
          "target region of the procedure", OMP_OPTIONAL,
          "  call work(a, b, host_flag)\n", contains=_OPT_WORK,
          mutant=(("y(k) = 2*x(k) + 1", "y(k) = 2*x(k)"),),
          spec_acc=ACC_OPTIONAL),
    FSpec("optional-present", "base.device.optional_present",
          "a present OPTIONAL dummy array referenced (PRESENT() true) in a "
          "target region of the procedure", OMP_OPTIONAL,
          "  call work(a, b, host_flag, c)\n", ref="4*i",
          decls="  integer :: c(n)\n", init="  c = 3*a\n",
          contains=_OPT_WORK,
          mutant=(("y(k) = x(k) + c(k)", "y(k) = x(k)"),),
          spec_acc=ACC_OPTIONAL),
    FSpec("optional-device-routine", "base.device.optional_routine",
          "a device routine with an OPTIONAL scalar dummy, called with and "
          "without it", OMP_IMPLICIT + "; " + OMP_OPTIONAL,
          ploop("b(i) = addopt(a(i)) + addopt(a(i), 1)"),
          modules=module("""\
contains
  integer function addopt(x, y)
    @ROUTINE
    integer, intent(in) :: x
    integer, intent(in), optional :: y
    if (present(y)) then
      addopt = x + y
    else
      addopt = x
    end if
  end function addopt"""), uses="  use wmod\n",
          mutant=(("addopt = x + y", "addopt = x"),), spec_acc=ACC_OPTIONAL),
    FSpec("block", "base.device.block",
          "a BLOCK construct with a local variable inside a target loop",
          OMP_BLOCK_PRIV, ploop("""\
block
  integer :: t
  t = 2*a(i)
  b(i) = t + 1
end block"""), mutant=(("b(i) = t + 1", "b(i) = t"),), spec_acc=ACC_F08),
    FSpec("stop-unreached", "base.device.stop",
          "a STOP statement in device code that is not executed",
          OMP_STOP, ploop("if (a(i) < 0) stop 1\nb(i) = 2*a(i) + 1"),
          mutant=(W2,), spec_acc=ACC_F08),
    FSpec("error-stop-unreached", "base.device.error_stop",
          "an ERROR STOP statement in device code that is not executed",
          OMP_STOP, ploop("if (a(i) < 0) error stop 2\nb(i) = 2*a(i) + 1"),
          mutant=(W2,), spec_acc=ACC_F08),
    FSpec("common-block", "base.device.common_block",
          "a named COMMON block made device data (declare target / acc "
          "declare create), updated from the host and read in a target loop",
          OMP_COMMON,
          "  @UPD_TO(cb)\n" + ploop("b(i) = cb(i) + 1",
                                    "from(b) tofrom(host_flag)"),
          ref="3*i + 1",
          decls="  integer :: cb(n)\n  common /wblk/ cb\n  @DECLVAR(/wblk/)\n",
          init="  cb = 3*a\n",
          mutant=(("b(i) = cb(i) + 1", "b(i) = 1"),), spec_acc=ACC_COMMON),
    FSpec("alloc-component", "base.device.alloc_component",
          "an allocatable component of a derived type mapped explicitly "
          "and read on the device",
          "OpenMP 5.2 §5.8.3, p.150: a structure element may be a map "
          "list item; " + OMP_DEFAULT_MAPPER,
          ploop("b(i) = r%v(i) + 1", "to(r%v) from(b) tofrom(host_flag)"),
          ref="3*i + 1", modules=_TYPES_ALLOC, uses="  use wtypes\n",
          decls="  type(rec_t) :: r\n",
          init="  allocate(r%v(n))\n  r%v = 3*a\n",
          acc={"kernel": "  @ENTER to(r)\n  @ENTER to(r%v)\n" + ploop(
              "b(i) = r%v(i) + 1", "present(r) from(b) tofrom(host_flag)")
              + "  @EXIT delete(r%v)\n  @EXIT delete(r)\n"},
          mutant=(("b(i) = r%v(i) + 1", "b(i) = 1"),), spec_acc=ACC_DEEP),
    FSpec("alloc-component-whole", "base.device.alloc_component_whole",
          "a derived type with an allocated allocatable component mapped "
          "as a whole (the default mapper maps the component)",
          OMP_DEFAULT_MAPPER,
          ploop("b(i) = r%v(i) + 1", "to(r) from(b) tofrom(host_flag)"),
          ref="3*i + 1", modules=_TYPES_ALLOC, uses="  use wtypes\n",
          decls="  type(rec_t) :: r\n",
          init="  allocate(r%v(n))\n  r%v = 3*a\n", models=("omp",),
          mutant=(("b(i) = r%v(i) + 1", "b(i) = 1"),)),
    FSpec("pointer-component", "base.device.pointer_component",
          "a POINTER component of a derived type mapped explicitly (its "
          "target is mapped and attached) and read on the device",
          "OpenMP 5.2 §5.8.3, p.151: an associated pointer list item "
          "maps its pointer target",
          ploop("b(i) = r%p(i) + 1", "to(r%p) from(b) tofrom(host_flag)"),
          ref="3*i + 1", modules=_TYPES_PTR, uses="  use wtypes\n",
          decls="  type(prec_t) :: r\n",
          init="  allocate(r%p(n))\n  r%p = 3*a\n",
          acc={"kernel": "  @ENTER to(r)\n  @ENTER to(r%p)\n" + ploop(
              "b(i) = r%p(i) + 1", "present(r) from(b) tofrom(host_flag)")
              + "  @EXIT delete(r%p)\n  @EXIT delete(r)\n"},
          mutant=(("b(i) = r%p(i) + 1", "b(i) = 1"),), spec_acc=ACC_DEEP),
    FSpec("derived-type-array", "base.device.derived_array",
          "an array of a derived type mapped and its components read on the "
          "device", OMP_F08,
          ploop("b(i) = ps(i)%x + 2*ps(i)%y", "to(ps) from(b) tofrom(host_flag)"),
          ref="5*i", modules=_TYPES_PT, uses="  use wtypes\n",
          decls="  type(pt_t) :: ps(n)\n",
          init="  do i = 1, n\n    ps(i)%x = i\n    ps(i)%y = 2*i\n  end do\n",
          mutant=(("b(i) = ps(i)%x + 2*ps(i)%y", "b(i) = ps(i)%x"),),
          spec_acc=ACC_F08),
    FSpec("derived-scalar", "base.device.derived_scalar",
          "a scalar of a derived type with integer components mapped and "
          "read on the device", OMP_F08,
          ploop("b(i) = s%k*a(i) + s%m", "to(s) from(b) tofrom(host_flag)"),
          ref="3*i + 1", modules=_TYPES_PT, uses="  use wtypes\n",
          decls="  type(par_t) :: s\n", init="  s%k = 3\n  s%m = 1\n",
          mutant=(("b(i) = s%k*a(i) + s%m", "b(i) = s%k*a(i)"),),
          spec_acc=ACC_F08),
    FSpec("nested-derived-type", "base.device.nested_type",
          "a derived type with a derived-type component and an array "
          "component, mapped and read on the device", OMP_F08,
          ploop("b(i) = o%inner%k*a(i) + o%w(mod(i, 4) + 1)",
                "to(o) from(b) tofrom(host_flag)"),
          ref="3*i + mod(i, 4) + 1", modules=_TYPES_NEST,
          uses="  use wtypes\n", decls="  type(out_t) :: o\n",
          init="  o%inner%k = 3\n  o%w = [1, 2, 3, 4]\n",
          mutant=((" + o%w(mod(i, 4) + 1)", ""),), spec_acc=ACC_F08),
    FSpec("derived-assignment", "base.device.derived_assign",
          "intrinsic assignment of a whole derived-type value to a private "
          "variable in device code", OMP_F08,
          ploop("t = s\nt%m = t%m + a(i)\nb(i) = t%k*a(i) + t%m",
                "to(s) from(b) tofrom(host_flag) private(t)"),
          ref="4*i + 1", modules=_TYPES_PT, uses="  use wtypes\n",
          decls="  type(par_t) :: s, t\n", init="  s%k = 3\n  s%m = 1\n",
          mutant=(("    t = s\n", "    t = par_t(0, 0)\n"),),
          spec_acc=ACC_F08),
    FSpec("assumed-shape-dummy", "base.device.assumed_shape_routine",
          "a device routine with assumed-shape dummy arrays (SIZE of the "
          "dummy on the device)", OMP_IMPLICIT,
          region("call dbl(a, b)"), modules=module("""\
contains
  subroutine dbl(x, y)
    @ROUTINE
    integer, intent(in) :: x(:)
    integer, intent(out) :: y(:)
    integer :: k
    do k = 1, size(x)
      y(k) = 2*x(k) + 1
    end do
  end subroutine dbl"""), uses="  use wmod\n",
          mutant=(("y(k) = 2*x(k) + 1", "y(k) = 2*x(k)"),),
          spec_acc=ACC_F08),
    FSpec("assumed-size-dummy", "base.device.assumed_size_routine",
          "a device routine with assumed-size dummy arrays", OMP_IMPLICIT,
          region("call dbl(a, b, n)"), modules=module("""\
contains
  subroutine dbl(x, y, m)
    @ROUTINE
    integer, intent(in) :: m
    integer, intent(in) :: x(*)
    integer, intent(inout) :: y(*)
    integer :: k
    do k = 1, m
      y(k) = 2*x(k) + 1
    end do
  end subroutine dbl"""), uses="  use wmod\n",
          mutant=(("y(k) = 2*x(k) + 1", "y(k) = 2*x(k)"),),
          spec_acc=ACC_F08),
    FSpec("assumed-shape-in-target", "base.device.assumed_shape_target",
          "a target region in a procedure whose assumed-shape dummy arrays "
          "are mapped", OMP_F08,
          "  call work(a, b, host_flag)\n", contains="""\
  subroutine work(x, y, hf)
    integer, intent(in) :: x(:)
    integer, intent(inout) :: y(:)
    integer, intent(inout) :: hf
    integer :: k
    @PLOOP to(x) tofrom(y, hf)
    do k = 1, size(x)
      y(k) = 2*x(k) + 1
      if (k == 1) @HOSTFLAG[hf]
    end do
    @END_PLOOP
  end subroutine work
""", mutant=(("y(k) = 2*x(k) + 1", "y(k) = 2*x(k)"),), spec_acc=ACC_F08),
    FSpec("internal-procedure", "base.device.internal_procedure",
          "an internal function of the program (no host-associated "
          "variable) called in a target loop",
          OMP_IMPLICIT + "; p.284: only references to host-associated "
          "variables are unspecified", ploop("b(i) = tw(a(i))"),
          contains="""\
  integer function tw(x)
    integer, intent(in) :: x
    tw = 2*x + 1
  end function tw
""", mutant=(("tw = 2*x + 1", "tw = 2*x"),), spec_acc=ACC_IMPLICIT),
    FSpec("implicit-routine", "base.device.implicit_routine",
          "a module function without a declare target / routine directive "
          "called in a target loop (implicitly a device routine)",
          OMP_IMPLICIT, ploop("b(i) = tw(a(i))"), modules=module("""\
contains
  integer function tw(x)
    integer, intent(in) :: x
    tw = 2*x + 1
  end function tw"""), uses="  use wmod\n",
          mutant=(("tw = 2*x + 1", "tw = 2*x"),), spec_acc=ACC_IMPLICIT),
    FSpec("routine-call", "base.device.routine_call",
          "a module function with declare target / routine seq called in a "
          "target loop", OMP_IMPLICIT, ploop("b(i) = tw(a(i))"),
          modules=_ROUTINE_TW, uses="  use wmod\n",
          mutant=(("tw = 2*x + 1", "tw = 2*x"),),
          spec_acc="OpenACC 3.4 §2.15.1, p.91 (routine directive)"),
    FSpec("module-variable-routine", "base.device.module_variable",
          "a module array made device data, updated from the host and read "
          "by a device routine", "OpenMP 5.2 \u00a77.8.1 (declare target): a "
          "module variable may be a declare target list item",
          "  @UPD_TO(mtab)\n" + ploop("b(i) = getm(a(i)) + 1",
                                      "from(b) tofrom(host_flag)"),
          ref="3*i + 1", modules=module("""\
  integer :: mtab(64)
  @DECLVAR(mtab)
contains
  integer function getm(k)
    @ROUTINE
    integer, intent(in) :: k
    getm = mtab(k)
  end function getm"""), uses="  use wmod\n", init="  mtab = 3*a\n",
          mutant=(("getm = mtab(k)", "getm = 0"),),
          spec_acc="OpenACC 3.4 §2.13 (declare create in a module)"),
    FSpec("elemental-routine", "base.device.elemental",
          "an ELEMENTAL device function applied to an array section in a "
          "target region", OMP_IMPLICIT, region("b(1:n) = tw(a(1:n))"),
          modules=module("""\
contains
  elemental integer function tw(x)
    @ROUTINE
    integer, intent(in) :: x
    tw = 2*x + 1
  end function tw"""), uses="  use wmod\n",
          mutant=(("tw = 2*x + 1", "tw = 2*x"),), spec_acc=ACC_F08),
    FSpec("pure-routine", "base.device.pure",
          "a PURE device function called in a target loop", OMP_IMPLICIT,
          ploop("b(i) = tw(a(i))"), modules=module("""\
contains
  pure integer function tw(x)
    @ROUTINE
    integer, intent(in) :: x
    tw = 2*x + 1
  end function tw"""), uses="  use wmod\n",
          mutant=(("tw = 2*x + 1", "tw = 2*x"),), spec_acc=ACC_F08),
    FSpec("recursive-routine", "base.device.recursion",
          "a RECURSIVE device function", OMP_IMPLICIT,
          ploop("b(i) = sumto(mod(a(i), 8))"), ref="mod(i, 8)*(mod(i, 8) + 1)/2",
          modules=module("""\
contains
  recursive function sumto(k) result(r)
    @ROUTINE
    integer, intent(in) :: k
    integer :: r
    if (k <= 0) then
      r = 0
    else
      r = k + sumto(k - 1)
    end if
  end function sumto"""), uses="  use wmod\n",
          mutant=(("r = k + sumto(k - 1)", "r = k"),), spec_acc=ACC_F08),
    FSpec("generic-interface", "base.device.generic_interface",
          "a generic interface with integer and real(8) specifics resolved "
          "in device code", OMP_IMPLICIT,
          ploop("b(i) = twice(a(i)) + int(twice(real(a(i), 8)))"),
          ref="4*i + 1", modules=module("""\
  interface twice
    module procedure twice_i, twice_r
  end interface twice
contains
  integer function twice_i(x)
    @ROUTINE
    integer, intent(in) :: x
    twice_i = 2*x + 1
  end function twice_i
  real(8) function twice_r(x)
    @ROUTINE
    real(8), intent(in) :: x
    twice_r = 2.0d0*x
  end function twice_r"""), uses="  use wmod\n",
          mutant=(("twice_i = 2*x + 1", "twice_i = 2*x"),),
          spec_acc=ACC_F08),
    FSpec("type-bound-nopass", "base.device.type_bound_nopass",
          "a NOPASS type-bound procedure called through a mapped object in "
          "device code", OMP_F08,
          ploop("b(i) = op%tw(a(i))", "to(a, op) from(b) tofrom(host_flag)"),
          modules=module("""\
  type op_t
    integer :: k = 0
  contains
    procedure, nopass :: tw => tw_impl
  end type op_t
contains
  integer function tw_impl(x)
    @ROUTINE
    integer, intent(in) :: x
    tw_impl = 2*x + 1
  end function tw_impl"""), uses="  use wmod\n", decls="  type(op_t) :: op\n",
          mutant=(("tw_impl = 2*x + 1", "tw_impl = 2*x"),),
          spec_acc=ACC_F08),
    FSpec("type-bound-pass", "base.device.type_bound_pass",
          "a type-bound procedure with a CLASS passed-object dummy called "
          "through a mapped object in device code", OMP_F08,
          ploop("b(i) = op%scaled(a(i))", "to(a, op) from(b) tofrom(host_flag)"),
          modules=module("""\
  type op_t
    integer :: k = 2
  contains
    procedure :: scaled => scaled_impl
  end type op_t
contains
  integer function scaled_impl(self, x)
    @ROUTINE
    class(op_t), intent(in) :: self
    integer, intent(in) :: x
    scaled_impl = self%k*x + 1
  end function scaled_impl"""), uses="  use wmod\n", decls="  type(op_t) :: op\n",
          mutant=(("scaled_impl = self%k*x + 1", "scaled_impl = self%k*x"),),
          spec_acc=ACC_F08),
    FSpec("intrinsic-sum", "base.device.intrinsic_sum",
          "SUM of an array section in device code", OMP_F08,
          ploop("b(i) = sum(a(1:i))"), ref="i*(i + 1)/2",
          mutant=(("sum(a(1:i))", "a(i)"),), spec_acc=ACC_F08),
    FSpec("intrinsic-maxval-minval", "base.device.intrinsic_maxval",
          "MAXVAL and MINVAL of array sections in device code", OMP_F08,
          ploop("b(i) = maxval(a(1:i)) + minval(a(i:n))"), ref="2*i",
          mutant=((" + minval(a(i:n))", ""),), spec_acc=ACC_F08),
    FSpec("intrinsic-maxloc-minloc", "base.device.intrinsic_maxloc",
          "MAXLOC and MINLOC (DIM=1) of array sections in device code",
          OMP_F08,
          ploop("b(i) = maxloc(a(1:i), dim=1) + minloc(a(i:n), dim=1)"),
          ref="i + 1",
          mutant=((" + minloc(a(i:n), dim=1)", ""),), spec_acc=ACC_F08),
    FSpec("intrinsic-count-any-all", "base.device.intrinsic_count",
          "COUNT, ANY and ALL of masks in device code", OMP_F08,
          ploop("b(i) = count(a(1:i) > i/2) + merge(1, 0, any(a(1:i) == i)) "
                "+ merge(1, 0, all(a(1:i) <= i))"), ref="i - i/2 + 2",
          mutant=(("count(a(1:i) > i/2)", "i"),), spec_acc=ACC_F08),
    FSpec("intrinsic-dot-product", "base.device.intrinsic_dot_product",
          "DOT_PRODUCT of array sections in device code", OMP_F08,
          ploop("b(i) = dot_product(a(1:mod(i, 4) + 1), a(1:mod(i, 4) + 1))"),
          ref="(mod(i, 4) + 1)*(mod(i, 4) + 2)*(2*mod(i, 4) + 3)/6",
          mutant=(("dot_product(a(1:mod(i, 4) + 1), a(1:mod(i, 4) + 1))",
                   "sum(a(1:mod(i, 4) + 1))"),), spec_acc=ACC_F08),
    FSpec("intrinsic-matmul", "base.device.intrinsic_matmul",
          "MATMUL of two integer matrices in a target region", OMP_F08,
          region("m3 = matmul(m1, m2)",
                 "to(m1, m2) from(m3) tofrom(host_flag)"),
          check="all(m3 == r3)",
          decls="  integer :: m1(4, 4), m2(4, 4), m3(4, 4), r3(4, 4)\n"
                "  integer :: j, k, l\n",
          init="""\
  do k = 1, 4
    do j = 1, 4
      m1(j, k) = j + k
      m2(j, k) = j - k + 5
      m3(j, k) = 0
    end do
  end do
  do k = 1, 4
    do j = 1, 4
      r3(j, k) = 0
      do l = 1, 4
        r3(j, k) = r3(j, k) + m1(j, l)*m2(l, k)
      end do
    end do
  end do
""", mutant=(("m3 = matmul(m1, m2)", "m3 = m1"),), spec_acc=ACC_F08),
    FSpec("intrinsic-transpose-reshape", "base.device.intrinsic_reshape",
          "TRANSPOSE of a RESHAPE of an array section in a target region",
          OMP_F08,
          region("m3 = transpose(reshape(a(1:16), [4, 4]))",
                 "to(a) from(m3) tofrom(host_flag)"),
          check="all(m3 == r3)",
          decls="  integer :: m3(4, 4), r3(4, 4)\n  integer :: j, k\n",
          init="""\
  do k = 1, 4
    do j = 1, 4
      r3(j, k) = k + 4*(j - 1)
      m3(j, k) = 0
    end do
  end do
""", mutant=(("m3 = transpose(reshape(a(1:16), [4, 4]))",
              "m3 = reshape(a(1:16), [4, 4])"),), spec_acc=ACC_F08),
    FSpec("intrinsic-transcendental", "base.device.intrinsic_math",
          "EXP, LOG, SIN and COS of real(8) values in device code (checked "
          "to 1e-9)", OMP_F08,
          ploop("x(i) = exp(log(real(a(i), 8))) + sin(real(a(i), 8))**2 + "
                "cos(real(a(i), 8))**2", "to(a) from(x) tofrom(host_flag)"),
          check="all(abs(x - (real(a, 8) + 1.0d0)) < 1.0d-9)",
          decls="  real(8) :: x(n)\n", init="  x = 0.0d0\n",
          mutant=((" + cos(real(a(i), 8))**2", ""),), spec_acc=ACC_F08),
    FSpec("intrinsic-modulo-int8", "base.device.intrinsic_modulo_int8",
          "MODULO of INTEGER(8) values (negative and positive) in device "
          "code", OMP_F08,
          ploop("q8(i) = modulo(p8(i), 7_8)", "to(p8) from(q8) tofrom(host_flag)"),
          check="all(q8 == r8)",
          decls="  integer(8) :: p8(n), q8(n), r8(n)\n",
          init="""\
  do i = 1, n
    p8(i) = int(i, 8)*1000000007_8 - 30000000000_8
    q8(i) = 0_8
    r8(i) = mod(p8(i), 7_8)
    if (r8(i) < 0_8) r8(i) = r8(i) + 7_8
  end do
""", mutant=(("modulo(p8(i), 7_8)", "mod(p8(i), 7_8)"),), spec_acc=ACC_F08),
    FSpec("intrinsic-bits", "base.device.intrinsic_bits",
          "POPCNT, IAND and ISHFT in device code", OMP_F08,
          ploop("b(i) = popcnt(a(i)) + iand(a(i), 3) + ishft(a(i), 1)"),
          ref="popcnt(i) + iand(i, 3) + ishft(i, 1)",
          mutant=((" + iand(a(i), 3)", ""),), spec_acc=ACC_F08),
    FSpec("intrinsic-conversions", "base.device.intrinsic_conversion",
          "NINT, FLOOR and CEILING of real(8) and real(4) quotients in "
          "device code", OMP_F08,
          ploop("b(i) = nint(real(a(i), 8)/4.0d0) + floor(real(a(i), 8)/3.0d0)"
                " + ceiling(real(a(i))/5.0)"),
          ref="nint(real(i, 8)/4.0d0) + floor(real(i, 8)/3.0d0) + "
              "ceiling(real(i)/5.0)",
          mutant=(("b(i) = nint(", "b(i) = int("),), spec_acc=ACC_F08),
    FSpec("array-syntax", "base.device.array_syntax",
          "whole-array and section assignment in a target region", OMP_F08,
          region("b(:) = 2*a(:) + 1\nb(1:4) = b(4:1:-1) - b(4:1:-1) + b(1:4)"),
          mutant=(("b(:) = 2*a(:) + 1", "b(:) = 2*a(:)"),), spec_acc=ACC_F08),
    FSpec("where", "base.device.where",
          "a WHERE construct with ELSEWHERE in a target region", OMP_F08,
          region("where (a > n/2)\n  b = 2*a + 1\nelsewhere\n  b = a\nend where"),
          ref="merge(2*i + 1, i, i > n/2)",
          mutant=(("  b = a\n", "  b = 0\n"),), spec_acc=ACC_F08),
    FSpec("do-concurrent-in-region", "base.device.do_concurrent",
          "a DO CONCURRENT loop (no loop directive) in a target region",
          OMP_F08, region("do concurrent (j = 1:n)\n  b(j) = 2*a(j) + 1\nend do"),
          decls="  integer :: j\n",
          mutant=(("b(j) = 2*a(j) + 1", "b(j) = 2*a(j)"),), spec_acc=ACC_F08),
    FSpec("select-case", "base.device.select_case",
          "a SELECT CASE construct in device code", OMP_F08, ploop("""\
select case (mod(a(i), 3))
case (0)
  b(i) = a(i)
case (1)
  b(i) = 2*a(i)
case default
  b(i) = 3*a(i)
end select"""), ref="(mod(i, 3) + 1)*i",
          mutant=(("  b(i) = 3*a(i)\n", "  b(i) = a(i)\n"),),
          spec_acc=ACC_F08),
    FSpec("character-local", "base.device.character",
          "a private CHARACTER(len=8) variable built by concatenation and "
          "searched with INDEX and LEN_TRIM in device code", OMP_F08,
          ploop("s = 'abcd' // 'efgh'\nb(i) = index(s, s(mod(i, 8) + 1:mod(i, 8) "
                "+ 1)) + len_trim(s)", "to(a) from(b) tofrom(host_flag) private(s)"),
          ref="mod(i, 8) + 9", decls="  character(len=8) :: s\n",
          mutant=((" + len_trim(s)", ""),), spec_acc=ACC_F08),
    FSpec("character-mapped", "base.device.character_array",
          "a mapped CHARACTER(len=4) array read with ICHAR and LEN in "
          "device code", OMP_F08,
          ploop("b(i) = ichar(nm(i)(1:1)) - 64 + len(nm(i))",
                "to(nm) from(b) tofrom(host_flag)"),
          ref="mod(i, 26) + 5", decls="  character(len=4) :: nm(n)\n",
          init="  do i = 1, n\n    nm(i) = achar(65 + mod(i, 26)) // 'xyz'\n"
               "  end do\n",
          mutant=(("ichar(nm(i)(1:1)) - 64", "0"),), spec_acc=ACC_F08),
    FSpec("print-in-device", "base.device.print",
          "a PRINT statement executed once in device code", OMP_F08,
          ploop("if (i == n) print '(a)', 'device print'\nb(i) = 2*a(i) + 1"),
          mutant=(W2,), spec_acc=ACC_F08),
    FSpec("allocate-in-device", "base.device.allocate",
          "ALLOCATE and DEALLOCATE of a local allocatable array in a target "
          "region", OMP_F08, region("""\
block
  integer, allocatable :: w(:)
  allocate(w(n))
  w = 2*a + 1
  b = w
  deallocate(w)
end block"""), mutant=(("w = 2*a + 1", "w = 2*a"),), spec_acc=ACC_F08),
    FSpec("allocate-derived-default-init", "base.device.allocate_derived",
          "ALLOCATE of a scalar of a derived type with default "
          "initialization in a target region", OMP_F08, region("""\
block
  type(cfg_t), allocatable :: c
  allocate(c)
  b = c%k*a + c%m
  deallocate(c)
end block"""), modules=module("""\
  type cfg_t
    integer :: k = 2
    integer :: m = 1
  end type cfg_t""", "wtypes"), uses="  use wtypes\n",
          mutant=(("b = c%k*a + c%m", "b = c%k*a"),), spec_acc=ACC_F08),
    FSpec("private-array", "base.device.private_array",
          "a private local array written at constant indices in a target "
          "loop", "OpenMP 5.2 §5.4.3, p.112 (private clause; an array is a "
          "list item)",
          ploop("t(1) = a(i)\nt(2) = 1\nt(3) = a(i)\nt(4) = 0\nb(i) = sum(t)",
                "to(a) from(b) tofrom(host_flag) private(t)"),
          decls=_PRIV_T, mutant=(("t(2) = 1", "t(2) = 0"),),
          spec_acc="OpenACC 3.4 §2.5.14 (private clause)"),
    FSpec("private-array-dynamic-index", "base.device.private_array_dynamic",
          "a private 1-based local array written at a run-time index in a "
          "target loop",
          "OpenMP 5.2 §5.4.3, p.112 (private clause; an array is a list "
          "item)",
          ploop("t = 0\nt(mod(a(i), 4) + 1) = a(i)\nb(i) = sum(t) + "
                "t(mod(a(i), 4) + 1)",
                "to(a) from(b) tofrom(host_flag) private(t)"),
          ref="2*i", decls=_PRIV_T,
          mutant=(("t(mod(a(i), 4) + 1) = a(i)", "t(1) = 0"),),
          spec_acc="OpenACC 3.4 §2.5.14 (private clause)"),
    FSpec("private-array-dynamic-write", "base.device.private_array_dynamic_write",
          "a private local array written at a run-time index that is the "
          "same for every iteration (a host value) and read back at a "
          "constant index in a target loop",
          "OpenMP 5.2 \u00a75.4.3, p.112 (private clause; an array is a list "
          "item)",
          ploop("t(1) = 0\nt(2) = 0\nt(3) = 0\nt(4) = 0\nt(nd) = 5*a(i)\n"
                "b(i) = t(1)", "to(a) from(b) tofrom(host_flag) private(t) "
                "firstprivate(nd)"),
          ref="5*i", decls=_PRIV_T + "  integer :: nd\n",
          init="  nd = command_argument_count() + 1\n",
          mutant=(("t(nd) = 5*a(i)", "t(2) = 5*a(i)"),),
          spec_acc="OpenACC 3.4 \u00a72.5.14 (private clause)"),
    FSpec("save-local-routine", "base.device.save_local",
          "a SAVE local variable of a device routine, updated by sequential "
          "calls in one target region", OMP_STATIC_IN_ROUTINE,
          region("b(1) = bump()\nb(2) = bump()\nb(3) = bump()",
                 "tofrom(b, host_flag)"),
          check="all(b(1:3) == [1, 2, 3])", modules=module("""\
contains
  integer function bump()
    @ROUTINE
    integer, save :: cnt = 0
    cnt = cnt + 1
    bump = cnt
  end function bump"""), uses="  use wmod\n", models=("omp",),
          mutant=(("cnt = cnt + 1", "cnt = 1"),)),
    FSpec("complex-arith", "base.device.complex",
          "COMPLEX(8) arithmetic in device code", OMP_F08,
          ploop("z(i) = cmplx(a(i), 1, 8)*(0.0d0, 1.0d0)",
                "to(a) from(z) tofrom(host_flag)"),
          check="all(real(z) == -1.0d0 .and. aimag(z) == real(a, 8))",
          decls="  complex(8) :: z(n)\n", init="  z = (0.0d0, 0.0d0)\n",
          mutant=(("*(0.0d0, 1.0d0)", ""),), spec_acc=ACC_F08),
    FSpec("exit-cycle", "base.device.exit_cycle",
          "EXIT and CYCLE in a sequential loop in device code", OMP_F08,
          ploop("s = 0\ndo k = 1, n\n  if (k > a(i)) exit\n  if (mod(k, 2) == 0) "
                "cycle\n  s = s + k\nend do\nb(i) = s",
                "to(a) from(b) tofrom(host_flag) private(s, k)"),
          ref="((i + 1)/2)**2", decls="  integer :: s, k\n",
          mutant=(("  if (mod(k, 2) == 0) cycle\n", ""),), spec_acc=ACC_F08),
    FSpec("associate", "base.device.associate",
          "an ASSOCIATE construct in device code", OMP_F08,
          ploop("associate (x => a(i), y => b(i))\n  y = 2*x + 1\nend associate"),
          mutant=(("y = 2*x + 1", "y = 2*x"),), spec_acc=ACC_F08),
    FSpec("int8-loop", "base.device.int8_index",
          "an INTEGER(8) loop variable of the target loop", OMP_F08,
          "  @PLOOP to(a) from(b) tofrom(host_flag)\n  do j8 = 1_8, int(n, 8)\n"
          "    b(j8) = 2*a(j8) + 1\n    if (j8 == 1_8) @HOSTFLAG\n  end do\n"
          "  @END_PLOOP\n", decls="  integer(8) :: j8\n",
          mutant=(("b(j8) = 2*a(j8) + 1", "b(j8) = 2*a(j8)"),),
          spec_acc=ACC_F08),
    FSpec("sequence-association", "base.device.sequence_association",
          "an array element passed as the actual argument of an "
          "explicit-shape dummy array of a device routine (sequence "
          "association)", OMP_IMPLICIT,
          ploop("call rowsum(a2(1, i), 4, b(i))",
                "to(a2) from(b) tofrom(host_flag)"),
          ref="10*i", decls="  integer :: a2(4, n)\n  integer :: k\n",
          init="  do i = 1, n\n    do k = 1, 4\n      a2(k, i) = k*i\n    end do\n"
               "  end do\n", modules=module("""\
contains
  subroutine rowsum(x, m, s)
    @ROUTINE
    integer, intent(in) :: m
    integer, intent(in) :: x(m)
    integer, intent(out) :: s
    integer :: k
    s = 0
    do k = 1, m
      s = s + x(k)
    end do
  end subroutine rowsum"""), uses="  use wmod\n",
          mutant=(("s = s + x(k)", "s = x(k)"),), spec_acc=ACC_F08),
    FSpec("parallel-in-seq-loop", "base.device.parallel_in_seq_loop",
          "a parallel do nested in a sequential DO loop of a target region",
          "OpenMP 5.2 §13.8 (target) and §10.1 (parallel): a "
          "parallel construct may be nested in a target region",
          """\
  !$omp target map(to: a) map(tofrom: b, host_flag)
  @HOSTFLAG
  do k = 1, 3
    !$omp parallel do
    do i = 1, n
      b(i) = b(i) + a(i)
    end do
    !$omp end parallel do
  end do
  !$omp end target
""", ref="3*i", decls="  integer :: k\n", models=("omp",),
          mutant=(("b(i) = b(i) + a(i)", "b(i) = a(i)"),)),
    FSpec("host-data-generic", "base.device.host_data_generic",
          "a generic interface (integer and real(8) specifics) resolved in "
          "a call inside a host_data use_device region (the device address "
          "is passed; the specific only takes the size)",
          "OpenACC 3.4 \u00a72.8 (host_data construct: the device address of "
          "a var in use_device is used within the region)", """\
  !$acc data copyin(a) copyout(b) copy(host_flag)
  !$acc host_data use_device(a)
  m = nelem(a)
  !$acc end host_data
  !$acc parallel loop present(a, b, host_flag)
  do i = 1, n
    b(i) = 2*a(i) + m - n + 1
    if (i == 1) @HOSTFLAG
  end do
  !$acc end data
""", decls="  integer :: m\n", modules=module("""\
  interface nelem
    module procedure nelem_i, nelem_r
  end interface nelem
contains
  integer function nelem_i(x)
    integer, intent(in) :: x(:)
    nelem_i = size(x)
  end function nelem_i
  integer function nelem_r(x)
    real(8), intent(in) :: x(:)
    nelem_r = size(x)
  end function nelem_r"""), uses="  use wmod\n", models=("acc",),
          mutant=(("  m = nelem(a)\n", "  m = 0\n"),)),
    FSpec("loop-in-routine", "base.device.loop_in_routine",
          "a loop seq construct inside a routine seq procedure called in a "
          "parallel loop",
          "OpenACC 3.4 §2.9 (loop construct) and §2.15.1 (routine "
          "seq: a loop construct in it must be seq)",
          ploop("call rowsum(a2(:, i), b(i))",
                "to(a2) from(b) tofrom(host_flag)"),
          ref="10*i", decls="  integer :: a2(4, n)\n  integer :: k\n",
          init="  do i = 1, n\n    do k = 1, 4\n      a2(k, i) = k*i\n    end do\n"
               "  end do\n", modules=module("""\
contains
  subroutine rowsum(x, s)
    !$acc routine seq
    integer, intent(in) :: x(:)
    integer, intent(out) :: s
    integer :: k
    s = 0
    !$acc loop seq
    do k = 1, size(x)
      s = s + x(k)
    end do
  end subroutine rowsum"""), uses="  use wmod\n", models=("acc",),
          mutant=(("s = s + x(k)", "s = x(k)"),)),
]

# --- directives outside the slice, in device code (OpenMP, Fortran) ----------------

_CRIT = """\
  s = 0
  !$omp target parallel do map(to: a) map(tofrom: s, host_flag) private(t)
  do i = 1, n
    !$omp critical{name}{hint}
    t = s
    s = t + a(i)
    !$omp end critical{name}
    if (i == 1) @HOSTFLAG
  end do
  !$omp end target parallel do
"""
_SUM_CHECK = "s == n*(n + 1)/2"


def _crit(name="", hint=""):
    return _CRIT.format(name=name, hint=hint)


F_DIRECTIVES = [
    FSpec("critical", "omp.directive.critical",
          "an unnamed critical construct in a target parallel loop",
          OMP_CRITICAL, _crit(), check=_SUM_CHECK,
          decls="  integer :: s, t\n", models=("omp",),
          mutant_device="a race: without the construct the updates race",
          mutant=(("    !$omp critical\n", ""),
                  ("    !$omp end critical\n", ""))),
    FSpec("critical-named", "form.omp.critical_named",
          "a named critical construct in a target parallel loop",
          OMP_CRITICAL, _crit(" (wsum)"), check=_SUM_CHECK,
          decls="  integer :: s, t\n", models=("omp",),
          mutant_device="a race: without the construct the updates race",
          mutant=(("    !$omp critical (wsum)\n", ""),
                  ("    !$omp end critical (wsum)\n", ""))),
    FSpec("critical-hint", "omp.clause.hint",
          "a named critical construct with a hint clause in a target "
          "parallel loop", OMP_CRITICAL + "; §15.1 (hint clause)",
          _crit(" (wsum)", " hint(omp_sync_hint_contended)"),
          check=_SUM_CHECK, decls="  integer :: s, t\n",
          uses="  use omp_lib, only: omp_sync_hint_contended\n",
          models=("omp",),
          mutant_device="a race: without the construct the updates race",
          mutant=(("    !$omp critical (wsum) hint(omp_sync_hint_contended)\n",
                   ""), ("    !$omp end critical (wsum)\n", ""))),
    FSpec("sections", "omp.directive.sections",
          "a sections construct with two sections in a target parallel "
          "region", OMP_SECTIONS, """\
  !$omp target parallel map(to: a) map(tofrom: b, host_flag)
  !$omp sections
  !$omp section
  do i = 1, n/2
    b(i) = 2*a(i) + 1
  end do
  @HOSTFLAG
  !$omp section
  do i = n/2 + 1, n
    b(i) = a(i) + a(i) + 1
  end do
  !$omp end sections
  !$omp end target parallel
""", models=("omp",),
          mutant=(("b(i) = a(i) + a(i) + 1", "b(i) = 0"),)),
    FSpec("parallel-sections", "omp.directive.parallel_sections",
          "a parallel sections construct nested in a target region",
          OMP_SECTIONS, """\
  !$omp target map(to: a) map(tofrom: b, host_flag)
  @HOSTFLAG
  !$omp parallel sections
  !$omp section
  do i = 1, n/2
    b(i) = 2*a(i) + 1
  end do
  !$omp section
  do i = n/2 + 1, n
    b(i) = a(i) + a(i) + 1
  end do
  !$omp end parallel sections
  !$omp end target
""", models=("omp",),
          mutant=(("b(i) = a(i) + a(i) + 1", "b(i) = 0"),)),
    FSpec("single", "omp.directive.single",
          "a single construct in a target parallel region",
          "OpenMP 5.2 §11.1, p.221 (single construct)", """\
  s = 0
  !$omp target parallel map(tofrom: s, host_flag)
  !$omp single
  s = s + 1
  @HOSTFLAG
  !$omp end single
  !$omp end target parallel
""", check="s == 1", decls="  integer :: s\n", models=("omp",),
          mutant=(("  !$omp single\n", ""), ("  !$omp end single\n", ""),
                  ("  s = s + 1\n", "  s = s + 2\n"))),
    FSpec("masked", "omp.directive.masked",
          "a masked construct in a target parallel region",
          "OpenMP 5.2 §10.5, p.214 (masked construct)", """\
  s = 0
  !$omp target parallel map(tofrom: s, host_flag)
  !$omp masked
  s = s + 1
  @HOSTFLAG
  !$omp end masked
  !$omp end target parallel
""", check="s == 1", decls="  integer :: s\n", models=("omp",),
          mutant=(("  s = s + 1\n", "  s = s + 2\n"),)),
    FSpec("barrier", "omp.directive.barrier",
          "a barrier between a write by every thread and a read by the "
          "primary thread in a target parallel region",
          "OpenMP 5.2 §15.3.1, p.317 (barrier construct)", """\
  okf = 0
  c = 0
  !$omp target parallel num_threads(4) map(tofrom: c, okf, host_flag) private(tid, nt, k)
  tid = omp_get_thread_num()
  nt = omp_get_num_threads()
  c(tid + 1) = tid + 1
  !$omp barrier
  if (tid == 0) then
    okf = 1
    do k = 1, nt
      if (c(k) /= k) okf = 0
    end do
    @HOSTFLAG
  end if
  !$omp end target parallel
""", check="okf == 1",
          decls="  integer :: c(4), okf, tid, nt, k\n",
          uses="  use omp_lib, only: omp_get_thread_num, omp_get_num_threads\n",
          models=("omp",),
          mutant=(("      if (c(k) /= k) okf = 0\n", "      okf = 0\n"),)),
    FSpec("atomic", "omp.directive.atomic",
          "an atomic construct (update form, no clause) in a target loop",
          OMP_ATOMIC,
          ploop("!$omp atomic\ns = s + a(i)", "to(a) tofrom(s, host_flag)"),
          check=_SUM_CHECK, decls="  integer :: s\n", init="  s = 0\n",
          models=("omp",), mutant=(("s = s + a(i)", "s = s + 1"),)),
    FSpec("atomic-update", "omp.clause.update",
          "an atomic update construct in a target loop", OMP_ATOMIC,
          ploop("!$omp atomic update\ns = s + a(i)", "to(a) tofrom(s, host_flag)"),
          check=_SUM_CHECK, decls="  integer :: s\n", init="  s = 0\n",
          models=("omp",), mutant=(("s = s + a(i)", "s = s + 1"),)),
    FSpec("atomic-capture", "omp.clause.capture",
          "an atomic capture construct (each iteration takes a ticket) in a "
          "target loop", OMP_ATOMIC,
          ploop("!$omp atomic capture\nt = s\ns = s + 1\n!$omp end atomic\n"
                "b(i) = t", "tofrom(s, b, host_flag) private(t)"),
          check="s == n .and. sum(b) == n*(n - 1)/2",
          decls="  integer :: s, t\n", init="  s = 0\n", models=("omp",),
          mutant=(("    t = s\n    s = s + 1\n", "    s = s + 1\n    t = s\n"),)),
    FSpec("atomic-write", "omp.clause.write",
          "an atomic write construct in a target loop", OMP_ATOMIC,
          ploop("b(i) = 2*a(i) + 1\nif (i == n) then\n  !$omp atomic write\n"
                "  w = 7\nend if", "to(a) from(b) tofrom(w, host_flag)"),
          check="all(b == ref) .and. w == 7", decls="  integer :: w\n",
          init="  w = 0\n", models=("omp",),
          mutant=(("  w = 7\n", "  w = 6\n"),)),
    FSpec("atomic-read", "omp.clause.read",
          "an atomic read construct in a target loop", OMP_ATOMIC,
          ploop("!$omp atomic read\nt = w\nb(i) = a(i) + t",
                "to(a, w) from(b) tofrom(host_flag) private(t)"),
          ref="i + 7", decls="  integer :: w, t\n", init="  w = 7\n",
          models=("omp",), mutant=(("b(i) = a(i) + t", "b(i) = a(i)"),)),
    FSpec("ordered", "omp.directive.ordered",
          "an ordered region in a target parallel do with the ordered clause",
          "OpenMP 5.2 §15.10.1, p.338 (ordered construct)", """\
  cnt = 0
  !$omp target parallel do ordered map(to: a) map(tofrom: b, cnt, host_flag)
  do i = 1, n
    !$omp ordered
    cnt = cnt + 1
    b(cnt) = a(i)
    !$omp end ordered
    if (i == 1) @HOSTFLAG
  end do
  !$omp end target parallel do
""", ref="i", check="all(b == ref) .and. cnt == n",
          decls="  integer :: cnt\n", models=("omp",),
          mutant=(("    b(cnt) = a(i)\n", "    b(cnt) = a(n + 1 - i)\n"),)),
    FSpec("task", "omp.directive.task",
          "a task and a taskwait in a target region",
          "OpenMP 5.2 §12.5, p.247 (task construct)", """\
  s = 0
  !$omp target map(tofrom: s, host_flag)
  @HOSTFLAG
  !$omp task shared(s)
  s = s + 1
  !$omp end task
  !$omp taskwait
  !$omp end target
""", check="s == 1", decls="  integer :: s\n", models=("omp",),
          mutant=(("  s = s + 1\n", "  s = s + 2\n"),)),
    FSpec("declare-mapper", "omp.directive.declare_mapper",
          "a default declare mapper of a derived type with a POINTER "
          "component, applied by map(to: r) in a target loop (the default "
          "mapper leaves the pointer's association undefined, the declared "
          "one maps its target)", OMP_MAPPER,
          ploop("b(i) = r%p(i) + 1", "to(r) from(b) tofrom(host_flag)"),
          ref="3*i + 1", modules=module("""\
  type prec_t
    integer :: k = 0
    integer, pointer :: p(:) => null()
  end type prec_t
  !$omp declare mapper(prec_t :: x) map(x, x%p)""", "wtypes"),
          uses="  use wtypes\n", decls="  type(prec_t) :: r\n",
          init="  allocate(r%p(n))\n  r%p = 3*a\n", models=("omp",),
          mutant_device="copy semantics: without the mapper the pointer component's association on the device is undefined (OpenMP 5.2 \u00a75.8.3, p.150); under unified memory the host pointer still works",
          mutant=(("  !$omp declare mapper(prec_t :: x) map(x, x%p)\n", ""),)),
    FSpec("declare-mapper-extended-type",
          "form.omp.declare_mapper_extended_type",
          "a default declare mapper of an extended derived type (an "
          "inherited component and an own POINTER component)", OMP_MAPPER,
          ploop("b(i) = e%k*e%w(i) + 1", "to(e) from(b) tofrom(host_flag)"),
          ref="3*i + 1", modules=module("""\
  type base_t
    integer :: k = 1
  end type base_t
  type, extends(base_t) :: ext_t
    integer, pointer :: w(:) => null()
  end type ext_t
  !$omp declare mapper(ext_t :: x) map(x, x%w)""", "wtypes"),
          uses="  use wtypes\n", decls="  type(ext_t) :: e\n",
          init="  allocate(e%w(n))\n  e%w = 3*a\n", models=("omp",),
          mutant_device="copy semantics: without the mapper the pointer component's association on the device is undefined (OpenMP 5.2 \u00a75.8.3, p.150); under unified memory the host pointer still works",
          mutant=(("  !$omp declare mapper(ext_t :: x) map(x, x%w)\n", ""),)),
]

# --- pairs (Fortran) ------------------------------------------------------------------
#
# A pair's parts each have a program of their own (tests/cluster/test_widen.py);
# omp / acc parts are the model's own construct atoms.

_A2 = ("  integer :: a2(4, n), c2(4, n)\n  integer :: j\n",
       "  do i = 1, n\n    do j = 1, 4\n      a2(j, i) = i*j\n      c2(j, i) = 0\n"
       "    end do\n  end do\n")
OMP_PART = {"collapse": "omp.clause.collapse",
            "reduction": "omp.clause.reduction",
            "update": "omp.directive.target_update",
            "atomic": "omp.directive.atomic",
            "private": "omp.clause.private",
            "firstprivate": "omp.clause.firstprivate",
            "data": "omp.directive.target_data",
            "enter": "omp.directive.target_enter_data"}
ACC_PART = {"collapse": "acc.clause.collapse",
            "reduction": "acc.clause.reduction",
            "update": "acc.directive.update",
            "atomic": "acc.directive.atomic",
            "private": "acc.clause.private",
            "firstprivate": "acc.clause.firstprivate",
            "data": "acc.directive.data",
            "enter": "acc.directive.enter_data"}


def pair_atom(a: str, b: str) -> str:
    return f"pair.{a}+{b}"


def pair(slug, construct, base, feature, kernel, models=("omp", "acc"),
         **kw):
    """One FSpec per model: parts (the model's `construct` atom, `base`)."""
    out = []
    for m in models:
        tab = OMP_PART if m == "omp" else ACC_PART
        parts = (tab.get(construct, construct), tab.get(base, base))
        extra = dict(kw)
        acc = extra.pop("acc", {})
        out.append(FSpec(slug, pair_atom(*parts), feature,
                         extra.pop("spec", "the parts' own programs"),
                         kernel, models=(m,), parts=parts,
                         acc=acc if m == "acc" else {}, **extra))
    return out


def _c2loop(body, clauses, hf="if (i == 1 .and. j == 1) @HOSTFLAG"):
    inner = "\n".join("      " + ln for ln in body.strip("\n").splitlines())
    return (f"  @PLOOP {clauses} collapse(2)\n  do j = 1, 4\n    do i = 1, n\n"
            f"{inner}\n      {hf}\n    end do\n  end do\n  @END_PLOOP\n")


_REC_ALLOC = dict(modules=_TYPES_ALLOC, uses="  use wtypes\n",
                  decls="  type(rec_t) :: r\n",
                  init="  allocate(r%v(n))\n  r%v = 3*a\n")

F_PAIRS = [
    *pair("collapse-private-array", "collapse", "base.device.private_array",
          "a private array in a collapse(2) target loop",
          _c2loop("t(1) = a2(j, i)\nt(2) = 1\nt(3) = a2(j, i)\nt(4) = 0\n"
                  "c2(j, i) = sum(t)", "to(a2) from(c2) tofrom(host_flag) "
                  "private(t)"),
          check="all(c2 == 2*a2 + 1)", decls=_A2[0] + _PRIV_T, init=_A2[1],
          mutant=(("t(2) = 1", "t(2) = 0"),)),
    *pair("collapse-reduction", "collapse", "reduction",
          "a sum reduction over a collapse(2) target loop",
          _c2loop("s = s + a2(j, i)", "to(a2) tofrom(host_flag) "
                  "reduction(+:s)"),
          check="s == 10*n*(n + 1)/2", decls=_A2[0] + "  integer :: s\n",
          init=_A2[1] + "  s = 0\n",
          mutant=(("s = s + a2(j, i)", "s = s + 1"),)),
    *pair("collapse-routine-call", "collapse", "base.device.routine_call",
          "a device routine called in a collapse(2) target loop",
          _c2loop("c2(j, i) = tw(a2(j, i))", "to(a2) from(c2) tofrom(host_flag)"),
          check="all(c2 == 2*a2 + 1)", decls=_A2[0], init=_A2[1],
          modules=_ROUTINE_TW, uses="  use wmod\n",
          mutant=(("tw = 2*x + 1", "tw = 2*x"),)),
    *pair("reduction-routine-call", "reduction", "base.device.routine_call",
          "a device routine called in a sum reduction loop",
          ploop("s = s + tw(a(i))", "to(a) tofrom(host_flag) reduction(+:s)"),
          check="s == n*(n + 1) + n", decls="  integer :: s\n",
          init="  s = 0\n", modules=_ROUTINE_TW, uses="  use wmod\n",
          mutant=(("tw = 2*x + 1", "tw = 2*x"),)),
    *pair("update-alloc-component", "update", "base.device.alloc_component",
          "an allocatable component kept on the device by enter data, "
          "updated from the host between two target loops",
          "  @ENTER to(r%v)\n"
          + ploop("b(i) = r%v(i) + 1", "to(r%v) from(b) tofrom(host_flag)")
          + "  r%v = 5*a\n  @UPD_TO(r%v)\n"
          + ploop("b(i) = b(i) + r%v(i)", "to(r%v) tofrom(b)", flag=False)
          + "  @EXIT delete(r%v)\n",
          ref="8*i + 1", **_REC_ALLOC,
          acc={"kernel": "  @ENTER to(r)\n  @ENTER to(r%v)\n"
               + ploop("b(i) = r%v(i) + 1", "present(r) from(b) tofrom(host_flag)")
               + "  r%v = 5*a\n  @UPD_TO(r%v)\n"
               + ploop("b(i) = b(i) + r%v(i)", "present(r) tofrom(b)",
                       flag=False)
               + "  @EXIT delete(r%v)\n  @EXIT delete(r)\n",
               "mutant": (("  !$acc update device(r%v)\n", ""),)},
          mutant_device="copy semantics: without the update the device keeps the old values (separate memory only)",
          mutant=(("  !$omp target update to(r%v)\n", ""),)),
    *pair("collapse-alloc-component", "collapse", "base.device.alloc_component",
          "an allocatable component read in a collapse(2) target loop",
          _c2loop("c2(j, i) = r%v(i)*j + 1", "to(r%v) from(c2) tofrom(host_flag)"),
          check="all(c2 == 3*a2 + 1)",
          modules=_TYPES_ALLOC, uses="  use wtypes\n",
          decls="  type(rec_t) :: r\n" + _A2[0],
          init="  allocate(r%v(n))\n  r%v = 3*a\n" + _A2[1],
          acc={"kernel": "  @ENTER to(r)\n  @ENTER to(r%v)\n" + _c2loop(
              "c2(j, i) = r%v(i)*j + 1", "present(r) from(c2) tofrom(host_flag)")
              + "  @EXIT delete(r%v)\n  @EXIT delete(r)\n"},
          mutant=(("c2(j, i) = r%v(i)*j + 1", "c2(j, i) = 1"),)),
    *pair("atomic-reduction", "atomic", "reduction",
          "an atomic update of one variable and a sum reduction of another "
          "in one target loop",
          ploop("s = s + a(i)\n@ATOMIC\nw = w + 1",
                "to(a) tofrom(w, host_flag) reduction(+:s)"),
          check="s == n*(n + 1)/2 .and. w == n", decls="  integer :: s, w\n",
          init="  s = 0\n  w = 0\n",
          mutant=(("w = w + 1", "w = w + 2"),)),
    *pair("atomic-derived-component", "atomic", "base.device.derived_scalar",
          "an atomic update of an integer component of a mapped derived-type "
          "scalar in a target loop",
          ploop("@ATOMIC\nst%k = st%k + a(i)", "to(a) tofrom(st, host_flag)"),
          check="st%k == n*(n + 1)/2 .and. st%m == 1",
          modules=_TYPES_PT, uses="  use wtypes\n",
          decls="  type(par_t) :: st\n", init="  st%k = 0\n  st%m = 1\n",
          mutant=(("st%k = st%k + a(i)", "st%k = st%k + 1"),)),
    *pair("private-array-routine-arg", "base.device.private_array",
          "base.device.assumed_shape_routine",
          "a private array passed to a device routine with an assumed-shape "
          "dummy",
          ploop("call fill(t, a(i))\nb(i) = sum(t)",
                "to(a) from(b) tofrom(host_flag) private(t)"),
          decls=_PRIV_T, modules=module("""\
contains
  subroutine fill(x, v)
    @ROUTINE
    integer, intent(out) :: x(:)
    integer, intent(in) :: v
    x = 0
    x(1) = v
    x(2) = v + 1
  end subroutine fill"""), uses="  use wmod\n",
          mutant=(("x(2) = v + 1", "x(2) = v"),)),
    *pair("collapse-select-case", "collapse", "base.device.select_case",
          "a SELECT CASE in a collapse(2) target loop",
          _c2loop("select case (mod(a2(j, i), 3))\ncase (0)\n  c2(j, i) = 1\n"
                  "case default\n  c2(j, i) = 2\nend select",
                  "to(a2) from(c2) tofrom(host_flag)"),
          check="all(c2 == merge(1, 2, mod(a2, 3) == 0))",
          decls=_A2[0], init=_A2[1],
          mutant=(("  c2(j, i) = 2\n", "  c2(j, i) = 1\n"),)),
    *pair("collapse-stop", "collapse", "base.device.stop",
          "an unreached STOP in a collapse(2) target loop",
          _c2loop("if (a2(j, i) < 0) stop 1\nc2(j, i) = 2*a2(j, i) + 1",
                  "to(a2) from(c2) tofrom(host_flag)"),
          check="all(c2 == 2*a2 + 1)", decls=_A2[0], init=_A2[1],
          mutant=(("c2(j, i) = 2*a2(j, i) + 1", "c2(j, i) = 2*a2(j, i)"),)),
    *pair("data-optional-absent", "data", "base.device.optional_absent",
          "an absent OPTIONAL dummy in the map clause of a data region "
          "around a target loop that tests PRESENT()",
          "  call work(a, b, host_flag)\n", contains="""\
  subroutine work(x, y, hf, c)
    integer, intent(in) :: x(n)
    integer, intent(inout) :: y(n)
    integer, intent(inout) :: hf
    integer, intent(in), optional :: c(n)
    integer :: k
    @DATA to(c)
    @PLOOP to(x) tofrom(y, hf)
    do k = 1, n
      if (present(c)) then
        y(k) = x(k) + c(k)
      else
        y(k) = 2*x(k) + 1
      end if
      if (k == 1) @HOSTFLAG[hf]
    end do
    @END_PLOOP
    @END_DATA
  end subroutine work
""", mutant=(("y(k) = 2*x(k) + 1", "y(k) = 2*x(k)"),)),
    *pair("enter-assumed-shape", "enter", "base.device.assumed_shape_target",
          "assumed-shape dummy arrays put on the device with enter data, "
          "used by a target loop and brought back with exit data",
          "  call work(a, b, host_flag)\n", contains="""\
  subroutine work(x, y, hf)
    integer, intent(in) :: x(:)
    integer, intent(inout) :: y(:)
    integer, intent(inout) :: hf
    integer :: k
    @ENTER to(x) alloc(y)
    @PLOOP present(x, y) tofrom(hf)
    do k = 1, size(x)
      y(k) = 2*x(k) + 1
      if (k == 1) @HOSTFLAG[hf]
    end do
    @END_PLOOP
    @EXIT from(y) delete(x)
  end subroutine work
""", mutant=(("y(k) = 2*x(k) + 1", "y(k) = 2*x(k)"),)),
    *pair("reduction-derived-array", "reduction", "base.device.derived_array",
          "a sum reduction over the components of a mapped array of a "
          "derived type",
          ploop("s = s + ps(i)%x + ps(i)%y", "to(ps) tofrom(host_flag) "
                "reduction(+:s)"),
          check="s == 3*n*(n + 1)/2", modules=_TYPES_PT, uses="  use wtypes\n",
          decls="  type(pt_t) :: ps(n)\n  integer :: s\n",
          init="  do i = 1, n\n    ps(i)%x = i\n    ps(i)%y = 2*i\n  end do\n"
               "  s = 0\n",
          mutant=(("s = s + ps(i)%x + ps(i)%y", "s = s + ps(i)%x"),)),
    *pair("elemental-array-syntax", "base.device.elemental",
          "base.device.array_syntax",
          "an ELEMENTAL device function applied to strided array sections",
          region("b(1:n:2) = tw(a(1:n:2))\nb(2:n:2) = tw(a(2:n:2))"),
          modules=module("""\
contains
  elemental integer function tw(x)
    @ROUTINE
    integer, intent(in) :: x
    tw = 2*x + 1
  end function tw"""), uses="  use wmod\n",
          mutant=(("tw = 2*x + 1", "tw = 2*x"),)),
    *pair("reduction-math", "reduction", "base.device.intrinsic_math",
          "a real(8) sum reduction of SIN**2 + COS**2 (checked to 1e-9)",
          ploop("x = real(a(i), 8)\ns = s + sin(x)**2 + cos(x)**2",
                "to(a) tofrom(host_flag) private(x) reduction(+:s)"),
          check="abs(s - real(n, 8)) < 1.0d-9",
          decls="  real(8) :: s, x\n", init="  s = 0.0d0\n",
          mutant=((" + cos(x)**2", ""),)),
    *pair("reduction-complex", "reduction", "base.device.complex",
          "a COMPLEX(8) sum reduction", ploop(
              "z = z + cmplx(a(i), -a(i), 8)",
              "to(a) tofrom(host_flag) reduction(+:z)"),
          check="real(z) == real(n*(n + 1)/2, 8) .and. aimag(z) == "
                "-real(n*(n + 1)/2, 8)",
          decls="  complex(8) :: z\n", init="  z = (0.0d0, 0.0d0)\n",
          mutant=(("cmplx(a(i), -a(i), 8)", "cmplx(a(i), a(i), 8)"),)),
    *pair("private-derived-scalar", "private", "base.device.derived_scalar",
          "a private scalar of a derived type in a target loop",
          ploop("t%k = a(i)\nt%m = 1\nb(i) = 2*t%k + t%m",
                "to(a) from(b) tofrom(host_flag) private(t)"),
          modules=_TYPES_PT, uses="  use wtypes\n",
          decls="  type(par_t) :: t\n",
          mutant=(("b(i) = 2*t%k + t%m", "b(i) = 2*t%k"),)),
    *pair("firstprivate-derived-scalar", "firstprivate",
          "base.device.derived_scalar",
          "a firstprivate scalar of a derived type in a target loop",
          ploop("b(i) = s%k*a(i) + s%m",
                "to(a) from(b) tofrom(host_flag) firstprivate(s)"),
          ref="3*i + 1", modules=_TYPES_PT, uses="  use wtypes\n",
          decls="  type(par_t) :: s\n", init="  s%k = 3\n  s%m = 1\n",
          mutant=(("b(i) = s%k*a(i) + s%m", "b(i) = s%k*a(i)"),)),
    *pair("atomic-collapse", "atomic", "collapse",
          "an atomic update of a histogram bin in a collapse(2) target loop",
          _c2loop("@ATOMIC\nh(mod(a2(j, i), 4) + 1) = h(mod(a2(j, i), 4) + 1) + 1",
                  "to(a2) tofrom(h, host_flag)"),
          check="all(h == hr)", decls=_A2[0] + "  integer :: h(4), hr(4)\n",
          init=_A2[1] + "  h = 0\n  hr = 0\n  do i = 1, n\n    do j = 1, 4\n"
               "      hr(mod(i*j, 4) + 1) = hr(mod(i*j, 4) + 1) + 1\n    end do\n"
               "  end do\n",
          mutant=(("= h(mod(a2(j, i), 4) + 1) + 1", "= h(mod(a2(j, i), 4) + 1) + 2"),)),
    *pair("update-derived-array", "update", "base.device.derived_array",
          "an array of a derived type kept on the device by enter data and "
          "updated from the host between two target loops",
          "  @ENTER to(ps)\n"
          + ploop("b(i) = ps(i)%x + ps(i)%y", "present(ps) from(b) tofrom(host_flag)")
          + "  do i = 1, n\n    ps(i)%y = 5*i\n  end do\n  @UPD_TO(ps)\n"
          + ploop("b(i) = b(i) + ps(i)%y", "present(ps) tofrom(b)", flag=False)
          + "  @EXIT delete(ps)\n",
          ref="8*i", modules=_TYPES_PT, uses="  use wtypes\n",
          decls="  type(pt_t) :: ps(n)\n",
          init="  do i = 1, n\n    ps(i)%x = i\n    ps(i)%y = 2*i\n  end do\n",
          mutant_device="copy semantics: without the update the device keeps the old values (separate memory only)",
          mutant=(("  !$omp target update to(ps)\n", ""),),
          acc={"mutant": (("  !$acc update device(ps)\n", ""),)}),
    *pair("collapse-derived-array", "collapse", "base.device.derived_array",
          "an array of a derived type read in a collapse(2) target loop",
          _c2loop("c2(j, i) = ps(i)%x*j + ps(i)%y",
                  "to(ps) from(c2) tofrom(host_flag)"),
          check="all(c2 == a2 + spread(2*a, 1, 4))", modules=_TYPES_PT,
          uses="  use wtypes\n", decls="  type(pt_t) :: ps(n)\n" + _A2[0],
          init="  do i = 1, n\n    ps(i)%x = i\n    ps(i)%y = 2*i\n  end do\n"
               + _A2[1],
          mutant=(("c2(j, i) = ps(i)%x*j + ps(i)%y", "c2(j, i) = ps(i)%x*j"),)),
    *pair("reduction-private-array", "reduction", "base.device.private_array",
          "a private array and a sum reduction in one target loop",
          ploop("t(1) = a(i)\nt(2) = 1\nt(3) = a(i)\nt(4) = 0\ns = s + sum(t)",
                "to(a) tofrom(host_flag) private(t) reduction(+:s)"),
          check="s == n*(n + 1) + n", decls=_PRIV_T + "  integer :: s\n",
          init="  s = 0\n", mutant=(("t(2) = 1", "t(2) = 0"),)),
    *pair("data-alloc-component", "data", "base.device.alloc_component",
          "an allocatable component mapped by a data region around a "
          "target loop",
          "  @DATA to(r%v)\n" + ploop("b(i) = r%v(i) + 1",
                                      "to(r%v) from(b) tofrom(host_flag)")
          + "  @END_DATA\n", ref="3*i + 1", **_REC_ALLOC,
          acc={"kernel": "  @DATA to(r)\n  @DATA to(r%v)\n" + ploop(
              "b(i) = r%v(i) + 1", "present(r) from(b) tofrom(host_flag)")
              + "  @END_DATA\n  @END_DATA\n"},
          mutant=(("b(i) = r%v(i) + 1", "b(i) = 1"),)),
    *pair("routine-stop", "base.device.routine_call", "base.device.stop",
          "an unreached STOP in a device routine",
          ploop("b(i) = tw(a(i))"), modules=module("""\
contains
  integer function tw(x)
    @ROUTINE
    integer, intent(in) :: x
    if (x < 0) stop 3
    tw = 2*x + 1
  end function tw"""), uses="  use wmod\n",
          mutant=(("tw = 2*x + 1", "tw = 2*x"),)),
    *pair("routine-character", "base.device.routine_call",
          "base.device.character",
          "a device routine with a CHARACTER(len=*) dummy",
          ploop("s = 'abcdefgh'\nb(i) = code(s(1:mod(i, 8) + 1))",
                "to(a) from(b) tofrom(host_flag) private(s)"),
          ref="97 + mod(i, 8) + 1", decls="  character(len=8) :: s\n",
          modules=module("""\
contains
  integer function code(c)
    @ROUTINE
    character(len=*), intent(in) :: c
    code = ichar(c(1:1)) + len(c)
  end function code"""), uses="  use wmod\n",
          mutant=(("code = ichar(c(1:1)) + len(c)", "code = ichar(c(1:1))"),)),
    # OpenMP only
    *pair("critical-reduction", "omp.directive.critical", "omp.clause.reduction",
          "a critical update of one variable and a sum reduction of another "
          "in one target parallel loop", """\
  s = 0
  w = 0
  !$omp target parallel do map(to: a) map(tofrom: w, host_flag) reduction(+: s)
  do i = 1, n
    s = s + a(i)
    !$omp critical
    w = w + 1
    !$omp end critical
    if (i == 1) @HOSTFLAG
  end do
  !$omp end target parallel do
""", models=("omp",), check="s == n*(n + 1)/2 .and. w == n",
          decls="  integer :: s, w\n", mutant=(("w = w + 1", "w = w + 2"),)),
    *pair("lastprivate-parallel-in-seq-loop", "omp.clause.lastprivate",
          "base.device.parallel_in_seq_loop",
          "lastprivate on a parallel do nested in a sequential loop of a "
          "target region", """\
  !$omp target map(to: a) map(tofrom: b, host_flag)
  @HOSTFLAG
  do k = 1, 3
    !$omp parallel do lastprivate(last)
    do i = 1, n
      last = a(i) + k
    end do
    !$omp end parallel do
    b(k) = last
  end do
  !$omp end target
""", models=("omp",), check="all(b(1:3) == [n + 1, n + 2, n + 3])",
          decls="  integer :: k, last\n",
          mutant=(("last = a(i) + k", "last = a(i)"),)),
    *pair("reduction-parallel-in-seq-loop", "omp.clause.reduction",
          "base.device.parallel_in_seq_loop",
          "a reduction on a parallel do nested in a sequential loop of a "
          "target region", """\
  s = 0
  !$omp target map(to: a) map(tofrom: s, host_flag)
  @HOSTFLAG
  do k = 1, 3
    !$omp parallel do reduction(+: s)
    do i = 1, n
      s = s + a(i)
    end do
    !$omp end parallel do
  end do
  !$omp end target
""", models=("omp",), check="s == 3*n*(n + 1)/2",
          decls="  integer :: k, s\n", mutant=(("s = s + a(i)", "s = s + 1"),)),
    *pair("defaultmap-present-private-array", "omp.clause.defaultmap.present",
          "base.device.private_array",
          "defaultmap(present: aggregate) with a private array on the same "
          "target loop (the arrays the loop maps are present by enter data)",
          """\
  !$omp target enter data map(to: a) map(alloc: b)
  !$omp target teams distribute parallel do defaultmap(present: aggregate) &
  !$omp& private(t) map(tofrom: host_flag)
  do i = 1, n
    t(1) = a(i)
    t(2) = 1
    t(3) = a(i)
    t(4) = 0
    b(i) = sum(t)
    if (i == 1) @HOSTFLAG
  end do
  !$omp end target teams distribute parallel do
  !$omp target exit data map(from: b) map(release: a)
""", models=("omp",), decls=_PRIV_T, mutant=(("t(2) = 1", "t(2) = 0"),),
          spec="OpenMP 5.2 §5.8.7, p.161 (defaultmap applies to variables "
               "without an explicitly determined attribute: the private "
               "array is not one)"),
    *pair("allocate-const-firstprivate", "omp.clause.allocate",
          "omp.clause.firstprivate",
          "a firstprivate scalar allocated with omp_const_mem_alloc "
          "(uses_allocators) on a target loop", """\
  x = 5
  !$omp target teams distribute parallel do map(to: a) map(from: b) &
  !$omp& map(tofrom: host_flag) firstprivate(x) allocate(omp_const_mem_alloc: x) &
  !$omp& uses_allocators(omp_const_mem_alloc)
  do i = 1, n
    b(i) = a(i) + x
    if (i == 1) @HOSTFLAG
  end do
  !$omp end target teams distribute parallel do
""", models=("omp",), ref="i + 5", decls="  integer :: x\n",
          uses="  use omp_lib, only: omp_const_mem_alloc\n",
          mutant=(("b(i) = a(i) + x", "b(i) = a(i)"),),
          spec="OpenMP 5.2 §6.6 (allocate clause) and §13.8, p.285: "
               "an allocator in a uses_allocators clause may be used in an "
               "allocate clause on the target construct"),
    *pair("mapper-reduction", "omp.directive.declare_mapper",
          "omp.clause.reduction",
          "a sum reduction over the POINTER component of a structure "
          "mapped through its declared default mapper",
          ploop("s = s + r%p(i)", "to(r) tofrom(host_flag) reduction(+:s)"),
          models=("omp",), check="s == 3*n*(n + 1)/2",
          modules=module("""\
  type prec_t
    integer :: k = 0
    integer, pointer :: p(:) => null()
  end type prec_t
  !$omp declare mapper(prec_t :: x) map(x, x%p)""", "wtypes"),
          uses="  use wtypes\n", decls="  type(prec_t) :: r\n  integer :: s\n",
          init="  allocate(r%p(n))\n  r%p = 3*a\n  s = 0\n",
          mutant_device="copy semantics: without the mapper the pointer component's association on the device is undefined (OpenMP 5.2 \u00a75.8.3, p.150); under unified memory the host pointer still works",
          mutant=(("  !$omp declare mapper(prec_t :: x) map(x, x%p)\n", ""),)),
    *pair("mapper-iterator", "omp.directive.declare_mapper",
          "omp.clause.map.iterator",
          "a default declare mapper whose map clause has an iterator over "
          "the POINTER components of an array component",
          ploop("b(i) = r%s(1)%p(i) + r%s(2)%p(i)",
                "to(r) from(b) tofrom(host_flag)"),
          models=("omp",), ref="5*i", modules=module("""\
  type seg_t
    integer, pointer :: p(:) => null()
  end type seg_t
  type rec2_t
    type(seg_t) :: s(2)
  end type rec2_t
  !$omp declare mapper(rec2_t :: x) map(x) map(iterator(k = 1:2), to: x%s(k)%p)""", "wtypes"),
          uses="  use wtypes\n", decls="  type(rec2_t) :: r\n",
          init="  allocate(r%s(1)%p(n), r%s(2)%p(n))\n  r%s(1)%p = 2*a\n"
               "  r%s(2)%p = 3*a\n",
          spec="OpenMP 5.2 \u00a75.8.8 (declare mapper) and \u00a73.2.6 (iterator modifier)",
          mutant_device="copy semantics: without the mapper the pointer component's association on the device is undefined (OpenMP 5.2 \u00a75.8.3, p.150); under unified memory the host pointer still works",
          mutant=(("  !$omp declare mapper(rec2_t :: x) map(x) map(iterator(k = 1:2), to: x%s(k)%p)\n", ""),)),
    *pair("enter-alloc-component-whole", "omp.directive.target_enter_data",
          "base.device.alloc_component_whole",
          "a derived type with an allocatable component put on the device "
          "whole by enter data (the default mapper maps the component) and "
          "used by a target loop",
          "  !$omp target enter data map(to: r)\n"
          + ploop("b(i) = r%v(i) + 1", "from(b) tofrom(host_flag)")
          + "  !$omp target exit data map(delete: r)\n",
          models=("omp",), ref="3*i + 1", **_REC_ALLOC,
          mutant=(("b(i) = r%v(i) + 1", "b(i) = 1"),)),
    # OpenACC only
    *pair("loop-in-routine-sequence-association",
          "base.device.loop_in_routine", "base.device.sequence_association",
          "an array element passed to an explicit-shape dummy of a routine "
          "seq procedure that has a loop seq construct",
          ploop("call rowsum(a2(1, i), 4, b(i))",
                "to(a2) from(b) tofrom(host_flag)"),
          models=("acc",), ref="10*i",
          decls="  integer :: a2(4, n)\n  integer :: k\n",
          init="  do i = 1, n\n    do k = 1, 4\n      a2(k, i) = k*i\n    end do\n"
               "  end do\n", modules=module("""\
contains
  subroutine rowsum(x, m, s)
    !$acc routine seq
    integer, intent(in) :: m
    integer, intent(in) :: x(m)
    integer, intent(out) :: s
    integer :: k
    s = 0
    !$acc loop seq
    do k = 1, m
      s = s + x(k)
    end do
  end subroutine rowsum"""), uses="  use wmod\n",
          mutant=(("s = s + x(k)", "s = x(k)"),)),
    *pair("kernels-derived-array", "acc.directive.kernels",
          "base.device.derived_array",
          "an array of a derived type read in a kernels construct", """\
  !$acc kernels copyin(ps) copyout(b) copy(host_flag)
  do i = 1, n
    b(i) = ps(i)%x + 2*ps(i)%y
  end do
  @HOSTFLAG
  !$acc end kernels
""", models=("acc",), ref="5*i", modules=_TYPES_PT, uses="  use wtypes\n",
          decls="  type(pt_t) :: ps(n)\n",
          init="  do i = 1, n\n    ps(i)%x = i\n    ps(i)%y = 2*i\n  end do\n",
          mutant=(("b(i) = ps(i)%x + 2*ps(i)%y", "b(i) = ps(i)%x"),)),
]



# --- From the application corpus (data/bench/apps) ----------------------------------
# A failing kernel of a real code whose construct, pair or form the catalog
# did not have; each reduced to a program of its own (parts: their own
# programs). Sources: miniWeather (target update with depend, AFAR
# rejects), PRK transpose (a team-private array shared by a nested parallel
# loop, AFAR and CCE wrong), PRK stencil (OpenACC tile over a loop body with
# inner loops, CCE rejects).
OMP_UPDATE_DEPEND = ("OpenMP 5.2 §13.9, p.292 (target update construct: "
                     "depend and nowait clauses); §15.9.5 (depend clause)")
OMP_TEAMS_PRIVATE = ("OpenMP 5.2 §10.2, p.214 (teams: private list items are "
                     "private to each team) and §10.1 (a parallel region in a "
                     "teams region: its threads share the team's variables); "
                     "§5.4.3 (private clause)")
ACC_TILE = ("OpenACC 3.4 §2.9.8, p.68 (tile clause: the loops of the tile "
            "are the tightly nested loops the clause names; the body of the "
            "innermost may hold other loops)")

F_APPS = [
    FSpec("update-depend", "pair.omp.directive.target_update+omp.clause.depend",
          "a target update with a depend clause between two device loops "
          "(then taskwait)", OMP_UPDATE_DEPEND, """  !$omp target enter data map(to: a) map(alloc: b)
  !$omp target teams distribute parallel do map(tofrom: host_flag)
  do i = 1, n
    b(i) = 2*a(i) + 1
    if (i == 1) @HOSTFLAG
  end do
  !$omp end target teams distribute parallel do
  !$omp target update from(b) depend(inout: b)
  !$omp taskwait
  !$omp target exit data map(delete: a, b)
""", models=("omp",),
          parts=("omp.directive.target_update", "omp.clause.depend"),
          mutant=(("  !$omp target update from(b) depend(inout: b)\n", ""),),
          mutant_device="copy semantics: without the update the host keeps "
                        "b = 0 (separate memory only)"),
    FSpec("update-depend-nowait",
          "form.omp.target_update_depend_nowait",
          "a deferred target update (depend, nowait) completed by taskwait",
          OMP_UPDATE_DEPEND, """  !$omp target enter data map(to: a) map(alloc: b)
  !$omp target teams distribute parallel do map(tofrom: host_flag) depend(out: b) nowait
  do i = 1, n
    b(i) = 2*a(i) + 1
    if (i == 1) @HOSTFLAG
  end do
  !$omp end target teams distribute parallel do
  !$omp target update from(b) depend(inout: b) nowait
  !$omp taskwait
  !$omp target exit data map(delete: a, b)
""", models=("omp",),
          mutant=(("  !$omp target update from(b) depend(inout: b) nowait\n",
                   ""),),
          mutant_device="copy semantics: without the update the host keeps "
                        "b = 0 (separate memory only)"),
    FSpec("teams-private-array-parallel",
          "form.omp.teams_private_array_nested_parallel",
          "an array private to each team (teams distribute private) written "
          "and read by the threads of nested parallel loops",
          OMP_TEAMS_PRIVATE, """  !$omp target teams distribute private(t, j) map(to: a) map(from: b) map(tofrom: host_flag)
  do jt = 1, n, 4
    !$omp parallel do
    do j = 0, 3
      t(j) = a(jt + j)
    end do
    !$omp end parallel do
    !$omp parallel do
    do j = 0, 3
      b(jt + j) = 2*t(3 - j) + 1
    end do
    !$omp end parallel do
    if (jt == 1) @HOSTFLAG
  end do
  !$omp end target teams distribute
""", models=("omp",), ref="2*(2*(4*((i-1)/4)+1)+3-i)+1",
          decls="  integer :: t(0:3), j, jt\n",
          mutant=(("b(jt + j) = 2*t(3 - j) + 1", "b(jt + j) = 2*t(j) + 1"),)),
    FSpec("declared-alloc-component", "base.device.declared_alloc_component",
          "a module variable of a derived type with an allocatable "
          "component made device data (declare target / declare create), "
          "its component entered by enter data and read in a device loop",
          "OpenMP 5.2 \u00a77.8.1 (declare target: a module variable may be "
          "a declare target list item) and \u00a75.8.3 (map: a structure "
          "component with the allocatable attribute is attached to its "
          "containing structure)",
          "  allocate(gq%v(n))\n  gq%v = 3*a\n  @ENTER to(gq%v)\n"
          + ploop("b(i) = gq%v(i) + 1", "from(b) tofrom(host_flag)")
          + "  @EXIT delete(gq%v)\n",
          ref="3*i + 1", modules=module("""\
  type rec_t
    integer, allocatable :: v(:)
  end type rec_t
  type(rec_t) :: gq
  @DECLVAR(gq)""", "wtypes"), uses="  use wtypes\n",
          mutant=(("b(i) = gq%v(i) + 1", "b(i) = gq%v(i)"),),
          spec_acc="OpenACC 3.4 \u00a72.13 (declare create in a module) and "
                   "\u00a72.7.1 (attach of a member of a declared aggregate)"),
    FSpec("tile-inner-loops", "form.acc.tile_inner_loops",
          "a tile(*,*) loop whose innermost tiled loop body holds other loops",
          ACC_TILE, """  !$acc parallel loop tile(*,*) copyin(a) copy(c2) copy(host_flag)
  do j = 1, 4
    do i = 1, n
      do k = 1, 2
        c2(j, i) = c2(j, i) + a(i)
      end do
      do k = 1, j
        c2(j, i) = c2(j, i) + 1
      end do
      if (i == 1 .and. j == 1) @HOSTFLAG
    end do
  end do
""", models=("acc",), decls="  integer :: c2(4, n), j, k\n",
          init="  c2 = 0\n", check="all([((c2(j, i) == 2*a(i) + j, j = 1, 4), i = 1, n)])",
          mutant=(("        c2(j, i) = c2(j, i) + 1\n", ""),)),
]

F_SPECS = F_BASE + F_DIRECTIVES + F_PAIRS + F_APPS

# --- C ------------------------------------------------------------------------------------

C_HEAD = "#include <stdio.h>\n#include <stdbool.h>\n#include <omp.h>\n"
CPL = "map(to: a) map(from: b) map(tofrom: host_flag)"
CHF = "host_flag = omp_is_initial_device();"


def _pragma(text: str, indent: str = "  ") -> str:
    """A #pragma line continued with backslashes past 88 columns."""
    words = text.split(" ")
    lines, cur = [], indent + words[0]
    for w in words[1:]:
        if len(cur) + 1 + len(w) > 88:
            lines.append(cur + " \\")
            cur = indent + "    " + w
        else:
            cur += " " + w
    lines.append(cur)
    return "\n".join(lines)


def _ind(body: str, n: int) -> str:
    return "\n".join((" " * n + ln) if ln.strip() else ln
                     for ln in body.strip("\n").splitlines())


def cploop(body: str, clauses: str = CPL, flag: bool = True) -> str:
    hf = f"\n    if (i == 0) {CHF}" if flag else ""
    return (_pragma("#pragma omp target teams distribute parallel for "
                    + clauses) + "\n  for (int i = 0; i < n; i++) {\n"
            + _ind(body, 4) + hf + "\n  }\n")


def cregion(body: str, clauses: str = CPL) -> str:
    return (_pragma("#pragma omp target " + clauses) + "\n  {\n    " + CHF
            + "\n" + _ind(body, 4) + "\n  }\n")


def cprog(kernel: str, ref: str | None = None, helpers: str = "",
          decls: str = "", init: str = "", check: str = "",
          includes: str = "") -> str:
    if ref is None:  # a program checked by `check` alone leaves b at 0
        ref = "0" if check else "2 * (i + 1) + 1"
    chk = ("  bool ok = true;\n  for (int i = 0; i < n; i++)\n"
           "    ok = ok && (b[i] == ref[i]);\n")
    if check:
        chk += f"  ok = ok && ({check});\n"
    return (C_HEAD + includes + "\nenum { n = 64 };\n\n"
            + (helpers.strip("\n") + "\n\n" if helpers.strip() else "")
            + "int main(void) {\n  int a[n], b[n], ref[n];\n"
            "  int host_flag = 1;\n" + decls
            + "  for (int i = 0; i < n; i++) {\n    a[i] = i + 1;\n"
            f"    b[i] = 0;\n    ref[i] = {ref};\n  }}\n" + init + kernel + chk
            + '  printf("RESULT ran_on_host=%d check=%s\\n", host_flag, '
            'ok ? "pass" : "fail");\n  return 0;\n}\n')


CW2 = ("b[i] = 2 * a[i] + 1;", "b[i] = 2 * a[i];")
_C_TW = """\
#pragma omp declare target
int tw(int x) { return 2 * x + 1; }
#pragma omp end declare target"""
_C_PRIV = "  int t[4];\n"


def C(slug, atom, feature, spec, body, **kw):
    return CSpec(slug, atom, feature, spec, body, **kw)


C_BASE = [
    C("pointer-component", "base.device.pointer_component",
      "a struct with a pointer member mapped with its pointee (map(r, "
      "r.p[0:n]): the device pointer is attached) and read on the device",
      "OpenMP 5.2 §5.8.3, p.151: a list item with a base pointer is "
      "attached to the corresponding pointer",
      cprog(cploop("b[i] = r.p[i] + 1;", "map(to: r, r.p[0:n]) map(from: b) "
                   "map(tofrom: host_flag)"),
            ref="3 * (i + 1) + 1", helpers="struct rec { int m; int *p; };",
            decls="  int store[n];\n  struct rec r;\n",
            init="  for (int i = 0; i < n; i++) store[i] = 3 * (i + 1);\n"
                 "  r.m = n;\n  r.p = store;\n"),
      mutant=(("b[i] = r.p[i] + 1;", "b[i] = 1;"),)),
    C("derived-type-array", "base.device.derived_array",
      "an array of structs mapped and its members read on the device",
      OMP_C11, cprog(cploop("b[i] = ps[i].x + 2 * ps[i].y;",
                            "map(to: ps) map(from: b) map(tofrom: host_flag)"),
                     ref="5 * (i + 1)", helpers="struct pt { int x; int y; };",
                     decls="  struct pt ps[n];\n",
                     init="  for (int i = 0; i < n; i++) {\n    ps[i].x = i + 1;\n"
                          "    ps[i].y = 2 * (i + 1);\n  }\n"),
      mutant=(("b[i] = ps[i].x + 2 * ps[i].y;", "b[i] = ps[i].x;"),)),
    C("derived-scalar", "base.device.derived_scalar",
      "a struct scalar mapped and its members read on the device", OMP_C11,
      cprog(cploop("b[i] = s.k * a[i] + s.m;",
                   "map(to: a, s) map(from: b) map(tofrom: host_flag)"),
            ref="3 * (i + 1) + 1", helpers="struct par { int k; int m; };",
            decls="  struct par s = {3, 1};\n"),
      mutant=(("b[i] = s.k * a[i] + s.m;", "b[i] = s.k * a[i];"),)),
    C("nested-derived-type", "base.device.nested_type",
      "a struct with a struct member and an array member, mapped and read "
      "on the device", OMP_C11,
      cprog(cploop("b[i] = o.inner.k * a[i] + o.w[(i + 1) % 4];",
                   "map(to: a, o) map(from: b) map(tofrom: host_flag)"),
            ref="3 * (i + 1) + (i + 1) % 4 + 1",
            helpers="struct in_s { int k; };\n"
                    "struct out_s { struct in_s inner; int w[4]; };",
            decls="  struct out_s o = {{3}, {1, 2, 3, 4}};\n"),
      mutant=((" + o.w[(i + 1) % 4];", ";"),)),
    C("derived-assignment", "base.device.derived_assign",
      "struct assignment to a local struct in device code", OMP_C11,
      cprog(cploop("struct par t = s;\nt.m = t.m + a[i];\nb[i] = t.k * a[i] + t.m;",
                   "map(to: a, s) map(from: b) map(tofrom: host_flag)"),
            ref="4 * (i + 1) + 1", helpers="struct par { int k; int m; };",
            decls="  struct par s = {3, 1};\n"),
      mutant=(("struct par t = s;", "struct par t = {0, 0};"),)),
    C("union", "base.device.union",
      "a mapped array of unions written through one member and read "
      "through another (little-endian byte order on host and devices)",
      OMP_C11 + "; C11 §6.5.2.3 (reading another union member "
      "reinterprets the bytes)",
      cprog(cploop("us[i].i = 2 * a[i] + 1;\nb[i] = us[i].c[0];",
                   "map(to: a) map(tofrom: us) map(from: b) "
                   "map(tofrom: host_flag)"),
            helpers="union u { int i; unsigned char c[4]; };",
            decls="  union u us[n];\n",
            init="  for (int i = 0; i < n; i++) us[i].i = 0;\n"),
      mutant=(("us[i].i = 2 * a[i] + 1;", "us[i].i = 2 * a[i];"),)),
    C("save-local-routine", "base.device.save_local",
      "a static local variable of a declare target function, updated by "
      "sequential calls in one target region", OMP_STATIC_IN_ROUTINE,
      cprog(cregion("b[0] = bump();\nb[1] = bump();\nb[2] = bump();",
                    "map(tofrom: b, host_flag)"),
            ref="i < 3 ? i + 1 : 0", helpers="""\
#pragma omp declare target
int bump(void) {
  static int cnt = 0;
  cnt = cnt + 1;
  return cnt;
}
#pragma omp end declare target"""),
      mutant=(("cnt = cnt + 1;", "cnt = 1;"),)),
    C("vla-local", "base.device.vla",
      "a variable-length array declared in a target region", OMP_C11,
      cprog(cregion("int t[m];\nfor (int k = 0; k < m; k++) t[k] = 2 * a[k] + 1;\n"
                    "for (int k = 0; k < m; k++) b[k] = t[k];",
                    "map(to: a, m) map(from: b) map(tofrom: host_flag)"),
            decls="  int m = n;\n"),
      mutant=(("t[k] = 2 * a[k] + 1;", "t[k] = 2 * a[k];"),)),
    C("vla-mapped", "base.device.vla_mapped",
      "a host variable-length array mapped and written in a target loop",
      OMP_C11,
      cprog(cploop("v[i] = 2 * a[i] + 1;",
                   "map(to: a) map(from: v) map(tofrom: host_flag)")
            + "  for (int i = 0; i < n; i++) b[i] = v[i];\n",
            decls="  int m = n;\n  int v[m];\n"),
      mutant=(("v[i] = 2 * a[i] + 1;", "v[i] = 2 * a[i];"),)),
    C("print-in-device", "base.device.print",
      "printf executed once in device code (the device C library is "
      "implementation defined: a rejection is no conformance failure)",
      OMP_C11,
      cprog(cploop('if (i == n - 1) printf("device print\\n");\n'
                   "b[i] = 2 * a[i] + 1;")),
      mutant=(CW2,)),
    C("complex-arith", "base.device.complex",
      "double _Complex arithmetic in device code", OMP_C11,
      cprog(cploop("z[i] = ((double)a[i] + 1.0 * I) * I;",
                   "map(to: a) map(from: z) map(tofrom: host_flag)"),
            includes="#include <complex.h>\n",
            decls="  double _Complex z[n];\n",
            init="  for (int i = 0; i < n; i++) z[i] = 0;\n",
            check="cz(z)",
            helpers="#include <complex.h>\nstatic bool cz(double _Complex *z) {\n"
                    "  for (int i = 0; i < n; i++)\n"
                    "    if (creal(z[i]) != -1.0 || cimag(z[i]) != i + 1.0) "
                    "return false;\n  return true;\n}"),
      mutant=(("z[i] = ((double)a[i] + 1.0 * I) * I;",
               "z[i] = ((double)a[i] + 1.0 * I);"),)),
    C("long-double", "base.device.long_double",
      "long double arithmetic on a mapped long double array (the "
      "representation of long double is implementation defined; a device "
      "that has no wider type than double may reject it)", OMP_C11,
      cprog(cploop("ld[i] = (long double)a[i] * 2.0L + 1.0L;",
                   "map(to: a) map(from: ld) map(tofrom: host_flag)")
            + "  for (int i = 0; i < n; i++) b[i] = (int)ld[i];\n",
            decls="  long double ld[n];\n",
            init="  for (int i = 0; i < n; i++) ld[i] = 0.0L;\n"),
      mutant=(("ld[i] = (long double)a[i] * 2.0L + 1.0L;",
               "ld[i] = (long double)a[i] * 2.0L;"),)),
    C("function-pointer", "base.device.function_pointer",
      "a pointer to a declare target function taken and called in device "
      "code", OMP_FPTR,
      cprog(cploop("int (*f)(int) = (i % 2) ? tw : th;\nb[i] = f(a[i]);"),
            ref="(i % 2) ? 2 * (i + 1) + 1 : 3 * (i + 1)", helpers="""\
#pragma omp declare target
int tw(int x) { return 2 * x + 1; }
int th(int x) { return 3 * x; }
#pragma omp end declare target"""),
      mutant=(("int th(int x) { return 3 * x; }",
               "int th(int x) { return 2 * x + 1; }"),)),
    C("private-array", "base.device.private_array",
      "a private local array written at constant indices in a target loop",
      "OpenMP 5.2 §5.4.3, p.112 (private clause; an array is a list item)",
      cprog(cploop("t[0] = a[i];\nt[1] = 1;\nt[2] = a[i];\nt[3] = 0;\n"
                   "b[i] = t[0] + t[1] + t[2] + t[3];", CPL + " private(t)"),
            decls=_C_PRIV),
      mutant=(("t[1] = 1;", "t[1] = 0;"),)),
    C("private-array-dynamic-index", "base.device.private_array_dynamic",
      "a private local array written at a run-time index in a target loop",
      "OpenMP 5.2 §5.4.3, p.112 (private clause; an array is a list item)",
      cprog(cploop("for (int k = 0; k < 4; k++) t[k] = 0;\nt[a[i] % 4] = a[i];\n"
                   "b[i] = t[0] + t[1] + t[2] + t[3] + t[a[i] % 4];",
                   CPL + " private(t)"), ref="2 * (i + 1)", decls=_C_PRIV),
      mutant=(("t[a[i] % 4] = a[i];", "t[0] = 0;"),)),
    C("intrinsic-transcendental", "base.device.intrinsic_math",
      "exp, log, sin and cos of doubles in device code (checked to 1e-9)",
      OMP_C11,
      cprog(cploop("double v = (double)a[i];\nx[i] = exp(log(v)) + sin(v) * sin(v)"
                   " + cos(v) * cos(v);",
                   "map(to: a) map(from: x) map(tofrom: host_flag)")
            + "  for (int i = 0; i < n; i++)\n"
              "    b[i] = fabs(x[i] - (a[i] + 1.0)) < 1e-9 ? ref[i] : -1;\n",
            includes="#include <math.h>\n", decls="  double x[n];\n"),
      mutant=((" + cos(v) * cos(v);", ";"),)),
    C("select-case", "base.device.select_case",
      "a switch statement in device code", OMP_C11,
      cprog(cploop("switch (a[i] % 3) {\ncase 0:\n  b[i] = a[i];\n  break;\n"
                   "case 1:\n  b[i] = 2 * a[i];\n  break;\ndefault:\n"
                   "  b[i] = 3 * a[i];\n}"),
            ref="((i + 1) % 3 + 1) * (i + 1)"),
      mutant=(("  b[i] = 3 * a[i];", "  b[i] = a[i];"),)),
    C("recursive-routine", "base.device.recursion",
      "a recursive declare target function", OMP_C11,
      cprog(cploop("b[i] = sumto(a[i] % 8);"),
            ref="((i + 1) % 8) * ((i + 1) % 8 + 1) / 2", helpers="""\
#pragma omp declare target
int sumto(int k) { return k <= 0 ? 0 : k + sumto(k - 1); }
#pragma omp end declare target"""),
      mutant=(("k + sumto(k - 1)", "k"),)),
    C("implicit-routine", "base.device.implicit_routine",
      "a function without a declare target directive called in a target "
      "loop (implicitly a device function)", OMP_IMPLICIT,
      cprog(cploop("b[i] = tw(a[i]);"),
            helpers="int tw(int x) { return 2 * x + 1; }"),
      mutant=(("return 2 * x + 1;", "return 2 * x;"),)),
    C("routine-call", "base.device.routine_call",
      "a declare target function called in a target loop", OMP_IMPLICIT,
      cprog(cploop("b[i] = tw(a[i]);"), helpers=_C_TW),
      mutant=(("return 2 * x + 1;", "return 2 * x;"),)),
    C("allocate-in-device", "base.device.allocate",
      "malloc and free in a target region (the device C library is "
      "implementation defined: a rejection is no conformance failure)",
      OMP_C11,
      cprog(cregion("int *w = (int *)malloc(n * sizeof(int));\n"
                    "for (int k = 0; k < n; k++) w[k] = 2 * a[k] + 1;\n"
                    "for (int k = 0; k < n; k++) b[k] = w[k];\nfree(w);"),
            includes="#include <stdlib.h>\n"),
      mutant=(("w[k] = 2 * a[k] + 1;", "w[k] = 2 * a[k];"),)),
    C("stop-unreached", "base.device.stop",
      "a call to abort() in device code that is not executed",
      "OpenMP 5.2 §4.3, p.75: a structured block may contain calls to "
      "exit(), _Exit(), quick_exit() or abort()",
      cprog(cploop("if (a[i] < 0) abort();\nb[i] = 2 * a[i] + 1;"),
            includes="#include <stdlib.h>\n"),
      mutant=(CW2,)),
    C("bitfield", "base.device.bitfield",
      "a mapped array of structs with bit-field members read on the device",
      OMP_C11,
      cprog(cploop("b[i] = bf[i].lo + 16 * bf[i].hi;",
                   "map(to: bf) map(from: b) map(tofrom: host_flag)"),
            ref="(i + 1) % 256",
            helpers="struct bits { unsigned lo : 4; unsigned hi : 4; };",
            decls="  struct bits bf[n];\n",
            init="  for (int i = 0; i < n; i++) {\n    bf[i].lo = (i + 1) % 16;\n"
                 "    bf[i].hi = ((i + 1) / 16) % 16;\n  }\n"),
      mutant=((" + 16 * bf[i].hi;", ";"),)),
    C("struct-by-value", "base.device.struct_by_value",
      "a struct passed by value to and returned from a declare target "
      "function", OMP_C11,
      cprog(cploop("struct par p = {a[i], 1};\nb[i] = sc(p).k;"),
            helpers="""\
struct par { int k; int m; };
#pragma omp declare target
struct par sc(struct par p) {
  struct par q = {2 * p.k + p.m, 0};
  return q;
}
#pragma omp end declare target"""),
      mutant=(("{2 * p.k + p.m, 0}", "{2 * p.k, 0}"),)),
    C("character-local", "base.device.character",
      "a local char array filled and searched in device code", OMP_C11,
      cprog(cploop("char s[9] = \"abcdefgh\";\nint pos = 0;\n"
                   "for (int k = 0; k < 8; k++)\n  if (s[k] == s[i % 8] && pos == 0) "
                   "pos = k + 1;\nb[i] = pos + 8;"),
            ref="i % 8 + 9"),
      mutant=(("b[i] = pos + 8;", "b[i] = pos;"),)),
    C("int8-loop", "base.device.int8_index",
      "a long long loop variable of the target loop", OMP_C11,
      cprog(_pragma("#pragma omp target teams distribute parallel for " + CPL)
            + "\n  for (long long j = 0; j < n; j++) {\n"
            "    b[j] = 2 * a[j] + 1;\n    if (j == 0) " + CHF + "\n  }\n"),
      mutant=(("b[j] = 2 * a[j] + 1;", "b[j] = 2 * a[j];"),)),
    C("parallel-in-seq-loop", "base.device.parallel_in_seq_loop",
      "a parallel for nested in a sequential loop of a target region",
      "OpenMP 5.2 §13.8 (target) and §10.1 (parallel)",
      cprog(_pragma("#pragma omp target map(to: a) map(tofrom: b, host_flag)")
            + "\n  {\n    " + CHF + "\n    for (int k = 0; k < 3; k++) {\n"
            "      #pragma omp parallel for\n      for (int i = 0; i < n; i++)\n"
            "        b[i] = b[i] + a[i];\n    }\n  }\n", ref="3 * (i + 1)"),
      mutant=(("b[i] = b[i] + a[i];", "b[i] = a[i];"),)),
]

_C_SUM = "s == n * (n + 1) / 2"


def _c_crit(name="", hint=""):
    return (_pragma("#pragma omp target parallel for map(to: a) "
                    "map(tofrom: s, host_flag)") + "\n"
            "  for (int i = 0; i < n; i++) {\n"
            f"    #pragma omp critical{name}{hint}\n"
            "    {\n      int t = s;\n      s = t + a[i];\n    }\n"
            f"    if (i == 0) {CHF}\n  }}\n")


C_DIRECTIVES = [
    C("critical", "omp.directive.critical",
      "an unnamed critical construct in a target parallel loop",
      OMP_CRITICAL, cprog(_c_crit(), decls="  int s = 0;\n", check=_C_SUM),
      mutant_device="a race: without the construct the updates race",
          mutant=(("    #pragma omp critical\n", ""),)),
    C("critical-named", "form.omp.critical_named",
      "a named critical construct in a target parallel loop", OMP_CRITICAL,
      cprog(_c_crit("(wsum)"), decls="  int s = 0;\n", check=_C_SUM),
      mutant_device="a race: without the construct the updates race",
          mutant=(("    #pragma omp critical(wsum)\n", ""),)),
    C("critical-hint", "omp.clause.hint",
      "a named critical construct with a hint clause in a target parallel "
      "loop", OMP_CRITICAL + "; §15.1 (hint clause)",
      cprog(_c_crit("(wsum)", " hint(omp_sync_hint_contended)"),
            decls="  int s = 0;\n", check=_C_SUM),
      mutant_device="a race: without the construct the updates race",
          mutant=(("    #pragma omp critical(wsum) hint(omp_sync_hint_contended)\n",
               ""),)),
    C("sections", "omp.directive.sections",
      "a sections construct with two sections in a target parallel region",
      OMP_SECTIONS,
      cprog(_pragma("#pragma omp target parallel map(to: a) "
                    "map(tofrom: b, host_flag)") + """
  {
    #pragma omp sections
    {
      #pragma omp section
      {
        for (int i = 0; i < n / 2; i++) b[i] = 2 * a[i] + 1;
        host_flag = omp_is_initial_device();
      }
      #pragma omp section
      {
        for (int i = n / 2; i < n; i++) b[i] = a[i] + a[i] + 1;
      }
    }
  }
"""), mutant=(("b[i] = a[i] + a[i] + 1;", "b[i] = 0;"),)),
    C("parallel-sections", "omp.directive.parallel_sections",
      "a parallel sections construct nested in a target region",
      OMP_SECTIONS,
      cprog(_pragma("#pragma omp target map(to: a) map(tofrom: b, host_flag)")
            + """
  {
    host_flag = omp_is_initial_device();
    #pragma omp parallel sections
    {
      #pragma omp section
      {
        for (int i = 0; i < n / 2; i++) b[i] = 2 * a[i] + 1;
      }
      #pragma omp section
      {
        for (int i = n / 2; i < n; i++) b[i] = a[i] + a[i] + 1;
      }
    }
  }
"""), mutant=(("b[i] = a[i] + a[i] + 1;", "b[i] = 0;"),)),
    C("single", "omp.directive.single",
      "a single construct in a target parallel region",
      "OpenMP 5.2 §11.1, p.221 (single construct)",
      cprog("  #pragma omp target parallel map(tofrom: s, host_flag)\n  {\n"
            "    #pragma omp single\n    {\n      s = s + 1;\n      " + CHF
            + "\n    }\n  }\n", decls="  int s = 0;\n", check="s == 1"),
      mutant=(("s = s + 1;", "s = s + 2;"),)),
    C("masked", "omp.directive.masked",
      "a masked construct in a target parallel region",
      "OpenMP 5.2 §10.5, p.214 (masked construct)",
      cprog("  #pragma omp target parallel map(tofrom: s, host_flag)\n  {\n"
            "    #pragma omp masked\n    {\n      s = s + 1;\n      " + CHF
            + "\n    }\n  }\n", decls="  int s = 0;\n", check="s == 1"),
      mutant=(("s = s + 1;", "s = s + 2;"),)),
    C("barrier", "omp.directive.barrier",
      "a barrier between a write by every thread and a read by the primary "
      "thread in a target parallel region",
      "OpenMP 5.2 §15.3.1, p.317 (barrier construct)",
      cprog(_pragma("#pragma omp target parallel num_threads(4) "
                    "map(tofrom: c, okf, host_flag)") + """
  {
    int tid = omp_get_thread_num();
    int nt = omp_get_num_threads();
    c[tid] = tid + 1;
    #pragma omp barrier
    if (tid == 0) {
      okf = 1;
      for (int k = 0; k < nt; k++)
        if (c[k] != k + 1) okf = 0;
      host_flag = omp_is_initial_device();
    }
  }
""", decls="  int c[4] = {0, 0, 0, 0};\n  int okf = 0;\n", check="okf == 1"),
      mutant=(("        if (c[k] != k + 1) okf = 0;", "        okf = 0;"),)),
    C("atomic", "omp.directive.atomic",
      "an atomic construct (update form, no clause) in a target loop",
      OMP_ATOMIC,
      cprog(cploop("#pragma omp atomic\ns = s + a[i];",
                   "map(to: a) map(tofrom: s, host_flag)"),
            decls="  int s = 0;\n", check=_C_SUM),
      mutant=(("s = s + a[i];", "s = s + 1;"),)),
    C("atomic-update", "omp.clause.update",
      "an atomic update construct in a target loop", OMP_ATOMIC,
      cprog(cploop("#pragma omp atomic update\ns = s + a[i];",
                   "map(to: a) map(tofrom: s, host_flag)"),
            decls="  int s = 0;\n", check=_C_SUM),
      mutant=(("s = s + a[i];", "s = s + 1;"),)),
    C("atomic-capture", "omp.clause.capture",
      "an atomic capture construct (each iteration takes a ticket) in a "
      "target loop", OMP_ATOMIC,
      cprog(cploop("int t;\n#pragma omp atomic capture\nt = s++;\nb[i] = t;",
                   "map(tofrom: s, b, host_flag)"),
            ref="0", decls="  int s = 0;\n",
            check="s == n && sumv(b) == n * (n - 1) / 2",
            helpers="static int sumv(int *v) {\n  int r = 0;\n"
                    "  for (int i = 0; i < n; i++) r += v[i];\n  return r;\n}")
      .replace("    ok = ok && (b[i] == ref[i]);\n", "    ok = ok && true;\n"),
      mutant=(("t = s++;", "t = s += 2;"),)),
    C("atomic-write", "omp.clause.write",
      "an atomic write construct in a target loop", OMP_ATOMIC,
      cprog(cploop("b[i] = 2 * a[i] + 1;\nif (i == n - 1) {\n"
                   "  #pragma omp atomic write\n  w = 7;\n}",
                   "map(to: a) map(from: b) map(tofrom: w, host_flag)"),
            ref="2 * (i + 1) + 1", decls="  int w = 0;\n", check="w == 7"),
      mutant=(("  w = 7;", "  w = 6;"),)),
    C("atomic-read", "omp.clause.read",
      "an atomic read construct in a target loop", OMP_ATOMIC,
      cprog(cploop("int t;\n#pragma omp atomic read\nt = w;\nb[i] = a[i] + t;",
                   "map(to: a, w) map(from: b) map(tofrom: host_flag)"),
            ref="i + 1 + 7", decls="  int w = 7;\n"),
      mutant=(("b[i] = a[i] + t;", "b[i] = a[i];"),)),
    C("ordered", "omp.directive.ordered",
      "an ordered region in a target parallel for with the ordered clause",
      "OpenMP 5.2 §15.10.1, p.338 (ordered construct)",
      cprog(_pragma("#pragma omp target parallel for ordered map(to: a) "
                    "map(tofrom: b, cnt, host_flag)") + """
  for (int i = 0; i < n; i++) {
    #pragma omp ordered
    {
      b[cnt] = a[i];
      cnt = cnt + 1;
    }
    if (i == 0) host_flag = omp_is_initial_device();
  }
""", ref="i + 1", decls="  int cnt = 0;\n", check="cnt == n"),
      mutant=(("b[cnt] = a[i];", "b[cnt] = a[n - 1 - i];"),)),
    C("task", "omp.directive.task",
      "a task and a taskwait in a target region",
      "OpenMP 5.2 §12.5, p.247 (task construct)",
      cprog("  #pragma omp target map(tofrom: s, host_flag)\n  {\n    " + CHF
            + "\n    #pragma omp task shared(s)\n    s = s + 1;\n"
            "    #pragma omp taskwait\n  }\n", decls="  int s = 0;\n",
            check="s == 1"),
      mutant=(("s = s + 1;", "s = s + 2;"),)),
    C("declare-mapper", "omp.directive.declare_mapper",
      "a default declare mapper of a struct with a pointer member, applied "
      "by map(to: r) in a target loop", OMP_MAPPER,
      cprog(cploop("b[i] = r.p[i] + 1;", "map(to: r) map(from: b) "
                   "map(tofrom: host_flag)"),
            ref="3 * (i + 1) + 1", helpers="struct rec { int m; int *p; };\n"
            "#pragma omp declare mapper(struct rec x) map(x, x.p[0:x.m])",
            decls="  int store[n];\n  struct rec r;\n",
            init="  for (int i = 0; i < n; i++) store[i] = 3 * (i + 1);\n"
                 "  r.m = n;\n  r.p = store;\n"),
      mutant_device="copy semantics: without the mapper the pointee is not "
                    "mapped (map(to: r) copies the host address); under "
                    "unified memory the host address still works",
      mutant=(("#pragma omp declare mapper(struct rec x) map(x, x.p[0:x.m])\n",
               ""),)),
]

_C_A2 = ("  int a2[n][4], c2[n][4];\n",
         "  for (int i = 0; i < n; i++)\n    for (int j = 0; j < 4; j++) {\n"
         "      a2[i][j] = (i + 1) * (j + 1);\n      c2[i][j] = 0;\n    }\n")


def c2loop(body: str, clauses: str) -> str:
    return (_pragma("#pragma omp target teams distribute parallel for "
                    "collapse(2) " + clauses) + "\n"
            "  for (int i = 0; i < n; i++)\n    for (int j = 0; j < 4; j++) {\n"
            + _ind(body, 6) + f"\n      if (i == 0 && j == 0) {CHF}\n    }}\n")


_C2_CHECK = ("c2ok(a2, c2)", "static bool c2ok(int a2[n][4], int c2[n][4]) {\n"
             "  for (int i = 0; i < n; i++)\n    for (int j = 0; j < 4; j++)\n"
             "      if (c2[i][j] != 2 * a2[i][j] + 1) return false;\n"
             "  return true;\n}")


def CP(slug, a, b, feature, body, **kw):
    return CSpec(slug, f"pair.{a}+{b}", feature, kw.pop(
        "spec", "the parts' own programs"), body, parts=(a, b), **kw)


C_PAIRS = [
    CP("collapse-private-array", "omp.clause.collapse",
       "base.device.private_array", "a private array in a collapse(2) target "
       "loop",
       cprog(c2loop("t[0] = a2[i][j];\nt[1] = 1;\nt[2] = a2[i][j];\nt[3] = 0;\n"
                    "c2[i][j] = t[0] + t[1] + t[2] + t[3];",
                    "map(to: a2) map(from: c2) map(tofrom: host_flag) private(t)"),
             decls=_C_A2[0] + _C_PRIV, init=_C_A2[1], check=_C2_CHECK[0],
             helpers=_C2_CHECK[1]),
       mutant=(("t[1] = 1;", "t[1] = 0;"),)),
    CP("collapse-reduction", "omp.clause.collapse", "omp.clause.reduction",
       "a sum reduction over a collapse(2) target loop",
       cprog(c2loop("s += a2[i][j];", "map(to: a2) map(tofrom: host_flag) "
                    "reduction(+: s)"),
             decls=_C_A2[0] + "  int s = 0;\n", init=_C_A2[1],
             check="s == 10 * n * (n + 1) / 2"),
       mutant=(("s += a2[i][j];", "s += 1;"),)),
    CP("collapse-routine-call", "omp.clause.collapse",
       "base.device.routine_call", "a declare target function called in a "
       "collapse(2) target loop",
       cprog(c2loop("c2[i][j] = tw(a2[i][j]);",
                    "map(to: a2) map(from: c2) map(tofrom: host_flag)"),
             decls=_C_A2[0], init=_C_A2[1], check=_C2_CHECK[0],
             helpers=_C_TW + "\n" + _C2_CHECK[1]),
       mutant=(("return 2 * x + 1;", "return 2 * x;"),)),
    CP("reduction-routine-call", "omp.clause.reduction",
       "base.device.routine_call", "a declare target function called in a "
       "sum reduction loop",
       cprog(cploop("s += tw(a[i]);", "map(to: a) map(tofrom: host_flag) "
                    "reduction(+: s)"), decls="  int s = 0;\n",
             check="s == n * (n + 1) + n", helpers=_C_TW),
       mutant=(("return 2 * x + 1;", "return 2 * x;"),)),
    CP("update-pointer-component", "omp.directive.target_update",
       "base.device.pointer_component",
       "a struct and its pointee kept on the device by enter data, the "
       "pointee updated from the host between two target loops",
       cprog("  #pragma omp target enter data map(to: r, r.p[0:n])\n"
             + cploop("b[i] = r.p[i] + 1;", "map(from: b) map(tofrom: host_flag)")
             + "  for (int i = 0; i < n; i++) store[i] = 5 * (i + 1);\n"
             "  #pragma omp target update to(r.p[0:n])\n"
             + cploop("b[i] = b[i] + r.p[i];", "map(tofrom: b)", flag=False)
             + "  #pragma omp target exit data map(delete: r.p[0:n], r)\n",
             ref="8 * (i + 1) + 1", helpers="struct rec { int m; int *p; };",
             decls="  int store[n];\n  struct rec r;\n",
             init="  for (int i = 0; i < n; i++) store[i] = 3 * (i + 1);\n"
                  "  r.m = n;\n  r.p = store;\n"),
       mutant_device="copy semantics: without the update the device keeps the old values (separate memory only)",
          mutant=(("  #pragma omp target update to(r.p[0:n])\n", ""),)),
    CP("atomic-reduction", "omp.directive.atomic", "omp.clause.reduction",
       "an atomic update of one variable and a sum reduction of another in "
       "one target loop",
       cprog(cploop("s += a[i];\n#pragma omp atomic\nw = w + 1;",
                    "map(to: a) map(tofrom: w, host_flag) reduction(+: s)"),
             decls="  int s = 0, w = 0;\n", check=_C_SUM + " && w == n"),
       mutant=(("w = w + 1;", "w = w + 2;"),)),
    CP("critical-reduction", "omp.directive.critical", "omp.clause.reduction",
       "a critical update of one variable and a sum reduction of another in "
       "one target parallel loop",
       cprog(_pragma("#pragma omp target parallel for map(to: a) "
                     "map(tofrom: w, host_flag) reduction(+: s)") + """
  for (int i = 0; i < n; i++) {
    s += a[i];
    #pragma omp critical
    w = w + 1;
    if (i == 0) host_flag = omp_is_initial_device();
  }
""", decls="  int s = 0, w = 0;\n", check=_C_SUM + " && w == n"),
       mutant=(("w = w + 1;", "w = w + 2;"),)),
    CP("private-array-routine-arg", "base.device.private_array",
       "base.device.routine_call",
       "a private array passed to a declare target function",
       cprog(cploop("fill(t, a[i]);\nb[i] = t[0] + t[1] + t[2] + t[3];",
                    CPL + " private(t)"), ref="2 * (i + 1) + 1",
             decls=_C_PRIV, helpers="""\
#pragma omp declare target
void fill(int *x, int v) {
  for (int k = 0; k < 4; k++) x[k] = 0;
  x[0] = v;
  x[1] = v + 1;
}
#pragma omp end declare target"""),
       mutant=(("x[1] = v + 1;", "x[1] = v;"),)),
    CP("mapper-reduction", "omp.directive.declare_mapper",
       "omp.clause.reduction",
       "a sum reduction over the pointee of a struct mapped through its "
       "default mapper",
       cprog(cploop("s += r.p[i];", "map(to: r) map(tofrom: host_flag) "
                    "reduction(+: s)"),
             helpers="struct rec { int m; int *p; };\n"
             "#pragma omp declare mapper(struct rec x) map(x, x.p[0:x.m])",
             decls="  int store[n];\n  struct rec r;\n  int s = 0;\n",
             init="  for (int i = 0; i < n; i++) store[i] = 3 * (i + 1);\n"
                  "  r.m = n;\n  r.p = store;\n",
             check="s == 3 * n * (n + 1) / 2"),
       mutant_device="copy semantics: without the mapper the pointee is not "
                     "mapped; under unified memory the host address still "
                     "works",
       mutant=(("#pragma omp declare mapper(struct rec x) map(x, x.p[0:x.m])\n",
                ""),)),
    CP("mapper-iterator", "omp.directive.declare_mapper",
       "omp.clause.map.iterator",
       "a default declare mapper whose map clause has an iterator over the "
       "pointer members of a struct",
       cprog(cploop("b[i] = r.p[0][i] + r.p[1][i];", "map(to: r) map(from: b) "
                    "map(tofrom: host_flag)"),
             ref="5 * (i + 1)", helpers="struct rec2 { int m; int *p[2]; };\n"
             "#pragma omp declare mapper(struct rec2 x) map(x) "
             "map(iterator(k = 0:2), to: x.p[k][0:x.m])",
             decls="  int s0[n], s1[n];\n  struct rec2 r;\n",
             init="  for (int i = 0; i < n; i++) {\n    s0[i] = 2 * (i + 1);\n"
                  "    s1[i] = 3 * (i + 1);\n  }\n  r.m = n;\n  r.p[0] = s0;\n"
                  "  r.p[1] = s1;\n"),
       spec="OpenMP 5.2 \u00a75.8.8 (declare mapper) and \u00a73.2.6 "
            "(iterator modifier)",
       mutant_device="copy semantics: without the mapper the pointees are "
                     "not mapped; under unified memory the host addresses "
                     "still work",
       mutant=(("#pragma omp declare mapper(struct rec2 x) map(x) "
                "map(iterator(k = 0:2), to: x.p[k][0:x.m])\n", ""),)),
    CP("allocate-const-firstprivate", "omp.clause.allocate",
       "omp.clause.firstprivate",
       "a firstprivate scalar allocated with omp_const_mem_alloc "
       "(uses_allocators) on a target loop",
       cprog(cploop("b[i] = a[i] + x;", CPL + " firstprivate(x) "
                    "allocate(omp_const_mem_alloc: x) "
                    "uses_allocators(omp_const_mem_alloc)"),
             ref="i + 1 + 5", decls="  int x = 5;\n"),
       mutant=(("b[i] = a[i] + x;", "b[i] = a[i];"),)),
    CP("lastprivate-parallel-in-seq-loop", "omp.clause.lastprivate",
       "base.device.parallel_in_seq_loop",
       "lastprivate on a parallel for nested in a sequential loop of a "
       "target region",
       cprog(_pragma("#pragma omp target map(to: a) map(tofrom: b, host_flag)")
             + """
  {
    host_flag = omp_is_initial_device();
    for (int k = 0; k < 3; k++) {
      int last = 0;
      #pragma omp parallel for lastprivate(last)
      for (int i = 0; i < n; i++)
        last = a[i] + k;
      b[k] = last;
    }
  }
""", ref="i < 3 ? n + i : 0"),
       mutant=(("last = a[i] + k;", "last = a[i];"),)),
    CP("reduction-parallel-in-seq-loop", "omp.clause.reduction",
       "base.device.parallel_in_seq_loop",
       "a reduction on a parallel for nested in a sequential loop of a "
       "target region",
       cprog(_pragma("#pragma omp target map(to: a) map(tofrom: s, host_flag)")
             + """
  {
    host_flag = omp_is_initial_device();
    for (int k = 0; k < 3; k++) {
      #pragma omp parallel for reduction(+: s)
      for (int i = 0; i < n; i++)
        s += a[i];
    }
  }
""", decls="  int s = 0;\n", check="s == 3 * n * (n + 1) / 2"),
       mutant=(("        s += a[i];", "        s += 1;"),)),
    CP("defaultmap-present-private-array", "omp.clause.defaultmap.present",
       "base.device.private_array",
       "defaultmap(present: aggregate) with a private array on the same "
       "target loop (the arrays the loop maps are present by enter data)",
       cprog("  #pragma omp target enter data map(to: a) map(alloc: b)\n"
             + cploop("t[0] = a[i];\nt[1] = 1;\nt[2] = a[i];\nt[3] = 0;\n"
                      "b[i] = t[0] + t[1] + t[2] + t[3];",
                      "defaultmap(present: aggregate) private(t) "
                      "map(tofrom: host_flag)")
             + "  #pragma omp target exit data map(from: b) map(release: a)\n",
             decls=_C_PRIV),
       mutant=(("t[1] = 1;", "t[1] = 0;"),),
       spec="OpenMP 5.2 §5.8.7, p.161 (defaultmap applies to variables "
            "without an explicitly determined attribute: the private array "
            "is not one)"),
    CP("reduction-derived-array", "omp.clause.reduction",
       "base.device.derived_array",
       "a sum reduction over the members of a mapped array of structs",
       cprog(cploop("s += ps[i].x + ps[i].y;", "map(to: ps) "
                    "map(tofrom: host_flag) reduction(+: s)"),
             helpers="struct pt { int x; int y; };",
             decls="  struct pt ps[n];\n  int s = 0;\n",
             init="  for (int i = 0; i < n; i++) {\n    ps[i].x = i + 1;\n"
                  "    ps[i].y = 2 * (i + 1);\n  }\n",
             check="s == 3 * n * (n + 1) / 2"),
       mutant=(("s += ps[i].x + ps[i].y;", "s += ps[i].x;"),)),
    CP("reduction-complex", "omp.clause.reduction", "base.device.complex",
       "a double _Complex sum reduction",
       cprog(cploop("z += (double)a[i] - (double)a[i] * I;",
                     "map(to: a) map(tofrom: host_flag) reduction(+: z)"),
             includes="#include <complex.h>\n", decls="  double _Complex z = 0;\n",
             check="creal(z) == n * (n + 1) / 2.0 && cimag(z) == "
                   "-n * (n + 1) / 2.0"),
       mutant=(("z += (double)a[i] - (double)a[i] * I;",
                "z += (double)a[i] + (double)a[i] * I;"),)),
]



# (see F_APPS)
C_APPS = [
    CP("update-depend", "omp.directive.target_update", "omp.clause.depend",
       "a target update with a depend clause between two device loops "
       "(then taskwait)",
       cprog("  #pragma omp target enter data map(to: a) map(alloc: b)\n"
             + cploop("b[i] = 2 * a[i] + 1;", "map(tofrom: host_flag)")
             + "  #pragma omp target update from(b) depend(inout: b)\n"
             "  #pragma omp taskwait\n"
             "  #pragma omp target exit data map(delete: a, b)\n"),
       spec=OMP_UPDATE_DEPEND,
       mutant=(("  #pragma omp target update from(b) depend(inout: b)\n",
                ""),),
       mutant_device="copy semantics: without the update the host keeps "
                     "b = 0 (separate memory only)"),
]

C_SPECS = C_BASE + C_DIRECTIVES + C_PAIRS + C_APPS
