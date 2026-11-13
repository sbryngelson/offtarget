! Finding: CCE 19, 20, 21 crash (internal compiler error) on a
! character scalar in the map clause of a standalone target enter data or
! target exit data construct. In this smallest form optcg is killed by
! signal 11 (ftn-2116 "optcg was terminated due to receipt of signal 013:
! Segmentation fault"); in larger programs the same statements give
! "Unhandled expression type in get base or dv mem" (s1 seed 8634; with a
! derived-type variable and an internal subroutine in the program,
! data/evidence/dataenv_probe/ice/a5.f90 gives it on CCE 19, 20 and 21) or
! "unexpected type in TYPE_DEREF" (s1 seed 2952 on CCE 21). Character
! arrays in the same constructs compile (data/evidence/dataenv_probe/ice/c2.f90).
!
! Legal OpenMP 5.2: a character scalar is a variable list item of map
! (5.2 §5.8.3; the enter and exit data constructs take map clauses, §13.6,
! §13.7). (A gfortran -fopenmp accept is no evidence: owner, 2026-10-23.) Expected: "RESULT
! check=pass".
!
! Observed (tuolumne, MI300A, -O2, 2026-10-23, results/t28_probe/icev3.log
! and icev.log; data/evidence/dataenv_probe/ice/c1.f90 is this program):
! - CCE 19.0.0, 20.0.2, 21.0.3: ftn-2116, optcg killed by signal 11; the
!   same with map(delete: xs) on exit data alone
!   (data/evidence/dataenv_probe/ice_char_exit_delete.f90);
! - AFAR amdflang 24.0.0git: compiles and prints "RESULT check=pass".
! - Tioga MI250X (gfx90a, HSA_XNACK=0): CCE 21 the same ICE
!   (results/t28_probe/g90/ice_char_exit_delete.cce21_g90.json).
! Fuzz campaign s1: the "Unhandled expression type in get base or dv mem"
! and "unexpected type in TYPE_DEREF" ICE cells of CCE 19/20/21 (most of
! those programs map character scalars and arrays in target enter data;
! not every one was reduced). The confirmer's reduction of seed 8634
! (results/confirm/drafts/fuzz_s1_8634_cce21_gfx942_unified, 151 -> 76
! lines, ICE site kept) keeps "!$omp target exit data map(delete: xs)" of
! character(len=8) :: xs; this file is reduced from it by hand.
!
! ftn -fopenmp -O2
program p
  implicit none
  character(len=8) :: xs
  xs = 'abcdefgh'
  !$omp target enter data map(to: xs)
  !$omp target exit data map(release: xs)
  print '(a)', 'RESULT check=pass'
end program p
! site:
! title: ftn: internal compiler error (optcg signal 11) for a character scalar in target enter data / exit data
! control: ../vendor/checks/src/other/control/s1-8634-cce21-control.f90 a character array xs(2) instead of a character scalar
! end site
