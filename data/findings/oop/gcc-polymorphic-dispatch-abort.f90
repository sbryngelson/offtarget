! # Finding (fortran-oop): a type-bound call through a CLASS dummy in device code aborts at run time
!
! - toolchains and modes that fail: gcc_g90 (GCC 16.2 (gfx90a): copy), gcc_sm80 (GCC 16.2 (sm_80): copy); -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90);
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic (gcc_sm80)
! - failure: crash (SIGABRT); OMP_TARGET_OFFLOAD=mandatory
! - observed: the program compiles and aborts (SIGABRT, a backtrace without symbols) in every run
! - expected: `r1= 29`
! - rule: 5.2 §1.2.6 p.19 l.1-3 (every type-bound procedure accessed is declare target)
! - same-compiler control: the same program with the region calling the binding on the TYPE objects instead of through area_of's
!   CLASS(shape) dummy (controls/poly-dispatch-static.f90, one change): `r1= 29`, check=pass in the stored run and the gate's four
!   environments a-d on both GPUs (results/oop/probe/ctl2.*.poly-dispatch-static.gcc.jsonl, (c) on another Tioga node;
!   results/oop/probe/ctl2.*.poly-dispatch-static.wt-gcc_sm80.jsonl, (c) on another A100)
! - other families: AFAR correct; CCE fails at the device link (cce-polymorphic-dispatch-device-link.f90)
! - gate and confirmer: 8 cells, 8 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl); confirmer
!   (results/oop/main/confirm.jsonl): compiler_bug (R20-runtime-bug) 4, needs_human (R22-expected-weak) 4; R22-expected-weak means
!   the expected value has one source, the generator's Python model; the values follow from the program's arithmetic (checked by
!   hand), and AFAR print them on this program
! - programs (4): oop-poly-dispatch, oop-poly-dispatch-loop, oop-poly-parent-call, oop-tbp-nested-call (offload/engine/oop_gen.py;
!   this file is the first one)
! - legality: for the gcc cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) and a CCE compile and NVHPC 26.9 nvfortran (compile only) (tools/campaigns/oop.py legality,
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
! title: dynamic dispatch of a type-bound procedure in device code aborts
! summary: A declare target function calls a type-bound procedure through a CLASS dummy argument (every bound procedure declare
! + target). GCC 16.2 compiles it and the program aborts at run time. The same program calling the binding on the non-polymorphic
! + objects works. AFAR runs it correctly.
! control: oop/controls/poly-dispatch-static.f90 the same program; the binding is called on the TYPE objects (statically resolved)
! + instead of through a CLASS dummy
! end site
