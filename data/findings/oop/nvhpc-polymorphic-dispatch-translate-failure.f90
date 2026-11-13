! # Finding (fortran-oop): dispatch through a CLASS dummy in device code: 'Compiler failed to translate accelerator region'
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11: managed, separate), nvhpc269 (NVHPC 26.9: managed, separate); -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -O2 (managed: -gpu=mem:managed)
! - failure: ice (a compiler failure: failed to translate); OMP_TARGET_OFFLOAD=mandatory
! - observed: `NVFORTRAN-W-0155-Compiler failed to translate accelerator region (see -Minfo messages): No device symbol for
!   address reference`, then the compile fails, NVHPC 25.11 and 26.9, both modes. A compiler failure: the message does not say the
!   feature is unsupported and the user guide does not mention it
! - expected: compiles; `r1= 29`
! - rule: 5.2 §1.2.6 p.19 l.1-3 (every type-bound procedure accessed is declare target)
! - other families: AFAR correct; CCE fails at the link (cce-polymorphic-dispatch-device-link.f90); GCC aborts at run time
!   (gcc-polymorphic-dispatch-abort.f90)
! - gate and confirmer: 12 cells, 12 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl);
!   confirmer (results/oop/main/confirm.jsonl): compiler_bug (R10-compile-ice) 12
! - programs (3): oop-poly-dispatch, oop-poly-dispatch-loop, oop-poly-parent-call (offload/engine/oop_gen.py; this file is the first
!   one)
! - legality: for the nvhpc cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) and a CCE compile (tools/campaigns/oop.py legality,
!   results/oop/main/legality.json)
module oop_m
  implicit none
  integer, parameter :: n = 64
  type, abstract :: shape
    integer :: id = 0
  contains
    procedure(area_if), deferred :: area
  end type shape
  abstract interface
    integer function area_if(s)
      import :: shape
      class(shape), intent(in) :: s
    end function area_if
  end interface
  type, extends(shape) :: sq
    integer :: side = 0
  contains
    procedure :: area => sq_area
  end type sq
  type, extends(shape) :: rect
    integer :: w = 0, h = 0
  contains
    procedure :: area => rect_area
  end type rect
contains
  integer function sq_area(s)
    !$omp declare target
    class(sq), intent(in) :: s
    sq_area = s%side * s%side
  end function sq_area
  integer function rect_area(s)
    !$omp declare target
    class(rect), intent(in) :: s
    rect_area = s%w * s%h
  end function rect_area
  integer function area_of(s)
    !$omp declare target
    class(shape), intent(in) :: s
    area_of = s%area()
  end function area_of
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1
  type(sq) :: q
  type(rect) :: rr
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  q%side = 3
  rr%w = 4
  rr%h = 5
  !$omp target map(tofrom: q, rr) map(from: r1)
  r1 = area_of(q) + area_of(rr)
  !$omp end target
  ok = .true.
  ok = ok .and. (r1 == 29)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: dynamic dispatch of a type-bound procedure in device code makes the compiler fail
! summary: A declare target function calls a type-bound procedure through a CLASS dummy argument. NVHPC 25.11 and 26.9 stop with
! + 'Compiler failed to translate accelerator region'. AFAR runs it correctly.
! end site
