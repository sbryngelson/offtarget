! # Finding (fortran-oop): mapping the allocatable component of an array element aborts: 'overlaps present region'
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0: copy, unified), cce20 (CCE 20.0.2: copy, unified), cce21 (CCE 21.0.3: copy,
!   unified), cce21_4 (CCE 21.0.4: copy, unified); -O2
! - build: ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm/<r>; OpenACC: ftn -h acc)
! - failure: run_error (exit 1); OMP_TARGET_OFFLOAD=mandatory
! - observed: `CRAY_ACC_ERROR - Host region ... overlaps present region ... but is not contained for 't$2(:)'` at the target
!   construct, every CCE release, both modes. Mapping the whole component v(2)%a instead of its section
!   (controls/section-element-whole-component.f90) stops with the same message in every environment a-d
!   (results/oop/probe/ctl2.*.section-element-whole-component.*.jsonl): the defect is the component of an array element, not
!   the section
! - expected: `r1= 2880 r2= 2080`
! - rule: 5.2 §5.8.3 p.151 l.13; the construct maps one list item, so no earlier storage overlaps it (§5.8.3 p.156 l.19-22 is
!   about storage present before the construct)
! - same-compiler control: the same program mapping the whole array v (controls/section-element-whole-array.f90, one change:
!   map(tofrom: v), whose default mapper maps each element's component): correct (check=pass) on CCE 19, 20, 21.0.3 and 21.0.4 in
!   both modes, in the stored run and the gate's four environments a-d with (c) on another node
!   (results/oop/probe/ctl2.*.section-element-whole-array.*.jsonl)
! - other families: AFAR and GCC 16.2 correct; related to harvest/cce-c-implicit-struct-map-partly-present.c (the same runtime
!   message for a structure whose members are present)
! - gate and confirmer: 8 cells, 8 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl); confirmer
!   (results/oop/main/confirm.jsonl): needs_human (R22-expected-weak) 8; R22-expected-weak means the expected value has one
!   source, the generator's Python model; the values follow from the program's arithmetic (checked by hand), and AFAR, GCC 16.2
!   (gfx90a), GCC 16.2 (sm_80), NVHPC 25.11, NVHPC 26.9 print them on this program
! - programs (1): oop-section-element (offload/engine/oop_gen.py; this file is the first one)
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
  type(vec) :: v(3)
  integer :: i, k
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  do k = 1, 3
    allocate(v(k)%a(n))
    v(k)%n = n
    do i = 1, n
      v(k)%a(i) = i
    end do
  end do
  !$omp target teams distribute parallel do map(tofrom: v(2)%a(5:20))
  do i = 5, 20
    v(2)%a(i) = v(2)%a(i) + 50
  end do
  r1 = sum(v(2)%a)
  r2 = sum(v(1)%a)
  ok = .true.
  ok = ok .and. (r1 == 2880)
  ok = ok .and. (r2 == 2080)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: mapping the allocatable component of an array element aborts as a partial overlap
! summary: map(tofrom: v(2)%a(5:20)) (v an array of structures with an allocatable component; the whole component v(2)%a too)
! + aborts at the target construct on CCE 19, 20 and 21 in both memory modes: the runtime reports that the host region overlaps a
! + present region but is not contained in it. Mapping the whole array v works. AFAR and GCC run it correctly.
! control: oop/controls/section-element-whole-array.f90 the same program mapping the whole array v
! end site
