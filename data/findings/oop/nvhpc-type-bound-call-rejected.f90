! # Finding (fortran-oop): type-bound calls in device code rejected: 'Call to type-bound procedures are not allowed on device'
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11: managed, separate), nvhpc269 (NVHPC 26.9: managed, separate); -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -O2 (managed: -gpu=mem:managed)
! - failure: rejected (diagnostic); OMP_TARGET_OFFLOAD=mandatory
! - observed: `NVFORTRAN-F-1252-Call to type-bound procedures are not allowed on device - scale_i$tbp`, NVHPC 25.11 and 26.9, both
!   modes; the other binding calls compile and then fail at run time (linked to
!   catalog/nvhpc-flang-type-bound-kernel-missing.f90). The claim rests on NVHPC's own message; its user guide does not mention
!   type-bound procedures in device code
! - expected: compiles; `r1= 180`
! - rule: 5.2 §1.2.6 p.19 l.1-3 (type-bound procedures in a target region are allowed when declare target)
! - other families: AFAR, CCE and GCC 16.2 correct on all three
! - gate and confirmer: 12 cells, 12 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl);
!   confirmer (results/oop/main/confirm.jsonl): compiler_bug (R11-compile-rejection) 6, needs_human (R12b-compile-undecided) 6
! - programs (3): oop-tbp-generic, oop-tbp-loop, oop-assignfinal-tbp-assign (offload/engine/oop_gen.py; this file is the first one)
! - legality: for the nvhpc cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) and a CCE compile (tools/campaigns/oop.py legality,
!   results/oop/main/legality.json)
module oop_m
  implicit none
  integer, parameter :: n = 64
  type vec3
    integer :: x = 0, y = 0, z = 0
  contains
    procedure :: norm2 => v_norm2
    procedure, nopass :: twice => v_twice
    procedure :: scale_i, scale_ij
    generic :: scale => scale_i, scale_ij
  end type vec3
contains
  integer function v_norm2(s)
    !$omp declare target
    class(vec3), intent(in) :: s
    v_norm2 = s%x * s%x + s%y * s%y + s%z * s%z
  end function v_norm2
  integer function v_twice(k)
    !$omp declare target
    integer, intent(in) :: k
    v_twice = 2 * k
  end function v_twice
  subroutine scale_i(s, k)
    !$omp declare target
    class(vec3), intent(inout) :: s
    integer, intent(in) :: k
    s%x = s%x * k
    s%y = s%y * k
    s%z = s%z * k
  end subroutine scale_i
  subroutine scale_ij(s, a, b)
    !$omp declare target
    class(vec3), intent(inout) :: s
    integer, intent(in) :: a, b
    s%x = s%x * a * b
    s%y = s%y * a * b
    s%z = s%z * a * b
  end subroutine scale_ij
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1
  type(vec3) :: v
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  v%x = 1
  v%y = 2
  v%z = 3
  !$omp target map(tofrom: v)
  call v%scale(3)
  call v%scale(2, 5)
  !$omp end target
  r1 = v%x + v%y + v%z
  ok = .true.
  ok = ok .and. (r1 == 180)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: type-bound procedure calls in device code are rejected
! summary: Calls of type-bound procedures (a generic binding, a binding in a loop, a type-bound defined assignment) in a target
! + region are rejected by NVHPC 25.11 and 26.9: 'Call to type-bound procedures are not allowed on device'. Every procedure involved
! + is declare target. AFAR, CCE and GCC compile and run them correctly.
! end site
