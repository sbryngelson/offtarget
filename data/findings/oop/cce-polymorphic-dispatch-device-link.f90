! # Finding (fortran-oop): a type-bound call through a CLASS dummy in device code fails to link (__GET_TYPE_BOUND_PROC)
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0: copy, unified), cce20 (CCE 20.0.2: copy, unified), cce21 (CCE 21.0.3: copy,
!   unified), cce21_4 (CCE 21.0.4: copy, unified); -O2
! - build: ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm/<r>; OpenACC: ftn -h acc)
! - failure: rejected (link_undefined_symbol, the program's own object); OMP_TARGET_OFFLOAD=mandatory
! - observed: `lld: error: undefined symbol: __GET_TYPE_BOUND_PROC` at the device link, every CCE release, both modes: dynamic
!   dispatch of a binding of an abstract type, in a loop, through an override that calls its parent's binding, through a
!   polymorphic pointer, and a binding that calls another binding of its CLASS dummy
! - expected: compiles; `r1= 29` (area of a 3x3 square plus a 4x5 rectangle)
! - rule: every type-bound procedure the region accesses is in a declare target directive (5.2 §1.2.6 p.19 l.1-3; checked by the
!   rules, typebound-declaretarget-001), which is all OpenMP asks of a derived type used in a target region
! - same-compiler control: the same program with the region calling the binding on the TYPE objects, q%area() + rr%area(), instead
!   of area_of's CLASS(shape) dummy (controls/poly-dispatch-static.f90, one change): correct (check=pass) on CCE 19, 20, 21.0.3
!   and 21.0.4 in both modes, in the stored run and the gate's four environments a-d with (c) on another node
!   (results/oop/probe/ctl2.*.poly-dispatch-static.*.jsonl)
! - other families: AFAR correct on all five; GCC 16.2 compiles them and aborts at run time (gcc-polymorphic-dispatch-abort.f90);
!   OpenACC's routine form (unspecified behaviour) fails the same way on CCE with ftn-7066 'Unsupported accelerator code error:
!   Calls -- __GET_TYPE_BOUND_PROC'
! - gate and confirmer: 40 cells, 40 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl);
!   confirmer (results/oop/main/confirm.jsonl): compiler_bug (R10b-own-link-or-hang) 40
! - programs (5): oop-poly-dispatch, oop-poly-dispatch-loop, oop-poly-parent-call, oop-poly-pointer, oop-tbp-nested-call
!   (offload/engine/oop_gen.py; this file is the first one)
! - legality: for the cce cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) and NVHPC 26.9 nvfortran (compile only) (tools/campaigns/oop.py legality, results/oop/main/legality.json)
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
! title: dynamic dispatch of a type-bound procedure in device code fails at the link
! summary: A declare target function calls a type-bound procedure through a CLASS(shape) dummy argument (dynamic dispatch); every
! + procedure bound to the binding is declare target. CCE 19, 20 and 21 fail at the device link with an undefined
! + __GET_TYPE_BOUND_PROC. The same program calling the binding on the non-polymorphic objects themselves (no dispatch) works. AFAR
! + compiles and runs the program correctly.
! control: oop/controls/poly-dispatch-static.f90 the same program; the binding is called on the TYPE objects (statically resolved)
! + instead of through a CLASS dummy
! end site
