! Minimized by compliance.fuzz_min from fuzz seed 1540 (fuzz-1).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: ice (afar FIR verification: 'omp.target' op SPMD kernel must capture an 'omp.loop_nest' operation)
! expected: compiles
! observed: internal compiler error: ice: error: verification of lowering to FIR failed
! Legal OpenMP 5.2: offload.engine.rules accepts it (offload.engine.prerun.check, rerun: with the
!   race rule and the restriction checks); NVHPC is no witness: it rejects it
!   (NVFORTRAN-S-0034-Syntax error at or near :); the check's other
!   witness, the AFAR flang front end, is the compiler under test and is not counted; no gfortran
!   or gcc is a legality witness.
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 16, m = 4
  integer :: i, j, lp1
  integer(8) :: cs
  lp1 = 0
  ! fuzz: kernels
  !$omp target parallel do lastprivate(conditional: lp1)
  do i = 1, n
  end do
  !$omp end target parallel do
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: amdflang: "'omp.target' op SPMD kernel must capture an 'omp.loop_nest' operation" for lastprivate(conditional:) on target
! + parallel do
! control: ../vendor/checks/src/fuzz/control/fuzz-1540-afar-control.f90 lastprivate(lp1) without the conditional modifier
! end site
! spec (requirement): the lastprivate clause accepts the conditional modifier on a worksharing loop (the original list item
!   receives the value the last assigning iteration of sequential execution would leave), and on a combined construct with target
!   the list item is mapped tofrom.
! "When the conditional modifier appears on the clause or the list item is an iteration variable of one of the associated loops,
!   if sequential execution of the loop nest would assign a value to the list item then the original list item is assigned the
!   value that the list item would have after sequential execution of the loop nest." (5.2 §5.4.5 p.115 l.16-19)
! "If the target construct is among the constituent constructs and the list item is not the base variable or base pointer of a
!   list item that appears in a map clause, the effect of the lastprivate clause is as if the same list item appears in a map
!   clause with a map-type of tofrom." (5.2 §17.2 p.340 l.27-30)
! spec (this program): target parallel do lastprivate(conditional: lp1) with a loop body that assigns nothing is a legal
!   combined construct that leaves lp1 unchanged; AFAR stops with an internal compiler error in FIR verification (SPMD kernel must
!   capture an omp.loop_nest) instead of compiling it, while lastprivate(lp1) without the modifier compiles.
