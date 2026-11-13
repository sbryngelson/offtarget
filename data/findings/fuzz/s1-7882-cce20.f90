! Minimized by compliance.fuzz_min from fuzz seed 7882 (fuzz-3).
! toolchain: cce20 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (exit_status)
! message: Variable not found in present table
! expected: runs to completion (the host run does)
! observed: device: fail exit_status: 1; host reference (afar) checksum=0
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: cce19, cce21
! Finding: CCE 19, 20, 21 end with exit status 1 ("Variable not
! found in present table", the CCE runtime's present check) at a target
! construct with map(present, tofrom: xc) for a character array xc that the
! enclosing target data construct maps (map(to: ... xc ...)); AFAR runs it.
! Legal OpenMP 5.2: the target data construct makes xc present, so the
! present modifier is satisfied (5.2 §5.8.3 p.152 l.25-27: "If a map clause with a
! present map-type-modifier appears on a construct and on entry to the
! region the corresponding list item is not present in the device data
! environment, runtime error termination is performed"); a
! character array is a map list item. Related to s1-8634-cce21.f90 (CCE ICE
! on a character scalar in enter/exit data): another construct and
! symptom (an array, a run-time presence failure).
! Observed (tuolumne, MI300A, -O2, HSA_XNACK=1 and 0, 2026-10-23,
! results/t28_probe/rt/7882-cce20.f90.*.json): CCE 19, 20, 21 exit status 1
! in both modes; AFAR "RESULT checksum=0" (the reference). Reduced from s1
! seed 7882 by tools/campaigns/fuzz.py minimize-one (197 -> 84 lines).
! Shorter form (fix; written by hand from
! the 84-line reduction, which git history keeps): an allocatable
! character(len=4) array alone in target data map(to: xc) and an inner
! target map(present, tofrom: xc) (data/evidence/dataenv_probe/short/c7882_a.f90).
! Observed (tuolumne, MI300A, -O2, 2026-10-23, results/t28_probe/short/
! c7882_a.f90.*.json): CCE 19, 20, 21 exit status 1 ("Variable not found in
! present table") in both modes; AFAR "RESULT check=pass" in both modes.
! With a fixed-size character array (c7882_b) only CCE 19 fails; with
! other items in the target data list (c7882_c, c7882_d) all three fail.
! Expected: "RESULT check=pass".
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 48
  character(len=4), allocatable :: xc(:)
  integer :: i, hf1
  allocate(xc(n))
  do i = 1, n
    xc(i) = achar(65 + mod(i * 33, 26)) // 'b#c'
  end do
  hf1 = -1
  !$omp target data map(to: xc)
    !$omp target map(present, tofrom: xc) map(tofrom: hf1)
      hf1 = merge(1, 0, omp_is_initial_device())
    !$omp end target
  !$omp end target data
  if (hf1 == 0) then
    print '(a)', 'RESULT check=pass'
  else
    print '(a)', 'RESULT check=fail'
  end if
end program p
! site:
! title: ftn: map(present, tofrom: xc) of an allocatable character array mapped by the enclosing target data stops with "Variable
! + not found in present table"
! control: ../vendor/checks/src/other/control/s1-7882-cce20-control.f90 map(tofrom: xc) without the present modifier
! end site
