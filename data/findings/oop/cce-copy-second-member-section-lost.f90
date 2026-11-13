! # Finding (fortran-oop): two member sections of one structure on one map clause: the second is not copied back (copy mode)
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0: copy), cce20 (CCE 20.0.2: copy), cce21 (CCE 21.0.3: copy), cce21_4 (CCE
!   21.0.4: copy); -O2
! - build: ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm/<r>; OpenACC: ftn -h acc)
! - failure: wrong_answer (check=fail); OMP_TARGET_OFFLOAD=mandatory
! - observed: `r1= 18 r2= 0` at HSA_XNACK=0 on every CCE release: f%b(3:6) comes back, f%d(3:6) does not; with two structures the
!   second member of each is lost (`r1= 18 r2= 54`, expected 54 126); HSA_XNACK=1 correct
! - expected: `r1= 18 r2= 36`
! - rule: 5.2 §5.8.3 p.152 l.28-31 (list items with the same containing structure form one mappable storage block); §5.8.3 p.154
!   exit step 1a (each tofrom list item is copied back); §13.8 p.286 l.27-28 (every referenced element is mapped)
! - same-compiler control: one member section (controls/section-fixed.f90): correct on every CCE in both modes
!   (results/oop/main/rows.part*.jsonl)
! - other families: AFAR and GCC 16.2 correct; the AOMP leads derived-type-member-array-map-3 and
!   double-derived-type-double-member-array-map also fail on CCE
! - gate and confirmer: 8 cells, 8 confirmed in the gate's four environments (a-d; results/oop/main/gate_reruns*.jsonl); confirmer
!   (results/oop/main/confirm.jsonl): needs_human (R22-expected-weak) 8; R22-expected-weak means the expected value has one
!   source, the generator's Python model; the values follow from the program's arithmetic (checked by hand), and AFAR, GCC 16.2
!   (gfx90a), GCC 16.2 (sm_80), NVHPC 25.11, NVHPC 26.9 print them on this program
! - programs (2): oop-elemsec-two-members, oop-elemsec-two-structs (offload/engine/oop_gen.py; this file is the first one)
! - legality: for the cce cells: the rules (offload.engine.rules, with the fortran-oop restrictions) and AFAR's flang front end
!   (-fsyntax-only) and NVHPC 26.9 nvfortran (compile only) (tools/campaigns/oop.py legality, results/oop/main/legality.json)
module oop_m
  implicit none
  integer, parameter :: n = 64
  type da
    integer :: b(10) = 0
    integer :: d(10) = 0
  end type da
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2
  type(da) :: f
  integer :: l
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  !$omp target map(tofrom: f%b(3:6), f%d(3:6))
  do l = 3, 6
    f%b(l) = l
    f%d(l) = 2 * l
  end do
  !$omp end target
  r1 = sum(f%b)
  r2 = sum(f%d)
  ok = .true.
  ok = ok .and. (r1 == 18)
  ok = ok .and. (r2 == 36)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
! site:
! title: the second of two member sections of a structure is not copied back
! summary: map(tofrom: f%b(3:6), f%d(3:6)) on one target construct: the device's writes to f%d do not come back with CCE 19, 20
! + and 21 when memory is separate (f%b does). One member section works; unified memory works; AFAR and GCC are correct.
! control: oop/controls/section-fixed.f90 one member section instead of two
! end site
