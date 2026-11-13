! Minimized by compliance.fuzz_min from fuzz seed 591 (fuzz-1).
! toolchain: cce19 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: ice (ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!!)
! expected: compiles
! observed: internal compiler error: ice: INTERNAL COMPILER ERROR:  "Unhandled contexts must be fixed!!!
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: cce20, cce21
program fuzz_prog
  implicit none
  integer, parameter :: n = 128, m = 8
  integer :: o1(n, m)
  integer :: i, j, lp1, t1
  integer(8) :: cs
  o1 = 0
  lp1 = 0
  ! fuzz: kernels
  !$omp target
    !$omp teams distribute simd lastprivate(lp1) private(t1) nontemporal(o1)
    do i = n, 1, -1
      do j = 1, m
        t1 = 0
        lp1 = 0
      end do
    end do
    !$omp end teams distribute simd
  !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: ftn: internal compiler error "Unhandled contexts must be fixed!!!" for teams distribute simd with lastprivate, private and
! + nontemporal
! control: ../vendor/checks/src/fuzz/control/fuzz-591-cce19-control.f90 nontemporal(o1) removed
! end site
! spec (requirement): the nontemporal clause is permitted on simd (and so on a composite construct with simd as a leaf), and the
!   lastprivate clause applies to every leaf construct that permits it; a clause on a composite construct must apply to at least
!   one leaf construct.
! "The nontemporal clause specifies that accesses to the storage locations to which the list items refer have low temporal
!   locality across the iterations in which those storage locations are accessed. The list items of the nontemporal clause may
!   also appear as list items of data-environment attribute clauses." (5.2 §10.4.1 p.236 l.21-24)
! "The effect of the lastprivate clause is as if it is applied to all leaf constructs that permit the clause. If the parallel
!   construct is among the constituent constructs and the list item is not also" (5.2 §17.2 p.340 l.21-22)
! spec (this program): teams distribute simd with lastprivate(lp1), private(t1) and nontemporal(o1) is a legal composite
!   construct; CCE 19, 20 and 21 stop with an internal compiler error (Unhandled contexts must be fixed), and compile it when
!   nontemporal(o1) is removed.
