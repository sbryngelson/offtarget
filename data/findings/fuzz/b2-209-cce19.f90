! Minimized by compliance.fuzz_min from fuzz seed 209 (fuzz-3).
! toolchain: cce19 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (elision) checksum=16)
! observed: device checksum=0 ran_on_host=0
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: cce20, cce21
module fuzz_mod
  implicit none
contains
end module fuzz_mod
program fuzz_prog
  implicit none
  integer, parameter :: n = 16, m = 3
  type :: rec_t
  end type rec_t
  type :: el_t
  end type el_t
  type(rec_t) :: dr
  type(el_t) :: ds(n)
  integer :: i, j, jj, lp1, acc1
  integer(8) :: cs
  lp1 = 0
  ! fuzz: kernels
  !$omp target simd lastprivate(conditional: lp1) private(acc1, jj)
  do i = 1, n
    acc1 = 0
    if (mod(i, 2) == 0) lp1 = i
  end do
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: ftn: lastprivate(conditional:) on target simd does not imply map(tofrom), value lost
! control: ../vendor/checks/src/fuzz/control/fuzz-b2-209-cce19-control.f90 lp1 also mapped explicitly: map(tofrom: lp1)
! end site
! spec (requirement): on a combined construct that includes target, a list item of a lastprivate clause is mapped as if with
!   map-type tofrom, and with the conditional modifier the original list item receives the value that sequential execution of the
!   loop would leave.
! "If the target construct is among the constituent constructs and the list item is not the base variable or base pointer of a
!   list item that appears in a map clause, the effect of the lastprivate clause is as if the same list item appears in a map
!   clause with a map-type of tofrom." (5.2 §17.2 p.340 l.27-30)
! "When the conditional modifier appears on the clause or the list item is an iteration variable of one of the associated loops,
!   if sequential execution of the loop nest would assign a value to the list item then the original list item is assigned the
!   value that the list item would have after sequential execution of the loop nest." (5.2 §5.4.5 p.115 l.16-19)
! spec (this program): target simd lastprivate(conditional: lp1) implies map(tofrom: lp1), so the host must see lp1 = 16 after
!   the loop; CCE 19, 20 and 21 return 0, and the program is correct when lp1 is also mapped explicitly with map(tofrom: lp1).
