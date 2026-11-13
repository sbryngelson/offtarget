! Finding: CCE 20 rejects the enter clause of declare
! target (ftn-1725 "Unexpected syntax while parsing the DIRECTIVE statement :
! "INDIRECT, LINK, TO or DEVICE_TYPE" was expected but found "E"").
!
! Legal OpenMP 5.2: enter is the 5.2 name of the declare target clause that
! 5.0/5.1 spell to ("The clause-name to may be used as a synonym for the
! clause-name enter. This use has been deprecated.", 5.2 §5.8.4 p.158; "The
! enter clause was added as a synonym for the to clause on the declare
! target directive", 5.2 Appendix B.2 p.627). CCE 20 claims it: the CCE
! 20.0.0 release notes list "[5.2] ... misc. new syntax allowed by
! specification (e.g. `declare target`, `ordered`, metadirective)", and
! the only new 5.2 syntax of declare target is enter (catalog/omp/
! claims.yaml; maintainer reading). A claimed form
! rejected: compiler_bug. CCE 19 makes no such claim (its identical
! rejection is unsupported, rule R11c); CCE 21 claims enter (Fortran) and
! accepts it.
!
! Observed (tuolumne, MI300A, -O2, HSA_XNACK=1 and 0, 2026-10-23,
! results/t28_probe/dt_enter.f90.*.json): CCE 20.0.2 ftn-1725 at the enter
! keyword (dt_enter.f90 line 13, column 24); CCE 19.0.0 the same
! (unsupported, no claim); CCE 21.0.3 and AFAR amdflang 24.0.0git compile
! it and print "RESULT check=pass" in both modes. Tioga MI250X (gfx90a):
! the catalog program omp52-clause-enter is rejected the same way by
! cce20_g90 (results/confirm/batch_full.jsonl, R11).
! Fuzz campaign s1: CCE 20's 7,099 enter rejections (s1 and s1x0; 5,588
! s1 programs use enter) are compiler_bug: 4,502 by rule R11 (another
! family compiles the program) and 2,597 by decision D9 (the other
! families reject the program at other statements). Representative: s1
! seed 6760 (116 lines, AFAR and CCE 21 print the model value); this
! reproducer is written by hand (data/evidence/dataenv_probe/dt_enter.f90).
! Expected: "RESULT check=pass".
!
! ftn -fopenmp -O2 (cce20 recipe, offload/engine/toolchains.py)
module m
  implicit none
  integer, parameter :: n = 16
  integer :: g(n) = 1
  !$omp declare target enter(g)
end module m
program p
  use m
  implicit none
  integer :: i
  logical :: ok
  !$omp target
  do i = 1, n
    g(i) = g(i) + i
  end do
  !$omp end target
  !$omp target update from(g)
  ok = .true.
  do i = 1, n
    ok = ok .and. g(i) == 1 + i
  end do
  if (ok) then
    print '(a)', 'RESULT check=pass'
  else
    print '(a)', 'RESULT check=fail'
  end if
end program p
! site:
! title: ftn rejects the enter clause of declare target (the OpenMP 5.2 name of the to clause)
! control: ../vendor/checks/src/other/control/s1-6760-cce20-control.f90 declare target to(g), the deprecated spelling, instead of
! + enter(g)
! end site
