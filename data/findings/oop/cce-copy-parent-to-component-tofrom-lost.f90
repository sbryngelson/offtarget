! # Finding (fortran-oop): map(to: x) map(tofrom: x%a): the allocatable component is not copied back (copy mode)
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0: copy), cce20 (CCE 20.0.2: copy), cce21 (CCE 21.0.3: copy), cce21_4 (CCE
!   21.0.4: copy); -O2
! - build: ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm/<r>; OpenACC: ftn -h acc)
! - failure: wrong_answer (check=fail); OMP_TARGET_OFFLOAD=mandatory
! - observed: `r1= 2080` (the host values) at HSA_XNACK=0 on every CCE release; HSA_XNACK=1 correct
! - expected: `r1= 2528`
! - rule: 5.2 §5.8.3 p.156 l.6-7 (a structure and its element may both be list items); the component is mapped tofrom, so it is
!   copied back on exit (§5.8.3 p.154 exit step 1a)
! - same-compiler control: the same program without map(to: x) (controls/parent-and-comp-component-only.f90, one change): correct
!   (check=pass) on CCE 19, 20, 21.0.3 and 21.0.4 in both modes, in the stored run and the gate's four environments a-d with (c)
!   on another node (results/oop/probe/ctl2.*.parent-and-comp-component-only.*.jsonl)
! - other families: AFAR and GCC 16.2 correct
! - gate and confirmer: 4 cells, 4 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl); confirmer
!   (results/oop/main/confirm.jsonl): needs_human (R22-expected-weak) 4; R22-expected-weak means the expected value has one
!   source, the generator's Python model; the values follow from the program's arithmetic (checked by hand), and AFAR, GCC 16.2
!   (gfx90a), GCC 16.2 (sm_80), NVHPC 25.11, NVHPC 26.9 print them on this program
! - programs (1): oop-alloccomp-parent-and-comp (offload/engine/oop_gen.py; this file is the first one)
! - legality: for the cce cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) and NVHPC 26.9 nvfortran (compile only) (tools/campaigns/oop.py legality, results/oop/main/legality.json)
module oop_m
  implicit none
  integer, parameter :: n = 64
  type vec
    integer :: n = 0
    integer, allocatable :: a(:)
  end type vec
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1
  type(vec) :: x
  integer :: i
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  allocate(x%a(n))
  x%n = n
  do i = 1, n
    x%a(i) = i
  end do
  !$omp target teams distribute parallel do map(to: x) map(tofrom: x%a)
  do i = 1, n
    x%a(i) = x%a(i) + 7
  end do
  r1 = sum(x%a)
  ok = .true.
  ok = ok .and. (r1 == 2528)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: map(to: x) with map(tofrom: x%a) loses the component's copy back
! summary: With map(to: x) map(tofrom: x%a) on one target construct (x a structure with an allocatable array component a), the
! + device's writes to x%a do not come back to the host with CCE 19, 20 and 21 when memory is separate. Mapping x%a alone works.
! + AFAR and GCC are correct.
! control: oop/controls/parent-and-comp-component-only.f90 the same program without map(to: x)
! end site
