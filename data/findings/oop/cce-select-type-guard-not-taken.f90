! # Finding (fortran-oop): SELECT TYPE in a declare target procedure takes CLASS DEFAULT for mapped objects of extended types
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0: copy, unified), cce20 (CCE 20.0.2: copy, unified), cce21 (CCE 21.0.3: copy,
!   unified), cce21_4 (CCE 21.0.4: copy, unified); -O2
! - build: ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm/<r>; OpenACC: ftn -h acc)
! - failure: wrong_answer (check=fail); OMP_TARGET_OFFLOAD=mandatory
! - observed: `r1= 0 r2= 0 r3= -1`: the calls with an ext1 and an ext2 actual take the CLASS DEFAULT branch (oop-poly-select-type,
!   every CCE release, both modes); a CLASS(*) dummy classifies every derived-type actual as CLASS DEFAULT (oop-unlimited-classify
!   `r1= 0`, every CCE, both modes); with intrinsic and derived actuals of a CLASS(*) dummy CCE 19 misses only the derived-type
!   actual (oop-unlimited-select-type `r1= 42 r2= 20 r3= 5`, expected r3= 7; CCE 20 and 21 correct). All three programs map
!   non-polymorphic objects from the host and dispatch on them in the device procedure
! - expected: `r1= 10 r2= 100 r3= -1` (the TYPE IS (ext1) and TYPE IS (ext2) branches run for those actuals)
! - rule: Fortran 2018 11.1.11 (a TYPE IS guard is chosen when the dynamic type of the selector is that type); a CLASS dummy
!   argument of a declare target procedure is not restricted by OpenMP (5.2 §1.2.6 p.19 l.1-3: the type-bound procedures accessed
!   must be declare target; this program has none)
! - same-compiler control: the same three calls on the host (controls/host-select-type.f90 and
!   controls/host-class-star-select-type.f90: correct on every CCE release in both modes, results/oop/probe/controls.jsonl)
! - other families: AFAR correct on all three programs; GCC 16.2 rejects them at compile time (a separate finding:
!   gcc-vtab-not-marked-for-offload.f90)
! - gate and confirmer: 18 cells, 18 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl);
!   confirmer (results/oop/main/confirm.jsonl): compiler_bug (R20-runtime-bug) 18
! - programs (3): oop-poly-select-type, oop-unlimited-classify, oop-unlimited-select-type (offload/engine/oop_gen.py; this file
!   is the
!   first one)
! - legality: for the cce cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) (tools/campaigns/oop.py legality, results/oop/main/legality.json)
module oop_m
  implicit none
  integer, parameter :: n = 64
  type base_t
    integer :: a = 0
  end type base_t
  type, extends(base_t) :: ext1
    integer :: u = 0
  end type ext1
  type, extends(base_t) :: ext2
    integer :: v = 0
  end type ext2
contains
  subroutine bump(s)
    !$omp declare target
    class(base_t), intent(inout) :: s
    select type (s)
      type is (ext1)
        s%u = s%u + 10
      type is (ext2)
        s%v = s%v + 100
      class default
        s%a = -1
    end select
  end subroutine bump
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2, r3
  type(ext1) :: e1
  type(ext2) :: e2
  type(base_t) :: b0
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  !$omp target map(tofrom: e1, e2, b0)
  call bump(e1)
  call bump(e2)
  call bump(b0)
  !$omp end target
  r1 = e1%u
  r2 = e2%v
  r3 = b0%a
  ok = .true.
  ok = ok .and. (r1 == 10)
  ok = ok .and. (r2 == 100)
  ok = ok .and. (r3 == -1)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0)', 'r3= ', r3
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: SELECT TYPE in a device procedure takes the CLASS DEFAULT branch for mapped objects
! summary: A declare target subroutine with a CLASS(base_t) dummy argument and a SELECT TYPE construct, called in a target region
! + with objects of two extended types, should run the matching TYPE IS branch. CCE 19, 20 and 21 run the CLASS DEFAULT branch for
! + every object (the same with a CLASS(*) dummy). The same calls on the host take the right branches. AFAR runs the right branches.
! control: oop/controls/host-select-type.f90 the same calls of the same procedure on the host
! end site
