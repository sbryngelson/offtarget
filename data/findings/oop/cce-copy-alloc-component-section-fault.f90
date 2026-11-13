! # Finding (fortran-oop): map(tofrom: x%a(9:40)) of an allocatable component section faults on the device in copy mode
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0: copy), cce20 (CCE 20.0.2: copy), cce21 (CCE 21.0.3: copy), cce21_4 (CCE
!   21.0.4: copy); -O2
! - build: ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm/<r>; OpenACC: ftn -h acc)
! - failure: crash / run_error; OMP_TARGET_OFFLOAD=mandatory
! - observed: HSA_XNACK=0: CCE 19 and 20 `Memory access fault by GPU ... on address (nil)` (SIGABRT); CCE 21.0.3 and 21.0.4
!   `hipStreamSynchronize returned hipErrorIllegalAddress` (exit 1); HSA_XNACK=1 correct. Also a section of an allocatable
!   component of a nested structure and of an allocatable array-of-structures component of an allocatable scalar
! - expected: `r1= 34080 r2= 8`
! - rule: 5.2 §5.8.3 p.151 l.13 (structure elements and array sections are list items); the region references only the mapped
!   elements (§5.8.3 p.157 l.21-22)
! - same-compiler control: the same program mapping the whole component (controls/section-alloc-whole-component.f90, one change):
!   correct (check=pass) on CCE 19, 20, 21.0.3 and 21.0.4 in both modes, in the stored run and the gate's four environments a-d
!   with (c) on another node (results/oop/probe/ctl2.*.section-alloc-whole-component.*.jsonl)
! - other families: AFAR and GCC 16.2 correct; the AOMP fortran-map-tests leads of harvest 2
!   (dtype-allocatable-array-with-bounds-map, nested-dtype-allocatable-array-with-bounds-map, dtype-array-of-dtype-member-map-v5)
!   also fail on CCE
! - gate and confirmer: 12 cells, 12 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl);
!   confirmer (results/oop/main/confirm.jsonl): needs_human (R22-expected-weak) 12; R22-expected-weak means the expected value has
!   one source, the generator's Python model; the values follow from the program's arithmetic (checked by hand), and AFAR, GCC
!   16.2 (gfx90a), GCC 16.2 (sm_80), NVHPC 25.11, NVHPC 26.9 print them on this program
! - programs (3): oop-section-alloc, oop-section-nested, oop-elemsec-alloc-parent (offload/engine/oop_gen.py; this file is the first
!   one)
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
  integer :: r1, r2
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
  !$omp target teams distribute parallel do map(tofrom: x%a(9:40))
  do i = 9, 40
    x%a(i) = x%a(i) + 1000
  end do
  r1 = sum(x%a)
  r2 = x%a(8)
  ok = .true.
  ok = ok .and. (r1 == 34080)
  ok = ok .and. (r2 == 8)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: mapping a section of an allocatable component faults on the GPU with separate memory
! summary: map(tofrom: x%a(9:40)), a section of an allocatable array component, on a target teams distribute parallel do faults on
! + the GPU (memory access fault, illegal address) with CCE 19, 20 and 21 when host and device memory are separate. Mapping the
! + whole component works; unified memory works.
! control: oop/controls/section-alloc-whole-component.f90 the same program; the whole component x%a instead of the section
! end site
