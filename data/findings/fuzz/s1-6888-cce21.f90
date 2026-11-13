! Finding: CCE 19, 20, 21 reject a strided array section in a
! motion clause of target update (ftn-1747 "The stride specified for array
! ... must not be greater than 1. Subarray references in the MAP clause
! must be to contiguous memory").
!
! Legal OpenMP 5.0-5.2: "A stride expression may not be specified unless
! otherwise stated" (5.2 §3.2.5 p.66) and the data-motion clauses state it:
! "The list items may include array sections with stride expressions"
! (5.2 §5.9 p.165); added in 5.0: "The target update construct (see Section
! 13.9) was modified to allow array sections that specify discontiguous
! storage" (5.2 §B.4 p.634). Only the map clause requires contiguous storage
! (5.2 §5.8.3 p.156). CCE claims full OpenMP 5.0 (intro_openmp(7) of 19.0.0,
! 20.0.2, 21.0.3). gfortran 13 rejects it too ("Stride should not be
! specified for array section in TO clause"): a limitation of gfortran, not
! a legality verdict. AFAR prints "error: stride cannot be specified on an
! array section" for strided sections of structure components (e.g.
! gs%k(1:n:2)); in s1 and s1x0 289 AFAR cells carry it and none of them
! agrees (194 compile_reject, 68 run_error, 17 wrong_code, 10 ICE), against
! 54% agree for the cells without it, and 22 of AFAR's 138 present-modifier
! aborts are among them (8 times the overall rate). The message is not
! always fatal; an AFAR defect with strided component sections is likely
! but was not reduced in this task. For a plain array, as here, AFAR is
! silent and correct.
! Expected: "RESULT check=pass" (the odd elements are doubled on the device
! and copied back; the even ones are not checked, since they depend on the
! memory mode).
!
! Observed (tuolumne, MI300A, -O2, HSA_XNACK=1 and 0, 2026-10-23,
! results/t28_probe/strided_update.f90.*.json):
! - CCE 19.0.0, 20.0.2, 21.0.3: compile error ftn-1747 at the target update
!   (21.0.3 words it "... in the MAP clause must not be greater than 1.");
! - AFAR amdflang 24.0.0git: compiles, "RESULT check=pass" in both modes.
! - Tioga MI250X (gfx90a, HSA_XNACK=0): the same; CCE 19/20/21 reject,
!   AFAR passes (results/t28_probe/g90/strided_update.cce21_g90.json).
! Fuzz campaign s1: 988 CCE cells (s1 and s1x0) fail on this diagnostic,
! verdict compiler_bug (rule R11 where AFAR compiles the program, decision
! D1 where every family rejects the program at different statements).
! Representative: s1 seed 6888 on cce21 (the confirmer's reduction,
! results/confirm/drafts/fuzz_s1_6888_cce21_gfx942_unified, keeps
! "!$omp target update to(gs%k(1:n:2))"); reproducer written by hand from
! it (data/evidence/dataenv_probe/strided_update.f90).
!
! ftn -fopenmp -O2 (cce19/cce20/cce21 recipes, offload/engine/toolchains.py)
program p
  implicit none
  integer, parameter :: n = 16
  integer :: a(n), i
  logical :: ok
  a = 0
  !$omp target enter data map(to: a)
  do i = 1, n
    a(i) = i
  end do
  !$omp target update to(a(1:n:2))
  !$omp target
  do i = 1, n
    a(i) = 2 * a(i)
  end do
  !$omp end target
  !$omp target exit data map(from: a)
  ok = .true.
  do i = 1, n
    ! the even elements are 0 with separate memory and 2 * i with
    ! shared memory: only the updated ones are checked
    if (mod(i, 2) == 1) ok = ok .and. a(i) == 2 * i
  end do
  if (ok) then
    print '(a)', 'RESULT check=pass'
  else
    print '(a)', 'RESULT check=fail'
  end if
end program p
! site:
! title: ftn: target update to(a(1:n:2)) rejected (ftn-1747, stride must not be greater than 1)
! control: ../vendor/checks/src/other/control/s1-6888-cce21-control.f90 to(a(1:n)), without the stride (all elements updated)
! end site
