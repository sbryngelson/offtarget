! # Finding (fortran-oop): map(tofrom: vk(4)%g(3)) of a component of an array element does not reach the host (copy mode)
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0: copy), cce20 (CCE 20.0.2: copy); -O2
! - build: ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm/<r>; OpenACC: ftn -h acc)
! - failure: wrong_answer (check=fail); OMP_TARGET_OFFLOAD=mandatory
! - observed: `r1= 0 r2= 0` at HSA_XNACK=0: the device's write to vk(4)%g(3) is lost on CCE 19 and 20; the same for a section
!   vk(5)%g(3:5) and a nested element vk(4)%h%c(8); HSA_XNACK=1 correct. CCE 21.0.3 and 21.0.4 lose it in both modes
!   (cce21-element-component-map-lost.f90, same_as)
! - expected: `r1= 74 r2= 74`
! - rule: 5.2 §5.8.3 p.151 l.13 (structure elements and array sections, of an array element, are list items); §5.8.3 p.154 exit
!   step 1a
! - same-compiler control: the whole element map(tofrom: vk(5)) (controls/elemsec-element.f90): correct on every CCE in both modes
!   (results/oop/main/rows.part*.jsonl)
! - other families: AFAR and GCC 16.2 correct; the AOMP lead dtype-syntax-support (the same map forms) fails on CCE
! - gate and confirmer: 6 cells, 6 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl); confirmer
!   (results/oop/main/confirm.jsonl): needs_human (R22-expected-weak) 6; R22-expected-weak means the expected value has one
!   source, the generator's Python model; the values follow from the program's arithmetic (checked by hand), and AFAR, GCC 16.2
!   (gfx90a), GCC 16.2 (sm_80), NVHPC 25.11, NVHPC 26.9 print them on this program
! - programs (3): oop-elemsec-comp-element, oop-elemsec-comp-section, oop-elemsec-nested-element (offload/engine/oop_gen.py;
!   this file
!   is the first one)
! - legality: for the cce cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) and NVHPC 26.9 nvfortran (compile only) (tools/campaigns/oop.py legality, results/oop/main/legality.json)
module oop_m
  implicit none
  integer, parameter :: n = 64
  type dc
    integer :: g(20) = 0
    integer :: i = 0
  end type dc
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2
  type(dc) :: vk(5)
  integer :: l
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  !$omp target map(tofrom: vk(4)%g(3))
  vk(4)%g(3) = 74
  !$omp end target
  r1 = vk(4)%g(3)
  r2 = sum(vk(4)%g)
  ok = .true.
  ok = ok .and. (r1 == 74)
  ok = ok .and. (r2 == 74)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: a component of an array element mapped tofrom does not come back with separate memory
! summary: map(tofrom: vk(4)%g(3)), an element of a component of an element of an array of structures: the target region's write
! + is lost on CCE 19 and 20 when host and device memory are separate. Mapping the whole element vk(5) works. AFAR and GCC are
! + correct.
! control: oop/controls/elemsec-element.f90 the whole array element instead of a component of it
! end site
